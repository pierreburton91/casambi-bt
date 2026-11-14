"""Tests for how CasambiClient handles the transport reporting a lost link.

Regression coverage: the transport refactor stopped passing any disconnect
callback to the BLE stack, so a link lost outside of disconnect() left the
client AUTHENTICATED on a dead connection and no reconnect was ever triggered.
"""

import asyncio
import contextlib
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

import bleak_retry_connector
import pytest
from bleak.backends.device import BLEDevice

from CasambiBt._bleak_transport import BleakTransport
from CasambiBt._client import CasambiClient
from CasambiBt._constants import MIN_VERSION, ConnectionState
from CasambiBt._network import Network
from CasambiBt._transport import BluetoothTransport, TransportConnection
from CasambiBt.errors import BluetoothError

_ADDRESS = "AA:BB:CC:DD:EE:FF"


class _FakeConnection(TransportConnection):
    def __init__(self, transport: "_FakeTransport") -> None:
        self._transport = transport
        self.connected = True

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def disconnect(self) -> None:
        # Like bleak, report an intentional disconnect through the same callback.
        self.connected = False
        self._transport.drop_link()

    async def read_gatt_char(self, char_uuid: str) -> bytes:
        raise NotImplementedError

    async def write_gatt_char(self, char_uuid: str, data: bytes) -> None:
        raise NotImplementedError

    async def start_notify(
        self, char_uuid: str, callback: Callable[[bytes], None]
    ) -> None:
        raise NotImplementedError

    async def stop_notify(self, char_uuid: str) -> None:
        pass


class _FakeTransport(BluetoothTransport):
    def __init__(self) -> None:
        self.disconnected_callback: Callable[[], None] | None = None

    async def discover(self, timeout: float = 10.0) -> list[BLEDevice]:
        return []

    async def connect(
        self,
        device: BLEDevice,
        disconnected_callback: Callable[[], None] | None = None,
    ) -> _FakeConnection:
        self.disconnected_callback = disconnected_callback
        return _FakeConnection(self)

    def drop_link(self) -> None:
        assert self.disconnected_callback is not None
        self.disconnected_callback()


async def _connected_client(
    state: ConnectionState,
) -> tuple[CasambiClient, _FakeTransport, list[str]]:
    transport = _FakeTransport()
    disconnects: list[str] = []
    network = cast(Network, SimpleNamespace(protocolVersion=MIN_VERSION))
    client = CasambiClient(
        _ADDRESS,
        lambda *_: None,
        lambda: disconnects.append("disconnected"),
        network,
        transport=transport,
    )
    await client.connect()
    # The key exchange needs a real device; jump to the state it would reach.
    client._connectionState = state
    return client, transport, disconnects


async def _wait_cancelled(task: asyncio.Task[None] | None) -> None:
    assert task is not None
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert task.cancelled()


def test_lost_link_reports_disconnect_once() -> None:
    """A link lost while authenticated is reported once and stops the reader."""

    async def scenario() -> None:
        client, transport, disconnects = await _connected_client(
            ConnectionState.AUTHENTICATED
        )
        callback_task = client._callbackTask

        transport.drop_link()

        assert disconnects == ["disconnected"]
        assert client._connectionState == ConnectionState.NONE
        await _wait_cancelled(callback_task)

        # A duplicate notification for the same loss is ignored.
        transport.drop_link()
        assert disconnects == ["disconnected"]

    asyncio.run(scenario())


def test_lost_link_during_handshake_does_not_report_disconnect() -> None:
    """A link lost mid-handshake resets the state without reporting a disconnect."""

    async def scenario() -> None:
        client, transport, disconnects = await _connected_client(
            ConnectionState.CONNECTED
        )
        callback_task = client._callbackTask

        transport.drop_link()

        assert disconnects == []
        assert client._connectionState == ConnectionState.NONE
        await _wait_cancelled(callback_task)

    asyncio.run(scenario())


def test_intentional_disconnect_reports_disconnect_once() -> None:
    """disconnect() reports once even though the transport also signals it."""

    async def scenario() -> None:
        client, _transport, disconnects = await _connected_client(
            ConnectionState.AUTHENTICATED
        )

        # _FakeConnection.disconnect() also fires the transport callback.
        await client.disconnect()

        assert disconnects == ["disconnected"]
        assert client._connectionState == ConnectionState.NONE

    asyncio.run(scenario())


def test_failed_connect_cancels_callback_task() -> None:
    """A failed transport connect doesn't leave the reader task pending."""

    class FailingTransport(_FakeTransport):
        async def connect(
            self,
            device: BLEDevice,
            disconnected_callback: Callable[[], None] | None = None,
        ) -> _FakeConnection:
            raise OSError("adapter unavailable")

    async def scenario() -> None:
        network = cast(Network, SimpleNamespace(protocolVersion=MIN_VERSION))
        client = CasambiClient(
            _ADDRESS,
            lambda *_: None,
            lambda: None,
            network,
            transport=FailingTransport(),
        )
        with pytest.raises(BluetoothError):
            await client.connect()
        assert client._callbackTask is None

    asyncio.run(scenario())


def test_bleak_transport_forwards_disconnects(monkeypatch: pytest.MonkeyPatch) -> None:
    """BleakTransport passes a disconnect callback down to the BLE stack."""

    captured: dict[str, Any] = {}

    async def fake_close_stale_connections(device: BLEDevice) -> None:
        return None

    async def fake_establish_connection(
        client_class: Any,
        device: BLEDevice,
        name: str,
        disconnected_callback: Callable[[Any], None] | None = None,
        **kwargs: Any,
    ) -> Any:
        captured["disconnected_callback"] = disconnected_callback
        return SimpleNamespace(is_connected=True)

    monkeypatch.setattr(
        bleak_retry_connector, "close_stale_connections", fake_close_stale_connections
    )
    monkeypatch.setattr(
        bleak_retry_connector, "establish_connection", fake_establish_connection
    )

    calls: list[str] = []
    device = BLEDevice(_ADDRESS, None, {})
    asyncio.run(BleakTransport().connect(device, lambda: calls.append("lost")))

    forwarded = captured["disconnected_callback"]
    assert forwarded is not None
    forwarded(object())  # bleak passes the BleakClient that disconnected

    assert calls == ["lost"]
