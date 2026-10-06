#!/bin/bash
# Setup Xvfb + dépendances pour Playwright avec anti-détection Cloudflare
# À exécuter sur Proxmox/Debian

echo "Installation Xvfb et dépendances Chromium..."

# Xvfb (serveur d'affichage virtuel)
apt-get update
apt-get install -y xvfb

# Dépendances Chromium (au cas où)
apt-get install -y libnspr4 libnss3 libgbm1 libatk-bridge2.0-0 libatk1.0-0 \
  libxkbcommon0 libpango-1.0-0 libpangoxft-1.0-0 libgtk-3-0 libx11-6

echo "Installation des paquets Python..."
pip install --break-system-packages playwright-stealth

echo ""
echo "✓ Setup terminé !"
echo ""
echo "Pour tester :"
echo "  cd /opt/mouflanga && xvfb-run -a python3 probe_xvfb.py"
echo ""
echo "Note : xvfb-run lance automatiquement un serveur X virtuel"
echo "      avant d'exécuter la commande."
