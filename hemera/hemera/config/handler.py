"""YAML-backed config persistence — one file per resource, debounced saves.

Adapted from diyHue's BridgeEmulator/configManager/configHandler.py
(Apache-2.0) — see /NOTICE. Trimmed to the resources this project's Step 1
scope covers: config (incl. paired users), lights, groups (incl. Entertainment
areas), scenes. Sensors/rules/schedules/etc. are deliberately out of scope for
now (see the project plan) but nothing here blocks adding their YAML files
back later on the same pattern.

Design note: ``yaml_config`` is created once, non-None, at ``Config()``
construction and only ever mutated in place (``.clear()`` + ``.update()``),
never reassigned — every module that does
``from hemera.config.handler import bridge_config`` and reads
``bridge_config.yaml_config`` at import time keeps seeing live data after
``load_config()``/``reset_config()`` run, exactly as in the original.
"""

from __future__ import annotations

import glob
import os
import shutil
import threading
import time
import uuid
import weakref
from copy import deepcopy

import yaml

from hemera.logging_setup import get_logger
from hemera.objects.api_user import ApiUser
from hemera.objects.entertainment_configuration import EntertainmentConfiguration
from hemera.objects.group import Group
from hemera.objects.light import Light
from hemera.objects.scene import Scene

logging = get_logger(__name__)


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):  # noqa: ARG002
        return True


def _safe_open_yaml(path: str, default: dict | None = None) -> dict:
    """Load a YAML file; corrupt files are renamed to `<path>.corrupt` rather than crashing."""
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, encoding="utf-8") as fp:
            data = yaml.load(fp, Loader=yaml.FullLoader)
    except Exception as exc:  # noqa: BLE001
        logging.error("Failed to parse %s: %s", path, exc)
        try:
            os.rename(path, path + ".corrupt")
            logging.warning("Renamed corrupt config to %s.corrupt — starting with defaults", path)
        except OSError as exc2:
            logging.error("Could not rename corrupt file %s: %s", path, exc2)
        return default if default is not None else {}
    if data is None:
        return default if default is not None else {}
    if not isinstance(data, dict):
        logging.error("%s is not a dict (got %s), renaming", path, type(data).__name__)
        try:
            os.rename(path, path + ".corrupt")
        except OSError:
            pass
        return default if default is not None else {}
    return data


def _write_yaml(path: str, contents: dict) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fp:
        yaml.dump(contents, fp, Dumper=NoAliasDumper, allow_unicode=True, sort_keys=False)
    os.replace(tmp_path, path)  # atomic on the same filesystem


class Config:
    CONFIG_FILES = {
        "config": "config.yaml",
        "lights": "lights.yaml",
        "groups": "groups.yaml",
        "scenes": "scenes.yaml",
    }

    def __init__(self, config_dir: str) -> None:
        self.configDir = config_dir
        os.makedirs(self.configDir, exist_ok=True)
        self._save_lock = threading.RLock()
        self._dirty_resources: set[str] = set()
        self._last_dirty_time = 0.0
        self._save_debounce_s = 5.0
        # Never None, never reassigned — see module docstring.
        self.yaml_config: dict = {
            "apiUsers": {}, "lights": {}, "groups": {}, "scenes": {}, "config": {},
            "temp": {"eventstream": []},
        }

    def _config_path(self, resource: str, subdir: str | None = None) -> str:
        if subdir:
            return os.path.join(self.configDir, subdir, self.CONFIG_FILES[resource])
        return os.path.join(self.configDir, self.CONFIG_FILES[resource])

    def mark_dirty(self, resource: str) -> None:
        if resource not in self.CONFIG_FILES:
            return
        with self._save_lock:
            self._dirty_resources.add(resource)
            self._last_dirty_time = time.time()

    def save_dirty_if_needed(self) -> None:
        """Call periodically (e.g. from a background asyncio task) to flush debounced writes."""
        if not self._dirty_resources:
            return
        if not self._save_lock.acquire(blocking=False):
            return
        try:
            if time.time() - self._last_dirty_time < self._save_debounce_s:
                return
            to_save = list(self._dirty_resources)
            self._dirty_resources.clear()
        finally:
            self._save_lock.release()
        for resource in to_save:
            try:
                self.save_config(resource=resource)
            except Exception as exc:  # noqa: BLE001
                logging.error("Failed to save %s: %s", resource, exc)
                with self._save_lock:
                    self._dirty_resources.add(resource)

    def load_config(self, default_config: dict) -> None:
        """(Re)populate ``yaml_config`` in place from disk, seeding missing files from `default_config`."""
        self.yaml_config.clear()
        self.yaml_config.update({
            "apiUsers": {}, "lights": {}, "groups": {}, "scenes": {}, "config": {},
            "temp": {"eventstream": []},
        })

        # config (+ paired users, stored under its "whitelist" key)
        if os.path.exists(self._config_path("config")):
            config = _safe_open_yaml(self._config_path("config")) or dict(default_config)
            whitelist = config.pop("whitelist", {})
            for user, data in whitelist.items():
                try:
                    self.yaml_config["apiUsers"][user] = ApiUser(
                        user, data["name"], data["client_key"], data["create_date"], data["last_use_date"]
                    )
                except Exception as exc:  # noqa: BLE001
                    logging.error("Skipping corrupt apiUser %s: %s", user, exc)
        else:
            config = dict(default_config)
        # Migrate excluded_devices from the old flat {ieee: name} shape (a
        # single MQTT/Z2M-only exclusion list) to the per-connector
        # {"mqtt": {ieee: name}, "ha": {entity_id: name}} shape the HA
        # connector needs (entity_ids and ieee addresses share no format,
        # but excluding one shouldn't require knowing the other exists).
        excluded = config.get("excluded_devices", {})
        if "mqtt" not in excluded and "ha" not in excluded:
            config["excluded_devices"] = {"mqtt": excluded, "ha": {}}
            self.mark_dirty("config")
        else:
            excluded.setdefault("mqtt", {})
            excluded.setdefault("ha", {})
        self.yaml_config["config"] = config

        # lights
        if os.path.exists(self._config_path("lights")):
            for light_id, data in (_safe_open_yaml(self._config_path("lights")) or {}).items():
                try:
                    data["id_v1"] = light_id
                    self.yaml_config["lights"][light_id] = Light(data)
                except Exception as exc:  # noqa: BLE001
                    logging.error("Skipping corrupt light %s: %s", light_id, exc)

        # group 0 (all lights) always exists, like a real bridge
        self.yaml_config["groups"]["0"] = Group({
            "name": "Group 0", "id_v1": "0", "type": "LightGroup",
            "state": {"all_on": False, "any_on": True}, "recycle": False,
        })
        for light in self.yaml_config["lights"].values():
            self.yaml_config["groups"]["0"].add_light(light)

        # groups (rooms/zones/entertainment areas)
        if os.path.exists(self._config_path("groups")):
            for group_id, data in (_safe_open_yaml(self._config_path("groups")) or {}).items():
                try:
                    data["id_v1"] = group_id
                    if data.get("type") == "Entertainment":
                        group = EntertainmentConfiguration(data)
                        self.yaml_config["groups"][group_id] = group
                        for light_id in data.get("lights", []):
                            if light_id in self.yaml_config["lights"]:
                                group.add_light(self.yaml_config["lights"][light_id])
                            else:
                                logging.warning("Group %s references missing light %s — skipping", group_id, light_id)
                        for light_id, location in data.get("locations", {}).items():
                            if light_id in self.yaml_config["lights"]:
                                group.locations[self.yaml_config["lights"][light_id]] = location
                    else:
                        owner_ref = data.get("owner")
                        if self.yaml_config["apiUsers"]:
                            first_user = next(iter(self.yaml_config["apiUsers"].values()))
                            data["owner"] = self.yaml_config["apiUsers"].get(owner_ref, first_user)
                        else:
                            data["owner"] = None
                        group = Group(data)
                        self.yaml_config["groups"][group_id] = group
                        for light_id in data.get("lights", []):
                            if light_id in self.yaml_config["lights"]:
                                group.add_light(self.yaml_config["lights"][light_id])
                            else:
                                logging.warning("Group %s references missing light %s — skipping", group_id, light_id)
                except Exception as exc:  # noqa: BLE001
                    logging.error("Skipping corrupt group %s: %s", group_id, exc)

        # scenes
        if os.path.exists(self._config_path("scenes")):
            for scene_id, data in (_safe_open_yaml(self._config_path("scenes")) or {}).items():
                try:
                    data["id_v1"] = scene_id
                    if data.get("type") == "GroupScene":
                        if data["group"] not in self.yaml_config["groups"]:
                            logging.warning("Scene %s references missing group %s — skipping", scene_id, data.get("group"))
                            continue
                        group_ref = weakref.ref(self.yaml_config["groups"][data["group"]])
                        data["lights"] = group_ref().lights
                        data["group"] = group_ref
                    else:
                        objs = []
                        for light_id in data.get("lights", []):
                            if light_id in self.yaml_config["lights"]:
                                objs.append(weakref.ref(self.yaml_config["lights"][light_id]))
                            else:
                                logging.warning("Scene %s references missing light %s — skipping", scene_id, light_id)
                        data["lights"] = objs
                    if data.get("owner") not in self.yaml_config["apiUsers"]:
                        logging.warning("Scene %s references missing owner %s — skipping", scene_id, data.get("owner"))
                        continue
                    data["owner"] = self.yaml_config["apiUsers"][data["owner"]]
                    scene = Scene(data)
                    self.yaml_config["scenes"][scene_id] = scene
                    for light_id, lightstate in data.get("lightstates", {}).items():
                        if light_id in self.yaml_config["lights"]:
                            scene.lightstates[self.yaml_config["lights"][light_id]] = lightstate
                except Exception as exc:  # noqa: BLE001
                    logging.error("Skipping corrupt scene %s: %s", scene_id, exc)

        self.yaml_config["config"]["whitelist"] = {
            user: obj.save() for user, obj in self.yaml_config["apiUsers"].items()
        }
        logging.info("Config loaded from %s", self.configDir)

    def save_config(self, resource: str = "all") -> None:
        if not self._save_lock.acquire(blocking=True, timeout=10):
            logging.warning("save_config(%s) timed out waiting for lock", resource)
            return
        try:
            if resource in ("all", "config"):
                config_write = deepcopy(self.yaml_config["config"])
                config_write["whitelist"] = {u: o.save() for u, o in self.yaml_config["apiUsers"].items()}
                _write_yaml(self._config_path("config"), config_write)
                if resource == "config":
                    return
            resources = [r for r in self.CONFIG_FILES if r != "config"] if resource == "all" else [resource]
            for res in resources:
                file_path = self._config_path(res)
                dump: dict = {}
                for key, obj in self.yaml_config[res].items():
                    if key == "0":  # synthetic group 0, never persisted
                        continue
                    saved = obj.save()
                    if saved:
                        dump[obj.id_v1] = saved
                if not dump and os.path.exists(file_path + ".corrupt"):
                    logging.warning("Refusing to overwrite %s with empty data — .corrupt backup exists", file_path)
                    continue
                _write_yaml(file_path, dump)
        finally:
            self._save_lock.release()

    def reset_config(self, default_config: dict) -> None:
        self.save_config()
        with self._save_lock:
            for yf in glob.glob(os.path.join(self.configDir, "*.yaml")):
                try:
                    os.remove(yf)
                except OSError as exc:
                    logging.error("Failed to remove %s during reset: %s", yf, exc)
            self._dirty_resources.clear()
            self._last_dirty_time = 0.0
            self.load_config(default_config)

    def restore_backup(self) -> None:
        backup_dir = os.path.join(self.configDir, "backup")
        if not os.path.isdir(backup_dir):
            raise ValueError("No backup directory found")
        backup_files = glob.glob(os.path.join(backup_dir, "*.yaml"))
        if not backup_files:
            raise ValueError("Backup directory is empty")
        for bf in backup_files:
            with open(bf, encoding="utf-8") as fp:
                data = yaml.load(fp, Loader=yaml.FullLoader)
            if not isinstance(data, dict):
                raise ValueError(f"Backup file {os.path.basename(bf)} is corrupt or empty")
        with self._save_lock:
            for yf in glob.glob(os.path.join(self.configDir, "*.yaml")):
                os.remove(yf)
            for bf in backup_files:
                shutil.copy2(bf, self.configDir)
            self._dirty_resources.clear()
            self._last_dirty_time = 0.0


def default_config(bridge_id: str, mac: str, host_ip: str) -> dict:
    return {
        "bridgeid": bridge_id.upper(),
        "mac": mac,
        "name": "Hemera Bridge",
        "ipaddress": host_ip,
        "netmask": "255.255.255.0",
        "gateway": host_ip.rsplit(".", 1)[0] + ".1",
        # Matches Bifrost's currently-shipped defaults
        # (crates/hue/src/lib.rs: HUE_BRIDGE_V2_DEFAULT_APIVERSION /
        # _SWVERSION) rather than an older, lower version. The Hue app
        # compares the bridge's reported version against the latest real
        # firmware it knows about and nags "your bridge needs an update" (with
        # no actual update possible, since this isn't real Signify hardware)
        # if it looks outdated — bumping these to Bifrost's proven, currently
        # up-to-date values avoids that permanently-stuck update prompt.
        "apiversion": "1.70.0",
        "swversion": "1970084010",
        "timezone": "Europe/Paris",
        "linkbutton": {"lastlinkbuttonpushed": 0},
        "mqtt": {"host": "127.0.0.1", "port": 1883, "user": "", "password": "", "base_topic": "zigbee2mqtt"},
        "portalservices": False,
        "zigbeechannel": 25,
        # Per-connector: "mqtt" keyed by ieee_address, "ha" keyed by entity_id
        # — either -> last known friendly_name, set via the admin panel.
        "excluded_devices": {"mqtt": {}, "ha": {}},
    }


def make_bridge_id(mac: str) -> str:
    """16 hex-char bridge id, Zigbee-EUI64-style expansion of a 6-byte MAC (matches real Hue bridges)."""
    mac = mac.replace(":", "").lower()
    return (mac[:6] + "fffe" + mac[6:]).upper()
