#!/usr/bin/env bash
# Run ON the OCI VM (Ubuntu ARM/x86). Installs Docker, opens the host firewall,
# and brings up Caddy + the app with auto-HTTPS. Idempotent — safe to re-run.
set -euo pipefail

: "${PUBLIC_HOST:?Set PUBLIC_HOST, e.g. PUBLIC_HOST=129-153-1-2.sslip.io bash bootstrap.sh}"
APP_DIR="${APP_DIR:-$HOME/rockstar_radar}"

echo "▶ PUBLIC_HOST=$PUBLIC_HOST  APP_DIR=$APP_DIR"

# 1. Docker (+ compose plugin) via the official convenience script.
if ! command -v docker >/dev/null 2>&1; then
  echo "▶ Installing Docker …"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
fi

# 2. Open the VM's OS firewall for HTTP/HTTPS. OCI Ubuntu images block these by default
#    in iptables — this is IN ADDITION to the OCI Security List / NSG rule in the console.
echo "▶ Opening ports 80/443 in the host firewall …"
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT || true
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT || true
if command -v netfilter-persistent >/dev/null 2>&1; then
  sudo netfilter-persistent save || true
else
  sudo apt-get update -y && sudo apt-get install -y iptables-persistent || true
fi

# 3. Bring the stack up (build the app image, start Caddy + app).
cd "$APP_DIR/deploy/oci"
echo "▶ Building & starting containers …"
sudo PUBLIC_HOST="$PUBLIC_HOST" docker compose up -d --build

echo ""
echo "✅ Deployed. Give Caddy ~30s to obtain a certificate, then open:"
echo "   https://radar.$PUBLIC_HOST"
echo ""
echo "Logs:  sudo docker compose -f $APP_DIR/deploy/oci/docker-compose.yml logs -f"
