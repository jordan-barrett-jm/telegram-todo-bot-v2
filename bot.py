from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import os
from openai import OpenAI
from openai import AssistantEventHandler
from typing_extensions import override
from helper_functions import *
import asyncio
import time
import tempfile
import traceback

# Load environment variables from .env file
load_dotenv()

# Get the token from environment variables
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
ALLOWED_CHATS = os.getenv("ALLOWED_CHATS").split(",")
assistant_id = os.getenv("OPENAI_ASSISTANT_ID")
client = OpenAI()
run_id = None
tool_calls = []

def get_or_create_thread(chat_id):
    if str(chat_id) not in ALLOWED_CHATS:
        logging.error(f"User from chat with id {chat_id} attempted to initiate an unauthorized message")
        raise Exception("You are not allowed to use this bot")
    conn = create_connection()
    if conn is not None:
        try:
            c = conn.cursor()
            
            # Look for the thread ID given the chat ID
            c.execute("SELECT thread_id FROM chats WHERE chat_id = ?", (chat_id,))
            result = c.fetchone()
            
            if result:
                # If the thread ID is found in the database, return it
                thread_id = result[0]
                logging.info(f"Existing thread found for chat_id {chat_id}")
            else:
                # If not, create a new thread and thread ID, save it to the DB and return the thread
                new_thread = client.beta.threads.create()
                thread_id = new_thread.id
                c.execute("INSERT INTO chats (chat_id, thread_id) VALUES (?, ?)", (chat_id, thread_id))
                conn.commit()
                logging.info(f"New thread created for chat_id {chat_id}")
            
            conn.close()
            return thread_id
        except Error as e:
            logging.error(f"Database error: {e}")
            if conn:
                conn.close()
            return None
    else:
        logging.error("Error! Cannot create the database connection.")
        return None

# Create an event handler class to manage streaming events
class MyEventHandler(AssistantEventHandler):
    @override
    def on_text_created(self, text) -> None:
        global run_id
        run_id = self.current_run.id
      
    @override
    def on_text_delta(self, delta, snapshot):
        global run_id
        run_id = self.current_run.id

    def on_tool_call_done(self, tool_call):
        global run_id
        global tool_calls
        print("Added tool call to list...")
        tool_calls.append(tool_call)
        run_id = self.current_run.id
        

    def on_tool_call_delta(self, delta, snapshot):
        global run_id
        run_id = self.current_run.id
        if delta.type == 'function':
            if delta.function.arguments:
                print(delta.function.arguments, end="", flush=True)
    
    def on_message_done(self, message):
        global run_id
        run_id = self.current_run.id

def get_run_status(thread_id):
    run = client.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=run_id
            )
    run_status = run.status
    return run_status

async def stream_assistant_response(thread_id, message):
    global tool_calls
    global run_id
    tool_calls = []
    with client.beta.threads.runs.stream(
        thread_id=thread_id,
        assistant_id=assistant_id,
        event_handler=MyEventHandler(),
    ) as stream:
        stream.until_done()
    run_status = get_run_status(thread_id)
    while run_status in ('queued', 'in_progress', 'requires_action'):
        if run_status == 'requires_action':
            try:
                tool_outputs = await executeToolCalls(tool_calls)
                tool_calls = []
                with client.beta.threads.runs.submit_tool_outputs_stream(
                        thread_id=thread_id,
                        run_id=run_id,
                        tool_outputs=tool_outputs,
                        event_handler=MyEventHandler()
                    ) as stream:
                        stream.until_done()
            except Exception as e:
                print(e)
                tool_calls = []
                client.beta.threads.runs.cancel(
                    thread_id=thread_id,
                    run_id=run_id
                )
                break
        else:
            await asyncio.sleep(1)
        run_status = get_run_status(thread_id)
    run_id = None
    messages = client.beta.threads.messages.list(thread_id)
    latest_message = messages.data[0].content[0].text
    return latest_message

async def respond(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        thread_id = get_or_create_thread(chat_id)
        
        if thread_id is None:
            await update.message.reply_text("Sorry, there was an error processing your request.")
            return

        chat_image = None
        chat_voice = None
        content = ""

        # Check if the message contains an image
        if update.message.document:
            chat_image = await update.message.document.get_file()
        elif update.message.photo:
            chat_image = await update.message.photo[-1].get_file()

        # Check if the message is a voice message
        elif update.message.voice:
            chat_voice = await update.message.voice.get_file()

        # Process text content
        if update.message.text:
            content = update.message.text
        elif update.message.caption:
            content = update.message.caption
        
        # Process voice message
        if chat_voice:
            voice_file = await chat_voice.download_as_bytearray()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_file:
                temp_file.write(voice_file)
                temp_file_path = temp_file.name
            
            # Convert speech to text
            content = await generate_transcript(temp_file_path)
            os.unlink(temp_file_path)

        if chat_image:
            # Get the file name and extension of the uploaded file
            file_name = chat_image.file_path.split('/')[-1]
            file_extension = os.path.splitext(file_name)[1]
            
            # Create a temporary file with the same extension
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                await chat_image.download_to_memory(temp_file)
                temp_file_path = temp_file.name

            image_file = client.files.create(file=open(temp_file_path, "rb"), purpose="assistants")
            message_content = [
                {
                    "type": "text",
                    "text": content
                },
                {
                    "type": "image_file",
                    "image_file": {
                        "file_id": image_file.id
                    }
                }
            ]
        else:
            message_content = content

        print(message_content)
        message = client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=message_content
        )
        response = await stream_assistant_response(thread_id, message)
        output = response.value

        # Clean up the temporary file if it was created
        if chat_image:
            os.unlink(temp_file_path)

    except Exception as e:
        traceback.print_exc()
        output = str(e)

    await update.message.reply_text(output)

def main():
    # Initialize the application with the token
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

     # Register a handler for all text messages and messages with images
    application.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.Document.IMAGE | filters.VOICE) & (~filters.COMMAND),
        respond
    ))

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()
