#!/usr/bin/env bash
# Manual redeploy — run ON the VM when you want to ship the latest code.
# Pulls main, rebuilds the images, and restarts the stack (secrets re-fetched from Vault on start).
# No auto-pull, no schedule — this only runs when you run it.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/rockstar_radar}"
cd "$APP_DIR"

echo "▶ Pulling latest main …"
sudo git pull --ff-only

echo "▶ Rebuilding + restarting (secrets-init re-reads the Vault) …"
sudo systemctl restart rockstar.service

echo "▶ Status:"
sleep 6
sudo docker compose -f "$APP_DIR/deploy/oci/docker-compose.yml" ps
echo ""
echo "✅ Redeployed. Check https://intraday.live"
