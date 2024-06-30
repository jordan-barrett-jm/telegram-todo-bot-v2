from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import os
import tempfile
import traceback
from bot_helper import get_or_create_thread
from helper_functions import *

# Load environment variables from .env file
load_dotenv()

# Get the token from environment variables
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
ALLOWED_CHATS = os.getenv("ALLOWED_CHATS").split(",")
run_id = None
tool_calls = []

async def respond(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        thread_id = get_or_create_thread(chat_id, ALLOWED_CHATS, client)
        helper = TodoAPIHelper(chat_id, thread_id)
        
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
        response = await helper.stream_assistant_response()
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
