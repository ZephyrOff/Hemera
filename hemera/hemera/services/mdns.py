"""mDNS advertisement (_hue._tcp.local) so the Hue app / Sync Box can find us.

Adapted from 83noit/ha-hue-entertainment's discovery.py (MIT, see /NOTICE),
using a standalone ``AsyncZeroconf()`` instance instead of Home Assistant's
shared one.
"""

from __future__ import annotations

import socket

from zeroconf import IPVersion
from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf

from hemera.logging_setup import get_logger

logging = get_logger(__name__)


class MdnsAdvertiser:
    def __init__(self, bridge_id: str, host_ip: str, port: int) -> None:
        self._bridge_id = bridge_id
        self._host_ip = host_ip
        self._port = port
        self._zeroconf: AsyncZeroconf | None = None
        self._service_info: AsyncServiceInfo | None = None

    async def start(self) -> None:
        self._zeroconf = AsyncZeroconf(ip_version=IPVersion.V4Only)
        last6 = self._bridge_id[-6:].upper()
        service_name = f"Philips Hue - {last6}._hue._tcp.local."
        self._service_info = AsyncServiceInfo(
            type_="_hue._tcp.local.",
            name=service_name,
            addresses=[socket.inet_aton(self._host_ip)],
            port=self._port,
            properties={"bridgeid": self._bridge_id.upper(), "modelid": "BSB002"},
            server=f"hahb-{last6.lower()}.local.",
        )
        await self._zeroconf.async_register_service(self._service_info)
        logging.info("mDNS: advertising %s at %s:%d", service_name, self._host_ip, self._port)

    async def stop(self) -> None:
        if self._zeroconf and self._service_info:
            await self._zeroconf.async_unregister_service(self._service_info)
            await self._zeroconf.async_close()
            logging.info("mDNS: service unregistered")
