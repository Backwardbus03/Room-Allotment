import pandas as pd
import random
import uuid
from collections import defaultdict
from datetime import datetime

def generate_schedule(rooms, supervisors, sessions_data):
    """
    Generates a schedule with Double Supervision (1 Main + 1 Backup) per Block.
    
    Logic:
    1. Calculate required rooms for each subject (Students / Room Capacity).
    2. Create TASKS for every required room: 1 MAIN task + 1 BACKUP task.
    3. Sort all tasks globally by Time Slot Scarcity (fewest available supervisors).
    4. Assign supervisors using Least-Duty-First with Fairness constraints.
       - Ensures a supervisor is only assigned ONCE per Time Slot.
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

    # 2. DISTRIBUTE STUDENTS (Pass 1)
    # Map: slot_key -> room_name -> { 'used': int, 'sessions': [ {id, count, subject...} ] }
    slot_room_map = defaultdict(lambda: defaultdict(lambda: {'used': 0, 'sessions': []}))
    
    # Track unallocated for reporting
    unallocated = []

    for sess in sessions_data:
        sess_id = sess['_id']
        # Normalize Date/Time
        date_raw = sess.get('date', f"Day {sess.get('day', '?')}")
        time_raw = sess.get('time', sess.get('session', 'Unknown'))
        date_norm = str(date_raw).strip().lower()
        time_norm = str(time_raw).strip().lower()
        slot_key = (date_norm, time_norm)
        
        total_students = int(sess['total_students'])
        remaining = total_students
        
        # Try to fit in rooms
        for room in sorted_rooms:
            if remaining <= 0: break
            
            r_name = room['name']
            r_cap = room['capacity']
            
            # Check current usage
            current_usage = slot_room_map[slot_key][r_name]['used']
            free_space = r_cap - current_usage
            
            if free_space > 0:
                take = min(free_space, remaining)
                
                # Record Allocation
                slot_room_map[slot_key][r_name]['used'] += take
                slot_room_map[slot_key][r_name]['sessions'].append({
                    'sess_id': sess_id,
                    'count': take,
                    'subject': sess.get('subject', 'General'),
                    'department': sess.get('department', ''),
                    'date_disp': date_raw,
                    'time_disp': time_raw
                })
                
                remaining -= take
        
        if remaining > 0:
            unallocated.append(f"{remaining} students for {sess.get('subject')} in {date_raw}")
            print(f"Warning: Could not allocate {remaining} students for {sess.get('subject')}")
            
    # DEBUG DISTRIBUTION
    print("\n--- ROOM ALLOCATION DEBUG ---")
    for key, rooms in slot_room_map.items():
        print(f"Slot {key}:")
        for r_name, data in rooms.items():
            if data['used'] > 0:
                print(f"  Room {r_name}: {data['used']} students ({len(data['sessions'])} subjects).")
    print("---------------------------------\n")

    
    import math

    # 3. DEFINE TASKS (Pass 2)
    tasks = []
    
    # Pre-calc Availability Map per Task
    # task_availability[task_id_ref] = [sup_names]
    task_availability = {} 
    
    for slot_key, room_dict in slot_room_map.items():
        active_rooms_in_slot = 0
        slot_unavailable_supervisors = set() # For Relievers
        
        for r_name, data in room_dict.items():
            if data['used'] == 0: continue
            active_rooms_in_slot += 1
            
            # Combine unavailable lists from all sessions in this room
            combined_unavailable = set()
            for s_info in data['sessions']:
                s_obj = session_map.get(s_info['sess_id'])
                if s_obj:
                    combined_unavailable.update(s_obj.get('unavailable', []))
            
            # Add to slot-wide unavailable (for relievers safety)
            slot_unavailable_supervisors.update(combined_unavailable)

            candidates = [s for s in all_supervisors if s not in combined_unavailable]
            
            # 1. Main Task
            t_main = {
                'id': str(uuid.uuid4()),
                'slot': slot_key,
                'block': r_name,
                'role': 'MAIN',
                'display_role': 'BLOCK SUPERVISOR',
                'sessions': data['sessions'], 
                'candidates': candidates
            }
            tasks.append(t_main)
            
            # 2. Conditional Room Backup (Only if students > 40)
            if int(data['used']) > 40:
                t_backup = {
                    'id': str(uuid.uuid4()),
                    'slot': slot_key,
                    'block': r_name,
                    'role': 'BACKUP_ROOM',
                    'display_role': 'ROOM BACKUP',
                    'sessions': data['sessions'],
                    'candidates': candidates
                }
                tasks.append(t_backup)

        # 3. Pool Backups (Relievers)
        # 1 Reliever for every 5 rooms. Explicitly list the blocks they relieve.
        if active_rooms_in_slot > 0:
            # Collect all active room names for this slot
            active_room_names = [r for r, d in room_dict.items() if d['used'] > 0]
            
            # Chunk into groups of 5
            chunk_size = 5
            for i in range(0, len(active_room_names), chunk_size):
                chunk = active_room_names[i:i + chunk_size]
                block_range = ", ".join(chunk)
                
                # Reliever candidates
                reliever_candidates = [s for s in all_supervisors if s not in slot_unavailable_supervisors]
                
                t_reliever = {
                    'id': str(uuid.uuid4()),
                    'slot': slot_key,
                    'block': block_range, # Specific blocks
                    'role': 'BACKUP_RELIEVER',
                    'display_role': 'RELIEVER', # Shortened for display
                    'sessions': [{
                        'date_disp': slot_key[0], 
                        'time_disp': slot_key[1],
                        'subject': 'Reliever for: ' + block_range,
                        'count': 0
                    }],
                    'candidates': reliever_candidates
                }
                tasks.append(t_reliever)

    # 4. FAIRNESS & ASSIGNMENT
    total_tasks = len(tasks)
    n_sups = len(all_supervisors)
    if n_sups == 0: return {"schedule": [], "duties": {}}
    
    ideal = total_tasks // n_sups
    max_fair = ideal + 1
    
    max_allowed = { name: max_fair for name in all_supervisors }
    
    # Sort Tasks
    # Scarcity = len(t['candidates'])
    random.shuffle(tasks)
    tasks.sort(key=lambda t: (len(t['candidates']), 0 if t['role'] == 'MAIN' else 1))
    
    assignments = []
    duty_count = defaultdict(int)
    
    # Track supervisor busy status per slot
    # slot_assignments[slot_key] = set(sup_names)
    slot_assignments = defaultdict(set)
    
    for task in tasks:
        slot = task['slot']
        candidates = task['candidates']
        busy_in_slot = slot_assignments[slot]
        
        eligible = [c for c in candidates if c not in busy_in_slot]
        
        # Decide Supervisor
        chosen_sup = "NOBODY AVAILABLE"
        
        if eligible:
            # Fairness
            strict = [c for c in eligible if duty_count[c] < max_allowed[c]]
            pool = strict if strict else eligible
            
            # Load Balancing
            pool.sort(key=lambda x: duty_count[x])
            min_load = duty_count[pool[0]]
            best = [x for x in pool if duty_count[x] == min_load]
            chosen_sup = random.choice(best)
            
            # Commit
            duty_count[chosen_sup] += 1
            slot_assignments[slot].add(chosen_sup)
            
        # EXPAND TO OUTPUT ROWS
        # One row per subject in this room
        # But wait, if we have main and backup, we produce 2 rows per subject?
        # Typically:
        # Row 1: Subj A, Block 1, Main Sup
        # Row 2: Subj B, Block 1, Main Sup
        # Row 3: Subj A, Block 1, Backup Sup
        # Row 4: Subj B, Block 1, Backup Sup
        
        for sess_info in task['sessions']:
            assignments.append({
                "Date": sess_info['date_disp'],
                "Time": sess_info['time_disp'],
                "Subject": sess_info['subject'],
                "Department": sess_info.get('department', ''),
                "Count": sess_info.get('count', 0),
                "Block": task['block'],
                "Role": task['display_role'],
                "Supervisor": chosen_sup
            })

    # 5. FINAL SORT
    def sort_key(row):
        d_val = row['Date']
        try:
            if "Day" in d_val:
                parts = d_val.split(' ')
                if len(parts) > 1 and parts[1].isdigit():
                    return (0, int(parts[1]), row['Time'], row['Block'])
            else:
                 dt = datetime.strptime(d_val.strip(), "%d %B %Y")
                 return (dt.toordinal(), 0, row['Time'], row['Block'])
        except:
             # Fallback for parsing failure
             pass
             
        is_backup = 1 if 'BACKUP' in row['Role'] else 0
        return (d_val, row['Time'], row['Block'], is_backup)
        
    assignments.sort(key=sort_key)

    return {
        "schedule": assignments,
        "duties": dict(duty_count)
    }


