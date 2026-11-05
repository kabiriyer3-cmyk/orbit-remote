"""LAN discovery: replies to ``ORBIT_DISCOVER_V1`` UDP broadcasts from the phone app."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

log = logging.getLogger("orbit.discovery")
QUERY = b"ORBIT_DISCOVER_V1"


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, info: Callable[[], dict]) -> None:
        self._info = info
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:  # type: ignore[override]
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        if data.strip() != QUERY or self.transport is None:
            return
        try:
            self.transport.sendto(json.dumps(self._info()).encode("utf-8"), addr)
        except OSError as exc:
            log.debug("discovery reply failed: %s", exc)


async def start_discovery(port: int, info: Callable[[], dict]):
    loop = asyncio.get_running_loop()
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _Protocol(info), local_addr=("0.0.0.0", port), allow_broadcast=True
        )
        log.info("discovery listening on udp/%s", port)
        return transport
    except OSError as exc:
        log.warning("discovery unavailable on udp/%s: %s", port, exc)
        return None
