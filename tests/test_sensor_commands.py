#!/usr/bin/env python3
"""Test sensor command rejection for read-only controls."""

import asyncio
from src.CasambiBt import Casambi
from src.CasambiBt._unit import UnitControlType
from src.CasambiBt.errors import ReadOnlyControlError


async def test_sensor_control_rejection():
    """Verify that attempting to set a SENSOR control raises ReadOnlyControlError."""
    casa = Casambi()
    
    # Attempt to set a sensor value should raise ReadOnlyControlError
    try:
        # This should raise before any network operations
        await casa.setControl(None, UnitControlType.SENSOR, 25)
        assert False, "Expected ReadOnlyControlError to be raised"
    except ReadOnlyControlError as e:
        assert "Sensors are read-only" in str(e)
        print("✓ SENSOR control correctly rejected with ReadOnlyControlError")
    except Exception as e:
        assert False, f"Unexpected exception: {e}"


async def test_other_controls_allowed():
    """Verify that non-sensor controls don't raise ReadOnlyControlError immediately."""
    casa = Casambi()
    
    # These should not raise ReadOnlyControlError (may fail later due to no connection)
    allowed_controls = [
        (UnitControlType.DIMMER, 128),
        (UnitControlType.SLIDER, 100),
        (UnitControlType.TEMPERATURE, 3000),
        (UnitControlType.ONOFF, 1),
    ]
    
    for control_type, value in allowed_controls:
        try:
            # This will fail later due to no connection, but not due to readonly
            await casa.setControl(None, control_type, value)
            assert False, f"Expected connection error, not success for {control_type}"
        except ReadOnlyControlError:
            assert False, f"Unexpected ReadOnlyControlError for {control_type}"
        except Exception as e:
            # Expected to fail due to connection, not readonly
            assert "Expected state" in str(e) or "connection" in str(e).lower()
            print(f"✓ {control_type} control passed readonly check (failed later as expected)")


async def main():
    await test_sensor_control_rejection()
    await test_other_controls_allowed()
    print("All sensor command rejection tests passed!")


if __name__ == "__main__":
    asyncio.run(main())