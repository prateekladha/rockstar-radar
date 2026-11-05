#!/usr/bin/env bash
# Run ON the OCI VM (Ubuntu). Installs Docker, opens the host firewall, and brings up
# Postgres + app + Caddy (auto-HTTPS). Idempotent — safe to re-run. Reads deploy/oci/.env.
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/rockstar_radar}"
cd "$APP_DIR/deploy/oci"

if [ ! -f .env ]; then
  echo "✗ deploy/oci/.env not found. Copy .env.example to .env and fill it in first." >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; . ./.env; set +a
: "${DOMAIN:?Set DOMAIN in .env, e.g. DOMAIN=intraday.live}"

echo "▶ DOMAIN=$DOMAIN  APP_DIR=$APP_DIR"

# 1. Docker (+ compose plugin).
if ! command -v docker >/dev/null 2>&1; then
  echo "▶ Installing Docker …"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
fi

# 2. Open the VM's OS firewall for HTTP/HTTPS (in addition to the OCI Security List rule).
echo "▶ Opening ports 80/443 in the host firewall …"
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT || true
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT || true
if command -v netfilter-persistent >/dev/null 2>&1; then
  sudo netfilter-persistent save || true
else
  sudo apt-get update -y && sudo apt-get install -y iptables-persistent || true
fi

# 3. Build + start (compose reads ./.env automatically).
echo "▶ Building & starting containers …"
sudo docker compose up -d --build

echo ""
echo "✅ Deployed. Point ${DOMAIN} DNS at this VM's IP (if not already), give Caddy ~30s for the"
echo "   TLS cert, then open:  https://${DOMAIN}"
echo "Logs:  sudo docker compose -f $APP_DIR/deploy/oci/docker-compose.yml logs -f"
