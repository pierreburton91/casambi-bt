"""Framework-agnostic helpers mapping CasambiBt units/controls onto HA entities.

Deliberately free of any `homeassistant` import so it can be unit-tested without
installing Home Assistant as a dependency (see src/casambi-bt-ha/tests/). Platform
modules (light.py, cover.py, sensor.py, binary_sensor.py) import from here rather
than duplicating this logic inline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from CasambiBt import ColorSource, DeviceRole, UnitControl, UnitControlType, UnitType


@dataclass(frozen=True)
class PositionControl:
    """The control backing a shade/screen's open/close position, and its native range."""

    control: UnitControl
    field: str  # "slider" or "dimmer"
    native_min: int
    native_max: int


def resolve_position_control(unit_type: UnitType) -> PositionControl | None:
    """Find the SLIDER/DIMMER control backing a shade/screen's position.

    Mirrors demo/web_app.py's get_position_control(): MOTORIZED_SHADE units use
    their SLIDER control's own min/max (e.g. louver blade-angle degrees);
    MOTORIZED_SCREEN units use their DIMMER control with a fixed 0-255 range,
    since DIMMER decoding never consults min/max.
    """
    role = unit_type.device_role
    if role == DeviceRole.MOTORIZED_SHADE:
        control = unit_type.get_control(UnitControlType.SLIDER)
        if control is not None and control.min is not None and control.max is not None:
            return PositionControl(control, "slider", control.min, control.max)
    elif role == DeviceRole.MOTORIZED_SCREEN:
        control = unit_type.get_control(UnitControlType.DIMMER)
        if control is not None:
            return PositionControl(control, "dimmer", 0, 255)
    return None


def native_to_percent(raw: int, native_min: int, native_max: int) -> int:
    """Convert a raw control value to a 0-100 position percentage, clamped."""
    if native_max == native_min:
        return 0
    pct = round((raw - native_min) / (native_max - native_min) * 100)
    return max(0, min(100, pct))


def percent_to_native(percent: int, native_min: int, native_max: int) -> int:
    """Inverse of native_to_percent(), clamped to the control's native range."""
    native = round(percent / 100 * (native_max - native_min) + native_min)
    return max(native_min, min(native_max, native))


_COLOR_CONTROL_ORDER: Final = (
    (UnitControlType.TEMPERATURE, "color_temp"),
    (UnitControlType.RGB, "rgb"),
    (UnitControlType.XY, "xy"),
)


def supported_light_color_modes(unit_type: UnitType) -> set[str]:
    """HA-style color mode keys ("color_temp"/"rgb"/"xy"/"brightness"/"onoff")
    a light entity should advertise, derived from the unit's controls."""
    control_types = {c.type for c in unit_type.controls}
    modes = {
        key
        for control_type, key in _COLOR_CONTROL_ORDER
        if control_type in control_types
    }
    if not modes and UnitControlType.DIMMER in control_types:
        modes.add("brightness")
    if not modes:
        modes.add("onoff")
    return modes


_COLORSOURCE_TO_MODE: Final = {
    ColorSource.TEMPERATURE: "color_temp",
    ColorSource.RGB: "rgb",
    ColorSource.XY: "xy",
}


def active_light_color_mode(
    supported_modes: set[str], colorsource: ColorSource | None
) -> str | None:
    """Pick the currently-active color mode key out of `supported_modes`.

    Only meaningful when a unit supports more than one color mode: with a single
    mode there's nothing to disambiguate. With several, `UnitState.rgb`/`.xy`/
    `.temperature` are all decoded from the same shared state blob on every
    update regardless of which is "active" - only `colorsource` says which one
    the fixture is actually driving right now.
    """
    if len(supported_modes) <= 1:
        return next(iter(supported_modes), None)
    if colorsource is None:
        return None
    return _COLORSOURCE_TO_MODE.get(colorsource)


def has_tagged_sensor_controls(unit_type: UnitType) -> list[UnitControl]:
    """Zero-length, tagged SENSOR controls backing the round-robin sensor group.

    Scanned independent of device_role: a MOTORIZED_SHADE/SCREEN unit can carry
    these alongside its SLIDER/DIMMER+ONOFF controls (see louvers.json/screen.json).
    """
    return [
        c
        for c in unit_type.controls
        if c.type == UnitControlType.SENSOR and c.tag is not None
    ]


def has_plain_sensor_controls(unit_type: UnitType) -> list[UnitControl]:
    """Ungrouped SENSOR controls decoded onto UnitState.sensor directly."""
    return [
        c
        for c in unit_type.controls
        if c.type == UnitControlType.SENSOR and c.tag is None and c.length > 0
    ]


def has_lux_control(unit_type: UnitType) -> bool:
    return unit_type.get_control(UnitControlType.LUX) is not None


def has_presence_control(unit_type: UnitType) -> bool:
    return unit_type.get_control(UnitControlType.PRESENCE) is not None
