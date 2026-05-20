# Detailed Plan: Fix Demo Application Threading Model

## Goal
Fix the broken threading model in `demo/web_app.py` to make the demo application functional. The current implementation mixes `threading.Thread` + `asyncio` without proper synchronization, causing race conditions, deadlocks, and non-functional behavior.

## Current Problems
1. **Mixed threading model**: Uses `threading.Thread` + `asyncio` without proper synchronization
2. **Global mutable state**: `casambi_instance`, `units_cache`, `connection_status` cause race conditions
3. **Blocking Flask threads**: `run_in_thread()` blocks Flask request thread via `future.result()`
4. **No error propagation**: Async background tasks don't propagate errors
5. **Clean shutdown missing**: `loop.run_forever()` never stops cleanly
6. **Duplicate globals**: `connection_status`, `units_cache`, `state_queue` declared twice

## Solution Approach
**Use Quart (async Flask)** - This is the cleanest approach because:
- The Casambi library is already async (uses `asyncio`, `bleak`, `httpx`)
- Quart provides async/await support natively
- Eliminates the need for threading hacks
- Simplifies the code significantly
- Better performance and reliability

## Implementation Plan

### Phase 1: Setup Quart (1 file)
**File: `demo/web_app.py`**

**Tasks:**
1. Replace `from flask import Flask` with `from quart import Quart`
2. Change `app = Flask(__name__)` to `app = Quart(__name__)`
3. Add async route decorators: `@app.route()` → `@app.get()` / `@app.post()`
4. Make all route handlers async functions
5. Update `app.run()` to use Quart's `app.run_task()` or `asyncio.run()`

**Specific changes:**
- Import: `from quart import Quart, jsonify, render_template, request`
- App creation: `app = Quart(__name__, static_folder='static', template_folder='templates')`
- Route decorators: Use `@app.get('/')`, `@app.post('/api/connect')`, etc.
- Run: `asyncio.run(app.run_task(host='0.0.0.0', port=5000))`

---

### Phase 2: Remove Threading Hack (1 file)
**File: `demo/web_app.py`**

**Tasks:**
1. Remove the background thread code:
   - Remove `loop: asyncio.AbstractEventLoop | None = None`
   - Remove `run_async_loop()` function
   - Remove `threading.Thread(target=run_async_loop, daemon=True).start()`
   - Remove `run_in_thread()` helper function

2. Replace all `run_in_thread(coro)` calls with direct `await coro`

---

### Phase 3: Fix Global State Management (1 file)
**File: `demo/web_app.py`**

**Tasks:**
1. Remove duplicate global declarations (keep only one of each)
2. Use Quart's `app.app_context()` or `g` for request-scoped state where appropriate
3. For shared async state, use `asyncio.Lock()` for synchronization

**New state management:**
```python
# Shared state with async locking
casambi_instance = None
connection_status = {"connected": False, "network_name": None, "network_id": None, "error": None}
units_cache = {}
state_lock = asyncio.Lock()  # For synchronizing access to shared state
```

4. Wrap state access in async context with locks where needed

---

### Phase 4: Fix Route Handlers (1 file)
**File: `demo/web_app.py`**

Convert all routes to async and update Casambi API calls:

**Example transformation:**
```python
# BEFORE (sync, blocking)
@app.route('/api/connect', methods=['POST'])
def connect_network():
    global casambi_instance, connection_status, units_cache, discovered_devices
    try:
        data = request.get_json()
        address = data.get('address')
        password = data.get('password')
        device = next((d for d in discovered_devices if d.address == address), None)
        if not device:
            return jsonify({"success": False, "error": "Device not found"})
        casambi_instance = Casambi()
        casambi_instance.registerUnitChangedHandler(on_unit_changed)
        casambi_instance.registerDisconnectCallback(on_disconnected)
        run_in_thread(casambi_instance.connect(device, password))  # BLOCKING!
        # ...

# AFTER (async, non-blocking)
@app.post('/api/connect')
async def connect_network():
    global casambi_instance, connection_status, units_cache, discovered_devices
    try:
        data = await request.get_json()
        address = data.get('address')
        password = data.get('password')
        device = next((d for d in discovered_devices if d.address == address), None)
        if not device:
            return jsonify({"success": False, "error": "Device not found"})
        casambi_instance = Casambi()
        casambi_instance.registerUnitChangedHandler(on_unit_changed)
        casambi_instance.registerDisconnectCallback(on_disconnected)
        await casambi_instance.connect(device, password)  # NON-BLOCKING!
        # ...
```

**All routes to convert:**
- `/` - index
- `/api/networks` - GET
- `/api/connect` - POST
- `/api/status` - GET
- `/api/disconnect` - POST
- `/api/units` - GET
- `/api/units/<unit_id>/state` - GET
- `/api/units/<unit_id>/control` - POST
- `/api/poll-state` - GET
- `/api/poll-toggle` - POST

---

### Phase 5: Fix Callback Handlers (1 file)
**File: `demo/web_app.py`**

**IMPORTANT FINDING**: The Casambi library callbacks are **synchronous**, not async. They use `Callable[[Unit], None]` and are called with `h(u)` not `await h(u)`. See `_casambi.py` lines 494, 515, 613, 622.

This means we cannot make the callback handlers async functions. We have two options:

**Option A (Recommended for Demo Fix)**: Keep queue-based approach, but use `asyncio.Queue` instead of `queue.Queue`
- The sync callbacks put items into an async queue
- The async routes read from the async queue
- No blocking operations needed

**Option B (Complex)**: Modify Casambi library to support async callbacks
- Requires changes to library code
- Out of scope for demo fix

**We'll use Option A.**

**Tasks:**
1. Replace `queue.Queue()` with `asyncio.Queue()`
2. Keep callbacks as sync functions that put to the async queue:
```python
def on_unit_changed(unit: Unit):
    """Callback for unit state changes - called synchronously by Casambi lib"""
    # Schedule an async task to update the cache
    async def update_cache():
        async with state_lock:
            units_cache[unit.uuid] = unit
    # Create a task to run the async update
    asyncio.create_task(update_cache())

# OR: Put in async queue for processing elsewhere
def on_unit_changed(unit: Unit):
    """Callback for unit state changes"""
    state_queue.put_nowait({"type": "unit_update", "unit": unit})
```

3. Update `on_disconnected` similarly:
```python
def on_disconnected():
    """Callback for disconnection - called synchronously"""
    async def update_status():
        global connection_status
        async with state_lock:
            connection_status["connected"] = False
            connection_status["error"] = "Disconnected"
    asyncio.create_task(update_status())
```

4. Process the async queue in endpoints that need fresh data (or use a background task)

---

### Phase 6: Fix Serialization Issues (1 file)
**File: `demo/web_app.py`**

**Problem:** `units_cache` stores raw `Unit` objects which are not JSON-serializable.

**Tasks:**
1. Create a helper function to serialize Unit objects:
```python
def serialize_unit(unit: Unit) -> dict:
    """Convert Unit object to JSON-serializable dict."""
    state_dict = {}
    if unit.state:
        state_dict = {
            "dimmer": unit.state.dimmer,
            "rgb": unit.state.rgb,
            "white": unit.state.white,
            "temperature": unit.state.temperature,
            "vertical": unit.state.vertical,
            "xy": unit.state.xy,
            "slider": unit.state.slider,
            "sensor": unit.state.sensor,
            "onoff": unit.state.onoff,
            "colorsource": unit.state.colorsource.value if unit.state.colorsource else None,
        }
        # Remove None values for cleaner output
        state_dict = {k: v for k, v in state_dict.items() if v is not None}
    
    return {
        "id": str(unit.uuid),
        "uuid": str(unit.uuid),
        "deviceId": unit.deviceId,
        "address": unit.address,
        "name": unit.name,
        "firmwareVersion": unit.firmwareVersion,
        "device_role": unit.unitType.device_role.name,
        "controls": [c.type.name for c in unit.unitType.controls],
        "state": state_dict,
        "online": unit.online,
        "is_on": unit.is_on,
    }
```

2. Update `/api/units` endpoint to serialize units:
```python
@app.get('/api/units')
async def get_units():
    if not connection_status["connected"]:
        return jsonify({"success": False, "error": "Not connected"})
    async with state_lock:
        serialized_units = {str(u.uuid): serialize_unit(u) for u in units_cache.values()}
    return jsonify({"success": True, "data": serialized_units})
```

3. Update `/api/units/<unit_id>/state` endpoint similarly
4. Update `/api/poll-state` to return serialized unit states

---

### Phase 7: Update Frontend Compatibility (1 file)
**File: `demo/static/script.js`**

The frontend expects certain property names that don't match the backend:
- Frontend expects: `unit.state.level`, `unit.state.onOff`
- Backend has: `state.dimmer`, `state.onoff` (lowercase)

**Tasks:**
1. Update `serialize_unit()` to map property names:
```python
# In state_dict, add:
"level": unit.state.dimmer,  # Map dimmer to level
"onOff": unit.state.onoff,   # Map onoff to onOff
```

2. Ensure `device_role` and `controls` are at the top level of the unit object (not nested in unitType)

---

### Phase 8: Add CORS Support (1 file)
**File: `demo/web_app.py`**

**Tasks:**
1. Install and import Quart-CORS or add CORS headers manually
2. Configure CORS for development:
```python
from quart_cors import cors
app = Quart(__name__)
app = cors(app, allow_origin="*")  # For development only
```

---

### Phase 9: Add Proper Error Handling (1 file)
**File: `demo/web_app.py`**

**Tasks:**
1. Add try/except to all async routes
2. Ensure errors are properly returned as JSON
3. Add logging for debugging

---

### Phase 10: Add Graceful Shutdown (1 file)
**File: `demo/web_app.py`**

**Tasks:**
1. Add signal handlers for Ctrl+C
2. Implement cleanup of Casambi connection on shutdown

---

## File Touch Summary

| # | File | Changes | Lines Changed (est.) |
|---|------|---------|---------------------|
| 1 | `demo/web_app.py` | Complete refactor | ~200 lines |
| 2 | `demo/static/script.js` | Property name mapping fix | ~20 lines |

**Total files touched: 2** (well under the 10-file limit)

---

## Dependencies to Add

1. **quart**: `pip install quart`
2. **quart-cors**: `pip install quart-cors` (or use manual CORS headers)

---

## Testing Checklist

- [ ] Install Quart and dependencies
- [ ] Run the application: `python demo/web_app.py`
- [ ] Open browser to `http://localhost:5000`
- [ ] Verify discovery works (click "Refresh Networks")
- [ ] Verify connection works (select network, enter password, click Connect)
- [ ] Verify units display in dashboard
- [ ] Verify controls work (sliders, buttons)
- [ ] Verify state updates via polling
- [ ] Verify disconnect works
- [ ] Test multiple rapid actions (no deadlocks)
- [ ] Test page refresh (state should reset cleanly)
- [ ] Check browser console for errors
- [ ] Check server console for errors

---

## Chunk Breakdown (For Junior Developer)

### Chunk 1: Setup and Dependencies (30 min)
**Goal:** Install Quart and verify it works

1. Create a new virtual environment (optional but recommended)
2. Install Quart: `pip install quart quart-cors`
3. Create a minimal test Quart app to verify installation:
```python
from quart import Quart
app = Quart(__name__)

@app.get('/')
async def hello():
    return "Hello Quart!"

async def main():
    await app.run_task(host='0.0.0.0', port=5000)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
```
4. Run and verify it works at `http://localhost:5000`

### Chunk 2: Convert App to Quart (1 hour)
**Goal:** Replace Flask with Quart

1. Change imports from flask to quart
2. Change `Flask` to `Quart`
3. Change all route decorators to use `@app.get()` and `@app.post()`
4. Make all route handlers async
5. Update `request.get_json()` to `await request.get_json()`
6. Test that the app starts (even if routes don't work yet)

### Chunk 3: Remove Threading and Add Async (1 hour)
**Goal:** Remove threading hacks and make everything async

1. Remove `threading` import
2. Remove `loop` global variable
3. Remove `run_async_loop()` function
4. Remove the thread creation line
5. Remove `run_in_thread()` function
6. Replace all `run_in_thread(coro)` with `await coro`
7. Test that routes work (discovery should work now)

### Chunk 4: Fix State Management (1 hour)
**Goal:** Proper shared state with async locks

1. Remove duplicate global variable declarations
2. Add `state_lock = asyncio.Lock()`
3. Wrap shared state access in `async with state_lock:` blocks
4. Update callback handlers to use the lock
5. Test that connection flow works

### Chunk 5: Fix Serialization (1 hour)
**Goal:** Make Unit objects JSON-serializable

1. Create `serialize_unit()` helper function
2. Create `serialize_state()` helper function
3. Update `/api/units` endpoint to return serialized units
4. Update `/api/units/<unit_id>/state` endpoint
5. Update `/api/poll-state` endpoint
6. Test that units display in the dashboard

### Chunk 6: Fix Frontend Property Mapping (30 min)
**Goal:** Map backend property names to frontend expectations

1. Update `serialize_unit()` to include `level` and `onOff` mappings
2. Ensure `device_role` and `controls` are at the top level
3. Test that unit cards render correctly with controls

### Chunk 7: Add CORS Support (15 min)
**Goal:** Enable cross-origin requests for development

1. Import and configure quart-cors
2. Test that frontend can call all API endpoints

### Chunk 8: Add Error Handling and Cleanup (1 hour)
**Goal:** Robust error handling and graceful shutdown

1. Add try/except to all routes
2. Add proper error responses
3. Add signal handlers for shutdown
4. Add Casambi disconnect on shutdown
5. Test error scenarios

---

## Success Criteria

The threading model fix is complete when:
- [ ] Demo application starts without errors
- [ ] Discovery endpoint works and returns networks
- [ ] Connection endpoint works and connects to network
- [ ] Units endpoint returns JSON-serializable unit data
- [ ] Dashboard displays units with their controls
- [ ] Control commands work (sliders, buttons)
- [ ] State updates work via polling
- [ ] No deadlocks or race conditions observed
- [ ] Page refresh works cleanly
- [ ] No console errors in browser or server

---

## Notes for Junior Developer

### Key Concepts to Understand:
1. **Async/Await**: All route handlers must be async functions that use `await` for async operations
2. **Quart vs Flask**: Quart is async Flask - most APIs are the same but routes use `@app.get()`/`@app.post()`
3. **No Threading Needed**: Since Quart is async and Casambi library is async, we don't need threads
4. **Shared State**: Use `asyncio.Lock()` to protect shared variables from race conditions
5. **JSON Serialization**: Python objects must be converted to dicts/primitives for JSON serialization

### Common Pitfalls:
1. **Forgetting `await`**: Always use `await` when calling async functions
2. **Blocking the event loop**: Never use `.result()` on futures - use `await` instead
3. **Forgetting async on functions**: All route handlers must have `async def`
4. **Race conditions**: Always use locks when accessing shared state from multiple coroutines
5. **Non-serializable objects**: Always serialize complex objects before returning as JSON

### Debugging Tips:
1. Check server console for errors
2. Check browser console (F12) for errors
3. Use `print()` or logging liberally
4. Test one endpoint at a time
5. Use `curl` to test API endpoints directly

---

## Summary

This plan addresses **ROADMAP Issue #1: Demo Application - Threading Model Broken**, which is the top priority critical issue preventing the demo from being functional.

### Key Decisions:
1. **Use Quart instead of Flask**: The Casambi library is already async (uses bleak, httpx). Quart provides native async/await support, eliminating the need for threading hacks.
2. **Keep sync callbacks with async wrappers**: The Casambi library uses synchronous callbacks. We'll wrap them to schedule async tasks.
3. **Use asyncio.Lock for shared state**: Protects `units_cache`, `connection_status`, etc. from race conditions.
4. **Serialize Unit objects**: Create helper functions to convert Unit objects to JSON-serializable dicts.
5. **Fix property name mapping**: Map backend `dimmer`/`onoff` to frontend `level`/`onOff`.

### Files to Modify:
| File | Lines Changed (est.) | Type of Change |
|------|---------------------|----------------|
| `demo/web_app.py` | ~200 | Complete refactor to Quart |
| `demo/static/script.js` | ~5 | Minor property name fixes |

**Total: 2 files** (well under 10-file limit)

### Estimated Time:
- **Total**: ~6-8 hours for a junior developer
- **Chunked**: 8 chunks of 15-60 minutes each

### Dependencies to Add:
```bash
pip install quart quart-cors
```

---

## Next Steps After This Fix

Once the threading model is fixed, the next critical issues are:
1. **Issue #2: Demo - Missing Unit Serialization** (partially addressed in this fix)
2. **Issue #3: Library - Unbounded Packet Growth** (logging verbosity)
3. **Issue #4: Library - Memory Leak in Callbacks**
4. **Issue #10: Library - Missing Error Types in __init__.py**

But the threading fix is the foundation - everything else builds on this.
