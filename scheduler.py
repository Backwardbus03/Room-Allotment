import pandas as pd
import random
import uuid
from collections import defaultdict

def generate_schedule(num_days, rooms, supervisors, sessions_data):
    """
    Generates a schedule with Double Supervision (1 Main + 1 Backup) per Block.
    
    Logic:
    1. Calculate required rooms for each session (Students / Room Capacity).
    2. Create TASKS for every required room: 1 MAIN task + 1 BACKUP task.
    3. Sort all tasks globally by Session Scarcity (fewest available supervisors).
    4. Assign supervisors using Least-Duty-First with Fairness constraints.
       - Ensures a supervisor is only assigned ONCE per Session.
    """
    
    # 1. PREP DATA
    all_supervisors = [s.strip() for s in supervisors if s.strip()]
    if not all_supervisors:
        return {"schedule": [], "duties": {}}

    # Map session IDs
    session_map = {}
    for s in sessions_data:
        if '_id' not in s:
            s['_id'] = str(uuid.uuid4())
        session_map[s['_id']] = s

    # Sort rooms by capacity (Descending) as preferred by user
    sorted_rooms = sorted(rooms, key=lambda r: r['capacity'], reverse=True)

    # 2. DEFINE TASKS
    tasks = []
    
    # Pre-calculate session availability and scarcity
    # session_availability[sess_id] = [sup1, sup2, ...]
    session_availability = {}
    
    for sess in sessions_data:
        sess_id = sess['_id']
        unavailable = set(sess.get('unavailable', []))
        candidates = [name for name in all_supervisors if name not in unavailable]
        session_availability[sess_id] = candidates
        
        # Calculate Rooms Needed
        total_students = int(sess['total_students'])
        students_remaining = total_students
        
        for room in sorted_rooms:
            if students_remaining <= 0: break
            
            used_cap = min(room['capacity'], students_remaining)
            students_remaining -= used_cap
            
            # --- CREATE 2 TASKS PER ROOM ---
            
            # 1. Main Supervisor
            tasks.append({
                'session_id': sess_id,
                'block': room['name'],
                'role': 'MAIN',
                'display_role': 'BLOCK SUPERVISOR'
            })
            
            # 2. Backup Supervisor
            tasks.append({
                'session_id': sess_id,
                'block': room['name'],
                'role': 'BACKUP',
                'display_role': 'BACKUP SUPERVISOR'
            })

    # 3. FAIRNESS CONSTANTS
    total_tasks = len(tasks)
    n_sups = len(all_supervisors)
    if n_sups == 0: return {"schedule": [], "duties": {}}
    
    ideal = total_tasks // n_sups
    max_fair = ideal + 1
    
    # Per-supervisor max allowed (capped by their total availability?)
    # Replicating logic: max_allowed[s] = min(max_fair, availability_count[s])
    # However, global availability might be high but they might be needed for specific hard sessions.
    # Let's stick to the simpler max_fair for now, or the strict temp.py logic if preferred.
    # User's temp.py logic:
    # availability_count[sup] += 2 (per session available) -> roughly total slots they COULD fill
    # max_allowed[sup] = min(max_fair, availability_count[sup])
    
    # Let's count how many SESSIONS they are available for
    sup_session_availability_count = defaultdict(int)
    for sess in sessions_data:
        for name in session_availability[sess['_id']]:
            sup_session_availability_count[name] += 1 # They could potentially do 1 task here
            # Ideally they can do 1 task per session.
            
    max_allowed = {
        name: max_fair 
        for name in all_supervisors
    }

    # 4. SORT TASKS
    # Key 1: Scarcity of the Session (Ascending)
    # Key 2: Role (Main=0, Backup=1) - Fill Rooms first
    
    def get_scarcity(task):
        return len(session_availability[task['session_id']])
        
    random.shuffle(tasks) # Randomize initially
    tasks.sort(key=lambda t: (get_scarcity(t), 0 if t['role'] == 'MAIN' else 1))

    # 5. ASSIGNMENT LOOP
    assignments = []
    duty_count = defaultdict(int)
    
    # Track assigned supervisors per session to prevent double booking
    # session_assignments[sess_id] = set(names)
    session_assignments = defaultdict(set)
    
    for task in tasks:
        sess_id = task['session_id']
        sess_data = session_map[sess_id]
        
        candidates = session_availability[sess_id]
        current_session_busy = session_assignments[sess_id]
        
        # Filter 1: Available & Not Busy
        eligible = [c for c in candidates if c not in current_session_busy]
        
        if not eligible:
             assignments.append({
                "Day": f"Day {sess_data['day']}",
                "Session": sess_data['session'],
                "Block": task['block'],
                "Role": task['display_role'],
                "Supervisor": "NOBODY AVAILABLE"
            })
             continue
             
        # Filter 2: Fairness (Strict)
        strict_pool = [c for c in eligible if duty_count[c] < max_allowed[c]]
        
        final_pool = strict_pool if strict_pool else eligible
        
        # Filter 3: Least Loading (Dynamic Balancing)
        # Sort by current duty count
        final_pool.sort(key=lambda x: duty_count[x])
        
        min_load = duty_count[final_pool[0]]
        best_candidates = [x for x in final_pool if duty_count[x] == min_load]
        
        chosen = random.choice(best_candidates)
        
        # Commit
        duty_count[chosen] += 1
        session_assignments[sess_id].add(chosen)
        
        assignments.append({
            "Day": f"Day {sess_data['day']}",
            "Session": sess_data['session'],
            "Block": task['block'],
            "Role": task['display_role'],
            "Supervisor": chosen
        })

    # 6. FINAL SORT
    def sort_key(row):
        d_num = int(row['Day'].split(' ')[1])
        s_rank = 0 if row['Session'] == 'Morning' else 1
        # Sort by Room Name, then Role (Block Sup then Backup Sup)
        is_backup = 1 if 'BACKUP' in row['Role'] else 0
        return (d_num, s_rank, row['Block'], is_backup)
        
    assignments.sort(key=sort_key)

    return {
        "schedule": assignments,
        "duties": dict(duty_count)
    }


