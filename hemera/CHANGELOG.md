# Changelog

## 0.15.1

- **Correctif du pairing avec Hue Sync (Desktop, et sans doute la Sync Box)**
  : bloqué indéfiniment sur "appuyez sur le bouton Push-Link", malgré un
  appairage qui fonctionne très bien avec l'application Hue elle-même.
  Trouvé grâce aux logs de l'add-on (pas une supposition) : Hue Sync
  envoie systématiquement `POST /api/` — **avec un slash final** — pour
  s'enregistrer, alors que l'application Hue, curl, et tous nos tests
  utilisent `POST /api` (sans slash). Le routeur d'aiohttp traite ces deux
  chemins comme distincts ; seul le second était enregistré, donc chaque
  tentative de Sync se terminait en 404 — indiscernable, de son côté, d'un
  pont qui ne répond jamais.
  - Corrigé en enregistrant systématiquement un alias avec slash final
    pour chaque route (v1, v2/CLIP, panel d'administration) — nouveau
    module `api/routing.py`.
  - Détail technique noté au passage : la solution la plus évidente (un
    middleware aiohttp qui redirige `/api/` vers `/api`, ou le
    `normalize_path_middleware` intégré à aiohttp qui fait exactement
    ça) a été écartée puis abandonnée après test : une redirection HTTP
    exige que le client renvoie correctement la même méthode et le même
    corps vers la nouvelle adresse, ce qu'on ne peut pas garantir pour un
    client qu'on ne maîtrise pas. Un middleware qui tente de router en
    interne sans redirection ne fonctionne pas non plus, confirmé en le
    testant en isolation : aiohttp fige le gestionnaire suivant sur la
    route résolue *avant* l'exécution des middlewares, donc muter
    `match_info` en cours de route n'a aucun effet. Enregistrer les deux
    chemins dès le départ évite ces deux problèmes.
  - Vérifié de bout en bout avec la requête exacte observée dans les logs
    (`POST /api/` avec le corps JSON envoyé par Sync) : réussit
    maintenant normalement, `clientkey` inclus.

## 0.15.0

- **« Points de dégradé » retiré de la vue Lumières** : depuis la 0.14.0,
  ce nombre se déduit et se corrige tout seul (longueur Zigbee2MQTT réelle
  pour Aqara, `length_max` pour un vrai bandeau Hue) — un réglage manuel
  affiché en permanence n'avait plus vraiment d'utilité. Le réglage
  reste possible via l'API (`POST /api/lights/{id}/gradient_points`) pour
  les cas où l'auto-détection ne suffirait pas, simplement plus affiché.

- **Nouveau connecteur Home Assistant**, à côté du connecteur MQTT
  existant : permet d'ajouter au pont des lumières qui viennent d'*autres*
  intégrations Home Assistant (WLED, Tuya, ESPHome, une autre intégration
  Hue...) plutôt que de Zigbee2MQTT.
  - **Aucune configuration requise** sur une installation add-on réelle :
    `homeassistant_api: true` donne à l'add-on l'accès à l'API de Home
    Assistant via le Supervisor, avec le jeton déjà fourni automatiquement
    à chaque add-on — pas d'adresse ni de jeton à saisir. Hors add-on
    (dev local), `HEMERA_HA_URL`/`HEMERA_HA_TOKEN` prennent le relais.
  - Découverte par sondage périodique de `GET /api/states` (toutes les 3s)
    plutôt qu'un abonnement WebSocket en direct — plus simple et plus sûr
    pour une première version, au prix d'un délai de quelques secondes
    avant qu'un changement d'état externe atteigne l'app Hue (l'inverse
    du connecteur MQTT, qui reçoit les changements immédiatement).
  - Le modèle Hue présenté est déduit des `supported_color_modes` de
    l'entité (même principe que la détection depuis les `exposes` Z2M).
  - Nouvelles vues dans **Configuration → Connecteur MQTT / Connecteur
    HA** : statut de connexion, lumières découvertes et exclusions,
    séparément pour chaque connecteur. La vue **Lumières** reste la vue
    d'ensemble (toutes les lumières, tous connecteurs confondus), avec une
    nouvelle colonne **Connecteur** ; l'exclusion d'une lumière se fait
    désormais depuis la vue Configuration du connecteur concerné plutôt
    que depuis Lumières.
  - Attention aux doublons : si l'intégration Zigbee2MQTT de Home
    Assistant est elle-même activée, ses lumières apparaissent à la fois
    comme entités `light.*` (visibles par le connecteur HA) et via MQTT
    directement (connecteur MQTT) — les exclure d'un des deux connecteurs
    évite de les voir en double dans l'app Hue.
  - Bug trouvé et corrigé pendant les tests (avec un faux serveur HA, en
    l'absence d'une vraie instance Home Assistant sous la main) : contrairement
    à un message MQTT de Z2M (qui ne contient que les propriétés qui ont
    réellement changé), chaque sondage de `/api/states` renvoie l'état
    *complet* de l'entité, changé ou non — sans comparaison avec l'état
    déjà connu, ça aurait repoussé un évènement identique vers l'app Hue
    toutes les 3 secondes indéfiniment. Corrigé avant publication.

## 0.14.0

- **Correctif important sur `AQARA_GRADIENT` : le dégradé ne remplissait
  qu'une partie du bandeau.** Cause identifiée en comparant avec Alex Light
  Studio (le projet HA développé en parallèle contre le même bandeau) :
  contrairement à un vrai bandeau Gradient Hue, le matériel Aqara n'a
  **aucun lissage embarqué** entre segments — chaque segment doit recevoir
  sa propre couleur explicite. Or l'application Hue semble plafonner le
  nombre de points de couleur qu'on peut placer dans son éditeur de
  dégradé bien en dessous du nombre réel de segments de ce type de
  bandeau (observé concrètement : un bandeau à 10 segments, 3 points
  envoyés par l'app). Le pont transmettait jusqu'ici ces points un pour un
  vers `segment_colors` — un dégradé à 3 points sur un bandeau à 10
  segments n'allumait donc que les 3 premiers, les 7 restants gardant
  leur dernier état.
  - Corrigé : les points reçus de l'app sont maintenant ré-échantillonnés
    (interpolation linéaire par points d'ancrage, comme un dégradé CSS)
    sur le nombre réel de segments du bandeau — celui suivi automatiquement
    depuis la 0.13.1 via la longueur réelle rapportée par Zigbee2MQTT.
    Nouveau module `functions/gradient.py`, porté depuis Alex Light Studio
    (voir `NOTICE`) : c'est exactement le mécanisme dédié qu'il avait fallu
    y développer pour la même raison.
  - Uniquement pour `AQARA_GRADIENT` — un vrai bandeau Hue (ou
    `HUE_UNSUPPORTED_GRADIENT`, du matériel Hue authentique que Z2M ne
    reconnaît juste pas encore comme "gradient") a son propre lissage
    matériel et n'a pas besoin de ce traitement.
  - Testé de bout en bout : un dégradé à 3 points envoyé sur un bandeau
    configuré à 10 segments réels publie désormais bien 10 couleurs
    interpolées, du premier au dernier point, sur `segment_colors`.
  - Concernant l'hypothèse d'un plafond de 3 points côté application Hue :
    aucune source ne permet de le confirmer avec certitude de mon côté,
    mais la correction fonctionne quel que soit le nombre réel de points
    envoyés par l'app — inutile de trancher la question pour que ça marche.

## 0.13.1

- **Correctif `AQARA_GRADIENT` : le nombre de points de dégradé peut
  maintenant se désynchroniser du nombre réel de segments configurés dans
  Zigbee2MQTT.** Cas réel signalé : un bandeau réglé sur 3 points de
  dégradé dans le panel, mais avec 5 segments effectivement configurés
  côté Z2M (suite à un test manuel antérieur) — n'allumait que le début du
  bandeau, puisqu'on ne publiait de couleur que pour 3 segments sur 5.
  Corrigé : la longueur réelle du bandeau (`length`, en mètres) est un
  réglage propre à chaque appareil Aqara que Zigbee2MQTT republie en
  direct — le nombre réel de segments s'en déduit (`longueur × 5`, densité
  fixe des bandeaux Aqara LED Strip T1). Le pont recalcule maintenant le
  nombre de points de dégradé à partir de cette valeur à chaque message
  d'état reçu pour un appareil `AQARA_GRADIENT`, et corrige silencieusement
  toute valeur déjà enregistrée si elle ne correspond plus — y compris une
  valeur définie manuellement dans le panel, contrairement au réglage
  équivalent pour un vrai bandeau Hue (où une valeur manuelle reste
  volontairement prioritaire, parce qu'elle représente un choix informé
  face à une capacité que Z2M ne fait que deviner ; ici `length` est la
  configuration réelle de l'appareil, pas une estimation, donc rien ne
  justifie qu'un réglage resté périmé dans le panel continue à primer sur
  elle). Le champ manuel du panel reste disponible en repli pour les
  versions/convertisseurs Zigbee2MQTT qui ne republient pas `length`.

## 0.13.0

- **Dégradé simulé pour les bandeaux non reconnus comme Gradient par
  Zigbee2MQTT** : deux nouveaux modèles dans le sélecteur de la vue
  Lumières, `HUE_UNSUPPORTED_GRADIENT` et `AQARA_GRADIENT`. Présentés à
  l'application Hue exactement comme un vrai bandeau Gradient (même
  gabarit que `LCX004` — capacités, points de dégradé réglables, zone
  Entertainment), mais le pont adapte la commande MQTT réellement envoyée
  selon le modèle choisi :
  - `HUE_UNSUPPORTED_GRADIENT` : identique au format déjà utilisé pour un
    vrai bandeau Hue (`{"gradient": ["#rrggbb", ...]}`) — pour un bandeau
    dont Zigbee2MQTT ne détecte pas nativement la fonction gradient, mais
    qui répond quand même à ce champ.
  - `AQARA_GRADIENT` : nouveau format `{"segment_colors": [{"segment": 1,
    "color": {"r":,"g":,"b":}}, ...]}` (numérotation à partir de 1, une
    couleur RVB par segment) — celui qu'attend le firmware Aqara (LED
    Strip T1 et similaires), qui n'a pas de champ `gradient` du tout.
  - Porté depuis `alex_light_studio` (l'intégration Home Assistant
    développée en parallèle contre le même matériel réel) — voir
    `NOTICE`. Le nombre de points de dégradé reste réglable dans le panel
    (Lumières → Points de dégradé) comme pour tout modèle Gradient,
    puisque Zigbee2MQTT ne peut évidemment rien rapporter de fiable sur un
    appareil qu'il ne reconnaît pas comme tel.
  - Testé de bout en bout : bascule de modèle depuis le panel, envoi d'un
    dégradé depuis l'API v2 (donc depuis l'app Hue en conditions réelles),
    vérification du message MQTT réellement publié pour les deux formats.

## 0.12.0

- **Marges entre les blocs du panel corrigées** : "Lumières découvertes" et
  "Appareils exclus" (et toutes les autres paires de cartes dans une même
  vue) étaient collées l'une à l'autre. En cause : l'espacement n'était
  posé que sur le conteneur de premier niveau, entre les *vues* elles-mêmes
  (Appairage/Configuration/...), qui ne sont jamais visibles deux à la
  fois — donc sans effet réel — et jamais entre les cartes à l'intérieur
  d'une même vue.
  - Corrigé en ajoutant l'espacement au niveau de chaque vue. Au passage,
    ce changement avait initialement cassé le changement de vue lui-même
    (toutes les vues s'affichaient empilées en même temps, plus aucune
    séparation entre Appairage/Configuration/etc.) à cause d'un conflit de
    priorité CSS avec l'attribut `hidden` — repéré à la capture d'écran de
    vérification avant publication, corrigé dans la foulée.
  - Un deuxième effet de bord similaire (noms de lumières/pièces affichés
    en MAJUSCULES dans les listes à cocher) a été trouvé et corrigé de la
    même manière.
- **Plus de modèles de lumière disponibles** (vue Lumières → sélecteur de
  modèle et « Liste des modèles ») : passé de 6 à 10, en portant les
  variantes de diyHue qui représentent une différence réelle (icône/forme
  affichée dans l'app, pas seulement un SKU Philips différent pour une
  capacité identique) — spot couleur GU10 (`LCG001`), bandeau couleur sans
  dégradé façon Lightstrip Plus (`LST002`), et deux variantes Gradient
  supplémentaires : le bandeau TV/Play 3 zones (`LCX002`, déjà géré par le
  moteur Entertainment mais jusqu'ici pas sélectionnable) et le lampadaire
  Signe Gradient (`915005987201`). Les autres variantes de diyHue (`LCT001`,
  `LCA005`, `LOM004`, `LOM010`, `LCX006`) ont été délibérément laissées de
  côté : elles sont identiques, y compris dans le code source de diyHue
  lui-même, à un modèle déjà proposé (même capacités, même icône).
- **Suivi de l'état en direct : toujours en cours d'investigation.** Les
  deux correctifs précédents (poussée d'évènement à chaque changement MQTT,
  puis prise en charge de la reconnexion SSE standard) sont vérifiés
  fonctionnels par des tests directs sur le protocole — mais un
  changement fait depuis Home Assistant reste invisible dans l'app tant
  qu'elle n'est pas relancée. N'ayant pas d'appareil réel sous la main
  pour observer ce que fait précisément l'app à ce moment-là, des logs
  détaillés ont été ajoutés (niveau INFO, donc visibles sans rien
  configurer) : chaque connexion/déconnexion au flux d'évènements
  (`hemera.api.v2.eventstream`, avec l'IP du client et si une reprise
  `Last-Event-ID` a eu lieu) et chaque changement d'état poussé suite à un
  message Zigbee2MQTT (`hemera.services.mqtt_client`). La prochaine fois
  que le problème se reproduit, ces deux lignes de log (consultables dans
  l'onglet Journal de l'add-on) diront si l'app avait une connexion active
  au flux à ce moment-là et si le changement a bien été poussé — de quoi
  distinguer un problème côté pont (rien n'est poussé, ou personne n'est
  connecté) d'un problème côté app (tout est poussé correctement mais elle
  ne l'affiche pas).

## 0.11.0

- **Deuxième bug réel trouvé sur la remontée d'état en direct** (suite de la
  0.10.0) : même avec la notification à chaque changement, l'application
  Hue ne voyait toujours pas les changements externes (Zigbee2MQTT,
  automatisation...) sans redémarrage complet — seul le statut au moment de
  l'ouverture de l'app était correct. Cause trouvée en comparant avec
  Bifrost (`routes/eventstream.rs`) : le flux SSE ne gérait pas la
  reconnexion standard (en-tête `Last-Event-ID`). Chaque connexion perdue
  (l'app en arrière-plan sur mobile suspend son réseau — un cas très
  fréquent, pas une exception) puis rétablie repartait "en direct à partir
  de maintenant", sans aucun moyen pour l'app de demander "qu'ai-je
  manqué ?" — tout changement survenu pendant la coupure était perdu
  définitivement, silencieusement, jusqu'au prochain `GET` complet (un
  vrai relancement de l'app). Corrigé dans `objects/__init__.py` (chaque
  évènement a maintenant un numéro de séquence global stable, indépendant
  de toute connexion) et `api/v2/eventstream.py` (une reconnexion avec
  `Last-Event-ID` rejoue tout ce qui a été manqué) — comportement standard
  du protocole SSE, que Bifrost implémente pour la même raison. Testé en
  conditions simulées : connexion coupée, changement d'état publié
  pendant la coupure, reconnexion avec le dernier ID connu — les
  évènements manqués sont bien rejoués.
- **Modèles : noms réels affichés, description déplacée dans une fenêtre
  dédiée**. Le sélecteur de modèle sur chaque lumière affiche maintenant
  le vrai identifiant Hue (`LCT015`, `LCX004`...) plutôt qu'un libellé
  français inventé. Un bouton « Liste des modèles » en haut de la vue
  Lumières ouvre une fenêtre récapitulant chaque modèle avec sa
  description.
- **Panel visuellement retravaillé** : palette et ombres plus soignées,
  icônes dans le menu de gauche, badge de marque, transitions plus douces
  sur les boutons/cartes/lignes de tableau — toujours sans dépendance
  externe (aucune police ni bibliothèque d'icônes chargée depuis
  Internet, cohérent avec le fonctionnement hors-ligne de l'add-on).

## 0.10.0

- **Vrai bug trouvé et corrigé : l'application Hue ne reflétait pas l'état
  réel des lumières** (allumage, couleur, luminosité) quand il changeait en
  dehors d'une commande envoyée depuis l'app elle-même — interrupteur
  physique, automatisation, autre contrôleur. En cause : les mises à jour
  reçues depuis Zigbee2MQTT étaient bien appliquées à l'état interne du
  pont (un `GET` direct renvoyait déjà la bonne valeur), mais **jamais
  notifiées au flux d'évènements CLIP v2** (`GET /eventstream/clip/v2`,
  SSE) dont l'app dépend pour son affichage en temps réel — elle ne fait
  pas de sondage actif. Corrigé dans `services/mqtt_client.py` :
  `_update_light_state` pousse maintenant un évènement v2 à chaque
  changement réellement affiché (on/off, luminosité, couleur, température
  de couleur), en réutilisant le même mécanisme que les commandes envoyées
  depuis l'app (`Light.genStreamEvent`) — sans bruit inutile : un message
  Z2M qui ne change qu'un champ non affiché (ex. `linkquality`) ne pousse
  rien.
- **Modèle de lumière modifiable depuis le panel** (vue Lumières) : un
  menu déroulant sur chaque lumière permet de changer le modèle Hue
  présenté à l'application (couleur+température, couleur seule,
  température seule, intensité seule, prise on/off, bandeau Gradient) —
  utile quand l'auto-détection depuis les *exposes* Zigbee2MQTT a mal
  deviné les capacités réelles de l'appareil. Le changement se fait sur
  l'objet existant (pas de recréation) pour ne pas perdre son
  appartenance aux pièces déjà configurées, et réinitialise état/config
  depuis le nouveau modèle en ne conservant que les champs communs aux
  deux (on/off, luminosité, couleur, température de couleur) pour éviter
  toute incohérence avec les capacités annoncées du nouveau modèle.
- **Point sur la limite à 3 points de couleur des bandeaux Gradient**,
  question posée en parallèle : ce n'est pas un bridage introduit par le
  pont — vérifié en conditions réelles, l'app Hue affiche exactement le
  nombre que Zigbee2MQTT annonce lui-même pour l'appareil
  (`length_max` de son expose `gradient`, lu dynamiquement depuis la
  0.8.0). Si Z2M annonce 3, c'est cette valeur précise qui remonte — ce
  n'est donc pas un choix arbitraire de notre côté. Un réglage manuel est
  maintenant disponible dans le panel (à côté du sélecteur de modèle,
  visible uniquement pour un bandeau Gradient) pour forcer une autre
  valeur si le matériel réel supporte plus que ce que Z2M rapporte — cette
  valeur manuelle est alors mémorisée et n'est plus jamais écrasée par la
  resynchronisation automatique. Cela dit, si Zigbee2MQTT/le firmware du
  bandeau n'acceptent réellement que 3 couleurs au niveau du cluster
  Zigbee, forcer un nombre plus élevé ne fera qu'afficher plus de points
  dans l'app sans qu'ils soient réellement appliqués sur le bandeau — Z2M
  tronquera ou ignorera les couleurs en trop à la publication.

## 0.9.0

- **Panel d'administration réorganisé en vues séparées**, avec un menu de
  navigation à gauche : Appairage, Configuration, Lumières, Pièces,
  Entertainment — au lieu d'une seule longue page où toutes les sections
  s'empilaient. Chaque section précédente est simplement déplacée dans la
  vue correspondante ; aucun comportement n'a changé côté fonctionnalités
  déjà en place (recherche, sélection multiple, affectation directe depuis
  le tableau des lumières...).
- **Nouvelle vue Configuration → Général** : renommer le pont et définir son
  fuseau horaire directement depuis le panel, sans dépendre de l'application
  Hue pour ce dernier. Le champ fuseau horaire est une liste déroulante des
  552 fuseaux valides (la même liste que `GET .../info/timezones`) plutôt
  qu'un champ texte libre. Les deux champs passent par le même mécanisme que
  ce que l'app Hue elle-même déclenche en interne (`config.name` /
  `config.timezone` + application immédiate au processus pour le fuseau) —
  ce n'est pas un système parallèle.
- **Suppression de la configuration MQTT des options de l'add-on**
  (`mqtt_host`, `mqtt_port`, `mqtt_user`, `mqtt_password`,
  `mqtt_base_topic`) : elle faisait doublon avec le panel, qui est de toute
  façon devenu la source de vérité dès le premier démarrage. Au premier
  démarrage, la détection automatique du broker Mosquitto (add-on officiel,
  via `bashio::services`) reste le point de départ ; en son absence,
  l'add-on démarre avec un broker par défaut (`127.0.0.1:1883`) à corriger
  depuis Configuration → Connexion MQTT. Les installations existantes ne
  sont pas affectées : leur configuration MQTT déjà enregistrée dans
  `/data` continue de s'appliquer normalement.

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
