# Détails par appli (MouFlanimeXer, MouFloster, MouFlopening, MouFlanga, redémarrages)

Sorti de `/opt/CLAUDE.md` pour l'alléger : à lire seulement quand on travaille sur l'appli concernée.

## MouFlanimeXer (`mouflanimexer.py`, v3.33)
- Remux MKV d'épisodes : garde les pistes audio japonaise/française, traite les sous-titres ASS (mise à l'échelle de la résolution y compris `\iclip`, dessins, bordures et ombres ; style imposé ; polices vérifiées et embarquées depuis la bibliothèque `/opt/mouflanimexer/fonts`). Un fichier dont une police manque est mis de côté dans « À traiter (police manquante) ».
- Deux usages : l'**interface web** (scan d'un dossier, file d'attente, pause) et le **surveillant Sonarr** lancé par cron toutes les 2 minutes (`python3 mouflanimexer.py --watch-sonarr`). Le surveillant parcourt le dossier manga (`.mkv` et `.mp4`), traite chaque fichier stable et nouveau, **remplace l'original en place** (`os.replace`), puis demande à Sonarr un rescan + renommage. Il envoie un compte rendu Telegram par fichier.
- Verrou `fcntl` (un seul passage à la fois), retard croissant après un échec (30 min jusqu'à 24 h), alerte NAS inaccessible (une par heure).
- Réglages : `data/paths.json` (dossiers : travail, scan par défaut, dossiers surveillés, `watch_mp4`), `telegram_config.json` et `sonarr_api_config.json` dans `/opt/mouflanimexer` (hors git, écrits par la page Réglages), table de correspondance des chemins Sonarr ↔ serveur.
- État : `sonarr_watch_state.json` (fichiers déjà traités + marqueur `__mp4_connus__`), `sonarr_watch_failures.json`, journal des décisions `.jsonl` dans `<dossier de travail>/Log`. Sorties terminées dans `FICHIER OK/<série>`, sorties temporaires du surveillant dans `.en-cours-auto`.
- Séries exclues (style conservé, ex. One Piece) et pistes de sous-titres supplémentaires par série : commandes `--list-series`, `--exclude-series`, `--add-extra-sub-lang` (voir `INSTALL.md`).
- Python système (pas de venv), service `mouflanimexer.service`. Tests : `python3 -m unittest discover -s tests`.

## MouFloster (`app.py`, ~3 500 lignes, page HTML et JavaScript dans le même fichier, v1.0)
- Cherche films, séries et **sagas** sur TheMovieDB, fabrique des posters 1000×1500 : cadre blanc (« anime » 45 px ou standard 22 px), dégradé noir, jusqu'à 5 textes (Arial Bold), numéro de saison, zoom 50–300 %, recadrage au doigt, effacement de texte/logo (OpenCV, ou **LaMa** installé en arrière-plan par `deploy.sh`).
- **Envoi dans la médiathèque** (`library.py`) : repère le bon dossier (mémorisé par identifiant TMDB dans `data/layouts.json` et le choix de dossier), compare ancien et nouveau poster, **sauvegarde toujours l'ancien** (`<nom>.<date>.jpg`, restaurable depuis la page), puis actualise seulement le titre concerné dans Emby (`emby.py`). Vignettes d'épisode `S00E100-thumb.jpg`. Sagas : image envoyée directement dans la collection Emby.
- **Couverture dans MouFlanga** (`mouflanga_link.py`) : par le réseau (adresse + clé API de MouFlanga, `MOUFLANGA_URL` / `MOUFLANGA_CLE`, ⚙️ Réglages → MouFlanga) ou, sans réglage, en local (copie de `cover.jpg` dans le dossier de la série, `MANGA_DIR` lu dans `/opt/mouflanga/data/secrets.env`) ; ancienne couverture sauvegardée dans `_anciens-posters/MouFlanga/<série>/`. Ouverture depuis MouFlanga : `?mouflanga=<série>&q=<recherche>&retour=<adresse>` (bandeau + bouton retour).
- **Alertes Telegram** (`notif.py`) : témoin `data/en-marche` effacé à l'arrêt normal (SIGTERM) ; s'il est encore là au démarrage → alerte « plantage » ou « serveur redémarré » (heure de démarrage du serveur comparée au témoin). `au_demarrage()` n'est appelé que dans `if __name__ == "__main__"` (jamais lors d'un import pour un essai). Options `NOTIF_REDEMARRAGE/ERREURS/LOT/MAJ`.
- **Générique manquant** : après `/api/library/apply`, `_a_un_generique()` (même règle que MouFlopening : theme.<audio> ≥ 8 Ko ou theme-music/) ; si absent, fenêtre « Ouvrir MouFlopening » → `<mouflopening>/?dossier=<chemin>&retour=…` (adresses `MOUFLOPENING_URL` / `_EXTERNE`). MouFlopening : `ouvrirDepuisLien()` sélectionne le titre (champ `chemin` de /api/library).

## Bouton « 🔄 Redémarrer l'appli » (les quatre applis)
- `redemarrer.py`, **fichier identique dans les quatre dépôts** : route `POST /api/redemarrer` (admin), prévient si un travail long est en cours (`forcer` pour passer outre), s'envoie SIGTERM (témoin effacé), systemd relance. Le bouton est ajouté par `ui/mou-settings.js` (onglet Général).

## Alerte « redémarrage inattendu » (MouFlanga, MouFlanimeXer, MouFlopening)
- `redemarrage.py`, **fichier identique dans les trois dépôts** : témoin `data/en-marche` (effacé sur SIGTERM), `verifier()` appelé seulement au lancement du vrai service, case dans ⚙️ Réglages (`data/alerte-redemarrage-coupee`). MouFloster a la même logique dans `notif.py`.
- **Lot de posters** : plusieurs titres d'un coup ; n'envoie automatiquement que quand le dossier est trouvé avec certitude (sinon le poster est gardé pour envoi manuel).
- Clés : TMDB et Emby via la page Réglages ou `set-secret.sh` (`TMDB_API_KEY`, `EMBY_API_KEY`, `EMBY_URL`). Sorties dans `/mnt/mouflosyno/MouFloster`. Pas de dossier `tests` ; les essais se font sur une copie avec de fausses données.
- Piège connu : dans le gabarit HTML (chaîne Python entre triples guillemets), un `\'` ou `\s` dans le JavaScript est interprété par Python ; utiliser `’` ou doubler la barre oblique.

## MouFlopening (`app.py` + `mouflopening.py` + `src/`, v1.0)
- Télécharge le **générique de chaque anime ou série** (`theme.mp3` dans le dossier du titre) pour Emby. Sources : AnimeThemes, ThemerrDB, YouTube (`yt-dlp`, avec cookies facultatifs). Recherche, filtre « sans thème / recherché sans résultat », éditeur audio (recadrage, normalisation en dB réglable, `AUTO_TRIM`), anciens thèmes restaurables (`/api/backups*`), détection de doublons.
- Tâches en arrière-plan (`src/progress.py`) avec verrou `_work_lock` ; installation d'un thème = copie de l'ancien en sauvegarde puis `os.replace`. Les échecs passagers (partage réseau, YouTube) sont préfixés `⏳ ` et ne mettent pas le titre de côté.
- **Lot de nuit** (`src/nightly.py`) à l'heure choisie + **compte rendu Telegram** (échecs regroupés par cause) ; registre des titres mis de côté `data/skipped.json` (raison, date, « réessayer après N jours »).
- Réglages : `config.json` (catégories de bibliothèque), `data/secrets.env` (clé Emby, jeton Telegram, cookies). Page Réglages avec dB, rognage automatique, délai de réessai, Telegram.
- Service `mouflopening.service`, venv dans `/opt/mouflopening/venv`. Tests : `python3 -m unittest discover -s tests` (nombreux).

## MouFlanga (`app.py`, `archives.py`, v2.0)
- Bibliothèque : chaque sous-dossier du dossier des mangas (réglage `MANGA_DIR`, défaut `/mnt/mouflosyno/Manga`) est une série ; chaque `.cbz` / `.cbr` / `.zip` / `.rar` est un chapitre ou un tome. Les `.cbr` sont souvent des ZIP : on regarde le contenu, pas l'extension (`archives.py` ; vrais RAR via `rarfile` + `bsdtar`).
- Couverture = première page du premier fichier (ou `cover.jpg`), mise en cache dans `data/covers`. Progression dans `data/progress.json` (chapitres lus, page en cours).
- Lecteur `/lire` : une page ou défilement, sens manga ou occidental, reprise à la page, chapitre suivant automatique. Les chemins demandés sont vérifiés : tout ce qui sort du dossier des mangas (`../`, lien symbolique) est refusé.
- D'autres modules ont été ajoutés ensuite par une autre session de Claude Code (téléchargement depuis un site, alertes Telegram, corbeille) ; ils ne sont pas décrits ici : lire le `CLAUDE.md` du dépôt MouFlanga.
- Service `mouflanga.service`, venv dans `/opt/mouflanga/venv`. Tests : `python3 -m unittest discover -s tests`.

