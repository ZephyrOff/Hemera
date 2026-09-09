"""Add a newly-discovered Zigbee2MQTT light to the bridge's config.

Adapted from diyHue's BridgeEmulator/lights/discover.py (Apache-2.0) — see
/NOTICE. Trimmed to just ``add_new_light`` (the only piece
hemera.services.mqtt_client needs) — diyHue's network-scan orchestration for
its other 21 protocols is dropped entirely, along with the module-level
imports that pulled all of them in.

Bug fixed relative to the original: diyHue's ``addNewLight`` mutates
``lightTypes[modelid]`` **in place** and hands that same dict to ``Light()``,
so every light created with the same modelid ends up sharing one ``state``/
``config`` dict instance — turning one such light on would misreport the
others as on too. Here we deep-copy the template first.
"""

from __future__ import annotations

from copy import deepcopy

from hemera.lights.light_types import lightTypes
from hemera.logging_setup import get_logger
from hemera.objects.light import Light

logging = get_logger(__name__)


def next_free_id(resource: dict) -> str:
    i = 1
    while str(i) in resource:
        i += 1
    return str(i)


def add_new_light(bridge_config, modelid: str, name: str, protocol: str, protocol_cfg: dict) -> str | bool:
    yaml_config = bridge_config.yaml_config
    if modelid not in lightTypes:
        logging.error("Unknown modelid %s — cannot add light %s", modelid, name)
        return False

    new_id = next_free_id(yaml_config["lights"])
    data = deepcopy(lightTypes[modelid])
    data.update({"name": name, "id_v1": new_id, "modelid": modelid, "protocol": protocol, "protocol_cfg": protocol_cfg})
    light = Light(data)
    yaml_config["lights"][new_id] = light
    yaml_config["groups"]["0"].add_light(light)
    rooms = [g.id_v2 for k, g in yaml_config["groups"].items() if k != "0"]
    lights = [light_obj.id_v2 for light_obj in yaml_config["lights"].values()]
    yaml_config["groups"]["0"].groupZeroStream(rooms, lights)
    bridge_config.mark_dirty("lights")
    logging.info("Added light %s (%s, id=%s)", name, modelid, new_id)
    return new_id
