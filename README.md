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

For specific Bluetooth backends, install the appropriate optional dependency:

```bash
# For ESPHome Bluetooth Proxy
pip install casambi-bt[esphome]

# For Home Assistant integration (validates against HA, then connects to an ESPHome proxy)
pip install casambi-bt[homeassistant]

# For all optional dependencies
pip install casambi-bt[esphome,homeassistant]
```

Have a look at `demo.py` for a small example.

### Bluetooth Transports

CasambiBt supports multiple Bluetooth transport backends:

| Transport | Description | Required Package | Configuration |
|----------|-------------|-----------------|---------------|
| **bleak** | Local Bluetooth adapter (default) | `bleak` (included) | None |
| **esphome** | ESPHome Bluetooth Proxy device | `aioesphomeapi` | Host, port, noise_psk |
| **homeassistant** | Validates connectivity via Home Assistant, then talks directly to a given ESP32 (HA is not in the BLE data path) | `homeassistant-api` | HA host, port, token; ESP32 `esphome_host`, `esphome_port` |

The transport is auto-selected based on environment variables:
- Set `ESPHOME_IP` to use ESPHome transport directly

Or use the transport factory for explicit selection:

```python
from CasambiBt._transport_factory import get_transport_by_type

# Create a specific transport
transport = get_transport_by_type(
    'homeassistant',
    host='192.168.1.100',        # Home Assistant host
    token='your_long_lived_token',
    esphome_host='192.168.1.50', # the ESP32 running ESPHome (Bluetooth proxy)
    ssl=True
)

# Use with discover
from CasambiBt import discover
devices = await discover(transport=transport)
```

### Running the demo

`demo/web_app.py` (run with `python demo/web_app.py`) reads the same transport
configuration from environment variables - Pipenv auto-loads a `.env` file in
the project root for `pipenv run`/`pipenv shell`, or you can type these values
directly into the demo's transport selection UI:

- **esphome**: `ESPHOME_HOST`, `ESPHOME_PORT`, `ESPHOME_NOISE_PSK`
- **homeassistant**: `HOME_ASSISTANT_HOST`, `HOME_ASSISTANT_PORT`, `HOME_ASSISTANT_TOKEN`,
  `HOME_ASSISTANT_SSL`, `HOME_ASSISTANT_VERIFY_SSL`, plus `ESPHOME_HOST` (or
  `ESP_HOME_HOSTNAME`) and `ESPHOME_PORT` for the ESP32 itself

Some ESPHome Bluetooth Proxy devices only forward BLE advertisements to a single
native-API subscriber at a time. If Home Assistant already has an active
connection to the ESP32, a second direct connection (e.g. from this demo) may
see the connection succeed but receive zero advertisements. If discovery finds
nothing, try temporarily disabling the ESPHome integration for that device in
Home Assistant first.

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

This library supports not only lighting fixtures but also motorized shades, screens, and read-only sensors.
The public API is intentionally device-agnostic: commands are dispatched by control type while semantics are exposed through the `device_role` property.

### Device Roles

Each device type is classified by a semantic `device_role` on its `UnitType`:

- **LIGHT**: Standard lighting fixtures with dimmer and color controls.
- **MOTORIZED_SHADE**: Louvers or blinds controlled by a slider position.
- **MOTORIZED_SCREEN**: Screens or projection devices controlled by on/off state or position commands.
- **SENSOR**: Read-only sensors that expose measured values such as temperature, illuminance, humidity, motion, or current.
- **UNKNOWN**: When the role cannot be inferred from available controls.

The role is derived from the device's reported control set and helps consumers distinguish lights from motors and sensors.

### Querying and Filtering by Role

Use `device_role` to discover units by semantic type:

```python
from CasambiBt import DeviceRole

lights = [u for u in casambi.units if u.unitType.device_role == DeviceRole.LIGHT]
shades = [u for u in casambi.units if u.unitType.device_role == DeviceRole.MOTORIZED_SHADE]
screens = [u for u in casambi.units if u.unitType.device_role == DeviceRole.MOTORIZED_SCREEN]
sensors = [u for u in casambi.units if u.unitType.device_role == DeviceRole.SENSOR]
```

### Controlling Devices with `setControl()`

The preferred API is `setControl()`, which routes commands by control type and avoids light-specific naming:

```python
from CasambiBt import UnitControlType

# Light brightness
await casambi.setControl(light_unit, UnitControlType.DIMMER, 128)

# Shade position
await casambi.setControl(shade_unit, UnitControlType.SLIDER, 100)

# Screen up/down via on/off semantics
await casambi.setControl(screen_unit, UnitControlType.ONOFF, 1)

# RGB color on a tunable light
await casambi.setControl(light_unit, UnitControlType.RGB, (255, 128, 64))

# White temperature on a tunable light
await casambi.setControl(light_unit, UnitControlType.TEMPERATURE, 3000)

# Scene activation still uses a dedicated API
await casambi.switchToScene(scene)
```

`setControl()` raises `ReadOnlyControlError` for sensors and any controls that are not writable on the target unit.

### Sensor Devices and Read-Only Controls

Sensor units are modeled as read-only devices. Attempting to write a `UnitControlType.SENSOR` value or any read-only control on a target will raise `ReadOnlyControlError`.

```python
from CasambiBt import ReadOnlyControlError, UnitControlType

try:
    await casambi.setControl(sensor_unit, UnitControlType.SENSOR, 0)
except ReadOnlyControlError:
    print("Sensor units are read-only and cannot be controlled.")
```

### Legacy Device-Specific Methods

Legacy device-specific methods are still available for compatibility, but `setControl()` is the recommended interface.

- `setLevel(target, level)` — Set brightness (0-255)
- `setSlider(target, value)` — Set slider position (0-255)
- `setVertical(target, value)` — Set vertical coordinate (0-255)
- `setColor(target, rgb)` — Set RGB color as tuple (r, g, b) in range 0-255
- `setTemperature(target, temperature)` — Set color temperature in degrees Kelvin
- `setColorXY(target, xy)` — Set XY color as (x, y) tuple in range 0.0-1.0
- `setWhite(target, level)` — Set white channel (0-255)
- `turnOn(target)` — Turn unit on to last brightness level

Use these only when porting older code; new integrations should use `setControl()` and `device_role` inspection.
