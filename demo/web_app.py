import asyncio
import logging
import signal
import sys

from quart import Quart, jsonify, render_template, request
from quart_cors import cors

from CasambiBt import Casambi, discover
from CasambiBt._unit import UnitControlType, Unit

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Quart(__name__, static_folder='static', template_folder='templates')
app = cors(app, allow_origin="*")  # For development only

@app.get('/')
async def index():
    return await render_template('index.html')

# Global variables for state management
casambi_instance = None
connection_status = {"connected": False, "network_name": None, "network_id": None, "error": None}
units_cache = {}
state_lock = asyncio.Lock()  # For synchronizing access to shared state

discovered_devices = []  # List of BLEDevice
state_queue = asyncio.Queue()  # Async queue for state updates from callbacks
queue_task: asyncio.Task = None  # Background task for processing the queue
shutdown_event: asyncio.Event = None  # Event for graceful shutdown

# State update message types
class StateMessage:
    def __init__(self, msg_type: str, data=None):
        self.msg_type = msg_type
        self.data = data


async def process_state_queue():
    """Background task to process state updates from the async queue."""
    global connection_status, units_cache, shutdown_event
    while not shutdown_event.is_set():
        try:
            # Use timeout to allow periodic shutdown checks
            message = await asyncio.wait_for(state_queue.get(), timeout=0.1)
            try:
                async with state_lock:
                    if message.msg_type == "unit_update":
                        unit = message.data
                        units_cache[str(unit.uuid)] = unit
                        logger.debug(f"Updated unit {unit.uuid} in cache")
                    elif message.msg_type == "disconnected":
                        connection_status["connected"] = False
                        connection_status["error"] = "Disconnected"
                        logger.info("Connection status updated to disconnected")
            except Exception as e:
                logger.error(f"Error processing state queue message: {e}", exc_info=True)
            finally:
                state_queue.task_done()
        except asyncio.TimeoutError:
            # Timeout occurred, check shutdown_event again
            continue
        except asyncio.CancelledError:
            # Task was cancelled, exit gracefully
            logger.info("Queue processor cancelled, shutting down")
            break
        except Exception as e:
            logger.error(f"Unexpected error in queue processor: {e}", exc_info=True)


# Casambi callback handlers
def on_unit_changed(unit: Unit):
    """Callback for unit state changes - called synchronously by Casambi lib.
    
    Puts a message into the async queue for processing by the background task.
    """
    try:
        state_queue.put_nowait(StateMessage("unit_update", unit))
        logger.debug(f"Unit changed callback: {unit.name} ({unit.uuid})")
    except Exception as e:
        logger.error(f"Failed to queue unit update: {e}")

def on_disconnected():
    """Callback for disconnection - called synchronously by Casambi lib.
    
    Puts a message into the async queue for processing by the background task.
    """
    try:
        state_queue.put_nowait(StateMessage("disconnected"))
        logger.info("Disconnected callback triggered")
    except Exception as e:
        logger.error(f"Failed to queue disconnection: {e}")


def serialize_unit(unit: Unit) -> dict:
    """Convert Unit object to JSON-serializable dict with frontend-compatible property names."""
    state_dict = {}
    if unit.state:
        # Extract RGB components
        if unit.state.rgb:
            r, g, b = unit.state.rgb
            state_dict["red"] = int(r) if r is not None else None
            state_dict["green"] = int(g) if g is not None else None
            state_dict["blue"] = int(b) if b is not None else None
        
        # Extract XY components
        if unit.state.xy:
            state_dict["x"] = float(unit.state.xy[0]) if unit.state.xy[0] is not None else None
            state_dict["y"] = float(unit.state.xy[1]) if unit.state.xy[1] is not None else None
        
        state_dict.update({
            "dimmer": unit.state.dimmer,
            "white": unit.state.white,
            "temperature": unit.state.temperature,
            "vertical": unit.state.vertical,
            "slider": unit.state.slider,
            "sensor": unit.state.sensor,
            "onoff": unit.state.onoff,
            "colorSource": unit.state.colorsource.value if unit.state.colorsource else None,
            # Frontend expects these names
            "level": unit.state.dimmer,
            "onOff": unit.state.onoff,
        })
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


# API Endpoints

@app.get('/api/networks')
async def get_networks():
    """Discover available Casambi networks."""
    global discovered_devices
    try:
        logger.info("Starting network discovery")
        discovered_devices = await discover()
        networks = [{"address": d.address, "name": d.name or "Unknown"} for d in discovered_devices]
        logger.info(f"Discovered {len(networks)} networks")
        return jsonify({"success": True, "data": networks})
    except Exception as e:
        logger.error(f"Network discovery failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

@app.post('/api/connect')
async def connect_network():
    """Connect to a Casambi network."""
    global casambi_instance, connection_status, units_cache, discovered_devices
    try:
        data = await request.get_json()
        address = data.get('address')
        password = data.get('password')

        if not address:
            logger.warning("Connect request missing address")
            return jsonify({"success": False, "error": "Address is required"}), 400

        # Find the BLEDevice by address
        device = next((d for d in discovered_devices if d.address == address), None)
        if not device:
            logger.warning(f"Device not found for address: {address}")
            return jsonify({"success": False, "error": "Device not found"}), 404

        logger.info(f"Connecting to network: {device.name or device.address}")
        
        casambi_instance = Casambi()
        casambi_instance.registerUnitChangedHandler(on_unit_changed)
        casambi_instance.registerDisconnectCallback(on_disconnected)

        await casambi_instance.connect(device, password)

        # Update status with lock protection
        async with state_lock:
            connection_status["connected"] = True
            connection_status["network_name"] = casambi_instance.networkName
            connection_status["network_id"] = casambi_instance.networkId
            connection_status["error"] = None
            logger.info(f"Connected to network '{casambi_instance.networkName}'")

        return jsonify({"success": True})
    except ValueError as e:
        logger.error(f"Invalid request data: {e}")
        async with state_lock:
            casambi_instance = None
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"Connection failed: {e}", exc_info=True)
        async with state_lock:
            casambi_instance = None
            connection_status["connected"] = False
            connection_status["error"] = str(e)
        return jsonify({"success": False, "error": str(e)}), 500

@app.get('/api/status')
async def get_status():
    """Get current connection status."""
    async with state_lock:
        # Return a copy to avoid race conditions
        status_copy = dict(connection_status)
        logger.debug(f"Status request: {status_copy}")
        return jsonify({"success": True, "data": status_copy})

@app.post('/api/disconnect')
async def disconnect_network():
    """Disconnect from the current network."""
    global casambi_instance, connection_status, units_cache
    try:
        logger.info("Initiating disconnection")
        if casambi_instance:
            await casambi_instance.disconnect()
            logger.info("Casambi instance disconnected")
        async with state_lock:
            casambi_instance = None
            units_cache.clear()
            connection_status = {"connected": False, "network_name": None, "network_id": None, "error": None}
        logger.info("Disconnection complete, state cleared")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Disconnection failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

@app.get('/api/units')
async def get_units():
    """Get all units in the connected network."""
    async with state_lock:
        if not connection_status["connected"]:
            logger.warning("Units request while not connected")
            return jsonify({"success": False, "error": "Not connected"}), 400
        serialized = {uid: serialize_unit(u) for uid, u in units_cache.items()}
        logger.debug(f"Returning {len(serialized)} units")
    return jsonify({"success": True, "data": serialized})

@app.get('/api/units/<unit_id>/state')
async def get_unit_state(unit_id):
    """Get the state of a specific unit."""
    async with state_lock:
        if unit_id not in units_cache:
            logger.warning(f"Unit {unit_id} not found")
            return jsonify({"success": False, "error": "Unit not found"}), 404
        unit = units_cache[unit_id]
    logger.debug(f"Returning state for unit {unit_id}")
    return jsonify({"success": True, "data": serialize_unit(unit)})

@app.post('/api/units/<unit_id>/control')
async def control_unit(unit_id):
    """Send a control command to a unit."""
    global casambi_instance
    async with state_lock:
        if not casambi_instance:
            logger.warning(f"Control request for unit {unit_id} while not connected")
            return jsonify({"success": False, "error": "Not connected"}), 400
        unit = units_cache.get(unit_id)
        if not unit:
            logger.warning(f"Unit {unit_id} not found for control")
            return jsonify({"success": False, "error": "Unit not found"}), 404
    try:
        data = await request.get_json()
        if not data:
            logger.warning("Control request missing data")
            return jsonify({"success": False, "error": "Request data is required"}), 400
        
        control_type_str = data.get('control_type')
        value = data.get('value')

        if not control_type_str:
            logger.warning("Control request missing control_type")
            return jsonify({"success": False, "error": "control_type is required"}), 400

        # Map string to UnitControlType
        control_type = getattr(UnitControlType, control_type_str, None)
        if not control_type:
            logger.warning(f"Invalid control type: {control_type_str}")
            return jsonify({"success": False, "error": f"Invalid control type: {control_type_str}"}), 400

        logger.info(f"Sending {control_type_str}={value} to unit {unit.name} ({unit_id})")
        await casambi_instance.setControl(unit, control_type, value)
        logger.debug(f"Control command sent successfully")

        return jsonify({"success": True})
    except ValueError as e:
        logger.error(f"Invalid control value: {e}")
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"Control command failed for unit {unit_id}: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


async def cleanup():
    """Clean up resources on shutdown."""
    global casambi_instance, queue_task, shutdown_event
    logger.info("Starting cleanup...")
    
    # Signal the queue processor to stop
    if shutdown_event and not shutdown_event.is_set():
        shutdown_event.set()
        logger.debug("Shutdown event set, queue processor will exit")
    
    # Wait for the queue processing task to finish
    if queue_task:
        try:
            await queue_task
            logger.debug("Queue task completed successfully")
        except asyncio.CancelledError:
            logger.debug("Queue task was cancelled")
        except Exception as e:
            logger.error(f"Error waiting for queue task: {e}")
    
    # Drain any remaining items in the queue
    if state_queue:
        while not state_queue.empty():
            try:
                state_queue.get_nowait()
                state_queue.task_done()
            except asyncio.QueueEmpty:
                break
        logger.debug("Queue drained")
    
    # Disconnect from Casambi
    if casambi_instance:
        try:
            logger.info("Disconnecting from Casambi...")
            await casambi_instance.disconnect()
            logger.info("Casambi disconnected")
        except Exception as e:
            logger.error(f"Error disconnecting from Casambi: {e}")
    
    logger.info("Cleanup complete")

async def shutdown_handler():
    """Handle shutdown by setting the shutdown event."""
    global shutdown_event
    logger.info("Shutdown signal received")
    if shutdown_event:
        shutdown_event.set()

async def main():
    global queue_task, shutdown_event
    
    # Initialize the background task for processing the queue
    queue_task = asyncio.create_task(process_state_queue())
    
    # Initialize shutdown event for graceful shutdown
    shutdown_event = asyncio.Event()
    
    # Register signal handlers for graceful shutdown
    # Try Unix-style signal handlers first (add_signal_handler)
    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(shutdown_handler()))
        loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(shutdown_handler()))
        logger.debug("Using Unix-style signal handlers")
    except (AttributeError, NotImplementedError):
        # Fall back to standard signal module for Windows compatibility
        # Note: On Windows, SIGTERM is not supported, only SIGINT (Ctrl+C)
        def handle_signal(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown...")
            asyncio.create_task(shutdown_handler())
        
        signal.signal(signal.SIGINT, handle_signal)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, handle_signal)
        logger.debug("Using standard signal handlers")
    
    logger.info("Starting Casambi BT Demo Web App on http://0.0.0.0:5000")
    
    try:
        # Run the app and wait for shutdown signal concurrently
        app_task = asyncio.create_task(app.run_task(host='0.0.0.0', port=5000))
        
        # Wait for either the app to finish or shutdown signal
        done, pending = await asyncio.wait(
            [app_task, shutdown_event.wait()],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Cancel any remaining tasks
        for task in pending:
            task.cancel()
        
        # Wait for app task to finish cleanup
        if app_task in pending:
            try:
                await app_task
            except asyncio.CancelledError:
                pass
    except asyncio.CancelledError:
        logger.info("App run cancelled, cleaning up...")
    finally:
        await cleanup()

if __name__ == '__main__':
    import asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, exiting")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
