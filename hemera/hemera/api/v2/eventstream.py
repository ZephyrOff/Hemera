"""CLIP v2 Server-Sent-Events stream (`GET /eventstream/clip/v2`).

Conceptually adapted from diyHue's BridgeEmulator/services/eventStreamer.py
(Apache-2.0, see /NOTICE), but each connection tracks its own read cursor
into the shared ``hemera.objects.eventstream`` list instead of every
connected client re-reading from index 0 on every tick — the original
approach could deliver the same message twice to one client. A background
task caps the list's size so it cannot grow unboundedly when no client is
connected to drain it.

Supports the standard SSE auto-reconnect protocol (``Last-Event-ID``
request header, matching Bifrost's routes/eventstream.rs, proven against
the real Hue app) — added after real-world testing showed that without it,
a light's state change made from outside the app (Zigbee2MQTT, an
automation, a physical switch) never reached the app until it was fully
relaunched. The eventstream push itself (see mqtt_client.py) was necessary
but not sufficient: whenever the app's connection dropped for any reason —
a mobile OS suspending background network access being the big one — its
automatic reconnect carried no way to ask "what did I miss", so every event
published during the gap was silently lost forever, indistinguishable from
the push never having happened at all.
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


def _latest_seq() -> int:
    return eventstream[-1][0] if eventstream else 0


async def stream_v2_events(request: web.Request) -> web.StreamResponse:
    response = web.StreamResponse(
        status=200,
        headers={"Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache"},
    )
    await response.prepare(request)
    await response.write(b": hi\n\n")

    last_event_id = request.headers.get("Last-Event-ID")
    if last_event_id is not None:
        try:
            cursor_seq = int(last_event_id)
        except ValueError:
            cursor_seq = _latest_seq()
    else:
        # First-ever connection from this client — nothing to catch up on,
        # start live-only (matches the real bridge: no reason to dump
        # unrelated history to someone who's never connected before).
        cursor_seq = _latest_seq()

    last_activity = time.monotonic()
    try:
        while True:
            # A plain seq > cursor_seq filter over whatever's currently in
            # the list (rather than tracking a list *index*) stays correct
            # even if trim_eventstream_forever has removed older entries out
            # from under this connection — and it's what makes the
            # Last-Event-ID case above just work: it's the exact same
            # "resume from here" logic, whether resuming from a fresh
            # reconnect or from the last tick.
            pending = [(seq, message) for seq, message in eventstream if seq > cursor_seq]
            if pending:
                for seq, message in pending:
                    chunk = f"id: {seq}\ndata: {json.dumps([message], separators=(',', ':'))}\n\n"
                    await response.write(chunk.encode("utf-8"))
                    cursor_seq = seq
                last_activity = time.monotonic()
            elif time.monotonic() - last_activity >= _HEARTBEAT_INTERVAL_S:
                await response.write(b": hue-bridge-heartbeat\n\n")
                last_activity = time.monotonic()
            await asyncio.sleep(_POLL_INTERVAL_S)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return response
