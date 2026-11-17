# CasambiBt (embedded, modified)

This directory is a modified copy of the [`casambi-bt`](https://github.com/lkempf/casambi-bt)
Python library by Lukas Kempf (Copyright 2022, Apache License 2.0), starting from
version 0.3.2. It is embedded in the Home Assistant integration one level up and
is not published to PyPI: it is not guaranteed to stay compatible with the
upstream `casambi-bt` package. See [NOTICE](../../../NOTICE) for the list of
changes; each file changed from the original carries a "Modified by" header.

The library talks to Casambi networks over Bluetooth Low Energy. Its protocol
support comes from independent reverse engineering by the original author; it is
**alpha quality** and not affiliated with Casambi.

## Using it outside Home Assistant

For development, the repository installs it in editable mode as the top-level
package `CasambiBt` (`pipenv install --dev` at the repository root). The demo web
app (`demo/`) and `demo.py` use it that way.

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

If you have problems connecting to the network, check how the network is configured. The original author tested with a network using the **Evolution firmware**, configured as follows (screenshots are for the iOS app but the Android app should look very similar):

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

#### Reading Sensor Values

Decoded readings are available on `unit.state` after a state update:

```python
state = sensor_unit.state

state.presence     # int | None - raw occupancy/presence reading
state.lux          # int | None - ambient light level
state.sensorgroup  # int | None - raw group-protocol index (see below)
state.sensors      # dict[str, int] - named readings, e.g. {"Wind Snelheid": 1234}
```

Some sensor platforms (e.g. wind/rain/light/motion combo boards, or the auxiliary
temperature/travel-distance sensors on motorized shades) report multiple named readings
that share a single group of controls, but only send one fresh reading per state update,
round-robin. `state.sensors` reflects this: each key updates only when that particular
sensor's turn comes around, and keeps its last known value in between — a key being
"stale" for a few updates is expected, not a bug.

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
