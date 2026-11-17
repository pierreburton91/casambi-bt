# Casambi Bluetooth for Home Assistant

A custom Home Assistant integration that controls a Casambi network directly over
Bluetooth Low Energy (BLE), without a Casambi gateway. It was built to drive a
motorized pergola (adjustable louvers, screen, lights, and wind, rain, sun,
illuminance and presence sensors), but it is not tied to that hardware: any Casambi
network whose units it recognizes can be used.

The integration uses Home Assistant's own Bluetooth stack for discovery and
connections, so it works with a local adapter as well as with
[ESPHome Bluetooth proxies](https://esphome.io/components/bluetooth_proxy.html),
which are the practical way to reach units that are out of range of the Home
Assistant host. It reconnects on its own when the BLE link drops.

It embeds a modified copy of the [`casambi-bt`](https://github.com/lkempf/casambi-bt)
Python library by Lukas Kempf (see [Credits and license](#credits-and-license)).

> **Status:** alpha. The Casambi protocol support comes from independent reverse
> engineering; this project is not affiliated with Casambi or with any pergola
> manufacturer.

## Requirements

- Home Assistant 2024.6 or later, with the Bluetooth integration set up (a local
  adapter or at least one ESPHome Bluetooth proxy in range of a Casambi unit).
- The Casambi network's password, the same one used in the official Casambi app.
- Internet access during setup: the network's configuration and keys are fetched
  from the Casambi cloud with that password, then cached locally. Control itself
  goes over Bluetooth.

## Installation

### HACS (custom repository)

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/pierreburton91/casambi-bt` with the type **Integration**.
3. Install **Casambi Bluetooth**.
4. Restart Home Assistant completely.

HACS follows the `main` branch. After installing an update, restart Home Assistant
completely: reloading the integration does not load new Python code.

### Manual

Copy `custom_components/casambi_bt` into your Home Assistant
`config/custom_components/` directory and restart Home Assistant.

## Setup

Home Assistant discovers nearby Casambi networks over Bluetooth and offers to add
them. You can also add one from **Settings → Devices & Services → Add Integration →
Casambi Bluetooth**, which lists the Casambi units already seen by Home
Assistant's Bluetooth stack. Pick the unit with the best signal, then enter the
network's password.

If the password changes, Home Assistant asks for the new one (reauthentication).
If setup fails because of a temporary Bluetooth or cloud error, Home Assistant
retries automatically.

## Supported entities

Entities are created per unit, based on the controls Casambi reports the unit
supports:

- **Light**: units with brightness, color temperature, RGB, or XY controls.
  Brightness, on/off, and whichever color mode is currently active are supported.
- **Cover**: motorized shades (such as pergola louvers) and screens. Position
  get/set is supported; stopping mid-motion is not (no known protocol opcode for
  it).
- **Sensor**: illuminance, and any named per-unit sensor readings (temperature,
  wind speed, travel distance, etc.), including sensors that live on a shade or
  screen unit alongside its cover entity.
- **Binary sensor**: occupancy/presence, where supported.

## Known limitations

- **No cover stop.** Casambi's protocol has no documented "stop" opcode for
  motorized shades/screens, so `cover.stop_cover` is not implemented rather than
  guessed at.
- **No switch platform yet.** Plain on/off relay-style fixtures (no dimmer or
  color controls) don't match any entity platform yet. The bundled library's
  `setControl(ONOFF, ...)` sends the dimmer opcode for anything that isn't a
  shade or screen, instead of writing the actual on/off control.
- **No RGBW.** Casambi's white channel is written with a separate opcode from RGB;
  combining both into Home Assistant's single `rgbw_color` write isn't implemented.
- **No physical switch/button events, scenes, or groups.** Button presses, Casambi
  scenes and Casambi groups aren't mapped to Home Assistant entities or events.
- **One unit per config entry.** The entry connects through the unit chosen at
  setup. If that unit becomes unreachable, the entry has to be removed and added
  again through another unit.

## Logging

Per-packet traces of the bundled library are logged at `DEBUG`. To investigate a
connection problem, enable them in `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.casambi_bt: debug
```

If the integration cannot connect at all, also check the Casambi network's own
settings (gateway and performance options), shown in the
[library README](custom_components/casambi_bt/CasambiBt/README.md#casambi-network-setup).

## Repository layout

- `custom_components/casambi_bt/`: the Home Assistant integration, the only part
  HACS installs.
- `custom_components/casambi_bt/CasambiBt/`: the modified `casambi-bt` library it
  embeds. It is also importable on its own as `CasambiBt` for development.
- `demo/` and `demo.py`: a local web app and a minimal script that drive the
  library directly, without Home Assistant. Useful to diagnose a network from a
  computer.
- `tests/`: library tests, and integration tests (`tests/casambi_bt_ha/`) that run
  without Home Assistant installed.
- `doc/`: device fixtures (control layouts of real units) used by the tests.

### Development

Dependencies are managed with Pipenv:

```bash
pipenv install --dev
pipenv run isort --check-only --diff . && pipenv run black --check --diff . \
  && pipenv run ruff check . && pipenv run mypy . && pipenv run pytest -W error
```

## Credits and license

This project is licensed under the [Apache License 2.0](LICENSE).

It is built on [`casambi-bt`](https://github.com/lkempf/casambi-bt) by Lukas Kempf
(Copyright 2022, Apache License 2.0), whose reverse engineering of the Casambi BLE
protocol makes it possible. This repository started as a fork of version 0.3.2.
The library was then modified and embedded into the integration; the
[NOTICE](NOTICE) file lists what changed, and each modified file carries a
"Modified by" header.
