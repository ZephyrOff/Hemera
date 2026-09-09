"""Hue Entertainment area (v1 "Entertainment" group / v2 entertainment_configuration).

Adapted from diyHue's BridgeEmulator/HueObjects/EntertainmentConfiguration.py
(Apache-2.0) — see /NOTICE. The DTLS/HueStream streaming session itself lives
in hemera.services.entertainment (ported from 83noit/ha-hue-entertainment,
MIT) — this class only models the *resource* the Hue app / Sync Box
discovers and PUTs {"stream": {"active": true}} / v2 {"action": "start"} to.
"""

from __future__ import annotations

import uuid
import weakref
from datetime import datetime, timezone

from hemera.logging_setup import get_logger
from hemera.objects import gen_v2_uuid, set_group_action, stream_event, v1_state_to_v2, v2_state_to_v1

logging = get_logger(__name__)

# Gradient-strip anchor positions used when a member light is a gradient
# lightstrip (7 evenly-spread points along a virtual TV-top arc).
_GRADIENT_STRIP_POSITIONS = [
    {"x": -0.4, "y": 0.8, "z": -0.4}, {"x": -0.4, "y": 0.8, "z": 0.0},
    {"x": -0.4, "y": 0.8, "z": 0.4}, {"x": 0.0, "y": 0.8, "z": 0.4},
    {"x": 0.4, "y": 0.8, "z": 0.4}, {"x": 0.4, "y": 0.8, "z": 0.0},
    {"x": 0.4, "y": 0.8, "z": -0.4},
]
_GRADIENT_MODELIDS = ("LCX001", "LCX002", "LCX003", "LCX004", "LCX006", "915005987201")


class EntertainmentConfiguration:
    def __init__(self, data: dict) -> None:
        self.name = data.get("name", "Group " + data["id_v1"])
        self.id_v1 = data["id_v1"]
        self.id_v2 = data.get("id_v2", gen_v2_uuid())
        self.configuration_type = data.get("configuration_type", "screen")
        self.lights: list = []
        self.action = {
            "on": False, "bri": 100, "hue": 0, "sat": 254, "effect": "none",
            "xy": [0.0, 0.0], "ct": 153, "alert": "none", "colormode": "xy",
        }
        self.sensors: list = []
        self.type = data.get("type", "Entertainment")
        self.locations: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        self.stream = {"proxymode": "auto", "proxynode": "/bridge", "active": False, "owner": None}
        self.state = {"all_on": False, "any_on": False}
        self.dxState = {"all_on": None, "any_on": None}

        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [self.get_v2_api()],
            "id": str(uuid.uuid4()),
            "type": "add",
        })

    def add_light(self, light) -> None:
        self.lights.append(weakref.ref(light))
        self.locations[light] = [{"x": 0, "y": 0, "z": 0}]

    def update_attr(self, newdata: dict) -> None:
        newdata = dict(newdata)
        newdata.pop("lights", None)
        newdata.pop("locations", None)  # set directly via self.locations, not through update_attr
        for key, value in newdata.items():
            current = getattr(self, key)
            if isinstance(current, dict):
                current.update(value)
                setattr(self, key, current)
            else:
                setattr(self, key, value)
        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [self.get_v2_api()],
            "id": str(uuid.uuid4()),
            "type": "update",
        })

    def update_state(self) -> dict:
        all_on = len(self.lights) > 0
        any_on = False
        for ref in self.lights:
            light = ref()
            if not light:
                continue
            if light.state.get("on"):
                any_on = True
            else:
                all_on = False
        return {"all_on": all_on, "any_on": any_on}

    def get_v2_grouped_light(self) -> dict:
        return {
            "alert": {"action_values": ["breathe"]},
            "id": self.id_v2,
            "id_v1": "/groups/" + self.id_v1,
            "on": {"on": self.update_state()["any_on"]},
            "type": "grouped_light",
        }

    def get_v1_api(self) -> dict:
        lights = [ref().id_v1 for ref in self.lights if ref()]
        result = {
            "name": self.name,
            "lights": lights,
            "sensors": [ref().id_v1 for ref in self.sensors if ref()],
            "type": self.type,
            "state": self.update_state(),
            "recycle": False,
            "class": "TV" if self.configuration_type != "3dspace" else "Free",
            "action": self.action,
            "locations": {
                light.id_v1: [loc[0]["x"], loc[0]["y"], loc[0]["z"]]
                for light, loc in self.locations.items() if light.id_v1 in lights
            },
            "stream": dict(self.stream),
        }
        return result

    def get_v2_api(self) -> dict:
        result: dict = {
            "configuration_type": self.configuration_type,
            "locations": {"service_locations": []},
            "metadata": {"name": self.name},
            "id_v1": "/groups/" + self.id_v1,
            "stream_proxy": {
                "mode": "auto",
                "node": {
                    "rid": str(uuid.uuid5(uuid.NAMESPACE_URL, self.lights[0]().id_v2 + "entertainment")) if self.lights else None,
                    "rtype": "entertainment",
                },
            },
            "light_services": [],
            "channels": [],
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, self.id_v2 + "entertainment_configuration")),
            "type": "entertainment_configuration",
            "name": self.name,
            "status": "active" if self.stream["active"] else "inactive",
        }
        if self.stream["active"]:
            result["active_streamer"] = {"rid": self.stream["owner"], "rtype": "auth_v1"}

        channel_id = 0
        for ref in self.lights:
            light = ref()
            if not light:
                continue
            result["light_services"].append({"rtype": "light", "rid": light.id_v2})
            entertainment_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, light.id_v2 + "entertainment"))
            location = self.locations.get(light, [{"x": 0, "y": 0, "z": 0}])
            result["locations"]["service_locations"].append({
                "equalization_factor": 1,
                "positions": location,
                "service": {"rid": entertainment_uuid, "rtype": "entertainment"},
                "position": location[0],
            })

            is_gradient = light.modelid in _GRADIENT_MODELIDS
            loops = light.protocol_cfg.get("points_capable", 7) if is_gradient else 1
            for i in range(loops):
                channel: dict = {
                    "channel_id": channel_id,
                    "members": [{"index": i, "service": {"rid": entertainment_uuid, "rtype": "entertainment"}}],
                }
                if is_gradient and i < len(_GRADIENT_STRIP_POSITIONS):
                    channel["position"] = _GRADIENT_STRIP_POSITIONS[i]
                else:
                    channel["position"] = location[0]
                result["channels"].append(channel)
                channel_id += 1
        return result

    def setV2Action(self, state: dict) -> None:
        set_group_action(self, v2_state_to_v1(state))
        self.genStreamEvent(state)

    def setV1Action(self, state: dict, scene=None) -> None:
        set_group_action(self, state, scene)
        self.genStreamEvent(v1_state_to_v2(state))

    def genStreamEvent(self, v2_state: dict) -> None:
        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [{"id": self.id_v2, "type": "grouped_light", **v2_state}],
            "id": str(uuid.uuid4()),
            "type": "update",
            "id_v1": "/groups/" + self.id_v1,
        })

    def getObjectPath(self) -> dict:
        return {"resource": "groups", "id": self.id_v1}

    def save(self) -> dict:
        lights = [ref().id_v1 for ref in self.lights if ref()]
        return {
            "id_v2": self.id_v2,
            "name": self.name,
            "configuration_type": self.configuration_type,
            "lights": lights,
            "action": self.action,
            "type": self.type,
            "locations": {
                light.id_v1: loc for light, loc in self.locations.items() if light.id_v1 in lights
            },
        }
