"""Entertainment streaming engine: HueStream frames -> Zigbee2MQTT commands.

Design combines the tolerance-based dedup constants validated independently
by both 83noit/ha-hue-entertainment and diyHue (MIT / Apache-2.0 — see
/NOTICE) with a fixed-interval drain loop, NOT the "wait for the previous
command to finish" pacing either reference project used.

That adaptation is deliberate: 83noit's engine paces itself by awaiting each
blocking `hass.services.async_call` (naturally rate-limited by ZHA's real
throughput), and diyHue awaits nothing at all when publishing to MQTT
(fire-and-forget). Neither pattern is right for a persistent async MQTT
publish, which returns immediately with no per-command backpressure signal —
copying either would either add artificial latency or flood the Zigbee mesh.
Instead: incoming frames only ever update a per-light "latest colour" slot
(latest value wins, matching both reference engines), and a separate task
ticks at a fixed, configurable rate (`target_fps`) publishing whatever
slots are dirty — this is the "Rate Limiter" component called out explicitly
in the project's own framing document.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass, field

from hemera.functions.colors import convert_rgb_xy, convert_xy
from hemera.logging_setup import get_logger
from hemera.objects.entertainment_configuration import EntertainmentConfiguration
from hemera.services.entertainment.frame_parser import ChannelColor, COLOR_SPACE_XY, parse_huestream_frame

logging = get_logger(__name__)

CIE_TOLERANCE = 0.03  # validated independently by both reference projects
BRIGHTNESS_TOLERANCE = 16
DEFAULT_TARGET_FPS = 15  # "Zigbee can't do much more" — same conclusion in both reference projects
FRAME_TIMEOUT_S = 5.0  # auto-stop a session with no frames for this long (TV vanished uncleanly)


@dataclass
class _Segment:
    x: float = -1.0
    y: float = -1.0
    bri: int = -1  # 0-255
    last_sent_x: float = -1.0
    last_sent_y: float = -1.0
    last_sent_bri: int = -1


@dataclass
class _LightSlot:
    light: object
    total_segments: int
    command_topic: str
    segments: list[_Segment] = field(default_factory=list)
    dirty: bool = False

    def __post_init__(self) -> None:
        if not self.segments:
            self.segments = [_Segment() for _ in range(self.total_segments)]


def _rgb_to_xy_bri(r: int, g: int, b: int) -> tuple[float, float, int]:
    x, y = convert_rgb_xy(r / 255.0, g / 255.0, b / 255.0)
    return x, y, max(r, g, b)


class EntertainmentEngine:
    def __init__(self, mqtt_publish, target_fps: int = DEFAULT_TARGET_FPS) -> None:
        """``mqtt_publish``: async callable(topic, payload_str) — normally
        ``MqttClient.publish``, the persistent connection (never the one-shot
        publisher used for regular REST-triggered commands)."""
        self._mqtt_publish = mqtt_publish
        self._tick_interval = 1.0 / target_fps
        self._active_group: EntertainmentConfiguration | None = None
        self._slots: dict[str, _LightSlot] = {}  # keyed by light.id_v1
        self._channel_index: dict[int, tuple[str, int]] = {}  # channel_id -> (light.id_v1, segment_index)
        self._drain_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self.last_frame_time = 0.0
        self.frames_received = 0
        self.commands_sent = 0

    @property
    def is_active(self) -> bool:
        return self._active_group is not None

    @property
    def active_group_id(self) -> str | None:
        return self._active_group.id_v1 if self._active_group else None

    async def start_session(self, group: EntertainmentConfiguration) -> None:
        if self._active_group is not None and self._active_group is not group:
            logging.info("New Entertainment session (%s) pre-empts the previous one", group.name)
        self._active_group = group
        self._slots = {}
        self._channel_index = {}
        for channel_id, (light, segment_index, total_segments) in group.build_channel_map().items():
            slot = self._slots.get(light.id_v1)
            if slot is None:
                slot = _LightSlot(light=light, total_segments=total_segments, command_topic=light.protocol_cfg.get("command_topic", ""))
                self._slots[light.id_v1] = slot
            self._channel_index[channel_id] = (light.id_v1, segment_index)
            light.state["mode"] = "streaming"
        self.last_frame_time = time.monotonic()
        self.frames_received = 0
        self.commands_sent = 0
        if self._drain_task is None or self._drain_task.done():
            self._drain_task = asyncio.create_task(self._drain_loop(), name="entertainment-drain")
        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(self._watchdog_loop(), name="entertainment-watchdog")
        logging.info(
            "Entertainment session started: area=%s lights=%d channels=%d",
            group.name, len(self._slots), len(self._channel_index),
        )

    async def stop_session(self) -> None:
        if self._active_group is None:
            return
        for slot in self._slots.values():
            slot.light.state["mode"] = "homeautomation"
        logging.info(
            "Entertainment session stopped: area=%s, %d frames received, %d commands sent",
            self._active_group.name, self.frames_received, self.commands_sent,
        )
        self._active_group = None
        self._slots = {}
        self._channel_index = {}
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watchdog_task
            self._watchdog_task = None
        if self._drain_task is not None:
            self._drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._drain_task
            self._drain_task = None

    def handle_frame(self, data: bytes) -> None:
        """Callback for DTLSPSKServer — runs on the event loop (scheduled via
        call_soon_threadsafe from the DTLS thread), never blocks."""
        if self._active_group is None:
            return
        parsed = parse_huestream_frame(data)
        if parsed is None:
            return
        api_version, color_space, channels = parsed
        self.last_frame_time = time.monotonic()
        self.frames_received += 1
        for channel in channels:
            self._apply_channel(channel, color_space, api_version)

    def _apply_channel(self, channel: ChannelColor, color_space: int, api_version: int) -> None:
        if api_version == 2:
            target = self._channel_index.get(channel.channel_id)
            if target is None:
                return
            light_id, segment_index = target
        else:
            # v1 legacy HueStream: channel_id is the numeric v1 light id directly;
            # gradient per-segment addressing over v1 is not supported (see plan).
            light_id, segment_index = str(channel.channel_id), 0
            if light_id not in self._slots:
                return

        slot = self._slots[light_id]
        if segment_index >= len(slot.segments):
            return
        seg = slot.segments[segment_index]

        if color_space == COLOR_SPACE_XY:
            x = channel.r / 65535.0
            y = channel.g / 65535.0
            bri = round(channel.b / 65535 * 255)
        else:
            r, g, b = channel.r >> 8, channel.g >> 8, channel.b >> 8
            x, y, bri = _rgb_to_xy_bri(r, g, b)

        if (
            abs(x - seg.last_sent_x) < CIE_TOLERANCE
            and abs(y - seg.last_sent_y) < CIE_TOLERANCE
            and abs(bri - seg.last_sent_bri) < BRIGHTNESS_TOLERANCE
        ):
            return
        seg.x, seg.y, seg.bri = x, y, bri
        slot.dirty = True

    async def _watchdog_loop(self) -> None:
        try:
            while self._active_group is not None:
                await asyncio.sleep(1.0)
                if self._active_group is None:
                    break
                if time.monotonic() - self.last_frame_time > FRAME_TIMEOUT_S:
                    logging.warning("No Entertainment frames for %.0fs, auto-stopping session", FRAME_TIMEOUT_S)
                    group = self._active_group
                    await self.stop_session()
                    if group is not None:
                        group.stream["active"] = False
                        group.stream["owner"] = None
                    break
        except asyncio.CancelledError:
            pass

    async def _drain_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._tick_interval)
                for slot in self._slots.values():
                    if not slot.dirty:
                        continue
                    slot.dirty = False
                    await self._publish_slot(slot)
        except asyncio.CancelledError:
            pass

    async def _publish_slot(self, slot: _LightSlot) -> None:
        if slot.total_segments > 1:
            hexes = []
            for seg in slot.segments:
                if seg.x < 0:  # never received a frame for this segment yet
                    hexes.append("#000000")
                    continue
                r, g, b = convert_xy(seg.x, seg.y, seg.bri)
                hexes.append(f"#{r:02x}{g:02x}{b:02x}")
                seg.last_sent_x, seg.last_sent_y, seg.last_sent_bri = seg.x, seg.y, seg.bri
            payload = json.dumps({"gradient": hexes, "transition": 0})
        else:
            seg = slot.segments[0]
            if seg.x < 0:
                return
            payload = json.dumps({
                "state": "ON",
                "color": {"x": seg.x, "y": seg.y},
                "brightness": seg.bri,
                "transition": 0,
            })
            seg.last_sent_x, seg.last_sent_y, seg.last_sent_bri = seg.x, seg.y, seg.bri

        if slot.command_topic:
            await self._mqtt_publish(slot.command_topic, payload)
            self.commands_sent += 1
