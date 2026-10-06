# Installation et remise en route de MouFlanga

Ce guide sert à installer MouFlanga sur le serveur (Proxmox / LXC) et à tout remettre en place après une panne ou une migration. Toutes les commandes se tapent en `root`, sans `sudo`.

## 1. Installer

```bash
cd /opt
git clone https://github.com/mouflo/MouFlanga.git mouflanga
bash /opt/mouflanga/install.sh
```

Le script `install.sh` :
- crée l'environnement Python (`venv`) et installe les dépendances ;
- essaie d'installer un outil de décompression RAR (`bsdtar`), utile seulement pour les vrais `.cbr` ;
- installe et démarre le service `mouflanga` (port **5002**) ;
- ajoute **une ligne** à la crontab pour la mise à jour automatique, sans toucher aux autres lignes.

Si le dépôt est privé, `git clone` demande un accès : crée un jeton GitHub en lecture seule limité à ce dépôt (*Settings → Developer settings → Fine-grained tokens*), et ne le colle jamais dans une conversation. Le jeton n'est utile qu'au clonage (le `git pull` automatique le garde dans la configuration de git sur le serveur).

## 2. Définir l'identifiant

```bash
bash /opt/mouflanga/set-login.sh
```

Le script demande un identifiant et un mot de passe (8 caractères minimum). Seul un hash du mot de passe est conservé, dans `data/secrets.env`.

## 3. Choisir le dossier des mangas

Ouvre `http://IP-DU-SERVEUR:5002`, clique sur ⚙️ Réglages, puis sur 📂 Parcourir. Valeur par défaut : `/mnt/mouflosyno/Manga`. L'appli redémarre toute seule après l'enregistrement.

## 4. Mise à jour automatique

Chaque minute, `deploy.sh` compare le serveur à GitHub. S'il y a du nouveau, il met le code à jour, installe les dépendances si besoin et redémarre l'appli. Les réglages et la progression de lecture (dossier `data/`) ne sont jamais touchés.

- Journal du déploiement : `tail -f /var/log/mouflanga-cron.log`
- Journal de l'appli : `journalctl -u mouflanga -n 50`
- Tout est aussi visible dans l'appli, bouton 🩺 **Journal**

## 5. Reconstruire après une panne

1. Refaire l'étape 1 (cloner et lancer `install.sh`).
2. Remettre le dossier `data/` sauvegardé (identifiant, progression, réglages), ou refaire les étapes 2 et 3.
3. Vérifier que le partage réseau est bien monté (`ls /mnt/mouflosyno`).

## Fichiers propres au serveur (jamais sur GitHub)

| Fichier | Contenu |
|---|---|
| `data/secrets.env` | identifiant, mot de passe haché, dossier des mangas |
| `data/progress.json` | chapitres lus et page en cours |
| `data/covers/` | couvertures déjà calculées (peuvent être supprimées sans risque) |
| `data/mouflanga.log` | journal de l'appli |

## Problèmes courants

- **« Dossier des mangas introuvable »** : le partage réseau n'est pas monté, ou le chemin est faux. Corrige-le dans ⚙️ Réglages.
- **Un `.cbr` ne s'ouvre pas** : le Journal indique s'il s'agit d'un vrai RAR sans outil de décompression. Installe-le avec `apt-get install libarchive-tools`, puis `./venv/bin/python -m pip install rarfile`.
- **L'appli ne répond plus** : `systemctl restart mouflanga`, puis ouvre le Journal.
