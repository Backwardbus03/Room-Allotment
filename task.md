
# Tasks

- [ ] Verify `scheduler.py` duty counting logic with a test script (ensure single count for multi-subject room). <!-- id: 1 -->
- [ ] Fix `app.py` `admin_dashboard` duty calculation to deduplicate assignments by (Day, Session, Block, Supervisor). <!-- id: 2 -->
- [ ] Verify the fix by comparing `scheduler.py` output with `app.py` calculated output. <!-- id: 3 -->
- [ ] Implement the "Main Block Only" counting change if confirmed relevant (User's latest message suggests this might not be needed if the multi-subject issue is the real root cause, but implies keeping Backup might be fine if distinct). <!-- id: 4 -->
