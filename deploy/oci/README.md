# Deploy to OCI (Oracle Cloud — Always Free)

A reusable, free, multi-app host: one Always-Free **Ampere A1** VM running Docker + a
**Caddy** reverse proxy with automatic HTTPS. Rockstar Radar is the first app; future
products (AIDLC, finance agent) add a service to `docker-compose.yml` + a route in `Caddyfile`.
No domain required — HTTPS works via `sslip.io` wildcard DNS off the VM's public IP.

## 1. Create the VM (OCI Console — one time, ~5 min)
1. Sign in at <https://cloud.oracle.com>. Menu → **Compute → Instances → Create instance**.
2. **Image & shape:** Image **Canonical Ubuntu 22.04**; Shape → **Ampere** → `VM.Standard.A1.Flex`,
   set **2 OCPU / 12 GB** (well within the Always-Free 4 OCPU / 24 GB).
3. **Networking:** let it **create a new VCN** (this gives a public subnet + internet gateway).
   Ensure **"Assign a public IPv4 address" = Yes**.
4. **SSH keys:** choose **Paste public keys** and paste the contents of `~/.ssh/id_rsa.pub`.
5. **Create.** When it's running, copy the **Public IP address**.

## 2. Open ports 80 & 443 (OCI Security List — one time)
Instance → its **Subnet** → **Default Security List** → **Add Ingress Rules**:
- Source `0.0.0.0/0`, IP Protocol **TCP**, Destination port **80**
- Source `0.0.0.0/0`, IP Protocol **TCP**, Destination port **443**
(Port 22 is already open.) The `bootstrap.sh` script opens the VM's own iptables for 80/443 too.

## 3. Deploy
Your HTTPS hostname is derived from the IP: replace dots with dashes + `.sslip.io`
(e.g. IP `129.153.1.2` → `PUBLIC_HOST=129-153-1-2.sslip.io`).

**Either** tell Claude the public IP and it will copy the project up and run the deploy for you,
**or** do it manually:

```bash
# from your Mac, in the project root:
IP=129.153.1.2                     # your VM public IP
scp -r . ubuntu@$IP:~/rockstar_radar
ssh ubuntu@$IP "PUBLIC_HOST=${IP//./-}.sslip.io bash ~/rockstar_radar/deploy/oci/bootstrap.sh"
```

Open **https://radar.<dashed-ip>.sslip.io** (give Caddy ~30s for the TLS cert on first run).

## Adding another app later
1. Add its image/Dockerfile as a new service in `docker-compose.yml` (expose 8080).
2. Add `aidlc.{$PUBLIC_HOST} { reverse_proxy aidlc:8080 }` to `Caddyfile`.
3. `sudo PUBLIC_HOST=... docker compose up -d --build`. Caddy auto-issues its cert.

## Going live (real FYERS data) later
Flip `RADAR_DEMO` off and provide credentials via a server-side `.env` (never commit it).
For a public multi-user product, each user connects their own FYERS app — see the product roadmap.
