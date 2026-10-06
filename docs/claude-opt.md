# Serveur MouFluxer : mémo complet pour Claude Code

Ce fichier est lu au démarrage de Claude Code quand on le lance depuis `/opt` (ou depuis le dossier d'une appli). Il résume toute la suite d'applis MouFl pour éviter de tout redécouvrir.
Source : `docs/claude-opt.md` du dépôt MouFlanga, recopié dans `/opt/CLAUDE.md` à chaque déploiement de MouFlanga. **Pour le modifier, change le fichier dans le dépôt, pas dans `/opt`** (il serait écrasé).

## La personne
- Elle pilote tout depuis son **téléphone** (SSH par VPN) et n'a presque jamais accès à un ordinateur : tout doit être utilisable au téléphone (boutons de l'appli, commandes courtes à copier).
- Elle se dit nulle en ligne de commande : explications simples, sans jargon.
- Elle est `root` sur Proxmox : **jamais de `sudo`** dans les commandes.
- Elle préfère que Claude fasse tout lui-même (lancer, tester, vérifier) plutôt que de lui demander de taper des commandes.
- **Tout en français, jamais d'anglais** : réponses, commits, README, CHANGELOG, textes des pages, messages d'erreur.

## Règles à respecter
- **Prévenir avant de pousser** sur GitHub ou de redémarrer un service pendant qu'un long traitement tourne : chaque poussée sur `main` redémarre l'appli dans la minute. Dans chaque réponse qui pousse, rappeler que l'appli redémarre.
- **Ne jamais remplacer la crontab** : seulement y ajouter des lignes.
- **Aucun secret** (clés API, jetons, mots de passe) dans le chat ni sur GitHub ni dans un fichier suivi par git. Les secrets vont dans `data/secrets.env` (droits 600, ignoré par git) via les boutons de l'appli ou `bash set-secret.sh NOM "valeur"`.
- Le **README GitHub est toujours entièrement en français**, et les **captures d'écran** (`docs/screenshots`) sont refaites à chaque grosse mise à jour.
- La page **⚙️ Réglages** garde le même style et les mêmes réglages communs dans les quatre applis (pour pouvoir l'exporter d'une appli à l'autre).
- Les polices sous licence (Arial…) ne vont **jamais** sur GitHub (dossier `data/fonts`, ignoré).
- Les messages de commit sont en français et se terminent par la ligne `Co-Authored-By` habituelle.

## Le serveur
- Conteneur LXC Debian nommé **MouFluxer** sur Proxmox, Python **3.11** (pas de barre oblique inverse dans une expression de f-string).
- Le NAS Synology est monté sous `/mnt/mouflosyno` : médiathèque Emby dans `/mnt/mouflosyno/Emby-Media/` (sous-dossiers `Films HD`, `Films 4k`, `Series`, `Manga`, `Sentai`, un dossier par titre `Titre (Année)`). Si le partage n'est pas monté, les applis le signalent au lieu de planter.
- Emby tourne sur `http://192.168.1.134:8096`. Sonarr et qBittorrent tournent à côté ; le DNS est AdGuard Home (192.168.1.139).
- Chaque appli est dans `/opt/<nom>` avec son dépôt GitHub `mouflo/<Nom>` (tous publics), un service systemd du même nom et un **déploiement automatique** : une ligne de cron lance `deploy.sh` chaque minute ; s'il y a du nouveau sur `main`, il fait `git reset --hard origin/main`, réinstalle les dépendances si `requirements.txt` a changé et redémarre le service. **Pousser sur `main` = mettre en ligne.**
- Journaux : `journalctl -u <nom> -n 50`, `/var/log/<nom>-deploy.log` (déploiement), `/var/log/<nom>-cron.log`, `data/<nom>.log` (appli). Le bouton 🩺 **Journal** de chaque appli rassemble tout en un rapport à copier-coller.

| Appli | Dossier | Port | Rôle |
|---|---|---|---|
| MouFlanimeXer | `/opt/mouflanimexer` | 5000 | remux des épisodes (audio, sous-titres) + surveillant Sonarr automatique |
| MouFloster | `/opt/moufloster` | 8000 | fabrique de posters TheMovieDB, envoi dans la médiathèque Emby |
| MouFlopening | `/opt/mouflopening` | 8001 | génériques (« theme songs ») pour Emby |
| MouFlanga | `/opt/mouflanga` | 5002 | bibliothèque et lecteur de mangas (.cbz / .cbr) |

## Ce qui est commun aux quatre applis
- **Flask**, une page d'accueil, une page **⚙️ Réglages**, connexion par identifiant et mot de passe haché (`set-login.sh`), Journal de diagnostic (`diag.py`), explorateur de dossiers (`fs_browser.py`).
- **Kit d'interface partagé, fichiers identiques dans les quatre dépôts** : `ui/mou-ui.css`, `ui/mou-ui.js` (en-tête, fenêtre Journal), `ui/mou-settings.css`, `ui/mou-settings.js`, `fs_browser.py`. On modifie à un seul endroit puis on **recopie dans les trois autres** (vérifier avec `md5sum`). `auth.py` et `diag.py` ressemblent d'une appli à l'autre mais diffèrent par le nom de l'appli et les sections propres.
- Thème sombre, vert `#52b54b`, titre « MouFl » en blanc + suite du nom en vert, police Noto Sans. Les pages marchent au téléphone (champs en 16 px, boutons larges).
- **Version** affichée = base manuelle (`BASE_VERSION`) + nombre de commits + hash court.
- **Secrets et réglages locaux** dans `data/` (jamais sur GitHub) : `data/secrets.env`, `data/session_key`, selon l'appli `data/paths.json`, `data/progress.json`, etc. `_write_secret` écrit en droits 600 ; les valeurs ne doivent pas contenir `"`, `$`, `` ` ``, `\` ni saut de ligne (rejetées par les pages de réglages).
- Changer un dossier dans ⚙️ Réglages fait redémarrer l'appli toute seule (`os._exit(0)`, systemd la relance).
- Les clés ne sont jamais renvoyées à la page (seulement les 4 derniers caractères) et sont masquées dans les journaux (`_RedactFormatter`).

- **Telegram par sujets** : un seul bot, un groupe à sujets, un sujet par appli. Chaque appli a son propre numéro de sujet (`thread_id` dans `telegram_config.json` pour MouFlanimeXer, `TELEGRAM_THREAD_ID` dans `data/secrets.env` pour les autres), envoyé en `message_thread_id` ; vide = message normal. Le sujet n'est jamais repris d'une autre appli.

## MouFlanimeXer (`mouflanimexer.py`, v3.33)
- Remux MKV d'épisodes : garde les pistes audio japonaise/française, traite les sous-titres ASS (mise à l'échelle de la résolution y compris `\iclip`, dessins, bordures et ombres ; style imposé ; polices vérifiées et embarquées depuis la bibliothèque `/opt/mouflanimexer/fonts`). Un fichier dont une police manque est mis de côté dans « À traiter (police manquante) ».
- Deux usages : l'**interface web** (scan d'un dossier, file d'attente, pause) et le **surveillant Sonarr** lancé par cron toutes les 2 minutes (`python3 mouflanimexer.py --watch-sonarr`). Le surveillant parcourt le dossier manga (`.mkv` et `.mp4`), traite chaque fichier stable et nouveau, **remplace l'original en place** (`os.replace`), puis demande à Sonarr un rescan + renommage. Il envoie un compte rendu Telegram par fichier.
- Verrou `fcntl` (un seul passage à la fois), retard croissant après un échec (30 min jusqu'à 24 h), alerte NAS inaccessible (une par heure).
- Réglages : `data/paths.json` (dossiers : travail, scan par défaut, dossiers surveillés, `watch_mp4`), `telegram_config.json` et `sonarr_api_config.json` dans `/opt/mouflanimexer` (hors git, écrits par la page Réglages), table de correspondance des chemins Sonarr ↔ serveur.
- État : `sonarr_watch_state.json` (fichiers déjà traités + marqueur `__mp4_connus__`), `sonarr_watch_failures.json`, journal des décisions `.jsonl` dans `<dossier de travail>/Log`. Sorties terminées dans `FICHIER OK/<série>`, sorties temporaires du surveillant dans `.en-cours-auto`.
- Séries exclues (style conservé, ex. One Piece) et pistes de sous-titres supplémentaires par série : commandes `--list-series`, `--exclude-series`, `--add-extra-sub-lang` (voir `INSTALL.md`).
- Python système (pas de venv), service `mouflanimexer.service`. Tests : `python3 -m unittest discover -s tests`.

## MouFloster (`app.py`, ~3 000 lignes, page HTML et JavaScript dans le même fichier)
- Cherche films, séries et **sagas** sur TheMovieDB, fabrique des posters 1000×1500 : cadre blanc (« anime » 45 px ou standard 22 px), dégradé noir, jusqu'à 5 textes (Arial Bold), numéro de saison, zoom 50–300 %, recadrage au doigt, effacement de texte/logo (OpenCV, ou **LaMa** installé en arrière-plan par `deploy.sh`).
- **Envoi dans la médiathèque** (`library.py`) : repère le bon dossier (mémorisé par identifiant TMDB dans `data/layouts.json` et le choix de dossier), compare ancien et nouveau poster, **sauvegarde toujours l'ancien** (`<nom>.<date>.jpg`, restaurable depuis la page), puis actualise seulement le titre concerné dans Emby (`emby.py`). Vignettes d'épisode `S00E100-thumb.jpg`. Sagas : image envoyée directement dans la collection Emby.
- **Couverture dans MouFlanga** (`mouflanga_link.py`) : par le réseau (adresse + clé API de MouFlanga, `MOUFLANGA_URL` / `MOUFLANGA_CLE`, ⚙️ Réglages → MouFlanga) ou, sans réglage, en local (copie de `cover.jpg` dans le dossier de la série, `MANGA_DIR` lu dans `/opt/mouflanga/data/secrets.env`) ; ancienne couverture sauvegardée dans `_anciens-posters/MouFlanga/<série>/`. Ouverture depuis MouFlanga : `?mouflanga=<série>&q=<recherche>&retour=<adresse>` (bandeau + bouton retour).
- **Alertes Telegram** (`notif.py`) : témoin `data/en-marche` effacé à l'arrêt normal (SIGTERM) ; s'il est encore là au démarrage → alerte « plantage » ou « serveur redémarré » (heure de démarrage du serveur comparée au témoin). `au_demarrage()` n'est appelé que dans `if __name__ == "__main__"` (jamais lors d'un import pour un essai). Options `NOTIF_REDEMARRAGE/ERREURS/LOT/MAJ`.

## Alerte « redémarrage inattendu » (MouFlanga, MouFlanimeXer, MouFlopening)
- `redemarrage.py`, **fichier identique dans les trois dépôts** : témoin `data/en-marche` (effacé sur SIGTERM), `verifier()` appelé seulement au lancement du vrai service, case dans ⚙️ Réglages (`data/alerte-redemarrage-coupee`). MouFloster a la même logique dans `notif.py`.
- **Lot de posters** : plusieurs titres d'un coup ; n'envoie automatiquement que quand le dossier est trouvé avec certitude (sinon le poster est gardé pour envoi manuel).
- Clés : TMDB et Emby via la page Réglages ou `set-secret.sh` (`TMDB_API_KEY`, `EMBY_API_KEY`, `EMBY_URL`). Sorties dans `/mnt/mouflosyno/MouFloster`. Pas de dossier `tests` ; les essais se font sur une copie avec de fausses données.
- Piège connu : dans le gabarit HTML (chaîne Python entre triples guillemets), un `\'` ou `\s` dans le JavaScript est interprété par Python ; utiliser `’` ou doubler la barre oblique.

## MouFlopening (`app.py` + `mouflopening.py` + `src/`, v0.26)
- Télécharge le **générique de chaque anime ou série** (`theme.mp3` dans le dossier du titre) pour Emby. Sources : AnimeThemes, ThemerrDB, YouTube (`yt-dlp`, avec cookies facultatifs). Recherche, filtre « sans thème / recherché sans résultat », éditeur audio (recadrage, normalisation en dB réglable, `AUTO_TRIM`), anciens thèmes restaurables (`/api/backups*`), détection de doublons.
- Tâches en arrière-plan (`src/progress.py`) avec verrou `_work_lock` ; installation d'un thème = copie de l'ancien en sauvegarde puis `os.replace`. Les échecs passagers (partage réseau, YouTube) sont préfixés `⏳ ` et ne mettent pas le titre de côté.
- **Lot de nuit** (`src/nightly.py`) à l'heure choisie + **compte rendu Telegram** (échecs regroupés par cause) ; registre des titres mis de côté `data/skipped.json` (raison, date, « réessayer après N jours »).
- Réglages : `config.json` (catégories de bibliothèque), `data/secrets.env` (clé Emby, jeton Telegram, cookies). Page Réglages avec dB, rognage automatique, délai de réessai, Telegram.
- Service `mouflopening.service`, venv dans `/opt/mouflopening/venv`. Tests : `python3 -m unittest discover -s tests` (nombreux).

## MouFlanga (`app.py`, `archives.py`, v1.0+)
- Bibliothèque : chaque sous-dossier du dossier des mangas (réglage `MANGA_DIR`, défaut `/mnt/mouflosyno/Manga`) est une série ; chaque `.cbz` / `.cbr` / `.zip` / `.rar` est un chapitre ou un tome. Les `.cbr` sont souvent des ZIP : on regarde le contenu, pas l'extension (`archives.py` ; vrais RAR via `rarfile` + `bsdtar`).
- Couverture = première page du premier fichier (ou `cover.jpg`), mise en cache dans `data/covers`. Progression dans `data/progress.json` (chapitres lus, page en cours).
- Lecteur `/lire` : une page ou défilement, sens manga ou occidental, reprise à la page, chapitre suivant automatique. Les chemins demandés sont vérifiés : tout ce qui sort du dossier des mangas (`../`, lien symbolique) est refusé.
- D'autres modules ont été ajoutés ensuite par une autre session de Claude Code (téléchargement depuis un site, alertes Telegram, corbeille) ; ils ne sont pas décrits ici : lire le `CLAUDE.md` du dépôt MouFlanga.
- Service `mouflanga.service`, venv dans `/opt/mouflanga/venv`. Tests : `python3 -m unittest discover -s tests`.

## Façon de travailler
1. Lire le `CLAUDE.md` de l'appli concernée (s'il existe) puis son `README.md` et son `INSTALL.md`.
2. Modifier, puis lancer les tests de l'appli (`python3 -m unittest discover -s tests`) avant toute poussée.
3. Vérifier les pages au téléphone (largeur 390 px) et dans le Journal de l'appli, pas seulement en ligne de commande.
4. Mettre à jour `CHANGELOG.md`, le README et les captures si c'est une grosse mise à jour ; tout en français.
5. Prévenir, puis pousser sur `main` ; contrôler dans `/var/log/<nom>-deploy.log` que le déploiement a réussi.
- Ne jamais lancer `pkill -f` ou `pgrep -f` avec un motif présent dans la même commande : cela peut tuer le shell lui-même.
- Si le kit d'interface partagé change, le recopier dans les quatre dépôts et pousser les quatre.
