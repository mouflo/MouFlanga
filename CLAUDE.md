# MouFlanga : notes pour Claude Code

Lis aussi `/opt/CLAUDE.md` si présent (règles communes à toutes les applis : français partout, pas de sudo, pas de secret sur GitHub, prévenir avant un push pendant un traitement long).

## Ce que c'est
Appli Flask (bibliothèque et lecteur de mangas) + scraper Japscan. Dossier `/opt/mouflanga`, service `mouflanga.service`, déploiement automatique par cron (chaque minute). Réglages et secrets dans `data/` (`data/secrets.env`, jamais sur GitHub).

## Tests
`python -m unittest discover -s tests` (doit rester vert avant tout push). Journal : `journalctl -u mouflanga`. Le bouton « Rapport » de l'appli résume l'état (vérification Cloudflare, DNS, carte graphique, derniers événements).

## Bibliothèque
- Suppression (`/api/delete`) : chapitre ou série déplacés dans `<dossier des mangas>/.corbeille/<AAAA-MM-JJ>/`, vidée après 30 jours (`CORBEILLE_JOURS`) ; refusée pendant le téléchargement de la série.

- Couverture : `cover.jpg` dans le dossier de la série (prioritaire), choisie par `/api/cover/choisir`, retirée par `/api/cover/automatique`. Chapitres manquants : trous dans les numéros lus dans les noms de fichiers (`_numero_chapitre`).
- Séries Japscan : la liste du site pointe vers le dernier chapitre (« Dandadan 247 ») → `titre_serie()` retire ce numéro ; `_dossier_serie()` renomme l'ancien dossier « Titre N ». Page Télécharger : `deja` = chapitre déjà présent (même nom de fichier après « NNN - »).

- Accès des autres applis (`api_externe.py`) : `/api/externe/series`, `/api/externe/couverture` (GET/POST), en-tête `X-Cle-API` ; clé générée dans ⚙️ Réglages (`MOUFLANGA_CLE_API_SHA256` + 4 derniers caractères) ; ces routes passent hors de l'écran de connexion (`auth.py`). Bouton « Créer avec MouFloster » : `MOUFLOSTER_URL` → `<moufloster>/?mouflanga=<série>&q=…&retour=…`.

## Tomes (`tomes.py`, `tomes_cbz.py`)
- `tomes.chercher(série)` : Wikipédia (« List of … chapters », formats Numbered list / « *12. » / « * Chapter: 1–7 » / « # », commentaires retirés, section « Chapters not yet in tankōbon ») puis MangaDex ; cache 3 jours `data/tomes/`. Wikipédia limite les requêtes (429) : rester sobre.
- Fichier de tome : `Tome NN/<Série> - Tome NN.cbz` (ou `Hors tome/`), pages `c0012.00-p003.jpg`, `chapitres.json` (titres), `ComicInfo.xml`. Réécriture complète à chaque ajout (fichier .tmp puis remplacement).
- Bibliothèque : `_entrees()` donne les chapitres (clé = chemin pour un fichier ordinaire, « #12 » pour un chapitre de tome, avec `debut`/`nb`) ; progression et « lu » par clé. `_ranger_en_tomes()` : anciens fichiers → tomes, hors tome → tome sorti ; lancé avant chaque téléchargement (`preparer`) et par le bouton « Ranger en tomes ».

- Séries ajoutées à la main : `_plan_organiser()` (nom proposé d'après les noms de fichiers, crochets et « T01 » retirés) et `/api/organiser` (`_organiser()` : renommage, tomes complets déplacés dans `Tome NN/`, progression suivie, puis rangement des chapitres en arrière-plan). `_numero_tome()` reconnaît un tome complet ; `tomes_cbz._reecrire` refuse d'écraser un fichier qui n'est pas un fichier de tome.

- Import (`importer.py`) : PDF et archives > 400 Mo (`LOT_MIN`) = « à importer » (affichés 📦, non lisibles) ; extraction avec `bsdtar` dans `<série>/.import/` sur le NAS (le disque du conteneur est petit), tome = dossier « …Tome NN… », chapitre = sous-dossier numérique ; PDF via PyMuPDF. Choix de noms retenus dans `data/organiser-choix.json` (`_appris`), option `ORGANISER_AUTO`.

- Import des archives de la racine : `/importer`, `_archives_racine()` (nom proposé `_nom_depuis_archive`), file `_FILE_IMPORT` traitée par `_travail_file()` (une série à la fois, Telegram à la fin). `importer.deplier()` ouvre les archives/PDF intérieurs ; `_classer()` : 1er dossier « tome », sinon numéro final (« MAR.07 »), sinon nom de l'image ; `repartir()` sépare les séries dont les tomes se chevauchent. Cas réels étudiés : inventaire de 72 archives du 06/10/2026.

- Marque fini/incomplet/en cours : `tomes.statut_officiel()` (AniList, choix du résultat d'après le titre et le nombre de tomes locaux, cache `statut_officiel` dans `data/tomes/<série>.json`, 7 jours), rempli en fond par `_remplir_statuts()` à l'ouverture de la bibliothèque ; `_etat_serie()` compare au NAS.

## Le scraper Japscan (`japscan_scraper.py`)
- Navigateur au choix dans ⚙ Réglages : Chrome (Patchright, profil `data/navigateur`) ou Camoufox (Firefox, profil `data/navigateur-firefox`), sous écran virtuel Xvfb ; clics réels avec xdotool.
- Cloudflare impose une vérification interactive : la page `/verification` montre le navigateur du serveur (capture) et relaie clics, défilement et glisser du doigt ; alerte Telegram.
- `brunhild.challenges.cloudflare.com` n'existe qu'en IPv6 et le serveur n'a pas d'IPv6 : redirection vers IPv4 (option du navigateur ou ligne `# MouFlanga-cloudflare` dans `/etc/hosts`). AdGuard Home (DNS 192.168.1.139) doit laisser passer les domaines Cloudflare.
- Fiche série : le site cache la vraie liste de chapitres sous des leurres (liens `d-none`, faux « Chapitre 000001 » invisibles par `clip-path`). On ne lit que les éléments réellement visibles (`_JS_ZONES_VISIBLES`) ; l'adresse d'un chapitre est `/manga/<série>/<numéro>/`.
- Lecteur : un captcha d'images (tranches à remettre en ordre en glissant) peut s'afficher avant les pages ; détecté par le contenu de la page (Camoufox cache les variables `window`), résolu **à la main** par l'utilisateur. Ne pas chercher à le résoudre ni à l'éviter automatiquement (refusé le 06/10/2026, Cloudflare compris). Option « captchas groupés » (`JAPSCAN_CAPTCHAS_GROUPES=1`) : 1re passe sans attendre (`CaptchaReporte`), puis une alerte et les captchas à la suite ; le rapport note « captchas : N pour M chapitre(s) » pour comparer avec le mode normal (constaté : 1 captcha sur 2 chapitres).
- Pages : capturées sur le réseau (images de `c4.japscan.foo`), rangées dans l'ordre où le lecteur les demande (les noms de fichiers n'ont pas d'ordre). Ordre vérifié à l'œil le 06/10/2026 (Dandadan ch. 1 : 63/63, couverture → « Fin »). L'appli attend toutes les pages annoncées (`select#pages`) ; lecteur vide après captcha → rechargement du chapitre.
- Un seul navigateur sert à tout un téléchargement ; arrêt automatique après 3 chapitres de suite sans page ; onglet « En cours » avec bouton Annuler.
- Liste des mangas gardée 6 h (`data/mangas-japscan.json`), chapitres 1 h en mémoire.

## À faire / pistes
- Comprendre quand le site redemande un captcha (le rapport note la « mémoire du site ») ; vérifier que le rechargement après captcha rend bien les pages.
- Essai hors appli : charger `data/secrets.env` (choix du navigateur) et appeler `_assurer_ecran()` avant `download_chapter_pages`.
- Utiliser la puce graphique Intel Iris Xe du conteneur (`/dev/dri`) : le rapport a une section « Carte graphique » ; Xvfb n'utilise aucune carte graphique, il faudrait changer d'affichage.
- Mettre à jour les captures d'écran du README pour la grosse mise à jour Japscan.
