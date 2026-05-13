# Casambi-BT Project Improvement Roadmap

## Executive Summary

This master plan addresses **critical robustness issues** in the `src/CasambiBt/` library and **functionality gaps** in the `demo/` web application. The library is alpha-quality with solid core architecture but needs hardening for production use. The demo is structurally flawed and needs significant refactoring.

---

## 🚨 CRITICAL ISSUES (Priority: HIGH)

### 1. Demo Application - Threading Model Broken
**Location:** `demo/web_app.py`

**Problems:**
- Uses `threading.Thread` + `asyncio` mixing without proper synchronization
- Global mutable state (`casambi_instance`, `units_cache`, `connection_status`) causes race conditions
- `run_in_thread()` blocks Flask request thread, causing potential deadlocks
- No error propagation from async background tasks
- `loop.run_forever()` never stops cleanly

**Impact:** Demo is **non-functional** as stated by user. Will hang or crash under load.

**Fix Required:** Complete refactor to use one of:
- Async Flask (Quart)
- Proper thread pool with futures
- Separate asyncio loop with clean shutdown

---

### 2. Demo - Missing Unit Serialization
**Location:** `demo/web_app.py`, `demo/static/script.js`

**Problems:**
- `units_cache` stores raw `Unit` objects which are not JSON-serializable
- Frontend expects `unit.device_role`, `unit.controls`, `unit.state` but `Unit` objects don't have these as dict keys
- `get_units()` endpoint returns non-serializable objects → 500 errors
- State polling returns raw bytes/UnitState objects, not JSON

**Impact:** Dashboard never renders; API calls fail silently or with errors.

---

### 3. Library - Unbounded Packet Growth
**Location:** `src/CasambiBt/_client.py:427-435`

**Problem:**
```python
raw_encrypted_packet = data[:]
self._logger.info(f"[CASAMBI_RAW_PACKET] Encrypted #{self._inPacketCount}: {b2a(raw_encrypted_packet)}")
```

Logging every packet at INFO level with full hex dump will:
- Fill disk space quickly
- Slow down the application
- Expose sensitive data in logs

**Fix:** Move to DEBUG level or add rate limiting.

---

### 4. Library - Memory Leak in Callbacks
**Location:** `src/CasambiBt/_casambi.py:380-395`

**Problem:**
- `registerUnitChangedHandler` appends to list without cleanup
- No weak references used - handlers prevent GC of listener objects
- No max size limit on callback lists

**Impact:** Memory leak if consumers don't unregister callbacks.

**Fix:** Use `weakref.WeakMethod` or `weakref.WeakSet` for callback storage.

---

### 5. Library - No Connection Timeout
**Location:** `src/CasambiBt/_client.py`

**Problem:**
- BLE operations can block indefinitely
- No timeout on `exchangeKey()`, `authenticate()`, or `send()`
- Network issues cause permanent hangs

**Fix:** Add configurable timeouts to all BLE operations.

---

## ⚠️ HIGH PRIORITY ISSUES

### 6. Demo - No CORS Support
**Location:** `demo/web_app.py`

**Problem:** No CORS headers → frontend cannot call API if served separately.

**Fix:** Add `flask-cors` or manual CORS headers.

---

### 7. Demo - No Connection State Persistence
**Location:** `demo/web_app.py`

**Problem:**
- Global `casambi_instance` lost on page refresh
- No session management
- User must re-authenticate on every page reload

**Fix:** Add server-side session storage or client-side localStorage.

---

### 8. Library - Inconsistent State Access
**Location:** `src/CasambiBt/_unit.py`

**Problem:**
- `Unit._state`, `Unit._on`, `Unit._online` are mutable dataclass fields
- Direct mutation bypasses validation and callbacks
- No property setters for `state`, `online` properties

**Impact:** Inconsistent state; callbacks not triggered on direct mutation.

**Fix:** Make Unit immutable or add proper property setters.

---

### 9. Library - Type Safety Issues
**Location:** Multiple files

**Problems:**
- `Group.groudId` - TYPO in field name (should be `groupId`)
- `setControl()` accepts `value: int | tuple[int,int,int] | tuple[float,float]` but no runtime validation
- `_send()` casts target types without type guards
- Missing return type annotations on many methods

**Impact:** Runtime errors, poor IDE support, potential type confusion.

---

### 10. Library - Missing Error Types in __init__.py
**Location:** `src/CasambiBt/__init__.py`

**Problem:** Error classes not exported. Users cannot catch specific exceptions:
```python
from CasambiBt import Casambi, ConnectionStateError  # FAILS - not exported
```

**Fix:** Export all error types in `__init__.py`.

---

## 📊 MEDIUM PRIORITY ISSUES

### 11. Demo - Frontend State Mismatch
**Location:** `demo/static/script.js`

**Problems:**
- Frontend expects `unit.state.level`, `unit.state.onOff` but backend sends `state.dimmer`, `state.onoff` (lowercase)
- `unit.controls` expected but `Unit.unitType.controls` is the actual path
- `unit.device_role` expected but `Unit.unitType.device_role` is the actual property

**Fix:** Either fix frontend expectations or add serialization layer.

---

### 12. Demo - No Real-time Updates via WebSocket
**Location:** `demo/web_app.py`, `demo/static/script.js`

**Problem:** Polling via `/api/poll-state` every 3 seconds is inefficient. WebSocket or Server-Sent Events would be better.

**Fix:** Implement SSE or WebSocket for push updates.

---

### 13. Library - Cache Versioning Issue
**Location:** `src/CasambiBt/_cache.py`

**Problem:**
- `CACHE_VERSION = 2` is hardcoded
- No migration path for cache version upgrades
- Invalidation deletes entire cache, not just stale entries

**Fix:** Add proper cache migration and selective invalidation.

---

### 14. Library - No Retry Logic for Transient Failures
**Location:** `src/CasambiBt/_network.py`, `_client.py`

**Problem:** Network requests fail on transient errors (network blips, API rate limits) with no retry.

**Fix:** Add exponential backoff retry for transient errors.

---

### 15. Library - Incomplete Protocol Support
**Location:** `src/CasambiBt/_client.py:470-475`

**Problem:**
```python
else:
    self._logger.info(f"Packet type {packetType} not implemented. Ignoring!")
```

Unknown packet types are silently ignored. Should log at higher level for debugging.

---

### 16. Demo - No Input Validation
**Location:** `demo/web_app.py`

**Problem:**
- No validation on `control_type` from client
- No validation on `value` ranges
- No rate limiting on control commands
- Potential for abuse or accidental damage

**Fix:** Add request validation middleware.

---

### 17. Library - Switch Event Parsing Fragility
**Location:** `src/CasambiBt/_switch.py`

**Problems:**
- Complex packet parsing with many edge cases
- Falls back to INFO logging for unknown message types (should be DEBUG)
- No packet length validation before parsing
- Message type 0x29 handled inconsistently

**Fix:** Harden parsing with length checks and better error recovery.

---

## 📝 LOW PRIORITY / TECHNICAL DEBT

### 18. Library - TODO Comments
- `_unit.py:245` - "Support for different resolutions?"
- `_unit.py:246` - "Work with HS instead of RGB internally"
- `_unit.py:408` - "Make unit immutable"
- `_unit.py:660` - "Add tests for this method"
- `_unit.py:682` - "Add tests for this method"
- `_network.py:405` - "Parse more stuff"
- `_client.py:127` - "Should we try to get access to the network name here?"
- `_client.py:150` - "Implement proper handling after understanding this behavior"
- `_client.py:160` - "Verify counter"
- `_client.py:174` - "Verify Digest 2"

### 19. Documentation Issues
- README references `demo.py` which doesn't exist (should be `demo/web_app.py`)
- No API documentation for `setControl()` in docstrings
- Missing examples for sensor handling
- No documentation on error handling patterns

### 20. Testing Gaps
- No tests for `_client.py` (BLE interaction)
- No tests for `_network.py` (HTTP API interaction)
- No tests for `_discover.py`
- No integration tests
- Test coverage appears low

### 21. Code Style Issues
- Some files use `ruff: noqa: F401` for unused imports
- Inconsistent docstring formatting
- Some methods missing docstrings entirely
- Line length exceeds 88 chars in many places

---

## 🎯 IMPROVEMENT ROADMAP

### Phase 1: Critical Fixes (Week 1-2)
**Goal: Make demo functional and fix critical library bugs**

| Task | File | Effort | Priority |
|------|------|--------|----------|
| Fix threading model in demo | `demo/web_app.py` | 4h | HIGH |
| Add unit serialization | `demo/web_app.py` | 3h | HIGH |
| Fix frontend state expectations | `demo/static/script.js` | 4h | HIGH |
| Fix Group.groudId typo | `src/CasambiBt/_unit.py` | 1h | HIGH |
| Export error types | `src/CasambiBt/__init__.py` | 1h | HIGH |
| Reduce logging verbosity | `src/CasambiBt/_client.py` | 1h | HIGH |
| Fix memory leak in callbacks | `src/CasambiBt/_casambi.py` | 2h | HIGH |

### Phase 2: Robustness Improvements (Week 3-4)
**Goal: Harden library for production use**

| Task | File | Effort | Priority |
|------|------|--------|----------|
| Add connection timeouts | `src/CasambiBt/_client.py` | 4h | HIGH |
| Make Unit state changes trigger callbacks | `src/CasambiBt/_unit.py` | 4h | HIGH |
| Add input validation to demo | `demo/web_app.py` | 3h | MEDIUM |
| Add CORS support | `demo/web_app.py` | 1h | MEDIUM |
| Add retry logic for transient failures | `_network.py`, `_client.py` | 4h | MEDIUM |
| Improve switch event parsing | `src/CasambiBt/_switch.py` | 3h | MEDIUM |

### Phase 3: Enhancements (Week 5-6)
**Goal: Improve developer experience**

| Task | File | Effort | Priority |
|------|------|--------|----------|
| Replace polling with SSE/WebSocket | `demo/web_app.py` | 4h | MEDIUM |
| Add session persistence | `demo/web_app.py` | 4h | MEDIUM |
| Add proper cache migration | `src/CasambiBt/_cache.py` | 3h | LOW |
| Complete TODO items | Various | 8h | LOW |
| Improve documentation | README.md, docstrings | 4h | LOW |
| Add more tests | `tests/` | 8h | LOW |

### Phase 4: Technical Debt (Ongoing)
**Goal: Code quality improvements**

| Task | File | Effort | Priority |
|------|------|--------|----------|
| Add missing type hints | All source files | 4h | LOW |
| Fix ruff lint issues | All source files | 4h | LOW |
| Add property setters for Unit state | `_unit.py` | 4h | LOW |
| Address all TODO comments | Various | 8h | LOW |
| Add integration tests | `tests/` | 8h | LOW |

---

## 📊 SUCCESS METRICS

### Library (src/CasambiBt/)
- [ ] All public classes and functions have docstrings
- [ ] All error types exported in `__init__.py`
- [ ] No memory leaks in callback handling
- [ ] All BLE operations have timeouts
- [ ] Unit state changes properly trigger callbacks
- [ ] Group.groudId typo fixed
- [ ] Type hints complete and accurate

### Demo (demo/)
- [ ] Application starts without errors
- [ ] Can discover networks
- [ ] Can connect to network
- [ ] Units display in dashboard
- [ ] Controls are functional
- [ ] Real-time updates work (SSE or polling)
- [ ] State persists across page refreshes
- [ ] No race conditions in state management

---

## 🎯 IMMEDIATE NEXT STEPS

1. **Fix the demo threading model** - This is the most critical blocker
2. **Fix unit serialization** - Demo will not work without this
3. **Fix the typo in Group.groudId** - Breaks group operations
4. **Export error types** - Needed for proper error handling
5. **Reduce logging verbosity** - Current logging fills disks

---

## 📋 FILE-SPECIFIC ACTION ITEMS

### src/CasambiBt/__init__.py
- [ ] Export all error types from `errors.py`
- [ ] Export `ColorSource` enum
- [ ] Consider exporting `SwitchEvent` for advanced users

### src/CasambiBt/_unit.py
- [ ] Fix `Group.groudId` → `Group.groupId` (BACKWARDS COMPATIBILITY: keep alias)
- [ ] Add property setters for `Unit.state`, `Unit.online`
- [ ] Consider making Unit immutable (frozen dataclass)
- [ ] Add tests for `getStateAsBytes` and `setStateFromBytes`

### src/CasambiBt/_casambi.py
- [ ] Use weakref for callback lists
- [ ] Add max callback list size
- [ ] Add timeout to `connect()` operation
- [ ] Improve error messages for connection failures

### src/CasambiBt/_client.py
- [ ] Move packet logging to DEBUG level
- [ ] Add timeouts to all BLE operations
- [ ] Add packet length validation
- [ ] Handle unknown packet types more gracefully

### src/CasambiBt/_network.py
- [ ] Add retry logic with exponential backoff
- [ ] Improve cache version migration
- [ ] Add better error messages for API failures

### demo/web_app.py
- [ ] REFACTOR: Use async Flask (Quart) or proper threading
- [ ] Add unit serialization helpers
- [ ] Add CORS support
- [ ] Add input validation
- [ ] Add session persistence
- [ ] Add proper error handling
- [ ] Add logging

### demo/static/script.js
- [ ] Fix state property names (dimmer→level, onoff→onOff, etc.)
- [ ] Fix unit structure expectations (unitType.controls, etc.)
- [ ] Add error handling for failed API calls
- [ ] Improve UI feedback

### demo/templates/index.html
- [ ] Add loading states
- [ ] Add error display
- [ ] Improve layout for mobile

---

## ⚠️ BREAKING CHANGES TO CONSIDER

1. **Group.groudId → Group.groupId**: This is a typo that should be fixed. Maintain `groudId` as deprecated alias for backwards compatibility.

2. **Logging reduction**: Users relying on INFO-level packet logs for debugging will need to change to DEBUG.

3. **Callback weak references**: Code that stores callback references in variables may find callbacks disappearing unexpectedly.

---

## 🔍 TESTING REQUIREMENTS

Each PR should include:
- Unit tests for new functionality
- Integration tests for complex interactions
- Manual testing of demo application
- Documentation updates

---

## 📅 ESTIMATED TIMELINE

| Phase | Duration | Deliverables |
|-------|----------|--------------|
| Phase 1 | 2 weeks | Functional demo, critical bug fixes |
| Phase 2 | 2 weeks | Robust library, hardened error handling |
| Phase 3 | 2 weeks | Enhanced features, better UX |
| Phase 4 | Ongoing | Code quality, technical debt |

---

## 🎉 COMPLETION CRITERIA

The project improvements are complete when:
1. ✅ Demo application is fully functional
2. ✅ Library has no known critical bugs
3. ✅ All error types are properly exported
4. ✅ Memory leaks are fixed
5. ✅ Timeouts are in place for all external operations
6. ✅ Type hints are complete and accurate
7. ✅ Test coverage is >80%
8. ✅ All documentation is updated
