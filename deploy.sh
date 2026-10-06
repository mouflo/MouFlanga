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
