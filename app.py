from flask import Flask, render_template, request, session, redirect, url_for, flash
import pandas as pd
import scheduler
import json
import os
from functools import wraps
from config import Config
import db
import extract_pdf
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from flask import send_file

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

@app.route('/reset_password', methods=['POST'])
def reset_password():
    name = request.form.get('name').strip()
    old_password = request.form.get('old_password')
    new_password = request.form.get('new_password')
    
    if not name or not old_password or not new_password:
        flash("All fields are required.")
        return redirect(url_for('login'))
        
    # Verify Old Password
    if db.verify_supervisor(name, old_password):
        # Update to New Password
        if db.update_supervisor_password(name, new_password):
            flash("Password updated successfully. Please login.")
        else:
            flash("Error updating password. Please try again.")
    else:
        flash("Invalid Name or Old Password.")
        
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
            supervisors_db_data = []
            supervisors_names_only = []
            
            # Check if 'Password' column exists, else default
            has_password = 'Password' in df_supervisors.columns
            
            # Assuming Name is Col 0
            for index, row in df_supervisors.iterrows():
                name = str(row.iloc[0]).strip()
                if not name or name.lower() == 'nan': 
                    continue
                
                password = '123456'
                if has_password:
                    val = row['Password']
                    if pd.notna(val):
                        password = str(val)
                
                supervisors_db_data.append({'name': name, 'password': password})
                supervisors_names_only.append(name)
            
            # Check if we got any valid supervisors
            if not supervisors_names_only:
                flash("No valid supervisors found in the Supervisors file. Please check the file format.", "danger")
                return redirect(url_for('admin_dashboard'))
                
        except Exception as e:
            flash(f"Error reading Supervisors file: {str(e)}", "danger")
            return redirect(url_for('admin_dashboard'))
        
        # SAVE TO DB
        db.upsert_blocks(rooms)
        db.upsert_supervisors(supervisors_db_data)
        
        flash(f"Successfully loaded {len(rooms)} rooms and {len(supervisors_names_only)} supervisors.", "success")
        
        # Check for Timetable PDF
        preloaded_sessions = []
        if 'timetable_pdf' in request.files:
            pdf = request.files['timetable_pdf']
            if pdf and pdf.filename:
                pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_timetable.pdf')
                pdf.save(pdf_path)
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
        
        return render_template('configure.html', 
                               rooms_json=json.dumps(rooms), 
                               supervisors_json=json.dumps(supervisors_names_only),
                               preloaded_sessions=json.dumps(preloaded_sessions))
                               
    except Exception as e:
        flash(f"An unexpected error occurred: {str(e)}", "danger")
        return redirect(url_for('admin_dashboard'))

@app.route('/generate', methods=['POST'])
@admin_required
def generate():
    try:
        rooms = json.loads(request.form.get('rooms_json'))
        supervisors = json.loads(request.form.get('supervisors_json'))
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

        # Generate
        result = scheduler.generate_schedule(rooms, supervisors, sessions_data)
        
        # Process & Save
        schedule_data = result['schedule']
        
        # SAVE TO DB (New Snapshot method)
        if schedule_data:
            input_snapshot = {
                'rooms': rooms,
                'supervisors': supervisors,
                'sessions_data': sessions_data
            }
            db.save_schedule(exam_name, input_snapshot, schedule_data)
        
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

@app.route('/api/export-pdf', methods=['GET'])
@admin_required
def export_pdf():
    # Fetch data
    selected_exam = request.args.get('exam_name')
    if not selected_exam:
        return "Error: Exam Name required.", 400
        
    results = db.get_full_schedule(selected_exam)
    if not results:
        return "Error: No data found for this exam.", 400

    # Aggregate rows to match dashboard view (combines subjects/counts)
    results = aggregate_schedule_rows(results)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
    elements = []
    styles = getSampleStyleSheet()
    
    title_text = f"VIT EXAM CELL - GLOBAL MASTER DUTY LIST - {selected_exam}"
    elements.append(Paragraph(title_text, styles['Title']))
    
    # Headers
    # Removed Count as requested
    data = [["Date", "Slot", "Room", "Supervisor", "Role", "Subject"]]
    
    # Create a custom style for the table cells to handle wrapping
    cell_style = styles['BodyText']
    cell_style.fontSize = 9
    cell_style.leading = 11

    for row in results:
        # Wrap Subject in Paragraph for auto-newline
        subj_text = row.get('Subject', '')
        subj_para = Paragraph(subj_text, cell_style)
        
        data.append([
            row.get('Date', ''),
            row.get('Time', ''),
            row.get('Block', ''),
            Paragraph(row.get('Supervisor', ''), cell_style), # Wrap supervisor too just in case
            row.get('Role', '').replace(' SUPERVISOR', ''),
            subj_para
        ])

    # Adjusted widths to fill A4 Landscape (~800pt usable)
    # Total: 90+90+60+150+80+300 = 770
    table = Table(data, colWidths=[90, 90, 60, 150, 80, 300])
    
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#002d62")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (3,1), (3,-1), 'LEFT'), 
        ('ALIGN', (5,1), (5,-1), 'LEFT'),
    ]))
    
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    
    filename = f"{selected_exam.replace(' ', '_')}_Duty_List.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')

@app.route('/resolve_issue', methods=['POST'])
@admin_required
def resolve_issue():
    issue_id = request.form.get('issue_id')
    exam_name = request.form.get('exam_name')
    
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
    
    if not all([issue_id, exam_name, supervisor_A, date_A, time_A, supervisor_B]):
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
        db.resolve_issue(issue_id)
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

    buffer = io.BytesIO()
    # Portrait might be better for single person, but keeping Landscape for consistency if needed. 
    # Let's use Portrait for personal schedule
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()
    
    elements.append(Paragraph(f"DUTY SCHEDULE - {name.upper()}", styles['Title']))
    elements.append(Paragraph(f"Exam: {selected_exam}", styles['Heading2']))
    
    # Headers
    data = [["Date", "Time", "Block", "Role", "Subject"]]
    
    cell_style = styles['BodyText']
    cell_style.fontSize = 10
    
    for row in my_schedule:
        subj_para = Paragraph(row.get('Subject', '-'), cell_style)
        
        data.append([
            row.get('Date', row.get('Day', '')),
            row.get('Time', row.get('Session', '')),
            row.get('Block', ''),
            row.get('Role', '').replace(' SUPERVISOR', ''),
            subj_para
        ])

    # A4 Portrait Width ~ 595pt - margins -> ~450pt usable?
    # ReportLab default margins are ~72pt each side? 
    # Let's assume ~450pt safe width. 
    # [80, 80, 60, 80, 150] = 450
    table = Table(data, colWidths=[80, 80, 60, 80, 150])
    
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#4f46e5")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (4,1), (4,-1), 'LEFT'),
    ]))
    
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    
    filename = f"{name.replace(' ', '_')}_{selected_exam.replace(' ', '_')}_Schedule.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')

# --- Supervisor Routes ---

@app.route('/supervisor')
@login_required
def supervisor_dashboard():
    name = session.get('user_name')
    
    # 1. Get List of Exams
    available_exams = db.get_available_exams()
    
    # 2. Check if specific exam selected
    selected_exam = request.args.get('exam_name')
    
    my_schedule = []
    pending_issues = set()  # Store (date, time, block) tuples for sessions with pending issues
    
    try:
        if selected_exam:
            raw_sched = db.get_schedule_for_supervisor(selected_exam, name)
            aggregated = aggregate_schedule_rows(raw_sched)
            my_schedule = calculate_row_spans(aggregated)
            
            # Get issues for this supervisor in this exam
            issues = db.get_open_issues(selected_exam)
            for issue in issues:
                if issue.get('supervisor_name') == name:
                    pending_issues.add((issue.get('date'), issue.get('time'), issue.get('block')))
    except Exception as e:
        flash(f"Error loading schedule: {e}")
            
    return render_template('supervisor_dashboard.html', 
                           exams=available_exams, 
                           selected_exam=selected_exam, 
                           schedule=my_schedule, 
                           name=name,
                           pending_issues=pending_issues)

@app.route('/report_issue', methods=['POST'])
@login_required
def report_issue():
    exam_name = request.form.get('exam_name')
    date = request.form.get('date')
    time = request.form.get('time')
    block = request.form.get('block')
    reason = request.form.get('reason')
    supervisor_name = session.get('user_name')
    
    if not all([exam_name, date, time, block, supervisor_name]):
        flash("Missing information for reporting issue.")
        return redirect(url_for('supervisor_dashboard', exam_name=exam_name))
        
    success, msg = db.report_issue(exam_name, supervisor_name, date, time, block, reason)
    flash(msg)
    return redirect(url_for('supervisor_dashboard', exam_name=exam_name))

if __name__ == '__main__':
    # host='0.0.0.0' makes the server accessible on your local network
    # This allows you to access it from your phone using your computer's IP address
    app.run(host='0.0.0.0', port=5000, debug=True)
