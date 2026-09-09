# Changelog

## 0.3.5

- **Alignement TLS complet sur diyHue** (dont le pairing avec l'app Hue est
  éprouvé) : suite de chiffrement restreinte à
  `ECDHE-ECDSA-AES128-GCM-SHA256`, courbe `prime256v1`, préférence serveur,
  et TLS plafonné à 1.2 — reproduisant exactement `HueEmulator3.py`. Le
  certificat gagne aussi les extensions `basicConstraints`/`keyUsage`/
  `extendedKeyUsage=serverAuth` de `genCert.sh`/`openssl.conf`, absentes de
  notre génération initiale. Une suite de chiffrement Python par défaut
  (beaucoup plus large que ce que le client TLS embarqué de l'app Hue
  accepte probablement) ou un certificat sans extensions de type "serveur"
  peuvent faire échouer la poignée de main TLS silencieusement, avant tout
  échange HTTP — indiscernable, de notre côté, d'un client qui n'a jamais
  essayé. Le certificat existant est à nouveau détecté comme obsolète et
  régénéré automatiquement au démarrage.

## 0.3.4

- **Correctif probable du pairing qui reste bloqué avec un spinner actif** :
  le certificat auto-signé n'avait pas d'extension Subject Alternative Name
  (SAN). Les clients TLS modernes (iOS/Android, RFC 6125) ignorent le CN et
  exigent un SAN correspondant ; sans lui, la poignée de main TLS peut
  échouer silencieusement avant qu'aucune requête HTTP ne soit envoyée — ce
  qui expliquerait un spinner actif côté app sans qu'aucune tentative
  `POST /api` n'apparaisse dans nos logs. Le certificat existant est détecté
  et régénéré automatiquement au démarrage si son SAN ne correspond pas à
  l'IP courante — aucune action manuelle requise.

## 0.3.3

- **Correctif pairing** : l'API v1 (`/api/...`) est désormais servie sur le
  port 443 (HTTPS) en plus du port 80, comme sur un vrai Hue Bridge.
  Diagnostiqué à partir des logs réels : l'app Hue officielle (user-agent
  `Dart/3.12`) sondait `/api/config` en HTTPS d'abord (404, car seule l'API
  v2/CLIP y répondait), retombait sur HTTP (200), puis abandonnait sans
  jamais tenter `POST /api` — elle n'obtenait donc jamais la fenêtre de
  pairing sur le port qu'elle essayait en premier.

## 0.3.2

- Ajout d'un log explicite pour chaque tentative de pairing (`POST /api`) :
  IP, content-type, corps brut, et état du bouton de couplage au moment de
  la requête — pour diagnostiquer un blocage sans deviner. Consultable dans
  l'onglet Journal de l'add-on.

## 0.3.1

- Correction du format du champ `webui` (`[PORT:8099]` au lieu de `8099`),
  invalide selon le schéma du Supervisor — cette erreur faisait disparaître
  l'add-on entier de la boutique, silencieusement (log de niveau debug
  seulement pour un dépôt personnalisé hors canal dev).

## 0.3.0

- **Panel d'administration** (port 8099, lien "Web UI" de l'add-on) :
  - Configuration de la connexion MQTT (hôte/port/utilisateur/mot de passe/
    base topic), appliquée à chaud sans redémarrer l'add-on.
  - Création de pièces (rooms) avec sélection directe des lumières à y
    inclure, ajout/retrait de lumières sur les pièces existantes.
  - Exclusion d'appareils détectés (retirés du pont ; réinclusion possible,
    ré-applique immédiatement la dernière liste d'appareils connue de Z2M).
  - Simulation de l'appui du bouton de couplage.
  - Vue d'ensemble : lumières découvertes, pièces, zones Entertainment.
- La configuration MQTT persistée (fichier `config.yaml` interne) est
  désormais la source de vérité après le premier démarrage — les options de
  l'add-on ne servent qu'à l'amorcer une fois, le panel prend le relais.

## 0.2.1

- Fenêtre de pairing portée de 30 à 60 secondes.
- Nouvelle route `POST /linkbutton` (non authentifiée, comme le bouton
  physique d'un vrai bridge) pour réarmer le pairing sans redémarrer
  l'add-on — corrige le cas où l'application Hue reste bloquée sur "Appuyez
  sur le bouton" parce que la fenêtre de 30s au démarrage avait déjà expiré.

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
