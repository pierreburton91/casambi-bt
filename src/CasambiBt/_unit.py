import logging
from binascii import b2a_hex as b2a
from colorsys import hsv_to_rgb, rgb_to_hsv
from dataclasses import dataclass
from enum import Enum, unique
from typing import Final

_LOGGER = logging.getLogger(__name__)


# Numbers are totally arbitrary so far.
@unique
class UnitControlType(Enum):
    """All implemented control types."""

    DIMMER = 0
    """The brightness of the light can be adjusted."""

    WHITE = 1
    """The amount of white in the light can be adjusted."""

    RGB = 2
    """The color of the light can be adjusted."""

    ONOFF = 3
    """The unit can be turned on or off."""

    TEMPERATURE = 4
    """The temperature of the light can be adjusted."""

    VERTICAL = 5
    """The vertical value of the light can be adjusted."""

    COLORSOURCE = 6
    """The light can switch color source. (TW, RGB, XY)"""

    XY = 7
    """The color of the light can be controlled using CIE color space."""

    SLIDER = 8
    """The slider of the light can be adjusted."""

    SENSOR = 9
    """A sensor value of the light."""

    PRESENCE = 10
    """Raw presence/occupancy sensor reading. Semantics beyond the raw bit value are not reverse engineered."""

    LUX = 11
    """Ambient light level, linearly scaled like SENSOR."""

    SENSORGROUP = 12
    """Raw sensor-group bitmask/flag field. Semantics are not reverse engineered."""

    SENSORGROUPVALUE = 13
    """Packed multi-value blob backing one or more zero-length, tagged SENSOR controls."""

    UNKOWN = 99
    """State isn't implemented. Control saved for debuggin purposes."""


@unique
class DeviceRole(Enum):
    """Semantic classification of a device based on its available controls.

    This enum is used to distinguish lights, motorized devices, and read-only sensors.
    The role is inferred from the `UnitType.controls` list and is intended for
    consumer-facing filtering and device discovery.
    """

    LIGHT = 0
    """A light fixture with dimmer and optional color controls."""

    MOTORIZED_SHADE = 1
    """A motorized shade or blind controlled by slider position."""

    MOTORIZED_SCREEN = 2
    """A motorized projection screen or similar device."""

    SENSOR = 3
    """A sensor providing read-only measurements (temperature, light, humidity, presence, etc.)."""

    UNKNOWN = 99
    """Device type cannot be determined from available controls."""


@unique
class ColorSource(Enum):
    """The possible values for the color source control."""

    TEMPERATURE = 0
    RGB = 1
    XY = 2


@dataclass(frozen=True, repr=True)
class UnitControl:
    type: UnitControlType
    offset: int
    length: int
    default: int
    readonly: bool

    min: int | None = None
    max: int | None = None
    name: str = ""
    unit: str = ""
    localized_names: dict[str, str] | None = None
    tag: int | None = None


@dataclass(frozen=True, repr=True)
class UnitType:
    """Each ``Unit`` has one type that describes what the model is capable of.

    :ivar model: The model name of this unit type.
    :ivar manufacturer: The manufacturer of this unit type.
    :ivar controls: The different types of controls this unit type is capable of.
    """

    id: int
    model: str
    manufacturer: str
    mode: str
    stateLength: int
    controls: list[UnitControl]

    def get_control(self, controlType: UnitControlType) -> UnitControl | None:
        """Return the control description if the unit type supports the given type of control.

        :param controlType: The desired control type.
        :return: A control description for the given control type if available, otherwise `None`
        """
        for c in self.controls:
            if c.type == controlType:
                return c

        return None

    @property
    def device_role(self) -> DeviceRole:
        """Determine the semantic role of this device based on its available controls.

        Heuristic classification:
        - SENSOR: Only has SENSOR control type (read-only measurements)
        - MOTORIZED_SHADE: Has SLIDER + ONOFF (motorized blind/shade positioning)
        - MOTORIZED_SCREEN: Has ONOFF (motor control without slider; e.g., projection screen)
        - LIGHT: Has DIMMER or color controls (RGB, TEMPERATURE, XY, WHITE, COLORSOURCE)
        - UNKNOWN: Unclear device type

        :return: The detected DeviceRole for this device.
        """
        control_types = {c.type for c in self.controls}

        # Check for sensor-only devices
        if (
            UnitControlType.SENSOR in control_types
            or UnitControlType.PRESENCE in control_types
            or UnitControlType.LUX in control_types
            or UnitControlType.SENSORGROUP in control_types
            or UnitControlType.SENSORGROUPVALUE in control_types
        ) and not (
            UnitControlType.DIMMER in control_types
            or UnitControlType.RGB in control_types
            or UnitControlType.TEMPERATURE in control_types
            or UnitControlType.XY in control_types
            or UnitControlType.WHITE in control_types
            or UnitControlType.COLORSOURCE in control_types
            or UnitControlType.SLIDER in control_types
        ):
            return DeviceRole.SENSOR

        # Check for motorized shades (slider + on/off control)
        if (
            UnitControlType.SLIDER in control_types
            and UnitControlType.ONOFF in control_types
        ):
            return DeviceRole.MOTORIZED_SHADE

        # Check for motorized screens (dimmer driven motor control without slider)
        if (
            UnitControlType.DIMMER in control_types
            and UnitControlType.ONOFF in control_types
            and UnitControlType.SLIDER not in control_types
            and not (
                UnitControlType.RGB in control_types
                or UnitControlType.TEMPERATURE in control_types
                or UnitControlType.XY in control_types
                or UnitControlType.WHITE in control_types
                or UnitControlType.COLORSOURCE in control_types
            )
        ):
            return DeviceRole.MOTORIZED_SCREEN

        # Check for lights (dimmer or color controls)
        if (
            UnitControlType.DIMMER in control_types
            or UnitControlType.RGB in control_types
            or UnitControlType.TEMPERATURE in control_types
            or UnitControlType.XY in control_types
            or UnitControlType.WHITE in control_types
            or UnitControlType.COLORSOURCE in control_types
        ):
            return DeviceRole.LIGHT

        return DeviceRole.UNKNOWN


# TODO: Support for different resolutions?
# TODO: Work with HS instead of RGB internally
class UnitState:
    """Parsed representation of the state of a unit."""

    def __init__(self) -> None:
        self._dimmer: int | None = None
        self._rgb: tuple[int, int, int] | None = None
        self._white: int | None = None
        self._temperature: int | None = None
        self._vertical: int | None = None
        self._colorsource: ColorSource | None = None
        self._xy: tuple[float, float] | None = None
        self._slider: int | None = None
        self._sensor: int | None = None
        self._onoff: bool | None = None
        self._presence: int | None = None
        self._lux: int | None = None
        self._sensorgroup: int | None = None
        self._sensors: dict[str, int] = {}

    def _check_range(
        self, value: int | float, min: int | float, max: int | float
    ) -> None:
        if value < min or value > max:
            raise ValueError(f"{value} is not between {min} and {max}")

    DIMMER_RESOLUTION: Final = 8
    DIMMER_MIN: Final = 0
    DIMMER_MAX: Final = 2**DIMMER_RESOLUTION - 1

    @property
    def dimmer(self) -> int | None:
        return self._dimmer

    @dimmer.setter
    def dimmer(self, value: int) -> None:
        self._check_range(value, self.DIMMER_MIN, self.DIMMER_MAX)
        self._dimmer = value

    @dimmer.deleter
    def dimmer(self) -> None:
        self._dimmer = None

    VERTICAL_RESOLUTION: Final = 8
    VERTICAL_MIN: Final = 0
    VERTICAL_MAX: Final = 2**VERTICAL_RESOLUTION - 1

    @property
    def vertical(self) -> int | None:
        return self._vertical

    @vertical.setter
    def vertical(self, value: int) -> None:
        self._check_range(value, self.VERTICAL_MIN, self.VERTICAL_MAX)
        self._vertical = value

    @vertical.deleter
    def vertical(self) -> None:
        self._vertical = None

    RGB_RESOLUTION: Final = 8
    RGB_MIN: Final = 0
    RGB_MAX: Final = 2**RGB_RESOLUTION - 1

    @property
    def rgb(self) -> tuple[int, int, int] | None:
        return self._rgb

    @rgb.setter
    def rgb(self, value: tuple[int, int, int]) -> None:
        r, g, b = value
        self._check_range(r, self.RGB_MIN, self.RGB_MAX)
        self._check_range(g, self.RGB_MIN, self.RGB_MAX)
        self._check_range(b, self.RGB_MIN, self.RGB_MAX)

        self._rgb = (r, g, b)

    @rgb.deleter
    def rgb(self) -> None:
        self._rgb = None

    @property
    def hs(self) -> tuple[float, float] | None:
        """Convert RGB into HS where H is a float in [0..1[ and S a float in [0..1]."""
        if self._rgb is None:
            return None

        rgb_float = [c / (2**self.RGB_RESOLUTION - 1) for c in self._rgb]
        h, s, _ = rgb_to_hsv(*rgb_float)

        h %= 1
        if h == 0 and s == 0:
            h = 0.5

        return (h, s)

    @hs.setter
    def hs(self, value: tuple[float, float]) -> None:
        """Convert HS color to interal RBG representation where H is a float in [0..1[ and S a float in [0..1]."""
        h, s = value

        rgb = hsv_to_rgb(h, s, 1)
        self.rgb = tuple([round(c * (2**self.RGB_RESOLUTION - 1)) for c in rgb])  # type: ignore[assignment]

    WHITE_RESOLUTION = 8
    WHITE_MIN = 0
    WHITE_MAX = 2**WHITE_RESOLUTION - 1

    @property
    def white(self) -> int | None:
        return self._white

    @white.setter
    def white(self, value: int) -> None:
        self._check_range(value, self.WHITE_MIN, self.WHITE_MAX)
        self._white = value

    @white.deleter
    def white(self) -> None:
        self._white = None

    @property
    def temperature(self) -> int | None:
        return self._temperature

    @temperature.setter
    def temperature(self, value: int) -> None:
        self._temperature = value

    @temperature.deleter
    def temperature(self) -> None:
        self._temperature = None

    @property
    def sensor(self) -> int | None:
        return self._sensor

    @sensor.setter
    def sensor(self, value: int) -> None:
        self._sensor = value

    @sensor.deleter
    def sensor(self) -> None:
        self._sensor = None

    @property
    def presence(self) -> int | None:
        return self._presence

    @presence.setter
    def presence(self, value: int) -> None:
        self._presence = value

    @presence.deleter
    def presence(self) -> None:
        self._presence = None

    @property
    def lux(self) -> int | None:
        return self._lux

    @lux.setter
    def lux(self, value: int) -> None:
        self._lux = value

    @lux.deleter
    def lux(self) -> None:
        self._lux = None

    @property
    def sensorgroup(self) -> int | None:
        return self._sensorgroup

    @sensorgroup.setter
    def sensorgroup(self, value: int) -> None:
        self._sensorgroup = value

    @sensorgroup.deleter
    def sensorgroup(self) -> None:
        self._sensorgroup = None

    @property
    def sensors(self) -> dict[str, int]:
        """Decoded values for named, tagged sensor controls (e.g. members of a sensor group)."""
        return self._sensors

    @sensors.setter
    def sensors(self, value: dict[str, int]) -> None:
        self._sensors = dict(value)

    @sensors.deleter
    def sensors(self) -> None:
        self._sensors = {}

    @property
    def colorsource(self) -> ColorSource | None:
        return self._colorsource

    @colorsource.setter
    def colorsource(self, value: ColorSource) -> None:
        self._colorsource = value

    @colorsource.deleter
    def colorsource(self) -> None:
        self._colorsource = None

    @property
    def xy(self) -> tuple[float, float] | None:
        return self._xy

    @xy.setter
    def xy(self, value: tuple[float, float]) -> None:
        x, y = value
        self._check_range(x, 0, 1)
        self._check_range(y, 0, 1)
        self._xy = (x, y)

    @xy.deleter
    def xy(self) -> None:
        self._xy = None

    SLIDER_RESOLUTION: Final = 8
    SLIDER_MIN: Final = 0
    SLIDER_MAX: Final = 2**SLIDER_RESOLUTION - 1

    @property
    def slider(self) -> int | None:
        return self._slider

    @slider.setter
    def slider(self, value: int) -> None:
        self._check_range(value, self.SLIDER_MIN, self.SLIDER_MAX)
        self._slider = value

    @slider.deleter
    def slider(self) -> None:
        self._slider = None

    @property
    def onoff(self) -> bool | None:
        return self._onoff

    @onoff.setter
    def onoff(self, value: bool) -> None:
        self._onoff = value

    @onoff.deleter
    def onoff(self) -> None:
        self._onoff = None

    def __repr__(self) -> str:
        return f"UnitState(dimmer={self.dimmer}, vertical={self.vertical}, rgb={self.rgb.__repr__()}, white={self.white}, temperature={self.temperature}, colorsource={self.colorsource}, xy={self.xy}, slider={self.slider}, onoff={self.onoff}, presence={self.presence}, lux={self.lux}, sensorgroup={self.sensorgroup}, sensors={self.sensors})"


# TODO: Make unit immutable (refactor state, on, online out of it)
@dataclass(init=True, repr=True)
class Unit:
    """A unit in a network.

    :ivar deviceId: Id of the unit within the network.
    :ivar uuid: Globally unique id of the unit.
    :ivar address: MAC address of the unit.
    :ivar name: User assigned name of the unit.
    :ivar firmwareVersion: Firmware version of the unit.

    :ivar unitType: Type of the unit. Determines the capabilities.
    """

    _typeId: int
    deviceId: int
    uuid: str
    address: str
    name: str
    firmwareVersion: str

    unitType: UnitType

    _state: UnitState | None = None
    _on: bool = False
    _online: bool = False

    @property
    def state(self) -> UnitState | None:
        """Get the state of the unit if it has been set."""
        return self._state

    @property
    def is_on(self) -> bool:
        """Determine whether the unit is turned on."""
        if self.unitType.get_control(UnitControlType.ONOFF) and self._state:
            return self._on and self._state.onoff is True
        if self.unitType.get_control(UnitControlType.DIMMER) and self._state:
            return (
                self._on and self._state.dimmer is not None and self._state.dimmer > 0
            )
        else:
            return self._on

    @property
    def online(self) -> bool:
        return self._online

    # TODO: Add tests for this method
    def getStateAsBytes(self, state: UnitState) -> bytes:
        """Given a generic UnitState convert it into the internal state representation.

        Unsupported state information will be ignored.
        """

        # offset, lenth, value
        values: list[tuple[int, int, int]] = []

        # TODO: Support for resolutions >8 byte?
        # Parse and convert state
        for c in self.unitType.controls:
            if c.type == UnitControlType.DIMMER and state.dimmer is not None:
                scale = UnitState.DIMMER_RESOLUTION - c.length
                scaledValue = state.dimmer >> scale
            elif c.type == UnitControlType.VERTICAL and state.vertical is not None:
                scale = UnitState.VERTICAL_RESOLUTION - c.length
                scaledValue = state.vertical >> scale
            elif c.type == UnitControlType.RGB and state.rgb is not None:
                hueLen = (c.length * 10) // 18
                hueMask = 2**hueLen - 1
                satLen = c.length - hueLen
                satMask = 2**satLen - 1

                h, s = state.hs  # type: ignore[misc]

                scaledValue = ((round(h * hueMask) & hueMask) << satLen) + (
                    round(s * satMask) & satMask
                )

                # Old RGB code (might still be useful for earlier protocol versions):
                """
                assert c.length % 3 == 0, "Invalid RGB length"
                scale = UnitState.RGB_RESOLUTION - (c.length // 3)
                scaledValue = 0
                value = state.rgb
                for i in range(3):
                    scaledValue += (value[i] >> scale) * 2 ** (
                        (c.length // 3) * (2 - i)
                    )
                """
            elif c.type == UnitControlType.WHITE and state.white is not None:
                scale = UnitState.WHITE_RESOLUTION - c.length
                scaledValue = state.white >> scale
            elif (
                c.type == UnitControlType.TEMPERATURE
                and state.temperature is not None
                and c.min is not None
                and c.max is not None
                and c.max != c.min
            ):
                clampedTemp = min(c.max, max(c.min, state.temperature))
                tempMask = 2**c.length - 1
                scaledValue = (tempMask * (clampedTemp - c.min)) // (c.max - c.min)
            elif (
                c.type == UnitControlType.SENSOR
                and state.sensor is not None
                and c.min is not None
                and c.max is not None
                and c.length > 0
                and c.max != c.min
            ):
                clampedSensor = min(c.max, max(c.min, state.sensor))
                sensorMask = 2**c.length - 1
                scaledValue = (sensorMask * (clampedSensor - c.min)) // (
                    c.max - c.min
                )
            elif (
                c.type == UnitControlType.COLORSOURCE and state.colorsource is not None
            ):
                scaledValue = state.colorsource.value
            elif c.type == UnitControlType.XY and state.xy is not None:
                coordLen = c.length // 2
                x, y = state.xy
                xyMask = 2**coordLen - 1
                scaledValue = (round(x * xyMask) << coordLen) | round(y * xyMask)
            elif (
                c.type == UnitControlType.SLIDER
                and state.slider is not None
                and c.min is not None
                and c.max is not None
            ):
                clampedSlider = min(c.max, max(c.min, state.slider))
                sliderMask = 2**c.length - 1
                scaledValue = (sliderMask * (clampedSlider - c.min)) // (c.max - c.min)
            elif c.type == UnitControlType.ONOFF and state.onoff is not None:
                scaledValue = 1 if state.onoff else 0

            # Use default if unsupported type or unset value in state
            else:
                scaledValue = c.default

            values.append((c.offset, c.length, scaledValue))

        # Pack state into bytes
        res = bytearray(self.unitType.stateLength)
        for off, len, val in values:
            val <<= off % 8
            byteLen = (len + off % 8 - 1) // 8 + 1
            valBytes = val.to_bytes(byteLen, byteorder="little", signed=False)
            for i in range(byteLen):
                res[off // 8] |= valBytes[i]
                off += 8 - off % 8

        _LOGGER.debug(f"Packing {values.__repr__()} as {res}")
        return bytes(res)

    def _decode_tagged_sensor(
        self,
        c: UnitControl,
        group_raw_by_offset: dict[int, int],
        active_tag: int | None,
    ) -> int | None:
        """Decode a zero-length, tagged SENSOR control from the shared SENSORGROUPVALUE blob.

        Confirmed against live device captures: the device reports exactly one tagged
        sensor's fresh reading per update, round-robin. SENSORGROUP holds a 1-based index
        of which tag that is; SENSORGROUPVALUE's *entire* raw value (not a bit-slice) is
        that tag's raw reading, used as-is (`min`/`max` are documentation bounds, not a
        linear scale target - unlike LUX/generic SENSOR). Other tags simply have no fresh
        data this update and are left at their previous value.

        :return: The tag's raw value if it's the currently active one, else `None`.
        """
        if active_tag is None or c.tag is None or c.tag != active_tag:
            return None
        groupRaw = group_raw_by_offset.get(c.offset)
        if groupRaw is None:
            _LOGGER.warning(
                f"Can't decode zero-length sensor '{c.name}' at offset {c.offset}: "
                "no matching SENSORGROUPVALUE control."
            )
            return None
        return groupRaw

    def _index_sensor_groups(self, value: bytes) -> tuple[dict[int, int], int | None]:
        """Decode SENSORGROUPVALUE blobs and the active tag index from SENSORGROUP.

        SENSORGROUPVALUE/SENSORGROUP typically appear *after* their tagged SENSOR siblings
        in the control list, so this pre-pass lets `setStateFromBytes` resolve them
        regardless of declaration order. Assumes a single SENSORGROUP control selects the
        active tag for all SENSORGROUPVALUE blobs in the unit (true for all known fixtures).
        """
        group_raw_by_offset: dict[int, int] = {}
        active_tag: int | None = None
        for g in self.unitType.controls:
            if g.type not in (
                UnitControlType.SENSORGROUPVALUE,
                UnitControlType.SENSORGROUP,
            ):
                continue
            gByteLen = (g.length + g.offset % 8 - 1) // 8 + 1
            gBytes = value[g.offset // 8 : g.offset // 8 + gByteLen]
            gInt = int.from_bytes(gBytes, byteorder="little", signed=False)
            gInt >>= g.offset % 8
            gInt &= 2**g.length - 1
            if g.type == UnitControlType.SENSORGROUPVALUE:
                group_raw_by_offset[g.offset] = gInt
            elif gInt >= 1:
                active_tag = gInt - 1
        return group_raw_by_offset, active_tag

    # TODO: Add tests for this method
    def setStateFromBytes(self, value: bytes) -> None:
        """Parse state bytes into a `UnitState` and set it for the current unit.

        :param value: State bytes for the unit.
        """
        if not self._state:
            self._state = UnitState()

        group_raw_by_offset, active_tag = self._index_sensor_groups(value)

        # TODO: Support for resolutions >8 byte?
        for c in self.unitType.controls:
            # Extract all relevant bytes from the state
            byteLen = (c.length + c.offset % 8 - 1) // 8 + 1
            cBytes = value[c.offset // 8 : c.offset // 8 + byteLen]

            # Extract c.Length bits form the byte string
            cInt = int.from_bytes(cBytes, byteorder="little", signed=False)
            cInt >>= c.offset % 8
            cInt &= 2**c.length - 1

            if c.type == UnitControlType.DIMMER:
                scale = UnitState.DIMMER_RESOLUTION - c.length
                self._state.dimmer = cInt << scale
            elif c.type == UnitControlType.VERTICAL:
                scale = UnitState.VERTICAL_RESOLUTION - c.length
                self._state.vertical = cInt << scale
            elif c.type == UnitControlType.RGB:
                hueLen = (c.length * 10) // 18
                hueMask = 2**hueLen - 1
                satLen = c.length - hueLen
                satMask = 2**satLen - 1

                h = (cInt >> satLen) / hueMask
                s = (cInt & satMask) / satMask

                self._state.hs = (h, s)
                # Old RGB Code (might still be useful for earlier protocol versions):
                """
                assert c.length % 3 == 0, "Invalid RGB length"
                compLen = c.length // 3
                rgb = []
                scale = UnitState.RGB_RESOLUTION - compLen

                # Extract components from int and scale them
                for i in range(3):
                    v = (cInt >> ((2 - i) * compLen)) & (2 ** compLen - 1)
                    v <<= scale
                    rgb.append(v)
                self._state.rgb = tuple(rgb)
                """
            elif c.type == UnitControlType.WHITE:
                scale = UnitState.WHITE_RESOLUTION - c.length
                self._state.white = cInt << scale
            elif c.type == UnitControlType.TEMPERATURE:
                if c.max is None or c.min is None or c.max == c.min:
                    _LOGGER.warning("Can't set temperature when min or max unknown.")
                    continue
                tempRange = c.max - c.min
                tempMask = 2**c.length - 1
                # TODO: We should probalby try to make this number a bit more round
                self._state.temperature = int(((cInt / tempMask) * tempRange) + c.min)
            elif c.type == UnitControlType.SENSOR and c.length == 0:
                tagValue = self._decode_tagged_sensor(
                    c, group_raw_by_offset, active_tag
                )
                if tagValue is not None:
                    self._state.sensors[c.name] = tagValue
            elif c.type == UnitControlType.SENSOR:
                if c.max is None or c.min is None or c.max == c.min:
                    _LOGGER.warning("Can't set sensor when min or max unknown.")
                    continue
                sensorRange = c.max - c.min
                sensorMask = 2**c.length - 1
                self._state.sensor = int(((cInt / sensorMask) * sensorRange) + c.min)
            elif c.type == UnitControlType.PRESENCE:
                self._state.presence = cInt
            elif c.type == UnitControlType.LUX:
                luxMin = c.min if c.min is not None else 0
                if c.max is None or c.max == luxMin:
                    _LOGGER.warning("Can't set lux when max unknown.")
                    continue
                luxRange = c.max - luxMin
                luxMask = 2**c.length - 1
                self._state.lux = int(((cInt / luxMask) * luxRange) + luxMin)
            elif c.type == UnitControlType.SENSORGROUP:
                self._state.sensorgroup = cInt
            elif c.type == UnitControlType.SENSORGROUPVALUE:
                # Consumed via the pre-pass + the zero-length SENSOR branch above.
                pass
            elif c.type == UnitControlType.COLORSOURCE:
                self._state.colorsource = ColorSource(cInt)
            elif c.type == UnitControlType.XY:
                coordLen = c.length // 2
                xyMask = 2**coordLen - 1
                y = cInt & xyMask
                x = (cInt >> coordLen) & xyMask
                self._state.xy = (x / xyMask, y / xyMask)
            elif c.type == UnitControlType.SLIDER:
                if c.max is None or c.min is None or c.max == c.min:
                    _LOGGER.warning("Can't set slider when min or max unknown.")
                    continue
                sliderRange = c.max - c.min
                sliderMask = 2**c.length - 1
                self._state.slider = int(((cInt / sliderMask) * sliderRange) + c.min)
            elif c.type == UnitControlType.ONOFF:
                self._state.onoff = cInt != 0
            elif c.type == UnitControlType.UNKOWN:
                # Might be useful for implementing more state types
                _LOGGER.debug(
                    f"Value for unkown control type at {c.offset}: {cInt}. Unit type is {self.unitType.id}."
                )

        _LOGGER.debug(f"Parsed {b2a(value)} to {self.state.__repr__()}")


@dataclass
class Scene:
    """A scene in a network.

    :ivar sceneId: The id of the scene in the network.
    :ivar name: The name of the scene.
    """

    sceneId: int
    name: str


@dataclass
class Group:
    """A group (collection of units) in a network.

    :ivar groupId: The id of the group in the network.
    :ivar name: The name of the group.
    :ivar units: A list of units in this group.
    """

    groudId: int
    name: str

    units: list[Unit]
