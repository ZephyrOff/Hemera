# Changelog

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
