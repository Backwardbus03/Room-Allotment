import pandas as pd
import random
import uuid

def generate_schedule(num_days, rooms, supervisors, sessions_data):
    """
    Generates a balanced exam schedule using Two-Pass Scarcity-Weighted Heuristic.
    Pass 1: Assign Room Supervisors (Main Duties) - Balanced by Main Count.
    Pass 2: Assign Backup Supervisor - Balanced by Total Count.

    Args:
        num_days (int): Number of exam days.
        rooms (list): List of dicts.
        supervisors (list): List of supervisor names.
        sessions_data (list): List of dictionaries containing session details.

    Returns:
        dict: Contains 'schedule_data' (list of dicts) and 'duty_counts' (dict).
    """
    
    # 1. SETUP
    all_supervisors = [s.strip() for s in supervisors if s.strip()]
    main_counts = {name: 0 for name in all_supervisors}
    total_counts = {name: 0 for name in all_supervisors}
    
    schedule_data = []

    # Assign IDs
    for s in sessions_data:
        s['_id'] = str(uuid.uuid4())

    # 2. GLOBAL ANALYSIS (SCARCITY)
    availability_count = {name: 0 for name in all_supervisors}
    session_candidates = {}
    
    for sess in sessions_data:
        unavailable = set(sess.get('unavailable', []))
        candidates = [name for name in all_supervisors if name not in unavailable]
        session_candidates[sess['_id']] = candidates
        for name in candidates:
            availability_count[name] += 1
            
    # 3. PREPARE SESSIONS
    augmented_sessions = []
    for sess in sessions_data:
        total_students = int(sess['total_students'])
        
        # Calculate Rooms Needed
        students_remaining = total_students
        rooms_used = []
        for room in rooms:
            if students_remaining <= 0: break
            used_cap = min(room['capacity'], students_remaining)
            rooms_used.append(room['name'])
            students_remaining -= used_cap
            
        required_main = len(rooms_used)
        candidates = session_candidates[sess['_id']]
        
        # Difficulty = (Available) - (Main Needed)
        # We focus on main constraint first
        difficulty_score = len(candidates) - required_main
        
        augmented_sessions.append({
            'data': sess,
            'rooms_used': rooms_used,
            'candidates': candidates, # This list is static per session
            'score': difficulty_score,
            'assigned_supervisors': [] # Track who is taken in Pass 1
        })
        
    # Sort by Difficulty (Tightest First)
    augmented_sessions.sort(key=lambda x: x['score'])
    
    # ==========================
    # PASS 1: MAIN ASSIGNMENTS
    # ==========================
    for item in augmented_sessions:
        data = item['data']
        rooms_used = item['rooms_used']
        candidates = item['candidates']
        
        needed = len(rooms_used)
        
        # Filter candidates: Only those NOT excluded by user (already done in step 2)
        # But for sorting, we use MAIN counts
        
        # Dynamic Sort:
        # 1. Main Duty Count (Asc) - BALANCE MAIN LOAD
        # 2. Total Availability (Asc) - SCARCITY
        random.shuffle(candidates)
        candidates.sort(key=lambda name: (main_counts[name], availability_count[name]))
        
        selected = candidates[:needed]
        item['assigned_supervisors'] = selected # Save for Pass 2 exclusion
        
        day_str = f"Day {data['day']}"
        sess_str = data['session']
        
        for i, room_name in enumerate(rooms_used):
            if i < len(selected):
                sup = selected[i]
                schedule_data.append({
                    "Day": day_str,
                    "Session": sess_str,
                    "Block": room_name,
                    "Supervisor": sup
                })
                main_counts[sup] += 1
                total_counts[sup] += 1

    # ==========================
    # PASS 2: BACKUP ASSIGNMENTS
    # ==========================
    # We can re-sort augmented_sessions if we want, but keeping same order is fine/consistent
    
    for item in augmented_sessions:
        data = item['data']
        candidates = item['candidates']
        assigned_in_main = set(item['assigned_supervisors'])
        
        # Filter: Can't be someone already doing a room in this session
        valid_backups = [c for c in candidates if c not in assigned_in_main]
        
        if not valid_backups:
            # Critical: No one left for backup!
            schedule_data.append({
                "Day": f"Day {data['day']}",
                "Session": data['session'],
                "Block": "BACKUP",
                "Supervisor": "NOBODY AVAILABLE"
            })
            continue

        # Dynamic Sort:
        # 1. TOTAL Duty Count (Asc) - Balance overall load now
        # 2. Availability (Asc)
        random.shuffle(valid_backups)
        valid_backups.sort(key=lambda name: (total_counts[name], availability_count[name]))
        
        backup_sup = valid_backups[0]
        
        schedule_data.append({
            "Day": f"Day {data['day']}",
            "Session": data['session'],
            "Block": "BACKUP",
            "Supervisor": backup_sup
        })
        # Note: We DON'T increment main_counts, only total
        total_counts[backup_sup] += 1

    # 5. FINAL SORT FOR DISPLAY
    def sort_key(row):
        d_num = int(row['Day'].split(' ')[1])
        s_rank = 0 if row['Session'] == 'Morning' else 1
        is_backup = 1 if row['Block'] == 'BACKUP' else 0
        return (d_num, s_rank, is_backup)
        
    schedule_data.sort(key=sort_key)

    return {
        "schedule": schedule_data,
        "duties": total_counts # Return total counts for the report
    }
