#!/usr/bin/env bash
# Installe Claude Code sur le serveur (une seule fois) et prépare le dossier /opt.
set -e

echo "== Installation de Claude Code =="
if command -v claude >/dev/null 2>&1 || [ -x "$HOME/.local/bin/claude" ]; then
    echo "Claude Code est déjà installé."
else
    if ! command -v curl >/dev/null 2>&1; then
        echo "curl est absent : installation..."
        apt-get update -y && apt-get install -y curl ca-certificates
    fi
    curl -fsSL https://claude.ai/install.sh | bash
fi

# Le programme est rangé dans ~/.local/bin : on l'ajoute au PATH s'il n'y est pas (sans rien écraser)
if ! grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
fi
export PATH="$HOME/.local/bin:$PATH"

# Mémo commun à toutes les applis, lu par Claude Code quand on le lance depuis /opt
SRC="$(dirname "$0")/../docs/claude-opt.md"
if [ -f "$SRC" ] && [ ! -f /opt/CLAUDE.md ]; then
    cp "$SRC" /opt/CLAUDE.md
    echo "Mémo copié dans /opt/CLAUDE.md"
fi

echo
echo "== Terminé =="
echo "Pour l'utiliser :   cd /opt && claude"
echo "La première fois, il affiche un lien à ouvrir sur ton téléphone pour te connecter."
