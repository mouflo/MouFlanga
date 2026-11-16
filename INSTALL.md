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
- ne touche pas à la crontab : il n'y a pas de mise à jour automatique.

Si le dépôt est privé, `git clone` demande un accès : crée un jeton GitHub en lecture seule limité à ce dépôt (*Settings → Developer settings → Fine-grained tokens*), et ne le colle jamais dans une conversation. Le jeton n'est utile qu'au clonage (`git pull` le garde ensuite dans la configuration de git sur le serveur).

## 2. Définir l'identifiant

```bash
bash /opt/mouflanga/set-login.sh
```

Le script demande un identifiant et un mot de passe (8 caractères minimum). Seul un hash du mot de passe est conservé, dans `data/secrets.env`.

## 3. Choisir le dossier des mangas

Ouvre `http://IP-DU-SERVEUR:5002`, clique sur ⚙️ Réglages, puis sur 📂 Parcourir. Valeur par défaut : `/mnt/mouflosyno/Manga`. L'appli redémarre toute seule après l'enregistrement.

## 4. Mettre à jour

Rien ne se met à jour tout seul. Quand il y a du nouveau sur GitHub :

```bash
cd /opt/mouflanga && git pull && venv/bin/pip install -r requirements.txt
curl -s http://127.0.0.1:5002/api/occupe        # doit répondre "occupe": false
systemctl restart mouflanga
```

Les réglages et la progression de lecture (dossier `data/`) ne sont jamais touchés. Si l'appli est occupée (import, rangement, téléchargement), attends la fin avant de la redémarrer.

- Journal de l'appli : `journalctl -u mouflanga -n 50`
- Tout est aussi visible dans l'appli, bouton 🩺 **Journal**

## Option : la restauration IA des petits scans (✨ Améliorer → 🧠)

Sans rien installer, l'appli fonctionne comme avant (le réglage est ignoré et l'aperçu l'indique). Pour l'activer, sur le serveur (calcul sur processeur, aucune carte graphique nécessaire) :

```bash
apt install libomp5
venv/bin/pip install --no-deps realcugan-ncnn-py     # environ 46 Mo ; --no-deps car il réclame opencv-python, déjà présent en version « headless »
systemctl restart mouflanga
```

Les modèles sont livrés dans le paquet : rien d'autre à télécharger. Sur le processeur : environ 9 secondes par page, avec la moitié des cœurs (`MOUFLANGA_IA_THREADS` pour changer).

**Beaucoup plus vite avec la carte graphique Intel (environ 1,5 seconde par page).** L'appli s'en sert toute seule quand le conteneur la voit (`ls /dev/dri/renderD128`). Sur l'hôte Proxmox, ajouter au fichier du conteneur (`/etc/pve/lxc/<numéro>.conf`) puis `pct reboot <numéro>` :

```
lxc.cgroup2.devices.allow: c 226:0 rwm
lxc.cgroup2.devices.allow: c 226:128 rwm
lxc.mount.entry: /dev/dri dev/dri none bind,optional,create=dir
lxc.mount.entry: /dev/dri/renderD128 dev/dri/renderD128 none bind,optional,create=file
```

Le « Rapport » de l'appli (section « Carte graphique ») dit si elle est visible. Pour forcer le processeur : variable `MOUFLANGA_IA_GPU=non`.

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
