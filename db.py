import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import bcrypt

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


def migrate_schema():
    """Ensures DB schema is up to date."""
    conn = get_connection()
    if not conn: return
    try:
        cur = conn.cursor()
        # Add is_published column if not exists
        cur.execute("""
            ALTER TABLE schedules 
            ADD COLUMN IF NOT EXISTS is_published BOOLEAN DEFAULT TRUE;
        """)
        conn.commit()
        cur.close()
        print("Schema migration checked/applied.")
    except Exception as e:
        print(f"Schema migration error: {e}")
    finally:
        conn.close()

def upsert_supervisors(supervisors_list):
    """
    Upserts a list of supervisors. 
    supervisors_list: [{'name': '...', 'email': '...', 'password': '...'}, ...]
    """
    conn = get_connection()
    if not conn: return

    try:
        cur = conn.cursor()
        
        # We use executemany for bulk upsert
        # ON CONFLICT(email) DO UPDATE password, name
        
        # 1. MARK ALL AS INACTIVE FIRST
        # This ensures that anyone NOT in the new list becomes inactive
        cur.execute("UPDATE supervisors SET is_active = FALSE")
        
        # 2. Upsert new ones and mark as ACTIVE
        args = []
        for s in supervisors_list:
             # Hash the password
             hashed_pw = bcrypt.hashpw(s['password'].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
             args.append((s['name'], s['email'], hashed_pw))
        
        query = """
        INSERT INTO supervisors (name, email, password, is_active) 
        VALUES (%s, %s, %s, TRUE) 
        ON CONFLICT (email) 
        DO UPDATE SET 
            name = EXCLUDED.name, 
            is_active = TRUE;
        """
        cur.executemany(query, args)
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"Error upserting supervisors: {e}")
    finally:
        conn.close()

def create_supervisor(name, email, password):
    """
    Creates a new supervisor. 
    Returns (True, "Success") or (False, ErrorMessage).
    """
    conn = get_connection()
    if not conn: return False, "Database connection failed"

    try:
        cur = conn.cursor()
        hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        query = "INSERT INTO supervisors (name, email, password) VALUES (%s, %s, %s)"
        cur.execute(query, (name, email, hashed_pw))
        conn.commit()
        cur.close()
        return True, "Registration successful"
    except psycopg2.IntegrityError:
        conn.rollback() # duplicate email likely
        return False, "Supervisor email already exists"
    except Exception as e:
        conn.rollback()
        print(f"Error creating supervisor: {e}")
        return False, f"Error: {e}"
    finally:
        conn.close()

def verify_supervisor(email, password):
    """Verifies supervisor credentials. Returns (True, name) if valid, else (False, None)."""
    conn = get_connection()
    if not conn: return False, None

    try:
        cur = conn.cursor()
        cur.execute("SELECT password, name FROM supervisors WHERE email = %s", (email,))
        row = cur.fetchone()
        cur.close()
        
        if row:
            stored_hash = row[0]
            name = row[1]
            # Verify using bcrypt
            # Note: stored_hash should be a string from DB, we encode it to bytes for bcrypt
            try:
                if bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
                    return True, name
            except ValueError:
                # Fallback for plain text (during migration transition)
                if stored_hash == password:
                    return True, name
                
        return False, None
    except Exception as e:
        print(f"Error verifying supervisor: {e}")
        return False, None
    finally:
        conn.close()

def update_supervisor_password(name, new_password):
    # 'name' arg here is actually the email in the new context, will rename internally to email
    email = name
    """Updates supervisor password. Returns True if successful."""
    conn = get_connection()
    if not conn: return False

    try:
        cur = conn.cursor()
        hashed_pw = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cur.execute("UPDATE supervisors SET password = %s WHERE email = %s", (hashed_pw, name))
        conn.commit()
        updated = cur.rowcount > 0
        cur.close()
        return updated
    except Exception as e:
        print(f"Error updating password: {e}")
        return False
    finally:
        conn.close()

def update_supervisor_details(updates):
    """
    Updates role and unavailability for multiple supervisors.
    updates: list of {'email': ..., 'role': ..., 'start': ..., 'end': ...}
    """
    conn = get_connection()
    if not conn: return False

    try:
        cur = conn.cursor()
        query = """
        UPDATE supervisors 
        SET role = %s, unavailable_start = %s, unavailable_end = %s 
        WHERE email = %s
        """
        args = [(u['role'], u['start'], u['end'], u['email']) for u in updates]
        cur.executemany(query, args)
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"Error updating supervisor details: {e}")
        return False
    finally:
        conn.close()

def get_all_supervisors():
    """Returns a list of supervisor dictionaries with all details."""
    conn = get_connection()
    if not conn: return []

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT name, email, role, unavailable_start, unavailable_end FROM supervisors WHERE is_active = TRUE ORDER BY name")
        rows = cur.fetchall()
        cur.close()
        return rows # Returns list of dicts
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

def delete_all_blocks():
    """
    Deletes all rows from the blocks table.
    Used to clear old rooms before importing a new Excel file.
    """
    conn = get_connection()
    if not conn: return False

    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM blocks;")
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"Error deleting blocks: {e}")
        return False
    finally:
        conn.close()

def save_schedule(exam_name, input_snapshot, schedule_result, published=False):
    """
    Saves the new schedule as a snapshot.
    """
    conn = get_connection()
    if not conn: return
    
    try:
        cur = conn.cursor()
        import json
        
        # Check if exists to update or insert (Upsert)
        # Using simple check-then-insert/update logic for compatibility
        cur.execute("SELECT id FROM schedules WHERE exam_name = %s", (exam_name,))
        row = cur.fetchone()
        
        input_json = json.dumps(input_snapshot)
        result_json = json.dumps(schedule_result)
        
        if row:
            # Update existing
            cur.execute("""
                UPDATE schedules 
                SET input_snapshot = %s, schedule_result = %s, is_published = %s, created_at = NOW()
                WHERE exam_name = %s
            """, (input_json, result_json, published, exam_name))
        else:
            # Insert new
            cur.execute("""
                INSERT INTO schedules (exam_name, input_snapshot, schedule_result, is_published)
                VALUES (%s, %s, %s, %s)
            """, (exam_name, input_json, result_json, published))
        
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"Error saving schedule: {e}")
    finally:
        conn.close()

def publish_schedule_db(exam_name):
    """Sets is_published to True for an exam."""
    conn = get_connection()
    if not conn: return False
    try:
        cur = conn.cursor()
        cur.execute("UPDATE schedules SET is_published = TRUE WHERE exam_name = %s", (exam_name,))
        updated = cur.rowcount > 0
        conn.commit()
        cur.close()
        return updated
    except Exception as e:
        print(f"Error publishing schedule DB: {e}")
        return False
    finally:
        conn.close()

def get_available_exams(published_only=False):
    """Returns list of distinct exam names available in the db."""
    conn = get_connection()
    if not conn: return []
    
    try:
        cur = conn.cursor()
        
        if published_only:
             query = """
            SELECT s.exam_name, s.created_at, COUNT(i.id) as open_issues
            FROM schedules s
            LEFT JOIN supervisor_issues i ON s.exam_name = i.exam_name AND i.status = 'OPEN'
            WHERE s.is_published = TRUE
            GROUP BY s.exam_name, s.created_at
            ORDER BY s.created_at DESC
            """
        else:
            query = """
            SELECT s.exam_name, s.created_at, COUNT(i.id) as open_issues, s.is_published
            FROM schedules s
            LEFT JOIN supervisor_issues i ON s.exam_name = i.exam_name AND i.status = 'OPEN'
            GROUP BY s.exam_name, s.created_at, s.is_published
            ORDER BY s.created_at DESC
            """
            
        cur.execute(query)
        rows = cur.fetchall()
        cur.close()
        
        results = []
        for r in rows:
            item = {'name': r[0], 'date': r[1], 'issue_count': r[2]}
            if not published_only:
                 # Add status for admin
                 item['is_published'] = r[3] if len(r) > 3 else True
            results.append(item)
            
        return results
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

def get_schedule_snapshot(exam_name):
    """
    Fetch the input_snapshot for a specific exam.
    Used to retrieve persistent metadata like allocation errors.
    """
    conn = get_connection()
    if not conn: return {}
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT input_snapshot FROM schedules WHERE exam_name = %s", (exam_name,))
        row = cur.fetchone()
        cur.close()
        
        if not row or not row['input_snapshot']: return {}
        return row['input_snapshot'] 
        
    except Exception as e:
        print(f"Error fetching snapshot: {e}")
        return {}
    finally:
        conn.close()

def report_issue(exam_name, supervisor_name, date, time, block, reason, candidate_data=None):
    """
    Reports a supervisor unavailability issue.
    candidate_data: dict with candidate_supervisor, candidate_date, candidate_time, candidate_block, swap_type
    """
    conn = get_connection()
    if not conn: return False, "DB Connection Failed"
    
    try:
        cur = conn.cursor()
        
        # Prepare optional fields
        c_sup = None
        c_date = None
        c_time = None
        c_block = None
        s_type = '1-way (Relief)'
        
        if candidate_data:
            c_sup = candidate_data.get('candidate_supervisor')
            c_date = candidate_data.get('candidate_date')
            c_time = candidate_data.get('candidate_time')
            c_block = candidate_data.get('candidate_block')
            s_type = candidate_data.get('swap_type', '1-way (Relief)')
            
        query = """
        INSERT INTO supervisor_issues 
        (exam_name, supervisor_name, date, time, block, reason, 
         candidate_supervisor, candidate_date, candidate_time, candidate_block, swap_type)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cur.execute(query, (exam_name, supervisor_name, date, time, block, reason,
                            c_sup, c_date, c_time, c_block, s_type))
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

def get_supervisor_issues_history(exam_name, supervisor_name):
    """Fetches all issues reported by a supervisor for a specific exam."""
    conn = get_connection()
    if not conn: return []
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        query = """
        SELECT * FROM supervisor_issues 
        WHERE exam_name = %s AND supervisor_name = %s
        ORDER BY created_at DESC
        """
        cur.execute(query, (exam_name, supervisor_name))
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        print(f"Error fetching supervisor history: {e}")
        return []
    finally:
        conn.close()

def resolve_issue(issue_id, status='RESOLVED', rejection_reason=None):
    """Marks an issue as resolved or rejected."""
    conn = get_connection()
    if not conn: return False
    
    try:
        cur = conn.cursor()
        if status == 'REJECTED':
             cur.execute("UPDATE supervisor_issues SET status = %s, rejection_reason = %s WHERE id = %s", (status, rejection_reason, issue_id))
        else:
             cur.execute("UPDATE supervisor_issues SET status = %s WHERE id = %s", (status, issue_id))
        
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"Error resolving issue: {e}")
        return False
    finally:
        conn.close()

def get_all_blocks():
    """Returns a list of block dicts {'name': ..., 'capacity': ...}."""
    conn = get_connection()
    if not conn: return []

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT name, capacity FROM blocks ORDER BY name")
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        print(f"Error fetching blocks: {e}")
        return []
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
