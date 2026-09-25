# Casambi Bluetooth for Home Assistant

A custom Home Assistant integration that controls a Casambi BLE network directly
over Bluetooth, using [`casambi-bt`](https://github.com/lkempf/casambi-bt) — no
Casambi cloud account or gateway required. It uses Home Assistant's own Bluetooth
stack for discovery and connection management, so it plays well with other
Bluetooth integrations and Bluetooth proxies.

## Installation

### HACS (custom repository)

Add this repository to HACS as a custom repository of type "Integration", pointed
at the `src/casambi-bt-ha` subfolder, then install "Casambi Bluetooth" and restart
Home Assistant.

### Manual

Copy `custom_components/casambi_bt` into your Home Assistant `config/custom_components/`
directory and restart Home Assistant.

## Setup

Home Assistant will automatically discover nearby Casambi networks over Bluetooth
and prompt you to add them. You can also add one manually via
**Settings → Devices & Services → Add Integration → Casambi Bluetooth**, which
lists any Casambi networks already seen by Home Assistant's Bluetooth stack.
You'll need the network's password (the same one used in the official Casambi
app).

## Supported entities

Entities are created per unit, based on the controls Casambi reports the unit
supports:

- **Light** — units with brightness, color temperature, RGB, or XY controls.
  Brightness, on/off, and whichever color mode is currently active are supported.
- **Cover** — motorized shades and screens. Position get/set is supported;
  stopping mid-motion is not (no known protocol opcode for it).
- **Sensor** — illuminance, and any named per-unit sensor readings (temperature,
  wind speed, travel distance, etc.), including sensors that live on a shade or
  screen unit alongside its cover entity.
- **Binary sensor** — occupancy/presence, where supported.

## Known limitations / non-goals

- **No cover stop.** Casambi's protocol has no documented "stop" opcode for
  motorized shades/screens, so `cover.stop_cover` is not implemented rather than
  guessed at.
- **No switch platform yet.** Some plain on/off relay-style fixtures (no
  dimmer/color controls) don't match any entity platform in this version. Tracing
  the underlying library shows its `setControl(ONOFF, ...)` dispatch sends the
  *dimmer* opcode for anything that isn't a shade/screen, not an offset-aware
  write to the actual on/off control — likely a gap in the library itself. This
  will be revisited once that's addressed upstream.
- **No RGBW.** Casambi's white channel is written via a separate opcode from RGB;
  combining both into Home Assistant's single `rgbw_color` write isn't implemented
  in this version.
- **No physical switch/button events, scenes, or groups.** `SwitchEvent`
  (physical button presses), Casambi scenes, and Casambi groups aren't mapped to
  any Home Assistant entity or event in this version.

## Logging

The underlying `CasambiBt` library logs raw decrypted BLE packets at `INFO`. If
that's too noisy, add this to your Home Assistant `configuration.yaml`:

```yaml
logger:
  logs:
    CasambiBt: warning
```
