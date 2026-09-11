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
from hemera.functions.gradient import colors_to_stops, hex_to_rgb_obj, resample_stops
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
                if light.modelid == "AQARA_GRADIENT":
                    # Aqara's LED Strip T1 (and similar) has no native "gradient"
                    # Z2M feature, and — unlike real Hue gradient hardware — no
                    # onboard interpolation between segments either: every
                    # physical segment needs its own explicit colour. The Hue
                    # app's gradient editor appears to cap out at far fewer
                    # colour points than these strips actually have segments
                    # for (observed directly: a 10-segment strip, 3 colour
                    # points from the app), so forwarding the app's points 1:1
                    # as `segment_colors` only ever lit the first few segments,
                    # leaving the rest showing whatever they last displayed.
                    # Resampling however many points the app sent across the
                    # strip's real segment count (points_capable, kept in sync
                    # with Z2M's own reported length — see
                    # mqtt_client.py's _sync_aqara_segment_count) reproduces
                    # what alex_light_studio does for the same real hardware:
                    # a smooth gradient computed bridge-side, since the device
                    # itself will never do it. Real Hue-format gradients (the
                    # `else` branch below) don't need this — genuine Hue driver
                    # silicon does its own onboard interpolation.
                    hexes = ["#" + "".join(f"{int(round(c)):02x}" for c in rgb) for rgb in rgbs]
                    target_segments = light.protocol_cfg.get("points_capable", len(hexes))
                    resampled = resample_stops(colors_to_stops(hexes), target_segments)
                    payload["segment_colors"] = [
                        {"segment": i + 1, "color": hex_to_rgb_obj(hex_color)}
                        for i, hex_color in enumerate(resampled)
                    ]
                else:
                    # Real Hue Gradient Lightstrips, and non-Hue strips faked as
                    # one (e.g. "HUE_UNSUPPORTED_GRADIENT") that Z2M still
                    # exposes via the same flat-hex-array "gradient" property.
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
