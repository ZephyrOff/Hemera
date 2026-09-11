"""Persistent Zigbee2MQTT connection: auto-discovers lights from Z2M's own
device list and keeps their reported state in sync.

Conceptually adapted from diyHue's BridgeEmulator/services/mqtt.py
(Apache-2.0, see /NOTICE) but re-targeted at Zigbee2MQTT's *native*
``<base_topic>/bridge/devices`` payload (with its ``definition.exposes``
capability descriptors) instead of diyHue's reliance on Home Assistant MQTT
discovery topics — this way autodiscovery works whether or not the user has
Z2M's optional Home Assistant integration toggle enabled, since Z2M always
publishes its own device list.

Runs as a persistent ``aiomqtt`` client (asyncio-native) with its own
reconnect loop — separate from the one-shot ``paho.mqtt.publish`` calls used
by hemera.lights.protocols.mqtt for outgoing commands, and from the
high-rate Entertainment publisher added in a later step.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import aiomqtt

from hemera.config.handler import Config
from hemera.lights.discover import add_new_light
from hemera.logging_setup import get_logger
from hemera.objects import v1_state_to_v2

logging = get_logger(__name__)

_RECONNECT_INTERVAL_S = 5.0


# Real Hue Gradient Lightstrips advertise 7 via their own `gradient.points_capable`
# — used only as a fallback for Z2M devices whose `gradient` expose doesn't carry
# its own `length_max` (see _pick_gradient_length_max below).
_DEFAULT_GRADIENT_POINTS = 7


def _pick_modelid(exposes: list[dict]) -> str | None:
    """Best-effort mapping from a Z2M device's `exposes` to a Hue modelid template.

    Z2M's expose schema has shifted across versions (``color_xy`` vs a
    composite ``color`` feature, etc.) — this covers the common shapes; a
    device that doesn't look like a light returns None.
    """
    has_gradient = False
    has_xy = False
    has_ct = False
    has_bri = False
    is_light = False

    def walk(expose: dict) -> None:
        nonlocal has_gradient, has_xy, has_ct, has_bri, is_light
        prop = expose.get("property")
        if expose.get("type") == "light":
            is_light = True
        if prop == "gradient":
            has_gradient = True
        elif prop in ("color_xy", "color"):
            has_xy = True
        elif prop == "color_temp":
            has_ct = True
        elif prop == "brightness":
            has_bri = True
        for sub in expose.get("features", []) or []:
            walk(sub)

    for expose in exposes or []:
        walk(expose)

    if not (is_light or has_xy or has_ct or has_bri or has_gradient):
        return None
    if has_gradient:
        return "LCX004"
    if has_xy and has_ct:
        return "LCT015"
    if has_xy:
        return "LLC010"
    if has_ct:
        return "LTW001"
    if has_bri:
        return "LWB010"
    return "LOM001"


def _pick_gradient_length_max(exposes: list[dict]) -> int:
    """Real max gradient stop count reported by Z2M's own `gradient` expose
    (``length_max`` on its ``list``-type expose — zigbee-herdsman-converters'
    actual schema for gradient-capable lights), rather than a single hardcoded
    number for every device.

    Different gradient-capable Zigbee lights genuinely support different stop
    counts (the official Hue Gradient Lightstrip caps at 7; some third-party
    RGBIC strips exposed as "gradient" through Z2M support more or fewer) —
    hardcoding 7 for all of them either falsely under- or over-advertises a
    given device's real capability to the Hue app. Falls back to Hue's own
    documented 7 only when Z2M doesn't report a length_max at all.
    """

    def walk(expose: dict) -> int | None:
        if expose.get("property") == "gradient" and "length_max" in expose:
            try:
                return int(expose["length_max"])
            except (TypeError, ValueError):
                return None
        for sub in expose.get("features", []) or []:
            found = walk(sub)
            if found is not None:
                return found
        return None

    for expose in exposes or []:
        found = walk(expose)
        if found is not None and found > 0:
            return found
    return _DEFAULT_GRADIENT_POINTS


class MqttClient:
    def __init__(self, bridge_config: Config, host: str, port: int, user: str, password: str, base_topic: str) -> None:
        self.cfg = bridge_config
        self.host = host
        self.port = port
        self.user = user or None
        self.password = password or None
        self.base_topic = base_topic
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._client: aiomqtt.Client | None = None
        self._last_devices_payload: list[dict] | None = None

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def reconfigure(self, host: str, port: int, user: str, password: str, base_topic: str) -> None:
        """Apply new connection settings from the admin panel and reconnect.
        Safe to call while running — stops the current connection (if any)
        and starts a fresh one with the new parameters."""
        await self.stop()
        self.host = host
        self.port = port
        self.user = user or None
        self.password = password or None
        self.base_topic = base_topic
        self._stop = asyncio.Event()
        self.start()

    def resync_devices(self) -> None:
        """Re-run device sync against the last `bridge/devices` payload seen —
        used after un-excluding a device so it reappears immediately instead
        of waiting for Z2M to publish its (retained, rarely-repeated) device
        list again."""
        if self._last_devices_payload is not None:
            self._sync_devices(self._last_devices_payload)

    async def publish(self, topic: str, payload: str) -> None:
        """Publish on the persistent connection (used by the Entertainment engine
        for high-frequency streaming — never opens a new connection per call,
        unlike bridge.lights.protocols.mqtt's one-shot publish for REST commands).
        Silently drops the message if not currently connected — for a live
        Entertainment stream, a dropped frame during a broker hiccup is
        preferable to blocking or buffering stale colour data.
        """
        if self._client is None:
            return
        try:
            await self._client.publish(topic, payload)
        except aiomqtt.MqttError:
            pass

    def start(self) -> None:
        self._task = asyncio.create_task(self._run_forever(), name="mqtt-client")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                async with aiomqtt.Client(
                    hostname=self.host, port=self.port, username=self.user, password=self.password
                ) as client:
                    logging.info("Connected to MQTT broker %s:%d", self.host, self.port)
                    self._client = client
                    await client.subscribe(f"{self.base_topic}/bridge/devices")
                    await client.subscribe(f"{self.base_topic}/+")
                    async for message in client.messages:
                        self._handle_message(str(message.topic), message.payload)
            except aiomqtt.MqttError as exc:
                if self._stop.is_set():
                    break
                logging.warning("MQTT connection lost (%s); reconnecting in %.0fs", exc, _RECONNECT_INTERVAL_S)
                await asyncio.sleep(_RECONNECT_INTERVAL_S)
            finally:
                self._client = None

    def _handle_message(self, topic: str, payload: bytes) -> None:
        try:
            data = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            return
        try:
            if topic == f"{self.base_topic}/bridge/devices":
                self._sync_devices(data)
            elif topic.startswith(f"{self.base_topic}/") and "/" not in topic[len(self.base_topic) + 1:]:
                friendly_name = topic[len(self.base_topic) + 1:]
                self._update_light_state(friendly_name, data)
        except Exception:  # noqa: BLE001 — one bad message must not kill the client loop
            logging.exception("Error handling MQTT message on %s", topic)

    def _find_light_by_ieee(self, ieee_address: str):
        for light in self.cfg.yaml_config["lights"].values():
            if light.protocol == "mqtt" and light.protocol_cfg.get("ieee_address") == ieee_address:
                return light
        return None

    def _sync_devices(self, devices: list[dict]) -> None:
        self._last_devices_payload = devices
        excluded = self.cfg.yaml_config["config"].get("excluded_devices", {})
        for device in devices:
            if device.get("type") != "Router" and device.get("type") != "EndDevice":
                continue
            ieee = device.get("ieee_address")
            friendly_name = device.get("friendly_name")
            if not ieee or not friendly_name:
                continue
            if ieee in excluded:
                continue
            exposes = (device.get("definition") or {}).get("exposes", [])
            existing = self._find_light_by_ieee(ieee)
            if existing is not None:
                # Friendly name may have been renamed in Z2M — keep our command topic in sync.
                if existing.protocol_cfg.get("friendly_name") != friendly_name:
                    existing.protocol_cfg["friendly_name"] = friendly_name
                    existing.protocol_cfg["command_topic"] = f"{self.base_topic}/{friendly_name}/set"
                    self.cfg.mark_dirty("lights")
                # Re-derive the real gradient stop count too — lights discovered
                # before this device-reported length_max was read (or before
                # Z2M itself started reporting it) were stuck on the old
                # hardcoded default forever, since this branch previously
                # returned before ever looking at it again. Skipped once the
                # admin panel has set this manually (see admin/routes.py's
                # h_set_gradient_points) — otherwise the next device-list
                # refresh would silently revert that override.
                if existing.modelid == "LCX004" and not existing.protocol_cfg.get("points_capable_manual"):
                    real_points = _pick_gradient_length_max(exposes)
                    if existing.protocol_cfg.get("points_capable") != real_points:
                        existing.protocol_cfg["points_capable"] = real_points
                        self.cfg.mark_dirty("lights")
                continue

            modelid = _pick_modelid(exposes)
            if modelid is None:
                continue  # not a light (a sensor/switch — handled in a later step)

            protocol_cfg = {
                "ieee_address": ieee,
                "friendly_name": friendly_name,
                "ip": "mqtt",
                "command_topic": f"{self.base_topic}/{friendly_name}/set",
                "state_topic": f"{self.base_topic}/{friendly_name}",
                "mqtt_server": {
                    "mqttServer": self.host, "mqttPort": self.port,
                    "mqttUser": self.user or "", "mqttPassword": self.password or "",
                },
            }
            if modelid == "LCX004":
                protocol_cfg["points_capable"] = _pick_gradient_length_max(exposes)
            add_new_light(self.cfg, modelid, friendly_name, "mqtt", protocol_cfg)

    def _update_light_state(self, friendly_name: str, data: dict) -> None:
        light = None
        for candidate in self.cfg.yaml_config["lights"].values():
            if candidate.protocol == "mqtt" and candidate.protocol_cfg.get("friendly_name") == friendly_name:
                light = candidate
                break
        if light is None:
            return

        state: dict = {"reachable": True}
        if "state" in data:
            state["on"] = data["state"] == "ON"
        if "brightness" in data:
            state["bri"] = data["brightness"]
        if "color_temp" in data:
            state["ct"] = data["color_temp"]
            state["colormode"] = "ct"
        color = data.get("color")
        if isinstance(color, dict) and "x" in color and "y" in color:
            state["xy"] = [color["x"], color["y"]]
            state["colormode"] = "xy"
        light.state.update(state)

        # Without this, a state change coming from Z2M (a physical switch, an
        # automation, another controller) never reaches the Hue app: it only
        # ever learns about light state through the v2 CLIP eventstream (SSE)
        # — GET requests do return the correct live state, but the app relies
        # on push notifications for its normal UI, not polling. This left it
        # showing whatever it last saw at pairing/last-open time regardless of
        # what actually happened afterwards. `v1_state_to_v2` only returns the
        # fields actually present in this Z2M message, so a message that
        # changed nothing display-relevant (e.g. just `linkquality`) pushes
        # nothing rather than spamming empty events.
        v2_state = v1_state_to_v2(state)
        if v2_state:
            logging.info("MQTT state change for %s -> pushing eventstream update: %s", friendly_name, v2_state)
            light.genStreamEvent(v2_state)
