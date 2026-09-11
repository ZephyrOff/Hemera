"""Home Assistant light backend — for light entities that come from other
Home Assistant integrations (WLED, Tuya, ESPHome, a different Hue
integration, ...) rather than Zigbee2MQTT. Discovery and state sync live in
hemera.services.ha_client; this module only translates outgoing Hue v1
commands into Home Assistant `light.turn_on`/`turn_off` service calls.

Uses a plain synchronous HTTP request (stdlib ``urllib``), matching
hemera.lights.protocols.mqtt's use of a blocking one-shot publish for the
same reason: ``Light.setV1State`` calls a protocol's ``set_light`` as a
plain (non-async) function from inside an aiohttp request handler, so this
briefly blocks the event loop either way — adding aiohttp's async client
here wouldn't avoid that without a larger restructure, and a single HTTP
request is short-lived enough that diyHue/this project already accepts the
same tradeoff for MQTT.
"""

from __future__ import annotations

import json
import urllib.request

from hemera.logging_setup import get_logger

logging = get_logger(__name__)

_TIMEOUT_S = 5.0


def _call_service(light, service: str, service_data: dict) -> None:
    ha_cfg = light.protocol_cfg["ha_server"]
    url = f"{ha_cfg['baseUrl']}/services/light/{service}"
    body = json.dumps(service_data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Authorization": f"Bearer {ha_cfg['token']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        resp.read()


def set_light(light, data: dict) -> None:
    """Translate a Hue v1 state dict (or a {"lights": {entity_id: state}} batch)
    into Home Assistant `light.turn_on`/`turn_off` service calls."""
    if "lights" not in data:
        lights_data = {light.protocol_cfg["entity_id"]: data}
    else:
        lights_data = data["lights"]

    for entity_id, state in lights_data.items():
        # A plain "turn it off" must not carry colour/brightness attributes —
        # HA's light.turn_off rejects them outright.
        if state.get("on") is False:
            _call_service(light, "turn_off", {"entity_id": entity_id})
            continue

        service_data: dict = {"entity_id": entity_id}
        if "bri" in state:
            # Hue v1 brightness tops out at 254, HA's at 255.
            service_data["brightness"] = round(state["bri"] / 254 * 255)
        if "xy" in state:
            service_data["xy_color"] = [state["xy"][0], state["xy"][1]]
        if "ct" in state and state["ct"]:
            # Hue's `ct` is mirek (10^6/kelvin) — HA's modern service
            # parameter takes kelvin directly.
            service_data["color_temp_kelvin"] = round(1_000_000 / state["ct"])
        if "hue" in state or "sat" in state:
            hue_deg = state.get("hue", light.state.get("hue", 0)) / 65535 * 360
            sat_pct = state.get("sat", light.state.get("sat", 254)) / 254 * 100
            service_data["hs_color"] = [round(hue_deg, 2), round(sat_pct, 2)]
        if "transitiontime" in state:
            service_data["transition"] = state["transitiontime"] / 10
        if "effect" in state and state["effect"] not in ("none", "no_effect"):
            service_data["effect"] = state["effect"]
        if "alert" in state and state["alert"] != "none":
            service_data["flash"] = "short" if state["alert"] == "select" else "long"

        _call_service(light, "turn_on", service_data)


def get_light_state(light) -> dict:
    return {}
