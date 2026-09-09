"""Hue v1 REST API (aiohttp) — bridge discovery, pairing, and the
lights/groups/scenes surface the Hue app and Hue Sync (legacy v1 path) use.

Structure (routing table, catch-alls, pairing idempotency, unauthenticated
config shape) adapted from 83noit/ha-hue-entertainment's
custom_components/hue_entertainment/hue_api.py (MIT) — see /NOTICE — but the
light/group/scene bodies are now backed by the real object model
(hemera.objects.*) instead of a synthetic fixed light list, and group/scene
CRUD (create/update/delete) is added, following the JSON shapes used by
diyHue's BridgeEmulator/flaskUI/restful.py (Apache-2.0).

Entertainment start/stop (PUT .../groups/{id}/stream, v1's classic path) only
flips the resource's ``stream.active`` flag here — the actual DTLS session is
wired in by hemera.services.entertainment via ``set_entertainment_callbacks``
in a later step; until then this just makes the resource state consistent
for clients that check it.
"""

from __future__ import annotations

import secrets
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from aiohttp import web

from hemera.config.handler import Config
from hemera.logging_setup import get_logger
from hemera.objects.api_user import ApiUser
from hemera.objects.entertainment_configuration import EntertainmentConfiguration
from hemera.objects.group import Group

logging = get_logger(__name__)

LINK_BUTTON_TIMEOUT = 60.0


def _error(address: str, description: str, error_type: int = 1) -> list:
    return [{"error": {"type": error_type, "address": address, "description": description}}]


def _success_list(prefix: str, body: dict) -> list:
    result = []
    for k, v in body.items():
        if isinstance(v, dict):
            for sk, sv in v.items():
                result.append({"success": {f"{prefix}/{k}/{sk}": sv}})
        else:
            result.append({"success": {f"{prefix}/{k}": v}})
    return result


class HueV1Api:
    def __init__(self, bridge_config: Config) -> None:
        self.cfg = bridge_config
        self._link_button_expires = time.monotonic() + LINK_BUTTON_TIMEOUT  # armed on startup
        self._on_entertainment_start: Callable[[EntertainmentConfiguration, str], Awaitable[None]] | None = None
        self._on_entertainment_stop: Callable[[EntertainmentConfiguration], Awaitable[None]] | None = None

    def set_entertainment_callbacks(self, on_start, on_stop) -> None:
        self._on_entertainment_start = on_start
        self._on_entertainment_stop = on_stop

    @property
    def yaml_config(self) -> dict:
        return self.cfg.yaml_config

    # -- link button -----------------------------------------------------

    @property
    def link_button_active(self) -> bool:
        return time.monotonic() < self._link_button_expires

    @property
    def link_button_remaining_seconds(self) -> float:
        return max(0.0, self._link_button_expires - time.monotonic())

    def arm_link_button(self) -> None:
        self._link_button_expires = time.monotonic() + LINK_BUTTON_TIMEOUT
        logging.info("Link button armed for %.0fs — pair a client now", LINK_BUTTON_TIMEOUT)

    # -- routing -----------------------------------------------------------

    def register_routes(self, app: web.Application) -> None:
        routes = [
            ("GET", "/description.xml", self.h_description_xml),
            # Deliberately unauthenticated, like the real bridge's physical link
            # button: being able to reach this HTTP port already means you're on
            # the LAN, the same trust level a physical button press implies.
            # Needed because the only *other* way to (re)arm pairing is a
            # restart (30-90s auto-arm window) or, on a non-add-on deployment,
            # SIGUSR1 — neither is convenient once the add-on has been running
            # a while and a client's initial pairing window has lapsed.
            ("POST", "/linkbutton", self.h_arm_linkbutton),
            ("GET", "/api/nouser/config", self.h_config_unauth),
            ("GET", "/api/config", self.h_config_unauth),
            ("POST", "/api", self.h_create_user),
            ("GET", "/api/{username}", self.h_full_datastore),
            ("GET", "/api/{username}/config", self.h_config_auth),
            ("PUT", "/api/{username}/config", self.h_put_config),
            ("GET", "/api/{username}/capabilities", self.h_capabilities),
            ("GET", "/api/{username}/lights", self.h_lights_list),
            ("GET", "/api/{username}/lights/{id}", self.h_light_get),
            ("PUT", "/api/{username}/lights/{id}/state", self.h_light_state_put),
            ("PUT", "/api/{username}/lights/{id}", self.h_light_attrs_put),
            ("DELETE", "/api/{username}/lights/{id}", self.h_light_delete),
            ("GET", "/api/{username}/groups", self.h_groups_list),
            ("POST", "/api/{username}/groups", self.h_group_create),
            ("GET", "/api/{username}/groups/{id}", self.h_group_get),
            ("PUT", "/api/{username}/groups/{id}/action", self.h_group_action_put),
            ("PUT", "/api/{username}/groups/{id}/stream", self.h_group_stream_put),
            ("PUT", "/api/{username}/groups/{id}", self.h_group_put),
            ("DELETE", "/api/{username}/groups/{id}", self.h_group_delete),
            ("GET", "/api/{username}/scenes", self.h_scenes_list),
            ("POST", "/api/{username}/scenes", self.h_scene_create),
            ("GET", "/api/{username}/scenes/{id}", self.h_scene_get),
            ("PUT", "/api/{username}/scenes/{id}", self.h_scene_put),
            ("DELETE", "/api/{username}/scenes/{id}", self.h_scene_delete),
            # Catch-alls for resources not yet implemented (rules/schedules/sensors/...):
            # answer something well-formed instead of a 404 that could make the Hue app retry-loop.
            ("GET", "/api/{username}/{resource}", self.h_v1_catchall_get),
            ("GET", "/api/{username}/{resource}/{rid}", self.h_v1_catchall_get_one),
            ("PUT", "/api/{username}/{resource}/{rid}", self.h_v1_catchall_put),
            ("POST", "/api/{username}/{resource}", self.h_v1_catchall_post),
            ("DELETE", "/api/{username}/{resource}/{rid}", self.h_v1_catchall_delete),
        ]
        for method, path, handler in routes:
            app.router.add_route(method, path, handler)

    # -- helpers -----------------------------------------------------------

    def _check_user(self, request: web.Request) -> str | None:
        username = request.match_info.get("username", "")
        if username in self.yaml_config["apiUsers"]:
            self.yaml_config["apiUsers"][username].touch()
            return username
        return None

    @staticmethod
    async def _json(request: web.Request) -> dict | None:
        try:
            return await request.json()
        except Exception:  # noqa: BLE001
            return None

    def _build_config(self, authed: bool) -> dict:
        cfg = self.yaml_config["config"]
        result = {
            "name": cfg["name"],
            "datastoreversion": "163",
            "swversion": cfg["swversion"],
            "apiversion": cfg["apiversion"],
            "mac": cfg["mac"],
            "bridgeid": cfg["bridgeid"],
            "factorynew": False,
            "replacesbridgeid": None,
            "modelid": "BSB002",
            "starterkitid": "",
            "ipaddress": cfg["ipaddress"],
            "dhcp": True,
            "netmask": cfg["netmask"],
            "gateway": cfg["gateway"],
            "UTC": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "localtime": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "timezone": cfg["timezone"],
            "zigbeechannel": cfg.get("zigbeechannel", 25),
            "linkbutton": self.link_button_active,
            "portalservices": False,
            "portalstate": {"signedon": False, "incoming": False, "outgoing": False, "communication": "disconnected"},
            "internetservices": {"internet": "disconnected", "remoteaccess": "disconnected", "swupdate": "disconnected", "time": "disconnected"},
            "swupdate2": {"checkforupdate": False, "state": "noupdates", "autoinstall": {"on": False, "updatetime": "T14:00:00"}},
            "backup": {"errorcode": 0, "status": "idle"},
        }
        if authed:
            result["whitelist"] = {
                u: {"create date": o.create_date, "last use date": o.last_use_date, "name": o.name}
                for u, o in self.yaml_config["apiUsers"].items()
            }
        return result

    # -- handlers: bridge discovery / config --------------------------------

    async def h_description_xml(self, request: web.Request) -> web.Response:
        cfg = self.yaml_config["config"]
        serial = cfg["mac"].replace(":", "").lower()
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<root xmlns="urn:schemas-upnp-org:device-1-0">\n'
            "<specVersion><major>1</major><minor>0</minor></specVersion>\n"
            f'<URLBase>http://{cfg["ipaddress"]}:{request.url.port or 80}/</URLBase>\n'
            "<device>\n<deviceType>urn:schemas-upnp-org:device:Basic:1</deviceType>\n"
            f'<friendlyName>Philips hue ({cfg["ipaddress"]})</friendlyName>\n'
            "<manufacturer>Signify</manufacturer>\n<manufacturerURL>http://www.meethue.com</manufacturerURL>\n"
            "<modelDescription>Philips hue Personal Wireless Lighting</modelDescription>\n"
            "<modelName>Philips hue bridge 2015</modelName>\n<modelNumber>BSB002</modelNumber>\n"
            "<modelURL>http://www.meethue.com</modelURL>\n"
            f"<serialNumber>{serial}</serialNumber>\n<UDN>uuid:2f402f80-da50-11e1-9b23-{serial}</UDN>\n"
            "<presentationURL>index.html</presentationURL>\n</device>\n</root>"
        )
        return web.Response(text=xml, content_type="text/xml")

    async def h_arm_linkbutton(self, request: web.Request) -> web.Response:
        self.arm_link_button()
        return web.json_response({"linkbutton": True, "expires_in": LINK_BUTTON_TIMEOUT})

    async def h_config_unauth(self, request: web.Request) -> web.Response:
        return web.json_response(self._build_config(authed=False))

    async def h_config_auth(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        return web.json_response(self._build_config(authed=True))

    async def h_put_config(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        body = await self._json(request)
        if body is None:
            return web.json_response(_error("/", "body contains invalid json", 2))
        if body.get("linkbutton") is True:
            self.arm_link_button()
        if "name" in body:
            self.yaml_config["config"]["name"] = body["name"]
        self.cfg.mark_dirty("config")
        return web.json_response(_success_list("/config", body))

    async def h_create_user(self, request: web.Request) -> web.Response:
        raw = await request.read()
        body = await self._json(request)
        logging.info(
            "POST /api from %s (content-type=%s, body=%r) — link button active: %s",
            request.remote, request.content_type, raw[:200], self.link_button_active,
        )
        if body is None:
            return web.json_response(_error("/", "body contains invalid json", 2))
        # No link-button gate: matches Bifrost (a modern, actively-maintained
        # Hue-bridge-for-Zigbee2MQTT emulator)'s proven pairing behaviour —
        # its post_api() always succeeds unconditionally, no timestamp check
        # at all. For a personal home-LAN bridge this is an acceptable
        # trade-off (anyone who can reach the bridge can pair), and removes
        # an entire axis of "why won't the official app just send POST /api"
        # timing uncertainty that a 30-60s window otherwise introduces.
        device_type = body.get("devicetype", "unknown")
        generate_clientkey = bool(body.get("generateclientkey", False))

        existing = next(
            (u for u, o in self.yaml_config["apiUsers"].items() if o.name == device_type), None
        )
        if existing is not None:
            username = existing
            client_key = self.yaml_config["apiUsers"][username].client_key
        else:
            username = uuid.uuid4().hex[:32]
            client_key = secrets.token_hex(16)
            self.yaml_config["apiUsers"][username] = ApiUser(username, device_type, client_key)
            self.cfg.mark_dirty("config")
            logging.info("Paired new client: %s (%s)", device_type, username)

        result = {"success": {"username": username}}
        if generate_clientkey:
            result["success"]["clientkey"] = client_key
        return web.json_response([result])

    async def h_capabilities(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        return web.json_response({
            "lights": {"available": 63, "total": len(self.yaml_config["lights"])},
            "groups": {"available": 60, "total": len(self.yaml_config["groups"])},
            "scenes": {"available": 200, "total": len(self.yaml_config["scenes"])},
            "streaming": {"available": 1, "total": 1, "channels": 20},
        })

    async def h_full_datastore(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        return web.json_response({
            "lights": {k: v.get_v1_api() for k, v in self.yaml_config["lights"].items()},
            "groups": {k: v.get_v1_api() for k, v in self.yaml_config["groups"].items() if k != "0"},
            "config": self._build_config(authed=True),
            "schedules": {}, "scenes": {k: v.get_v1_api() for k, v in self.yaml_config["scenes"].items()},
            "rules": {}, "sensors": {}, "resourcelinks": {},
        })

    # -- handlers: lights ----------------------------------------------------

    async def h_lights_list(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        return web.json_response({k: v.get_v1_api() for k, v in self.yaml_config["lights"].items()})

    async def h_light_get(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        light = self.yaml_config["lights"].get(request.match_info["id"])
        if light is None:
            return web.json_response(_error(f"/lights/{request.match_info['id']}", "resource not available", 3))
        return web.json_response(light.get_v1_api())

    async def h_light_state_put(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        light_id = request.match_info["id"]
        light = self.yaml_config["lights"].get(light_id)
        if light is None:
            return web.json_response(_error(f"/lights/{light_id}/state", "resource not available", 3))
        body = await self._json(request)
        if body is None:
            return web.json_response(_error("/", "body contains invalid json", 2))
        light.setV1State(body)
        self.cfg.mark_dirty("lights")
        return web.json_response(_success_list(f"/lights/{light_id}/state", body))

    async def h_light_attrs_put(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        light = self.yaml_config["lights"].get(request.match_info["id"])
        if light is None:
            return web.json_response(_error("/", "resource not available", 3))
        body = await self._json(request)
        if body is None:
            return web.json_response(_error("/", "body contains invalid json", 2))
        if "name" in body:
            light.name = body["name"]
        self.cfg.mark_dirty("lights")
        return web.json_response(_success_list(f"/lights/{request.match_info['id']}", body))

    async def h_light_delete(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        light_id = request.match_info["id"]
        if light_id in self.yaml_config["lights"]:
            del self.yaml_config["lights"][light_id]
            self.cfg.mark_dirty("lights")
        return web.json_response([{"success": f"/lights/{light_id} deleted"}])

    # -- handlers: groups ------------------------------------------------------

    async def h_groups_list(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        return web.json_response({k: v.get_v1_api() for k, v in self.yaml_config["groups"].items() if k != "0"})

    async def h_group_create(self, request: web.Request) -> web.Response:
        username = self._check_user(request)
        if username is None:
            return web.json_response(_error("/", "unauthorized user"))
        body = await self._json(request)
        if body is None:
            return web.json_response(_error("/", "body contains invalid json", 2))
        from hemera.lights.discover import next_free_id

        new_id = next_free_id(self.yaml_config["groups"])
        body["id_v1"] = new_id
        light_ids = body.pop("lights", [])
        is_entertainment = body.get("type") == "Entertainment"
        if is_entertainment:
            group = EntertainmentConfiguration(body)
        else:
            body["owner"] = self.yaml_config["apiUsers"][username]
            group = Group(body)
        for light_id in light_ids:
            light = self.yaml_config["lights"].get(light_id)
            if light is not None:
                group.add_light(light)
        self.yaml_config["groups"][new_id] = group
        self.cfg.mark_dirty("groups")
        return web.json_response([{"success": {"id": new_id}}])

    async def h_group_get(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        group = self.yaml_config["groups"].get(request.match_info["id"])
        if group is None:
            return web.json_response(_error("/", "resource not available", 3))
        return web.json_response(group.get_v1_api())

    async def h_group_put(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        group_id = request.match_info["id"]
        group = self.yaml_config["groups"].get(group_id)
        if group is None:
            return web.json_response(_error("/", "resource not available", 3))
        body = await self._json(request)
        if body is None:
            return web.json_response(_error("/", "body contains invalid json", 2))
        stream = body.pop("stream", None)
        group.update_attr(body)
        if stream is not None:
            await self._set_entertainment_active(group, stream.get("active", False), request.match_info["username"])
        self.cfg.mark_dirty("groups")
        return web.json_response(_success_list(f"/groups/{group_id}", body))

    async def h_group_action_put(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        group_id = request.match_info["id"]
        group = self.yaml_config["groups"].get(group_id)
        if group is None:
            return web.json_response(_error("/", "resource not available", 3))
        body = await self._json(request)
        if body is None:
            return web.json_response(_error("/", "body contains invalid json", 2))
        group.setV1Action(body)
        self.cfg.mark_dirty("lights")
        return web.json_response(_success_list(f"/groups/{group_id}/action", body))

    async def _set_entertainment_active(self, group, active: bool, username: str) -> None:
        if not isinstance(group, EntertainmentConfiguration):
            return
        if active:
            group.stream["active"] = True
            group.stream["owner"] = username
            if self._on_entertainment_start:
                await self._on_entertainment_start(group, username)
        else:
            group.stream["active"] = False
            group.stream["owner"] = None
            if self._on_entertainment_stop:
                await self._on_entertainment_stop(group)

    async def h_group_stream_put(self, request: web.Request) -> web.Response:
        username = self._check_user(request)
        if username is None:
            return web.json_response(_error("/", "unauthorized user"))
        group = self.yaml_config["groups"].get(request.match_info["id"])
        if group is None or not isinstance(group, EntertainmentConfiguration):
            return web.json_response(_error("/", "resource not available", 3))
        body = await self._json(request) or {}
        stream = body.get("stream", body)
        active = bool(stream.get("active", False))
        await self._set_entertainment_active(group, active, username)
        return web.json_response([{"success": {f"/groups/{group.id_v1}/stream/active": active}}])

    async def h_group_delete(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        group_id = request.match_info["id"]
        if group_id in self.yaml_config["groups"] and group_id != "0":
            del self.yaml_config["groups"][group_id]
            self.cfg.mark_dirty("groups")
        return web.json_response([{"success": f"/groups/{group_id} deleted"}])

    # -- handlers: scenes ------------------------------------------------------

    async def h_scenes_list(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        return web.json_response({k: v.get_v1_api() for k, v in self.yaml_config["scenes"].items()})

    async def h_scene_create(self, request: web.Request) -> web.Response:
        username = self._check_user(request)
        if username is None:
            return web.json_response(_error("/", "unauthorized user"))
        body = await self._json(request)
        if body is None:
            return web.json_response(_error("/", "body contains invalid json", 2))
        from hemera.lights.discover import next_free_id
        from hemera.objects.scene import Scene

        new_id = next_free_id(self.yaml_config["scenes"])
        body["id_v1"] = new_id
        body["owner"] = self.yaml_config["apiUsers"][username]
        if body.get("type") == "GroupScene" and "group" in body:
            import weakref

            group_id = body["group"]
            if group_id not in self.yaml_config["groups"]:
                return web.json_response(_error("/", "resource not available", 3))
            body["group"] = weakref.ref(self.yaml_config["groups"][group_id])
        else:
            light_ids = body.get("lights", [])
            body["lights"] = [
                weakref_light for lid in light_ids
                if (weakref_light := self._weakref_light(lid)) is not None
            ]
        scene = Scene(body)
        scene.storelightstate()
        self.yaml_config["scenes"][new_id] = scene
        self.cfg.mark_dirty("scenes")
        return web.json_response([{"success": {"id": new_id}}])

    def _weakref_light(self, light_id: str):
        import weakref

        light = self.yaml_config["lights"].get(light_id)
        return weakref.ref(light) if light is not None else None

    async def h_scene_get(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        scene = self.yaml_config["scenes"].get(request.match_info["id"])
        if scene is None:
            return web.json_response(_error("/", "resource not available", 3))
        return web.json_response(scene.get_v1_api())

    async def h_scene_put(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        scene_id = request.match_info["id"]
        scene = self.yaml_config["scenes"].get(scene_id)
        if scene is None:
            return web.json_response(_error("/", "resource not available", 3))
        body = await self._json(request)
        if body is None:
            return web.json_response(_error("/", "body contains invalid json", 2))
        if "storelightstate" in body:
            scene.storelightstate()
        else:
            scene.activate(body)
        self.cfg.mark_dirty("scenes")
        return web.json_response(_success_list(f"/scenes/{scene_id}", body))

    async def h_scene_delete(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        scene_id = request.match_info["id"]
        if scene_id in self.yaml_config["scenes"]:
            del self.yaml_config["scenes"][scene_id]
            self.cfg.mark_dirty("scenes")
        return web.json_response([{"success": f"/scenes/{scene_id} deleted"}])

    # -- catch-alls (rules/schedules/sensors/resourcelinks: not implemented yet) --

    async def h_v1_catchall_get(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        return web.json_response({})

    async def h_v1_catchall_get_one(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        return web.json_response({})

    async def h_v1_catchall_put(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        body = await self._json(request) or {}
        resource = request.match_info.get("resource", "")
        rid = request.match_info.get("rid", "")
        return web.json_response(_success_list(f"/{resource}/{rid}", body))

    async def h_v1_catchall_post(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        return web.json_response([{"success": {"id": "0"}}])

    async def h_v1_catchall_delete(self, request: web.Request) -> web.Response:
        if self._check_user(request) is None:
            return web.json_response(_error("/", "unauthorized user"))
        resource = request.match_info.get("resource", "")
        rid = request.match_info.get("rid", "")
        return web.json_response([{"success": f"/{resource}/{rid} deleted"}])
