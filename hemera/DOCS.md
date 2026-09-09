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
| `entertainment_fps` | Débit de mise à jour des couleurs pendant une session Hue Entertainment (Sync Box), 1 à 30 Hz. À baisser si le réseau Zigbee sature. |
| `log_level` | Niveau de log. |

## Hue Entertainment (Sync Box)

Le port UDP 2100 (DTLS) reçoit le flux Hue Entertainment. Une session
démarre quand un client (Hue Sync Box, ou l'app Hue en mode "Sync des
lumières à l'écran") active une zone Entertainment via l'API v1 ou v2 — les
couleurs sont ensuite relayées vers Zigbee2MQTT en respectant
`entertainment_fps`, avec suppression des mises à jour trop proches de la
précédente pour ne pas saturer le maillage Zigbee.

Si le runtime OpenSSL 3.x n'est pas disponible dans le conteneur, un message
d'erreur apparaît au démarrage mais le reste du pont continue de
fonctionner normalement — seul le streaming Entertainment est indisponible.

## Réseau

Cet add-on utilise `host_network: true` (réseau de l'hôte) — requis pour que
la découverte mDNS/SSDP fonctionne et que l'application Hue / la Sync Box
trouvent le pont sur le réseau local. Ce n'est pas configurable.

## Pairing avec l'application Hue

Le bouton de couplage est armé automatiquement pendant 60 secondes au
démarrage de l'add-on. Si l'application reste bloquée sur "Appuyez sur le
bouton en haut du Hue Bridge" (fenêtre expirée avant que vous n'arriviez à
cet écran), pas besoin de redémarrer l'add-on : réarmez le bouton avec

```bash
curl -X POST http://<IP de votre serveur HA>/linkbutton
```

puis relancez immédiatement le pairing dans l'application (nouvelle fenêtre
de 60 secondes). Cette route n'est volontairement pas authentifiée — comme
le bouton physique d'un vrai bridge, l'accès au réseau local est considéré
comme suffisant.

## Persistance

L'état du pont (utilisateurs couplés, lumières, groupes, scènes, certificat)
est stocké dans `/data`, propre à cet add-on — il survit aux redémarrages et
mises à jour, et est inclus dans les sauvegardes Home Assistant.
