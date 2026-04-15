#!/usr/bin/env python3
"""Parameterized tests for round-trip encoding/decoding of control types using fixture specs."""

import json
import os
from CasambiBt._unit import Unit, UnitType, UnitControl, UnitControlType, UnitState


def load_fixture_spec(filename: str) -> dict:
    """Load a fixture spec from the doc/fixtures-specs directory."""
    fixture_path = os.path.join(
        os.path.dirname(__file__), "..", "doc", "fixtures-specs", filename
    )
    with open(fixture_path, "r") as f:
        return json.load(f)


def create_unit_type_from_spec(spec: dict) -> UnitType:
    """Create a UnitType object from a fixture spec JSON."""
    controls = []
    for control_json in spec["controls"]:
        type_str = control_json["type"].upper()
        try:
            control_type = UnitControlType[type_str]
        except KeyError:
            # Skip unknown control types for testing
            continue

        control = UnitControl(
            type=control_type,
            offset=control_json["offset"],
            length=control_json["length"],
            default=control_json.get("default", 0),
            readonly=control_json.get("readonly", False),
            min=control_json.get("min"),
            max=control_json.get("max"),
            name=control_json.get("name", ""),
            unit=control_json.get("unit", ""),
        )
        controls.append(control)

    return UnitType(
        id=spec["id"],
        model=spec["model"],
        manufacturer=spec["vendor"],
        mode=spec["mode"],
        stateLength=spec["stateLength"],
        controls=controls,
    )


def round_trip_encoding(unit_type: UnitType, control_type: UnitControlType, test_values: list[int]):
    """Test round-trip encoding/decoding for a specific control type."""
    control = unit_type.get_control(control_type)
    if control is None:
        print(f"⚠️  Skipping {control_type.name} - not supported by {unit_type.model}")
        return

    if control.length == 0:
        print(f"⚠️  Skipping {control_type.name} - zero-length control cannot round-trip")
        return

    if control.readonly and control_type != UnitControlType.SENSOR:
        print(f"⚠️  Skipping {control_type.name} - readonly control")
        return

    # Create a test unit
    unit = Unit(
        _typeId=unit_type.id,
        deviceId=1,
        uuid="test-unit",
        address="00:11:22:33:44:55",
        name=f"Test {unit_type.model}",
        firmwareVersion="1.0",
        unitType=unit_type,
    )

    print(f"\n🧪 Testing {control_type.name} on {unit_type.model} (min={control.min}, max={control.max})")

    for value in test_values:
        # Clamp value to control range if specified
        if control.min is not None and control.max is not None:
            clamped_value = min(control.max, max(control.min, value))
        else:
            clamped_value = value

        # Set the state
        state = UnitState()
        if control_type == UnitControlType.DIMMER:
            state.dimmer = clamped_value
        elif control_type == UnitControlType.SLIDER:
            state.slider = clamped_value
        elif control_type == UnitControlType.SENSOR:
            state.sensor = clamped_value
        elif control_type == UnitControlType.TEMPERATURE:
            state.temperature = clamped_value
        else:
            print(f"⚠️  Skipping {control_type.name} - test not implemented")
            continue

        # Encode to bytes
        encoded = unit.getStateAsBytes(state)

        # Decode back from bytes
        unit.setStateFromBytes(encoded)

        # Check the decoded value
        decoded_value = None
        if control_type == UnitControlType.DIMMER:
            decoded_value = unit.state.dimmer
        elif control_type == UnitControlType.SLIDER:
            decoded_value = unit.state.slider
        elif control_type == UnitControlType.SENSOR:
            decoded_value = unit.state.sensor
        elif control_type == UnitControlType.TEMPERATURE:
            decoded_value = unit.state.temperature

        # Allow small tolerance due to integer division in min/max scaling
        tolerance = 1 if (control.min is not None and control.max is not None) else 0
        if abs(decoded_value - clamped_value) <= tolerance:
            print(f"  ✓ {clamped_value} → encode → decode → {decoded_value}")
        else:
            raise AssertionError(
                f"Round-trip failed for {control_type.name}: {clamped_value} → {decoded_value} "
                f"(tolerance: {tolerance})"
            )


def test_louver_slider():
    """Test SLIDER control on louver fixture."""
    spec = load_fixture_spec("louvers.json")
    unit_type = create_unit_type_from_spec(spec)

    # Test values covering the range [0, 142]
    test_values = [0, 1, 71, 141, 142]
    round_trip_encoding(unit_type, UnitControlType.SLIDER, test_values)


def test_screen_dimmer():
    """Test DIMMER control on screen fixture."""
    spec = load_fixture_spec("screen.json")
    unit_type = create_unit_type_from_spec(spec)

    # Test values for dimmer (0-255 range, but screen may use subset)
    test_values = [0, 1, 128, 254, 255]
    round_trip_encoding(unit_type, UnitControlType.DIMMER, test_values)


def test_sensor_values():
    """Test SENSOR control on sensor platform fixture."""
    spec = load_fixture_spec("sensors-platform.json")
    unit_type = create_unit_type_from_spec(spec)

    # Test various sensor values
    test_values = [0, 1, 100, 1000, 10000]
    round_trip_encoding(unit_type, UnitControlType.SENSOR, test_values)


def test_temperature_control():
    """Test TEMPERATURE control if present in any fixture."""
    fixtures = ["louvers.json", "screen.json", "sensors-platform.json"]

    for fixture_file in fixtures:
        spec = load_fixture_spec(fixture_file)
        unit_type = create_unit_type_from_spec(spec)

        control = unit_type.get_control(UnitControlType.TEMPERATURE)
        if control:
            # Test temperature values in Kelvin
            test_values = [2700, 3000, 4000, 6500]
            round_trip_encoding(unit_type, UnitControlType.TEMPERATURE, test_values)
            break
    else:
        print("⚠️  No TEMPERATURE control found in fixtures")


if __name__ == "__main__":
    print("🧪 Running parameterized round-trip encoding/decoding tests...")

    try:
        test_louver_slider()
        test_screen_dimmer()
        test_sensor_values()
        test_temperature_control()

        print("\n✅ All round-trip encoding/decoding tests passed!")

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        raise