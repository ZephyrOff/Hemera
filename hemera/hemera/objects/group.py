"""Hue "group" resource — backs both v1 /groups and v2 room/zone/grouped_light.

Adapted from diyHue's BridgeEmulator/HueObjects/Group.py (Apache-2.0) — see
/NOTICE.
"""

from __future__ import annotations

import uuid
import weakref
from datetime import datetime, timezone

from hemera.logging_setup import get_logger
from hemera.objects import gen_v2_uuid, set_group_action, stream_event, v1_state_to_v2, v2_state_to_v1

logging = get_logger(__name__)


class Group:
    def __init__(self, data: dict) -> None:
        self.name = data.get("name", "Group " + data["id_v1"])
        self.id_v1 = data["id_v1"]
        self.id_v2 = data.get("id_v2", gen_v2_uuid())
        if "owner" in data:
            self.owner = data["owner"]
        self.icon_class = data.get("class", data.get("icon_class", "Other"))
        self.lights: list = []
        self.action = {
            "on": False, "bri": 100, "hue": 0, "sat": 254, "effect": "none",
            "xy": [0.0, 0.0], "ct": 153, "alert": "none", "colormode": "xy",
        }
        self.sensors: list = []
        self.device_children = list(data.get("device_children", []))
        self.type = data.get("type", "LightGroup")
        self.state = {"all_on": False, "any_on": False}
        self.dxState = {"all_on": None, "any_on": None}

        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [self.get_v2_room() if self.type == "Room" else self.get_v2_zone()],
            "id": str(uuid.uuid4()),
            "type": "add",
        })

    def groupZeroStream(self, rooms: list[str], lights: list[str]) -> None:
        message = {
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [{
                "children": [{"rid": r, "rtype": "room"} for r in rooms] + [{"rid": light, "rtype": "light"} for light in lights],
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, self.id_v2 + "bridge_home")),
                "id_v1": "/groups/0",
                "type": "bridge_home",
            }],
            "id": str(uuid.uuid4()),
            "type": "update",
        }
        stream_event(message)

    def add_light(self, light) -> None:
        self.lights.append(weakref.ref(light))
        element_id = self.get_v2_room()["id"] if self.type == "Room" else self.get_v2_zone()["id"]
        element_type = "room" if self.type == "Room" else "zone"
        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [{"alert": {"action_values": ["breathe"]}, "id": self.id_v2, "id_v1": "/groups/" + self.id_v1,
                      "on": {"on": self.action["on"]}, "type": "grouped_light"}],
            "id": str(uuid.uuid4()),
            "type": "add",
        })
        children = []
        services = []
        seen = set()
        for ref in self.lights:
            if ref():
                dev_id = ref().get_device()["id"]
                if dev_id not in seen:
                    seen.add(dev_id)
                    children.append({"rid": dev_id, "rtype": "device"})
                services.append({"rid": ref().id_v2, "rtype": "light"})
        for dev_id in self.device_children:
            if dev_id not in seen:
                seen.add(dev_id)
                children.append({"rid": dev_id, "rtype": "device"})
        services.append({"rid": self.id_v2, "rtype": "grouped_light"})
        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [{"children": children, "id": element_id, "id_v1": "/groups/" + self.id_v1,
                      "services": services, "type": element_type}],
            "id": str(uuid.uuid4()),
            "type": "update",
        })

    def add_sensor(self, sensor) -> None:
        self.sensors.append(weakref.ref(sensor))

    def update_attr(self, newdata: dict) -> None:
        newdata = dict(newdata)
        newdata.pop("lights", None)  # lights are updated via add_light() only
        if "class" in newdata:
            newdata["icon_class"] = newdata.pop("class")
        for key, value in newdata.items():
            current = getattr(self, key)
            if isinstance(current, dict):
                current.update(value)
                setattr(self, key, current)
            else:
                setattr(self, key, value)
        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [self.get_v2_room() if self.type == "Room" else self.get_v2_zone()],
            "id": str(uuid.uuid4()),
            "type": "update",
        })

    def update_state(self) -> dict:
        all_on = len(self.lights) > 0
        any_on = False
        bri = 0
        lights_on = 0
        for ref in self.lights:
            light = ref()
            if not light:
                continue
            if light.state.get("on"):
                any_on = True
                if "bri" in light.state:
                    bri += light.state["bri"]
                    lights_on += 1
            else:
                all_on = False
        avg_bri = int(((bri / lights_on) / 254) * 100) if any_on and bri > 0 else 0
        return {"all_on": all_on, "any_on": any_on, "avr_bri": avg_bri}

    def setV2Action(self, state: dict) -> None:
        set_group_action(self, v2_state_to_v1(state))
        self.genStreamEvent(state)

    def setV1Action(self, state: dict, scene=None) -> None:
        set_group_action(self, state, scene)
        self.genStreamEvent(v1_state_to_v2(state))

    def genStreamEvent(self, v2_state: dict) -> None:
        light_data = []
        for ref in self.lights:
            light = ref()
            if not light:
                continue
            light_data.append({
                "id": light.id_v2,
                "id_v1": "/lights/" + light.id_v1,
                "owner": {"rid": light.get_device()["id"], "rtype": "device"},
                "service_id": light.protocol_cfg.get("light_nr", 1) - 1,
                "type": "light",
                **v2_state,
            })
        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": light_data,
            "id": str(uuid.uuid4()),
            "type": "update",
        })
        grouped_state = dict(v2_state)
        if "on" in grouped_state:
            grouped_state["dimming"] = {"brightness": self.update_state()["avr_bri"]}
        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [{
                "id": self.id_v2, "id_v1": "/groups/" + self.id_v1, "type": "grouped_light",
                "owner": {
                    "rid": self.get_v2_room()["id"] if self.type == "Room" else self.get_v2_zone()["id"],
                    "rtype": "room" if self.type == "Room" else "zone",
                },
                **grouped_state,
            }],
            "id": str(uuid.uuid4()),
            "type": "update",
        })

    def get_v1_api(self) -> dict:
        result: dict = {"name": self.name}
        if hasattr(self, "owner"):
            result["owner"] = self.owner.username
        result["lights"] = [ref().id_v1 for ref in self.lights if ref()]
        result["sensors"] = [ref().id_v1 for ref in self.sensors if ref()]
        result["type"] = self.type.capitalize()
        result["state"] = self.update_state()
        result["recycle"] = False
        if self.id_v1 == "0":
            result["presence"] = {"state": {"presence": None, "presence_all": None, "lastupdated": "none"}}
            result["lightlevel"] = {"state": {
                "dark": None, "dark_all": None, "daylight": None, "daylight_any": None,
                "lightlevel": None, "lightlevel_min": None, "lightlevel_max": None, "lastupdated": "none",
            }}
        else:
            result["class"] = self.icon_class.capitalize() if len(self.icon_class) > 2 else self.icon_class.upper()
        result["action"] = self.action
        return result

    def get_v2_room(self) -> dict:
        children: list = []
        services: list = []
        seen_devices: set = set()
        seen_services: set = set()
        for ref in self.lights:
            light = ref()
            if not light:
                continue
            dev_id = light.get_device()["id"]
            if dev_id not in seen_devices:
                seen_devices.add(dev_id)
                children.append({"rid": dev_id, "rtype": "device"})
            if light.id_v2 not in seen_services:
                seen_services.add(light.id_v2)
                services.append({"rid": light.id_v2, "rtype": "light"})
        for dev_id in self.device_children:
            if dev_id not in seen_devices:
                seen_devices.add(dev_id)
                children.append({"rid": dev_id, "rtype": "device"})
        services.append({"rid": self.id_v2, "rtype": "grouped_light"})
        return {
            "children": children,
            "services": services,
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, self.id_v2 + "room")),
            "id_v1": "/groups/" + self.id_v1,
            "metadata": {"archetype": self.icon_class.replace(" ", "_").replace("'", "").lower(), "name": self.name},
            "type": "room",
        }

    def get_v2_zone(self) -> dict:
        children = [{"rid": ref().id_v2, "rtype": "light"} for ref in self.lights if ref()]
        services = [{"rid": ref().id_v2, "rtype": "light"} for ref in self.lights if ref()]
        services.append({"rid": self.id_v2, "rtype": "grouped_light"})
        return {
            "children": children,
            "services": services,
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, self.id_v2 + "zone")),
            "id_v1": "/groups/" + self.id_v1,
            "metadata": {"archetype": self.icon_class.replace(" ", "_").replace("'", "").lower(), "name": self.name},
            "type": "zone",
        }

    def get_v2_grouped_light(self) -> dict:
        result = {
            "alert": {"action_values": ["breathe"]},
            "color": {},
            "dimming": {"brightness": self.update_state()["avr_bri"]},
            "dimming_delta": {},
            "dynamics": {},
            "id": self.id_v2,
            "id_v1": "/groups/" + self.id_v1,
            "on": {"on": self.update_state()["any_on"]},
            "type": "grouped_light",
            "signaling": {"signal_values": ["no_signal", "on_off"]},
        }
        if hasattr(self, "owner"):
            result["owner"] = {"rid": self.owner.username, "rtype": "device"}
        else:
            result["owner"] = {"rid": self.id_v2, "rtype": "device"}
        return result

    def getObjectPath(self) -> dict:
        return {"resource": "groups", "id": self.id_v1}

    def save(self) -> dict:
        result: dict = {
            "id_v2": self.id_v2, "name": self.name, "class": self.icon_class,
            "lights": [ref().id_v1 for ref in self.lights if ref()],
            "action": self.action, "type": self.type, "device_children": self.device_children,
        }
        if hasattr(self, "owner"):
            result["owner"] = self.owner.username
        return result
