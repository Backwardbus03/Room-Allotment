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

def save_schedule(exam_name, input_snapshot, schedule_result):
    """
    Saves the new schedule as a snapshot.
    """
    conn = get_connection()
    if not conn: return
    
    try:
        cur = conn.cursor()
        
        # Insert or Update (Assuming we might want to update if same exam name? 
        # For now let's just Insert, or assume exam names are unique-ish enough or we allow duplicates)
        # Using JSONB for postgres
        import json
        
        query = """
        INSERT INTO schedules (exam_name, input_snapshot, schedule_result)
        VALUES (%s, %s, %s)
        """
        
        cur.execute(query, (
            exam_name, 
            json.dumps(input_snapshot), 
            json.dumps(schedule_result)
        ))
        
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"Error saving schedule: {e}")
    finally:
        conn.close()

def get_available_exams():
    """Returns list of distinct exam names available in the db."""
    conn = get_connection()
    if not conn: return []
    
    try:
        cur = conn.cursor()
        query = """
        SELECT s.exam_name, s.created_at, COUNT(i.id) as open_issues
        FROM schedules s
        LEFT JOIN supervisor_issues i ON s.exam_name = i.exam_name AND i.status = 'OPEN'
        GROUP BY s.exam_name, s.created_at
        ORDER BY s.created_at DESC
        """
        cur.execute(query)
        rows = cur.fetchall()
        cur.close()
        # Return dict with issue count
        return [{'name': r[0], 'date': r[1], 'issue_count': r[2]} for r in rows]
    except Exception as e:
        print(f"Error fetching exams: {e}")
        return []
    finally:
        conn.close()

def get_schedule_for_supervisor(exam_name, supervisor_name):
    """
    Fetch duties for a specific supervisor in a specific exam.
    Parses the JSONB schedule_result.
    """
    conn = get_connection()
    if not conn: return []
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Get the schedule blob
        cur.execute("SELECT schedule_result FROM schedules WHERE exam_name = %s", (exam_name,))
        row = cur.fetchone()
        cur.close()
        
        if not row: return []
        
        full_schedule = row['schedule_result'] # this is a list of dicts from the JSONB column
        
        # Filter in Python (easier than complex JSONB query for now)
        my_duties = []
        for item in full_schedule:
            if item.get('Supervisor') == supervisor_name:
                my_duties.append(item)
                
        return my_duties
        
    except Exception as e:
        print(f"Error fetching schedule: {e}")
        return []
    finally:
        conn.close()

def get_full_schedule(exam_name):
    """
    Fetch the entire schedule for a specific exam (for Admin view).
    """
    conn = get_connection()
    if not conn: return []
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT schedule_result FROM schedules WHERE exam_name = %s", (exam_name,))
        row = cur.fetchone()
        cur.close()
        
        if not row: return []
        return row['schedule_result'] # Return the list of dicts
        
    except Exception as e:
        print(f"Error fetching full schedule: {e}")
        return []
    finally:
        conn.close()

def report_issue(exam_name, supervisor_name, date, time, block, reason):
    """Reports a supervisor unavailability issue."""
    conn = get_connection()
    if not conn: return False, "DB Connection Failed"
    
    try:
        cur = conn.cursor()
        query = """
        INSERT INTO supervisor_issues (exam_name, supervisor_name, date, time, block, reason)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        cur.execute(query, (exam_name, supervisor_name, date, time, block, reason))
        conn.commit()
        cur.close()
        return True, "Issue reported successfully."
    except Exception as e:
        print(f"Error reporting issue: {e}")
        return False, str(e)
    finally:
        conn.close()

def get_open_issues(exam_name):
    """Fetches all open issues for an exam."""
    conn = get_connection()
    if not conn: return []
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        query = """
        SELECT * FROM supervisor_issues 
        WHERE exam_name = %s AND status = 'OPEN' 
        ORDER BY created_at DESC
        """
        cur.execute(query, (exam_name,))
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        print(f"Error fetching issues: {e}")
        return []
    finally:
        conn.close()

def resolve_issue(issue_id):
    """Marks an issue as resolved."""
    conn = get_connection()
    if not conn: return False
    
    try:
        cur = conn.cursor()
        cur.execute("UPDATE supervisor_issues SET status = 'RESOLVED' WHERE id = %s", (issue_id,))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"Error resolving issue: {e}")
        return False
    finally:
        conn.close()

def update_schedule(exam_name, new_schedule_list):
    """Updates the schedule blob for an exam (used after swapping)."""
    conn = get_connection()
    if not conn: return False
    
    try:
        cur = conn.cursor()
        import json
        cur.execute("""
            UPDATE schedules 
            SET schedule_result = %s 
            WHERE exam_name = %s
        """, (json.dumps(new_schedule_list), exam_name))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"Error updating schedule: {e}")
        return False
    finally:
        conn.close()
