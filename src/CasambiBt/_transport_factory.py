"""Transport factory for creating transport instances based on environment."""

import logging
import os
from typing import Any, Literal

from ._transport import BluetoothTransport

# Environment variables
_ESPHOME_IP: str | None = None
_ESPHOME_PORT: int = 6053
_ESPHOME_NOISE_PSK: str | None = None

_LOGGER = logging.getLogger(__name__)


def get_transport() -> BluetoothTransport:
    """Get the appropriate transport based on environment configuration.

    If ESPHOME_IP is set, use ESPHome transport.
    Otherwise, fall back to bleak.

    :return: A BluetoothTransport instance based on the environment.
    """
    global _ESPHOME_IP, _ESPHOME_PORT, _ESPHOME_NOISE_PSK

    # Check for cached environment variables (allows overriding after import)
    esphome_ip = os.environ.get("ESPHOME_IP") or _ESPHOME_IP
    esphome_port = int(os.environ.get("ESPHOME_PORT", _ESPHOME_PORT or "6053"))
    esphome_noise_psk = os.environ.get("ESPHOME_NOISE_PSK") or _ESPHOME_NOISE_PSK

    if esphome_ip:
        try:
            from ._esphome_transport import ESPHomeTransport

            return ESPHomeTransport(
                host=esphome_ip,
                port=esphome_port,
                noise_psk=esphome_noise_psk,
            )
        except ImportError:
            _LOGGER.warning(
                "ESPHOME_IP is set but aioesphomeapi is not installed. "
                "Falling back to bleak. Install with: pip install aioesphomeapi"
            )

    # Default to bleak
    from ._bleak_transport import BleakTransport

    return BleakTransport()


def get_transport_by_type(
    transport_type: Literal["bleak", "esphome", "homeassistant"],
    **kwargs: Any,
) -> BluetoothTransport:
    """Create a specific transport type with configuration.

    This function allows explicit selection of transport type and passes
    configuration via kwargs. Useful for applications that want to support
    multiple transport options.

    :param transport_type: The type of transport to create
        - "bleak": Local Bluetooth via bleak library (no config needed)
        - "esphome": ESPHome Bluetooth Proxy (needs host, optional port, noise_psk)
        - "homeassistant": Validates against Home Assistant, then connects
            directly to an ESPHome Bluetooth Proxy
            (needs host, token, esphome_host, optional port, esphome_port,
            ssl, esphome_entity, noise_psk)
    :param kwargs: Configuration parameters for the transport
    :return: A BluetoothTransport instance of the requested type
    :raises ImportError: If the required library for the transport is not installed
    :raises ValueError: If an invalid transport type is specified
    """
    normalized_type = transport_type.lower()

    if normalized_type == "bleak":
        from ._bleak_transport import BleakTransport
        return BleakTransport()

    elif normalized_type == "esphome":
        try:
            from ._esphome_transport import ESPHomeTransport
        except ImportError:
            raise ImportError(
                "aioesphomeapi is required for ESPHome transport. "
                "Install it with: pip install aioesphomeapi"
            )

        host = kwargs.get("host")
        port = int(kwargs.get("port", 6053))
        noise_psk = kwargs.get("noise_psk")

        if not host:
            raise ValueError("ESPHome transport requires 'host' parameter")

        return ESPHomeTransport(
            host=host,
            port=port,
            noise_psk=noise_psk,
        )

    elif normalized_type == "homeassistant":
        try:
            from ._homeassistant_transport import HomeAssistantTransport
        except ImportError:
            raise ImportError(
                "homeassistant-api is required for Home Assistant transport. "
                "Install it with: pip install homeassistant-api"
            )

        host = kwargs.get("host")
        port = int(kwargs.get("port", 8123))
        token = kwargs.get("token")
        ssl = kwargs.get("ssl", True)
        verify_ssl = kwargs.get("verify_ssl", True)
        esphome_host = kwargs.get("esphome_host")
        esphome_port = int(kwargs.get("esphome_port", 6053))
        esphome_entity = kwargs.get("esphome_entity")
        noise_psk = kwargs.get("noise_psk")

        if not host:
            raise ValueError("Home Assistant transport requires 'host' parameter")
        if not token:
            raise ValueError("Home Assistant transport requires 'token' parameter")
        if not esphome_host:
            raise ValueError("Home Assistant transport requires 'esphome_host' parameter")

        return HomeAssistantTransport(
            host=host,
            esphome_host=esphome_host,
            port=port,
            esphome_port=esphome_port,
            token=token,
            ssl=ssl,
            verify_ssl=verify_ssl,
            esphome_entity=esphome_entity,
            noise_psk=noise_psk,
        )

    else:
        raise ValueError(
            f"Unknown transport type: {transport_type}. "
            "Supported types: bleak, esphome, homeassistant"
        )
