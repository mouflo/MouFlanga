#!/bin/bash
# Installation de MouFlanga sur le serveur (Proxmox / LXC), à lancer UNE fois après le clonage dans /opt/mouflanga :
#   cd /opt && git clone https://github.com/mouflo/MouFlanga.git mouflanga && bash /opt/mouflanga/install.sh
set -e
REPO_DIR="/opt/mouflanga"

echo "📚 Installation de MouFlanga"
echo "============================"
[ -d "$REPO_DIR" ] || { echo "❌ $REPO_DIR introuvable : clone d'abord le dépôt dans /opt"; exit 1; }
command -v python3 >/dev/null || { echo "❌ Python 3 n'est pas installé"; exit 1; }
cd "$REPO_DIR"

echo "🐍 Environnement Python et dépendances..."
python3 -m venv venv
./venv/bin/python -m pip install -q --upgrade pip
./venv/bin/python -m pip install -q -r requirements.txt

# Lecture des vrais fichiers RAR (.cbr) : un outil de décompression est nécessaire (facultatif)
if ! command -v unrar >/dev/null && ! command -v 7z >/dev/null && ! command -v bsdtar >/dev/null; then
    echo "📦 Outil de décompression RAR (pour les vrais .cbr)..."
    (apt-get install -y -qq libarchive-tools >/dev/null 2>&1 && echo "✅ bsdtar installé") || echo "⚠️ Installation impossible : seuls les .cbz et les .cbr en ZIP s'ouvriront (voir le Journal)"
fi

mkdir -p data
chmod +x deploy.sh setup-cronjob.sh set-login.sh set-secret.sh

echo "⚙️  Service systemd..."
cp mouflanga.service /etc/systemd/system/mouflanga.service
systemctl daemon-reload
systemctl enable mouflanga >/dev/null 2>&1
systemctl restart mouflanga

echo "⏱️  Mise à jour automatique (cronjob, ajoutée sans toucher aux autres)..."
bash "$REPO_DIR/setup-cronjob.sh"

echo ""
echo "✅ Installation terminée !"
echo "🌐 Accès : http://IP-DU-SERVEUR:5002"
echo "🔒 Définis ton identifiant : bash /opt/mouflanga/set-login.sh"
echo "📁 Dossier des mangas : ⚙️ Réglages dans l'appli (par défaut /mnt/mouflosyno/Manga)"
