# Plan: Fix Issues in Demo Application Threading Model Implementation

## Goal
Fix the remaining issues in commit `7de91a8` (Demo Application Threading Model fix) to ensure proper shutdown, avoid race conditions, and clean up redundant code.

## Background
Commit `7de91a8` successfully migrated from Flask to Quart, removed threading hacks, added async queues and locks, and implemented proper serialization. However, several issues remain that could cause:
- Hanging on shutdown (infinite loop in queue processor)
- Lost callback updates (queue not initialized before use)
- Deadlocks (overly broad lock scoping)
- Redundant operations (duplicate cache population)

## Issues to Fix

### Issue 1: `process_state_queue()` has no exit condition
**Severity:** Critical
**File:** `demo/web_app.py`
**Problem:** The background task runs `while True` with no way to stop, preventing clean shutdown.
**Impact:** Application hangs on shutdown waiting for queue task to complete.

### Issue 2: Callback race condition on startup
**Severity:** Critical  
**File:** `demo/web_app.py`
**Problem:** `state_queue` is `None` at module level. If Casambi callbacks fire during `connect()` (before `main()` initializes the queue), updates are silently dropped.
**Impact:** Lost unit state updates.

### Issue 3: Overly broad lock in `control_unit`
**Severity:** High
**File:** `demo/web_app.py`
**Problem:** Lock is held during the entire control operation including `await casambi_instance.setControl()`, which can block other operations unnecessarily.
**Impact:** Potential deadlocks, reduced concurrency.

### Issue 4: Redundant cache population in `connect_network`
**Severity:** Medium
**File:** `demo/web_app.py`
**Problem:** Manually populates `units_cache` while callbacks also populate it via the queue, creating a race condition.
**Impact:** Inconsistent cache state.

### Issue 5: Redundant `poll_state` endpoint
**Severity:** Low
**File:** `demo/web_app.py`
**Problem:** `poll_state` is identical to `get_units`. The old threading model's polling logic is no longer needed.
**Impact:** Code duplication, confusion.

### Issue 6: Unused `polling_enabled` variable
**Severity:** Low
**File:** `demo/web_app.py`
**Problem:** Variable is declared, has toggle endpoint, but is never used.
**Impact:** Dead code.

---

## Implementation Plan

### Phase 1: Fix Background Queue Processor (Critical)
**File:** `demo/web_app.py`

**Task 1.1:** Add shutdown check to `process_state_queue()`
- Change `while True:` to `while not shutdown_event.is_set():`
- Add timeout to `state_queue.get()` to allow periodic shutdown checks
- Handle `asyncio.CancelledError` for task cancellation

**Task 1.2:** Handle queue shutdown in cleanup
- In `cleanup()`, await `queue_task` with proper cancellation handling
- Drain the queue before shutting down

**Verification:** App shuts down cleanly on SIGINT/SIGTERM without hanging.

---

### Phase 2: Fix Callback Initialization Race Condition (Critical)
**File:** `demo/web_app.py`

**Task 2.1:** Initialize `state_queue` at module level
- Change `state_queue: asyncio.Queue = None` to `state_queue = asyncio.Queue()`
- Remove initialization from `main()`

**Task 2.2:** Update `on_unit_changed` and `on_disconnected`
- Remove `if state_queue:` check (queue always exists)
- Simplify error handling

**Task 2.3:** Ensure queue task is created before any async operations
- Keep `queue_task = asyncio.create_task(process_state_queue())` in `main()`
- This ensures task exists before `connect()` is called

**Verification:** Callbacks work correctly from first connection.

---

### Phase 3: Fix Lock Scoping in `control_unit` (High)
**File:** `demo/web_app.py`

**Task 3.1:** Narrow lock scope
- Move `await request.get_json()` outside the lock (already async)
- Move `await casambi_instance.setControl()` outside the lock
- Keep only state *reads* (checking `casambi_instance`, getting `unit`) inside the lock

**Code change:**
```python
# BEFORE:
async with state_lock:
    if not casambi_instance:
        return ...
    unit = units_cache.get(unit_id)
try:
    data = await request.get_json()
    # ... validation and control ...
    await casambi_instance.setControl(unit, control_type, value)

# AFTER:
async with state_lock:
    if not casambi_instance:
        return jsonify({"success": False, "error": "Not connected"}), 400
    unit = units_cache.get(unit_id)
    if not unit:
        return jsonify({"success": False, "error": "Unit not found"}), 404

# Release lock before async operations
data = await request.get_json()
# ... validation ...
await casambi_instance.setControl(unit, control_type, value)
```

**Verification:** Multiple concurrent control requests don't deadlock.

---

### Phase 4: Remove Redundant Cache Population (Medium)
**File:** `demo/web_app.py`

**Task 4.1:** Remove manual `units_cache` population in `connect_network`
- Remove the line: `units_cache = {str(u.uuid): u for u in casambi_instance.units}`
- Let callbacks populate the cache via the queue

**Task 4.2:** Update error handling in `connect_network`
- On connection failure, ensure we don't leave stale state
- Clear `casambi_instance` on error

**Verification:** Units appear in cache via callback mechanism only.

---

### Phase 5: Clean Up Redundant Code (Low)
**File:** `demo/web_app.py`

**Task 5.1:** Remove `poll_state` endpoint OR differentiate it
- Option A: Remove entirely (recommended - it's redundant)
- Option B: Make it actually poll for fresh state from Casambi

**Task 5.2:** Remove unused `polling_enabled` variable
- Remove the global variable declaration
- Remove the `/api/poll-toggle` endpoint
- Remove all references

**Verification:** Code is cleaner, no dead code.

---

## File Changes Summary

| File | Changes | Estimated Lines |
|------|---------|-----------------|
| `demo/web_app.py` | Fix queue processor, race conditions, lock scoping, cleanup | ~40 lines |

**Total files touched: 1**

---

## Task Checklist

### Critical (Must Fix)
- [ ] Fix `process_state_queue()` infinite loop with shutdown check
- [ ] Initialize `state_queue` at module level to prevent lost callbacks
- [ ] Update callback handlers to remove null checks

### High Priority
- [ ] Fix lock scoping in `control_unit` to avoid holding lock during async operations

### Medium Priority
- [ ] Remove redundant `units_cache` population in `connect_network`

### Low Priority (Cleanup)
- [ ] Remove redundant `poll_state` endpoint
- [ ] Remove unused `polling_enabled` variable and toggle endpoint

---

## Testing Plan

1. **Shutdown test:** Start app, send SIGINT, verify it exits within 5 seconds
2. **Callback test:** Connect to network, verify unit updates appear in cache
3. **Concurrency test:** Send multiple control commands simultaneously, verify all complete
4. **Connection test:** Connect, verify units appear without duplicate cache entries
5. **Disconnect test:** Disconnect, verify state is cleared properly

---

## Success Criteria

- [ ] Application starts and stops cleanly without hanging
- [ ] No callback updates are lost on first connection
- [ ] Multiple concurrent requests don't deadlock
- [ ] Cache state is consistent (no duplicates, no race conditions)
- [ ] All existing functionality still works
- [ ] Code is cleaner with no dead code

---

## Dependencies

No new dependencies required. Uses existing `asyncio`, `quart`, `logging` modules.

---

## Estimated Time

- Critical fixes: 1-2 hours
- High priority fixes: 1 hour
- Medium priority fixes: 30 minutes
- Low priority cleanup: 30 minutes
- **Total: 3-4 hours**

---

## Notes

- All changes are to `demo/web_app.py` only
- No changes to the Casambi library required
- No changes to frontend (script.js) required
- No new dependencies needed
- Focus on correctness first (critical/high), cleanup second (medium/low)
