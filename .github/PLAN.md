# Plan: Extend CasambiBt to Support Non-Light Fixtures

## TL;DR

The existing **UnitType/UnitControl/UnitState framework already supports motorized and sensor devices**—louvers, screens, and sensors all fit seamlessly using existing control types (SLIDER, DIMMER, SENSOR, ONOFF). The **divergence is purely semantic**: current method names (`setLevel()`, `turnOn()`) assume "lighting," creating confusion.

**Solution**: Refactor the public API to be device-agnostic by renaming operations to use a generic `setControl()` dispatcher, introduce a `DeviceRole` enum for consumer discoverability, and implement graceful command rejection for read-only sensors. This avoids rewriting core encoding/decoding logic.

---

## Similarities: Why It Already Works

| Aspect                   | Evidence                                                                                                                                       |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| **Encoding framework**   | Bit-offset/bit-length abstraction in `Unit.getStateAsBytes()` handles any control layout—louvers' SLIDER and screen's DIMMER parse identically |
| **Control types**        | All exist: SLIDER (louver position), DIMMER (screen position), ONOFF (motor/sensor toggles), SENSOR (temp, current, lux, presence)             |
| **State representation** | `UnitState` holds dimmer + vertical + slider + onoff in parallel; devices just use relevant properties, rest stay null                         |
| **Cloud metadata**       | Casambi API returns identical fixture spec format—type IDs 38915/27814/19772 fetch control definitions exactly like lights                     |
| **Protocol transport**   | State bytes, OpCodes, encryption are device-agnostic                                                                                           |

---

## Hard Divergences

| Divergence                 | Impact                                                                 | Solution                                                         |
| -------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------- |
| **Operation naming**       | `setLevel(unit, 128)` for louvers is misleading                        | Rename to `setControl(target, UnitControlType.SLIDER, value)`    |
| **Semantic on/off**        | On/off means "motor running," not "light on"                           | Rename operations; clarify docs; device role hints in `UnitType` |
| **Sensor asymmetry**       | `setTemperature(sensor_unit, 25)` is nonsensical; should silently fail | Detect readonly controls; reject commands before sending packets |
| **State motion**           | Louver transitioning 0→128 has intermediate state                      | Accept as limitation; document pattern                           |
| **Device discoverability** | Consumers can't easily filter lights vs. motors vs. sensors            | Add `DeviceRole` enum heuristic to `UnitType`                    |

---

## ⚠️ Critical Bug: SLIDER Min/Max Encoding

**Discovery**: Current SLIDER encoding/decoding **ignores min/max bounds**, breaking devices like louvers with constrained ranges.

**Current behavior** (broken):

- Louvers spec: min=0°, max=142°, 8-bit encoding
- Consumer sets `state.slider = 142` (max angle)
- Current code: `scaledValue = 142 >> 0 = 142` → encodes as byte `142` ❌
- Device expects: linear map [0, 142] → [0, 255], so should encode as `255`
- **Result**: Louver can't reach full range; all values 0-142 map to bytes 0-142 (only 56% of byte range used)

**Root cause**: [\_unit.py](src/CasambiBt/_unit.py) SLIDER handling at line ~397:

```python
elif c.type == UnitControlType.SLIDER and state.slider is not None:
    scale = UnitState.SLIDER_RESOLUTION - c.length
    scaledValue = state.slider >> scale  # ← Ignores c.min/c.max!
```

**TEMPERATURE already does this correctly** (lines ~383-387):

```python
elif c.type == UnitControlType.TEMPERATURE and ... c.min and c.max:
    clampedTemp = min(c.max, max(c.min, state.temperature))
    tempMask = 2**c.length - 1
    scaledValue = (tempMask * (clampedTemp - c.min)) // (c.max - c.min)
```

**Fix**: Apply same pattern to SLIDER (both `getStateAsBytes()` and `setStateFromBytes()` methods).

---

## Implementation Steps (15 grouped into 6 phases, starting with critical bug fix)

### **Phase 0: Critical Bug Fix** (1 step) ✅ DONE

**0. ✅ DONE - Fix SLIDER min/max encoding** in `src/CasambiBt/_unit.py` (both `getStateAsBytes()` and `setStateFromBytes()`)

- Apply linear min/max mapping identical to TEMPERATURE implementation
- **Encoding** (state → bytes): `scaledValue = (mask * (value - min)) // (max - min)`
- **Decoding** (bytes → state): `value = (scaledInt / mask) * (max - min) + min`
- Add test to verify louvers full range encodes correctly
- **Priority**: Do this first; it's a correctness bug affecting all sliders with min/max bounds

**Completed**: Updated SLIDER encoding/decoding in `_unit.py` to apply linear scaling. Created test validation in `test_slider_minmax.py`.

### **Phase 1: Semantic Clarification** (4 steps) ✅ DONE

1. **✅ DONE - Rename public control methods** in `src/CasambiBt/_casambi.py` to generic `setControl()` dispatcher
   - Old: `setLevel()`, `setColor()`, `turnOn()`, etc.
   - New: `setControl(target, control_type=UnitControlType.DIMMER, value)`
   - Keep backward-compat shims as optional aliases

2. **✅ DONE - Define `DeviceRole` enum** in `src/CasambiBt/_unit.py`
   - Values: `LIGHT`, `MOTORIZED_SHADE`, `MOTORIZED_SCREEN`, `SENSOR`, `UNKNOWN`
   - Queryable: `unit.unitType.device_role` property

3. **✅ DONE - Document control inspection patterns** in `README.md`
   - Example: `[u for u in units if u.unitType.device_role == DeviceRole.MOTORIZED_SHADE]`

4. **✅ DONE - Add motorized/sensor example script** `examples/motorized_and_sensors.py`
   - Demonstrate louver positioning, screen control, and sensor reading

### **Phase 2: Sensor Read-Only Enforcement** (3 steps) ✅ DONE

5. **✅ DONE - Add readonly validation** in `src/CasambiBt/_casambi.py` before dispatching commands
   - Detect readonly controls; log + skip operation (or optionally raise `ReadOnlyControlError`)

6. **✅ DONE - Extend `OperationsContext`** (`src/CasambiBt/_operation.py`) with device role metadata

7. **✅ DONE - Add sensor command rejection tests** `tests/test_sensor_commands.py`

### **Phase 3: Device Classification Metadata** (2 steps) ✅ DONE

8. **✅ DONE - Implement `device_role` heuristic** in `src/CasambiBt/_unit.py`
   - Heuristic: SLIDER+ONOFF→motorized; SENSOR only→sensor; else→light

9. **✅ DONE - Optionally enrich `UnitControl`** with semantic hints (unit, min/max labels)
   - Extract from fixture spec e.g. `"unit": "°"` for louvers

### **Phase 4: Testing & Validation** (3 steps)

10. **Parameterized tests for all control types** `tests/test_device_types.py`
    - Round-trip SLIDER, DIMMER, SENSOR encoding/decoding using provided fixture specs

11. **Integration flow test** `tests/test_integration_devices.py`
    - Mock BLE messages for louvers + sensors; verify state parsing and command dispatch

12. **Update demo.py** with new API patterns and conditional device handling

### **Phase 5: Documentation** (2 steps)

13. **Expand README** with "Non-Light Devices" section, enumeration patterns, divergences explained

14. **Add docstrings** to `DeviceRole`, `setControl()`, `device_role` property, `ReadOnlyControlError`

---

## Relevant Files to Modify

- `src/CasambiBt/_unit.py` — `UnitType`, `UnitControl`, `UnitState`, device_role heuristic
- `src/CasambiBt/_casambi.py` — Refactor control methods to `setControl()` dispatcher; readonly validation
- `src/CasambiBt/_operation.py` — Optional device role metadata
- `src/CasambiBt/errors.py` — Add `ReadOnlyControlError` exception
- `README.md` — Device types, enumeration, examples
- `demo.py` — Update to new API
- **New files**: `tests/test_device_types.py`, `tests/test_integration_devices.py`, `tests/test_sensor_commands.py`, `examples/motorized_and_sensors.py`

---

## Verification Checklist

1. ✅ **SLIDER min/max encoding** works correctly: louvers full range [0°, 142°] maps to [0, 255] byte range
2. ✅ State encoding/decoding round-trip for SLIDER (louvers), DIMMER (screen), SENSOR (sensors)
3. ✅ `setControl()` routes commands correctly; readonly sensors reject commands gracefully
4. ✅ Device role heuristic classifies louvers/screen as motorized, sensors as sensor
5. ✅ Existing light control tests pass (backward compatibility or clean break documented)
6. ✅ README shows enumeration patterns; docs explain each device type
7. ✅ Example scripts are executable

---

## Key Decisions

- **Unified device list**: Consumer inspects `device_role` and `get_control()` rather than type casting (keeps API surface minimal)
- **Graceful readonly rejection**: Sensors parse state correctly but reject commands at dispatch time
- **DeviceRole is heuristic**: Cloud metadata could improve; not part of protocol
- **Clean API break**: Renaming methods is breaking change; justified by clarity; migration guide in CHANGELOG

---

## Further Considerations

1. **Sensor subscriptions** (low priority): Home Assistant may want observation-only semantics; solvable in external integration layer
2. **Unit standardization** (defer to examples): Louvers in degrees, screens in %, etc.—let cloud API define; document in examples
3. **Backward compatibility strategy** (release decision): Full break vs. long deprecation + adapters—recommend clean break given stated willingness
