import aiohttp
import asyncio
import os
from dotenv import load_dotenv
from typing import Optional, Dict, Any
import json
import os
import logging
import fal_client
from openai import OpenAI
from openai import AssistantEventHandler
from typing_extensions import override
import asyncio
import time

load_dotenv()

FAL_API_KEY = os.getenv("FAL_API_KEY")
client = OpenAI()
assistant_id = os.getenv("OPENAI_ASSISTANT_ID")

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables from .env file
load_dotenv()

BASE_URL = os.getenv("BASE_URL")

async def fetch(session: aiohttp.ClientSession, url: str, params: Dict[str, str] = None, headers: Dict[str, str] = None) -> Dict[str, Any]:
    async with session.get(url, params=params, headers=headers) as response:
        if response.status == 200:
            return await response.json()
        else:
            raise Exception(f"HTTP error {response.status}: {await response.text()}")

async def post(session: aiohttp.ClientSession, url: str, data: Dict[str, Any], headers: Dict[str, str] = None) -> Dict[str, Any]:
    async with session.post(url, json=data, headers=headers) as response:
        return await response.json()

async def put(session: aiohttp.ClientSession, url: str, data: Dict[str, Any], headers: Dict[str, str] = None) -> Dict[str, Any]:
    async with session.put(url, json=data, headers=headers) as response:
        return await response.json()

async def delete(session: aiohttp.ClientSession, url: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    async with session.delete(url, headers=headers) as response:
        return await response.json()

# Create an event handler class to manage streaming events
class MyEventHandler(AssistantEventHandler):
    def __init__(self, *args, helper=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = helper

    @override
    def on_text_created(self, text) -> None:
        self.helper.run_id = self.current_run.id
    
    @override
    def on_text_delta(self, text, snapshot):
        self.helper.run_id = self.current_run.id

    def on_tool_call_done(self, tool_call):
        print("Added tool call to list...")
        self.helper.tool_calls.append(tool_call)
        self.helper.run_id = self.current_run.id
        

    def on_tool_call_delta(self, delta, snapshot):
        self.helper.run_id = self.current_run.id
        if delta.type == 'function':
            if delta.function.arguments:
                print(delta.function.arguments, end="", flush=True)
    
    def on_message_done(self, message):
        self.helper.run_id = self.current_run.id

class TodoAPIHelper:
    def __init__(self, chat_id, thread_id):
        self.chat_id = chat_id
        self.headers = {"chat-id": str(chat_id)}
        self.params = {"completed": "false"}
        self.thread_id = thread_id
        self.run_id = None
        self.tool_calls = []

    async def get_tasks(self) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            url = f"{BASE_URL}/tasks"
            return await fetch(session, url, params=self.params, headers=self.headers)

    async def get_task(self, task_id: int) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            url = f"{BASE_URL}/tasks/{task_id}"
            return await fetch(session, url, headers=self.headers)

    async def create_task(self, title: str, description: Optional[str] = None, completed: Optional[bool] = False) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            url = f"{BASE_URL}/tasks"
            data = {
                "title": title,
                "description": description,
                "completed": completed
            }
            return await post(session, url, data, headers=self.headers)

    async def update_task(self, task_id: int, title: Optional[str] = None, description: Optional[str] = None, completed: Optional[bool] = False) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            url = f"{BASE_URL}/tasks/{task_id}"
            data = {
                "title": title,
                "description": description,
                "completed": completed
            }
            return await put(session, url, data, headers=self.headers)

    async def delete_task(self, task_id: int) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            url = f"{BASE_URL}/tasks/{task_id}"
            return await delete(session, url, headers=self.headers)

    async def run_tool(self, tool_call):
        arguments = json.loads(tool_call.function.arguments)
        function_name = tool_call.function.name
        try:
            if function_name == "get_tasks":
                res = await self.get_tasks()
            elif function_name == "get_task":
                task_id = arguments["task_id"]
                res = await self.get_task(task_id)
            elif function_name == "create_task":
                title = arguments["title"]
                description = arguments.get("description")
                completed = arguments.get("completed", False)
                res = await self.create_task(title, description, completed)
            elif function_name == "update_task":
                task_id = arguments["task_id"]
                title = arguments.get("title")
                description = arguments.get("description")
                completed = arguments.get("completed", False)
                res = await self.update_task(task_id, title, description, completed)    
            elif function_name == "delete_task":
                task_id = arguments["task_id"]
                res = await self.delete_task(task_id)
            else:
                raise Exception(f"Unknown function name: {function_name}")
        except Exception as e:
            print(e)
            return str(e), tool_call.id
        return str(res), tool_call.id

    async def executeToolCalls(self, tool_calls):
        tasks = [self.run_tool(tc) for tc in tool_calls]
        results = await asyncio.gather(*tasks)
        results_arr = []
        for res, tool_call_id in results:
            results_arr.append({
                "tool_call_id": tool_call_id,
                "output": res
            })
        return results_arr
    
    def get_run_status(self, run_id):
        run = client.beta.threads.runs.retrieve(
                thread_id=self.thread_id,
                run_id=run_id
                )
        run_status = run.status
        return run_status

    async def stream_assistant_response(self):
        self.tool_calls = []
        with client.beta.threads.runs.stream(
            thread_id=self.thread_id,
            assistant_id=assistant_id,
            event_handler=MyEventHandler(helper=self),
        ) as stream:
            stream.until_done()
        run_status = self.get_run_status(self.run_id)
        while run_status in ('queued', 'in_progress', 'requires_action'):
            if run_status == 'requires_action':
                try:
                    tool_outputs = await self.executeToolCalls(self.tool_calls)
                    self.tool_calls = []
                    with client.beta.threads.runs.submit_tool_outputs_stream(
                            thread_id=self.thread_id,
                            run_id=self.run_id,
                            tool_outputs=tool_outputs,
                            event_handler=MyEventHandler(helper=self)
                        ) as stream:
                            stream.until_done()
                except Exception as e:
                    print(e)
                    self.tool_calls = []
                    client.beta.threads.runs.cancel(
                        thread_id=self.thread_id,
                        run_id=self.run_id
                    )
                    break
            else:
                await asyncio.sleep(1)
            run_status = self.get_run_status(self.run_id)
        self.run_id = None
        messages = client.beta.threads.messages.list(self.thread_id)
        latest_message = messages.data[0].content[0].text
        return latest_message

async def generate_transcript(audio_path):
    logging.info(f"Generating transcript for: {audio_path}")
    fal_client.api_key = FAL_API_KEY # or is the key loaded from env variable, i don't know, i set both

    with open(audio_path, "rb") as audio_file:
        audio_bytes = audio_file.read()

    logging.info("Uploading audio file to fal.ai")

    audio_url = await fal_client.upload_async(audio_bytes, "audio/ogg")

    logging.info(f"Going to pass the audio url {audio_url} to fal and transcribe")

    handler = await fal_client.submit_async(
        "fal-ai/wizper",
        arguments={
            "audio_url": audio_url,
            "task": "transcribe",
            "language": "en",
            "chunk_level": "segment",
            "version": "3",
        },
    )

    result = await handler.get()
    transcript = result["text"]
    return transcript