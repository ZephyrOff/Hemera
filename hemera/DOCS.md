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
| `timezone` | Fuseau horaire IANA (ex. `Europe/Paris`) reporté à l'app Hue. Laisser vide pour reprendre automatiquement celui déjà configuré dans Home Assistant. N'est utilisé qu'au tout premier démarrage — ensuite, le panel d'administration (Configuration → Général) est la référence. |
| `entertainment_fps` | Débit de mise à jour des couleurs pendant une session Hue Entertainment (Sync Box), 1 à 30 Hz. À baisser si le réseau Zigbee sature. |
| `log_level` | Niveau de log. |

La connexion MQTT n'est **pas** une option de l'add-on : elle se configure
uniquement depuis le panel d'administration (Configuration → Connexion
MQTT), qui en est la référence dès le premier démarrage. Au tout premier
démarrage, sans configuration existante, l'add-on Mosquitto est
auto-détecté s'il est installé.

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

Organisé en cinq vues, via le menu à gauche :

- **Appairage** : le pairing avec l'application Hue réussit toujours, sans
  condition — pas besoin de l'armer avant. Le bouton reste disponible pour
  compatibilité/affichage.
- **Configuration** :
  - *Général* : renommer le pont, définir son fuseau horaire (liste
    déroulante des fuseaux valides). Passe par le même mécanisme que ce que
    l'app Hue elle-même peut définir pendant sa propre configuration — les
    deux agissent sur le même réglage, ni l'un ni l'autre ne prend le pas
    durablement sur l'autre.
  - *Connecteur MQTT* : modifier et reconnecter la connexion au broker sans
    redémarrer — c'est l'unique endroit où la configurer (voir ci-dessus),
    et elle survit aux redémarrages une fois enregistrée — ainsi que les
    lumières découvertes via Zigbee2MQTT et les appareils exclus de ce
    connecteur (réinclusion immédiate via "Réinclure").
  - *Connecteur HA* : même chose pour les lumières provenant d'**autres**
    intégrations Home Assistant (voir plus bas).
- **Lumières** : vue d'ensemble de toutes les lumières prises en compte par
  le pont, tous connecteurs confondus (colonne **Connecteur**), avec leur
  état actuel (allumé/éteint, luminosité) tel que connu du pont —
  affectation directe à une ou plusieurs pièces (bouton « + pièce » sur
  chaque ligne, × sur chaque étiquette pour en retirer une). Le **modèle**
  présenté à l'application Hue (identifiant Hue réel, ex. `LCT015`,
  `LCX004`...) est modifiable via un menu déroulant, utile quand
  l'auto-détection s'est trompée — le bouton « Liste des modèles » en haut
  de la vue détaille ce que chacun représente. Exclure une lumière se fait
  depuis Configuration → le connecteur concerné, pas depuis cette vue.
  - **Dégradé simulé** (`HUE_UNSUPPORTED_GRADIENT`, `AQARA_GRADIENT`) : pour
    un bandeau LED que Zigbee2MQTT n'expose pas nativement comme "gradient"
    mais qui peut quand même être piloté segment par segment via MQTT.
    Présenté à l'app exactement comme un vrai bandeau Gradient ; le pont
    envoie ensuite le format de commande réel attendu par l'appareil
    (tableau de couleurs hexadécimales pour un bandeau Hue non reconnu,
    `segment_colors` — une couleur RVB par segment numéroté à partir de 1 —
    pour un bandeau Aqara). Pour `AQARA_GRADIENT`, le nombre réel de
    segments se déduit automatiquement de la longueur configurée dans
    Zigbee2MQTT pour cet appareil (5 segments par mètre), et contrairement
    à un vrai bandeau Hue, ce matériel n'a aucun lissage embarqué entre
    segments — le pont ré-échantillonne donc automatiquement les couleurs
    reçues sur l'ensemble des segments réels avant de les envoyer, pour un
    dégradé continu sur tout le bandeau.
- **Pièces** : création avec sélection directe des lumières à y inclure
  (champ de recherche si la liste est longue). Une pièce déjà créée peut
  aussi recevoir plusieurs lumières d'un coup (sélection multiple avec
  recherche) ou être supprimée entièrement.
- **Entertainment** : zones Entertainment détectées (créées depuis l'app Hue
  Sync ou la Sync Box) et leur statut de streaming.

## Connecteur Home Assistant

Permet d'ajouter au pont des lumières qui viennent d'**autres** intégrations
Home Assistant (WLED, Tuya, ESPHome, une autre intégration Hue...) plutôt
que de Zigbee2MQTT — utile pour un appareil que Z2M ne backe pas.

Aucune configuration nécessaire sur une installation add-on normale : l'accès
à l'API de Home Assistant se fait via le Supervisor (`homeassistant_api:
true`), avec le jeton fourni automatiquement à l'add-on — pas d'adresse ni de
jeton à saisir quelque part. Le connecteur découvre les entités `light.*`
par sondage périodique (toutes les 3 secondes) plutôt qu'en direct : un
changement d'état externe met donc quelques secondes à atteindre
l'application Hue, contrairement au connecteur MQTT qui le reçoit
immédiatement.

**Attention aux doublons** : si l'intégration Zigbee2MQTT de Home Assistant
elle-même est activée, ses lumières apparaissent à la fois comme entités
`light.*` (visibles par le connecteur HA) et via MQTT directement (connecteur
MQTT) — les exclure de l'un des deux connecteurs (Configuration → le
connecteur en question) évite de les voir en double dans l'application Hue.

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
