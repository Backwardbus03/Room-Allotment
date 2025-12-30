import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

# Fetch variables
DB_USER = os.getenv("user")
DB_PASSWORD = os.getenv("password")
DB_HOST = os.getenv("host")
DB_PORT = os.getenv("port")
DB_NAME = os.getenv("dbname")

def get_connection():
    try:
        conn = psycopg2.connect(
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME
        )
        return conn
    except Exception as e:
        print(f"Failed to connect to DB: {e}")
        return None

def upsert_supervisors(supervisors_list):
    """
    Upserts a list of supervisors. 
    supervisors_list: [{'name': '...', 'password': '...'}, ...]
    """
    conn = get_connection()
    if not conn: return

    try:
        cur = conn.cursor()
        
        # We use executemany for bulk upsert
        # ON CONFLICT(name) DO UPDATE password
        
        args = [(s['name'], s['password']) for s in supervisors_list]
        
        query = """
        INSERT INTO supervisors (name, password) 
        VALUES (%s, %s) 
        ON CONFLICT (name) 
        DO UPDATE SET password = EXCLUDED.password;
        """
        cur.executemany(query, args)
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"Error upserting supervisors: {e}")
    finally:
        conn.close()

def create_supervisor(name, password):
    """
    Creates a new supervisor. 
    Returns (True, "Success") or (False, ErrorMessage).
    """
    conn = get_connection()
    if not conn: return False, "Database connection failed"

    try:
        cur = conn.cursor()
        query = "INSERT INTO supervisors (name, password) VALUES (%s, %s)"
        cur.execute(query, (name, password))
        conn.commit()
        cur.close()
        return True, "Registration successful"
    except psycopg2.IntegrityError:
        conn.rollback() # duplicate name likely
        return False, "Supervisor name already exists"
    except Exception as e:
        conn.rollback()
        print(f"Error creating supervisor: {e}")
        return False, f"Error: {e}"
    finally:
        conn.close()

def verify_supervisor(name, password):
    """Verifies supervisor credentials. Returns True if valid."""
    conn = get_connection()
    if not conn: return False

    try:
        cur = conn.cursor()
        cur.execute("SELECT password FROM supervisors WHERE name = %s", (name,))
        row = cur.fetchone()
        cur.close()
        
        if row:
            # In a real app, hash this!
            # Storing plain text as requested/implied by "excel upload" simplicity
            db_pass = row[0]
            if db_pass == password:
                return True
                
        return False
    except Exception as e:
        print(f"Error verifying supervisor: {e}")
        return False
    finally:
        conn.close()

def get_all_supervisors():
    """Returns a list of supervisor names."""
    conn = get_connection()
    if not conn: return []

    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM supervisors")
        rows = cur.fetchall()
        cur.close()
        return [row[0] for row in rows]
    except Exception as e:
        print(f"Error fetching supervisors: {e}")
        return []
    finally:
        conn.close()

def upsert_blocks(rooms_list):
    """
    Upserts rooms. rooms_list is list of dicts: {'name': 'Room A', 'capacity': 30}
    """
    conn = get_connection()
    if not conn: return

    try:
        cur = conn.cursor()
        
        for room in rooms_list:
            cur.execute("""
                INSERT INTO blocks (name, capacity) 
                VALUES (%s, %s)
                ON CONFLICT (name) 
                DO UPDATE SET capacity = EXCLUDED.capacity;
            """, (room['name'], room['capacity']))
            
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"Error upserting blocks: {e}")
    finally:
        conn.close()

def save_schedule(schedule_data):
    """
    Saves the new schedule.
    schedule_data is list of dicts: {'Day': '...', 'Session': '...', 'Block': '...', 'Supervisor': '...'}
    """
    conn = get_connection()
    if not conn: return
    
    try:
        cur = conn.cursor()
        
        # Optional: Clear old schedule? 
        # For now, let's assuming we append, or maybe we really should clear all for clarity in this demo.
        # cur.execute("TRUNCATE TABLE schedules;") # Careful with truncate
        
        # Let's perform a bulk insert
        
        values = []
        for row in schedule_data:
            is_backup = (row['Block'] == 'BACKUP')
            values.append((
                row['Day'], 
                row['Session'], 
                row['Block'], 
                row['Supervisor'], 
                is_backup
            ))
            
        # Using execute_mogrify approach or executemany
        cur.executemany("""
            INSERT INTO schedules (day, session, block_name, supervisor_name, is_backup)
            VALUES (%s, %s, %s, %s, %s)
        """, values)
        
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"Error saving schedule: {e}")
    finally:
        conn.close()

def get_schedule_for_supervisor(name):
    """Fetch schedule rows for a specific supervisor."""
    conn = get_connection()
    if not conn: return []
    
    try:
        # Use RealDictCursor to get dictionary-like result
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM schedules WHERE supervisor_name = %s", (name,))
        rows = cur.fetchall()
        
        ui_data = []
        for row in rows:
            ui_data.append({
                "Day": row['day'],
                "Session": row['session'],
                "Block": row['block_name'],
                "Supervisor": row['supervisor_name']
            })
            
        cur.close()
        return ui_data
    except Exception as e:
        print(f"Error fetching schedule: {e}")
        return []
    finally:
        conn.close()

def clear_schedule_data():
    """Helper to clear schedule table if needed"""
    conn = get_connection()
    if not conn: return
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM schedules")
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"Error clearing schedule: {e}")
    finally:
        conn.close()
