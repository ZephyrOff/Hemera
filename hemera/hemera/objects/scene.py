"""A stored Hue scene (per-light or per-group snapshot of colour/brightness).

Adapted from diyHue's BridgeEmulator/HueObjects/Scene.py (Apache-2.0) — see
/NOTICE. The dynamic-palette ("colorloop"-style) playback thread is kept
since it is protocol-agnostic (drives lights purely through setV2State).
"""

from __future__ import annotations

import uuid
import weakref
from datetime import datetime, timezone
from threading import Thread

from hemera.logging_setup import get_logger
from hemera.objects import gen_v2_uuid, stream_event

logging = get_logger(__name__)


class Scene:
    DEFAULT_SPEED = 0.6269841194152832

    def __init__(self, data: dict) -> None:
        self.name = data["name"]
        self.id_v1 = data["id_v1"]
        self.id_v2 = data.get("id_v2", gen_v2_uuid())
        self.owner = data["owner"]
        self.appdata = data.get("appdata", {})
        self.type = data.get("type", "LightScene")
        self.picture = data.get("picture", "")
        self.image = data.get("image")
        self.recycle = data.get("recycle", False)
        self.lastupdated = data.get("lastupdated", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
        self.lightstates: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        self.palette = data.get("palette", {})
        self.speed = data.get("speed", self.DEFAULT_SPEED)
        self.group = data.get("group")
        self.lights = data.get("lights", [])
        self.status = data.get("status", "inactive")
        if "group" in data:
            self.storelightstate()
            self.lights = self.group().lights

        stream_event({
            "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": [self.get_v2_api()],
            "id": str(uuid.uuid4()),
            "type": "add",
        })

    def add_light(self, light) -> None:
        self.lights.append(light)

    def activate(self, data: dict) -> None:
        if "recall" in data:
            action = data["recall"]["action"]
            if action == "dynamic_palette":
                self.status = action
                for index, light in enumerate(self.lights):
                    if light():
                        light().dynamics["speed"] = self.speed
                        Thread(target=light().dynamicScenePlay, args=[self.palette, index], daemon=True).start()
                return
            if action == "deactivate":
                self.status = "inactive"
                return

        queue_state: dict = {}
        # "recall" is only present when triggered via PUT /clip/v2/resource/scene;
        # internal callers pass a plain transition dict instead.
        self.status = data["recall"]["action"] if "recall" in data else "active"
        for light, state in list(self.lightstates.items()):
            light.state.update(state)
            light.updateLightState(state)
            if light.dynamics["status"] == "dynamic_palette":
                light.dynamics["status"] = "none"
            if data:
                transitiontime = 0
                if "seconds" in data:
                    transitiontime += data["seconds"] * 10
                if "minutes" in data:
                    transitiontime += data["minutes"] * 600
                if transitiontime > 0:
                    state["transitiontime"] = transitiontime
                if "recall" in data and "duration" in data["recall"]:
                    state["transitiontime"] = int(data["recall"]["duration"] / 100)

            if light.protocol == "mqtt":
                ip = light.protocol_cfg["ip"]
                if ip not in queue_state:
                    queue_state[ip] = {"object": light, "lights": {}}
                queue_state[ip]["lights"][light.protocol_cfg["command_topic"]] = state
            else:
                light.setV1State(state)
        for _ip, batch in queue_state.items():
            batch["object"].setV1State(batch)

        if self.type == "GroupScene" and self.group():
            self.group().state["any_on"] = True

    def get_v1_api(self) -> dict:
        result: dict = {"name": self.name, "type": self.type, "lights": [], "lightstates": {}}
        if self.type == "LightScene":
            result["lights"] = [light().id_v1 for light in self.lights if light()]
        elif self.type == "GroupScene" and self.group():
            result["group"] = self.group().id_v1
            result["lights"] = [light().id_v1 for light in self.group().lights if light()]

        for light, state in list(self.lightstates.items()):
            if light.id_v1 in result["lights"] and "gradient" not in state:
                result["lightstates"][light.id_v1] = state
        result["owner"] = self.owner.username
        result["recycle"] = self.recycle
        result["locked"] = True
        result["appdata"] = self.appdata
        if self.image is not None:
            result["image"] = self.image
        result["picture"] = self.picture
        result["lastupdated"] = self.lastupdated
        return result

    def get_v2_api(self) -> dict:
        result: dict = {"actions": []}
        for light, state in list(self.lightstates.items()):
            v2_state: dict = {}
            if "on" in state:
                v2_state["on"] = {"on": state["on"]}
            if "bri" in state:
                bri_value = state["bri"]
                if bri_value in (None, "null"):
                    bri_value = 1
                v2_state["dimming"] = {"brightness": round(float(bri_value) / 2.54, 2)}
            if "xy" in state:
                v2_state["color"] = {"xy": {"x": state["xy"][0], "y": state["xy"][1]}}
            if "ct" in state:
                v2_state["color_temperature"] = {"mirek": state["ct"]}
            result["actions"].append({"action": v2_state, "target": {"rid": light.id_v2, "rtype": "light"}})

        if self.type == "GroupScene" and self.group():
            result["group"] = {
                "rid": str(uuid.uuid5(uuid.NAMESPACE_URL, self.group().id_v2 + self.group().type.lower())),
                "rtype": self.group().type.lower(),
            }
        result["metadata"] = {}
        if self.image is not None:
            result["metadata"]["image"] = {"rid": self.image, "rtype": "public_image"}
        result["metadata"]["name"] = self.name
        result["id"] = self.id_v2
        result["id_v1"] = "/scenes/" + self.id_v1
        result["type"] = "scene"
        if self.palette:
            result["palette"] = self.palette
        result["speed"] = self.speed
        result["auto_dynamic"] = False
        result["status"] = {"active": self.status}
        result["recall"] = {}
        return result

    def storelightstate(self) -> None:
        # NOTE: diyHue's original non-GroupScene branch re-read
        # `self.lightstates.keys()` here — but those keys are the actual Light
        # objects (WeakKeyDictionary), not weakrefs, so `light()` on them would
        # raise TypeError. Snapshotting from `self.lights` (weakrefs, same
        # shape as the GroupScene branch's `self.group().lights`) is what
        # actually populates a scene's state on creation and re-snapshot.
        if self.type == "GroupScene" and self.group():
            lights = [light() for light in self.group().lights if light()]
        else:
            lights = [light() for light in self.lights if light()]
        for light in lights:
            if "on" not in light.state:
                continue
            state: dict = {"on": light.state["on"]}
            colormode = light.state.get("colormode")
            if colormode == "xy":
                state["xy"] = light.state["xy"]
            elif colormode == "ct":
                state["ct"] = light.state["ct"]
            elif colormode == "hs":
                state["hue"] = light.state["hue"]
                state["sat"] = light.state["sat"]
            if "bri" in light.state:
                state["bri"] = light.state["bri"]
            self.lightstates[light] = state

    def update_attr(self, newdata: dict) -> None:
        self.lastupdated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        if newdata.get("storelightstate"):
            self.storelightstate()
            return
        for key, value in newdata.items():
            current = getattr(self, key)
            if isinstance(current, dict):
                current.update(value)
                setattr(self, key, current)
            else:
                setattr(self, key, value)

    def getObjectPath(self) -> dict:
        return {"resource": "scenes", "id": self.id_v1}

    def save(self) -> dict | bool:
        result: dict = {
            "id_v2": self.id_v2, "name": self.name, "appdata": self.appdata,
            "owner": self.owner.username, "type": self.type, "picture": self.picture,
            "image": self.image, "recycle": self.recycle, "lastupdated": self.lastupdated,
            "lights": [], "lightstates": {},
        }
        if self.type == "GroupScene":
            if self.group and self.group():
                result["group"] = self.group().id_v1
            else:
                return False
        if self.palette:
            result["palette"] = self.palette
        result["speed"] = self.speed or self.DEFAULT_SPEED
        result["lights"] = [light().id_v1 for light in self.lights if light()]
        for light, state in list(self.lightstates.items()):
            result["lightstates"][light.id_v1] = state
        return result
