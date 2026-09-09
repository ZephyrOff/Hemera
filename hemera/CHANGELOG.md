# Changelog

## 0.2.0

- Découverte SSDP/UPnP (M-SEARCH + NOTIFY), en complément du mDNS.
- Hue Entertainment : serveur DTLS-PSK (port 2100/udp), parsing HueStream
  v1/v2, moteur de streaming avec dédup par tolérance et limitation de débit
  à intervalle fixe (configurable, `entertainment_fps`), agrégation des
  segments pour les bandeaux Gradient (Z2M `gradient`), câblé sur le
  démarrage/arrêt d'une zone Entertainment via les API v1 et v2.
  Démarrage tolérant aux pannes : si le runtime OpenSSL 3.x est absent, le
  reste du pont (pairing, lumières, groupes, scènes) continue de fonctionner
  normalement — seul le streaming Entertainment est indisponible.
- Nouvelle option `entertainment_fps` (débit de mise à jour, 1-30 Hz).

## 0.1.0

- Première version packagée en add-on Home Assistant.
- API Hue v1 (pairing, lights, groups, scenes).
- API Hue v2/CLIP (HTTPS, eventstream SSE, entertainment_configuration
  avec démarrage/arrêt de zone Entertainment).
- Auto-découverte des lumières Zigbee2MQTT, publication des commandes.
- Découverte mDNS.
- Pas encore implémenté à cette version : SSDP, serveur DTLS/HueStream (Hue
  Entertainment avec la Sync Box), capteurs/interrupteurs Zigbee.
