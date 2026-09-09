"""Zigbee2MQTT light backend — the only protocol this project supports.

Adapted from diyHue's BridgeEmulator/lights/protocols/mqtt.py (Apache-2.0)
— see /NOTICE. Publishes one-shot commands via ``paho.mqtt.publish`` (a
short-lived connect/publish/disconnect per call, same as diyHue) — simple
and adequate for REST-triggered commands from the Hue app. High-frequency
Entertainment streaming uses a separate persistent async client
(hemera.services.entertainment), never this module.
"""

from __future__ import annotations

import json

import paho.mqtt.publish as publish

from hemera.functions.colors import convert_xy, hsv_to_rgb
from hemera.logging_setup import get_logger

logging = get_logger(__name__)


def set_light(light, data: dict) -> None:
    """Translate a Hue v1 state dict (or a {"lights": {topic: state}} batch) to Z2M `set` messages."""
    if "lights" not in data:
        lights_data = {light.protocol_cfg["command_topic"]: data}
    else:
        lights_data = data["lights"]

    messages = []
    for topic, state in lights_data.items():
        payload: dict = {"transition": 0.3}
        color_from_hsv = False
        for key, value in state.items():
            if key == "on":
                payload["state"] = "ON" if value else "OFF"
            elif key == "bri":
                payload["brightness"] = value
            elif key == "xy":
                payload["color"] = {"x": value[0], "y": value[1]}
            elif key == "gradient":
                rgbs = [convert_xy(p["color"]["xy"]["x"], p["color"]["xy"]["y"], 255) for p in value["points"]]
                hexes = ["#" + "".join(f"{int(round(c)):02x}" for c in rgb) for rgb in rgbs]
                hexes.reverse()
                payload["gradient"] = hexes
            elif key == "ct":
                payload["color_temp"] = value
            elif key in ("hue", "sat"):
                color_from_hsv = True
            elif key == "alert" and value != "none":
                payload["alert"] = value
            elif key == "transitiontime":
                payload["transition"] = value / 10
            elif key == "effect":
                payload["effect"] = value
        if color_from_hsv:
            r, g, b = hsv_to_rgb(state.get("hue", 0), state.get("sat", 254), light.state.get("bri", 254))
            payload["color"] = {"r": r, "g": g, "b": b}
        messages.append({"topic": topic, "payload": json.dumps(payload)})

    logging.debug("MQTT publish: %s", messages)
    mqtt_cfg = light.protocol_cfg["mqtt_server"]
    auth = None
    if mqtt_cfg.get("mqttUser") and mqtt_cfg.get("mqttPassword"):
        auth = {"username": mqtt_cfg["mqttUser"], "password": mqtt_cfg["mqttPassword"]}
    publish.multiple(messages, hostname=mqtt_cfg["mqttServer"], port=mqtt_cfg["mqttPort"], auth=auth)


def get_light_state(light) -> dict:
    return {}
