# Hemera

Pont Hue virtuel autonome, backend Zigbee2MQTT, packagé en add-on Home
Assistant. Il expose l'API Hue (v1 et v2/CLIP) pour l'application Hue
officielle et prend en charge le pairing Hue Entertainment pour une Hue Sync
Box — voir le README du dépôt pour le détail du projet et son état
d'avancement.

## Installation

1. Réglages → Modules complémentaires → Boutique des modules → ⋮ → Dépôts,
   puis ajouter l'URL de ce dépôt.
2. Installer l'add-on **Hemera**.
3. Configurer les options (voir ci-dessous) puis démarrer.

## Configuration

| Option | Rôle |
|---|---|
| `mqtt_host` | Laisser vide pour utiliser automatiquement l'add-on Mosquitto broker installé. Ne renseigner que si vous utilisez un autre broker MQTT. |
| `mqtt_port`, `mqtt_user`, `mqtt_password` | Ignorés si `mqtt_host` est vide (auto-détection). |
| `mqtt_base_topic` | Le `base_topic` configuré dans Zigbee2MQTT (`zigbee2mqtt` par défaut). |
| `log_level` | Niveau de log. |

## Réseau

Cet add-on utilise `host_network: true` (réseau de l'hôte) — requis pour que
la découverte mDNS/SSDP fonctionne et que l'application Hue / la Sync Box
trouvent le pont sur le réseau local. Ce n'est pas configurable.

## Pairing avec l'application Hue

Le bouton de couplage est armé automatiquement pendant 30 secondes au
démarrage de l'add-on. Redémarrez l'add-on pour relancer une fenêtre de
pairing.

## Persistance

L'état du pont (utilisateurs couplés, lumières, groupes, scènes, certificat)
est stocké dans `/data`, propre à cet add-on — il survit aux redémarrages et
mises à jour, et est inclus dans les sauvegardes Home Assistant.
