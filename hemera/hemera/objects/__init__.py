"""Shared helpers for the Hue object model.

Adapted from diyHue's ``BridgeEmulator/HueObjects/__init__.py`` (Apache-2.0)
— see /NOTICE. Pure functions plus the v2 eventstream (SSE) backing list;
no dependency on any specific light protocol.
"""

from __future__ import annotations

import random
import uuid

from hemera.logging_setup import get_logger

logging = get_logger(__name__)

# Backing list for the CLIP v2 Server-Sent-Events stream (GET /eventstream/clip/v2).
# Consumed and cleared by hemera.api.v1.eventstream's broker loop.
eventstream: list[dict] = []


def stream_event(message: dict) -> None:
    eventstream.append(message)


def v1_state_to_v2(v1_state: dict) -> dict:
    v2_state: dict = {}
    if "on" in v1_state:
        v2_state["on"] = {"on": v1_state["on"]}
    if "bri" in v1_state:
        v2_state["dimming"] = {"brightness": round(v1_state["bri"] / 2.54, 2)}
    if "ct" in v1_state:
        v2_state["color_temperature"] = {"mirek": v1_state["ct"], "color_temperature_delta": {}}
    if "xy" in v1_state:
        v2_state["color"] = {"xy": {"x": v1_state["xy"][0], "y": v1_state["xy"][1]}}
    return v2_state


def v2_state_to_v1(v2_state: dict) -> dict:
    v1_state: dict = {}
    if "dimming" in v2_state:
        v1_state["bri"] = int(v2_state["dimming"]["brightness"] * 2.54)
    if "on" in v2_state:
        v1_state["on"] = v2_state["on"]["on"]
    if "color_temperature" in v2_state and v2_state["color_temperature"].get("mirek") is not None:
        v1_state["ct"] = v2_state["color_temperature"]["mirek"]
    if "color" in v2_state and "xy" in v2_state["color"]:
        v1_state["xy"] = [v2_state["color"]["xy"]["x"], v2_state["color"]["xy"]["y"]]
    if "gradient" in v2_state:
        v1_state["gradient"] = v2_state["gradient"]
    if "transitiontime" in v2_state:
        v1_state["transitiontime"] = v2_state["transitiontime"]
    return v1_state


def gen_v2_uuid() -> str:
    return str(uuid.uuid4())


def generate_unique_id() -> str:
    """Fake a Zigbee-MAC-shaped uniqueid for a light with no real one (e.g. an MQTT light)."""
    rand_bytes = [random.randrange(0, 256) for _ in range(3)]
    return "00:17:88:01:00:%02x:%02x:%02x-0b" % (rand_bytes[0], rand_bytes[1], rand_bytes[2])


def inc_process(state: dict, data: dict) -> dict:
    """Resolve v1 `_inc` relative-adjustment fields (bri_inc/ct_inc/hue_inc/sat_inc) in place."""
    if "bri_inc" in data:
        state["bri"] = max(1, min(254, state["bri"] + data["bri_inc"]))
        del data["bri_inc"]
        data["bri"] = state["bri"]
    elif "ct_inc" in data:
        state["ct"] = max(153, min(500, state["ct"] + data["ct_inc"]))
        del data["ct_inc"]
        data["ct"] = state["ct"]
    elif "hue_inc" in data:
        hue = state["hue"] + data["hue_inc"]
        state["hue"] = hue % 65536
        del data["hue_inc"]
        data["hue"] = state["hue"]
    elif "sat_inc" in data:
        state["sat"] = max(1, min(254, state["sat"] + data["sat_inc"]))
        del data["sat_inc"]
        data["sat"] = state["sat"]
    return data


def set_group_action(group, state: dict, scene=None) -> None:
    """Fan a group-level action out to its member lights.

    Ported near-verbatim from diyHue: batches lights whose protocol benefits
    from a single multi-light command (only "mqtt" here — diyHue's
    "native_multi" case is dropped, we have no such backend) and calls
    ``setV1State`` once per light otherwise.
    """
    lights_state: dict[str, dict] = {}
    if scene is not None:
        for light, lstate in list(scene.lightstates.items()):
            lights_state[light.id_v1] = lstate
            if lstate.get("on") is True:
                group.state["any_on"] = True
    else:
        state = inc_process(group.action, state)
        for light in group.lights:
            if light():
                lights_state[light().id_v1] = state
        if "xy" in state:
            group.action["colormode"] = "xy"
        elif "ct" in state:
            group.action["colormode"] = "ct"
        elif "hue" in state or "sat" in state:
            group.action["colormode"] = "hs"
        if "on" in state:
            group.state["any_on"] = state["on"]
            group.state["all_on"] = state["on"]
        group.action.update(state)

    queue_state: dict[str, dict] = {}
    for light in group.lights:
        if not (light() and light().id_v1 in lights_state):
            continue
        this_state = lights_state[light().id_v1]
        for key, value in this_state.items():
            if key in light().state:
                light().state[key] = value
        light().updateLightState(this_state)
        if "bri" in this_state:
            cfg = light().protocol_cfg
            if "min_bri" in cfg and cfg["min_bri"] > this_state["bri"]:
                this_state["bri"] = cfg["min_bri"]
            if "max_bri" in cfg and cfg["max_bri"] < this_state["bri"]:
                this_state["bri"] = cfg["max_bri"]
            if light().protocol == "mqtt" and not light().state["on"]:
                continue
        if light().protocol == "mqtt":
            ip = light().protocol_cfg["ip"]
            if ip not in queue_state:
                queue_state[ip] = {"object": light(), "lights": {}}
            queue_state[ip]["lights"][light().protocol_cfg["command_topic"]] = this_state
        else:
            light().setV1State(this_state)
    for _ip, batch in queue_state.items():
        # Whole-batch dict, not batch["lights"] — Light.setV1State() and the
        # mqtt protocol's set_light() both branch on `"lights" in state` to
        # tell a single-light call from a multi-light one (see Light.py).
        batch["object"].setV1State(batch)

    group.state = group.update_state()
