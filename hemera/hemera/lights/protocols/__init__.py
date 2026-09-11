"""Light backends. Trimmed from diyHue's 22-protocol list (Apache-2.0, see
/NOTICE) down to the two this project targets: Zigbee2MQTT (via MQTT) and
light entities from other Home Assistant integrations (via HA's own REST
API).

``Light.setV1State`` matches ``self.protocol`` against each module's
``__name__`` in this list — keep that behaviour when adding a protocol back.
"""

from hemera.lights.protocols import ha, mqtt

protocols = [mqtt, ha]
