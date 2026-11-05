# Deploy to OCI (Oracle Cloud — Always Free)

Runs the whole stack free on one Always-Free **Ampere A1** VM: Docker running **Postgres** +
the **Rockstar Radar** app + a **Caddy** reverse proxy with automatic HTTPS. No domain required —
HTTPS works via `sslip.io` wildcard DNS off the VM's public IP.

## 1. Create the VM (OCI Console — one time, ~5 min)
1. Sign in at <https://cloud.oracle.com>. Menu → **Compute → Instances → Create instance**.
2. **Image & shape:** Image **Canonical Ubuntu 22.04**; Shape → **Ampere** → `VM.Standard.A1.Flex`,
   set **4 OCPU / 24 GB** (the full Always-Free allowance).
3. **Networking:** let it **create a new VCN** (public subnet + internet gateway).
   Ensure **"Assign a public IPv4 address" = Yes**.
4. **SSH keys:** choose **Paste public keys** and paste the contents of `~/.ssh/id_rsa.pub`.
5. **Create.** When it's running, copy the **Public IP address**.

## 2. Open ports 80 & 443 (OCI Security List — one time)
Instance → its **Subnet** → **Default Security List** → **Add Ingress Rules**:
- Source `0.0.0.0/0`, IP Protocol **TCP**, Destination port **80**
- Source `0.0.0.0/0`, IP Protocol **TCP**, Destination port **443**

(Port 22 is already open.) `bootstrap.sh` also opens the VM's own iptables for 80/443.

## 3. Deploy
Your HTTPS hostname is derived from the IP: replace dots with dashes + `.sslip.io`
(e.g. IP `129.153.1.2` → `PUBLIC_HOST=129-153-1-2.sslip.io`).

```bash
# On the VM:
git clone https://github.com/prateekladha/rockstar-radar.git ~/rockstar_radar
cd ~/rockstar_radar/deploy/oci
cp .env.example .env            # then fill in secrets (see below)
nano .env
PUBLIC_HOST=129-153-1-2.sslip.io bash bootstrap.sh
```

Fill `.env` with: `PUBLIC_HOST`, a strong `POSTGRES_PASSWORD`, a `SESSION_SECRET`
(`openssl rand -hex 32`), an `ENCRYPTION_KEY`
(`python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`),
and your `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.

Open **https://radar.<dashed-ip>.sslip.io** (give Caddy ~30s for the TLS cert on first run).

## Google OAuth
Create a Google OAuth **Web** client and set the authorized redirect URI to
`https://radar.<dashed-ip>.sslip.io/auth/google/callback`.

## Updating
```bash
cd ~/rockstar_radar && git pull
cd deploy/oci && sudo PUBLIC_HOST=<dashed-ip>.sslip.io docker compose up -d --build
```
Postgres data and encrypted broker tokens persist across rebuilds (named Docker volumes).

## Notes
- Secrets live only in `deploy/oci/.env` on the VM (git-ignored, `chmod 600`) — never in the image.
- Each user connects **their own** broker account; SEBI requires a fresh broker login each trading day.
