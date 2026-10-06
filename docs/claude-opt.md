# Serveur MouFluxer : mémo pour Claude Code

Ce fichier est lu au démarrage de Claude Code quand on le lance depuis `/opt`.
Tout est en **français** (réponses, commits, README, CHANGELOG), sans jamais d'anglais.

## La personne
- Elle pilote tout depuis son **téléphone** (SSH par VPN). Elle se dit nulle en ligne de commande : explications simples, pas de jargon.
- Elle est `root` sur Proxmox : **jamais de `sudo`** dans les commandes.
- Elle préfère que Claude fasse tout lui-même (lancer les commandes, tester) plutôt que de lui demander de les taper.

## Règles à respecter
- **Prévenir avant de pousser (push)** ou de redémarrer un service pendant qu'un long traitement tourne : un déploiement redémarre l'appli.
- **Ne jamais remplacer la crontab** : seulement y ajouter des lignes.
- **Aucun secret** (clés, jetons, mots de passe) dans le chat ni sur GitHub : utiliser les boutons de l'appli ou `set-secret.sh`.
- Le README GitHub est toujours en français ; mettre à jour les captures d'écran (`docs/screenshots`) à chaque grosse mise à jour.
- La page **⚙ Réglages** garde le même style et les mêmes réglages communs dans les applis (MouFlanimeXer, MouFloster, MouFlopening, MouFlanga) pour pouvoir l'exporter facilement.

## Les applis (dans `/opt`)
- `mouflanga` : bibliothèque et lecteur de mangas, plus le scraper Japscan (Flask, service `mouflanga.service`).
- `mouflanimexer`, `moufloster`, `mouflopening` : les autres applis de la suite MouFl.
- Chaque appli a son dépôt GitHub (`mouflo/…`) et un **déploiement automatique par cron** (chaque minute : récupération des changements puis redémarrage du service). Pousser sur `main` = mettre en ligne.
- Python 3.11 sur le serveur : pas de barre oblique inverse dans les expressions d'un f-string.
