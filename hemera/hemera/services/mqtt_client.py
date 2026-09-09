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

logging = get_logger(__name__)

_RECONNECT_INTERVAL_S = 5.0


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
                    await client.subscribe(f"{self.base_topic}/bridge/devices")
                    await client.subscribe(f"{self.base_topic}/+")
                    async for message in client.messages:
                        self._handle_message(str(message.topic), message.payload)
            except aiomqtt.MqttError as exc:
                if self._stop.is_set():
                    break
                logging.warning("MQTT connection lost (%s); reconnecting in %.0fs", exc, _RECONNECT_INTERVAL_S)
                await asyncio.sleep(_RECONNECT_INTERVAL_S)

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
        for device in devices:
            if device.get("type") != "Router" and device.get("type") != "EndDevice":
                continue
            ieee = device.get("ieee_address")
            friendly_name = device.get("friendly_name")
            if not ieee or not friendly_name:
                continue
            existing = self._find_light_by_ieee(ieee)
            if existing is not None:
                # Friendly name may have been renamed in Z2M — keep our command topic in sync.
                if existing.protocol_cfg.get("friendly_name") != friendly_name:
                    existing.protocol_cfg["friendly_name"] = friendly_name
                    existing.protocol_cfg["command_topic"] = f"{self.base_topic}/{friendly_name}/set"
                    self.cfg.mark_dirty("lights")
                continue

            exposes = (device.get("definition") or {}).get("exposes", [])
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
                protocol_cfg["points_capable"] = 7
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
