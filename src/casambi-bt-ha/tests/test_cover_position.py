"""Tests for cover position/percent scaling logic (_logic.py), using real fixture specs."""

import json
import os

from CasambiBt import UnitControl, UnitControlType, UnitType

_FIXTURES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "doc", "fixtures-specs"
)


def _load_unit_type(filename: str) -> UnitType:
    with open(os.path.join(_FIXTURES_DIR, filename)) as f:
        spec = json.load(f)

    controls = []
    for control_json in spec["controls"]:
        try:
            control_type = UnitControlType[control_json["type"].upper()]
        except KeyError:
            control_type = UnitControlType.UNKOWN
        controls.append(
            UnitControl(
                type=control_type,
                offset=control_json["offset"],
                length=control_json["length"],
                default=control_json.get("default", 0),
                readonly=control_json.get("readonly", False),
                min=control_json.get("min"),
                max=control_json.get("max"),
                name=control_json.get("name", ""),
                unit=control_json.get("unit", ""),
                tag=control_json.get("tag"),
            )
        )
    return UnitType(
        id=spec["id"],
        model=spec["model"],
        manufacturer=spec["vendor"],
        mode=spec["mode"],
        stateLength=spec["stateLength"],
        controls=controls,
    )


def test_shade_position_uses_slider_native_range(logic):
    unit_type = _load_unit_type("louvers.json")
    position = logic.resolve_position_control(unit_type)
    assert position is not None
    assert position.field == "slider"
    assert (position.native_min, position.native_max) == (0, 142)


def test_screen_position_uses_fixed_dimmer_range(logic):
    unit_type = _load_unit_type("screen.json")
    position = logic.resolve_position_control(unit_type)
    assert position is not None
    assert position.field == "dimmer"
    assert (position.native_min, position.native_max) == (0, 255)


def test_shade_percent_round_trip(logic):
    unit_type = _load_unit_type("louvers.json")
    position = logic.resolve_position_control(unit_type)
    assert position is not None
    for percent in (0, 25, 50, 75, 100):
        native = logic.percent_to_native(
            percent, position.native_min, position.native_max
        )
        assert 0 <= native <= 142
        round_tripped = logic.native_to_percent(
            native, position.native_min, position.native_max
        )
        assert abs(round_tripped - percent) <= 1


def test_screen_percent_round_trip(logic):
    unit_type = _load_unit_type("screen.json")
    position = logic.resolve_position_control(unit_type)
    assert position is not None
    for percent in (0, 25, 50, 75, 100):
        native = logic.percent_to_native(
            percent, position.native_min, position.native_max
        )
        assert 0 <= native <= 255
        round_tripped = logic.native_to_percent(
            native, position.native_min, position.native_max
        )
        assert abs(round_tripped - percent) <= 1


def test_percent_clamped_to_range(logic):
    assert logic.native_to_percent(-10, 0, 100) == 0
    assert logic.native_to_percent(110, 0, 100) == 100
    assert logic.percent_to_native(150, 0, 255) == 255
    assert logic.percent_to_native(-50, 0, 255) == 0
