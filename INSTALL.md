# 📦 Installation - MouFlanga

Guide d'installation complet de MouFlanga sur différentes plateformes.

## 🚀 Installation rapide

### Linux / Proxmox / LXC

```bash
# Cloner le dépôt
cd /opt
git clone https://github.com/mouflo/MouFlanga.git mouflanga
cd mouflanga

# Lancer l'installation
bash install.sh

# Démarrer l'application
source venv/bin/activate
python3 app.py
```

Ouvre http://localhost:5002 🎉

### macOS

```bash
# Cloner le dépôt
git clone https://github.com/mouflo/MouFlanga.git ~/MouFlanga
cd ~/MouFlanga

# Créer l'environnement virtuel
python3 -m venv venv
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt

# Démarrer
python3 app.py
```

Ouvre http://localhost:5002

### Windows

```powershell
# Cloner le dépôt
git clone https://github.com/mouflo/MouFlanga.git C:\MouFlanga
cd C:\MouFlanga

# Créer l'environnement virtuel
python -m venv venv
venv\Scripts\activate

# Installer les dépendances
pip install -r requirements.txt

# Démarrer
python app.py
```

Ouvre http://localhost:5002

## ⚙️ Configuration

### Variables d'environnement

Crée un fichier `.env` dans le répertoire MouFlanga:

```env
# Dossiers
MANGA_DIR=/mnt/data/manga
OUTPUT_DIR=/mnt/data/manga-processed
LIBRARY_DIR=/mnt/mouflosyno/Emby-Media

# Application
FLASK_PORT=5002
FLASK_DEBUG=False
SECRET_KEY=change-me-in-production
```

### Page Réglages

Tout se configure depuis l'interface web → ⚙️ Réglages:

- **Dossier des mangas**: Où sont tes fichiers CBR
- **Dossier Emby**: Optionnel, pour la synchronisation
- **Import automatique**: Ajouter les nouveaux chapitres automatiquement

## 📂 Structure des fichiers

```
mouflanga/
├── app.py                 # Application Flask principale
├── requirements.txt       # Dépendances Python
├── install.sh            # Script d'installation
├── templates/            # Templates HTML
├── ui/                   # CSS et JS
├── static/               # Assets statiques
├── data/                 # Configuration (généré)
└── docs/                 # Documentation
```

## 🐍 Prérequis

- Python 3.9+
- Git (pour cloner)
- ~500 MB d'espace libre (code + dépendances)
- Accès aux fichiers CBR

## 📖 Dépannage

### Erreur "Port 5002 déjà utilisé"

Modifie dans `.env`:
```env
FLASK_PORT=5003
```

### Erreur "Répertoire non trouvé"

Vérifie que les dossiers existent:
```bash
ls -la /mnt/data/manga
```

### Mangas ne s'affichent pas

1. Vérifie le dossier configuré
2. Assure-toi qu'il y a des fichiers `.cbr`
3. Regarde la console pour les erreurs

### Impossible d'enregistrer les réglages

Vérifie les permissions du répertoire `data/`:
```bash
chmod 755 /opt/mouflanga/data
```

## 🚀 Démarrage automatique avec systemd

Crée `/etc/systemd/system/mouflanga.service`:

```ini
[Unit]
Description=MouFlanga - Lecteur de mangas
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/mouflanga
ExecStart=/opt/mouflanga/venv/bin/python3 /opt/mouflanga/app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Puis:
```bash
systemctl enable mouflanga
systemctl start mouflanga
systemctl status mouflanga
```

## 🔄 Mise à jour

```bash
cd /opt/mouflanga
git pull
source venv/bin/activate
pip install -r requirements.txt
systemctl restart mouflanga
```

## 📞 Aide

Besoin d'aide ? Ouvre une [issue sur GitHub](https://github.com/mouflo/MouFlanga/issues).

---

*Dernière mise à jour: 2026-10-06*
