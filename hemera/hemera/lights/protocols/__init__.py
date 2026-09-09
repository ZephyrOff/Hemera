"""Light backends. Trimmed from diyHue's 22-protocol list (Apache-2.0, see
/NOTICE) down to the one this project targets: Zigbee2MQTT via MQTT.

``Light.setV1State`` matches ``self.protocol`` against each module's
``__name__`` in this list — keep that behaviour when adding a protocol back.
"""

from hemera.lights.protocols import mqtt

protocols = [mqtt]
