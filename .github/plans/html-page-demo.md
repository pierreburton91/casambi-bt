# Plan: Web Interface for Casambi BT Controls

## TL;DR
Replace the scripted CLI demo with a Flask-based web interface at `localhost:5000`. Users discover networks, enter the password to connect via Bluetooth, then control all discovered units through an interactive dashboard. Real-time updates use optional polling (off by default). Each unit displays in a flat list with controls/state cards tailored to its capabilities (e.g., dimmer for lights, slider for motorized shades, read-only values for sensors).

## User Choices
- Framework: Flask (simpler, lightweight)
- Real-time updates: Polling via fetch with a toggle (off by default)
- Scope: Handle discovery + connection workflow
- Unit display: All units in a flat list (no grouping)

## Steps

### Phase 1: Backend Foundation (Flask + Casambi Integration)
1. **Create Flask server** (`web_app.py`)
   - Initialize Flask app with async support (use threading + queue pattern)
   - Global `Casambi` instance for managing BLE connection
   - Track connection state and discovered networks
   - Implement request/response helpers for JSON API

2. **API endpoints for discovery & connection flow**
   - `GET /api/networks` → returns list of discovered BLE devices (address, optional friendly name)
   - `POST /api/connect` → accepts device address + password; initiates Bluetooth connection; returns network ID
   - `GET /api/status` → returns connection status, network name, discovered units count
   - `POST /api/disconnect` → gracefully closes connection

3. **API endpoints for unit control & state**
   - `GET /api/units` → returns all units with current state, capabilities, control types
   - `GET /api/units/<unit_id>/state` → returns current state of specific unit
   - `POST /api/units/<unit_id>/control` → accepts control type + value; sends command via Casambi API
   - `GET /api/poll-state` → returns all unit states (for polling)
   - `POST /api/poll-toggle` → toggle polling enabled/disabled status

4. **Background state tracking**
   - Register Casambi callbacks (unit changed, disconnect) to track state changes
   - Maintain in-memory state cache for quick polling responses
   - Catch and log all exceptions; expose errors in API responses

### Phase 2: Frontend Structure (HTML + CSS + JavaScript)
5. **Create HTML template** (`templates/index.html`)
   - Semantic HTML structure
   - Three sections: discovery form, connection form (hidden until networks found), main dashboard (hidden until connected)
   - Each unit gets a `<section>` with name, device role, state display, and controls

6. **Create stylesheet** (`static/style.css`)
   - Clean, minimal design (no frameworks)
   - Responsive layout for unit cards
   - Differentiate read-only states (cards) vs. writable controls (inputs/buttons)
   - Basic color coding by device role or state (on/off)

7. **Create client-side logic** (`static/script.js`)
   - Discovery flow: Fetch networks on page load or refresh button
   - Connection flow: User selects network, enters password, submits
   - Dashboard rendering: Loop through units; dynamically render control sections based on available controls
   - Polling system: Fetch `/api/poll-state` on interval; update UI reactively
   - Control interaction: Send `POST /api/units/<id>/control` on user input; update local state optimistically

### Phase 3: Unit-Specific Rendering (Control-Type Mapping)
8. **Map each UnitControlType to UI control**
   - `DIMMER` → slider (0-255) with % label
   - `ONOFF` → toggle button (on/off)
   - `TEMPERATURE` → number input + label (e.g., "2700K")
   - `RGB` → color picker or three sliders (R, G, B)
   - `WHITE` → slider (0-255)
   - `VERTICAL` → slider (0-255) for top/bottom balance
   - `SLIDER` → slider (check min/max from UnitType.controls)
   - `COLORSOURCE` → dropdown (TEMPERATURE, RGB, XY)
   - `XY` → read-only display or dual sliders
   - `SENSOR` → read-only display card (no controls)

9. **Handle read-only vs. writable controls**
   - Check `UnitControlType` against device role and capabilities
   - Sensors (DeviceRole.SENSOR) → always read-only
   - Render writable controls as inputs/sliders
   - Render read-only as text/card display

### Phase 4: Integration & Error Handling
10. **Connect Flask callbacks to Casambi state changes**
    - On unit state change: Update cache; if polling enabled, send via GET on next poll
    - On disconnect: Set connection status to False; show reconnection UI

11. **Error handling & feedback**
    - Wrap all API responses in standard JSON format: `{success: bool, data: *, error: string?}`
    - Display user-facing errors on frontend (connection failed, control failed, etc.)
    - Log all exceptions server-side with context

### Phase 5: Verification & Polish
12. **Manual verification steps**
    - [ ] Start Flask server; discover networks on page load
    - [ ] Select a network, enter password, verify connection completes
    - [ ] Verify all units display with correct controls for their device type
    - [ ] Toggle dimmer on a light; verify state updates (polling on/off)
    - [ ] Control a motorized shade slider; verify position updates
    - [ ] Read sensor values; verify no controls rendered
    - [ ] Test disconnect/reconnect flow
    - [ ] Verify UI is responsive on mobile viewport

## Relevant Files

### To Create
- `web_app.py` — Flask server; Casambi lifecycle management; REST API endpoints; callback handlers
- `templates/index.html` — Main page structure; discovery/connection forms; unit dashboard
- `static/style.css` — Clean, minimal styling; responsive card layout
- `static/script.js` — API integration; polling system; dynamic control rendering; state updates

### To Modify
- `demo.py` — Can remain as-is or be simplified (optional; not blocking web interface)

### To Reference
- `src/CasambiBt/_casambi.py` — Casambi API: `setLevel()`, `setControl()`, `registerUnitChangedHandler()`, etc.
- `src/CasambiBt/_unit.py` — Unit, UnitState, UnitControlType, DeviceRole enums
- [demo.py](demo.py) — Reference implementation for connection/control patterns

## Decisions

1. **Flask chosen** for simplicity; avoids FastAPI setup complexity while still supporting the async Casambi API
2. **Polling (off by default)** matches user preference; toggle allows users to opt-in for real-time updates without WebSocket overhead
3. **Full workflow** (discovery + connection) in web UI provides single entry point; no pre-existing connection needed
4. **Flat unit list** simplifies frontend; cleaner UI than role-based grouping
5. **In-memory state cache** avoids querying Bluetooth on every poll; relies on Casambi callbacks for updates
6. **Standard REST API** (`/api/units`, `/api/control`, etc.) keeps backend simple and testable

## Scope Boundaries

**Included:**
- BLE network discovery & connection
- Unit state display & real-time polling
- Control for all writable unit types (dimmer, temperature, color, slider, etc.)
- Error display & feedback
- Graceful disconnect

**Excluded (not in scope):**
- Scene switching (can be added later)
- Group control
- WebSockets (polling sufficient for v1)
- Mobile app (web-only)
- Advanced animations/transitions (clean design only)
- Persistent authentication/multi-user sessions

## Implementation Notes

### Threading & Async Pattern
Flask runs synchronously, but Casambi API is async. Handle this by:
- Use `asyncio` event loop in background thread for Casambi operations
- Queue state changes from callbacks to be read by Flask request handlers
- Never block Flask request handler on BLE operations; use futures/events

### State Cache Structure
```python
{
  "connected": bool,
  "network_name": str,
  "network_id": str,
  "units": {
    "<unit_id>": {
      "name": str,
      "device_role": str,
      "state": {...},
      "controls": [...]
    }
  },
  "polling_enabled": bool,
  "error": str | None
}
```

### API Response Format
```json
{
  "success": true,
  "data": {...},
  "error": null
}
```

### Unit Control Rendering Logic (JavaScript)
```javascript
// For each unit, iterate through available controls
for (const controlType of unit.controls) {
  if (controlType === "DIMMER") {
    // Render slider 0-255
  } else if (controlType === "ONOFF") {
    // Render toggle button
  } else if (controlType === "SENSOR") {
    // Render read-only display
  }
  // ... etc
}
```

### Error Recovery
- Network discovery fails → display "No networks found" with refresh button
- Connection fails → display error, return to discovery screen
- Control command fails → show toast/alert, keep UI state unchanged
- Polling fails → disable updates, show status message
- Disconnect detected → show reconnection UI
