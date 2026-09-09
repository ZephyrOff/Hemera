"""CLIP v2 API (HTTPS, `hue-application-key` header auth).

Adapted from diyHue's BridgeEmulator/flaskUI/v2restapi.py (Apache-2.0) — see
/NOTICE — translated from Flask-RESTful to aiohttp and re-scoped to the
resources this project currently models: light, scene, room, zone,
grouped_light, device, zigbee_connectivity, entertainment,
entertainment_configuration, plus the bridge's own singleton resources
(bridge, bridge_home, device, zigbee_connectivity for the bridge itself).
Sensors/smart_scene/behavior_instance/geofence are deliberately out of scope
for now (see the project plan) — dropped rather than stubbed to avoid a v2
surface that claims capabilities we don't have yet.
"""

from __future__ import annotations

import uuid
import weakref
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from aiohttp import web

from hemera.config.handler import Config
from hemera.logging_setup import get_logger
from hemera.objects import stream_event
from hemera.objects.entertainment_configuration import EntertainmentConfiguration
from hemera.objects.group import Group
from hemera.objects.scene import Scene

logging = get_logger(__name__)


def _err(description: str) -> web.Response:
    return web.json_response({"errors": [{"description": description}], "data": []})


class HueV2Api:
    def __init__(self, bridge_config: Config) -> None:
        self.cfg = bridge_config
        self._on_entertainment_start: Callable[[EntertainmentConfiguration, str], Awaitable[None]] | None = None
        self._on_entertainment_stop: Callable[[EntertainmentConfiguration], Awaitable[None]] | None = None

    def set_entertainment_callbacks(self, on_start, on_stop) -> None:
        self._on_entertainment_start = on_start
        self._on_entertainment_stop = on_stop

    @property
    def yaml_config(self) -> dict:
        return self.cfg.yaml_config

    # -- auth -----------------------------------------------------------

    def _authorize(self, request: web.Request):
        key = request.headers.get("hue-application-key")
        if key is None:
            return None
        user = self.yaml_config["apiUsers"].get(key)
        if user is not None:
            user.touch()
        return user

    # -- bridge singleton resources ---------------------------------------

    def _bridge_id(self) -> str:
        return self.yaml_config["config"]["bridgeid"]

    def _v2_bridge(self) -> dict:
        bridge_id = self._bridge_id()
        return {
            "bridge_id": bridge_id.lower(),
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, bridge_id + "bridge")),
            "id_v1": "",
            "owner": {"rid": str(uuid.uuid5(uuid.NAMESPACE_URL, bridge_id + "device")), "rtype": "device"},
            "time_zone": {"time_zone": self.yaml_config["config"]["timezone"]},
            "type": "bridge",
        }

    def _v2_bridge_device(self) -> dict:
        cfg = self.yaml_config["config"]
        bridge_id = cfg["bridgeid"]
        return {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, bridge_id + "device")),
            "id_v1": "",
            "metadata": {"archetype": "bridge_v2", "name": cfg["name"]},
            "identify": {},
            "product_data": {
                "certified": True, "manufacturer_name": "Signify Netherlands B.V.", "model_id": "BSB002",
                "product_archetype": "bridge_v2", "product_name": "Philips hue",
                "software_version": cfg["apiversion"][:5] + cfg["swversion"],
            },
            "services": [
                {"rid": str(uuid.uuid5(uuid.NAMESPACE_URL, bridge_id + "bridge")), "rtype": "bridge"},
                {"rid": str(uuid.uuid5(uuid.NAMESPACE_URL, bridge_id + "zigbee_connectivity")), "rtype": "zigbee_connectivity"},
                {"rid": str(uuid.uuid5(uuid.NAMESPACE_URL, bridge_id + "entertainment")), "rtype": "entertainment"},
            ],
            "type": "device",
        }

    def _v2_bridge_zigbee(self) -> dict:
        bridge_id = self._bridge_id()
        return {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, bridge_id + "zigbee_connectivity")),
            "owner": {"rid": str(uuid.uuid5(uuid.NAMESPACE_URL, bridge_id + "device")), "rtype": "device"},
            "status": "connected",
            "mac_address": self.yaml_config["config"]["mac"],
            "channel": {"value": f"channel_{self.yaml_config['config'].get('zigbeechannel', 25)}", "status": "set"},
            "type": "zigbee_connectivity",
        }

    def _v2_bridge_entertainment(self) -> dict:
        bridge_id = self._bridge_id()
        return {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, bridge_id + "entertainment")),
            "owner": {"rid": str(uuid.uuid5(uuid.NAMESPACE_URL, bridge_id + "device")), "rtype": "device"},
            "renderer": False, "proxy": True, "equalizer": False, "max_streams": 1,
            "type": "entertainment",
        }

    def _v2_bridge_home(self) -> dict:
        children = []
        services = []
        for light in self.yaml_config["lights"].values():
            services.append({"rid": light.id_v2, "rtype": "light"})
            children.append({"rid": light.get_device()["id"], "rtype": "device"})
        for group in self.yaml_config["groups"].values():
            if isinstance(group, Group) and group.type == "Room":
                children.append({"rid": group.get_v2_room()["id"], "rtype": "room"})
        group0 = self.yaml_config["groups"]["0"]
        services.append({"rid": group0.id_v2, "rtype": "grouped_light"})
        return {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, group0.id_v2 + "bridge_home")),
            "id_v1": "/groups/0",
            "children": children,
            "services": services,
            "type": "bridge_home",
        }

    # -- lookups ----------------------------------------------------------

    def get_object(self, resource: str, v2uuid: str):
        yaml_config = self.yaml_config
        if resource in ("light", "grouped_light"):
            pool = yaml_config["lights"] if resource == "light" else yaml_config["groups"]
            return next((o for o in pool.values() if o.id_v2 == v2uuid), None)
        if resource == "scene":
            return next((o for o in yaml_config["scenes"].values() if o.id_v2 == v2uuid), None)
        if resource == "entertainment":
            for light in yaml_config["lights"].values():
                if str(uuid.uuid5(uuid.NAMESPACE_URL, light.id_v2 + "entertainment")) == v2uuid:
                    return light
            return None
        if resource == "entertainment_configuration":
            for group in yaml_config["groups"].values():
                if not isinstance(group, EntertainmentConfiguration):
                    continue
                derived = str(uuid.uuid5(uuid.NAMESPACE_URL, group.id_v2 + "entertainment_configuration"))
                # Also match the group's own id_v2: POST .../entertainment_configuration
                # returns id_v2 as `rid` (matching diyHue), but the resource's own `id`
                # field (what a later GET returns) is the derived uuid above — a client
                # that immediately GETs/PUTs using the id it was just handed must resolve.
                if derived == v2uuid or group.id_v2 == v2uuid:
                    return group
            return None
        # room / zone / device / zigbee_connectivity: derived uuid5(id_v2 + resource),
        # with the same id_v2 fallback as above for freshly-POSTed rooms/zones.
        for pool in (yaml_config["lights"], yaml_config["groups"]):
            for obj in pool.values():
                if str(uuid.uuid5(uuid.NAMESPACE_URL, obj.id_v2 + resource)) == v2uuid or obj.id_v2 == v2uuid:
                    return obj
        return None

    def _list_for_resource(self, resource: str) -> list[dict]:
        yaml_config = self.yaml_config
        if resource == "light":
            return [v.get_v2_api() for v in yaml_config["lights"].values()]
        if resource == "scene":
            return [v.get_v2_api() for v in yaml_config["scenes"].values()]
        if resource == "room":
            return [g.get_v2_room() for g in yaml_config["groups"].values() if isinstance(g, Group) and g.type == "Room"]
        if resource == "zone":
            return [g.get_v2_zone() for g in yaml_config["groups"].values() if isinstance(g, Group) and g.type == "Zone"]
        if resource == "grouped_light":
            return [g.get_v2_grouped_light() for g in yaml_config["groups"].values()]
        if resource == "device":
            return [light.get_device() for light in yaml_config["lights"].values()] + [self._v2_bridge_device()]
        if resource == "zigbee_connectivity":
            return [light.get_zigbee() for light in yaml_config["lights"].values()] + [self._v2_bridge_zigbee()]
        if resource == "entertainment":
            return [light.get_v2_entertainment() for light in yaml_config["lights"].values()] + [self._v2_bridge_entertainment()]
        if resource == "entertainment_configuration":
            return [g.get_v2_api() for g in yaml_config["groups"].values() if isinstance(g, EntertainmentConfiguration)]
        if resource == "bridge":
            return [self._v2_bridge()]
        if resource == "bridge_home":
            return [self._v2_bridge_home()]
        return []

    def _all_resources(self) -> list[dict]:
        data: list[dict] = []
        for resource in (
            "device", "bridge", "zigbee_connectivity", "entertainment",
            "scene", "light", "room", "zone", "entertainment_configuration",
        ):
            data.extend(self._list_for_resource(resource))
        for group in self.yaml_config["groups"].values():
            data.append(group.get_v2_grouped_light())
        data.append(self._v2_bridge_home())
        return data

    # -- routing ------------------------------------------------------------

    def register_routes(self, app: web.Application) -> None:
        app.router.add_get("/clip/v2/resource", self.h_list_all)
        app.router.add_get("/clip/v2/resource/{resource}", self.h_list_resource)
        app.router.add_get("/clip/v2/resource/{resource}/{id}", self.h_get_one)
        app.router.add_post("/clip/v2/resource/{resource}", self.h_create)
        app.router.add_put("/clip/v2/resource/{resource}/{id}", self.h_update)
        app.router.add_delete("/clip/v2/resource/{resource}/{id}", self.h_delete)
        app.router.add_get("/auth/v1", self.h_auth_v1)

    # -- handlers -------------------------------------------------------------

    async def h_auth_v1(self, request: web.Request) -> web.Response:
        user = self._authorize(request)
        if user is None:
            return web.Response(status=403)
        return web.json_response({}, headers={"hue-application-id": request.headers["hue-application-key"]})

    async def h_list_all(self, request: web.Request) -> web.Response:
        if self._authorize(request) is None:
            return web.Response(status=403)
        return web.json_response({"errors": [], "data": self._all_resources()})

    async def h_list_resource(self, request: web.Request) -> web.Response:
        if self._authorize(request) is None:
            return web.Response(status=403)
        resource = request.match_info["resource"]
        data = self._list_for_resource(resource)
        if not data and resource not in (
            "light", "scene", "room", "zone", "grouped_light", "device",
            "zigbee_connectivity", "entertainment", "entertainment_configuration", "bridge", "bridge_home",
        ):
            return _err(f"Resource type not supported: {resource}")
        return web.json_response({"errors": [], "data": data})

    async def h_get_one(self, request: web.Request) -> web.Response:
        if self._authorize(request) is None:
            return web.Response(status=403)
        resource = request.match_info["resource"]
        rid = request.match_info["id"]
        obj = self.get_object(resource, rid)
        if obj is None:
            return web.json_response({"errors": [], "data": []})
        builder = {
            "light": lambda o: o.get_v2_api(),
            "scene": lambda o: o.get_v2_api(),
            "room": lambda o: o.get_v2_room(),
            "zone": lambda o: o.get_v2_zone(),
            "grouped_light": lambda o: o.get_v2_grouped_light(),
            "device": lambda o: o.get_device(),
            "zigbee_connectivity": lambda o: o.get_zigbee(),
            "entertainment": lambda o: o.get_v2_entertainment(),
            "entertainment_configuration": lambda o: o.get_v2_api(),
        }.get(resource)
        if builder is None:
            return _err(f"Resource type not supported: {resource}")
        return web.json_response({"errors": [], "data": [builder(obj)]})

    async def h_create(self, request: web.Request) -> web.Response:
        user = self._authorize(request)
        if user is None:
            return web.Response(status=403)
        resource = request.match_info["resource"]
        body = await request.json()

        from hemera.lights.discover import next_free_id

        if resource == "scene":
            new_id = next_free_id(self.yaml_config["scenes"])
            data: dict = {
                "id_v1": new_id,
                "name": body["metadata"]["name"],
                "image": body["metadata"].get("image", {}).get("rid"),
                "owner": user,
            }
            if "group" in body:
                group_obj = self.get_object(body["group"]["rtype"], body["group"]["rid"])
                data["group"] = weakref.ref(group_obj)
                data["type"] = "GroupScene"
            elif "lights" in body:
                data["type"] = "LightScene"
                data["lights"] = [weakref.ref(self.get_object("light", ref["rid"])) for ref in body["lights"]]
            scene = Scene(data)
            self.yaml_config["scenes"][new_id] = scene
            for action in body.get("actions", []):
                target = action.get("target")
                if target and target["rtype"] == "light":
                    light = self.get_object("light", target["rid"])
                    state: dict = {}
                    a = action["action"]
                    if "on" in a:
                        state["on"] = a["on"]["on"]
                    if "dimming" in a:
                        state["bri"] = int(a["dimming"]["brightness"] * 2.54)
                    if "color" in a and "xy" in a["color"]:
                        state["xy"] = [a["color"]["xy"]["x"], a["color"]["xy"]["y"]]
                    if "color_temperature" in a and a["color_temperature"].get("mirek") is not None:
                        state["ct"] = a["color_temperature"]["mirek"]
                    if "gradient" in a:
                        state["gradient"] = a["gradient"]
                    scene.lightstates[light] = state
            if not scene.lightstates:
                scene.storelightstate()
            self.cfg.mark_dirty("scenes")
            new_object = scene

        elif resource == "entertainment_configuration":
            new_id = next_free_id(self.yaml_config["groups"])
            data = {"id_v1": new_id, "name": body["metadata"]["name"], **body}
            group = EntertainmentConfiguration(data)
            for loc in body.get("locations", {}).get("service_locations", []):
                obj = self.get_object(loc["service"]["rtype"], loc["service"]["rid"])
                if obj is not None:
                    group.add_light(obj)
                    group.locations[obj] = loc["positions"]
            self.yaml_config["groups"][new_id] = group
            self.cfg.mark_dirty("groups")
            stream_event({
                "creationtime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": [group.get_v2_api()], "id": str(uuid.uuid4()), "type": "update",
            })
            new_object = group

        elif resource in ("room", "zone"):
            new_id = next_free_id(self.yaml_config["groups"])
            data = {"id_v1": new_id, "name": body["metadata"]["name"], "owner": user, "type": resource.capitalize()}
            if "archetype" in body["metadata"]:
                data["icon_class"] = body["metadata"]["archetype"].replace("_", " ").capitalize()
            group = Group(data)
            for child in body.get("children", []):
                obj = self.get_object(child["rtype"], child["rid"])
                if obj is not None:
                    group.add_light(obj)
            self.yaml_config["groups"][new_id] = group
            self.cfg.mark_dirty("groups")
            new_object = group

        else:
            return web.json_response({"errors": [{"description": f"Resource type not supported: {resource}"}]}, status=500)

        return web.json_response({"data": [{"rid": new_object.id_v2, "rtype": resource}], "errors": []})

    async def _set_entertainment_active(self, group: EntertainmentConfiguration, active: bool, owner: str) -> None:
        if active:
            group.stream["active"] = True
            group.stream["owner"] = owner
            if self._on_entertainment_start:
                await self._on_entertainment_start(group, owner)
        else:
            group.stream["active"] = False
            group.stream["owner"] = None
            if self._on_entertainment_stop:
                await self._on_entertainment_stop(group)

    async def h_update(self, request: web.Request) -> web.Response:
        user = self._authorize(request)
        if user is None:
            return web.Response(status=403)
        resource = request.match_info["resource"]
        rid = request.match_info["id"]
        obj = self.get_object(resource, rid)
        if obj is None:
            return _err("Resource not found")
        body = await request.json()

        if resource == "light":
            obj.setV2State(body)
        elif resource == "scene":
            if "recall" in body:
                obj.activate(body)
            for attr in ("speed", "palette"):
                if attr in body:
                    setattr(obj, attr, body[attr])
            if "metadata" in body and "name" in body["metadata"]:
                obj.name = body["metadata"]["name"]
            self.cfg.mark_dirty("scenes")
        elif resource == "grouped_light":
            obj.setV2Action(body)
        elif resource in ("room", "zone"):
            attrs: dict = {}
            if "metadata" in body:
                if "name" in body["metadata"]:
                    attrs["name"] = body["metadata"]["name"]
                if "archetype" in body["metadata"]:
                    attrs["icon_class"] = body["metadata"]["archetype"].replace("_", " ").capitalize()
            if "children" in body:
                obj.lights = []
                for child in body["children"]:
                    light = self.get_object(child["rtype"], child["rid"])
                    if light is not None:
                        obj.add_light(light)
            obj.update_attr(attrs)
            self.cfg.mark_dirty("groups")
        elif resource == "entertainment_configuration":
            action = body.get("action")
            if action == "start":
                await self._set_entertainment_active(obj, True, user.username)
            elif action == "stop":
                await self._set_entertainment_active(obj, False, user.username)
            obj.update_attr({k: v for k, v in body.items() if k != "action"})
            self.cfg.mark_dirty("groups")
        else:
            return _err(f"Resource type not supported: {resource}")

        return web.json_response({"data": [{"rid": rid, "rtype": resource}], "errors": []})

    async def h_delete(self, request: web.Request) -> web.Response:
        if self._authorize(request) is None:
            return web.Response(status=403)
        resource = request.match_info["resource"]
        rid = request.match_info["id"]
        obj = self.get_object(resource, rid)
        if obj is None:
            return _err("Resource not found")
        path = obj.getObjectPath()
        if path["id"] != "0":
            del self.yaml_config[path["resource"]][path["id"]]
            self.cfg.mark_dirty(path["resource"])
        return web.json_response({"data": [{"rid": rid, "rtype": resource}], "errors": []})
