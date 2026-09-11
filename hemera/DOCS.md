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

**Important — l'option `mac`** : si le pairing avec l'application Hue reste
bloqué sur "appuyez sur le bouton" sans jamais aboutir, c'est presque
toujours parce que la MAC auto-détectée ne correspond pas à la vraie
interface réseau de votre serveur. Le certificat et l'identité du pont sont
dérivés de cette adresse, et **l'application Hue officielle l'utilise pour
authentifier le pont** — une mauvaise valeur casse le pairing silencieusement
(diyHue documente exactement le même piège pour son propre add-on). Trouvez
la MAC réelle de l'interface de votre serveur HA (celle utilisée pour
joindre votre réseau local, visible par exemple dans la liste des clients
DHCP de votre routeur) et renseignez-la dans l'option `mac`, au format
`XX:XX:XX:XX:XX:XX`. Un changement de cette option régénère automatiquement
le certificat au redémarrage.

| Option | Rôle |
|---|---|
| `mac` | MAC réelle de l'interface réseau du serveur (voir ci-dessus). Laisser vide pour tenter une auto-détection — non fiable sous réseau hôte. |
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

## Panel d'administration

Accessible via le bouton "Web UI" de l'add-on, ou directement sur
`http://<IP de votre serveur HA>:8099/`. Volontairement non authentifié —
comme le bouton physique d'un vrai bridge, l'accès au réseau local est
considéré comme suffisant.

- **Bouton de couplage** : le pairing avec l'application Hue réussit
  toujours, sans condition — pas besoin de l'armer avant. Le bouton reste
  disponible pour compatibilité/affichage.
- **MQTT** : modifier et reconnecter la connexion au broker sans redémarrer.
  Une fois enregistrée depuis le panel, cette configuration prend le pas sur
  les options de l'add-on au démarrage suivant.
- **Lumières** : liste des appareils Zigbee2MQTT détectés, avec la
  possibilité de les exclure du pont (ils redeviennent inclus, avec
  réapparition immédiate, via le bouton "Réinclure").
- **Pièces (rooms)** : création avec sélection directe des lumières à y
  inclure (champ de recherche si la liste est longue). Une fois créées,
  l'affectation aux pièces se fait directement depuis le tableau des
  lumières — un bouton « + pièce » sur chaque ligne ouvre un petit menu
  pour l'ajouter à une pièce existante, et chaque étiquette de pièce a un
  × pour l'en retirer. La section Pièces reste disponible pour ajouter
  plusieurs lumières à une pièce en une fois (sélection multiple avec
  recherche) ou supprimer une pièce entière.

## Persistance

L'état du pont (utilisateurs couplés, lumières, groupes, scènes, certificat)
est stocké dans `/data`, propre à cet add-on — il survit aux redémarrages et
mises à jour, et est inclus dans les sauvegardes Home Assistant.

Le certificat TLS est à `/data/cert.pem`. Contrairement à diyHue (qui utilise
`/config/diyhue`, visible depuis le partage Samba/l'éditeur de fichiers HA),
`/data` est un stockage privé de l'add-on, non accessible depuis ces outils —
il faut passer par le Terminal/SSH de HA (`docker exec addon_local_hemera ...`)
pour l'inspecter manuellement. En pratique ce ne devrait pas être nécessaire :
le certificat est régénéré automatiquement dès qu'il est détecté comme
obsolète (MAC ou IP changée, extensions manquantes).
