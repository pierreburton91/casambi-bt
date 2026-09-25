"""Tests for light color-mode selection logic (_logic.py)."""

from CasambiBt import ColorSource, UnitControl, UnitControlType, UnitType


def _unit_type(control_types: list[UnitControlType]) -> UnitType:
    controls = [
        UnitControl(
            type=t, offset=0, length=8, default=0, readonly=False, min=0, max=255
        )
        for t in control_types
    ]
    return UnitType(
        id=1,
        model="test",
        manufacturer="test",
        mode="test",
        stateLength=1,
        controls=controls,
    )


def test_dimmer_only_light_is_brightness_mode(logic):
    unit_type = _unit_type([UnitControlType.DIMMER])
    modes = logic.supported_light_color_modes(unit_type)
    assert modes == {"brightness"}


def test_onoff_only_light_falls_back_to_onoff_mode(logic):
    unit_type = _unit_type([UnitControlType.ONOFF])
    modes = logic.supported_light_color_modes(unit_type)
    assert modes == {"onoff"}


def test_multi_mode_light_advertises_all_color_controls(logic):
    unit_type = _unit_type(
        [
            UnitControlType.DIMMER,
            UnitControlType.TEMPERATURE,
            UnitControlType.RGB,
            UnitControlType.COLORSOURCE,
        ]
    )
    modes = logic.supported_light_color_modes(unit_type)
    assert modes == {"color_temp", "rgb"}


def test_active_mode_follows_colorsource(logic):
    modes = {"color_temp", "rgb"}
    assert logic.active_light_color_mode(modes, ColorSource.RGB) == "rgb"
    assert logic.active_light_color_mode(modes, ColorSource.TEMPERATURE) == "color_temp"


def test_active_mode_unknown_without_colorsource(logic):
    modes = {"color_temp", "rgb"}
    assert logic.active_light_color_mode(modes, None) is None


def test_single_mode_is_always_active(logic):
    assert logic.active_light_color_mode({"brightness"}, None) == "brightness"
