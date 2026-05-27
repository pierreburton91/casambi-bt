"""Transport factory for creating transport instances based on environment."""

import logging
import os

from ._transport import BluetoothTransport

# Environment variables
_ESPHOME_IP: str | None = None
_ESPHOME_PORT: int = 6053
_ESPHOME_NOISE_PSK: str | None = None


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
            logging.getLogger(__name__).warning(
                "ESPHOME_IP is set but aioesphomeapi is not installed. "
                "Falling back to bleak. Install with: pip install aioesphomeapi"
            )

    # Default to bleak
    from ._bleak_transport import BleakTransport

    return BleakTransport()
