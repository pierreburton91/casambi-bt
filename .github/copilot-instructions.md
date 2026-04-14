# CasambiBt Project Context

## Project Overview

**CasambiBt** is a currently alpha-quality Bluetooth-based Python library for controlling Casambi-based smart lighting networks. It allows direct BLE communication with Casambi lighting systems without requiring a gateway or the official Casambi API.

### Key Characteristics

- **Status**: Alpha quality, not feature complete
- **Scope**: Protocol implementation based on independent reverse engineering (not official)
- **Platform Support**: Cross-platform (MacOS, Linux, Raspberry Pi) with platform-specific considerations
- **Use Cases**: Direct Bluetooth control of Casambi lights; Home Assistant integration (see external project `casambi-bt-hass`)

## Architecture Overview

### Core Components

1. **`Casambi` class** (`_casambi.py`) - _Central orchestrator_
   - Main entry point for users; abstracts internal complexity
   - Manages callbacks for unit state changes, switch events, and disconnections
   - Owns `CasambiClient` and `Network` instances
   - Handles caching and HTTP client management
   - Provides methods for unit/group/scene operations

2. **`CasambiClient` class** (`_client.py`) - _Bluetooth communication layer_
   - Establishes BLE connections using `bleak` library with `bleak-retry-connector`
   - Handles encryption/decryption of packets
   - Manages protocol handshake (key exchange, authentication)
   - Communicates on characteristic `c9ffde48-ca5a-0001-ab83-8f519b482f77` under Casambi UUID `0000fe4d-0000-1000-8000-00805f9b34fb`
   - Parses incoming packets (UnitState, SwitchEvent, NetworkConfig)

3. **`Network` class** (`_network.py`) - _Network state management_
   - Manages network sessions and authentication token lifecycle
   - Caches network configuration, unit types, units, and groups
   - Fetches and updates network metadata from the Casambi cloud API
   - Handles protocol version negotiation (supports versions 10-11)
   - Manages two cache files: `session.pck` (session), `types.pck` (device type mappings)

4. **`Encryptor` class** (`_encryption.py`) - _Cryptographic operations_
   - AES-ECB encryption/decryption for payload data
   - CMAC (Cipher-based Message Authentication Code) for packet authentication
   - XOR operations for protocol-level encryption
   - Asymmetric key exchange using ECDSA during handshake

5. **`OperationsContext` class** (`_operation.py`) - _Command packaging_
   - Constructs protocol packets (OpCode, flags, lifetime, origin counter)
   - Supports operations: SetLevel, SetTemperature, SetVertical, SetWhite, SetColor, SetSlider, SetState, SetColorXY, SetColorSource
   - Enforces 63-byte payload limit

6. **Discovery system** (`_discover.py`)
   - Uses `BleakScanner` to discover Casambi devices
   - Filters devices by Casambi UUID
   - MacOS-specific: Uses undocumented IOBluetooth API for MAC address retrieval

### Data Models

**Unit** (`_unit.py`):

- Represents a controllable light device
- Supports multiple control types (dimmer, white, RGB, on/off, temperature, vertical, color source, XY, slider, sensor)
- Holds state (brightness, color, temperature, etc.) and metadata

**Group**: Collections of units that can be controlled together

**Scene**: Predefined states for group/unit configurations

**UnitControl/UnitControlType**: Define capabilities and current values for each control dimension

## Protocol Details

### Connection Flow

1. **Discovery**: Scan for BLE devices with Casambi UUID
2. **Connection**: Establish BLE connection to the device
3. **Key Exchange**: ECDSA key agreement for symmetric encryption key
4. **Authentication**: Exchange session tokens/keys
5. **State Sync**: Retrieve network config, units, groups, scenes from cache or cloud
6. **Operation**: Send commands via encrypted packets; receive state updates

### Packet Structure

- **Header** (4 bytes): Flags + OpCode + Origin counter + Target + Reserved
- **Payload** (0-63 bytes): Operation-specific data
- **Authentication** (16 bytes): CMAC signature

### Supported Protocol Versions

- Minimum: 10
- Maximum: 11

## Key Dependencies

- **bleak**: Bluetooth Low Energy client library
- **bleak-retry-connector**: Automatic retry & connection pooling for BLE
- **cryptography**: ECDSA, AES, CMAC implementations
- **httpx**: Async HTTP for cloud API calls (network updates)
- **py.typed**: PEP 561 marker for type checking support

## Configuration & Development

### Code Quality

- **Linting**: Ruff (Python 3.11+)
- **Type Checking**: MyPy (requires py.typed marker)
- **Import Sorting**: isort with black profile
- **Docstring Style**: Google-style with specific exclusions (see `pyproject.toml`)

### Special Considerations

**MacOS Platform**:

- MacOS doesn't expose Bluetooth MAC addresses via official APIs
- Uses undocumented IOBluetooth API as workaround
- Falls back to Raspberry Pi or Linux if MAC address retrieval fails

**Network Setup**:

- Requires Casambi network configured with Evolution firmware
- Network must be in specific configuration state (see README for screenshots)
- Uses HTTPS API for cloud metadata & session management

## Error Handling

Custom exception hierarchy:

- `CasambiBtError` (base)
  - `NetworkNotFoundError`: Network unreachable
  - `NetworkUpdateError`: Cloud sync failure
  - `NetworkOnlineUpdateNeededError`: Cloud update required
  - `AuthenticationError`: Encryption/auth handshake failure
  - `ConnectionStateError`: Invalid state machine transition
  - `BluetoothError`: BLE hardware/driver issues
  - `ProtocolError`: Protocol violation
  - `UnsupportedProtocolVersion`: Server version mismatch

## Caching Strategy

- **Session Cache** (`session.pck`): Network session & authentication tokens (pickle format)
- **Types Cache** (`types.pck`): Device type mappings (pickle format)
- **Expiration**: Sessions tracked with UTC expiry timestamps
- **Path**: Configurable via `cachePath` parameter; defaults to system temp/config

## Development Workflow

1. Use `demo.py` as reference implementation
2. Enable debug logging with `-d` flag (level: DEBUG)
3. Review BLE packet flow using debug logs
4. Run type checking: `mypy`
5. Run linting: `ruff check`
6. Format code: `ruff format`

## Day to day

If available, always refer to the root PLAN.md file to understand the current project state and goals. Before suggesting code, check which task is currently 'In Progress' and ensure your suggestions align with the overall architecture defined there.
