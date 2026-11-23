# P6 — Cutover runbook (VM → OKE + Oracle ADB)

The ordered, reversible steps to take Rockstar Radar live on OKE. The VM stays running the whole time;
rollback is a DNS revert. Do the cutover on a **market-closed** day/window.

## ⚠️ Blocker to resolve BEFORE cutover: FYERS egress IP
The scanner's FYERS REST + WebSocket traffic currently egresses from the VM's public IP
**130.210.19.216**, which is whitelisted in your FYERS app. On OKE the scanner pod egresses through the
**NAT gateway's** public IP, which is different. So:
1. Reserve a **static public IP** in OCI and attach it to the NAT gateway (`oci_core_nat_gateway` takes
   `public_ip_id`) so the egress IP is stable.
2. **Whitelist that NAT IP in the FYERS app** (in addition to, or replacing, the VM IP) before the
   scanner pod makes any live call. Until this is done, FYERS calls from the cluster will be rejected.

(The memory rule "never change 130.210.19.216" is about the VM; the cutover deliberately adds the new
egress IP. Keep the VM IP whitelisted until decommission so rollback still works.)

## Prerequisites (P1–P5 applied)
- `deploy/scripts/bootstrap.sh` + `terraform apply` done (cluster, ADB, Vault, OCIR, IAM).
- `cluster-addons.sh` done (External Secrets, cert-manager, Traefik, metrics-server). Note the LB IP.
- `put-secrets.sh` done — **the `encryption-key` value is byte-for-byte the current one** (else every
  stored FYERS token fails to decrypt and all users must re-login).
- `gh-secrets.sh` done; repo variables `DOMAIN` and `LETSENCRYPT_EMAIL` set.
- NAT egress IP whitelisted in FYERS (above).

## Step 1 — First deploy on a test domain
- Set repo var `DOMAIN=<lb-ip>.sslip.io`.
- Run the **Deploy to OKE** workflow with `deploy_scanner=true` (first install).
- Check: `https://<lb-ip>.sslip.io/healthz` is 200, the SPA loads, Google login works. The app is on
  **ADB** and empty at this point.

## Step 2 — Migrate the data (market closed)
From a machine (or a one-off Job) that can reach both the VM Postgres and ADB:
```bash
export SOURCE_DATABASE_URL='postgresql+psycopg://radar:<pw>@<vm-ip>:5432/radar'
export DB_DSN='<ADB TLS DSN>'  DB_USER=ROCKSTAR_APP  DB_APP_PASSWORD='<vault db-app-password>'
export DB_ADMIN_PASSWORD='<vault db-admin-password>'
python deploy/scripts/migrate_db.py --bootstrap-user   # create the app user + grants
python deploy/scripts/migrate_db.py                    # create_all + copy all rows
```
Verify row counts per table against the VM (`users`, `broker_connections`, `orders`, `settings`, …).

## Step 3 — Validate end to end on the test domain
Log in as yourself, confirm your broker connection decrypts (token works → encryption key carried over
correctly), the radar/SMC screens load, and a paper order round-trips. Since it's market-closed the
feed shows the "market closed" state — that's expected.

## Step 4 — Cut DNS over
- Point `intraday.live` A record at the **OKE LB IP**.
- Set repo var `DOMAIN=intraday.live`; re-run **Deploy to OKE** (web-only — `deploy_scanner=false`) so
  cert-manager issues the `intraday.live` certificate and the ingress host updates. The scanner pod is
  **not** restarted.
- Watch `https://intraday.live/healthz`, login, and (next market open) the live feed + a real paper
  trade. The VM is still up as instant rollback.

## Step 5 — Settle, then decommission
- Keep the VM running (and its FYERS IP whitelisted) for ~a week as rollback.
- When confident: stop/terminate the VM; switch the node pool back to Always-Free A1
  (`terraform apply -var node_shape=VM.Standard.A1.Flex -var node_ocpus=4 -var node_memory_gb=24`);
  retire `deploy.yml` (the VM deploy) and add `push: branches:[main]` to `deploy-oke.yml` so merges
  auto-deploy the web (scanner stays pinned unless `deploy_scanner=true`). Remove the VM's FYERS IP
  from the whitelist once rollback is no longer needed.

## Rollback (any time before Step 5)
Revert the `intraday.live` A record to **130.210.19.216**. The VM + Postgres are untouched and serve
immediately. Investigate, then retry the cutover.

## Result: your original goal
After cutover, a code change to the web is `git merge → Deploy to OKE` → a rolling update of the **web
Deployment only**. The **scanner pod keeps running** — same FYERS feed, same day-state, **zero REST
calls** — so you can deploy anytime during market hours without touching the scanner.
