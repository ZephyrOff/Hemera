"""Static per-model capability templates used to present a Zigbee2MQTT light
as a specific Hue product to the Hue app / Sync Box.

Adapted from diyHue's BridgeEmulator/lights/light_types.py (Apache-2.0) — see
/NOTICE. Trimmed to the models our MQTT auto-discovery (bridge/lights/protocols/mqtt.py)
actually picks between (color+CT, color-only, CT-only, dimmable, on/off, and the
gradient lightstrip models used for Zigbee2MQTT "gradient"-capable strips).

IMPORTANT: every value here is a *template*. ``hemera.lights.discover.add_new_light``
deep-copies it before use — never hand out these nested dicts directly, or every
light created with the same modelid ends up sharing (and corrupting) the same
``state``/``config`` dict instances.
"""

from __future__ import annotations

lightTypes: dict[str, dict] = {
    # Hue White and Color Ambiance A19 (xy + ct) — our default "full colour" model
    "LCT015": {
        "v1_static": {
            "type": "Extended color light",
            "swversion": "1.104.2",
            "swconfigid": "772B0E5E",
            "productid": "Philips-LCT015-1-A19ECLv5",
            "manufacturername": "Signify Netherlands B.V.",
            "swupdate": {"state": "noupdates", "lastinstall": "2020-12-09T19:13:52"},
            "capabilities": {
                "certified": True,
                "control": {
                    "colorgamut": [[0.6915, 0.3083], [0.17, 0.7], [0.1532, 0.0475]],
                    "colorgamuttype": "C",
                    "ct": {"max": 500, "min": 153},
                    "maxlumen": 800,
                    "mindimlevel": 1000,
                },
                "streaming": {"proxy": False, "renderer": True},
            },
        },
        "device": {
            "certified": True,
            "manufacturer_name": "Signify Netherlands B.V.",
            "product_archetype": "sultan_bulb",
            "product_name": "Hue color lamp",
            "software_version": "1.104.2",
        },
        "state": {
            "on": False, "bri": 200, "hue": 0, "sat": 0, "xy": [0.0, 0.0], "ct": 461,
            "alert": "none", "mode": "homeautomation", "effect": "none",
            "colormode": "ct", "reachable": True,
        },
        "config": {"archetype": "sultanbulb", "function": "mixed", "direction": "omnidirectional",
                    "startup": {"mode": "safety", "configured": True}},
        "dynamics": {"speed": 0, "speed_valid": False, "status": "none", "status_values": ["none", "dynamic_palette"]},
    },
    # Colour only (no CT) — Hue Iris-style
    "LLC010": {
        "v1_static": {
            "type": "Color Gamut light", "manufacturername": "Signify Netherlands B.V.", "swversion": "1.104.2",
            "swupdate": {"state": "noupdates", "lastinstall": "2020-12-09T19:13:52"},
            "capabilities": {
                "certified": True,
                "control": {"colorgamut": [[0.704, 0.296], [0.215, 0.711], [0.138, 0.08]],
                            "colorgamuttype": "A", "maxlumen": 600, "mindimlevel": 5000},
                "streaming": {"renderer": False, "proxy": False},
            },
        },
        "device": {"certified": True, "manufacturer_name": "Signify Netherlands B.V.",
                    "product_archetype": "hueiris", "product_name": "Dimmable light", "software_version": "1.76.6"},
        "state": {"alert": "none", "bri": 0, "colormode": "xy", "effect": "none", "hue": 0,
                   "mode": "homeautomation", "on": False, "reachable": True, "sat": 0, "xy": [0.408, 0.517]},
        "config": {"archetype": "hueiris", "function": "functional", "direction": "omnidirectional",
                    "startup": {"mode": "safety", "configured": True}},
        "dynamics": {"speed": 0, "speed_valid": False, "status": "none", "status_values": ["none", "dynamic_palette"]},
    },
    # Colour temperature only
    "LTW001": {
        "v1_static": {
            "type": "Color temperature light", "manufacturername": "Signify Netherlands B.V.", "swversion": "1.104.2",
            "swupdate": {"state": "noupdates", "lastinstall": "2020-12-09T19:13:52"},
            "capabilities": {"certified": True,
                              "control": {"mindimlevel": 1000, "maxlumen": 806, "ct": {"min": 153, "max": 454}},
                              "streaming": {"renderer": False, "proxy": False}},
        },
        "device": {"certified": True, "manufacturer_name": "Signify Netherlands B.V.",
                    "product_archetype": "classic_bulb", "product_name": "Dimmable light", "software_version": "1.76.6"},
        "state": {"on": False, "colormode": "ct", "alert": "none", "mode": "homeautomation",
                   "reachable": True, "bri": 254, "ct": 230},
        "config": {"archetype": "classicbulb", "function": "functional", "direction": "omnidirectional",
                    "startup": {"mode": "safety", "configured": True}},
        "dynamics": {"speed": 0, "speed_valid": False, "status": "none", "status_values": ["none", "dynamic_palette"]},
    },
    # Dimmable only (brightness, no colour)
    "LWB010": {
        "v1_static": {
            "type": "Dimmable light", "swversion": "1.50.2_r30933", "manufacturername": "Signify Netherlands B.V.",
            "productid": "Philips-LWB010-1-A19DLv4",
            "swupdate": {"state": "noupdates", "lastinstall": "2020-12-09T19:13:52"},
            "capabilities": {"certified": True, "control": {"mindimlevel": 5000, "maxlumen": 806},
                              "streaming": {"renderer": False, "proxy": False}},
        },
        "device": {"certified": True, "manufacturer_name": "Signify Netherlands B.V.",
                    "product_archetype": "classic_bulb", "product_name": "Color temperature light", "software_version": "1.104.2"},
        "state": {"on": False, "bri": 254, "alert": "none", "mode": "homeautomation", "reachable": True},
        "config": {"archetype": "classicbulb", "function": "mixed", "direction": "omnidirectional",
                    "startup": {"mode": "safety", "configured": True}},
        "dynamics": {"speed": 0, "speed_valid": False, "status": "none", "status_values": ["none", "dynamic_palette"]},
    },
    # On/off only
    "LOM001": {
        "v1_static": {
            "type": "On/Off plug-in unit", "manufacturername": "Signify Netherlands B.V.",
            "productname": "Hue Smart plug", "swversion": "1.104.2", "swconfigid": "A641B5AB",
            "productid": "SmartPlug_OnOff_v01-00_01",
            "swupdate": {"state": "noupdates", "lastinstall": "2020-12-09T19:13:52"},
            "capabilities": {"certified": True, "control": {}, "streaming": {"renderer": False, "proxy": False}},
        },
        "device": {"certified": True, "manufacturer_name": "Signify Netherlands B.V.", "model_id": "LOM001",
                    "product_archetype": "plug", "product_name": "Hue Smart plug", "software_version": "1.104.2"},
        "state": {"on": False, "alert": "select", "mode": "homeautomation", "reachable": True},
        "config": {"archetype": "plug", "function": "functional", "direction": "omnidirectional",
                    "startup": {"mode": "safety", "configured": True}},
        "dynamics": {"status": "none", "status_values": ["none"]},
    },
    # Hue Gradient Lightstrip (7-segment) — our template for any Z2M light with "gradient" capability
    "LCX004": {
        "v1_static": {
            "type": "Extended color light", "manufacturername": "Signify Netherlands B.V.",
            "productname": "Hue gradient lightstrip", "swversion": "1.94.2", "swconfigid": "DC0A18AF",
            "productid": "4422-9482-0441_HG01_PSU03",
            "swupdate": {"state": "noupdates", "lastinstall": "2022-01-13T22:54:51"},
            "capabilities": {
                "certified": True,
                "control": {"mindimlevel": 100, "maxlumen": 1600, "colorgamuttype": "C",
                            "colorgamut": [[0.6915, 0.3083], [0.1700, 0.7000], [0.1532, 0.0475]],
                            "ct": {"min": 153, "max": 500}},
                "streaming": {"renderer": True, "proxy": True},
            },
        },
        "device": {"certified": True, "hardware_platform_type": "100b-118",
                    "manufacturer_name": "Signify Netherlands B.V.", "model_id": "LCX004",
                    "product_archetype": "hue_lightstrip", "product_name": "Hue gradient lightstrip",
                    "software_version": "1.94.2"},
        "state": {"on": False, "bri": 254, "hue": 8417, "sat": 140, "effect": "none", "xy": [0.0, 0.0],
                   "ct": 366, "alert": "select", "colormode": "ct", "mode": "homeautomation",
                   "reachable": True, "gradient": {"points": []}},
        "config": {"archetype": "huelightstrip", "function": "mixed", "direction": "omnidirectional",
                    "startup": {"mode": "safety", "configured": False}},
        "dynamics": {"speed": 0, "speed_valid": False, "status": "none", "status_values": ["none", "dynamic_palette"]},
    },
    # Hue color spot (GU10-shaped) — same capability class as LCT015 (colour+CT)
    # but a distinct archetype/icon, useful for GU10-style Zigbee spots.
    "LCG001": {
        "v1_static": {
            "type": "Extended color light", "manufacturername": "Signify Netherlands B.V.", "swversion": "1.104.2",
            "swupdate": {"state": "noupdates", "lastinstall": "2020-12-09T19:13:52"},
            "capabilities": {
                "certified": True,
                "control": {"colorgamut": [[0.675, 0.322], [0.409, 0.518], [0.167, 0.04]],
                            "colorgamuttype": "B", "ct": {"max": 500, "min": 153},
                            "maxlumen": 600, "mindimlevel": 5000},
                "streaming": {"proxy": False, "renderer": True},
            },
        },
        "device": {"certified": True, "manufacturer_name": "Signify Netherlands B.V.",
                    "product_archetype": "sultan_bulb", "product_name": "Hue color spot",
                    "software_version": "1.104.2"},
        "state": {"alert": "none", "bri": 0, "colormode": "xy", "effect": "none", "hue": 0,
                   "mode": "homeautomation", "on": False, "reachable": True, "sat": 0, "xy": [0.408, 0.517]},
        "config": {"archetype": "sultanbulb", "direction": "omnidirectional", "function": "mixed",
                    "startup": {"configured": True, "mode": "safety"}},
        "dynamics": {"speed": 0, "speed_valid": False, "status": "none", "status_values": ["none", "dynamic_palette"]},
    },
    # Hue Lightstrip Plus — colour+CT like LCT015, but presented with the
    # lightstrip archetype/icon instead of a bulb; for a single-colour (non
    # gradient-segmented) Z2M LED strip.
    "LST002": {
        "v1_static": {
            "type": "Color light", "manufacturername": "Signify Netherlands B.V.", "swversion": "1.104.2",
            "productname": "Hue lightstrip plus", "swconfigid": "59F2C3A3",
            "productid": "Philips-LST002-1-LedStripsv3",
            "swupdate": {"state": "noupdates", "lastinstall": "2020-12-09T19:13:52"},
            "capabilities": {
                "certified": True,
                "control": {"mindimlevel": 40, "maxlumen": 1600, "colorgamuttype": "C",
                            "colorgamut": [[0.6915, 0.3083], [0.17, 0.7], [0.1532, 0.0475]],
                            "ct": {"min": 153, "max": 500}},
                "streaming": {"renderer": True, "proxy": True},
            },
        },
        "device": {"certified": True, "manufacturer_name": "Signify Netherlands B.V.",
                    "product_archetype": "hue_lightstrip", "product_name": "Hue lightstrip plus",
                    "software_version": "1.104.2"},
        "state": {"on": False, "bri": 200, "hue": 0, "sat": 0, "xy": [0.0, 0.0], "ct": 461,
                   "alert": "none", "mode": "homeautomation", "effect": "none",
                   "colormode": "ct", "reachable": True},
        "config": {"archetype": "huelightstrip", "function": "mixed", "direction": "omnidirectional",
                    "startup": {"mode": "safety", "configured": False}},
        "dynamics": {"speed": 0, "speed_valid": False, "status": "none", "status_values": ["none", "dynamic_palette"]},
    },
    # Hue Play Gradient Lightstrip (TV backlight variant) — same gradient
    # family as LCX004 but the real product has only 3 physical zones
    # (get_v2_entertainment() already branches on this modelid specifically),
    # matching a common real-world "why is my gradient limited to 3 points"
    # case for this exact product.
    "LCX002": {
        "v1_static": {
            "type": "Extended color light", "manufacturername": "Signify Netherlands B.V.",
            "productname": "Hue play gradient lightstrip", "swversion": "1.104.2", "swconfigid": "C74E5108",
            "productid": "Philips-LCX002-1-LedStripPXv1",
            "swupdate": {"state": "noupdates", "lastinstall": "2020-11-02T19:46:12"},
            "capabilities": {
                "certified": True,
                "control": {"mindimlevel": 100, "maxlumen": 1600, "colorgamuttype": "C",
                            "colorgamut": [[0.6915, 0.3083], [0.1700, 0.7000], [0.1532, 0.0475]],
                            "ct": {"min": 153, "max": 500}},
                "streaming": {"renderer": True, "proxy": True},
            },
        },
        "device": {"certified": True, "manufacturer_name": "Signify Netherlands B.V.", "model_id": "LCX002",
                    "product_archetype": "hue_lightstrip_tv", "product_name": "Hue play gradient lightstrip",
                    "software_version": "1.104.2"},
        "state": {"on": False, "bri": 254, "hue": 8417, "sat": 140, "effect": "none", "xy": [0.0, 0.0],
                   "ct": 366, "alert": "select", "colormode": "ct", "mode": "homeautomation",
                   "reachable": True, "gradient": {"points": []}},
        "config": {"archetype": "huelightstriptv", "function": "mixed", "direction": "omnidirectional",
                    "startup": {"mode": "safety", "configured": False}},
        "dynamics": {"speed": 0, "speed_valid": False, "status": "none", "status_values": ["none", "dynamic_palette"]},
    },
    # Hue Signe Gradient floor lamp — gradient family, distinct archetype.
    "915005987201": {
        "v1_static": {
            "type": "Extended color light", "manufacturername": "Signify Netherlands B.V.",
            "productname": "Signe gradient floor", "swversion": "1.94.2", "swconfigid": "DC0A18AF",
            "productid": "4422-9482-0441_HG01_PSU03",
            "swupdate": {"state": "noupdates", "lastinstall": "2022-01-13T22:54:51"},
            "capabilities": {
                "certified": True,
                "control": {"mindimlevel": 100, "maxlumen": 1600, "colorgamuttype": "C",
                            "colorgamut": [[0.6915, 0.3083], [0.1700, 0.7000], [0.1532, 0.0475]],
                            "ct": {"min": 153, "max": 500}},
                "streaming": {"renderer": True, "proxy": True},
            },
        },
        "device": {"certified": True, "hardware_platform_type": "100b-118",
                    "manufacturer_name": "Signify Netherlands B.V.", "model_id": "915005987201",
                    "product_archetype": "hue_signe", "product_name": "Signe gradient floor",
                    "software_version": "1.94.2"},
        "state": {"on": False, "bri": 254, "hue": 8417, "sat": 140, "effect": "none", "xy": [0.0, 0.0],
                   "ct": 366, "alert": "select", "colormode": "ct", "mode": "homeautomation",
                   "reachable": True, "gradient": {"points": []}},
        "config": {"archetype": "huesigne", "function": "decorative", "direction": "horizontal",
                    "startup": {"mode": "safety", "configured": False}},
        "dynamics": {"speed": 0, "speed_valid": False, "status": "none", "status_values": ["none", "dynamic_palette"]},
    },
}

# Human-readable labels for the admin panel's "change model" picker — the
# templates' own product_name fields are copied verbatim from real (and
# inconsistently-named, e.g. LWB010's says "Color temperature light" despite
# being dimmable-only) Philips SKUs, not written for picking one apart from
# another by capability.
MODEL_CHOICES: list[tuple[str, str]] = [
    ("LCT015", "Couleur + température (par défaut)"),
    ("LLC010", "Couleur uniquement"),
    ("LTW001", "Température de couleur uniquement"),
    ("LWB010", "Intensité réglable uniquement (pas de couleur)"),
    ("LOM001", "Prise On/Off uniquement"),
    ("LCG001", "Spot couleur (GU10)"),
    ("LST002", "Bandeau lumineux couleur (sans dégradé)"),
    ("LCX004", "Bandeau Gradient (couleur multi-points)"),
    ("LCX002", "Bandeau Gradient TV/Play (3 zones)"),
    ("915005987201", "Lampadaire Signe Gradient"),
]

# v1 "archetype" -> v2 "archetype" (dashes/case normalisation Hue uses between APIs).
archetype: dict[str, str] = {
    "sultanbulb": "sultan_bulb",
    "classicbulb": "classic_bulb",
    "hueiris": "hue_iris",
    "plug": "plug",
    "huelightstrip": "hue_lightstrip",
    "huelightstriptv": "hue_lightstrip_tv",
    "huesigne": "hue_signe",
    "unknownarchetype": "unknown_archetype",
}
