import logging
import sqlite3
from sqlite3 import Error
import os

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

def get_or_create_thread(chat_id, allowed_chats, client):
    if str(chat_id) not in allowed_chats:
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