# Hemera

Pont Hue virtuel pour Zigbee2MQTT, packagé en **add-on Home Assistant**
(comme `diyhue/hassio-addon`). Il se comporte comme un Hue Bridge vis-à-vis
de l'application Hue et de la Hue Sync Box, avec Zigbee2MQTT comme unique
backend d'éclairage — Home Assistant reste hors de la boucle temps réel
(voir `document_etude.pdf` pour le cadrage complet du projet).

## Structure du dépôt

Ce dépôt est un **dépôt d'add-ons** Home Assistant (`repository.json` à la
racine) contenant un seul add-on pour l'instant :

```
repository.json          <- déclare ce dépôt à Home Assistant
hemera/                   <- l'add-on (contexte de build du Supervisor)
  config.yaml              <- manifeste de l'add-on
  build.yaml                <- images de base par architecture
  Dockerfile
  rootfs/                    <- script de démarrage s6-overlay
  translations/en.yaml
  DOCS.md                     <- doc affichée dans l'onglet Documentation de l'add-on
  pyproject.toml
  hemera/                       <- le code Python (package `hemera`)
```

## Installation sur votre serveur HA

1. **Réglages → Modules complémentaires → Boutique des modules → ⋮ (en haut
   à droite) → Dépôts**, ajouter l'URL de ce dépôt
   (`https://github.com/ZephyrOff/HAHB`).
2. Installer l'add-on **Hemera** qui apparaît dans la liste.
3. Configurer les options (voir `hemera/DOCS.md`) et démarrer.

Pas de configuration MQTT à saisir si Mosquitto tourne déjà comme add-on :
Hemera le détecte automatiquement via l'API Supervisor.

## État actuel (étapes 1 et 2 du plan)

Implémenté et testé (voir la section Tests) :

- API Hue v1 (aiohttp) : découverte, pairing, lights/groups/scenes.
- API Hue v2/CLIP (HTTPS, `hue-application-key`) : light/scene/room/zone/
  grouped_light/device/zigbee_connectivity/entertainment/
  entertainment_configuration, y compris la création et le démarrage/arrêt
  d'une zone Entertainment (`{"action": "start"|"stop"}` — le chemin que la
  Sync Box utilisera).
- Eventstream SSE v2 (`/eventstream/clip/v2`) pour les mises à jour en direct
  côté application Hue.
- Auto-découverte des lumières Zigbee2MQTT (`<base_topic>/bridge/devices`)
  et synchronisation d'état en direct.
- Publication des commandes vers Z2M (`<base_topic>/<friendly_name>/set`).
- Persistance YAML (un fichier par ressource) avec sauvegarde différée.
- Annonce mDNS (`_hue._tcp.local`).
- Certificat auto-signé généré au premier démarrage, servi par l'API v2.

Pas encore implémenté (voir le plan) : SSDP, Hue Entertainment
(DTLS/HueStream — la Sync Box elle-même), capteurs/interrupteurs Zigbee.

## Développement local (hors add-on)

Le code reste utilisable en dehors de Home Assistant, par exemple pour
développer/tester rapidement sans passer par un build d'add-on :

```bash
cd hemera
python -m venv .venv
. .venv/Scripts/activate   # ou: source .venv/bin/activate sous Linux/macOS
pip install -e .

export HEMERA_MQTT_HOST=192.168.1.10   # IP de votre broker MQTT (Mosquitto)
export HEMERA_MQTT_BASE_TOPIC=zigbee2mqtt
export HEMERA_HTTP_PORT=80             # 80 requiert les droits admin/root
python -m hemera.main
```

Variables d'environnement principales (voir `hemera/hemera/config/bootstrap.py`) :

| Variable | Défaut | Rôle |
|---|---|---|
| `HEMERA_CONFIG_DIR` | `./config` | Dossier des fichiers YAML persistés et du certificat (`/data` dans l'add-on) |
| `HEMERA_BIND_IP` | `0.0.0.0` | Interface d'écoute HTTP |
| `HEMERA_HOST_IP` | auto-détecté | IP annoncée aux clients Hue (mDNS, config) |
| `HEMERA_HTTP_PORT` / `HEMERA_HTTPS_PORT` | `80` / `443` | Ports des API Hue v1 / v2 |
| `HEMERA_MQTT_HOST` / `_PORT` / `_USER` / `_PASSWORD` | `127.0.0.1` / `1883` | Broker MQTT (auto-détecté dans l'add-on) |
| `HEMERA_MQTT_BASE_TOPIC` | `zigbee2mqtt` | Préfixe des topics Z2M |
| `HEMERA_BRIDGE_ID` / `HEMERA_MAC` | dérivés de la machine | Identité du pont |

Pairing : le bouton de couplage est armé automatiquement pendant 30 s au
démarrage. Passé ce délai, réarmez-le avec `PUT /api/{username}/config
{"linkbutton": true}`, ou sous Linux : `kill -USR1 <pid>`.

## Tests manuels effectués

Le cœur (modèle d'objets, persistance, auto-découverte MQTT, API v1 et v2) a
été validé de bout en bout avec un broker MQTT local et des requêtes HTTP
directes : pairing, création de lumière depuis une annonce Z2M simulée,
synchronisation d'état Z2M → API (v1 et v2), commande API → publication MQTT,
création de groupe/scène/zone Entertainment, rappel de scène, démarrage/arrêt
d'une zone Entertainment via v2 (`action: start`/`stop`), eventstream SSE, et
rechargement depuis le disque après redémarrage. Deux bugs réels ont été
trouvés et corrigés pendant ces tests (état de scène jamais capturé à la
création ; id manquant dans `Light.get_v2_entertainment`).

Non testé : un vrai client Hue (application officielle ou Sync Box), et le
build/déploiement réel de l'add-on via le Supervisor Home Assistant — à
faire dès que possible sur votre serveur, conformément à la Milestone 1 du
document de cadrage.
