# Roadmap

_Last verified against the code: 2026-11-17 (integration 0.1.3)._

This repository is a custom Home Assistant integration that embeds a modified
copy of the `casambi-bt` library (see README and NOTICE). Items are grouped by
where they live: the integration first, since that is what users run, then the
embedded library, then the demo. Line numbers drift: re-check the code before
trusting a location.

---

## Done

- **Lint and type-check baseline**: isort, black, ruff and mypy pass, and the
  whole pytest suite passes with `-W error`.
- **Lost BLE links are detected again** (0.1.1): the disconnect callback is
  forwarded through the transport layer, and the coordinator reconnects with
  backoff.
- **Per-packet logs moved from INFO to DEBUG** (0.1.1).
- **Setup retries on transient errors** (0.1.2): BLE errors (e.g. GATT 133),
  Casambi cloud errors and timeouts raise `ConfigEntryNotReady`, so Home
  Assistant retries; a wrong password still triggers reauthentication.
- **Single copy of the library** (0.1.3): `src/` was removed;
  `custom_components/casambi_bt/CasambiBt/` is the only source.
- **Demo app** rebuilt on Quart (async lock, queue-based callbacks, unit
  serialization, input validation, CORS).

---

## Home Assistant integration

### 1. Watchdog for silent links
If entities freeze without a "Lost connection" log line, the link is dead but
not reported. Track the time since the last notification and force a
reconnect after a quiet period.

### 2. Single point of failure: one unit per config entry
**Location:** `config_flow.py`, `coordinator.py`

The entry is keyed on the BLE address of the unit chosen at setup
(`CONF_ADDRESS`, also the unique_id) and has no "reconfigure" step. If that unit
is out of range, the entry cannot connect. Idea: key the entry on the network's
persistent identifier (manufacturer data 963) and connect through whichever
unit currently has the best signal.

### 3. Missing platforms and features
- No switch platform for plain on/off fixtures (blocked by library item 5).
- No RGBW, no cover stop (no known opcode), no button events, scenes or groups.

### 4. Translations
Only `translations/en.json` exists. Add French and Dutch.

---

## Embedded library (`custom_components/casambi_bt/CasambiBt/`)

### 5. `setControl(ONOFF)` sends the dimmer opcode to plain on/off units
For any unit that isn't a shade or screen, ONOFF is translated to a dimmer
write instead of an offset-aware write to the actual on/off control. Fix this
before adding a switch platform.

### 6. Casambi cloud robustness (`_network.py`)
- Any non-200 answer when opening a session raises `AuthenticationError`, so a
  cloud outage looks like a wrong password and triggers reauthentication.
- An HTTP error from the cloud during the network update does not fall back to
  the cache.
- Refreshing the unit-type cache (28-day lifetime) does not catch
  `httpx.RequestError`: without Internet at startup, setup fails.
- More generally, only BLE connection establishment retries (via
  `bleak-retry-connector`); HTTP and protocol-level `send()`/`exchangeKey()`
  failures are not retried.

### 7. No timeout on BLE protocol operations (`_client.py`)
`exchangeKey()`, `authenticate()` and `send()` have no internal timeout. The
integration bounds every call itself (`CONNECT_TIMEOUT`, `OPERATION_TIMEOUT`),
but the library still hangs if used directly.

### 8. ESPHome transport cannot connect
`_esphome_transport.py` is aligned with aioesphomeapi 45 but does not propagate
`address_type`, so it does not work. The integration does not use it (it goes
through Home Assistant's Bluetooth stack); only the demo is affected.

### 9. API papercuts
- `Group.groudId` typo (`_unit.py`, used in `_casambi.py`); the docstring says
  `groupId`. Add a `groupId` alias.
- Error types are not exported from the package root: consumers must import
  from `CasambiBt.errors`.
- `Unit` state is exposed through read-only properties, but `_casambi.py` still
  writes the private fields directly.

### 10. Log levels for unrecognized protocol data
Unknown packet types (`_client.py`) and unknown switch messages or leftover
data (`_switch.py`) are logged at INFO. Pick WARNING (to surface them) or DEBUG.

### 11. Smaller items
- Callback lists have `unregister*` methods but no weak-reference option.
- A cache version bump deletes the whole cache directory instead of migrating.
- No direct tests for `_discover.py` or the handshake in `_client.py`, and no
  coverage tooling.
- `TODO` comments remain in the source: `grep -rn TODO custom_components/casambi_bt/CasambiBt/`.

---

## Demo app

### 12. Sensor group shown as binary
`demo/static/app.js` renders `sensorgroup` as a binary string, a leftover of the
disproven bitmask theory (it is a 1-based tag index, see CLAUDE.md).

### 13. Polling
The frontend polls `/api/units` every 3 s. Fine for a diagnostic tool.

---

## Packaging and documentation

- The `v1.0.0` Git tag predates this project and is misleading.
- No GitHub releases: HACS follows `main`.
