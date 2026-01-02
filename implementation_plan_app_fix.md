
# Implementation Plan - Fix Duty Counting Display

## Goal
The Admin Dashboard currently calculates supervisor duties incorrectly when multiple subjects are scheduled in the same room. It counts one duty per subject, whereas it should count one duty per room assignment. `scheduler.py` already computes this correctly, but `app.py` recalculates it incorrectly from the session rows.

The fix will update `app.py` to count duties by deduplicating assignments based on (Day, Session, Block, Supervisor).

## Changes Made
### `app.py`
- Modify the `admin_dashboard` route.
- In the loop where `duty_counts` is populated from `schedule_data`:
  - Change the logic from simple iteration to set-based counting.
  - Create a set `seen_duties = set()`
  - Key for set: `(supervisor_name, day, session, block_name)`
  - Only increment count if key is not in set.

## Verification
1. **Automated Test Script**:
   - Updates `repro_duty_count.py` to include the fix logic simulation.
   - Run `python repro_duty_count.py` to confirm logic correctness.

2. **Manual Verification**:
   - Run the app.
   - Go to Admin Dashboard.
   - Select an exam with multiple subjects in one room.
   - Verify that the "Duty Report" list shows the correct counts (1 per room) compared to the Schedule Table.
