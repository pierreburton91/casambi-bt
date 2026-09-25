"""Tests for sensor/binary_sensor entity-creation gating logic (_logic.py).

Confirms the rule from CLAUDE.md: sensor/presence/lux controls must be detected
independent of a unit's DeviceRole, since real fixtures (louvers, screens) carry
both a cover-classifying control set AND tagged sensor controls.
"""

import json
import os

from CasambiBt import DeviceRole, UnitControl, UnitControlType, UnitType

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


def test_louver_is_a_cover_but_still_has_tagged_sensors(logic):
    unit_type = _load_unit_type("louvers.json")
    assert unit_type.device_role == DeviceRole.MOTORIZED_SHADE

    tagged = logic.has_tagged_sensor_controls(unit_type)
    assert {c.name for c in tagged} == {
        "Temperatuur",
        "#Overcurrent",
        "Travel Distance",
        "Module State",
    }


def test_screen_is_a_cover_but_still_has_tagged_sensors(logic):
    unit_type = _load_unit_type("screen.json")
    assert unit_type.device_role == DeviceRole.MOTORIZED_SCREEN

    tagged = logic.has_tagged_sensor_controls(unit_type)
    assert {c.name for c in tagged} == {"Time Up", "Time Down"}


def test_no_lux_or_presence_on_shade_fixtures(logic):
    for fixture in ("louvers.json", "screen.json"):
        unit_type = _load_unit_type(fixture)
        assert not logic.has_lux_control(unit_type)
        assert not logic.has_presence_control(unit_type)


def test_plain_sensor_controls_excludes_tagged_ones(logic):
    unit_type = _load_unit_type("louvers.json")
    assert logic.has_plain_sensor_controls(unit_type) == []


def test_sensor_platform_has_lux_and_presence(logic):
    unit_type = _load_unit_type("sensors-platform.json")
    assert unit_type.device_role == DeviceRole.SENSOR
    assert logic.has_lux_control(unit_type)
    assert logic.has_presence_control(unit_type)

    tagged = logic.has_tagged_sensor_controls(unit_type)
    assert {c.name for c in tagged} == {
        "Wind Snelheid",
        "Zon schijnt",
        "PIR status",
        "Regen status",
    }
