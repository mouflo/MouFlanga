#!/bin/bash
# MouFlanga - Script d'installation

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
INSTALL_DIR="/opt/mouflanga"
PYTHON="python3"

echo "╔════════════════════════════════════════════════════════════╗"
echo "║            MouFlanga - Installation                        ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Vérifier Python
if ! command -v $PYTHON &> /dev/null; then
    echo "❌ Python 3 n'est pas installé"
    exit 1
fi

echo "✅ Python trouvé: $(python3 --version)"
echo ""

# Créer le répertoire d'installation
if [ -d "$INSTALL_DIR" ]; then
    echo "📂 MouFlanga existe déjà dans $INSTALL_DIR"
    read -p "Remplacer ? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$INSTALL_DIR"
    else
        exit 0
    fi
fi

mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/"
echo "✅ Fichiers copiés dans $INSTALL_DIR"
echo ""

# Créer l'environnement virtuel
cd "$INSTALL_DIR"
$PYTHON -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt

echo "✅ Environnement virtuel créé et dépendances installées"
echo ""

# Créer les répertoires
mkdir -p "$INSTALL_DIR/data"
chmod 755 "$INSTALL_DIR"

# Créer le fichier de configuration
cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env" 2>/dev/null || true

echo "✅ Répertoires créés"
echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║            Installation terminée ! 🎉                     ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "📌 Prochaines étapes:"
echo ""
echo "1. Lance l'application:"
echo "   cd $INSTALL_DIR"
echo "   source venv/bin/activate"
echo "   python3 app.py"
echo ""
echo "2. Ouvre http://localhost:5002"
echo ""
echo "3. Configure tes répertoires dans ⚙️ Réglages"
echo ""
echo "Besoin d'aide ? Voir INSTALL.md"
