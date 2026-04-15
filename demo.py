import asyncio
import logging
import sys
from importlib.metadata import version

from CasambiBt import Casambi, discover
from CasambiBt._unit import DeviceRole, UnitControlType
from CasambiBt.errors import ReadOnlyControlError

formatter = logging.Formatter(
    fmt="%(asctime)s %(name)-8s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
stream = logging.StreamHandler()
stream.setFormatter(formatter)
logging.getLogger().addHandler(stream)
_LOGGER = logging.getLogger(__name__)


async def main() -> None:
    logLevel = logging.INFO
    if "-d" in sys.argv:
        logLevel = logging.DEBUG
        logging.getLogger("bleak").setLevel(logging.DEBUG)

    _LOGGER.setLevel(logLevel)
    logging.getLogger("CasambiBt").setLevel(logLevel)

    _LOGGER.debug(f"Bleak version: {version('bleak')}")
    _LOGGER.debug(f"Bleak retry connector version: {version('bleak-retry-connector')}")

    # Discover networks
    print("Searching...")
    devices = await discover()
    for i, d in enumerate(devices):
        print(f"[{i}]\t{d.address}")

    selection = int(input("Select network: "))

    device = devices[selection]
    pwd = input("Enter password: ")

    # Connect to the selected network
    casa = Casambi()
    try:
        await casa.connect(device, pwd)

        # Print device information and demonstrate device-agnostic control
        print(f"\nConnected to network with {len(casa.units)} units:")
        for u in casa.units:
            role = u.unitType.device_role.name
            print(f"  - {u.name} ({u.unitType.model}): {role}")

        # Demonstrate device-agnostic control patterns
        print("\nDemonstrating device-agnostic control...")

        # Control all motorized shades (louvers)
        motorized_shades = [u for u in casa.units if u.unitType.device_role == DeviceRole.MOTORIZED_SHADE]
        if motorized_shades:
            print(f"Setting {len(motorized_shades)} motorized shade(s) to 50% position...")
            for shade in motorized_shades:
                await casa.setControl(shade, UnitControlType.SLIDER, 71)  # 50% of 0-142 range
            await asyncio.sleep(2)

        # Control all motorized screens
        motorized_screens = [u for u in casa.units if u.unitType.device_role == DeviceRole.MOTORIZED_SCREEN]
        if motorized_screens:
            print(f"Setting {len(motorized_screens)} motorized screen(s) to 75% position...")
            for screen in motorized_screens:
                await casa.setControl(screen, UnitControlType.DIMMER, 191)  # 75% of 0-255 range
            await asyncio.sleep(2)

        # Control all lights
        lights = [u for u in casa.units if u.unitType.device_role == DeviceRole.LIGHT]
        if lights:
            print(f"Turning on {len(lights)} light(s)...")
            await casa.setControl(None, UnitControlType.ONOFF, 1)  # Turn all on
            await asyncio.sleep(2)

            print(f"Setting {len(lights)} light(s) to 50% brightness...")
            await casa.setControl(None, UnitControlType.DIMMER, 128)  # 50% brightness
            await asyncio.sleep(2)

        # Read sensor values
        sensors = [u for u in casa.units if u.unitType.device_role == DeviceRole.SENSOR]
        if sensors:
            print(f"\nReading {len(sensors)} sensor(s)...")
            for sensor in sensors:
                print(f"  {sensor.name}: {sensor.state}")

        # Demonstrate error handling for read-only sensors
        # print("\nDemonstrating read-only sensor protection...")
        # try:
        #     await casa.setControl(sensors[0] if sensors else None, UnitControlType.SENSOR, 25)
        # except ReadOnlyControlError as e:
        #    print(f"  ✓ Correctly prevented setting sensor value: {e}")

        await asyncio.sleep(2)

        # Turn everything off
        # print("\nTurning all devices off...")
        # await casa.setControl(None, UnitControlType.ONOFF, 0)

        # Print final state of all units
        print("\nFinal state of all units:")
        for u in casa.units:
            print(f"  {u.name}: {u.state}")

    finally:
        await casa.disconnect()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    loop.run_until_complete(main())
