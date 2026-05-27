import asyncio
import logging
import struct
from binascii import b2a_hex as b2a
from collections.abc import Callable
from hashlib import sha256
from typing import Any

from bleak.backends.device import BLEDevice
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec

from CasambiBt._switch import parseSwitchEvents

from ._constants import (
    CASA_AUTH_CHAR_UUID,
    MAX_VERSION,
    MIN_VERSION,
    ConnectionState,
    IncomingPacketType,
)
from ._encryption import Encryptor
from ._network import Network
from ._transport import BluetoothTransport, TransportConnection

# We need to move these imports here to prevent a cycle.
from .errors import (  # noqa: E402
    BluetoothError,
    ConnectionStateError,
    NetworkNotFoundError,
    ProtocolError,
    UnsupportedProtocolVersion,
)


class CasambiClient:
    def __init__(
        self,
        address_or_device: str | BLEDevice,
        dataCallback: Callable[[IncomingPacketType, Any], None],
        disonnectedCallback: Callable[[], None],
        network: Network,
        transport: BluetoothTransport | None = None,
    ) -> None:
        self._notifySignal = asyncio.Event()
        self._network = network

        self._mtu: int
        self._unitId: int
        self._flags: int
        self._nonce: bytes
        self._key: bytearray

        self._encryptor: Encryptor

        self._outPacketCount = 0
        self._inPacketCount = 0

        self._callbackQueue: asyncio.Queue[tuple[str, bytes]]
        self._callbackTask: asyncio.Task[None] | None = None

        self._address_or_devive = address_or_device
        self.address = (
            address_or_device.address
            if isinstance(address_or_device, BLEDevice)
            else address_or_device
        )
        self._logger = logging.getLogger(__name__)
        self._connectionState: ConnectionState = ConnectionState.NONE
        self._dataCallback = dataCallback
        self._disconnectedCallback = disonnectedCallback
        self._activityLock = asyncio.Lock()

        # Transport-related attributes
        self._transport = transport
        self._connection: TransportConnection | None = None

        self._checkProtocolVersion(network.protocolVersion)

    def _checkProtocolVersion(self, version: int) -> None:
        if version < MIN_VERSION:
            raise UnsupportedProtocolVersion(
                f"Legacy version aren't supported currently. Your network version is {version}. Minimum version is {MIN_VERSION}."
            )
        if version > MAX_VERSION:
            self._logger.warning(
                "Version too new. Your network version is %i. Highest supported version is %i. Continue at your own risk.",
                version,
                MAX_VERSION,
            )

    def _checkState(self, desired: ConnectionState) -> None:
        if self._connectionState != desired:
            raise ConnectionStateError(desired, self._connectionState)

    async def connect(self) -> None:
        self._checkState(ConnectionState.NONE)

        self._logger.info(f"Connection to {self.address}")

        # Reset packet counters
        self._outPacketCount = 2
        self._inPacketCount = 1

        # Reset callback queue
        self._callbackQueue = asyncio.Queue()
        self._callbackTask = asyncio.create_task(self._processCallbacks())

        # Get transport if not provided
        if self._transport is None:
            from ._transport_factory import get_transport

            self._transport = get_transport()

        # Create a BLEDevice object for the address
        device = (
            self._address_or_devive
            if isinstance(self._address_or_devive, BLEDevice)
            else BLEDevice(
                address=self.address,
                name=None,
                details={},
                rssi=0,
            )
        )

        try:
            # Use transport to connect
            self._connection = await self._transport.connect(device)

            if not self._connection.is_connected:
                self._logger.error("Failed to connect via transport")
                raise NetworkNotFoundError

        except Exception as e:
            self._logger.error("Failed to connect.", exc_info=True)
            raise BluetoothError from e

        self._logger.info(f"Connected to {self.address}")
        self._connectionState = ConnectionState.CONNECTED

    async def _on_disconnect(self) -> None:
        """Handle disconnection from transport."""
        if self._connectionState != ConnectionState.NONE:
            self._logger.info(f"Received disconnect callback from {self.address}")
        if self._connectionState == ConnectionState.AUTHENTICATED:
            self._logger.debug("Executing disconnect callback.")
            self._disconnectedCallback()
        self._connectionState = ConnectionState.NONE

    async def exchangeKey(self) -> None:
        self._checkState(ConnectionState.CONNECTED)

        self._logger.info("Starting key exchange...")

        await self._activityLock.acquire()
        try:
            if self._connection is None:
                raise ConnectionStateError(
                    ConnectionState.CONNECTED, self._connectionState
                )

            # Initiate communication with device
            firstResp = await self._connection.read_gatt_char(CASA_AUTH_CHAR_UUID)
            self._logger.debug(f"Got {b2a(firstResp)}")

            # Check type and protocol version
            if not (
                firstResp[0] == 0x1 and firstResp[1] == self._network.protocolVersion
            ):
                if (
                    firstResp[0] == 0x1
                    and firstResp[1] == 0x2B
                    and self._network.protocolVersion == 11
                ):
                    # This is what happens for protocol version 11 so skip the error.
                    # TODO: Implement proper handling after understanding this behavior.
                    pass
                else:
                    self._logger.error(
                        "Unexpected answer from device! Wrong device or protocol version? Trying to continue."
                    )

            # Parse device info
            self._mtu, self._unit, self._flags, self._nonce = struct.unpack_from(
                ">BHH16s", firstResp, 2
            )
            self._logger.debug(
                f"Parsed mtu {self._mtu}, unit {self._unit}, flags {self._flags}, nonce {b2a(self._nonce)}"
            )

            # Device will initiate key exchange, so listen for that
            self._logger.debug("Starting notify")
            await self._connection.start_notify(
                CASA_AUTH_CHAR_UUID,
                self._queueCallback,
            )
        finally:
            self._activityLock.release()

        # Wait for key exchange, will get notified by _exchNotifyCallback
        await self._notifySignal.wait()
        await self._activityLock.acquire()
        try:
            self._notifySignal.clear()
            if self._connectionState == ConnectionState.ERROR:
                raise ProtocolError("Invalid key exchange initiation.")

            # Respond to key exchange
            pubNums = self._pubKey.public_numbers()
            keyExchResponse = struct.pack(
                ">B32s32sB",
                0x2,
                pubNums.x.to_bytes(32, byteorder="little", signed=False),
                pubNums.y.to_bytes(32, byteorder="little", signed=False),
                0x1,
            )
            if self._connection is None:
                raise ConnectionStateError(
                    ConnectionState.CONNECTED, self._connectionState
                )
            await self._connection.write_gatt_char(CASA_AUTH_CHAR_UUID, keyExchResponse)
        finally:
            self._activityLock.release()

        # Wait for success response from _exchNotifyCallback
        await self._notifySignal.wait()
        await self._activityLock.acquire()
        try:
            self._notifySignal.clear()
            if self._connectionState == ConnectionState.ERROR:  # type: ignore[comparison-overlap]
                raise ProtocolError("Failed to negotiate key!")
            else:
                self._logger.info("Key exchange successful")
                self._encryptor = Encryptor(self._transportKey)

                # Skip auth if the network doesn't use a key.
                if self._network.keyStore.getKey():
                    self._connectionState = ConnectionState.KEY_EXCHANGED
                else:
                    self._connectionState = ConnectionState.AUTHENTICATED
        finally:
            self._activityLock.release()

    def _queueCallback(self, data: bytes) -> None:
        """Handle notification data."""
        self._callbackQueue.put_nowait((CASA_AUTH_CHAR_UUID, data))

    async def _processCallbacks(self) -> None:
        while True:
            char_uuid, data = await self._callbackQueue.get()

            # Try to loose any races here.
            # Otherwise a state change caused by the last packet might not have been handled yet
            await asyncio.sleep(0.001)
            await self._activityLock.acquire()
            try:
                self._callbackMultiplexer(char_uuid, data)
            finally:
                self._callbackQueue.task_done()
                self._activityLock.release()

    def _callbackMultiplexer(self, char_uuid: str, data: bytes) -> None:
        """Route callback data to the appropriate handler based on connection state."""
        self._logger.debug(f"Callback for {char_uuid}: {b2a(data)}")

        if self._connectionState == ConnectionState.CONNECTED:
            self._exchNotifyCallback(data)
        elif self._connectionState == ConnectionState.KEY_EXCHANGED:
            self._authNotifyCallback(data)
        elif self._connectionState == ConnectionState.AUTHENTICATED:
            self._establishedNotifyCallback(data)
        else:
            self._logger.warning(
                f"Unhandled notify in state {self._connectionState}: {b2a(data)}"
            )

    def _exchNotifyCallback(self, data: bytes) -> None:
        """Handle notification during key exchange."""
        if data[0] == 0x2:
            # Parse device pubkey
            x, y = struct.unpack_from("<32s32s", data, 1)
            x = int.from_bytes(x, byteorder="little")
            y = int.from_bytes(y, byteorder="little")
            self._logger.debug(f"Got public key {x}, {y}")

            self._devicePubKey = ec.EllipticCurvePublicNumbers(
                x, y, ec.SECP256R1()
            ).public_key()

            # Generate key pair for client
            self._privKey = ec.generate_private_key(ec.SECP256R1())
            self._pubKey = self._privKey.public_key()

            # Generate shared secret
            secret = bytearray(self._privKey.exchange(ec.ECDH(), self._devicePubKey))
            secret.reverse()
            hashAlgo = sha256()
            hashAlgo.update(secret)
            digestedSecret = hashAlgo.digest()

            # Compute transport key
            self._transportKey = bytearray()
            for i in range(16):
                self._transportKey.append(digestedSecret[i] ^ digestedSecret[16 + i])

            # Inform exchangeKey that packet has been parsed
            self._notifySignal.set()

        elif data[0] == 0x3:
            if len(data) == 1:
                # Key exchange is acknowledged by device
                self._notifySignal.set()
            else:
                self._logger.error(
                    f"Unexpected package length for key exchange response: {b2a(data)}"
                )
                self._connectionState = ConnectionState.ERROR
                self._notifySignal.set()
        else:
            self._logger.error(f"Unexpected package type in {b2a(data)}.")
            self._connectionState = ConnectionState.ERROR
            self._notifySignal.set()

    async def authenticate(self) -> None:
        self._checkState(ConnectionState.KEY_EXCHANGED)

        self._logger.info("Authenticating channel...")
        key = self._network.keyStore.getKey()  # Session key

        if not key:
            self._logger.info("No key in keystore. Skipping auth.")
            # The channel already has to be set to authenticated by exchangeKey.
            # This needs to be done there a non-handshake packet could be sent right after acking the key exch
            # and we don't want that packet to end up in _authNotifyCallback.
            return

        await self._activityLock.acquire()
        try:
            # Compute client auth digest
            hashFcnt = sha256()
            hashFcnt.update(key.key)
            hashFcnt.update(self._nonce)
            hashFcnt.update(self._transportKey)
            authDig = hashFcnt.digest()
            self._logger.debug(f"Auth digest: {b2a(authDig)}")

            # Send auth packet
            authPacket = int.to_bytes(1, 4, "little")
            authPacket += b"\x04"
            authPacket += key.id.to_bytes(1, "little")
            authPacket += authDig
            await self._writeEncPacket(authPacket, 1, CASA_AUTH_CHAR_UUID)
        finally:
            self._activityLock.release()

        # Wait for auth response
        await self._notifySignal.wait()

        await self._activityLock.acquire()
        try:
            self._notifySignal.clear()
            if self._connectionState == ConnectionState.ERROR:
                raise ProtocolError("Failed to verify authentication response.")
            else:
                self._connectionState = ConnectionState.AUTHENTICATED
                self._logger.info("Authentication successful")
        finally:
            self._activityLock.release()

    def _authNotifyCallback(self, data: bytes) -> None:
        """Handle notification during authentication."""
        self._logger.info("Processing authentication response...")

        # TODO: Verify counter
        self._inPacketCount += 1

        try:
            self._encryptor.decryptAndVerify(data, data[:4] + self._nonce[4:])
        except InvalidSignature:
            self._logger.fatal("Invalid signature for auth response!")
            self._connectionState = ConnectionState.ERROR
            return

        # TODO: Verify Digest 2 (to compare with response from device); SHA256(key.key||self pubKey point||self._transportKey)

        self._notifySignal.set()

    async def _writeEncPacket(
        self, packet: bytes, id: int, char_uuid: str
    ) -> None:
        """Write an encrypted packet to a characteristic."""
        encPacket = self._encryptor.encryptThenMac(packet, self._getNonce(id))
        if self._connection is None:
            raise ConnectionStateError(ConnectionState.AUTHENTICATED, self._connectionState)
        try:
            await self._connection.write_gatt_char(char_uuid, encPacket)
        except BluetoothError as e:
            if "Not connected" in str(e):
                self._connectionState = ConnectionState.NONE
            else:
                raise e
        except Exception as e:
            self._connectionState = ConnectionState.NONE
            raise BluetoothError from e

    def _getNonce(self, id: int | bytes) -> bytes:
        if isinstance(id, int):
            id = id.to_bytes(4, "little")
        return self._nonce[:4] + id + self._nonce[8:]

    async def send(self, packet: bytes) -> None:
        self._checkState(ConnectionState.AUTHENTICATED)

        await self._activityLock.acquire()
        try:
            self._logger.debug(
                f"Sending packet {b2a(packet)} with counter {self._outPacketCount}"
            )

            counter = int.to_bytes(self._outPacketCount, 4, "little")
            headerPaket = counter + b"\x07" + packet

            self._logger.debug(f"Packet with header: {b2a(headerPaket)}")

            await self._writeEncPacket(
                headerPaket, self._outPacketCount, CASA_AUTH_CHAR_UUID
            )
            self._outPacketCount += 1
        finally:
            self._activityLock.release()

    def _establishedNotifyCallback(self, data: bytes) -> None:
        """Handle notification when connection is established and authenticated."""
        # TODO: Check incoming counter and direction flag
        self._inPacketCount += 1

        # Store raw encrypted packet for reference
        raw_encrypted_packet = data[:]

        # Log raw encrypted packet with special marker for easy filtering
        self._logger.info(
            f"[CASAMBI_RAW_PACKET] Encrypted #{self._inPacketCount}: {b2a(raw_encrypted_packet)}"
        )

        try:
            decrypted_data = self._encryptor.decryptAndVerify(
                data, data[:4] + self._nonce[4:]
            )
        except InvalidSignature:
            # We only drop packets with invalid signature here instead of going into an error state
            self._logger.error(f"Invalid signature for packet {b2a(data)}!")
            return

        packetType = decrypted_data[0]
        self._logger.debug(f"Incoming data of type {packetType}: {b2a(decrypted_data)}")

        # Log decrypted packet with special marker
        self._logger.info(
            f"[CASAMBI_DECRYPTED] Type={packetType} #{self._inPacketCount}: {b2a(decrypted_data)}"
        )

        if packetType == IncomingPacketType.UnitState:
            self._parseUnitStates(decrypted_data[1:])
        elif packetType == IncomingPacketType.SwitchEvent:
            for s in parseSwitchEvents(
                decrypted_data[1:], self._inPacketCount, raw_encrypted_packet
            ):
                self._dataCallback(IncomingPacketType.SwitchEvent, s)
        elif packetType == IncomingPacketType.NetworkConfig:
            # We don't care about the config the network thinks it has.
            # We assume that cloud config and local config match.
            # If there is a mismatch the user can solve it using the app.
            # In the future we might want to parse the revision and issue a warning if there is a mismatch.
            pass
        else:
            self._logger.info(f"Packet type {packetType} not implemented. Ignoring!")

    def _parseUnitStates(self, data: bytes) -> None:
        """Parse incoming unit states from notification data."""
        self._logger.info("Parsing incoming unit states...")
        self._logger.debug(f"Incoming unit state: {b2a(data)}")

        pos = 0
        oldPos = 0
        try:
            while pos <= len(data) - 4:
                id = data[pos]
                flags = data[pos + 1]
                stateLen = ((data[pos + 2] >> 4) & 15) + 1
                prio = data[pos + 2] & 15
                pos += 3

                online = flags & 2 != 0
                on = flags & 1 != 0

                if flags & 4:
                    pos += 1  # TODO: con?
                if flags & 8:
                    pos += 1  # TODO: sid?
                if flags & 16:
                    pos += 1  # Unknown value

                state = data[pos : pos + stateLen]
                pos += stateLen

                pos += (flags >> 6) & 3  # Padding?

                self._logger.debug(
                    f"Parsed state: Id {id}, prio {prio}, online {online}, on {on}, state {b2a(state)}1"
                )

                self._dataCallback(
                    IncomingPacketType.UnitState,
                    {"id": id, "online": online, "on": on, "state": state},
                )

                oldPos = pos
        except IndexError:
            self._logger.error(
                f"Ran out of data while parsing unit state! Remaining data {b2a(data[oldPos:])} in {b2a(data)}."
            )

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        self._logger.info("Disconnecting...")

        if self._callbackTask is not None:
            self._callbackTask.cancel()
            self._callbackTask = None

        if self._connection is not None:
            try:
                # Stop notifications first
                if self._connection.is_connected:
                    try:
                        await self._connection.stop_notify(CASA_AUTH_CHAR_UUID)
                    except Exception:
                        self._logger.debug("Failed to stop notifications.", exc_info=True)

                await self._connection.disconnect()
            except Exception:
                self._logger.error("Failed to disconnect transport.", exc_info=True)
            self._connection = None

        # Call disconnect callback if we were authenticated
        if self._connectionState == ConnectionState.AUTHENTICATED:
            self._disconnectedCallback()

        self._connectionState = ConnectionState.NONE
        self._logger.info("Disconnected.")
