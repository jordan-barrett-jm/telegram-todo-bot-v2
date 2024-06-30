import aiohttp
import asyncio
import os
from dotenv import load_dotenv
from typing import Optional, Dict, Any
import json
import sqlite3
from sqlite3 import Error
import os
import logging
import fal_client

load_dotenv()

FAL_API_KEY = os.getenv("FAL_API_KEY")

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_connection():
    db_file = 'chats.db'
    conn = None
    try:
        # This will create the database if it doesn't exist
        conn = sqlite3.connect(db_file)
        logging.info(f"Connected to the database: {db_file}")
        
        # Check if the database is newly created
        if not os.path.exists(db_file) or os.path.getsize(db_file) == 0:
            logging.info("Newly created database. Creating table...")
            create_table(conn)
        
        return conn
    except Error as e:
        logging.error(f"Error connecting to database: {e}")
    
    return conn

def create_table(conn):
    try:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS chats
                     (chat_id INTEGER PRIMARY KEY, thread_id TEXT)''')
        conn.commit()
        logging.info("Table 'chats' created successfully")
    except Error as e:
        logging.error(f"Error creating table: {e}")

# Load environment variables from .env file
load_dotenv()

BASE_URL = os.getenv("BASE_URL")

async def fetch(session: aiohttp.ClientSession, url: str) -> Dict[str, Any]:
    async with session.get(url) as response:
        return await response.json()

async def post(session: aiohttp.ClientSession, url: str, data: Dict[str, Any]) -> Dict[str, Any]:
    async with session.post(url, json=data) as response:
        return await response.json()

async def put(session: aiohttp.ClientSession, url: str, data: Dict[str, Any]) -> Dict[str, Any]:
    async with session.put(url, json=data) as response:
        return await response.json()

async def delete(session: aiohttp.ClientSession, url: str) -> Dict[str, Any]:
    async with session.delete(url) as response:
        return await response.json()

async def get_tasks() -> Dict[str, Any]:
    async with aiohttp.ClientSession() as session:
        url = f"{BASE_URL}/tasks"
        return await fetch(session, url)

async def get_task(task_id: int) -> Dict[str, Any]:
    async with aiohttp.ClientSession() as session:
        url = f"{BASE_URL}/tasks/{task_id}"
        return await fetch(session, url)

async def create_task(title: str, description: Optional[str] = None, completed: Optional[bool] = False) -> Dict[str, Any]:
    async with aiohttp.ClientSession() as session:
        url = f"{BASE_URL}/tasks"
        data = {
            "title": title,
            "description": description,
            "completed": completed
        }
        return await post(session, url, data)

async def update_task(task_id: int, title: Optional[str] = None, description: Optional[str] = None, completed: Optional[bool] = False) -> Dict[str, Any]:
    async with aiohttp.ClientSession() as session:
        url = f"{BASE_URL}/tasks/{task_id}"
        data = {
            "title": title,
            "description": description,
            "completed": completed
        }
        return await put(session, url, data)

async def delete_task(task_id: int) -> Dict[str, Any]:
    async with aiohttp.ClientSession() as session:
        url = f"{BASE_URL}/tasks/{task_id}"
        return await delete(session, url)

# Example usage
if __name__ == "__main__":
    import pprint

    async def main():
        # Create a task
        new_task = await create_task("Sample Task", "This is a sample task")
        pprint.pprint(new_task)

        # Get all tasks
        tasks = await get_tasks()
        pprint.pprint(tasks)

        # Get a specific task
        task = await get_task(new_task['id'])
        pprint.pprint(task)

        # Update the task
        updated_task = await update_task(new_task['id'], title="Updated Task", completed=True)
        pprint.pprint(updated_task)

        # Delete the task
        deleted_task = await delete_task(new_task['id'])
        pprint.pprint(deleted_task)

    asyncio.run(main())

async def run_tool(tool_call):
    arguments = json.loads(tool_call.function.arguments)
    function_name = tool_call.function.name
    try:
        if function_name == "get_tasks":
            res = await get_tasks()
        elif function_name == "get_task":
            task_id = arguments["task_id"]
            res = await get_task(task_id)
        elif function_name == "create_task":
            title = arguments["title"]
            description = arguments.get("description")
            completed = arguments.get("completed", False)
            res = await create_task(title, description, completed)
        elif function_name == "update_task":
            task_id = arguments["task_id"]
            title = arguments.get("title")
            description = arguments.get("description")
            completed = arguments.get("completed", False)
            res = await update_task(task_id, title, description, completed)    
        elif function_name == "delete_task":
            task_id = arguments["task_id"]
            res = await delete_task(task_id)
        else:
            raise Exception(f"Unknown function name: {function_name}")
    except Exception as e:
        print(e)
        return str(e), tool_call.id
    return str(res), tool_call.id

async def executeToolCalls(tool_calls):
    tasks = [run_tool(tc) for tc in tool_calls]
    results = await asyncio.gather(*tasks)
    results_arr = []
    for res, tool_call_id in results:
        results_arr.append({
            "tool_call_id": tool_call_id,
            "output": res
        })
    return results_arr

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
    return result["text"]
