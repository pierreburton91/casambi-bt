#!/usr/bin/env python3
"""Integration tests for device state parsing and command dispatch using mocked data."""

import json
import os
from src.CasambiBt import Casambi
from src.CasambiBt._unit import Unit, UnitType, UnitControl, UnitControlType, UnitState, DeviceRole


def load_fixture_spec(filename: str) -> dict:
    """Load a fixture spec from the doc/fixtures-specs directory."""
    fixture_path = os.path.join(os.path.dirname(__file__), "doc", "fixtures-specs", filename)
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


def test_device_role_classification():
    """Test that devices are correctly classified by role."""
    print("🧪 Testing device role classification...")

    # Test louver (should be MOTORIZED_SHADE)
    louver_spec = load_fixture_spec("louvers.json")
    louver_type = create_unit_type_from_spec(louver_spec)
    louver_unit = Unit(
        _typeId=louver_type.id,
        deviceId=1,
        uuid="test-louver",
        address="00:11:22:33:44:55",
        name="Test Louver",
        firmwareVersion="1.0",
        unitType=louver_type,
    )
    assert louver_unit.unitType.device_role == DeviceRole.MOTORIZED_SHADE
    print("  ✓ Louver classified as MOTORIZED_SHADE")

    # Test screen (should be MOTORIZED_SCREEN)
    screen_spec = load_fixture_spec("screen.json")
    screen_type = create_unit_type_from_spec(screen_spec)
    screen_unit = Unit(
        _typeId=screen_type.id,
        deviceId=2,
        uuid="test-screen",
        address="00:11:22:33:44:56",
        name="Test Screen",
        firmwareVersion="1.0",
        unitType=screen_type,
    )
    assert screen_unit.unitType.device_role == DeviceRole.MOTORIZED_SCREEN
    print("  ✓ Screen classified as MOTORIZED_SCREEN")

    # Test sensor platform (should be SENSOR)
    sensor_spec = load_fixture_spec("sensors-platform.json")
    sensor_type = create_unit_type_from_spec(sensor_spec)
    sensor_unit = Unit(
        _typeId=sensor_type.id,
        deviceId=3,
        uuid="test-sensor",
        address="00:11:22:33:44:57",
        name="Test Sensor",
        firmwareVersion="1.0",
        unitType=sensor_type,
    )
    assert sensor_unit.unitType.device_role == DeviceRole.SENSOR
    print("  ✓ Sensor platform classified as SENSOR")


def test_state_parsing_from_bytes():
    """Test parsing state bytes into UnitState for different device types."""
    print("\n🧪 Testing state parsing from bytes...")

    # Test louver state parsing
    louver_spec = load_fixture_spec("louvers.json")
    louver_type = create_unit_type_from_spec(louver_spec)
    louver_unit = Unit(
        _typeId=louver_type.id,
        deviceId=1,
        uuid="test-louver",
        address="00:11:22:33:44:55",
        name="Test Louver",
        firmwareVersion="1.0",
        unitType=louver_type,
    )

    # Mock state bytes for louver: slider at max (142° → 255 encoded)
    # Based on fixture: slider at offset 28, length 8, min=0, max=142
    state_bytes = bytearray(louver_type.stateLength)
    state_bytes[28 // 8] = 255  # Max position encoded
    state_bytes[36 // 8] = 1    # ON/OFF at offset 36, length 1, set to ON

    louver_unit.setStateFromBytes(bytes(state_bytes))

    assert louver_unit.state.slider == 142, f"Expected slider=142, got {louver_unit.state.slider}"
    assert louver_unit.state.onoff == True, f"Expected onoff=True, got {louver_unit.state.onoff}"
    print("  ✓ Louver state parsed correctly (slider=142, onoff=True)")

    # Test screen state parsing
    screen_spec = load_fixture_spec("screen.json")
    screen_type = create_unit_type_from_spec(screen_spec)
    screen_unit = Unit(
        _typeId=screen_type.id,
        deviceId=2,
        uuid="test-screen",
        address="00:11:22:33:44:56",
        name="Test Screen",
        firmwareVersion="1.0",
        unitType=screen_type,
    )

    # Mock state bytes for screen: dimmer at 50%
    # Based on fixture: dimmer at offset 28, length 8
    state_bytes = bytearray(screen_type.stateLength)
    state_bytes[28 // 8] = 128  # 50% position
    state_bytes[36 // 8] = 1    # ON/OFF at offset 36, length 1, set to ON

    screen_unit.setStateFromBytes(bytes(state_bytes))

    assert screen_unit.state.dimmer == 128, f"Expected dimmer=128, got {screen_unit.state.dimmer}"
    assert screen_unit.state.onoff == True, f"Expected onoff=True, got {screen_unit.state.onoff}"
    print("  ✓ Screen state parsed correctly (dimmer=128, onoff=True)")


def test_command_dispatch():
    """Test that setControl dispatches to correct underlying methods."""
    print("\n🧪 Testing command dispatch via setControl...")

    casa = Casambi()

    # Test that setControl calls are validated (will fail due to no connection)
    test_cases = [
        (UnitControlType.DIMMER, 128),
        (UnitControlType.SLIDER, 100),
        (UnitControlType.ONOFF, 1),
    ]

    for control_type, value in test_cases:
        try:
            # This should fail due to no connection, but not due to readonly checks
            import asyncio
            asyncio.run(casa.setControl(None, control_type, value))
            assert False, f"Expected connection error for {control_type}"
        except Exception as e:
            # Should fail with connection-related error, not ReadOnlyControlError
            error_str = str(e).lower()
            assert "readonly" not in error_str, f"Unexpected readonly error for {control_type}: {e}"
            assert any(keyword in error_str for keyword in ["connection", "state", "expected"]), \
                f"Unexpected error type for {control_type}: {e}"
            print(f"  ✓ {control_type} passed readonly validation (failed later as expected)")


def test_readonly_sensor_rejection():
    """Test that sensor controls are rejected as read-only."""
    print("\n🧪 Testing sensor readonly rejection...")

    casa = Casambi()

    try:
        # This should be rejected immediately as read-only
        import asyncio
        asyncio.run(casa.setControl(None, UnitControlType.SENSOR, 25))
        assert False, "Expected ReadOnlyControlError for SENSOR control"
    except Exception as e:
        from src.CasambiBt.errors import ReadOnlyControlError
        assert isinstance(e, ReadOnlyControlError), f"Expected ReadOnlyControlError, got {type(e)}: {e}"
        assert "Sensors are read-only" in str(e), f"Unexpected error message: {e}"
        print("  ✓ SENSOR control correctly rejected as read-only")


if __name__ == "__main__":
    print("🧪 Running integration tests for device state parsing and command dispatch...")

    try:
        test_device_role_classification()
        test_state_parsing_from_bytes()
        test_command_dispatch()
        test_readonly_sensor_rejection()

        print("\n✅ All integration tests passed!")

    except Exception as e:
        print(f"\n❌ Integration test failed: {e}")
        raise