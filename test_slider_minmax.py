#!/usr/bin/env python3
"""Test SLIDER min/max encoding fix for motorized devices like louvers."""

from src.CasambiBt._unit import Unit, UnitType, UnitControl, UnitControlType, UnitState


def test_slider_encoding_with_minmax():
    """Verify SLIDER min/max encoding maps to full byte range.
    
    Example: Louvers with min=0°, max=142°, 8-bit encoding
    - Setting slider to max (142) should encode as byte 255
    - Setting slider to min (0) should encode as byte 0
    - Setting slider to middle (71) should encode as byte ~128
    """
    # Create a mock louver unit type with SLIDER control
    slider_control = UnitControl(
        type=UnitControlType.SLIDER,
        offset=0,
        length=8,
        default=0,
        readonly=False,
        min=0,
        max=142,
        name="$pos",
        unit="°",
        localized_names={"en": "Louvre Position", "de": "Position der Lamellen"},
    )
    
    louver_type = UnitType(
        id=38915,
        model="Louver",
        manufacturer="Casambi",
        mode="motorized",
        stateLength=1,
        controls=[slider_control],
    )
    
    louver_unit = Unit(
        _typeId=38915,
        deviceId=1,
        uuid="test-louver",
        address="00:11:22:33:44:55",
        name="Test Louver",
        firmwareVersion="1.0",
        unitType=louver_type,
    )
    
    # Test 1: Max angle (142°) should encode to byte 255
    state = UnitState()
    state.slider = 142
    encoded = louver_unit.getStateAsBytes(state)
    assert encoded[0] == 255, f"Max angle (142°) should encode to 255, got {encoded[0]}"
    print("✓ Max angle (142°) encodes to byte 255")
    
    # Test 2: Min angle (0°) should encode to byte 0
    state = UnitState()
    state.slider = 0
    encoded = louver_unit.getStateAsBytes(state)
    assert encoded[0] == 0, f"Min angle (0°) should encode to 0, got {encoded[0]}"
    print("✓ Min angle (0°) encodes to byte 0")
    
    # Test 3: Middle angle (~71°) should encode to byte ~128
    state = UnitState()
    state.slider = 71
    encoded = louver_unit.getStateAsBytes(state)
    # 71/142 ≈ 0.5 * 255 ≈ 127-128
    assert 126 <= encoded[0] <= 128, f"Middle angle (~71°) should encode to ~128, got {encoded[0]}"
    print(f"✓ Middle angle (71°) encodes to byte {encoded[0]} (expected ~128)")
    
    # Test 4: Decoding - byte 255 should decode to slider ~142
    louver_unit.setStateFromBytes(bytes([255]))
    assert louver_unit.state.slider == 142, f"Byte 255 should decode to 142, got {louver_unit.state.slider}"
    print("✓ Byte 255 decodes to slider value 142")
    
    # Test 5: Decoding - byte 0 should decode to slider 0
    louver_unit.setStateFromBytes(bytes([0]))
    assert louver_unit.state.slider == 0, f"Byte 0 should decode to 0, got {louver_unit.state.slider}"
    print("✓ Byte 0 decodes to slider value 0")
    
    # Test 6: Decoding - byte 128 should decode to slider ~71
    louver_unit.setStateFromBytes(bytes([128]))
    # 128/255 * 142 + 0 ≈ 71
    assert 70 <= louver_unit.state.slider <= 72, f"Byte 128 should decode to ~71, got {louver_unit.state.slider}"
    print(f"✓ Byte 128 decodes to slider value {louver_unit.state.slider} (expected ~71)")
    
    # Test 7: Round-trip test
    state = UnitState()
    state.slider = 100
    encoded = louver_unit.getStateAsBytes(state)
    louver_unit.setStateFromBytes(encoded)
    # Due to integer division, we expect some loss of precision
    assert abs(louver_unit.state.slider - 100) <= 1, f"Round-trip should preserve ~100, got {louver_unit.state.slider}"
    print(f"✓ Round-trip: 100 → encode → decode → {louver_unit.state.slider}")
    
    print("\n✅ All SLIDER min/max encoding tests passed!")


if __name__ == "__main__":
    test_slider_encoding_with_minmax()
