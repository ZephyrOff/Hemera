"""Persistent Home Assistant connection: discovers `light.*` entities that
come from OTHER Home Assistant integrations (WLED, Tuya, ESPHome, a
different Hue integration, ...) — anything not already reachable through
the Zigbee2MQTT connector — and keeps their state in sync.

Talks to Home Assistant's own REST API through the Supervisor's proxy
(`http://supervisor/core/api`), authenticated with this add-on's own
SUPERVISOR_TOKEN — available with no setup at all once `homeassistant_api:
true` is set in config.yaml, unlike the MQTT connector which needs a
broker address. Outside the add-on (local dev), HEMERA_HA_URL/
HEMERA_HA_TOKEN (a manually created long-lived access token) fill the same
role — see config/bootstrap.py.

Runs a periodic poll of `GET /states` rather than a live WebSocket
subscription — simpler and safer for a first version (no auth handshake or
message-id bookkeeping to get wrong), at the cost of a state change taking
up to _POLL_INTERVAL_S to reach the Hue app instead of arriving instantly.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import urllib.request

from hemera.config.handler import Config
from hemera.lights.discover import add_new_light
from hemera.logging_setup import get_logger
from hemera.objects import v1_state_to_v2

logging = get_logger(__name__)

_POLL_INTERVAL_S = 3.0
_REQUEST_TIMEOUT_S = 10.0


def _pick_modelid(attributes: dict) -> str:
    """Best-effort mapping from a HA light entity's `supported_color_modes`
    to a Hue modelid template — mirrors mqtt_client.py's _pick_modelid for
    Z2M `exposes`, using HA's own capability vocabulary instead. Any color
    mode besides "onoff" implies HA's own light entity supports brightness
    too (HA's own data model, not something to special-case here)."""
    modes = set(attributes.get("supported_color_modes") or [])
    has_color = bool(modes & {"hs", "xy", "rgb", "rgbw", "rgbww"})
    has_ct = "color_temp" in modes
    has_bri = bool(modes - {"onoff"})
    if has_color and has_ct:
        return "LCT015"
    if has_color:
        return "LLC010"
    if has_ct:
        return "LTW001"
    if has_bri:
        return "LWB010"
    return "LOM001"


class HaClient:
    def __init__(self, bridge_config: Config, base_url: str, token: str) -> None:
        self.cfg = bridge_config
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.token = token
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._connected = False
        self._last_states: list[dict] | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def available(self) -> bool:
        """Whether there's anything to even try connecting with — unlike
        MQTT, the HA connector is entirely optional and typically needs no
        configuration at all (it's automatic under Supervisor), so the admin
        panel needs to tell "not available" apart from "configured but
        unreachable"."""
        return bool(self.base_url and self.token)

    def start(self) -> None:
        if not self.available:
            logging.info(
                "No Home Assistant API access available (add-on missing "
                "homeassistant_api, or HEMERA_HA_URL/HEMERA_HA_TOKEN not set "
                "outside the add-on) — HA connector disabled"
            )
            return
        self._task = asyncio.create_task(self._run_forever(), name="ha-client")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def resync_devices(self) -> None:
        """Re-run device sync against the last polled state list — used
        after un-excluding an entity so it reappears immediately instead of
        waiting for the next poll tick."""
        if self._last_states is not None:
            self._sync_entities(self._last_states)

    async def _run_forever(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            try:
                states = await loop.run_in_executor(None, self._fetch_states)
                self._connected = True
                self._last_states = states
                self._sync_entities(states)
            except Exception as exc:  # noqa: BLE001 — one bad poll must not kill the loop
                self._connected = False
                logging.warning("Home Assistant API poll failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=_POLL_INTERVAL_S)
            except TimeoutError:
                pass

    def _fetch_states(self) -> list[dict]:
        req = urllib.request.Request(
            f"{self.base_url}/states",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_S) as resp:
            return json.loads(resp.read())

    def _find_light_by_entity_id(self, entity_id: str):
        for light in self.cfg.yaml_config["lights"].values():
            if light.protocol == "ha" and light.protocol_cfg.get("entity_id") == entity_id:
                return light
        return None

    def _sync_entities(self, states: list[dict]) -> None:
        excluded = self.cfg.yaml_config["config"].get("excluded_devices", {}).get("ha", {})
        for entity in states:
            entity_id = entity.get("entity_id", "")
            if not entity_id.startswith("light.") or entity_id in excluded:
                continue

            existing = self._find_light_by_entity_id(entity_id)
            attributes = entity.get("attributes", {})
            friendly_name = attributes.get("friendly_name", entity_id)

            if existing is not None:
                if existing.protocol_cfg.get("friendly_name") != friendly_name:
                    existing.protocol_cfg["friendly_name"] = friendly_name
                    self.cfg.mark_dirty("lights")
                self._update_light_state(existing, entity)
                continue

            # Don't create a light from an entity HA itself doesn't have real
            # data for yet (e.g. still loading right after a HA restart) —
            # we'd have nothing sensible to pick a modelid or initial state
            # from; it'll be picked up on a later poll once it settles.
            if entity.get("state") in ("unavailable", "unknown"):
                continue

            modelid = _pick_modelid(attributes)
            protocol_cfg = {
                "entity_id": entity_id,
                "friendly_name": friendly_name,
                "ha_server": {"baseUrl": self.base_url, "token": self.token},
            }
            add_new_light(self.cfg, modelid, friendly_name, "ha", protocol_cfg)

    def _update_light_state(self, light, entity: dict) -> None:
        """Apply an entity's *current* state to `light`, but only include a
        field in what actually gets applied/pushed if it changed.

        Unlike mqtt_client.py's equivalent, which can assume a Z2M message
        only ever contains the properties that actually changed, HA's
        `/states` poll always returns the entity's *entire* current
        snapshot — every attribute present every time, whether or not it
        moved since the last poll. Comparing against `light.state` here is
        what keeps this from re-pushing (and re-logging) an identical
        eventstream update every _POLL_INTERVAL_S regardless of whether
        anything actually happened.
        """
        state_str = entity.get("state")
        attributes = entity.get("attributes", {})
        changed: dict = {}

        reachable = state_str != "unavailable"
        if reachable != light.state.get("reachable", True):
            changed["reachable"] = reachable
        if state_str in ("on", "off"):
            on = state_str == "on"
            if on != light.state.get("on"):
                changed["on"] = on
        brightness = attributes.get("brightness")
        if brightness is not None:
            bri = round(brightness / 255 * 254)
            if bri != light.state.get("bri"):
                changed["bri"] = bri
        xy = attributes.get("xy_color")
        if xy:
            xy_list = [xy[0], xy[1]]
            if xy_list != light.state.get("xy"):
                changed["xy"] = xy_list
                changed["colormode"] = "xy"
        color_temp_kelvin = attributes.get("color_temp_kelvin")
        if color_temp_kelvin:
            ct = round(1_000_000 / color_temp_kelvin)
            if ct != light.state.get("ct"):
                changed["ct"] = ct
                changed["colormode"] = "ct"

        if not changed:
            return
        light.state.update(changed)

        # Same reasoning as mqtt_client.py's _update_light_state: without
        # this, the Hue app never learns about a state change that came from
        # HA (another integration, an automation, the HA dashboard) until it
        # happens to make a fresh GET.
        v2_state = v1_state_to_v2(changed)
        if v2_state:
            logging.info("HA state change for %s -> pushing eventstream update: %s", light.name, v2_state)
            light.genStreamEvent(v2_state)
