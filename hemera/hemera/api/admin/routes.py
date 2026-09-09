"""Admin panel: a small local web UI to configure MQTT, create/manage
rooms, exclude devices from the bridge, and simulate the link button.

New in response to real-world testing: the Hue app's own pairing flow was
too opaque to debug remotely (the app just retries forever with no
diagnostic beyond "press the button"), and there was no way to inspect or
fix a stuck MQTT connection, exclude a mis-detected device, or organise
rooms without going through raw Hue API calls. This panel is plain
server-rendered JSON + vanilla JS (no build step, no framework) — it is
NOT part of the Hue protocol surface (bridge.api.v1/v2) and is deliberately
unauthenticated, same reasoning as the `/linkbutton` route: reaching it
already means being on the local network.
"""

from __future__ import annotations

import os

from aiohttp import web

from hemera.api.v1.routes import HueV1Api
from hemera.config.handler import Config
from hemera.lights.discover import next_free_id
from hemera.logging_setup import get_logger
from hemera.objects.entertainment_configuration import EntertainmentConfiguration
from hemera.objects.group import Group
from hemera.services.mqtt_client import MqttClient

logging = get_logger(__name__)

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class AdminApi:
    def __init__(self, cfg: Config, mqtt_client: MqttClient, hue_v1: HueV1Api) -> None:
        self.cfg = cfg
        self.mqtt_client = mqtt_client
        self.hue_v1 = hue_v1

    @property
    def yaml_config(self) -> dict:
        return self.cfg.yaml_config

    def register_routes(self, app: web.Application) -> None:
        app.router.add_get("/", self.h_index)
        app.router.add_get("/api/state", self.h_state)
        app.router.add_post("/api/mqtt", self.h_set_mqtt)
        app.router.add_post("/api/linkbutton", self.h_linkbutton)
        app.router.add_post("/api/rooms", self.h_create_room)
        app.router.add_delete("/api/rooms/{id}", self.h_delete_room)
        app.router.add_post("/api/rooms/{id}/lights", self.h_add_light_to_room)
        app.router.add_delete("/api/rooms/{id}/lights/{light_id}", self.h_remove_light_from_room)
        app.router.add_post("/api/lights/{id}/exclude", self.h_exclude_light)
        app.router.add_post("/api/excluded/{ieee}/include", self.h_include_device)

    async def h_index(self, request: web.Request) -> web.FileResponse:
        return web.FileResponse(os.path.join(_STATIC_DIR, "index.html"))

    # -- state ---------------------------------------------------------------

    async def h_state(self, request: web.Request) -> web.Response:
        lights = []
        for light_id, light in self.yaml_config["lights"].items():
            room_ids = [
                gid for gid, group in self.yaml_config["groups"].items()
                if gid != "0" and isinstance(group, Group)
                and any(ref() is light for ref in group.lights)
            ]
            lights.append({
                "id": light_id,
                "name": light.name,
                "modelid": light.modelid,
                "reachable": light.state.get("reachable", True),
                "on": light.state.get("on", False),
                "room_ids": room_ids,
            })

        rooms = []
        entertainment_areas = []
        for group_id, group in self.yaml_config["groups"].items():
            if group_id == "0":
                continue
            light_ids = [ref().id_v1 for ref in group.lights if ref()]
            entry = {"id": group_id, "name": group.name, "light_ids": light_ids}
            if isinstance(group, EntertainmentConfiguration):
                entry["stream_active"] = group.stream.get("active", False)
                entertainment_areas.append(entry)
            elif isinstance(group, Group):
                entry["type"] = group.type
                rooms.append(entry)

        excluded = [
            {"ieee": ieee, "name": name}
            for ieee, name in self.yaml_config["config"].get("excluded_devices", {}).items()
        ]

        mqtt_cfg = self.yaml_config["config"]["mqtt"]
        return web.json_response({
            "mqtt": {
                "host": mqtt_cfg["host"], "port": mqtt_cfg["port"],
                "user": mqtt_cfg["user"], "base_topic": mqtt_cfg["base_topic"],
                "connected": self.mqtt_client.connected,
                # password deliberately omitted from the response
            },
            "link_button": {
                "active": self.hue_v1.link_button_active,
                "remaining_seconds": round(self.hue_v1.link_button_remaining_seconds, 1),
            },
            "lights": lights,
            "rooms": rooms,
            "entertainment_areas": entertainment_areas,
            "excluded": excluded,
            "paired_users": len(self.yaml_config["apiUsers"]),
        })

    # -- mqtt ------------------------------------------------------------------

    async def h_set_mqtt(self, request: web.Request) -> web.Response:
        body = await request.json()
        host = str(body.get("host", "")).strip() or "127.0.0.1"
        port = int(body.get("port") or 1883)
        user = str(body.get("user", ""))
        password = str(body.get("password", ""))
        base_topic = str(body.get("base_topic", "")).strip() or "zigbee2mqtt"

        # Keep the previous password if the panel sent an empty field back
        # (the state endpoint never returns the real password to the browser).
        if not password:
            password = self.yaml_config["config"]["mqtt"].get("password", "")

        self.yaml_config["config"]["mqtt"] = {
            "host": host, "port": port, "user": user, "password": password, "base_topic": base_topic,
        }
        self.cfg.mark_dirty("config")
        await self.mqtt_client.reconfigure(host, port, user, password, base_topic)
        return web.json_response({"ok": True})

    # -- link button -------------------------------------------------------------

    async def h_linkbutton(self, request: web.Request) -> web.Response:
        self.hue_v1.arm_link_button()
        return web.json_response({"active": True, "remaining_seconds": self.hue_v1.link_button_remaining_seconds})

    # -- rooms -----------------------------------------------------------------

    async def h_create_room(self, request: web.Request) -> web.Response:
        body = await request.json()
        name = str(body.get("name", "")).strip()
        if not name:
            return web.json_response({"error": "name is required"}, status=400)
        light_ids = body.get("light_ids", [])
        new_id = next_free_id(self.yaml_config["groups"])
        group = Group({"id_v1": new_id, "name": name, "type": "Room", "class": body.get("class", "Other")})
        for light_id in light_ids:
            light = self.yaml_config["lights"].get(light_id)
            if light is not None:
                group.add_light(light)
        self.yaml_config["groups"][new_id] = group
        self.cfg.mark_dirty("groups")
        return web.json_response({"id": new_id})

    async def h_delete_room(self, request: web.Request) -> web.Response:
        room_id = request.match_info["id"]
        if room_id != "0" and room_id in self.yaml_config["groups"]:
            del self.yaml_config["groups"][room_id]
            self.cfg.mark_dirty("groups")
        return web.json_response({"ok": True})

    async def h_add_light_to_room(self, request: web.Request) -> web.Response:
        room_id = request.match_info["id"]
        body = await request.json()
        light_id = body.get("light_id")
        group = self.yaml_config["groups"].get(room_id)
        light = self.yaml_config["lights"].get(light_id)
        if group is None or light is None:
            return web.json_response({"error": "not found"}, status=404)
        if not any(ref() is light for ref in group.lights):
            group.add_light(light)
            self.cfg.mark_dirty("groups")
        return web.json_response({"ok": True})

    async def h_remove_light_from_room(self, request: web.Request) -> web.Response:
        room_id = request.match_info["id"]
        light_id = request.match_info["light_id"]
        group = self.yaml_config["groups"].get(room_id)
        if group is None:
            return web.json_response({"error": "not found"}, status=404)
        group.lights = [ref for ref in group.lights if not (ref() and ref().id_v1 == light_id)]
        self.cfg.mark_dirty("groups")
        return web.json_response({"ok": True})

    # -- exclusion ---------------------------------------------------------------

    async def h_exclude_light(self, request: web.Request) -> web.Response:
        light_id = request.match_info["id"]
        light = self.yaml_config["lights"].get(light_id)
        if light is None:
            return web.json_response({"error": "not found"}, status=404)
        ieee = light.protocol_cfg.get("ieee_address")
        if ieee:
            excluded = self.yaml_config["config"].setdefault("excluded_devices", {})
            excluded[ieee] = light.name
        del self.yaml_config["lights"][light_id]
        for group in self.yaml_config["groups"].values():
            group.lights = [ref for ref in group.lights if ref() is not light]
        self.cfg.mark_dirty("config")
        self.cfg.mark_dirty("lights")
        self.cfg.mark_dirty("groups")
        return web.json_response({"ok": True})

    async def h_include_device(self, request: web.Request) -> web.Response:
        ieee = request.match_info["ieee"]
        excluded = self.yaml_config["config"].get("excluded_devices", {})
        excluded.pop(ieee, None)
        self.cfg.mark_dirty("config")
        self.mqtt_client.resync_devices()
        return web.json_response({"ok": True})
