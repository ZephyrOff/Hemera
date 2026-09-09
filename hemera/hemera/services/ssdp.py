"""SSDP/UPnP discovery (`M-SEARCH` responder + periodic `NOTIFY` broadcast).

Adapted from diyHue's BridgeEmulator/services/ssdp.py (Apache-2.0) — see
/NOTICE — rewritten on asyncio datagram transports instead of blocking
sockets in dedicated threads, to match the rest of this project's asyncio
event loop instead of spawning extra OS threads for it.
"""

from __future__ import annotations

import asyncio
import random
import socket
import struct

from hemera.logging_setup import get_logger

logging = get_logger(__name__)

_SSDP_ADDR = "239.255.255.250"
_SSDP_PORT = 1900
_NOTIFY_INTERVAL_S = 60.0


def _targets(mac: str) -> list[tuple[str, str]]:
    mac_plain = mac.replace(":", "").lower()
    device_uuid = f"2f402f80-da50-11e1-9b23-{mac_plain}"
    return [
        ("upnp:rootdevice", f"uuid:{device_uuid}::upnp:rootdevice"),
        (f"uuid:{device_uuid}", f"uuid:{device_uuid}"),
        ("urn:schemas-upnp-org:device:basic:1", f"uuid:{device_uuid}"),
    ]


def _headers(method_line: str, host_ip: str, port: int, bridge_id: str) -> str:
    return (
        f"{method_line}\r\n"
        f"HOST: {_SSDP_ADDR}:{_SSDP_PORT}\r\n"
        "CACHE-CONTROL: max-age=100\r\n"
        f"LOCATION: http://{host_ip}:{port}/description.xml\r\n"
        "SERVER: Linux/3.14.0 UPnP/1.0 IpBridge/1.20.0\r\n"
        f"hue-bridgeid: {bridge_id.upper()}\r\n"
    )


class _SearchResponder(asyncio.DatagramProtocol):
    def __init__(self, host_ip: str, port: int, mac: str, bridge_id: str) -> None:
        self.host_ip = host_ip
        self.port = port
        self.mac = mac
        self.bridge_id = bridge_id
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            return
        if text.startswith("M-SEARCH * HTTP/1.1") and "ssdp:discover" in text:
            asyncio.ensure_future(self._respond(addr))

    async def _respond(self, addr: tuple[str, int]) -> None:
        # Real UPnP devices jitter their reply to avoid flooding a busy multicast segment.
        await asyncio.sleep(random.uniform(0.1, 1.0))
        if self.transport is None:
            return
        logging.debug("Responding to SSDP M-SEARCH from %s", addr[0])
        header = _headers("HTTP/1.1 200 OK", self.host_ip, self.port, self.bridge_id) + "EXT:\r\n"
        for st, usn in _targets(self.mac):
            msg = f"{header}ST: {st}\r\nUSN: {usn}\r\n\r\n"
            self.transport.sendto(msg.encode("utf-8"), addr)


async def _notify_forever(host_ip: str, port: int, mac: str, bridge_id: str, stop: asyncio.Event) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack("b", 1))
    header = _headers("NOTIFY * HTTP/1.1", host_ip, port, bridge_id) + "NTS: ssdp:alive\r\n"
    try:
        while not stop.is_set():
            for nt, usn in _targets(mac):
                msg = f"{header}NT: {nt}\r\nUSN: {usn}\r\n\r\n"
                try:
                    sock.sendto(msg.encode("utf-8"), (_SSDP_ADDR, _SSDP_PORT))
                except OSError as exc:
                    logging.warning("SSDP NOTIFY send failed: %s", exc)
            try:
                await asyncio.wait_for(stop.wait(), timeout=_NOTIFY_INTERVAL_S)
            except TimeoutError:
                pass
    finally:
        sock.close()


class SsdpService:
    def __init__(self, host_ip: str, port: int, mac: str, bridge_id: str) -> None:
        self.host_ip = host_ip
        self.port = port
        self.mac = mac
        self.bridge_id = bridge_id
        self._transport: asyncio.DatagramTransport | None = None
        self._notify_task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", _SSDP_PORT))
        mreq = struct.pack("4sL", socket.inet_aton(_SSDP_ADDR), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.setblocking(False)

        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _SearchResponder(self.host_ip, self.port, self.mac, self.bridge_id), sock=sock
        )
        self._notify_task = asyncio.create_task(
            _notify_forever(self.host_ip, self.port, self.mac, self.bridge_id, self._stop), name="ssdp-notify"
        )
        logging.info("SSDP: listening for M-SEARCH and announcing on %s:%d", _SSDP_ADDR, _SSDP_PORT)

    async def stop(self) -> None:
        self._stop.set()
        if self._notify_task is not None:
            self._notify_task.cancel()
        if self._transport is not None:
            self._transport.close()
