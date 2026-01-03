import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Fetch variables
DB_USER = os.getenv("user")
DB_PASSWORD = os.getenv("password")
DB_HOST = os.getenv("host")
DB_PORT = os.getenv("port")
DB_NAME = os.getenv("dbname")

print("Connecting to database...")

try:
    conn = psycopg2.connect(
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME
    )
    conn.autocommit = True
    cursor = conn.cursor()
    
    print("Creating Tables if not exist...")
    
    # 1. Supervisors
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS supervisors (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        name TEXT UNIQUE NOT NULL,
        password TEXT
    );
    """)
    # Migration for existing table
    try:
        cursor.execute("ALTER TABLE supervisors ADD COLUMN IF NOT EXISTS password TEXT;")
        print("- Supervisors schema update (password col) check.")
    except Exception as e:
        print(f"  (Migration warning: {e})")
        
    print("- Supervisors table check.")

    # 2. Blocks
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS blocks (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        name TEXT UNIQUE NOT NULL,
        capacity INT
    );
    """)
    print("- Blocks table check.")

    
    # 3. Schedules
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS schedules (
        id SERIAL PRIMARY KEY,
        exam_name TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        input_snapshot JSONB NOT NULL,
        schedule_result JSONB NOT NULL
    );
    """)
    print("- Schedules table check.")

    # 4. Supervisor Issues
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS supervisor_issues (
        id SERIAL PRIMARY KEY,
        exam_name TEXT NOT NULL,
        supervisor_name TEXT NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        block TEXT NOT NULL,
        reason TEXT,
        status TEXT DEFAULT 'OPEN',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    print("- Supervisor Issues table check.")

    cursor.close()
    conn.close()
    print("Database Setup Completed Successfully.")

except Exception as e:
    print(f"Error setting up database: {e}")
