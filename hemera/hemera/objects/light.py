"""A single Hue-presented light, backed by one Zigbee2MQTT device.

Adapted from diyHue's BridgeEmulator/HueObjects/Light.py (Apache-2.0) — see
/NOTICE. Deliberately trimmed of every non-MQTT protocol branch, and of the
WLED-specific ``effects_v2`` block in ``get_v2_api`` (diyHue's ``Light.py``
imports the ``wled`` protocol module just for that one branch — dropped
entirely here since we only ever target Zigbee2MQTT).
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime, timezone
from time import sleep
from typing import Any

from hemera.lights.light_types import archetype, lightTypes
from hemera.lights.protocols import protocols
from hemera.logging_setup import get_logger
from hemera.objects import (
    gen_v2_uuid,
    generate_unique_id,
    inc_process,
    stream_event,
    v1_state_to_v2,
    v2_state_to_v1,
)

logging = get_logger(__name__)

# Modelids whose Z2M "gradient" capability we present as a segmented Hue gradient light.
_GRADIENT_MODELIDS = ("LCX002", "LCX004", "915005987201", "LCX006")


class Light:
    def __init__(self, data: dict) -> None:
        self.name = data["name"]
        self.modelid = data["modelid"]
        self.id_v1 = data["id_v1"]
        self.id_v2 = data.get("id_v2", gen_v2_uuid())
        self.uniqueid = data.get("uniqueid", generate_unique_id())
        self.state = data.get("state", deepcopy(lightTypes[self.modelid]["state"]))
        self.protocol = data.get("protocol", "dummy")
        self.config = data.get("config", deepcopy(lightTypes[self.modelid]["config"]))
        self.protocol_cfg = data.get("protocol_cfg", {})
        self.streaming = False
        self.dynamics = deepcopy(lightTypes[self.modelid]["dynamics"])
        self.effect = "no_effect"
        self.function = data.get("function", "mixed")

        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [{"id": self._entertainment_uuid(), "type": "entertainment", **self.get_v2_entertainment()}],
            "id": str(uuid.uuid4()),
            "type": "add",
            "id_v1": "/lights/" + self.id_v1,
        })
        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [self.get_zigbee()],
            "id": str(uuid.uuid4()),
            "type": "add",
        })
        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [self.get_v2_api()],
            "id": str(uuid.uuid4()),
            "type": "add",
        })
        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [self.get_device()],
            "id": str(uuid.uuid4()),
            "type": "add",
        })

    def _entertainment_uuid(self) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, self.id_v2 + "entertainment"))

    def update_attr(self, newdata: dict) -> None:
        for key, value in newdata.items():
            current = getattr(self, key)
            if isinstance(current, dict):
                current.update(value)
                setattr(self, key, current)
            else:
                setattr(self, key, value)
        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [self.get_device()],
            "id": str(uuid.uuid4()),
            "type": "update",
        })

    def get_v1_api(self) -> dict:
        result = deepcopy(lightTypes[self.modelid]["v1_static"])
        result["config"] = self.config
        result["state"] = {"on": self.state["on"]}
        if "bri" in self.state and self.modelid != "LOM001":
            result["state"]["bri"] = int(self.state["bri"]) if self.state["bri"] is not None else 1
        if "ct" in self.state and self.modelid not in ("LOM001", "LTW001"):
            result["state"]["ct"] = self.state["ct"]
            result["state"]["colormode"] = self.state["colormode"]
        if "xy" in self.state and self.modelid not in ("LOM001", "LTW001", "LWB010"):
            result["state"]["xy"] = self.state["xy"]
            result["state"]["hue"] = self.state.get("hue", 0)
            result["state"]["sat"] = self.state.get("sat", 0)
            result["state"]["colormode"] = self.state["colormode"]
        result["state"]["alert"] = self.state["alert"]
        if "mode" in self.state:
            result["state"]["mode"] = self.state["mode"]
        result["state"]["reachable"] = self.state["reachable"]
        result["modelid"] = self.modelid
        result["name"] = self.name
        result["uniqueid"] = self.uniqueid
        return result

    def updateLightState(self, state: dict) -> None:
        """Recompute colormode after an externally-applied state (called by set_group_action)."""
        if "xy" in state and "xy" in self.state:
            self.state["colormode"] = "xy"
        elif "ct" in state and "ct" in self.state:
            self.state["colormode"] = "ct"
        elif ("hue" in state or "sat" in state) and "hue" in self.state:
            self.state["colormode"] = "hs"

    def setV1State(self, state: dict, advertise: bool = True) -> None:
        if "lights" not in state:
            state = inc_process(self.state, state)
            self.updateLightState(state)
            for key, value in state.items():
                if key in self.state:
                    self.state[key] = value
                if key in self.config:
                    self.config[key] = value.replace("_", "") if key == "archetype" else value
                if key == "name":
                    self.name = value
                if key == "function":
                    self.function = value
            if "bri" in state:
                if "min_bri" in self.protocol_cfg and self.protocol_cfg["min_bri"] > state["bri"]:
                    state["bri"] = self.protocol_cfg["min_bri"]
                if "max_bri" in self.protocol_cfg and self.protocol_cfg["max_bri"] < state["bri"]:
                    state["bri"] = self.protocol_cfg["max_bri"]

        if self.protocol != "dummy":
            for protocol in protocols:
                if "hemera.lights.protocols." + self.protocol == protocol.__name__:
                    try:
                        protocol.set_light(self, state)
                        self.state["reachable"] = True
                    except Exception as exc:  # noqa: BLE001 — best effort, mirrors diyHue
                        self.state["reachable"] = False
                        logging.warning("%s light error: %s", self.name, exc)
                    return
        if advertise:
            self.genStreamEvent(v1_state_to_v2(state))

    def setV2State(self, state: dict) -> None:
        v1_state = v2_state_to_v1(state)
        if "effects" in state:
            v1_state["effect"] = state["effects"]["effect"]
            self.effect = v1_state["effect"]
        if "dynamics" in state and "speed" in state["dynamics"]:
            self.dynamics["speed"] = state["dynamics"]["speed"]
        if "metadata" in state:
            if "archetype" in state["metadata"]:
                v1_state["archetype"] = state["metadata"]["archetype"]
            if "name" in state["metadata"]:
                v1_state["name"] = state["metadata"]["name"]
            if "function" in state["metadata"]:
                v1_state["function"] = state["metadata"]["function"]
        self.setV1State(v1_state, advertise=False)
        self.genStreamEvent(state)

    def genStreamEvent(self, v2_state: dict) -> None:
        light_nr = self.protocol_cfg.get("light_nr", 1) - 1
        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [{
                "id": self.id_v2,
                "id_v1": "/lights/" + self.id_v1,
                "type": "light",
                "owner": {"rid": self.get_device()["id"], "rtype": "device"},
                "service_id": light_nr,
                **v2_state,
            }],
            "id": str(uuid.uuid4()),
            "type": "update",
        })
        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [self.get_device()],
            "id": str(uuid.uuid4()),
            "type": "update",
        })

    def get_device(self) -> dict:
        device = deepcopy(lightTypes[self.modelid]["device"])
        device["model_id"] = self.modelid
        return {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, self.id_v2 + "device")),
            "id_v1": "/lights/" + self.id_v1,
            "identify": {},
            "metadata": {"archetype": archetype.get(self.config["archetype"], "unknown_archetype"), "name": self.name},
            "product_data": device,
            "service_id": self.protocol_cfg.get("light_nr", 1) - 1,
            "services": [
                {"rid": self.id_v2, "rtype": "light"},
                {"rid": str(uuid.uuid5(uuid.NAMESPACE_URL, self.id_v2 + "zigbee_connectivity")), "rtype": "zigbee_connectivity"},
                {"rid": self._entertainment_uuid(), "rtype": "entertainment"},
            ],
            "type": "device",
        }

    def get_zigbee(self) -> dict:
        return {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, self.id_v2 + "zigbee_connectivity")),
            "id_v1": "/lights/" + self.id_v1,
            "mac_address": self.uniqueid[:23],
            "owner": {"rid": self.get_device()["id"], "rtype": "device"},
            "status": "connected" if self.state["reachable"] else "connectivity_issue",
            "type": "zigbee_connectivity",
        }

    def get_v2_api(self) -> dict:
        result: dict[str, Any] = {"alert": {"action_values": ["breathe"]}}
        if self.modelid in _GRADIENT_MODELIDS:
            result["effects"] = {
                "effect_values": ["no_effect", "candle", "fire"],
                "status": self.effect,
                "status_values": ["no_effect", "candle", "fire"],
            }
            result["gradient"] = {
                "points": self.state["gradient"]["points"],
                "points_capable": self.protocol_cfg.get("points_capable", 7),
            }
        if "xy" in self.state:
            colorgamut = lightTypes[self.modelid]["v1_static"]["capabilities"]["control"]["colorgamut"]
            result["color"] = {
                "gamut": {
                    "blue": {"x": colorgamut[2][0], "y": colorgamut[2][1]},
                    "green": {"x": colorgamut[1][0], "y": colorgamut[1][1]},
                    "red": {"x": colorgamut[0][0], "y": colorgamut[0][1]},
                },
                "gamut_type": lightTypes[self.modelid]["v1_static"]["capabilities"]["control"]["colorgamuttype"],
                "xy": {"x": self.state["xy"][0], "y": self.state["xy"][1]},
            }
        if "ct" in self.state:
            ct = self.state["ct"]
            result["color_temperature"] = {
                "mirek": ct if self.state["colormode"] == "ct" else None,
                "mirek_schema": {"mirek_maximum": 500, "mirek_minimum": 153},
                "mirek_valid": ct is not None and 153 < ct < 500,
            }
            result["color_temperature_delta"] = {}
        if "bri" in self.state:
            bri_value = self.state["bri"]
            if bri_value in (None, "null"):
                bri_value = 1
            result["dimming"] = {"brightness": round(float(bri_value) / 2.54, 2), "min_dim_level": 0.1}
            result["dimming_delta"] = {}
        result["dynamics"] = self.dynamics
        result["effects"] = {
            "effect_values": ["no_effect", "candle", "fire", "colorloop"],
            "status": self.effect,
            "status_values": ["no_effect", "candle", "fire", "colorloop"],
        }
        result["timed_effects"] = {}
        result["identify"] = {}
        result["id"] = self.id_v2
        result["id_v1"] = "/lights/" + self.id_v1
        result["metadata"] = {
            "name": self.name,
            "function": self.function,
            "archetype": archetype.get(self.config["archetype"], "unknown_archetype"),
        }
        result["mode"] = "streaming" if self.state.get("mode") == "streaming" else "normal"
        result["on"] = {"on": self.state["on"]}
        result["owner"] = {"rid": str(uuid.uuid5(uuid.NAMESPACE_URL, self.id_v2 + "device")), "rtype": "device"}
        result["product_data"] = {"function": "mixed"}
        result["signaling"] = {"signal_values": ["no_signal", "on_off"]}
        result["powerup"] = {
            "preset": "last_on_state",
            "configured": True,
            "on": {"mode": "on", "on": {"on": True}},
            "dimming": {"mode": "previous"},
        }
        result["service_id"] = self.protocol_cfg.get("light_nr", 1) - 1
        result["type"] = "light"
        return result

    def get_v2_entertainment(self) -> dict:
        result: dict[str, Any] = {
            "equalizer": True,
            "id": self._entertainment_uuid(),
            "id_v1": "/lights/" + self.id_v1,
            "proxy": lightTypes[self.modelid]["v1_static"]["capabilities"]["streaming"]["proxy"],
            "renderer": lightTypes[self.modelid]["v1_static"]["capabilities"]["streaming"]["renderer"],
            "renderer_reference": {"rid": self.id_v2, "rtype": "light"},
            "owner": {"rid": self.get_device()["id"], "rtype": "device"},
            "segments": {"configurable": False},
            "type": "entertainment",
        }
        if self.modelid == "LCX002":
            result["segments"]["max_segments"] = 7
            result["segments"]["segments"] = [
                {"length": 2, "start": 0}, {"length": 2, "start": 2}, {"length": 4, "start": 4},
                {"length": 4, "start": 8}, {"length": 4, "start": 12}, {"length": 2, "start": 16},
                {"length": 2, "start": 18},
            ]
        elif self.modelid in ("915005987201", "LCX004", "LCX006"):
            result["segments"]["max_segments"] = self.protocol_cfg.get("points_capable", 7)
            result["segments"]["segments"] = [{"length": 3, "start": 0}, {"length": 4, "start": 3}, {"length": 3, "start": 7}]
        else:
            result["segments"]["max_segments"] = 1
            result["segments"]["segments"] = [{"length": 1, "start": 0}]
        return result

    def getObjectPath(self) -> dict:
        return {"resource": "lights", "id": self.id_v1}

    def dynamicScenePlay(self, palette: dict, index: int) -> None:
        """Cycle this light through a scene's dynamic palette until stopped (runs in a thread)."""
        if "dynamic_palette" in self.dynamics["status_values"]:
            self.dynamics["status"] = "dynamic_palette"
        while self.dynamics["status"] == "dynamic_palette":
            transition = int(30 / self.dynamics["speed"]) if self.dynamics["speed"] else 30
            if "xy" in self.state:
                colors = palette.get("color", [])
                if not colors:
                    break
                if index >= len(colors):
                    index = 0
                self.setV2State({**colors[index], "transitiontime": transition})
            elif "ct" in self.state:
                temps = palette.get("color_temperature", [])
                if not temps:
                    break
                if index >= len(temps):
                    index = 0
                self.setV2State({**temps[index], "transitiontime": transition})
            else:
                dims = palette.get("dimming", [])
                if not dims:
                    break
                if index >= len(dims):
                    index = 0
                self.setV2State({**dims[index], "transitiontime": transition})
            sleep(transition / 10)
            index += 1
        logging.debug("Dynamic scene stopped for %s", self.name)

    def save(self) -> dict:
        return {
            "id_v2": self.id_v2,
            "name": self.name,
            "modelid": self.modelid,
            "uniqueid": self.uniqueid,
            "function": self.function,
            "state": self.state,
            "config": self.config,
            "protocol": self.protocol,
            "protocol_cfg": self.protocol_cfg,
        }
