import asyncio
import queue
import threading

from flask import Flask, jsonify, render_template, request

from CasambiBt import Casambi, discover
from CasambiBt._unit import UnitControlType

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

# Global variables for state management
casambi_instance = None
connection_status = {"connected": False, "network_name": None, "network_id": None, "error": None}
units_cache = {}
state_queue = queue.Queue()  # For async callback data
polling_enabled = False
discovered_devices = []  # List of BLEDevice
connection_status = {"connected": False, "network_name": None, "network_id": None, "error": None}
units_cache = {}
state_queue = queue.Queue()  # For async callback data
polling_enabled = False

# Background thread for async operations
loop = None

def run_async_loop():
    global loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_forever()

# Start the background thread
threading.Thread(target=run_async_loop, daemon=True).start()

def run_in_thread(coro):
    """Helper to run async functions in the background thread"""
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()

# Casambi callback handlers
def on_unit_changed(unit_id, state):
    """Callback for unit state changes"""
    state_queue.put({"type": "unit_update", "unit_id": unit_id, "state": state})

def on_disconnected():
    """Callback for disconnection"""
    global connection_status
    connection_status["connected"] = False
    connection_status["error"] = "Disconnected"

# API Endpoints

@app.route('/api/networks', methods=['GET'])
def get_networks():
    global discovered_devices
    try:
        discovered_devices = run_in_thread(discover())
        networks = [{"address": d.address, "name": d.name or "Unknown"} for d in discovered_devices]
        return jsonify({"success": True, "data": networks})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/connect', methods=['POST'])
def connect_network():
    global casambi_instance, connection_status, units_cache, discovered_devices
    try:
        data = request.get_json()
        address = data.get('address')
        password = data.get('password')

        # Find the BLEDevice by address
        device = next((d for d in discovered_devices if d.address == address), None)
        if not device:
            return jsonify({"success": False, "error": "Device not found"})

        casambi_instance = Casambi()
        casambi_instance.registerUnitChangedHandler(on_unit_changed)
        casambi_instance.registerDisconnectCallback(on_disconnected)

        run_in_thread(casambi_instance.connect(device, password))

        # Update status
        connection_status["connected"] = True
        connection_status["network_name"] = casambi_instance.networkName
        connection_status["network_id"] = casambi_instance.networkId
        connection_status["error"] = None

        # Fetch units
        units = casambi_instance.units
        units_cache = {str(u.uuid): u for u in units}

        return jsonify({"success": True})
    except Exception as e:
        connection_status["error"] = str(e)
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify({"success": True, "data": connection_status})

@app.route('/api/disconnect', methods=['POST'])
def disconnect_network():
    global casambi_instance, connection_status, units_cache
    try:
        if casambi_instance:
            run_in_thread(casambi_instance.disconnect())
        casambi_instance = None
        units_cache.clear()
        connection_status = {"connected": False, "network_name": None, "network_id": None, "error": None}
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/units', methods=['GET'])
def get_units():
    if not connection_status["connected"]:
        return jsonify({"success": False, "error": "Not connected"})
    return jsonify({"success": True, "data": units_cache})

@app.route('/api/units/<unit_id>/state', methods=['GET'])
def get_unit_state(unit_id):
    if unit_id not in units_cache:
        return jsonify({"success": False, "error": "Unit not found"}), 404
    return jsonify({"success": True, "data": units_cache[unit_id]})

@app.route('/api/units/<unit_id>/control', methods=['POST'])
def control_unit(unit_id):
    if not casambi_instance:
        return jsonify({"success": False, "error": "Not connected"})
    try:
        data = request.get_json()
        control_type_str = data.get('control_type')
        value = data.get('value')

        # Map string to UnitControlType
        control_type = getattr(UnitControlType, control_type_str, None)
        if not control_type:
            return jsonify({"success": False, "error": f"Invalid control type: {control_type_str}"})

        unit = units_cache.get(unit_id)
        if not unit:
            return jsonify({"success": False, "error": "Unit not found"})

        run_in_thread(casambi_instance.setControl(unit, control_type, value))

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
@app.route('/api/poll-state', methods=['GET'])
def poll_state():
    # Process pending state updates
    while not state_queue.empty():
        update = state_queue.get()
        if update["type"] == "unit_update":
            units_cache[update["unit_id"]] = update["state"]
    return jsonify({"success": True, "data": units_cache})

@app.route('/api/poll-toggle', methods=['POST'])
def toggle_polling():
    global polling_enabled
    data = request.get_json()
    polling_enabled = data.get('enabled', False)
    return jsonify({"success": True, "data": {"polling_enabled": polling_enabled}})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
