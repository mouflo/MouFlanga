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

## Détails par appli
Fonctionnement interne de chaque appli (modules, réglages, pièges connus) : `/opt/mouflanga/docs/apps-details.md` (sections MouFlanimeXer, MouFloster, MouFlopening, MouFlanga, alerte et bouton de redémarrage). À lire seulement pour l'appli sur laquelle on travaille ; MouFlanga a en plus `/opt/mouflanga/CLAUDE.md`.

## Façon de travailler
1. Lire le `CLAUDE.md` de l'appli concernée (s'il existe) puis son `README.md` et son `INSTALL.md`.
2. Modifier, puis lancer les tests de l'appli (`python3 -m unittest discover -s tests`) avant toute poussée.
3. Vérifier les pages au téléphone (largeur 390 px) et dans le Journal de l'appli, pas seulement en ligne de commande.
4. Mettre à jour `CHANGELOG.md`, le README et les captures si c'est une grosse mise à jour ; tout en français.
5. Prévenir, puis pousser sur `main` ; contrôler dans `/var/log/<nom>-deploy.log` que le déploiement a réussi.
- Ne jamais lancer `pkill -f` ou `pgrep -f` avec un motif présent dans la même commande : cela peut tuer le shell lui-même.
- Si le kit d'interface partagé change, le recopier dans les quatre dépôts et pousser les quatre.

## Comptes (octobre 2026)
- **MouFlanga** : rôle « lecteur » (lecture seule, `auth.LECTEUR_OK`, progression `data/progression/<id>.json`), demandes 📮, séries suivies, torrents (Prowlarr + qBittorrent).
- **MouFloster / MouFlopening** : rôle « copain » (`comptes.py` identique dans les deux, `auth.COPAIN_OK` / `COPAIN_PREFIXES` remplis par app.py). MouFloster : posters dans `_copains/<id>`, envoi vers l'Emby DU copain (`emby.serveur(...)`), posters de l'admin en lecture seule. MouFlopening : page `/copain` (`copain_themes.py`), génériques de l'admin ou validés (ThemerrDB, AnimeThemes), jetons serveur.
- Adresses d'Emby des copains : jamais le réseau local ni les domaines de l'admin (`comptes.adresse_permise`).
- Versions : `BASE_VERSION` + commits depuis `DEPART_VERSION` (MouFlanga 2.0, MouFloster 1.0) ; MouFlopening lit le CHANGELOG ([1.0.0]).
- NAS : les fichiers partagés par qBittorrent ne peuvent être ni renommés ni effacés depuis MouFluxer (et certains gros fichiers copiés non plus) : placer directement sous le nom final.
