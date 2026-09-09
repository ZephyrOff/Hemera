"""CLIP v2 Server-Sent-Events stream (`GET /eventstream/clip/v2`).

Conceptually adapted from diyHue's BridgeEmulator/services/eventStreamer.py
(Apache-2.0, see /NOTICE), but each connection tracks its own read cursor
into the shared ``hemera.objects.eventstream`` list instead of every
connected client re-reading from index 0 on every tick — the original
approach could deliver the same message twice to one client. A background
task caps the list's size so it cannot grow unboundedly when no client is
connected to drain it.
"""

from __future__ import annotations

import asyncio
import json
import time

from aiohttp import web

from hemera.logging_setup import get_logger
from hemera.objects import eventstream

logging = get_logger(__name__)

_POLL_INTERVAL_S = 0.2
_HEARTBEAT_INTERVAL_S = 15.0
_MAX_BACKLOG = 2000


async def trim_eventstream_forever(stop: asyncio.Event) -> None:
    """Keep the shared eventstream list from growing unboundedly if nobody is listening."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=30.0)
        except TimeoutError:
            pass
        if len(eventstream) > _MAX_BACKLOG:
            del eventstream[: len(eventstream) - _MAX_BACKLOG]


async def stream_v2_events(request: web.Request) -> web.StreamResponse:
    response = web.StreamResponse(
        status=200,
        headers={"Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache"},
    )
    await response.prepare(request)
    await response.write(b": hi\n\n")

    cursor = len(eventstream)  # live updates only, matching the real bridge — no backlog replay
    counter = 0
    last_activity = time.monotonic()
    try:
        while True:
            current_len = len(eventstream)
            if current_len < cursor:
                cursor = 0  # list was trimmed/cleared underneath us — resync
            if current_len > cursor:
                new_messages = eventstream[cursor:current_len]
                cursor = current_len
                for message in new_messages:
                    chunk = f"id: {counter}\ndata: {json.dumps([message], separators=(',', ':'))}\n\n"
                    await response.write(chunk.encode("utf-8"))
                    counter += 1
                last_activity = time.monotonic()
            elif time.monotonic() - last_activity >= _HEARTBEAT_INTERVAL_S:
                await response.write(b": hue-bridge-heartbeat\n\n")
                last_activity = time.monotonic()
            await asyncio.sleep(_POLL_INTERVAL_S)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return response
