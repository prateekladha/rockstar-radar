# Deploy to OCI (Oracle Cloud — Always Free)

Runs the whole stack free on one Always-Free **Ampere A1** VM: Docker running **Postgres** +
the **Rockstar Radar** app + a **Caddy** reverse proxy with automatic HTTPS for your domain.

## 1. Create the VM (OCI Console — one time, ~5 min)
1. Sign in at <https://cloud.oracle.com>. Menu → **Compute → Instances → Create instance**.
2. **Image & shape:** Image **Canonical Ubuntu 22.04**; Shape → **Ampere** → `VM.Standard.A1.Flex`,
   set **4 OCPU / 24 GB** (the full Always-Free allowance).
3. **Networking:** let it **create a new VCN**; ensure **"Assign a public IPv4 address" = Yes**.
4. **SSH keys:** choose **Paste public keys** and paste the contents of `~/.ssh/id_rsa.pub`.
5. **Create.** When it's running, copy the **Public IP address**.

## 2. Open ports 80 & 443 (OCI Security List — one time)
Instance → its **Subnet** → **Default Security List** → **Add Ingress Rules**:
- Source `0.0.0.0/0`, TCP, port **80**
- Source `0.0.0.0/0`, TCP, port **443**

(Port 22 is already open.) `bootstrap.sh` also opens the VM's iptables for 80/443.

## 3. Point your domain at the VM (DNS)
At your registrar (e.g. Namecheap → Domain → **Advanced DNS**), add **A records** to the VM's public IP:
- Host `@`   → `<VM public IP>`  (the apex, e.g. `intraday.live`)
- Host `www` → `<VM public IP>`

DNS can take a few minutes to propagate. Caddy issues the TLS cert automatically once it resolves.

## 4. Deploy
```bash
# On the VM:
git clone https://github.com/prateekladha/rockstar-radar.git ~/rockstar_radar
cd ~/rockstar_radar/deploy/oci
cp .env.example .env && nano .env     # fill DOMAIN + secrets (below)
bash bootstrap.sh
```

Fill `.env`: `DOMAIN` (e.g. `intraday.live`), a strong `POSTGRES_PASSWORD`, `SESSION_SECRET`
(`openssl rand -hex 32`), `ENCRYPTION_KEY`
(`python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`),
and `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`. Optional: `VITE_POSTHOG_KEY`,
`SUPPORT_TELEGRAM_BOT_TOKEN` / `SUPPORT_TELEGRAM_CHAT_ID`.

Open **https://<your-domain>** (give Caddy ~30s for the cert on first run).

## Google OAuth
Create a Google OAuth **Web** client and set the authorized redirect URI to
`https://<your-domain>/auth/google/callback`. Also register the same base as the FYERS app
redirect: `https://<your-domain>/api/brokers/callback`.

## Updating
```bash
cd ~/rockstar_radar && git pull
cd deploy/oci && sudo docker compose up -d --build
```
Postgres data and encrypted broker tokens persist across rebuilds (named Docker volumes).

## Notes
- Secrets live only in `deploy/oci/.env` on the VM (git-ignored, `chmod 600`) — never in the image.
- Each user connects **their own** broker; SEBI requires a fresh broker login each trading day.
