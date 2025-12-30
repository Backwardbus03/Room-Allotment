import pandas as pd
import random

def create_balanced_schedule():
    print("--- Exam Scheduling System ---\n")
    
    # 1. SETUP INPUTS
    num_days = int(input("Number of exam days: "))
    capacity_per_block = int(input("Max students per block (e.g., 30 or 40): "))
    
    raw_supervisors = input("Enter supervisor names (comma separated, excluding exceptions): ").split(",")
    all_supervisors = [s.strip() for s in raw_supervisors if s.strip()]
    
    # Duty tracker: { "Name": duty_count }
    duty_counts = {name: 0 for name in all_supervisors}
    schedule_data = []

    # 2. DAILY PROCESSING
    for day in range(1, num_days + 1):
        for session in ["Morning", "Evening"]:
            print(f"\n>>> Day {day} | {session} Session")
            
            blocks_available = int(input(f"  Total blocks available: "))
            total_students = int(input(f"  Total students for this session: "))
            
            # Logic: Calculate blocks needed based on student input
            blocks_needed = (total_students // capacity_per_block) + (1 if total_students % capacity_per_block > 0 else 0)
            
            # Validation: Ensure we don't exceed physical blocks
            if blocks_needed > blocks_available:
                print(f"  ! WARNING: Need {blocks_needed} blocks, but only {blocks_available} are available.")
                print(f"  ! Adjustment: Using only {blocks_available} blocks (Squeeze students or find more rooms).")
                blocks_needed = blocks_available
            else:
                print(f"  - Using {blocks_needed} out of {blocks_available} available blocks.")

            # 3. BALANCED SUPERVISOR SELECTION
            # Step A: Shuffle the supervisor list to ensure randomness among equals
            names_list = list(duty_counts.keys())
            random.shuffle(names_list)
            
            # Step B: Sort by duty count (lowest duties first)
            # This ensures we pick people who haven't worked much yet
            sorted_names = sorted(names_list, key=lambda x: duty_counts[x])
            
            # Step C: Assign the top N people needed for this session
            assigned_this_session = sorted_names[:blocks_needed]

            for i, sup_name in enumerate(assigned_this_session):
                schedule_data.append({
                    "Day": f"Day {day}",
                    "Session": session,
                    "Block": f"Block {i+1}",
                    "Supervisor": sup_name
                })
                duty_counts[sup_name] += 1

    # 4. FINAL OUTPUT GENERATION
    if not schedule_data:
        print("No data to display.")
        return

    df = pd.DataFrame(schedule_data)
    
    # Pivot for the Final Schedule Chart
    chart = df.pivot(index=['Day', 'Session'], columns='Block', values='Supervisor').fillna("-")
    
    print("\n" + "="*40)
    print("FINAL SUPERVISOR WORKLOAD REPORT")
    print("="*40)
    for name, count in sorted(duty_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"{name.ljust(20)} : {count} Duties")
    
    print("\nALLOCATION CHART:")
    print(chart)
    
    # Optional: Save to CSV for Excel
    # chart.to_csv("Exam_Allocation_Chart.csv")
    # print("\nSuccess: Chart saved to Exam_Allocation_Chart.csv")

# Run the function
create_balanced_schedule()