# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

CasambiBt is an alpha-quality Python library for controlling Casambi-based Bluetooth lighting/shade/sensor networks directly over BLE, without a gateway or the official Casambi cloud API. The protocol implementation is based on independent reverse engineering. `demo/` contains a Quart-based web app that exercises the library.

## Development environment

Dependencies are managed with Pipenv (`Pipfile`); package metadata lives in `setup.cfg`, with `pyproject.toml` holding tool config (ruff, isort, pytest) and optional extras.

```bash
pipenv install --dev      # install all dependencies incl. dev tools
pipenv shell               # activate the venv
```

Optional transport extras (`aioesphomeapi`, `homeassistant-api`) are in `[dev-packages]` in the Pipfile so they're available during development, but are declared as optional extras (`esphome`, `homeassistant`) for end users in `setup.cfg`.

## Common commands

```bash
# Lint / format / type-check (all run in CI via .github/workflows/lint.yml)
pipenv run isort --check-only --diff .
pipenv run black --check --diff .
pipenv run ruff check .
pipenv run mypy .

# Auto-fix formatting
pipenv run isort .
pipenv run black .

# Tests
pipenv run pytest                          # full suite
pipenv run pytest tests/test_device_types.py            # single file
pipenv run pytest tests/test_device_types.py::test_name # single test
```

Tests live in `tests/` and use plain pytest (`testpaths = ["tests"]`, `python_files = test_*.py` per `pyproject.toml`). `tests/conftest.py` manually inserts `src/` onto `sys.path` rather than relying on an editable install. Some tests (`test_device_types.py`) build fixtures from JSON specs in `doc/fixtures-specs/` describing real device control layouts (louvers, screens, sensors) — use these when adding coverage for a new device type instead of hand-rolling `UnitType`/`UnitControl` objects.

CI (`.github/workflows/lint.yml`) runs on Python 3.11–3.14 via pipenv and gates on isort, black, ruff, and mypy — run all four before considering a change done.

### Running the demo

```bash
python demo/web_app.py   # Quart app on http://0.0.0.0:5000
```

`demo.py` at the repo root is a minimal scripted example (connect, list units, set a level) — read it first when you need a quick end-to-end usage reference.

## Architecture

### Transport abstraction

BLE access is behind the `BluetoothTransport` / `TransportConnection` ABCs in `_transport.py`, so the rest of the library (`_client.py`, `_discover.py`) never talks to `bleak` directly — it depends only on these interfaces. Three implementations exist:

- `_bleak_transport.py` — local adapter via `bleak` (default, always available).
- `_esphome_transport.py` — remote BLE via an ESPHome Bluetooth Proxy (`aioesphomeapi`), optional dependency.
- `_homeassistant_transport.py` — uses a Home Assistant instance to discover/manage ESPHome proxies (`homeassistant-api`), optional dependency.

`_transport_factory.py` is the seam between them:
- `get_transport()` auto-selects based on env vars (`ESPHOME_IP`/`ESPHOME_PORT`/`ESPHOME_NOISE_PSK`), falling back to bleak if the optional dependency isn't installed.
- `get_transport_by_type(transport_type, **kwargs)` builds a specific transport explicitly; raises `ImportError` if the extra isn't installed and `ValueError` for missing required config.

Optional transports are imported lazily inside functions (not at module top-level) so the base package works without `aioesphomeapi`/`homeassistant-api` installed. `src/CasambiBt/__init__.py` mirrors this: it tries to import `HomeAssistantTransport` and only adds it to `__all__` if the import succeeds — follow this pattern for any new optional transport.

### Core layers (independent of transport)

1. **`Casambi`** (`_casambi.py`) — top-level orchestrator and the main user-facing entry point. Owns a `CasambiClient` and `Network`, manages callbacks (unit changed, switch event, disconnect), and exposes both the legacy device-specific setters (`setLevel`, `setColor`, `setTemperature`, ...) and the preferred generic `setControl(target, UnitControlType, value)` / `switchToScene()` API.
2. **`CasambiClient`** (`_client.py`) — BLE protocol layer built on the transport abstraction plus `bleak-retry-connector`. Handles the handshake (ECDSA key exchange, auth), encrypts/decrypts packets, and parses incoming UnitState/SwitchEvent/NetworkConfig notifications on characteristic `c9ffde48-ca5a-0001-ab83-8f519b482f77`.
3. **`Network`** (`_network.py`) — network-level state: session/auth token lifecycle, cloud metadata sync (protocol versions 10–11), and on-disk caches (`session.pck`, `types.pck`, pickle format, path configurable via `cachePath`).
4. **`Encryptor`** (`_encryption.py`) — AES-ECB, CMAC, XOR, and ECDSA primitives for the protocol.
5. **`OperationsContext`** (`_operation.py`) — builds outgoing command packets (SetLevel, SetColor, SetSlider, SetState, etc.) within the 63-byte payload limit.
6. **`_discover.py`** — BLE scan filtered to the Casambi service UUID; on macOS falls back to an undocumented IOBluetooth API to obtain the real MAC address (macOS doesn't expose it via the public API — required for the protocol to work).

### Device model and roles (`_unit.py`)

Devices are modeled generically rather than as "lights": `Unit` holds a `UnitType` (its `UnitControl`s) and a `UnitState`. `UnitType.device_role` derives a semantic `DeviceRole` (`LIGHT`, `MOTORIZED_SHADE`, `MOTORIZED_SCREEN`, `SENSOR`, `UNKNOWN`) from the unit's control set — this is how consumers should distinguish device kinds rather than inspecting control types directly.

`Casambi.setControl()` is the preferred write API: it dispatches by `UnitControlType` (DIMMER, SLIDER, ONOFF, RGB, TEMPERATURE, ...) and raises `ReadOnlyControlError` for read-only controls (e.g. `SENSOR`) or controls not present/writable on the target. Legacy per-purpose methods (`setLevel`, `setSlider`, `setVertical`, `setColor`, `setTemperature`, `setColorXY`, `setWhite`, `turnOn`) remain for backward compatibility — prefer `setControl()` in new code.

`ONOFF` dispatch branches by `DeviceRole` because there's no universal on/off opcode. Lights have no dedicated `ONOFF` control at all — `setControl(..., ONOFF, ...)` is accepted anyway and translated to `turnOn()` (restoring last brightness) or `setLevel(target, 0)`. `MOTORIZED_SHADE`/`MOTORIZED_SCREEN` fixtures pack on/off as a bit alongside their `SLIDER`/`DIMMER` position in one state blob, with no dedicated on/off opcode either, so `setControl()` instead copies `target.state`, flips `.onoff`, and pushes it via the offset-aware `setUnitState()`/`SetState` path rather than `OpCode.SetLevel` — `SetLevel` either targets no field (shades have no dimmer control) or the wrong one (screens).

#### Sensor control types and the round-robin group protocol

Beyond the plain `SENSOR` type, `UnitControlType` has `PRESENCE`, `LUX`, `SENSORGROUP`, and `SENSORGROUPVALUE` for sensor-platform-style fixtures (see `doc/fixtures-specs/sensors-platform.json`, `louvers.json`, `screen.json`). `PRESENCE`/`LUX` decode independently onto `UnitState.presence`/`.lux` like any other control. `SENSORGROUP`/`SENSORGROUPVALUE` back a set of named, tagged `SENSOR` controls (`length: 0`, distinguished by `UnitControl.tag`) that share one offset — decoded into `UnitState.sensors: dict[str, int]` keyed by control name.

This group's wire format was confirmed empirically against live device captures (not documented anywhere officially), so it's worth understanding before touching `Unit._decode_tagged_sensor`/`_index_sensor_groups`: **the device reports exactly one tagged sensor's fresh reading per state update, round-robin.** `SENSORGROUP`'s raw value is a 1-based index of which tag just got refreshed (`tag = sensorgroup_raw - 1`); `SENSORGROUPVALUE`'s *entire* raw value (not a bit-slice divided across tags — that was an earlier, incorrect assumption) is that one tag's reading, used as-is with no linear `min`/`max` scaling (unlike `LUX`/plain `SENSOR`, where min/max *are* a scale target). Tags not selected this update simply keep their last known value in `UnitState.sensors` — don't treat a missing update as "zero".

`UnitType.device_role` OR's `PRESENCE`/`LUX`/`SENSORGROUP`/`SENSORGROUPVALUE` into the same branch as `SENSOR` for `DeviceRole.SENSOR` classification, but a device with these controls isn't necessarily role `SENSOR` — `louvers.json` and `screen.json` both carry a `sensorgroup`/tagged-sensor block alongside a `SLIDER`/`DIMMER` and classify as `MOTORIZED_SHADE`/`MOTORIZED_SCREEN` instead. Don't assume `UnitState.sensors` is only populated on `SENSOR`-role units.

### Error hierarchy (`errors.py`)

All exceptions derive from `CasambiBtError`: `NetworkNotFoundError`, `NetworkUpdateError`, `NetworkOnlineUpdateNeededError`, `AuthenticationError`, `ConnectionStateError`, `BluetoothError`, `ProtocolError`, `UnsupportedProtocolVersion`, `ReadOnlyControlError`. None of these are re-exported from `CasambiBt/__init__.py` (only `Casambi`, transports, and `_unit.py` types are) — import them from `CasambiBt.errors` directly, e.g. `from CasambiBt.errors import ConnectionStateError`.

### Demo app (`demo/web_app.py`)

Quart (async Flask) app, not Flask — required because it drives the async `Casambi`/transport APIs directly on the request-handling event loop. State (`casambi_instance`, `units_cache`, `connection_status`) is global and guarded by a single `asyncio.Lock`; Casambi's synchronous callbacks (`on_unit_changed`, `on_disconnected`) push onto an `asyncio.Queue` consumed by a background task (`process_state_queue`) rather than mutating shared state directly from the callback. `serialize_unit()` is the boundary that converts `Unit`/`UnitState` objects into JSON-safe dicts with frontend-expected field names — update it when adding new state fields that the UI needs. `get_position_control()` finds whichever `SLIDER`/`DIMMER`/`VERTICAL` control backs a shade/screen's open/close position and normalizes it to a 0–100% `positionPercent` against that control's own `min`/`max`, both in `serialize_unit()` and in `POST /api/units/<id>/position`, which does the reverse mapping. The frontend lives in `demo/static/app.js` (not `script.js`, despite what older references may say) and polls `/api/units` every 3s rather than using push updates.

## Notes

- The library's public surface is intentionally device-agnostic; when adding a new device type or control, extend `DeviceRole`/`UnitControlType` and the role-inference logic in `_unit.py` rather than special-casing device names elsewhere.
- `ROADMAP.md` tracks known robustness gaps and planned fixes — check it for current status before assuming an odd pattern is intentional or unaddressed.
