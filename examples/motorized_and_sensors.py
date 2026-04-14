"""Example demonstrating control of motorized devices and sensors.

This script shows how to:
1. Discover and connect to a Casambi network
2. Filter and identify different device types (lights, shades, screens, sensors)
3. Use the new device-agnostic setControl() API to control various devices
4. Handle read-only sensor values

Usage:
    python examples/motorized_and_sensors.py [-d]

    -d : Enable debug logging
"""

import asyncio
import logging
import sys
from importlib.metadata import version

from CasambiBt import Casambi, DeviceRole, UnitControlType, discover
from CasambiBt.errors import ReadOnlyControlError

formatter = logging.Formatter(
    fmt="%(asctime)s %(name)-8s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
stream = logging.StreamHandler()
stream.setFormatter(formatter)
logging.getLogger().addHandler(stream)
_LOGGER = logging.getLogger(__name__)


async def print_device_inventory(casa: Casambi) -> None:
    """Print an inventory of all devices organized by type."""
    print("\n=== NETWORK INVENTORY ===")
    print(f"Network: {casa.networkName}")
    print(f"Total units: {len(casa.units)}\n")

    # Organize by device role
    lights = [u for u in casa.units if u.unitType.device_role == DeviceRole.LIGHT]
    shades = [u for u in casa.units if u.unitType.device_role == DeviceRole.MOTORIZED_SHADE]
    screens = [u for u in casa.units if u.unitType.device_role == DeviceRole.MOTORIZED_SCREEN]
    sensors = [u for u in casa.units if u.unitType.device_role == DeviceRole.SENSOR]
    unknown = [u for u in casa.units if u.unitType.device_role == DeviceRole.UNKNOWN]

    if lights:
        print("💡 LIGHTS:")
        for u in lights:
            print(
                f"  - {u.name} (ID: {u.deviceId}): "
                f"Brightness={u.state.dimmer}, Online={u.online}"
            )

    if shades:
        print("\n🪟 MOTORIZED SHADES:")
        for u in shades:
            print(
                f"  - {u.name} (ID: {u.deviceId}): "
                f"Position={u.state.slider}, Online={u.online}"
            )

    if screens:
        print("\n📺 MOTORIZED SCREENS:")
        for u in screens:
            print(f"  - {u.name} (ID: {u.deviceId}): Online={u.online}")

    if sensors:
        print("\n📊 SENSORS (Read-only):")
        for u in sensors:
            controls_available = [c.type.name for c in u.unitType.controls]
            print(f"  - {u.name} (ID: {u.deviceId}): {', '.join(controls_available)}")

    if unknown:
        print("\n❓ UNKNOWN DEVICES:")
        for u in unknown:
            controls_available = [c.type.name for c in u.unitType.controls]
            print(f"  - {u.name} (ID: {u.deviceId}): {', '.join(controls_available)}")


async def demonstrate_light_control(casa: Casambi) -> None:
    """Demonstrate controlling lights using setControl()."""
    lights = [u for u in casa.units if u.unitType.device_role == DeviceRole.LIGHT]
    if not lights:
        print("\n✓ No lights found in network")
        return

    print("\n=== LIGHT CONTROL DEMO ===")
    light = lights[0]
    print(f"Controlling light: {light.name}")

    # Set brightness
    print("Setting brightness to 50%...")
    await casa.setControl(light, UnitControlType.DIMMER, 127)
    await asyncio.sleep(1)

    # Set to full brightness
    print("Setting brightness to 100%...")
    await casa.setControl(light, UnitControlType.DIMMER, 255)
    await asyncio.sleep(1)

    # Check if light supports color control
    if light.unitType.get_control(UnitControlType.RGB):
        print("Light supports RGB color control!")
        print("Setting color to warm red...")
        await casa.setControl(light, UnitControlType.RGB, (255, 100, 50))
        await asyncio.sleep(1)

        print("Setting color to cool blue...")
        await casa.setControl(light, UnitControlType.RGB, (50, 100, 255))
        await asyncio.sleep(1)

    # Check if light supports temperature control
    if light.unitType.get_control(UnitControlType.TEMPERATURE):
        print("Light supports tunable white control!")
        print("Setting to warm (3000K)...")
        await casa.setControl(light, UnitControlType.TEMPERATURE, 3000)
        await asyncio.sleep(1)

        print("Setting to cool-white (5000K)...")
        await casa.setControl(light, UnitControlType.TEMPERATURE, 5000)
        await asyncio.sleep(1)

    # Turn off
    print("Turning off...")
    await casa.setControl(light, UnitControlType.ONOFF, 0)
    await asyncio.sleep(1)


async def demonstrate_shade_control(casa: Casambi) -> None:
    """Demonstrate controlling motorized shades using setControl()."""
    shades = [u for u in casa.units if u.unitType.device_role == DeviceRole.MOTORIZED_SHADE]
    if not shades:
        print("\n✓ No motorized shades found in network")
        return

    print("\n=== MOTORIZED SHADE CONTROL DEMO ===")
    shade = shades[0]
    print(f"Controlling shade: {shade.name}")

    # Open shade (max position)
    print("Opening shade (100%)...")
    await casa.setControl(shade, UnitControlType.SLIDER, 255)
    await asyncio.sleep(2)

    # Half open
    print("Setting to 50% position...")
    await casa.setControl(shade, UnitControlType.SLIDER, 127)
    await asyncio.sleep(2)

    # Close shade
    print("Closing shade (0%)...")
    await casa.setControl(shade, UnitControlType.SLIDER, 0)
    await asyncio.sleep(2)


async def demonstrate_sensor_reading(casa: Casambi) -> None:
    """Demonstrate reading sensor values and proper error handling."""
    sensors = [u for u in casa.units if u.unitType.device_role == DeviceRole.SENSOR]
    if not sensors:
        print("\n✓ No sensors found in network")
        return

    print("\n=== SENSOR READING DEMO ===")
    sensor = sensors[0]
    print(f"Reading from sensor: {sensor.name}")

    # Print available sensor measurements
    print("Available sensor measurements:")
    for control in sensor.unitType.controls:
        if control.type == UnitControlType.SENSOR:
            print(f"  - Sensor measurement available")

    # Try to set a sensor value (should fail gracefully)
    print("\nAttempting to set sensor value (should fail)...")
    try:
        await casa.setControl(sensor, UnitControlType.SENSOR, 42)
        print("  ERROR: Sensor was writable! This should not happen.")
    except ReadOnlyControlError as e:
        print(f"  ✓ Correctly rejected: {e}")

    # Display current sensor state if available
    if sensor.state.slider is not None:
        print(f"Current sensor reading: {sensor.state.slider}")
    else:
        print("No current sensor reading available")


async def main() -> None:
    """Main entry point for the example."""
    logLevel = logging.INFO
    if "-d" in sys.argv:
        logLevel = logging.DEBUG
        logging.getLogger("bleak").setLevel(logging.DEBUG)

    _LOGGER.setLevel(logLevel)
    logging.getLogger("CasambiBt").setLevel(logLevel)

    _LOGGER.debug(f"Bleak version: {version('bleak')}")
    _LOGGER.debug(f"Bleak retry connector version: {version('bleak-retry-connector')}")

    # Discover networks
    print("Searching for Casambi networks...")
    devices = await discover()
    if not devices:
        print("No Casambi networks found!")
        return

    for i, d in enumerate(devices):
        print(f"[{i}]\t{d.address}")

    selection = int(input("\nSelect network: "))
    device = devices[selection]
    pwd = input("Enter password: ")

    # Connect to the selected network
    casa = Casambi()
    try:
        print("\nConnecting to network...")
        await casa.connect(device, pwd)

        # Print device inventory
        await print_device_inventory(casa)

        # Run demonstrations
        await demonstrate_light_control(casa)
        await demonstrate_shade_control(casa)
        await demonstrate_sensor_reading(casa)

        print("\n✓ Example completed successfully!")

    except asyncio.CancelledError:
        print("\n✓ Interrupted by user")
    except Exception as e:
        _LOGGER.error(f"Error: {e}", exc_info=True)
    finally:
        await casa.disconnect()
        print("Disconnected from network")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\n✓ Interrupted by user")
    finally:
        loop.close()
