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
            
            # 2. Schedule HTML Pivot
            schedule_html = ""
            try:
                df = pd.DataFrame(schedule_data)
                
                # Create display value
                display_role = df['Role'].apply(lambda x: "M" if "BLOCK" in str(x) else "B")
                df['Display'] = df['Supervisor'] + " (" + display_role + ")"
                
                chart = df.pivot_table(
                    index=['Day', 'Session'], 
                    columns='Block', 
                    values='Display', 
                    aggfunc=lambda x: '<br>'.join(x)
                ).fillna("-")
                
                schedule_html = chart.to_html(classes='table table-striped table-bordered text-center', border=0, escape=False)
            except Exception as ex:
                schedule_html = f"<p class='text-danger'>Chart unavailable: {str(ex)}</p>"
            
            return render_template('result.html', 
                                   duty_report=sorted_duties, 
                                   schedule_table=schedule_html, 
                                   schedule_data=schedule_data,
                                   exam_name=selected_exam,
                                   is_history=True)
                                   
    return render_template('index.html', exams=exams)
    
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
        
        # Check for Timetable PDF
        preloaded_sessions = []
        if 'timetable_pdf' in request.files:
            pdf = request.files['timetable_pdf']
            if pdf and pdf.filename:
                pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_timetable.pdf')
                pdf.save(pdf_path)
                try:
                    preloaded_sessions = extract_pdf.extract_sessions_from_pdf(pdf_path)
                    flash(f"Extracted {len(preloaded_sessions)} sessions from PDF.")
                except Exception as ex:
                    flash(f"Error extracting PDF: {str(ex)}")
        
        return render_template('configure.html', 
                               rooms_json=json.dumps(rooms), 
                               supervisors_json=json.dumps(supervisors_names_only),
                               preloaded_sessions=json.dumps(preloaded_sessions))
                               
    except Exception as e:
        return f"An error occurred reading/saving files: {str(e)}"

@app.route('/generate', methods=['POST'])
@admin_required
def generate():
    try:
        rooms = json.loads(request.form.get('rooms_json'))
        supervisors = json.loads(request.form.get('supervisors_json'))
        session_ids = request.form.getlist('session_ids')
        exam_name = request.form.get('exam_name', 'Untitled Exam')
        
        with open('debug_log.txt', 'w') as f:
            f.write(f"Rooms count: {len(rooms)}\n")
            f.write(f"Supervisors count: {len(supervisors)}\n")
            f.write(f"Session IDs: {session_ids}\n")
            f.write("Form Keys: " + str(list(request.form.keys())) + "\n")
        
        sessions_data = []
        for sid in session_ids:
            # Try new fields first
            date_val = request.form.get(f'date_{sid}')
            start_time_val = request.form.get(f'start_time_{sid}')
            end_time_val = request.form.get(f'end_time_{sid}')
            subject_val = request.form.get(f'subject_{sid}')
            
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
                    # Legacy fields just in case
                    item['day'] = 0 
                    item['session'] = item['time']
                elif day and s_type:
                     item['day'] = int(day)
                     item['session'] = s_type
                     item['date'] = f"Day {day}"
                     item['time'] = s_type
                     item['subject'] = "General"
                
                sessions_data.append(item)
        
        with open('debug_log.txt', 'a') as f:
            f.write(f"Constructed Sessions Data: {json.dumps(sessions_data, indent=2)}\n")

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
        
        # Prepare HTML for display
        schedule_html = ""
        if schedule_data:
            df = pd.DataFrame(schedule_data)
            try:
                # Use pivot_table with custom aggregation to handle Main + Backup in same cell
                # We want to display: "Name (Role) <br> Name (Role)"
                def agg_supervisors(series):
                    return "<br>".join(series)

                # Create display value
                df['Display'] = df['Supervisor'] + " (" + df['Role'].apply(lambda x: "M" if "BLOCK" in x else "B") + ")"
                
                # Check for new columns Date/Time/Subject vs old Day/Session
                index_cols = ['Date', 'Time'] if 'Date' in df.columns else ['Day', 'Session']
                
                chart = df.pivot_table(
                    index=index_cols, 
                    columns='Block', 
                    values='Display', 
                    aggfunc=lambda x: '<br>'.join(x)
                ).fillna("-")
                
                schedule_html = chart.to_html(classes='table table-striped table-bordered text-center', border=0, escape=False)
            except Exception as ex:
                schedule_html = f"<p class='text-danger'>Note: Overview chart generation failed ({str(ex)}). Please refer to the detailed list below.</p>"
            except Exception as ex:
                schedule_html = f"<p class='text-danger'>Note: Overview chart generation failed ({str(ex)}). Please refer to the detailed list below.</p>"
        else:
            schedule_html = "<p>No schedule data generated.</p>"

        duty_counts = result['duties']
        sorted_duties = sorted(duty_counts.items(), key=lambda x: x[1], reverse=True)
        
        return render_template('result.html', duty_report=sorted_duties, schedule_table=schedule_html)

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
    
    try:
        if selected_exam:
            my_schedule = db.get_schedule_for_supervisor(selected_exam, name)
    except Exception as e:
        flash(f"Error loading schedule: {e}")
            
    return render_template('supervisor_dashboard.html', 
                           exams=available_exams, 
                           selected_exam=selected_exam, 
                           schedule=my_schedule, 
                           name=name)

if __name__ == '__main__':
    app.run(debug=True)
