# Changelog

## 0.8.0

Deux retours utilisateur sur l'usage courant du pont (pairing et versions
étant désormais réglés) :

- **Panel d'administration : gestion des pièces repensée**, jugée peu
  intuitive. Deux problèmes corrigés :
  - **Bug réel trouvé en creusant** : le panel se rafraîchit automatiquement
    toutes les 5 secondes (pour refléter les changements MQTT/pairing en
    direct), mais ce rafraîchissement reconstruisait entièrement la liste de
    cases à cocher pour créer une pièce — toute sélection en cours,
    au-delà de 5 secondes, disparaissait silencieusement sans aucun
    indice sur la cause. Probablement la source principale du ressenti
    "pas intuitif". Corrigé : l'état des cases cochées, les champs de
    recherche et le focus/curseur en cours de frappe survivent maintenant
    au rafraîchissement automatique.
  - **Gestion des pièces directement depuis le tableau des lumières** :
    chaque lumière affiche désormais ses pièces sous forme d'étiquettes
    (avec un × pour en retirer une) et un bouton « + pièce » ouvrant un
    petit menu pour l'ajouter à une autre pièce — plus besoin de descendre
    jusqu'à la section Pièces et chercher la bonne carte. La section Pièces
    elle-même gagne un champ de recherche et une sélection multiple
    ("Ajouter la sélection") au lieu d'un menu déroulant à un seul choix
    répété pour chaque lumière. Aucun changement côté API/backend — tout
    repose sur les routes existantes (`api/rooms/...`).
- **Bandeau Hue Gradient Lightstrip bridé à un nombre de points fixe** :
  `points_capable` (le nombre de couleurs qu'on peut placer sur le
  dégradé, exposé dans `gradient.points_capable` du CLIP v2) était figé à
  `7` pour absolument tous les appareils détectés comme "gradient", sans
  jamais regarder ce que l'appareil réel annonce. Corrigé : lu directement
  depuis l'expose Zigbee2MQTT du bandeau (`length_max` de l'expose de type
  `list` nommé `gradient` — le champ que zigbee-herdsman-converters
  utilise réellement pour ça), avec un repli sur 7 seulement si Z2M ne le
  fournit pas. S'applique aussi aux lumières déjà découvertes avant cette
  mise à jour (la resynchronisation périodique met maintenant aussi ce
  champ à jour, alors qu'elle ne touchait jusqu'ici qu'au nom).
  - Au passage, correction d'un vrai bug trouvé en comparant avec diyHue
    (`HueObjects/Light.py`) : la ressource `entertainment` (utilisée pour
    le streaming Hue Sync, pas pour le dégradé statique) réutilisait par
    erreur ce même `points_capable` comme `max_segments`, alors que ce
    sont deux nombres sans rapport — diyHue fixe `max_segments` à `10`
    pour ce type de bandeau (nombre total de pixels virtuels répartis sur
    les 3 zones physiques réelles du matériau), indépendamment du nombre
    de points de dégradé statique disponibles. Sans effet visible connu,
    mais un désaccord avec le vrai bridge que ça vaut mieux ne pas laisser
    traîner.

## 0.7.0

Suite au succès de l'appairage en 0.6.0, deux nouveaux irritants signalés
par l'utilisateur, tous deux liés au fait qu'un pont virtuel n'a ni vrai
firmware à installer ni horloge/fuseau réellement configurés en usine :

- **"Le Hue Bridge n'est pas à jour"** : le `swversion`/`apiversion`
  renvoyés (`1967054020`/`1.67.0`) étaient simplement figés dans le code
  depuis la première version. L'app Hue compare ce qu'elle lit à la
  dernière version connue de Philips et affiche un bandeau de mise à jour
  bloquant si notre valeur paraît trop ancienne — sans qu'aucune mise à
  jour ne soit jamais réellement possible ici.
  - Solution retrouvée dans diyHue (`services/updateManager.py::versionCheck()`) :
    interroger directement l'API publique de Philips
    (`https://firmware.meethue.com/v1/checkupdate/?deviceTypeId=BSB002&version=...`)
    et adopter la version qu'elle renvoie si elle est plus récente que la
    nôtre — exactement ce qu'un vrai pont fait pour rester "à jour" en
    permanence aux yeux de l'app. Nouveau module
    `services/update_check.py` (portage asyncio/aiohttp de cette logique),
    appelé une fois au démarrage puis vérifié à nouveau toutes les 24h.
    Testé en direct contre l'API réelle de Philips au moment d'écrire ceci :
    elle a immédiatement fait passer une valeur `1.70.0`/`1970084010` (le
    défaut actuel de Bifrost, utilisé entretemps comme valeur de repli) à
    `1.79.0`/`1978293000` — confirmant qu'une valeur figée, y compris
    récente, se périme vite et que seule une vérification dynamique reste
    juste dans la durée. Si Philips est injoignable (pas de connexion
    Internet), la valeur de repli actuelle est conservée sans erreur
    bloquante.
  - `datastoreversion` aligné sur la valeur actuelle de Bifrost ("176" au
    lieu de "163", `crates/hue/src/legacy_api.rs`).
- **"Configurez le fuseau horaire de votre pont"**, en boucle : l'app Hue
  envoie bien `PUT /api/{user}/config` avec un champ `timezone` pendant la
  configuration, mais ce champ était silencieusement ignoré (seuls `name`
  et `linkbutton` étaient pris en compte) — l'app recevait un 200 mais ne
  voyait jamais son changement appliqué, donc reproposait indéfiniment
  l'écran de configuration.
  - `timezone` est désormais persisté et appliqué à l'environnement du
    processus (`os.environ['TZ']` + `time.tzset()`), comme le fait déjà
    diyHue dans `flaskUI/restful.py`/`configManager/configHandler.py`
    (`tzset` est protégé par un `hasattr` — absent sous Windows, présent
    sous Linux, la cible réelle de déploiement).
  - Nouvel endpoint `GET /api/{user}/info/timezones`, jusqu'ici absent,
    renvoyant la liste des fuseaux valides (552 noms, portés depuis
    `BridgeEmulator/functions/core.py::capabilities()` de diyHue) — sans
    lui, l'écran de sélection de fuseau de l'app n'a rien à afficher.
  - **Nouvelle option d'add-on `timezone`** (vide par défaut). Si laissée
    vide, le script de démarrage utilise automatiquement le fuseau
    horaire déjà configuré dans Home Assistant (`bashio::info.timezone`)
    plutôt qu'une valeur figée — à l'image de la convention `TZ=` des
    docker-compose officiels de diyHue. Cette valeur ne sert qu'à amorcer
    la configuration au tout premier démarrage : une fois que l'app Hue a
    elle-même défini un fuseau via son propre écran de configuration,
    c'est cette valeur-là qui fait foi (même logique que pour MQTT — pas
    de source de vérité concurrente qui écraserait un réglage déjà fait
    dans l'app à chaque redémarrage).

## 0.6.0

**Refonte complète de l'appairage**, à partir d'une comparaison ligne à ligne
avec le code source de Bifrost (`chrivers/bifrost`, GPL-3.0 — un pont Hue
pour Zigbee2MQTT actif, confirmé par l'utilisateur comme s'appairant
parfaitement avec l'app Hue officielle sur ce même réseau). Tous les
correctifs précédents (suppression du verrou "link button", correction des
404, option `mac`, premier alignement TLS) restent en place mais n'avaient
pas suffi : le problème vient d'un cumul de petites déviations protocolaires
qui, prises isolément, passent inaperçues avec des clients tolérants (Echo,
Hue Essentials) mais bloquent l'app officielle avant même l'envoi de
`POST /api`. Chaque point ci-dessous cite précisément le fichier Bifrost
correspondant.

- **mDNS annonce désormais le port 443 (HTTPS), pas 80** — trouvé dans
  `server/mdns.rs` : `let service_port = 443;`. On annonçait jusqu'ici le
  port HTTP, alors que le SSDP, lui, reste bien sur 80 (confirmé par
  `server/ssdp.rs` : `http://{}:80/description.xml`).
- **En-tête SSDP `SERVER` corrigé** en `Hue/1.0 UPnP/1.0 IpBridge/{apiversion}`
  (`server/ssdp.rs`, avec son propre commentaire : *"Hue Essentials strikes
  again: server name must look like this"*) — on utilisait auparavant le
  format diyHue `Linux/3.14.0 UPnP/1.0 IpBridge/1.20.0`, une convention plus
  ancienne et différente.
- **Certificat entièrement réaligné sur `server/certificate.rs`** (dont le
  commentaire précise : *"Great care has been taken to match real
  certificates"*) :
  - `CN` = `bridgeid` et non plus la `mac` — un vrai bridge (et Bifrost)
    utilise le bridgeid comme identité du certificat.
  - **Suppression du Subject Alternative Name** ajouté en 0.3.4 : ni un vrai
    bridge ni Bifrost n'en ont un ; cet ajout n'avait de toute façon pas
    résolu le blocage (confirmé par l'utilisateur : "Toujours pareil").
  - **Fenêtre de validité fixe** `2017-01-01` → `2038-01-19T03:14:07`
    (au lieu d'une fenêtre relative now±jours) — les vrais bridges (et
    Bifrost) utilisent ces bornes exactes plutôt qu'une date de génération.
  - **Ajout de l'extension `AuthorityKeyIdentifier`**, absente jusqu'ici.
  - Numéro de série désormais dérivé du bridgeid (comme
    `SerialNumber::new(&hue::bridge_id_raw(mac))`) plutôt qu'aléatoire.
  - Le certificat existant est de nouveau détecté comme obsolète et
    régénéré automatiquement au démarrage (CN et AuthorityKeyIdentifier).
- **Profil TLS élargi, pas restreint** — correction d'une fausse piste de la
  0.3.5 : `server/http.rs` construit explicitement un profil équivalent à
  `mozilla_intermediate_v5` plutôt que le défaut `mozilla_modern_v5` de sa
  bibliothèque, avec ce commentaire : *"That protocol version [TLS 1.3
  uniquement] is too new for some important clients, like Hue Sync for
  PC"*. Autrement dit, la bonne direction est une **compatibilité plus
  large**, pas la restriction à une seule suite `ECDHE-ECDSA-AES128-GCM-SHA256`
  + TLS 1.2 maximum copiée de diyHue en 0.3.5 (confirmée par l'utilisateur
  comme n'ayant rien changé). On repasse donc sur la suite de chiffrement
  TLS 1.2 par défaut de Python (déjà proche du profil "intermediate" de
  Mozilla) avec TLS 1.2 comme *minimum* (plus de plafond à 1.2), et on
  ajoute la négociation **ALPN** (`http/1.1`) — absente jusqu'ici — dont
  certains clients exigent la présence pour aboutir la poignée de main.
- **Champs manquants ajoutés à `/api/{user}/config`** (authentifié) :
  `analyticsconsent`, `portalconnection`, `proxyaddress`, `proxyport` —
  présents dans la structure `ApiConfig` de Bifrost
  (`crates/hue/src/legacy_api.rs`) mais absents de notre réponse ; un client
  qui valide la forme complète de la configuration avant de poursuivre le
  pairing pouvait s'arrêter là silencieusement.

Voir `NOTICE` pour l'attribution : ces correctifs suivent le design de
Bifrost (comportement observé/documenté dans son code source), aucun code
n'en a été copié — l'implémentation reste aiohttp/Python, indépendante de
son architecture axum/tokio en Rust.

## 0.5.1

- **Correction d'un vrai bug** : plusieurs réponses d'erreur v1 ("resource
  not available") renvoyaient le code HTTP 404 en plus du corps JSON
  d'erreur Hue standard. Or l'API Hue v1 renvoie **toujours HTTP 200**, même
  en cas d'erreur — celle-ci est encodée uniquement dans le JSON
  (`{"error": {...}}`), jamais via le statut HTTP (vérifié contre diyHue,
  qui ne renvoie jamais de statut explicite ici). Certains clients comme Hue
  Essentials n'attendent visiblement que ce format et plantent sur un vrai
  404 ("Expected ... JSON input: 404"). Toutes les réponses d'erreur v1
  renvoient maintenant HTTP 200, comme un vrai bridge.

## 0.5.0

- **Suppression du verrou "link button" sur `POST /api`** (pairing). Trouvé
  en examinant le code source de Bifrost (`bifrost-master/src/routes/api.rs`
  — un pont Hue pour Zigbee2MQTT moderne et activement maintenu, donc
  directement comparable) : son `post_api()` réussit **inconditionnellement**,
  sans aucune vérification de fenêtre temporelle. Les logs montraient que
  l'application Hue officielle ne renvoyait jamais `POST /api`, quelle que
  soit la durée d'activation du bouton (fenêtre au démarrage, bouton du
  panel, les deux cumulés) — pendant que d'autres clients (Echo) pairaient
  sans problème pendant ce temps. Plutôt que de continuer à deviner ce que
  l'app attend exactement du champ `linkbutton`, on adopte le comportement
  éprouvé : le pairing réussit désormais toujours, immédiatement.
  Compromis de sécurité assumé : n'importe quel appareil pouvant joindre le
  pont peut se pairer, sans confirmation — acceptable pour un pont Hue
  personnel sur un réseau local domestique, à l'image de Bifrost.
- Le bouton "Simuler l'appui" du panel reste disponible (affichage /
  compatibilité), mais n'est plus nécessaire pour que le pairing aboutisse.

## 0.4.0

- **Nouvelle option `mac`**, absente jusqu'ici. Trouvée en examinant l'add-on
  officiel diyHue (`hassio-addon`), dont la documentation prévient
  explicitement : *"You can not fake a Mac here, since it is used for
  original software (APP) to authenticate the Emulated Bridge!"*. Sous
  réseau hôte, `uuid.getnode()` peut détecter la MAC d'une interface
  virtuelle (pont Docker, VPN...) plutôt que la vraie carte réseau du
  serveur — le certificat et le `bridgeid` en dépendent, et une valeur
  incorrecte fait échouer l'authentification côté application Hue
  officielle silencieusement. C'est la cause la plus probable du blocage
  persistant sur "appuyez sur le bouton" malgré les correctifs précédents.
- La valeur de cette option, une fois renseignée, s'applique à chaque
  démarrage (contrairement à MQTT, elle n'a pas de source de vérité
  concurrente comme le panel) — pas besoin de vider `/data` pour corriger
  une MAC auto-détectée à tort. Le certificat est régénéré automatiquement
  si la MAC change.

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
