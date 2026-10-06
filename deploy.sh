#!/bin/bash
# Déploiement automatique de MouFlanga : lancé chaque minute par cron (voir setup-cronjob.sh).
# Si GitHub a du nouveau : récupère le code, met à jour les dépendances si besoin, redémarre l'appli.

if [ -d "/opt/mouflanga" ]; then
    REPO_DIR="/opt/mouflanga"
elif [ -d "/root/mouflanga" ]; then
    REPO_DIR="/root/mouflanga"
else
    echo "❌ Dossier mouflanga introuvable !"
    exit 1
fi

LOG_FILE="/var/log/mouflanga-deploy.log"
SERVICE_NAME="mouflanga"

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}
touch "$LOG_FILE"

cd "$REPO_DIR" || exit 1
OLD_COMMIT=$(git rev-parse HEAD)
git fetch origin -q || { log "⚠️ GitHub injoignable, nouvel essai à la prochaine minute"; exit 0; }
NEW_COMMIT=$(git rev-parse origin/main 2>/dev/null || git rev-parse origin/master)

if [ "$OLD_COMMIT" = "$NEW_COMMIT" ]; then
    exit 0
fi

# Un import, un rangement ou un téléchargement est en cours : on attend (nouvel essai à la minute suivante)
OCCUPE=$(curl -s -m 5 http://127.0.0.1:5002/api/occupe 2>/dev/null)
if echo "$OCCUPE" | grep -q '"occupe": *true'; then
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ⏸ Mise à jour reportée : $(echo "$OCCUPE" | sed -E 's/.*"raisons": *\[([^]]*)\].*/\1/')" >> "$LOG_FILE"
    exit 0
fi

log "=== 🚀 Déploiement MouFlanga détecté ==="
log "Ancien commit: $OLD_COMMIT"
log "Nouveau commit: $NEW_COMMIT"
log "📥 Téléchargement des changements..."
git reset --hard origin/main -q || git reset --hard origin/master -q

# Dépendances : seulement si requirements.txt a changé
if git diff "$OLD_COMMIT" HEAD -- requirements.txt | grep -q .; then
    log "📦 Installation des dépendances (requirements.txt modifié)..."
    if [ -d "./venv" ]; then
        ./venv/bin/python -m pip install -q -r requirements.txt 2>&1 | tee -a "$LOG_FILE"
    else
        log "⚠️ Dossier venv introuvable : dépendances non installées"
    fi
fi

# Écran virtuel (Chromium du scraper) : installé si absent, puis service mis à jour si besoin
if ! command -v xvfb-run >/dev/null 2>&1; then
    log "📦 Installation de xvfb (écran virtuel pour le scraper)..."
    apt-get install -y -q xvfb >>"$LOG_FILE" 2>&1
fi
if ! command -v unar >/dev/null 2>&1; then
    log "📦 Installation de unar (extraction de secours des archives RAR)..."
    apt-get install -y -q unar >>"$LOG_FILE" 2>&1 || log "⚠️ unar non installé : certaines archives RAR ne pourront pas être importées"
fi
if ! command -v xdotool >/dev/null 2>&1; then
    log "📦 Installation de xdotool (vrai clic de souris pour la vérification Cloudflare)..."
    apt-get install -y -q xdotool >>"$LOG_FILE" 2>&1 || log "⚠️ xdotool non installé : clic par automatisation à la place"
fi
if command -v xvfb-run >/dev/null 2>&1 && ! cmp -s "$REPO_DIR/mouflanga.service" /etc/systemd/system/mouflanga.service; then
    log "🛠 Mise à jour du fichier de service..."
    cp "$REPO_DIR/mouflanga.service" /etc/systemd/system/mouflanga.service
    systemctl daemon-reload
fi
# Navigateur de Patchright (idempotent : ne retélécharge pas s'il est déjà là)
if [ -x "./venv/bin/python" ]; then
    ./venv/bin/python -m patchright install chromium >>"$LOG_FILE" 2>&1 || log "⚠️ Installation de Chromium (Patchright) échouée, voir le journal"
    # Vrai Google Chrome : bien mieux accepté par Cloudflare que Chromium (facultatif, sinon Chromium est utilisé)
    if ! command -v google-chrome >/dev/null 2>&1 && ! command -v google-chrome-stable >/dev/null 2>&1; then
        log "📦 Installation de Google Chrome (Patchright)..."
        ./venv/bin/python -m patchright install chrome >>"$LOG_FILE" 2>&1 || log "⚠️ Google Chrome non installé : Chromium sera utilisé"
    fi
fi

# Mémo commun pour Claude Code : copie à jour dans /opt/CLAUDE.md (source : docs/claude-opt.md)
if [ -f "$REPO_DIR/docs/claude-opt.md" ]; then
    cp -f "$REPO_DIR/docs/claude-opt.md" /opt/CLAUDE.md 2>/dev/null && log "📝 Mémo /opt/CLAUDE.md mis à jour"
fi

log "🔄 Redémarrage du service..."
if systemctl is-active --quiet "$SERVICE_NAME"; then
    systemctl restart "$SERVICE_NAME"
else
    systemctl start "$SERVICE_NAME"
fi
sleep 2
if systemctl is-active --quiet "$SERVICE_NAME"; then
    log "✅ Déploiement réussi ! Service redémarré."
else
    log "❌ Erreur : le service n'a pas pu redémarrer (voir : journalctl -u $SERVICE_NAME -n 50)"
    exit 1
fi
log "=== Fin du déploiement MouFlanga ==="
