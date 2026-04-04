#!/bin/bash
# Deploy MIA Dashboard vers VPS
# Usage: bash DASHBOARD/deploy.sh

set -e

VPS="Administrator@212.28.179.199"
REMOTE_BASE="C:/TRADING_SIERRA_CHART_AUTO"
REMOTE_DIR="$REMOTE_BASE/DASHBOARD"

echo "============================================"
echo "  MIA Dashboard — Deploiement VPS"
echo "============================================"

# 1. Creer la structure sur le VPS
echo ""
echo "[1/5] Creation de la structure sur le VPS..."
ssh $VPS "mkdir -p \"$REMOTE_DIR/api\" \"$REMOTE_DIR/static/css\" \"$REMOTE_DIR/static/js\" \"$REMOTE_DIR/static/images\" \"$REMOTE_DIR/briefings\" \"$REMOTE_DIR/tests\""

# 2. Copier le backend Python
echo ""
echo "[2/5] Copie du backend Python..."
scp DASHBOARD/__init__.py "$VPS:\"$REMOTE_DIR/\""
scp DASHBOARD/config.py "$VPS:\"$REMOTE_DIR/\""
scp DASHBOARD/start_dashboard.py "$VPS:\"$REMOTE_DIR/\""
scp DASHBOARD/api/__init__.py "$VPS:\"$REMOTE_DIR/api/\""
scp DASHBOARD/api/app.py "$VPS:\"$REMOTE_DIR/api/\""
scp DASHBOARD/api/data_reader.py "$VPS:\"$REMOTE_DIR/api/\""
scp DASHBOARD/api/models.py "$VPS:\"$REMOTE_DIR/api/\""
scp DASHBOARD/api/auth.py "$VPS:\"$REMOTE_DIR/api/\""
scp DASHBOARD/api/briefing.py "$VPS:\"$REMOTE_DIR/api/\""

# 3. Copier le frontend
echo ""
echo "[3/5] Copie du frontend..."
scp DASHBOARD/static/index.html "$VPS:\"$REMOTE_DIR/static/\""
scp DASHBOARD/static/login.html "$VPS:\"$REMOTE_DIR/static/\""
scp DASHBOARD/static/register.html "$VPS:\"$REMOTE_DIR/static/\""
scp DASHBOARD/static/briefing.html "$VPS:\"$REMOTE_DIR/static/\""
scp DASHBOARD/static/pricing.html "$VPS:\"$REMOTE_DIR/static/\""
scp DASHBOARD/static/css/dashboard.css "$VPS:\"$REMOTE_DIR/static/css/\""
scp DASHBOARD/static/js/dashboard.js "$VPS:\"$REMOTE_DIR/static/js/\""
scp DASHBOARD/static/js/auth.js "$VPS:\"$REMOTE_DIR/static/js/\""
scp DASHBOARD/static/js/ticker-widget.js "$VPS:\"$REMOTE_DIR/static/js/\""

# 4. Copier les images
echo ""
echo "[4/5] Copie des images..."
for img in DASHBOARD/static/images/*; do
    if [ -f "$img" ]; then
        scp "$img" "$VPS:\"$REMOTE_DIR/static/images/\""
    fi
done

# 5. Installer les dependances + demarrer
echo ""
echo "[5/5] Installation des dependances..."
ssh $VPS "pip install fastapi uvicorn"

echo ""
echo "============================================"
echo "  DEPLOIEMENT TERMINE"
echo "============================================"
echo ""
echo "Pour demarrer le dashboard sur le VPS :"
echo "  ssh $VPS"
echo "  cd C:\\TRADING_SIERRA_CHART_AUTO"
echo "  python DASHBOARD/start_dashboard.py"
echo ""
echo "Ou en arriere-plan :"
echo "  pythonw DASHBOARD/start_dashboard.py"
echo ""
echo "Dashboard accessible sur : http://212.28.179.199:8000"
echo ""
echo "IMPORTANT: Pour HTTPS, configurer Caddy :"
echo "  1. Telecharger Caddy sur le VPS"
echo "  2. Caddyfile : mia-ia-system.com { reverse_proxy localhost:8000 }"
echo "  3. Pointer le DNS mia-ia-system.com vers 212.28.179.199"
echo ""
