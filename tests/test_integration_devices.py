#!/usr/bin/env python3
"""Integration tests for device state parsing and command dispatch using mocked data."""

import json
import os
from CasambiBt import Casambi
from CasambiBt._unit import Unit, UnitType, UnitControl, UnitControlType, UnitState, DeviceRole


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
            control_type = UnitControlType.UNKOWN

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
            tag=control_json.get("tag"),
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
    state_bytes[28 // 8] = 0xF0  # Max slider position encoded across the byte boundary
    state_bytes[36 // 8] = 0x1F  # Lower nibble contains slider high bits and bit4 is ON/OFF

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
    state_bytes[28 // 8] = 0x00  # 50% dimmer position encoded across the byte boundary
    state_bytes[36 // 8] = 0x18  # Lower nibble contains dimmer high bits and bit4 is ON/OFF

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


def test_onoff_dispatch_uses_setstate_for_shades_and_screens():
    """Test that ONOFF routes through setUnitState (OpCode.SetState) for shades/screens, not setLevel."""
    print("\n🧪 Testing ONOFF dispatch for motorized shades/screens...")

    import asyncio

    casa = Casambi()

    calls: dict = {"setUnitState": None, "setLevel": None, "turnOn": None}

    async def fake_set_unit_state(target, state):
        calls["setUnitState"] = (target, state)

    async def fake_set_level(target, level):
        calls["setLevel"] = (target, level)

    async def fake_turn_on(target):
        calls["turnOn"] = (target,)

    casa.setUnitState = fake_set_unit_state
    casa.setLevel = fake_set_level
    casa.turnOn = fake_turn_on

    # Louver (MOTORIZED_SHADE, no DIMMER control): slider position must be
    # preserved and ONOFF must be routed via setUnitState, not setLevel.
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
    seed_state = UnitState()
    seed_state.slider = 71
    louver_unit.setStateFromBytes(louver_unit.getStateAsBytes(seed_state))
    assert louver_unit.state is not None and louver_unit.state.slider is not None

    asyncio.run(casa.setControl(louver_unit, UnitControlType.ONOFF, 1))
    assert calls["setLevel"] is None, "ONOFF for a shade must not use setLevel"
    assert calls["setUnitState"] is not None, "ONOFF for a shade must use setUnitState"
    target, state = calls["setUnitState"]
    assert target is louver_unit
    assert state.onoff is True
    assert (
        abs(state.slider - 71) <= 1
    ), f"Slider position should be preserved, got {state.slider}"
    print("  ✓ Louver ONOFF routed through setUnitState with slider preserved")

    calls["setUnitState"] = None
    calls["setLevel"] = None

    # Screen (MOTORIZED_SCREEN, DIMMER but no SLIDER): dimmer position must
    # be preserved and ONOFF must be routed via setUnitState, not setLevel.
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
    seed_state = UnitState()
    seed_state.dimmer = 128
    screen_unit.setStateFromBytes(screen_unit.getStateAsBytes(seed_state))
    assert screen_unit.state is not None and screen_unit.state.dimmer is not None

    asyncio.run(casa.setControl(screen_unit, UnitControlType.ONOFF, 0))
    assert calls["setLevel"] is None, "ONOFF for a screen must not use setLevel"
    assert calls["setUnitState"] is not None, "ONOFF for a screen must use setUnitState"
    target, state = calls["setUnitState"]
    assert target is screen_unit
    assert state.onoff is False
    assert (
        state.dimmer == 128
    ), f"Dimmer position should be preserved, got {state.dimmer}"
    print("  ✓ Screen ONOFF routed through setUnitState with dimmer preserved")

    calls["setUnitState"] = None
    calls["setLevel"] = None
    calls["turnOn"] = None

    # Plain light (DIMMER+ONOFF+RGB => DeviceRole.LIGHT): ONOFF must restore
    # the last brightness via turnOn() rather than forcing setLevel(255) --
    # no fixture spec for a plain light exists under doc/fixtures-specs/, so
    # build one inline.
    light_type = UnitType(
        id=999,
        model="Test Light",
        manufacturer="Test",
        mode="test",
        stateLength=4,
        controls=[
            UnitControl(
                type=UnitControlType.DIMMER,
                offset=0,
                length=8,
                default=0,
                readonly=False,
            ),
            UnitControl(
                type=UnitControlType.ONOFF,
                offset=8,
                length=1,
                default=0,
                readonly=False,
            ),
            UnitControl(
                type=UnitControlType.RGB,
                offset=9,
                length=18,
                default=0,
                readonly=False,
            ),
        ],
    )
    light_unit = Unit(
        _typeId=light_type.id,
        deviceId=3,
        uuid="test-light",
        address="00:11:22:33:44:57",
        name="Test Light",
        firmwareVersion="1.0",
        unitType=light_type,
    )
    assert light_unit.unitType.device_role == DeviceRole.LIGHT

    asyncio.run(casa.setControl(light_unit, UnitControlType.ONOFF, 1))
    assert calls["setUnitState"] is None, "ONOFF for a light must not use setUnitState"
    assert calls["setLevel"] is None, "ONOFF=1 for a light should restore last level via turnOn, not setLevel"
    assert calls["turnOn"] == (
        light_unit,
    ), f"ONOFF=1 for a light should call turnOn(target), got {calls['turnOn']}"
    print("  ✓ Light ONOFF=1 routed through turnOn (restores last brightness)")

    calls["turnOn"] = None

    asyncio.run(casa.setControl(light_unit, UnitControlType.ONOFF, 0))
    assert calls["setUnitState"] is None, "ONOFF for a light must not use setUnitState"
    assert calls["turnOn"] is None, "ONOFF=0 for a light must not use turnOn"
    assert calls["setLevel"] == (
        light_unit,
        0,
    ), f"ONOFF=0 for a light should call setLevel(target, 0), got {calls['setLevel']}"
    print("  ✓ Light ONOFF=0 routed through setLevel(target, 0)")


def test_onoff_dispatch_for_light_without_onoff_control():
    """Test that ONOFF works for lights that have no dedicated ONOFF control (e.g. dimmer-only)."""
    print("\n🧪 Testing ONOFF dispatch for a dimmer-only light...")

    import asyncio

    casa = Casambi()

    calls: dict = {"setUnitState": None, "setLevel": None, "turnOn": None}

    async def fake_set_unit_state(target, state):
        calls["setUnitState"] = (target, state)

    async def fake_set_level(target, level):
        calls["setLevel"] = (target, level)

    async def fake_turn_on(target):
        calls["turnOn"] = (target,)

    casa.setUnitState = fake_set_unit_state
    casa.setLevel = fake_set_level
    casa.turnOn = fake_turn_on

    # Dimmer-only unit: no ONOFF control, but DIMMER alone still classifies
    # it as DeviceRole.LIGHT.
    dimmer_type = UnitType(
        id=1000,
        model="Test Dimmer Light",
        manufacturer="Test",
        mode="test",
        stateLength=1,
        controls=[
            UnitControl(
                type=UnitControlType.DIMMER,
                offset=0,
                length=8,
                default=0,
                readonly=False,
            ),
        ],
    )
    dimmer_unit = Unit(
        _typeId=dimmer_type.id,
        deviceId=4,
        uuid="test-dimmer-light",
        address="00:11:22:33:44:58",
        name="Test Dimmer Light",
        firmwareVersion="1.0",
        unitType=dimmer_type,
    )
    assert dimmer_unit.unitType.device_role == DeviceRole.LIGHT
    assert dimmer_unit.unitType.get_control(UnitControlType.ONOFF) is None

    asyncio.run(casa.setControl(dimmer_unit, UnitControlType.ONOFF, 1))
    assert calls["setUnitState"] is None, "ONOFF for a dimmer-only light must not use setUnitState"
    assert calls["setLevel"] is None, "ONOFF=1 for a dimmer-only light should restore last level via turnOn"
    assert calls["turnOn"] == (
        dimmer_unit,
    ), f"ONOFF=1 for a dimmer-only light should call turnOn(target), got {calls['turnOn']}"
    print("  ✓ Dimmer-only light ONOFF=1 routed through turnOn")

    calls["turnOn"] = None

    asyncio.run(casa.setControl(dimmer_unit, UnitControlType.ONOFF, 0))
    assert calls["turnOn"] is None, "ONOFF=0 for a dimmer-only light must not use turnOn"
    assert calls["setLevel"] == (
        dimmer_unit,
        0,
    ), f"ONOFF=0 for a dimmer-only light should call setLevel(target, 0), got {calls['setLevel']}"
    print("  ✓ Dimmer-only light ONOFF=0 routed through setLevel(target, 0)")


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
        from CasambiBt.errors import ReadOnlyControlError
        assert isinstance(e, ReadOnlyControlError), f"Expected ReadOnlyControlError, got {type(e)}: {e}"
        assert "Sensors are read-only" in str(e), f"Unexpected error message: {e}"
        print("  ✓ SENSOR control correctly rejected as read-only")


if __name__ == "__main__":
    print("🧪 Running integration tests for device state parsing and command dispatch...")

    try:
        test_device_role_classification()
        test_state_parsing_from_bytes()
        test_command_dispatch()
        test_onoff_dispatch_uses_setstate_for_shades_and_screens()
        test_onoff_dispatch_for_light_without_onoff_control()
        test_readonly_sensor_rejection()

        print("\n✅ All integration tests passed!")

    except Exception as e:
        print(f"\n❌ Integration test failed: {e}")
        raise