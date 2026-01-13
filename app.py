from flask import Flask, render_template, request, session, redirect, url_for, flash
import pandas as pd
import scheduler
import json
import os
from functools import wraps
from functools import wraps
from dotenv import load_dotenv
load_dotenv()
from config import Config
import db
import extract_pdf
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from flask import send_file
import mailer

app = Flask(__name__)
app.config.from_object(Config)

# Ensure data directory exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# --- Helpers & Decorators ---

def aggregate_schedule_rows(schedule_list):
    """
    Aggregates schedule rows with the same Supervisor, Date, Time, Block, and Role.
    Combines 'Subject' and 'Count' into a single 'Subject' string.
    """
    if not schedule_list:
        return []
        
    grouped = {}
    
    for row in schedule_list:
        # Create a unique key for grouping
        # tuple(Date, Time, Block, Role, Supervisor)
        key = (
            row.get('Date', ''),
            row.get('Time', ''),
            row.get('Block', ''),
            row.get('Role', ''),
            row.get('Supervisor', '')
        )
        
        if key not in grouped:
            grouped[key] = {
                'Date': row.get('Date', ''),
                'Time': row.get('Time', ''),
                'Day': row.get('Day', ''),
                'Session': row.get('Session', ''),
                'Block': row.get('Block', ''),
                'Role': row.get('Role', ''),
                'Supervisor': row.get('Supervisor', ''),
                'Subjects': []
            }
        
        # Add subject info
        subj = row.get('Subject', 'Unknown')
        dept = row.get('Department', '')
        count = row.get('Count', 0)
        
        if dept:
            grouped[key]['Subjects'].append(f"{subj} ({dept}) ({count})")
        else:
            grouped[key]['Subjects'].append(f"{subj} ({count})")

    # Reconstruct list
    aggregated_list = []
    for key, data in grouped.items():
        # Join subjects
        data['Subject'] = ", ".join(data['Subjects'])
        # Clean up temporary list
        del data['Subjects']
        aggregated_list.append(data)
        
    # Sort again for consistency
    def sort_key(r):
        return (r['Date'], r['Time'], r['Block'])
    
    aggregated_list.sort(key=sort_key)
    
    return aggregated_list

def calculate_row_spans(schedule_list):
    """
    Calculates rowspan values for Date and Time columns.
    Adds 'date_span' and 'time_span' to each row.
    span > 0: Render cell with rowspan.
    span == 0: Skip rendering cell.
    """
    if not schedule_list:
        return []
        
    n = len(schedule_list)
    i = 0
    while i < n:
        # 1. Calculate Date Span
        date_val = schedule_list[i].get('Date', '')
        j = i + 1
        while j < n and schedule_list[j].get('Date', '') == date_val:
            j += 1
        
        date_span = j - i
        schedule_list[i]['date_span'] = date_span
        for k in range(i + 1, j):
            schedule_list[k]['date_span'] = 0
            
        # 2. Calculate Time Span (within this Date block)
        # We need to sub-loop within the date block [i, j)
        p = i
        while p < j:
            time_val = schedule_list[p].get('Time', '')
            q = p + 1
            while q < j and schedule_list[q].get('Time', '') == time_val:
                q += 1
            
            time_span = q - p
            schedule_list[p]['time_span'] = time_span
            for k in range(p + 1, q):
                schedule_list[k]['time_span'] = 0
            
            p = q # Move to next time block
        
        i = j # Move to next date block
        
    return schedule_list

def find_swap_candidates(schedule_list, target_date, target_time, target_supervisor_name):
    """
    Finds supervisors who are FREE at (target_date, target_time).
    Returns a list of dicts: {'name': supervisor_name, 'swap_with': {date, time, block}}
    where 'swap_with' is a session of theirs that the target_supervisor is free to take.
    """
    # 1. Identify all supervisors in this schedule
    all_supervisors = set(row['Supervisor'] for row in schedule_list)
    
    # 2. Identify who is BUSY at target_time
    # (Note: Using Date+Time as key. If Time spans vary, logic might need adjustment, 
    # but currently we assume standard slots)
    busy_at_target = set()
    for row in schedule_list:
        if row.get('Date') == target_date and row.get('Time') == target_time:
            busy_at_target.add(row['Supervisor'])
            
    # 3. Candidates = All - Busy - Target
    candidates = all_supervisors - busy_at_target
    if target_supervisor_name in candidates:
        candidates.remove(target_supervisor_name)
        
    results = []
    
    # 4. For each candidate, find a session THEY have where Target is FREE
    for cand in candidates:
        # Get Candidate's schedule
        cand_sessions = [row for row in schedule_list if row['Supervisor'] == cand]
        
        valid_swap_found = False
        
        for sess in cand_sessions:
            # Check if Target Supervisor is free at sess['Date'], sess['Time']
            # Target is busy if any row in schedule matches Target & Date & Time
            is_target_busy = False
            for r in schedule_list:
                if (r['Supervisor'] == target_supervisor_name and 
                    r.get('Date') == sess.get('Date') and 
                    r.get('Time') == sess.get('Time')):
                    is_target_busy = True
                    break
            
            if not is_target_busy:
                # Valid 2-way swap found!
                results.append({
                    'name': cand,
                    'type': '2-way',
                    'their_session': sess # The session they give to Target
                })
                valid_swap_found = True
                # We can stop after finding one valid swap per candidate to keep list clean, 
                # or list all. Let's list all? Maybe just one for simplicity.
                # Let's list one.
                break
        
        if not valid_swap_found:
            # Maybe they have no sessions? Or Target is busy during all of them.
            # We can still offer a 1-way replacement (Candidate takes Target's slot, Target gets nothing/free)
            # PROMPT said "swapping... giving there some session". Implies 2-way.
            # But 1-way is also a valid "resolution".
            results.append({
                'name': cand,
                'type': '1-way (Relief)',
                'their_session': None
            })
            
    return results

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

@app.route('/api/get_swap_candidates', methods=['POST'])
@login_required
def get_swap_candidates_route():
    data = request.json
    exam_name = data.get('exam_name')
    date = data.get('date')
    time = data.get('time')
    supervisor_name = session.get('user_identifier', session.get('user_name'))
    
    if not all([exam_name, date, time]):
        return json.dumps({'error': 'Missing data'}), 400
        
    schedule_data = db.get_full_schedule(exam_name)
    if not schedule_data:
        return json.dumps({'error': 'Schedule not found'}), 404
        
    candidates = find_swap_candidates(schedule_data, date, time, supervisor_name)
    return json.dumps(candidates)

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
            email = request.form.get('email').strip().lower()
            password = request.form.get('password')
            
            # Verify via DB
            try:
                success, name = db.verify_supervisor(email, password)
                if success:
                    session['user_role'] = 'supervisor'
                    session['user_name'] = name 
                    # Use Name (Email) for schedule matching
                    session['user_identifier'] = f"{name} ({email})" 
                    session['user_email'] = email
                    return redirect(url_for('supervisor_dashboard'))
                else:
                    flash("Invalid Supervisor Email or Password.")
            except Exception as e:
                flash(f"Error accessing database: {e}")
                
    return render_template('login.html')

@app.route('/reset_password', methods=['POST'])
def reset_password():
    email = request.form.get('email').strip()
    old_password = request.form.get('old_password')
    new_password = request.form.get('new_password')
    
    if not email or not old_password or not new_password:
        flash("All fields are required.")
        return redirect(url_for('login'))
        
    # Verify Old Password
    success, _ = db.verify_supervisor(email, old_password)
    if success:
        # Update to New Password
        if db.update_supervisor_password(email, new_password):
            flash("Password updated successfully. Please login.")
        else:
            flash("Error updating password. Please try again.")
    else:
        flash("Invalid Email or Old Password.")
        
    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- Admin Routes ---

@app.route('/admin')
@admin_required
def admin_dashboard():
    # 1. Fetch all available exams
    exams = db.get_available_exams()
    
    # 2. Check if a specific exam is requested to view
    selected_exam = request.args.get('exam_name')
    
    schedule_html = None
    sorted_duties = None
    
    if selected_exam:
        # Fetch full schedule
        schedule_data = db.get_full_schedule(selected_exam)
        
        if schedule_data:
            # Reconstruct the view
            
            # 1. Duty Counts (Deduplicated by Room Assignment)
            duty_counts = {}
            seen_assignments = set()
            
            for row in schedule_data:
                sup = row.get('Supervisor', 'Unknown')
                if sup != 'NA' and sup != 'NOBODY AVAILABLE':
                    # Unique key: Supervisor + Day + Session + Block
                    # row['Date'] represents Day/Date, row['Time'] represents Session
                    key = (sup, row.get('Date'), row.get('Time'), row.get('Block'))
                    if key not in seen_assignments:
                        duty_counts[sup] = duty_counts.get(sup, 0) + 1
                        seen_assignments.add(key)
            
            # Legacy sort for display
            sorted_duties = sorted(duty_counts.items(), key=lambda x: x[1], reverse=True)
            
            # Separate Main Allocations vs Backups/Relievers
            main_allocations = []
            backup_allocations = []
            
            for row in schedule_data:
                role = row.get('Role', '')
                if 'BLOCK SUPERVISOR' in role:
                    main_allocations.append(row)
                else:
                    backup_allocations.append(row)

            # AGGREGATE ROWS FOR VIEW
            main_allocations = aggregate_schedule_rows(main_allocations)
            backup_allocations = aggregate_schedule_rows(backup_allocations)

            # CALCULATE ROW SPANS
            main_allocations = calculate_row_spans(main_allocations)
            backup_allocations = calculate_row_spans(backup_allocations)

            # 3. Fetch Issues & Suggestions
            issues = db.get_open_issues(selected_exam)
            # Enrich issues with swap suggestions
            for issue in issues:
                # issue is a dict-like RealDictRow
                suggestions = find_swap_candidates(
                    schedule_data, # Use raw schedule_data for logic
                    issue['date'],
                    issue['time'],
                    issue['supervisor_name']
                )
                issue['suggestions'] = suggestions

            # 2. Schedule HTML Pivot (For Main only)
            schedule_html = ""
            if main_allocations:
                try:
                    df = pd.DataFrame(main_allocations)
                    
                    # Create display value
                    df['Display'] = df['Supervisor']
                    
                    chart = df.pivot_table(
                        index=['Day', 'Session'], 
                        columns='Block', 
                        values='Display', 
                        aggfunc=lambda x: '<br>'.join(x)
                    ).fillna("-")
                    
                    schedule_html = chart.to_html(classes='table table-striped table-bordered text-center', border=0, escape=False)
                except Exception as ex:
                    schedule_html = f"<p class='text-danger'>Chart unavailable: {str(ex)}</p>"
            else:
                 schedule_html = "<p>No main allocations found.</p>"

            return render_template('result.html', 
                                   duty_report=sorted_duties, 
                                   schedule_table=schedule_html, 
                                   schedule_data=schedule_data,
                                   main_allocations=main_allocations,
                                   backup_allocations=backup_allocations,
                                   exam_name=selected_exam,
                                   issues=issues,
                                   is_history=True)
                                   
    return render_template('index.html', exams=exams)
    
@app.route('/configure', methods=['POST'])
@admin_required
def configure():
    try:
        # Check if files are present
        if 'blocks_file' not in request.files or 'supervisors_file' not in request.files:
            flash("Please upload both Excel files (Blocks/Rooms and Supervisors).", "danger")
            return redirect(url_for('admin_dashboard'))
            
        blocks_file = request.files['blocks_file']
        supervisors_file = request.files['supervisors_file']
        
        # Check if files were actually selected
        if not blocks_file.filename or not supervisors_file.filename:
            flash("Please select both Excel files before proceeding.", "danger")
            return redirect(url_for('admin_dashboard'))
        
        # Validate file extensions
        allowed_extensions = {'.xlsx', '.xls'}
        blocks_ext = os.path.splitext(blocks_file.filename)[1].lower()
        supervisors_ext = os.path.splitext(supervisors_file.filename)[1].lower()
        
        if blocks_ext not in allowed_extensions:
            flash(f"Blocks/Rooms file must be an Excel file (.xlsx or .xls). Got: {blocks_ext}", "danger")
            return redirect(url_for('admin_dashboard'))
        
        if supervisors_ext not in allowed_extensions:
            flash(f"Supervisors file must be an Excel file (.xlsx or .xls). Got: {supervisors_ext}", "danger")
            return redirect(url_for('admin_dashboard'))
        
        # Read Rooms file with validation
        try:
            df_rooms = pd.read_excel(blocks_file)
            
            # Check if file is empty
            if df_rooms.empty:
                flash("Blocks/Rooms Excel file is empty. Please provide room data.", "danger")
                return redirect(url_for('admin_dashboard'))
            
            # Check if file has at least 2 columns
            if len(df_rooms.columns) < 2:
                flash("Blocks/Rooms file must have at least 2 columns (Room No and Capacity).", "danger")
                return redirect(url_for('admin_dashboard'))
            
            # Try to parse rooms
            rooms = []
            for index, row in df_rooms.iterrows():
                try:
                    room_name = str(row.iloc[0])
                    capacity_val = row.iloc[1]
                    
                    # Validate room name
                    if not room_name or room_name.lower() == 'nan':
                        continue
                    
                    # Validate capacity is numeric
                    capacity = int(float(capacity_val))
                    
                    rooms.append({
                        'name': room_name,
                        'capacity': capacity
                    })
                except (ValueError, TypeError) as e:
                    flash(f"Invalid data in Blocks/Rooms file at row {index + 2}. Capacity must be numeric.", "danger")
                    return redirect(url_for('admin_dashboard'))
            
            # Check if we got any valid rooms
            if not rooms:
                flash("No valid rooms found in the Blocks/Rooms file. Please check the file format.", "danger")
                return redirect(url_for('admin_dashboard'))
                
        except Exception as e:
            flash(f"Error reading Blocks/Rooms file: {str(e)}", "danger")
            return redirect(url_for('admin_dashboard'))
        
        # Read Supervisors file with validation
        try:
            df_supervisors = pd.read_excel(supervisors_file)
            
            # Check if file is empty
            if df_supervisors.empty:
                flash("Supervisors Excel file is empty. Please provide supervisor data.", "danger")
                return redirect(url_for('admin_dashboard'))
            
            # Check if file has at least 1 column
            if len(df_supervisors.columns) < 1:
                flash("Supervisors file must have at least 1 column (Name).", "danger")
                return redirect(url_for('admin_dashboard'))
            
            # Process Supervisors List
            supervisors_db_data = [] # For UPSERT
            
            # Check if 'Password' column exists, else default
            has_password = 'Password' in df_supervisors.columns
            
            # Normalize column names just in case
            df_supervisors.columns = [c.strip() for c in df_supervisors.columns]
            
            # Assuming Name is 'Name' and Email is 'Email ids' (or column 2 and 4 fallback)
            col_name = 'Name' if 'Name' in df_supervisors.columns else df_supervisors.columns[2]
            col_email = 'Email ids' if 'Email ids' in df_supervisors.columns else (df_supervisors.columns[4] if len(df_supervisors.columns) > 4 else None)
            
            if not col_email:
                 flash("Could not find 'Email ids' column. Please ensure format is correct.", "danger")
                 return redirect(url_for('admin_dashboard'))

            for index, row in df_supervisors.iterrows():
                name = str(row[col_name]).strip()
                email = str(row[col_email]).strip().lower()
                
                if not name or name.lower() == 'nan': 
                    continue
                if not email or email.lower() == 'nan':
                     continue
                
                password = '123456'
                if has_password:
                    val = row.get('Password')
                    if pd.notna(val):
                        password = str(val)
                
                supervisors_db_data.append({'name': name, 'email': email, 'password': password})
            
            # Check if we got any valid supervisors
            if not supervisors_db_data:
                flash("No valid supervisors found in the Supervisors file. Please check the file format.", "danger")
                return redirect(url_for('admin_dashboard'))
                
        except Exception as e:
            flash(f"Error reading Supervisors file: {str(e)}", "danger")
            return redirect(url_for('admin_dashboard'))
        
        # SAVE TO DB
        db.upsert_blocks(rooms)
        db.upsert_supervisors(supervisors_db_data)
        
        flash(f"Successfully loaded {len(rooms)} rooms and {len(supervisors_db_data)} supervisors.", "success")
        
        # Check for Timetable PDF and SAVE IT
        if 'timetable_pdf' in request.files:
            pdf = request.files['timetable_pdf']
            if pdf and pdf.filename:
                pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_timetable.pdf')
                pdf.save(pdf_path)
        
        # REDIRECT TO ROLE DEFINITION
        # Fetch fresh list from DB (to get current roles/defaults)
        full_supervisors = db.get_all_supervisors()
        return render_template('define_roles.html', supervisors=full_supervisors)
                               
    except Exception as e:
        flash(f"An unexpected error occurred: {str(e)}", "danger")
        return redirect(url_for('admin_dashboard'))

@app.route('/save_roles', methods=['POST'])
@admin_required
def save_roles():
    try:
        # 1. Collect Form Data
        updates = []
        # We need to loop through submitted data. Since we used loop.index0 in template...
        # But we don't know how many rows. We can iterate request.form keys.
        
        # Easier strategy: We passed email as hidden field 'email_{i}'.
        # Find all keys starting with 'email_'
        for key in request.form:
            if key.startswith('email_'):
                idx = key.split('_')[1]
                email = request.form.get(f'email_{idx}')
                role = request.form.get(f'role_{idx}')
                start = request.form.get(f'start_{idx}')
                end = request.form.get(f'end_{idx}')
                
                # Normalize empty dates
                if not start: start = None
                if not end: end = None
                
                updates.append({
                    'email': email,
                    'role': role,
                    'start': start,
                    'end': end
                })
        
        # 2. Update DB
        if updates:
             db.update_supervisor_details(updates)
             flash(f"Updated roles for {len(updates)} supervisors.", "success")
             
        # 3. Proceed to PDF Extraction (Original /configure logic continues here)
        pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_timetable.pdf')
        preloaded_sessions = []
        
        if os.path.exists(pdf_path):
             try:
                 # Try Gemini first if API Key exists
                 if os.getenv('GEMINI_API_KEY'):
                     flash("Attempting PDF extraction with Gemini...")
                     preloaded_sessions = extract_pdf.parse_schedule_with_gemini(pdf_path)
                 
                 # Fallback or if Gemini returns empty
                 if not preloaded_sessions:
                     if os.getenv('GEMINI_API_KEY'):
                          flash("Gemini returned no data, falling back to local extractor.")
                     preloaded_sessions = extract_pdf.extract_sessions_from_pdf(pdf_path)
                 
                 flash(f"Extracted {len(preloaded_sessions)} sessions from PDF.")
             except Exception as ex:
                 flash(f"Error extracting PDF: {str(ex)}", "warning")
        else:
             flash("No PDF file found from previous step. Please start over if needed.", "warning")

        # 4. Fetch Data for configure.html
        rooms = db.get_all_blocks()
        full_supervisors = db.get_all_supervisors()
        
        # Convert supervisors to list of strings "Name (Email)" for JS compatibility
        # Filter: Exclude HODs from the dropdown
        supervisors_names_only = [
            f"{s['name']} ({s['email']})" 
            for s in full_supervisors 
            if s.get('role') != 'HOD'
        ]
        
        # Prepare constraints for frontend (Pre-filling unavailability)
        # Format: {"Name (Email)": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}}
        supervisor_constraints = {}
        for s in full_supervisors:
            if s.get('unavailable_start') and s.get('unavailable_end'):
                key = f"{s['name']} ({s['email']})"
                supervisor_constraints[key] = {
                    "start": s['unavailable_start'],
                    "end": s['unavailable_end']
                }
    
        # Render with constraints
        return render_template('configure.html',
                               rooms_json=json.dumps(rooms),
                               supervisors_json=json.dumps(supervisors_names_only),
                               preloaded_sessions=json.dumps(preloaded_sessions),
                               supervisor_constraints=json.dumps(supervisor_constraints))

    except Exception as e:
        flash(f"An unexpected error occurred saving roles: {str(e)}", "danger")
        return redirect(url_for('admin_dashboard'))

@app.route('/generate', methods=['POST'])
@admin_required
def generate():
    try:
        rooms = json.loads(request.form.get('rooms_json'))
        # supervisors = json.loads(request.form.get('supervisors_json')) # OLD: Strings
        
        # NEW: Fetch full supervisor details from DB to get Roles and Dates
        supervisors_data = db.get_all_supervisors()
        # Pass this list of dicts to scheduler
        
        session_ids = request.form.getlist('session_ids')
        exam_name = request.form.get('exam_name', 'Untitled Exam')
        
        # Parse global unavailability rules
        unavailability_rules = []
        unavailability_rules_json = request.form.get('unavailability_rules', '[]')
        try:
            unavailability_rules = json.loads(unavailability_rules_json)
        except:
            unavailability_rules = []
        
        sessions_data = []
        for sid in session_ids:
            # Try new fields first
            date_val = request.form.get(f'date_{sid}')
            start_time_val = request.form.get(f'start_time_{sid}')
            end_time_val = request.form.get(f'end_time_{sid}')
            subject_val = request.form.get(f'subject_{sid}')
            department_val = request.form.get(f'department_{sid}')
            
            # Fallback / Compatibility
            day = request.form.get(f'day_{sid}')
            s_type = request.form.get(f'session_type_{sid}')
            
            students = request.form.get(f'total_students_{sid}')
            unavailable = request.form.getlist(f'unavailable_{sid}')
            
            # Logic: If we have date/time/subject, use them. Else construct from day/session.
            if students:
                item = {
                    'total_students': int(students),
                    'unavailable': unavailable,
                    '_id': sid 
                }
                
                if date_val and start_time_val and end_time_val:
                    item['date'] = date_val
                    # Use formatted combined string for Scheduler Slot Key
                    item['time'] = f"{start_time_val} - {end_time_val}"
                    item['subject'] = subject_val or "General"
                    item['department'] = department_val or ""
                    # Legacy fields just in case
                    item['day'] = 0 
                    item['session'] = item['time']
                    
                    # Apply global unavailability rules
                    for rule in unavailability_rules:
                        rule_time = f"{rule['start_time']} - {rule['end_time']}"
                        if item['date'] == rule['date'] and item['time'] == rule_time:
                            # Merge supervisors from rule
                            item['unavailable'].extend(rule['supervisors'])
                    
                    # Remove duplicates
                    item['unavailable'] = list(set(item['unavailable']))
                    
                elif day and s_type:
                     item['day'] = int(day)
                     item['session'] = s_type
                     item['date'] = f"Day {day}"
                     item['time'] = s_type
                     item['subject'] = "General"
                
                sessions_data.append(item)

        # Generate (pass full objects)
        result = scheduler.generate_schedule(rooms, supervisors_data, sessions_data)
        
        # Process & Save
        schedule_data = result['schedule']
        
        # SAVE TO DB (New Snapshot method)
        if schedule_data:
            input_snapshot = {
                'rooms': rooms,
                'supervisors': supervisors_data, # Save full details
                'sessions_data': sessions_data
            }
            db.save_schedule(exam_name, input_snapshot, schedule_data)
            
            # --- SEND EMAILS ---
            try:
                flash("Schedule saved. Sending notification emails...", "info")
                print("--- STARTING EMAIL NOTIFICATIONS ---")
                
                # 0. Generate Master PDF & Workload PDF for Admin
                try:
                    admin_pdf_bytes = _generate_timetable_pdf_bytes(exam_name, schedule_data)
                    workload_pdf_bytes = _generate_workload_pdf_bytes(exam_name, schedule_data)
                    
                    print(f"Generated Admin PDF: {len(admin_pdf_bytes)} bytes")
                    print(f"Generated Workload PDF: {len(workload_pdf_bytes)} bytes")
                    
                    admin_email = app.config.get('MAIL_ADMIN')
                    if admin_email:
                        print(f"Sending Admin Notification to {admin_email}")
                        mailer.send_admin_schedule_notification(admin_email, exam_name, admin_pdf_bytes, workload_pdf_bytes, "Generated")
                    else:
                        print("MAIL_ADMIN not set, skipping Admin email.")
                except Exception as e_admin:
                    print(f"ERROR Sending Admin Email: {e_admin}")
                
                # 1. Group by Supervisor
                supervisor_schedules = {}
                for row in schedule_data:
                    sup_name = row.get('Supervisor')
                    if sup_name and sup_name != 'NA' and sup_name != 'NOBODY AVAILABLE':
                        if sup_name not in supervisor_schedules:
                            supervisor_schedules[sup_name] = []
                        supervisor_schedules[sup_name].append(row)
                
                print(f"Found {len(supervisor_schedules)} supervisors to notify.")
                        
                # 2. Get Supervisors to find Emails
                sup_lookup = {s['name']: s['email'] for s in supervisors_data}
                
                # 3. Send Emails
                count_sent = 0
                for sup_name, rows in supervisor_schedules.items():
                    # Extract email logic...
                    email = None
                    if "(" in sup_name and sup_name.endswith(")"):
                        parts = sup_name.rsplit('(', 1)
                        if len(parts) > 1:
                            email = parts[1].rstrip(')').strip()
                    if not email:
                         email = sup_lookup.get(sup_name)
                         
                    if email:
                        try:
                            # Generate PERSONAL PDF
                            sup_pdf_bytes = _generate_supervisor_pdf_bytes(exam_name, sup_name, rows)
                            print(f"Sending Superviser Email to {sup_name} ({email}) - PDF: {len(sup_pdf_bytes)} bytes")
                            mailer.send_schedule_notification(email, sup_name, exam_name, rows, pdf_bytes=sup_pdf_bytes)
                            count_sent += 1
                        except Exception as e_sup:
                             print(f"ERROR Sending Email to {sup_name}: {e_sup}")
                    else:
                        print(f"Skipping {sup_name} - No Email Found")
                
                if count_sent > 0:
                     flash(f"Emails triggered for {count_sent} supervisors + Admin.", "success")
                else:
                     flash("No supervisor emails sent (Emails not found). Admin email sent if configured.", "warning")
                
                print(f"--- EMAIL NOTIFICATIONS DONE. Sent: {count_sent} ---")
                     
            except Exception as e:
                print(f"--- CRITICAL EMAIL ERROR: {e} ---")
                flash(f"Error sending emails: {str(e)}", "danger")
        
        # Separate Main Allocations vs Backups/Relievers
        main_allocations = []
        backup_allocations = []
        
        if schedule_data:
            for row in schedule_data:
                role = row.get('Role', '')
                if 'BLOCK SUPERVISOR' in role:
                    main_allocations.append(row)
                else:
                    backup_allocations.append(row)

        # AGGREGATE ROWS FOR VIEW
        main_allocations = aggregate_schedule_rows(main_allocations)
        backup_allocations = aggregate_schedule_rows(backup_allocations)

        # CALCULATE ROW SPANS
        main_allocations = calculate_row_spans(main_allocations)
        backup_allocations = calculate_row_spans(backup_allocations)

        # Prepare HTML Pivot for Main Allocations Only
        schedule_html = ""
        if main_allocations:
            df = pd.DataFrame(main_allocations)
            try:
                # Same pivot logic but only for Main
                df['Display'] = df['Supervisor']
                # Check columns
                index_cols = ['Date', 'Time'] if 'Date' in df.columns else ['Day', 'Session']
                
                chart = df.pivot_table(
                    index=index_cols, 
                    columns='Block', 
                    values='Display', 
                    aggfunc=lambda x: '<br>'.join(x)
                ).fillna("-")
                
                schedule_html = chart.to_html(classes='table table-striped table-bordered text-center', border=0, escape=False)
            except Exception as ex:
                schedule_html = f"<p class='text-danger'>Chart unavailable: {str(ex)}</p>"
        else:
            schedule_html = "<p>No main allocations generated.</p>"

        duty_counts = result['duties']
        sorted_duties = sorted(duty_counts.items(), key=lambda x: x[1], reverse=True)
        
        return render_template('result.html', 
                               duty_report=sorted_duties, 
                               schedule_table=schedule_html, 
                               schedule_data=schedule_data,
                               main_allocations=main_allocations,
                               backup_allocations=backup_allocations,
                               exam_name=exam_name)

    except Exception as e:
        return f"An error occurred generating schedule: {str(e)}"

# --- PDF Helpers ---

def _generate_timetable_pdf_bytes(exam_name, schedule_data):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    
    # Title
    title_style = styles['Title']
    title_style.fontSize = 16
    title_style.textColor = colors.HexColor("#1e3a8a")
    elements = [Paragraph(f"MASTER TIMETABLE - {exam_name}", title_style)]
    
    # Data Processing
    aggregated_rows = aggregate_schedule_rows(schedule_data)
    
    data = [["Date", "Time", "Block", "Supervisor", "Role", "Subject"]]
    
    cell_style = styles['BodyText']
    cell_style.fontSize = 9
    cell_style.leading = 11
    
    for row in aggregated_rows:
        subj_para = Paragraph(row.get('Subject', ''), cell_style)
        sup_para = Paragraph(row.get('Supervisor', ''), cell_style)
        
        data.append([
            row.get('Date', ''),
            row.get('Time', ''),
            row.get('Block', ''),
            sup_para,
            row.get('Role', '').replace(' SUPERVISOR', ''),
            subj_para
        ])
    
    # Table Styling
    # Widths: Date(90), Time(90), Block(70), Supervisor(190), Role(80), Subject(250)
    table = Table(data, colWidths=[90, 90, 70, 190, 80, 250], repeatRows=1)
    
    style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1e40af")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('ALIGN', (3,1), (3,-1), 'LEFT'),
        ('ALIGN', (5,1), (5,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e5e7eb")),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 10),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f3f4f6")])
    ])
    
    table.setStyle(style)
    elements.append(table)
    
    doc.build(elements)

    return buffer.getvalue()

def _generate_workload_pdf_bytes(exam_name, schedule_data):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    
    elements = []
    title_text = f"SUPERVISOR WORKLOAD REPORT - {exam_name}"
    elements.append(Paragraph(title_text, styles['Title']))
    
    # 1. Calculate Counts
    duty_counts = {}
    seen_assignments = set()
    for row in schedule_data:
        sup = row.get('Supervisor', 'Unknown')
        if sup != 'NA' and sup != 'NOBODY AVAILABLE' and sup:
            key = (sup, row.get('Date'), row.get('Time'), row.get('Block'))
            if key not in seen_assignments:
                duty_counts[sup] = duty_counts.get(sup, 0) + 1
                seen_assignments.add(key)
    
    sorted_duties = sorted(duty_counts.items(), key=lambda x: x[1], reverse=True)
    
    # 2. Build Table Data
    data = [["Supervisor Name", "Total Duties"]]
    for name, count in sorted_duties:
        data.append([name, str(count)])
        
    table = Table(data, colWidths=[350, 100])
    table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e5e7eb")),
            ('ALIGN', (0,1), (0,-1), 'LEFT'),
            ('LEFTPADDING', (0,1), (0,-1), 15),
            ('ALIGN', (1,1), (1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1e40af")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f3f4f6")])
    ]))
    
    elements.append(table)
    doc.build(elements)
    return buffer.getvalue()

def _generate_supervisor_pdf_bytes(exam_name, supervisor_name, my_duties):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    
    elements = []
    elements.append(Paragraph(f"DUTY SCHEDULE - {supervisor_name}", styles['Title']))
    elements.append(Paragraph(f"Exam: {exam_name}", styles['Heading2']))
    elements.append(Paragraph("<br/>", styles['Normal']))
    
    data = [["Date", "Time", "Block", "Role", "Subject"]]
    cell_style = styles['BodyText']
    cell_style.fontSize = 10
    
    for row in my_duties:
        subj_para = Paragraph(row.get('Subject', '-'), cell_style)
        data.append([
            row.get('Date', row.get('Day', '')),
            row.get('Time', row.get('Session', '')),
            row.get('Block', ''),
            row.get('Role', '').replace(' SUPERVISOR', ''),
            subj_para
        ])
        
    table = Table(data, colWidths=[80, 80, 60, 80, 150])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#4f46e5")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (4,1), (4,-1), 'LEFT'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f9fafb")])
    ]))
    
    elements.append(table)
    doc.build(elements)
    return buffer.getvalue()

@app.route('/api/export-pdf', methods=['GET'])
@admin_required
def export_pdf():
    # Fetch data
    selected_exam = request.args.get('exam_name')
    export_type = request.args.get('type', 'timetable') # 'timetable' or 'workload'
    
    if not selected_exam:
        return "Error: Exam Name required.", 400
        
    results = db.get_full_schedule(selected_exam)
    if not results:
        return "Error: No data found for this exam.", 400

    if export_type == 'workload':
        # --- WORKLOAD REPORT ---
        pdf_bytes = _generate_workload_pdf_bytes(selected_exam, results)
        buffer = io.BytesIO(pdf_bytes)
        filename = f"{selected_exam.replace(' ', '_')}_Workload_Report.pdf"
        
    else:
        # --- DETAILED TIMETABLE (Use Helper) ---
        pdf_bytes = _generate_timetable_pdf_bytes(selected_exam, results)
        buffer = io.BytesIO(pdf_bytes)
        filename = f"{selected_exam.replace(' ', '_')}_Timetable.pdf"

    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')

@app.route('/resolve_issue', methods=['POST'])
@admin_required
def resolve_issue():
    issue_id = request.form.get('issue_id')
    exam_name = request.form.get('exam_name')
    action = request.form.get('action') # 'accept' or 'reject'
    rejection_reason = request.form.get('rejection_reason')

    if not issue_id or not exam_name:
         flash("Missing issue ID or exam name.")
         return redirect(url_for('admin_dashboard', exam_name=exam_name))

    if action == 'reject':
        if not rejection_reason:
            flash("Rejection reason is required.")
            return redirect(url_for('admin_dashboard', exam_name=exam_name))
            
        if db.resolve_issue(issue_id, status='REJECTED', rejection_reason=rejection_reason):
            try:
                # 1. Identify Supervisor
                target_sup = request.form.get('target_supervisor')
                
                if target_sup:
                    # 2. Get Email (Extract from "Name (Email)" or Lookup)
                    email = None
                    if "(" in target_sup and target_sup.endswith(")"):
                         parts = target_sup.rsplit('(', 1)
                         if len(parts) > 1:
                             email = parts[1].rstrip(')').strip()
                    
                    if not email:
                        # Fallback
                        all_sups = db.get_all_supervisors()
                        sup_lookup = {s['name']: s['email'] for s in all_sups}
                        email = sup_lookup.get(target_sup)
                    
                    if email:
                        mailer.send_swap_rejection(email, target_sup, exam_name, rejection_reason)
                        flash(f"Rejection email sent to {target_sup}.", "info")
                    else:
                         flash(f"Could not find email for {target_sup} to satisfy notification.", "warning")
                else:
                    flash("Supervisor name missing, could not send email.", "warning")
                    
            except Exception as e_mail:
                flash(f"Error sending rejection email: {e_mail}", "warning")
                
            flash("Issue rejected successfully.")
        else:
            flash("Error rejecting issue.")
        return redirect(url_for('admin_dashboard', exam_name=exam_name))
    
    # If Accept, proceed with swap logic
    
    # Original (Target) details
    supervisor_A = request.form.get('target_supervisor')
    date_A = request.form.get('target_date')
    time_A = request.form.get('target_time')
    
    # Candidate details
    supervisor_B = request.form.get('candidate_supervisor')
    
    # Type of swap
    swap_type = request.form.get('swap_type') # '2-way' or '1-way'
    
    # Their Session (for 2-way)
    date_B = request.form.get('candidate_date')
    time_B = request.form.get('candidate_time')
    
    if not all([supervisor_A, date_A, time_A, supervisor_B]):
        flash("Missing information to resolve issue.")
        return redirect(url_for('admin_dashboard', exam_name=exam_name))
        
    # Logic to Update Schedule
    schedule_data = db.get_full_schedule(exam_name)
    if not schedule_data:
        flash("Could not load schedule.")
        return redirect(url_for('admin_dashboard', exam_name=exam_name))
        
    updated = False
    
    # 1. Assign A's slot to B
    for row in schedule_data:
        if (row['Supervisor'] == supervisor_A and 
            row.get('Date') == date_A and 
            row.get('Time') == time_A):
            row['Supervisor'] = supervisor_B
            # If swapped to backup, logic remains same (just name change)
            updated = True
            break
            
    if not updated:
        flash("Could not find original slot to swap.")
        return redirect(url_for('admin_dashboard', exam_name=exam_name))
        
    # 2. If 2-way, Assign B's slot to A
    if swap_type == '2-way' and date_B and time_B:
        updated_B = False
        for row in schedule_data:
            if (row['Supervisor'] == supervisor_B and 
                row.get('Date') == date_B and 
                row.get('Time') == time_B):
                row['Supervisor'] = supervisor_A
                updated_B = True
                break
        if not updated_B:
            flash("Could not find candidate's slot to swap returned.")
            # Rolling back? In memory, just don't save.
            return redirect(url_for('admin_dashboard', exam_name=exam_name))
            
    # Save
    if db.update_schedule(exam_name, schedule_data):
        db.resolve_issue(issue_id, status='RESOLVED')
        
        # --- EMAIL NOTIFICATION (ACCEPT) ---
        try:
            flash("Swap successful. Sending emails...", "info")
            # 1. Get Emails
            all_sups = db.get_all_supervisors()
            sup_lookup = {s['name']: s['email'] for s in all_sups}
            
            def get_email_safe(identifier, lookup):
                if not identifier: return None
                if "(" in identifier and identifier.endswith(")"):
                    parts = identifier.rsplit('(', 1)
                    if len(parts) > 1:
                        return parts[1].rstrip(')').strip()
                return lookup.get(identifier)

            email_A = get_email_safe(supervisor_A, sup_lookup)
            email_B = get_email_safe(supervisor_B, sup_lookup)
            
            # 2. Get New Schedules (Filter from the `schedule_data` we just updated!)
            sched_A = [r for r in schedule_data if r['Supervisor'] == supervisor_A]
            sched_B = [r for r in schedule_data if r['Supervisor'] == supervisor_B]
            
            # 3. Generate PDFs for Supervisors
            pdf_A_bytes = _generate_supervisor_pdf_bytes(exam_name, supervisor_A, sched_A)
            pdf_B_bytes = _generate_supervisor_pdf_bytes(exam_name, supervisor_B, sched_B)

            # 4. Generate PDFs for Admin (Updated Master + Workload)
            admin_pdf_bytes = _generate_timetable_pdf_bytes(exam_name, schedule_data)
            workload_pdf_bytes = _generate_workload_pdf_bytes(exam_name, schedule_data)
            
            # 5. Send to Supervisors
            if email_A and email_B:
                 mailer.send_swap_acceptance(email_A, supervisor_A, email_B, supervisor_B, exam_name, sched_A, sched_B, pdf_A_bytes, pdf_B_bytes)
                 flash("Emails sent to both supervisors.", "success")
            else:
                 flash("Could not find emails for one or both supervisors.", "warning")
            
            # 6. Send to Admin
            admin_email = app.config.get('MAIL_ADMIN')
            if admin_email:
                mailer.send_admin_schedule_notification(admin_email, exam_name, admin_pdf_bytes, workload_pdf_bytes, "Updated (Swap Accepted)")
            
        except Exception as e_mail:
            print(f"Error sending acceptance emails: {e_mail}")
            flash(f"Error sending acceptance emails: {str(e_mail)}", "warning")
        flash(f"Swap successful. {supervisor_A} and {supervisor_B} swapped.")
    else:
        flash("Error saving updated schedule.")
        
    return redirect(url_for('admin_dashboard', exam_name=exam_name))

@app.route('/api/export-supervisor-pdf', methods=['GET'])
@login_required
def export_supervisor_pdf():
    name = session.get('user_name')
    selected_exam = request.args.get('exam_name')
    
    if not selected_exam or not name:
        return "Error: Exam Name and Login required.", 400
        
    # Reuse db logic but specific to supervisor
    my_schedule = db.get_schedule_for_supervisor(selected_exam, name)
    
    if not my_schedule:
        return "Error: No duties found for this exam.", 400

    pdf_bytes = _generate_supervisor_pdf_bytes(selected_exam, name, my_schedule)
    buffer = io.BytesIO(pdf_bytes)
    
    filename = f"{name.replace(' ', '_')}_{selected_exam.replace(' ', '_')}_Schedule.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')

@app.route('/api/test-email', methods=['GET', 'POST'])
@admin_required
def test_email_route():
    recipient = request.args.get('email') or app.config['MAIL_DEFAULT_SENDER']
    if not recipient:
        return "No recipient email configured. Check MAIL_DEFAULT_SENDER or pass ?email=..."
    
    # Debug Info
    username = app.config.get('MAIL_USERNAME', 'Not Set')
    password = app.config.get('MAIL_PASSWORD', 'Not Set')
    server = app.config.get('MAIL_SERVER', 'Not Set')
    
    masked_pw = f"{password[:2]}...{password[-2:]} (Len: {len(password)})" if password and len(str(password)) > 4 else "Too Short/None"
    debug_info = f"""
    <div style="background:#f0f0f0; padding:10px; margin-bottom:10px; border:1px solid #ccc;">
        <strong>Loaded Config:</strong><br>
        Server: {server}<br>
        Username: {username}<br>
        Password: {masked_pw}<br>
    </div>
    """
    
    success, msg = mailer.test_email_connection(app, recipient)
    
    if success:
        return f"{debug_info}<h3 style='color:green'>Success</h3><p>{msg}</p><p>Check inbox for {recipient}</p>"
    else:
        return f"{debug_info}<h3 style='color:red'>Failed</h3><p>Error: {msg}</p><p>Check your .env file for spaces or quotes around values.</p>"

# --- Supervisor Routes ---

@app.route('/supervisor')
@login_required
def supervisor_dashboard():
    # Use user_identifier (Name (Email)) for finding duties
    user_identifier = session.get('user_identifier', session.get('user_name'))
    user_name_simple = session.get('user_name') # Just name for display
    
    # 1. Fetch available exams that have schedules
    available_exams = db.get_available_exams() # Returns [{'name':..., 'date':...}, ...]
    
    # 2. Check if a specific exam is selected OR default to latest
    selected_exam = request.args.get('exam_name')
    if not selected_exam and available_exams:
        selected_exam = available_exams[0]['name']
        
    my_schedule = []
    pending_issues = {} # Dict: Key -> Status String
    
    try:
        if selected_exam:
            # Fetch my duties using Identifier
            # Note: get_schedule_for_supervisor might need simple name or identifier depending on how it was saved
            # In login we set identifier = Name (Email). In configure we saved Name (Email).
            # So passing identifier is correct.
            raw_sched = db.get_schedule_for_supervisor(selected_exam, user_identifier)
            aggregated = aggregate_schedule_rows(raw_sched)
            my_schedule = calculate_row_spans(aggregated)
            
            # Fetch my issues history
            issues_history = db.get_supervisor_issues_history(selected_exam, user_identifier)
            
            for issue in issues_history:
                # Key: (Date, Time, Block) - Normalize strings
                i_date = issue['date'].strip() if issue['date'] else ''
                i_time = issue['time'].strip() if issue['time'] else ''
                i_block = issue['block'].strip() if issue['block'] else ''
                
                key = (i_date, i_time, i_block)
                
                if key not in pending_issues:
                    if issue['status'] == 'OPEN':
                        pending_issues[key] = 'PENDING'
                    elif issue['status'] == 'REJECTED':
                        pending_issues[key] = f"REJECTED: {issue.get('rejection_reason', 'No reason given')}"
            
    except Exception as e:
        flash(f"Error loading schedule: {e}")
            
    return render_template('supervisor_dashboard.html', 
                           exams=available_exams, 
                           selected_exam=selected_exam, 
                           schedule=my_schedule, 
                           name=user_name_simple,
                           pending_issues=pending_issues)
                           
@app.route('/report_issue', methods=['POST'])
@login_required
def report_issue_route():
    exam_name = request.form.get('exam_name')
    date = request.form.get('date')
    time = request.form.get('time')
    block = request.form.get('block')
    reason = request.form.get('reason')
    
    # Optional swap selection
    candidate_supervisor = request.form.get('candidate_supervisor')
    candidate_date = request.form.get('candidate_date')
    candidate_time = request.form.get('candidate_time')
    candidate_block = request.form.get('candidate_block')
    swap_type = request.form.get('swap_type')
    
    candidate_data = None
    if candidate_supervisor:
        candidate_data = {
            'candidate_supervisor': candidate_supervisor,
            'candidate_date': candidate_date,
            'candidate_time': candidate_time,
            'candidate_block': candidate_block,
            'swap_type': swap_type
        }
    
    # Use identifier
    supervisor_name = session.get('user_identifier', session.get('user_name'))
    
    success, msg = db.report_issue(exam_name, supervisor_name, date, time, block, reason, candidate_data)
    
    if success:
        try:
            admin_email = app.config.get('MAIL_ADMIN')
            if admin_email:
                mailer.send_issue_reported_notification(admin_email, exam_name, supervisor_name, reason)
        except:
            pass
        flash("Issue reported successfully.")
    else:
        flash(f"Error reporting issue: {msg}")
        
    return redirect(url_for('supervisor_dashboard', exam_name=exam_name))

if __name__ == '__main__':
    # host='0.0.0.0' makes the server accessible on your local network
    # This allows you to access it from your phone using your computer's IP address
    app.run(host='0.0.0.0', port=5000, debug=True)
