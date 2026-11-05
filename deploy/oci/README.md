# Deploy to OCI (Oracle Cloud — Always Free, secrets in OCI Vault)

Runs free on one Always-Free **Ampere A1** VM: Docker running the app + Postgres + Caddy (HTTPS).
**Secrets live in OCI Vault**, not on the VM — a one-shot `secrets-init` container reads them via the
VM's own identity (instance principal) into a **RAM-only (tmpfs)** volume on each boot. The `.env` on
the VM holds only your domain + Vault OCIDs (no secret values).

## 1. Create the VM (OCI Console — one time)
Compute → Instances → Create: **Ubuntu 22.04**, shape **VM.Standard.A1.Flex** (4 OCPU / 24 GB),
assign a public IP, paste your `~/.ssh/id_rsa.pub`. Note the **public IP** and the VM's **OCID**.

## 2. Open ports 80 & 443 (Subnet → Default Security List → Ingress)
Add `0.0.0.0/0` TCP **80** and **443**. (22 is already open.)

## 3. Point your domain (DNS)
At your registrar add A records: `@` → VM IP, `www` → VM IP.

## 4. Create the Vault + secrets (OCI Console)
1. **Identity & Security → Vault → Create Vault** (and a **Master Encryption Key** inside it).
2. In the Vault, **Create Secret** for each of these (pick "Plain-text" content):
   - `SESSION_SECRET` → `openssl rand -hex 32`
   - `ENCRYPTION_KEY` → `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   - `POSTGRES_PASSWORD` → any strong password
   - `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` → from your Google OAuth client
   - (optional) `SUPPORT_TELEGRAM_BOT_TOKEN`, `SUPPORT_TELEGRAM_CHAT_ID`
   Copy each secret's **OCID**.
3. **Dynamic Group** (Identity → Domains → Dynamic Groups): create one matching the VM, e.g.
   `ALL {instance.id = '<your-VM-OCID>'}`.
4. **Policy** (Identity → Policies) in the compartment holding the Vault:
   ```
   Allow dynamic-group <your-dg-name> to read secret-bundles in compartment <compartment-name>
   ```

## 5. Deploy (on the VM — you run this; no access shared with anyone)
```bash
git clone https://github.com/prateekladha/rockstar-radar.git ~/rockstar_radar
cd ~/rockstar_radar/deploy/oci
cp .env.example .env && nano .env     # set DOMAIN, OCI_REGION, and the SECRET_OCID_* values
bash bootstrap.sh
```
`secrets-init` pulls the Vault secrets into RAM, Postgres starts with the Vault password, the app
loads its secrets from RAM, and Caddy gets a cert. Open **https://<your-domain>** (~30s on first run).

## 6. Google OAuth
In your OAuth client add the authorized redirect URI `https://<your-domain>/auth/google/callback`
(and register `https://<your-domain>/api/brokers/callback` as the FYERS app redirect).

## Updating
```bash
cd ~/rockstar_radar && git pull && cd deploy/oci && sudo docker compose up -d --build
```
Postgres data + encrypted broker tokens persist (named volumes). Secrets re-fetch from Vault on boot.

## Why this is safe
- Secret **values** never touch the VM disk or git — only Vault, fetched into tmpfs (RAM) at boot.
- The VM authenticates to Vault as itself (instance principal) — no keys stored anywhere.
- Broker tokens in Postgres are additionally Fernet-encrypted with the Vault `ENCRYPTION_KEY`.
