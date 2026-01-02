
# Implementation Plan - Update Duty Counting Logic

## Goal
Update the scheduling algorithm so that the Supervisor Duty Count increments **only** when assigned to a Classroom (Main Block Supervisor), and not for other roles (Backup Supervisor). This ensures that the load balancing prioritizes equalizing "Classroom Invigilation" duties.

## Changes Made
### `scheduler.py`
- Modify the `generate_schedule` function.
- In the assignment loop (step 4), update the condition for incrementing `duty_count`.
- Change:
  ```python
  duty_count[chosen_sup] += 1
  ```
  to:
  ```python
  if task['role'] == 'MAIN':
      duty_count[chosen_sup] += 1
  ```
- This change ensures that `duty_count` reflects only "Classroom" assignments.
- The `max_allowed` logic might need adjustment or simply be accepted as a loose cap since `duty_count` will typically be lower than `total_tasks / N`. To maintain fairness, `max_allowed` should ideally be based on `main_tasks / N`, but keeping it high effectively ignores the hard cap and relies on the `min_load` balancing, which is desired.

## Verification
1. **Automated Test Script**:
   - Create a script `test_scheduler_logic.py`.
   - Mock data: 2 Rooms, 2 Slots, 4 Supervisors.
   - Run `generate_schedule`.
   - Verify that `duties` dictionary counts match the number of MAIN assignments per supervisor.
   - Verify that BACKUP assignments exist but do not contribute to the count.

2. **Manual Verification**:
   - Generate a schedule via the web UI.
   - Check the "Duty Report" (which uses the returned `duties` dict).
   - Manually count the "M" (Main) roles in the schedule for a supervisor and verify it matches the report number.
