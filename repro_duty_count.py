
import scheduler
import json

# Setup mock data
rooms = [
    {'name': '101', 'capacity': 50}
]

supervisors = ['Sup A', 'Sup B']

# Session 1: Subj A, 10am, 20 students
# Session 2: Subj B, 10am, 20 students
# Both fit in Room 101.
sessions_data = [
    {
        '_id': 's1',
        'day': 1,
        'date': '01/01/2026',
        'time': '10am',
        'session': 'Morning',
        'total_students': 20,
        'subject': 'Math',
        'unavailable': []
    },
    {
        '_id': 's2',
        'day': 1,
        'date': '01/01/2026',
        'time': '10am',
        'session': 'Morning',
        'total_students': 20,
        'subject': 'Physics',
        'unavailable': []
    }
]

print("--- Running Schedule Generation ---")
result = scheduler.generate_schedule(rooms, supervisors, sessions_data)

print("\n--- Duty Counts (from scheduler) ---")
print(result['duties'])

print("\n--- Schedule Rows ---")
for row in result['schedule']:
    print(row)

# Verify if Sup gets 1 or 2 duties (Main + Backup)
# We have 1 Room Task (Main) + 1 Room Task (Backup). 
# So ideally Sup A gets 1, Sup B gets 1 (if distributed).
# Result: 'duties': {'Sup A': 1, 'Sup B': 1} (Expected)

# Verify app.py Recalculation Simulation
print("\n--- App.py Recalculation Simulation (Fixed) ---")
app_duty_counts = {}
seen_assignments = set()

for row in result['schedule']:
    sup = row.get('Supervisor')
    if sup != 'NA' and sup != 'NOBODY AVAILABLE':
        key = (sup, row.get('Date'), row.get('Time'), row.get('Block'))
        if key not in seen_assignments:
            app_duty_counts[sup] = app_duty_counts.get(sup, 0) + 1
            seen_assignments.add(key)
            
print(app_duty_counts)

# Expected: {'Sup A': 1, 'Sup B': 1} (Correctly deduplicated)
