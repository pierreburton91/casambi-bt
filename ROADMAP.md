# Casambi-BT Project Improvement Roadmap

_Last verified against code: 2026-08-06 (branch `feat/covers-handling`)._

## Executive Summary

The demo app rewrite (Quart, serialization, CORS, session persistence, input
validation) is **complete** — the app described as "non-functional" in the
original version of this roadmap now works end to end. Since that original
assessment, the project also grew three feature areas it didn't previously
mention at all: an **ESPHome/Home Assistant remote-BLE transport layer**, a
**sensor platform** (presence/lux/tagged round-robin sensor groups — see
CLAUDE.md for the wire-format details), and **motorized shade/screen on/off +
position control**.

What's left is mostly library hardening (timeouts, callback lifecycle, a
stale typo with a real API-surface impact) and a code-quality baseline that
has regressed: **ruff, isort, black, and mypy all currently fail** on this
branch, even though CI gates on all four (see item 8 below). Whoever picks
this up next should treat restoring a clean lint baseline as its own
short task, since new work will keep failing CI until it's fixed regardless
of what else gets tackled.

---

## ✅ RESOLVED

These were tracked as broken/missing in earlier versions of this roadmap and
are now done, verified directly against the code:

- **Demo threading model** — `demo/web_app.py` is Quart-based (async), with a
  real `asyncio.Lock` guarding shared state and an `asyncio.Queue` +
  background consumer task (`process_state_queue`) decoupling Casambi's sync
  callbacks from request handling. No `threading.Thread` remains.
- **Demo unit serialization** — `serialize_unit()` (`demo/web_app.py`)
  converts `Unit`/`UnitState` into JSON-safe dicts and is used by every API
  endpoint that returns unit data.
- **Frontend/backend field mismatch** — the frontend was rewritten as
  `demo/static/app.js` (replacing the old `script.js`); it consumes the
  exact field names `serialize_unit()` emits, including back-compat aliases
  like `state.onOff`/`state.dimmer`.
- **CORS support** — `demo/web_app.py` wraps the app with `quart_cors.cors()`.
- **Session persistence across refresh** — `app.js` persists connection
  config to `localStorage` and auto-reconnects on load via `tryReconnect()`.
  Note: the password is stored in plaintext in `localStorage` — fine for a
  local demo, but flag this if the demo is ever exposed beyond localhost.
- **Input validation on control endpoints** — `/api/units/<id>/control`
  validates `control_type` against `UnitControlType` and rejects unknown
  values with 400; `/api/units/<id>/position` validates `percent` is numeric
  and in `[0, 100]`.
- **README accuracy** — documents `demo.py` (root-level scripted example,
  which exists) and `demo/web_app.py` separately, and covers `setControl()`
  and sensor handling (including the round-robin group protocol) in depth.

---

## 🚨 OPEN — Correctness / API-surface

### 1. `Group.groudId` typo has no alias, contradicts its own docstring
**Location:** `src/CasambiBt/_unit.py:808,813`, `src/CasambiBt/_casambi.py:496-497`

The field is still spelled `groudId`, but the docstring right above it says
`:ivar groupId:`. `Casambi._send()` reads `target.groudId` directly. There is
no `groupId` alias anywhere in the repo. This is a one-line typo that's been
outstanding across multiple roadmap revisions — fix it and add a `groupId`
property alias for anyone who already read the docstring and typed the
"correct" name.

### 2. Error types not exported from the package root
**Location:** `src/CasambiBt/__init__.py:33-48`

`errors.py` defines `CasambiBtError` and 8 subclasses (`NetworkNotFoundError`,
`ConnectionStateError`, `ReadOnlyControlError`, etc.), none of which appear
in `__all__`. Consumers can't `from CasambiBt import ConnectionStateError` —
they have to reach into `CasambiBt.errors` directly, which isn't documented
anywhere as the intended import path.

### 3. `Unit` state mutation still bypasses encapsulation internally
**Location:** `src/CasambiBt/_unit.py:487-510`, `src/CasambiBt/_casambi.py:535-536,657`

`_state`/`_on`/`_online` gained read-only `@property` getters, but the
underlying fields are still plain mutable attributes, and `_casambi.py`
itself writes `u._on = ...` / `u._online = ...` directly rather than through
any setter. So the property layer doesn't actually prevent inconsistent
state — it just hides the fields from the public API while the library's
own code still pokes them directly. Either add real setters that the
library itself uses, or drop the pretense of encapsulation.

---

## ⚠️ OPEN — Robustness

### 4. Unbounded packet logging at INFO level
**Location:** `src/CasambiBt/_client.py:442-444` (raw encrypted packet hex),
`:459-461` (decrypted payload hex)

Every inbound packet is still logged at `INFO` with a full hex dump of both
the encrypted and decrypted payload. Anyone running with default logging
gets disk growth proportional to traffic and decrypted protocol data in
plaintext logs. Move to `DEBUG` (or add rate limiting) as originally
planned.

### 5. No timeout on BLE protocol operations
**Location:** `src/CasambiBt/_client.py`

`exchangeKey()`, `authenticate()`, and `send()` have no `asyncio.wait_for` or
equivalent around their awaits. A device that stops responding mid-handshake
or mid-send hangs the caller indefinitely. BLE *connection establishment*
does get retry/backoff for free via `bleak-retry-connector`
(`_bleak_transport.py:58-66`), but that's a different layer — it doesn't
help once a session is established and a specific request stalls.

### 6. Callback lists have no automatic lifecycle management
**Location:** `src/CasambiBt/_casambi.py:40-42,571-639`

`registerUnitChangedHandler`/`registerSwitchEventHandler`/
`registerDisconnectCallback` each have a matching `unregister*` method, so
manual cleanup is possible — this is better than previously described. But
there's still no weak-reference option and no cap, so a consumer that
forgets to unregister (e.g. on an exception path) leaks the listener for the
life of the `Casambi` instance. Lower priority than originally scored, since
a manual escape hatch exists; worth a `weakref.WeakMethod` option if this
becomes a real-world pain point rather than a theoretical one.

### 7. Cache invalidation is all-or-nothing
**Location:** `src/CasambiBt/_cache.py:14,42-70`

`CACHE_VERSION` is now `3` (bumped during the sensor-platform work), and a
version bump still deletes the entire cache directory
(`_ensureCacheValid()`) rather than migrating or selectively invalidating
stale entries. Fine at current scale; would matter more if the cache grows
expensive to rebuild.

### 8. Lint/type-check baseline is currently broken
**Location:** whole tree

CLAUDE.md states CI "gates on isort, black, ruff, and mypy" — right now all
four fail locally:
- `ruff check .` → 131 errors (mostly `T201` print-in-tests and whitespace,
  20 auto-fixable)
- `isort --check-only .` → 6 files misordered (`tests/conftest.py`,
  `tests/test_integration_devices.py`, `tests/test_slider_minmax.py`,
  `tests/test_device_types.py`, `tests/test_sensor_commands.py`,
  `src/CasambiBt/_casambi.py`)
- `black --check .` → 16 files would be reformatted, incl.
  `demo/web_app.py`, `src/CasambiBt/_unit.py`
- `mypy .` → 63 errors in 10 files, including real bugs, not just missing
  annotations: `_encryption.py` bytearray/bytes mismatches, `arg-type`
  errors on `get_transport_by_type` calls in `demo/web_app.py:349,403`
  (passing a bare `str` where a `Literal["bleak","esphome","homeassistant"]`
  is expected), and `union-attr` issues in `examples/motorized_and_sensors.py`
  from not narrowing `UnitState | None`.

Run `pipenv run isort . && pipenv run black .` for the easy wins, then
triage the ruff/mypy findings — some are real type bugs, not just style.

### 9. Retry logic is inconsistent across layers
**Location:** `src/CasambiBt/_network.py`, `_client.py`

BLE connection establishment retries via `bleak-retry-connector`. Nothing
else does: `_network.py` raises `NetworkUpdateError` on a bad HTTP status
with a comment suggesting the caller retry, but there's no actual backoff
loop, and protocol-level `send()`/`exchangeKey()` failures in `_client.py`
aren't retried either.

### 10. Silent handling of unrecognized protocol data
**Locations:**
- `src/CasambiBt/_client.py:476-477` — unknown packet type → `logger.info`
- `src/CasambiBt/_switch.py:158` — unknown switch message type → `logger.info`

Both still log at INFO rather than something that would actually surface in
default deployments (WARNING) or get filtered out in normal operation
(DEBUG). Note `_switch.py` did gain real length validation since the last
roadmap revision (`_switch.py:55,81`, plus an `IndexError` safety net at
`:162-164`) — the parsing-fragility concern is mostly addressed; only the
log-level nit remains.

---

## 📝 LOW PRIORITY / TECHNICAL DEBT

### 11. Real-time updates still via polling
**Location:** `demo/static/app.js:624`

`setInterval(fetchUnits, 3000)`. Works fine for a demo; would need SSE/WS if
this ever needs to feel responsive with many units or multiple simultaneous
clients.

### 12. Testing gaps
`tests/` covers device-type fixtures, sensor commands, slider min/max, and
integration-style device scenarios — but nothing exercises `_client.py`
(BLE protocol/handshake), `_network.py` (HTTP sync), or `_discover.py`
directly. No coverage tooling is configured (no `pytest-cov`, no threshold
in `pyproject.toml`), so there's no way to know the actual number, only that
three whole modules have zero direct test references.

### 13. Current TODOs in source
```
src/CasambiBt/_casambi.py:156
src/CasambiBt/_client.py:177,375,385,435,498,500
src/CasambiBt/_encryption.py:79
src/CasambiBt/_network.py:34,54,188,260,319
src/CasambiBt/_operation.py:31
src/CasambiBt/_switch.py:18,19
src/CasambiBt/_unit.py:209,210,464,512,522,675,686,736
```
`_unit.py:464` is the still-unresolved "make unit immutable" TODO tied to
item 3 above. Line numbers drift with every feature commit — re-grep
(`grep -rn TODO src/`) before trusting this list rather than assuming it's
current.

### 14. Cosmetic: sensor group value rendered as binary in the UI
**Location:** `demo/static/app.js:426`

Renders `sensorgroup` as `0b${value.toString(2).padStart(4,'0')}` — a
leftover from the disproven "bitmask" theory of the sensor group protocol
(see CLAUDE.md's sensor-group section: it's actually a 1-based tag index,
not a bitmask). Not a functional bug since the underlying decode in
`_unit.py` is correct, but the raw value shown in the UI is misleading to
anyone debugging via the demo.

---

## 🎯 SUGGESTED NEXT STEPS

Roughly in order of leverage vs. effort:

1. **Fix the lint/type baseline** (item 8) — everything else lands cleaner
   once `isort`/`black`/`ruff`/`mypy` are green again, and CI is presumably
   red right now for anyone opening a PR from a clean checkout.
2. **`groudId` → `groupId`** (item 1) + **export error types** (item 2) —
   both are small, both are real API papercuts that get more painful to fix
   the more the current names get depended on.
3. **Packet logging level** (item 4) — one-line log-level change, meaningful
   disk/security impact.
4. **BLE operation timeouts** (item 5) — the highest-effort item, but the
   only one that turns "device stops responding" into a recoverable error
   instead of a permanent hang.
5. Everything else in "OPEN — Robustness" and "LOW PRIORITY" as time allows;
   none of it is currently blocking real usage of the library or demo.
