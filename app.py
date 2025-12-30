from flask import Flask, render_template, request
import pandas as pd
import scheduler

app = Flask(__name__)

import json

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/configure', methods=['POST'])
def configure():
    try:
        # 1. Process Excel Files
        if 'blocks_file' not in request.files or 'supervisors_file' not in request.files:
            return "Error: Please upload both Excel files."
            
        blocks_file = request.files['blocks_file']
        supervisors_file = request.files['supervisors_file']
        
        # Read Rooms
        df_rooms = pd.read_excel(blocks_file)
        rooms = []
        for index, row in df_rooms.iterrows():
            rooms.append({
                'name': str(row.iloc[0]),
                'capacity': int(row.iloc[1])
            })
            
        # Read Supervisors
        df_supervisors = pd.read_excel(supervisors_file)
        supervisors = df_supervisors.iloc[:, 0].dropna().astype(str).tolist()
        
        # Serialize to JSON to pass to the next page
        return render_template('configure.html', 
                               rooms_json=json.dumps(rooms), 
                               supervisors_json=json.dumps(supervisors))
                               
    except Exception as e:
        return f"An error occurred reading files: {str(e)}"

@app.route('/generate', methods=['POST'])
def generate():
    try:
        # 1. Extract Config from Hidden JSON
        rooms = json.loads(request.form.get('rooms_json'))
        supervisors = json.loads(request.form.get('supervisors_json'))
        
        # 2. Extract Session Data dynamically
        # The form has specific named inputs per session: day_ID, session_type_ID, etc.
        # We also have a list of all IDs: session_ids
        
        session_ids = request.form.getlist('session_ids')
        
        sessions_data = []
        for sid in session_ids:
            day = request.form.get(f'day_{sid}')
            s_type = request.form.get(f'session_type_{sid}')
            students = request.form.get(f'total_students_{sid}')
            
            # Get unavailable list for this specific session ID
            unavailable = request.form.getlist(f'unavailable_{sid}')
            
            if day and s_type and students:
                sessions_data.append({
                    'day': int(day),
                    'session': s_type,
                    'total_students': int(students),
                    'unavailable': unavailable
                })
            
        # 3. Calculate max day
        max_day = 0
        if sessions_data:
            max_day = max(s['day'] for s in sessions_data)

        # 4. Generate Schedule
        result = scheduler.generate_schedule(max_day, rooms, supervisors, sessions_data)
        
        # 5. Process Output for Display
        duty_counts = result['duties']
        sorted_duties = sorted(duty_counts.items(), key=lambda x: x[1], reverse=True)
        
        schedule_data = result['schedule']
        
        schedule_html = ""
        if schedule_data:
            df = pd.DataFrame(schedule_data)
            chart = df.pivot(index=['Day', 'Session'], columns='Block', values='Supervisor').fillna("-")
            schedule_html = chart.to_html(classes='table table-striped', border=0)
        
        return render_template('result.html', duty_report=sorted_duties, schedule_table=schedule_html)

    except Exception as e:
        return f"An error occurred generating schedule: {str(e)}"

if __name__ == '__main__':
    app.run(debug=True)
