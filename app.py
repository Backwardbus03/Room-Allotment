from flask import Flask, render_template, request, session, redirect, url_for, flash
import pandas as pd
import scheduler
import json
import os
from functools import wraps
from config import Config
import db

app = Flask(__name__)
app.config.from_object(Config)

# Ensure data directory exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# --- Helpers & Decorators ---

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_role' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_role' not in session:
            return redirect(url_for('login'))
        if session.get('user_role') != 'admin':
            flash("Access denied: Admins only.")
            return redirect(url_for('supervisor_dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# --- Routes ---

@app.route('/')
def home():
    if 'user_role' in session:
        if session['user_role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('supervisor_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        role = request.form.get('role')
        
        if role == 'admin':
            password = request.form.get('password')
            if password == app.config['ADMIN_PASSWORD']:
                session['user_role'] = 'admin'
                session['user_name'] = 'Admin'
                return redirect(url_for('admin_dashboard'))
            else:
                flash("Invalid Admin Password")
        
        elif role == 'supervisor':
            name = request.form.get('name').strip()
            password = request.form.get('password')
            
            # Verify via DB
            try:
                if db.verify_supervisor(name, password):
                    session['user_role'] = 'supervisor'
                    session['user_name'] = name
                    return redirect(url_for('supervisor_dashboard'))
                else:
                    flash("Invalid Supervisor Name or Password.")
            except Exception as e:
                flash(f"Error accessing database: {e}")
                
    return render_template('login.html')

@app.route('/register', methods=['POST'])
def register():
    name = request.form.get('name').strip()
    password = request.form.get('password')
    
    if not name or not password:
        flash("Name and Password are required.")
        return redirect(url_for('login'))
        
    success, msg = db.create_supervisor(name, password)
    flash(msg)
    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- Admin Routes ---

@app.route('/admin')
@admin_required
def admin_dashboard():
    return render_template('index.html')

@app.route('/configure', methods=['POST'])
@admin_required
def configure():
    try:
        if 'blocks_file' not in request.files or 'supervisors_file' not in request.files:
            return "Error: Please upload both Excel files."
            
        blocks_file = request.files['blocks_file']
        supervisors_file = request.files['supervisors_file']
        
        # Read Rooms
        df_rooms = pd.read_excel(blocks_file)
        rooms = []
        # Format for DB: list of dicts {'name': ..., 'capacity': ...}
        # Assuming col 0 is Name, col 1 is Capacity
        for index, row in df_rooms.iterrows():
            rooms.append({
                'name': str(row.iloc[0]),
                'capacity': int(row.iloc[1])
            })
            
        # Read Supervisors
        df_supervisors = pd.read_excel(supervisors_file)
        
        # Process Supervisors List
        supervisors_db_data = []
        supervisors_names_only = []
        
        # Check if 'Password' column exists, else default
        has_password = 'Password' in df_supervisors.columns
        
        # Assuming Name is Col 0
        for index, row in df_supervisors.iterrows():
            name = str(row.iloc[0]).strip()
            if not name or name.lower() == 'nan': continue
            
            password = '123456'
            if has_password:
                val = row['Password']
                if pd.notna(val):
                    password = str(val)
            
            supervisors_db_data.append({'name': name, 'password': password})
            supervisors_names_only.append(name)
        
        # SAVE TO DB
        db.upsert_blocks(rooms)
        db.upsert_supervisors(supervisors_db_data)
        
        return render_template('configure.html', 
                               rooms_json=json.dumps(rooms), 
                               supervisors_json=json.dumps(supervisors_names_only))
                               
    except Exception as e:
        return f"An error occurred reading/saving files: {str(e)}"

@app.route('/generate', methods=['POST'])
@admin_required
def generate():
    try:
        rooms = json.loads(request.form.get('rooms_json'))
        supervisors = json.loads(request.form.get('supervisors_json'))
        session_ids = request.form.getlist('session_ids')
        
        sessions_data = []
        for sid in session_ids:
            day = request.form.get(f'day_{sid}')
            s_type = request.form.get(f'session_type_{sid}')
            students = request.form.get(f'total_students_{sid}')
            unavailable = request.form.getlist(f'unavailable_{sid}')
            
            if day and s_type and students:
                sessions_data.append({
                    'day': int(day),
                    'session': s_type,
                    'total_students': int(students),
                    'unavailable': unavailable
                })
        
        max_day = max(s['day'] for s in sessions_data) if sessions_data else 0

        # Generate
        result = scheduler.generate_schedule(max_day, rooms, supervisors, sessions_data)
        
        # Process & Save
        schedule_data = result['schedule']
        
        # SAVE TO DB
        if schedule_data:
            db.clear_schedule_data() # Optional: Clear old schedule first
            db.save_schedule(schedule_data)
        
        # Prepare HTML for display
        schedule_html = ""
        if schedule_data:
            df = pd.DataFrame(schedule_data)
            chart = df.pivot(index=['Day', 'Session'], columns='Block', values='Supervisor').fillna("-")
            schedule_html = chart.to_html(classes='table table-striped', border=0)
        else:
            schedule_html = "<p>No schedule data generated.</p>"

        duty_counts = result['duties']
        sorted_duties = sorted(duty_counts.items(), key=lambda x: x[1], reverse=True)
        
        return render_template('result.html', duty_report=sorted_duties, schedule_table=schedule_html)

    except Exception as e:
        return f"An error occurred generating schedule: {str(e)}"

# --- Supervisor Routes ---

@app.route('/supervisor')
@login_required
def supervisor_dashboard():
    name = session.get('user_name')
    
    my_schedule = []
    try:
        my_schedule = db.get_schedule_for_supervisor(name)
    except Exception as e:
        flash(f"Error loading schedule: {e}")
            
    return render_template('supervisor_dashboard.html', schedule=my_schedule, name=name)

if __name__ == '__main__':
    app.run(debug=True)
