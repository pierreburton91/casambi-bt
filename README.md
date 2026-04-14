![PyPI](https://img.shields.io/pypi/v/casambi-bt)
[![Discord](https://img.shields.io/discord/1186445089317326888)](https://discord.gg/jgZVugfx)

# A bluetooth based Python library for controlling Casambi networks

This library provides a currently **alpha quality** interface to Casambi-based lights over Bluetooth.
The author is not associated with Casambi and the implementation is based on his own analysis of the protocol.
This interface is not feature complete and was only tested with a very small network.

If you want to check out my (slow) progress in writing a integration for Home Assistant using this library you can take a look at [https://github.com/lkempf/casambi-bt-hass/](https://github.com/lkempf/casambi-bt-hass/).

For a more mature solution using a gateway and the official Casambi API have a look at [https://github.com/hellqvio86/aiocasambi](https://github.com/hellqvio86/aiocasambi).

## Getting started

This library is available on PyPi:

```
pip install casambi-bt
```

Have a look at `demo.py` for a small example.

### MacOS

MacOS [does not expose the Bluetooth MAC address via their official API](https://github.com/hbldh/bleak/issues/140),
if you're running this library on MacOS, it will use an undocumented IOBluetooth API to get the MAC Address.
Without the real MAC address the integration with Casambi will not work.
If you're running into problems fetching the MAC address on MacOS, try it on a Raspberry Pi.

### Casambi network setup

If you have problems connecting to the network please check that your network is configured appropriately before creating an issue. The network I test this with uses the **Evoultion firmware** and is configured as follows (screenshots are for the iOS app but the Android app should look very similar):

![Gateway settings](/doc/img/gateway.png)
![Network settings](/doc/img/network.png)
![Performance settings](/doc/img/perf.png)

## Supported Devices and Controls

The library supports not only lights but also motorized shades, screens, and sensor devices. The API automatically classifies devices based on their capabilities and makes them queryable via the `device_role` property.

### Device Types

Each device has a `device_role` property that indicates its semantic type:

- **LIGHT**: A light fixture with brightness and optional color controls (dimmers, RGB lights, temperature-tunable lights, etc.)
- **MOTORIZED_SHADE**: A motorized blind or shade controlled by slider position (louvers, roller shades, etc.)
- **MOTORIZED_SCREEN**: A motorized screen or projection device (without position feedback)
- **SENSOR**: A sensor providing read-only measurements (temperature, light level, humidity, motion, current draw, etc.)
- **UNKNOWN**: Device type cannot be determined

### Querying and Filtering Devices

You can filter units by device role to work with specific device types:

```python
from CasambiBt import DeviceRole

# Get all lights
lights = [u for u in casambi.units if u.unitType.device_role == DeviceRole.LIGHT]

# Get all motorized shades
shades = [u for u in casambi.units if u.unitType.device_role == DeviceRole.MOTORIZED_SHADE]

# Get all sensors
sensors = [u for u in casambi.units if u.unitType.device_role == DeviceRole.SENSOR]
```

### Control Interface

The primary method for controlling any device is `setControl()`, which provides a device-agnostic interface that works with any control type:

```python
from CasambiBt import UnitControlType

# Set dimmer brightness (lights)
await casambi.setControl(light_unit, UnitControlType.DIMMER, 128)

# Set shade position (motorized shades)
await casambi.setControl(shade_unit, UnitControlType.SLIDER, 100)

# Set light color (RGB lights)
await casambi.setControl(light_unit, UnitControlType.RGB, (255, 128, 64))

# Set light temperature (tunable whites)
await casambi.setControl(light_unit, UnitControlType.TEMPERATURE, 3000)

# Turn off (works with ONOFF or DIMMER controls)
await casambi.setControl(unit, UnitControlType.ONOFF, 0)

# Switching to scenes still uses the dedicated method
await casambi.switchToScene(scene)
```

### Legacy Device-Specific Methods

For backward compatibility, device-specific methods are still available:

- `setLevel(target, level)` — Set brightness (0-255)
- `setSlider(target, value)` — Set slider position (0-255), typically for motorized shades
- `setVertical(target, value)` — Set vertical coordinate (0-255)
- `setColor(target, rgb)` — Set RGB color as tuple (r, g, b) in range 0-255
- `setTemperature(target, temperature)` — Set color temperature in degrees Kelvin
- `setColorXY(target, xy)` — Set XY color as (x, y) tuple in range 0.0-1.0
- `setWhite(target, level)` — Set white channel (0-255)
- `turnOn(target)` — Turn unit on to last brightness level

These methods are maintained for convenience but `setControl()` is now the preferred interface.
