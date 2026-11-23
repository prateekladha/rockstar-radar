# Platform migration: OCI VM + Compose → OKE + Oracle Autonomous DB

**Status:** design / proposed · **Author:** platform · **Date:** 2026-11-23

Modelled on the `dt-telekom` self-care platform (OKE + Terraform + Helm + External Secrets +
Traefik + Oracle Autonomous DB). This doc is the plan of record; we execute it in phases, each a
reviewable PR, with the current single-VM deployment left running until the final DNS cutover.

---

## 1. Why

1. **Deploy the web without restarting the scanner.** Today the whole stack is one container
   (`radar`) started by `systemctl restart rockstar.service`; every deploy recreates it, which kills
   the per-user scanner subprocesses. On restart they re-establish the day's state from FYERS REST
   calls (OR anchors, cold caches) and can eat the 5,000/day quota. The web and the scanner have
   **different lifecycles** and must be deployed independently. (This is the dt-telekom principle:
   *"the hot path is a separate service because it scales differently."*)
2. **Standardise with the other projects** (dt-telekom) — same OKE + Helm + Terraform + Vault
   toolchain, so operating all of them is one skill set.
3. **Managed database.** Replace the self-managed Postgres container with **Oracle Autonomous
   Database (Always-Free)** — auto-patch, auto-backup, TLS, no `pgdata` volume to babysit on the VM.

Everything stays on the **OCI Always-Free** envelope: OKE **Basic** control plane is free, worker
nodes run on the existing **A1 (Ampere) Always-Free** compute (up to 4 OCPU / 24 GB), **ADB
Always-Free** (1 ECPU / 20 GB), **OCIR** registry is free.

---

## 2. Target architecture

```
                         Traefik Ingress (+ cert-manager TLS)        OCI Vault
                                     │                                   │  External Secrets Operator
                                     ▼                                   ▼  (instance principal)
  Browser ──https──▶  web Deployment (stateless, HPA) ──http──▶  scanner Deployment (stateful, 1 replica)
                          │ serves React SPA + API        svc     │ scheduler + per-user FYERS scanners
                          │ proxies radar/SMC state ───────────────┘ + order engine (paper)
                          └────────────────┬───────────────────────┐
                                           ▼                        ▼
                                 Oracle Autonomous DB         FYERS REST + WebSocket
                                 (OLTP, 23ai, wallet-less TLS, VCN-only)
```

| Workload | Kind | Replicas | Why |
|---|---|---|---|
| `web` | Deployment + Service + **HPA** + PDB | 1→N on CPU | Stateless: serves the SPA/API, proxies to `scanner`. Rolling-updates freely. |
| `scanner` | Deployment + Service | **1 (no HPA)** | **Stateful**: holds the live FYERS feed, per-user scanner subprocesses, day-state in memory and on its `data` volume. Deployed only when scanner code changes. |

Deploys are `helm upgrade`. A web image bump rolls **only** the `web` Deployment; the `scanner` pod
is untouched → **no feed restart, no FYERS calls**. This is the whole point.

### 2.1 The web ⇄ scanner boundary (replaces in-process `_cc_for`)
Today `server/scanners.py` spawns scanner subprocesses **inside the web process** and proxies to
`127.0.0.1:<port>`. We split that:

- **`scanner` pod** runs the app with `RADAR_SCHED=1`, `RADAR_ORDER_ENGINE=1` (these env gates
  already exist in `server/main.py` lifespan). It owns the scheduler, spawns/supervises the per-user
  scanner subprocesses (unchanged code), runs the order engine, and exposes **one HTTP facade** (its
  own `uvicorn`) that already knows every subprocess port in memory. It resolves per-user state
  internally — the web needs **no cross-pod port discovery**.
- **`web` pod** runs with `RADAR_SCHED=0`, `RADAR_ORDER_ENGINE=0`. `radar_state` / `smc_state` call
  `http://scanner:8080/internal/...` instead of local `_cc_for`. No scanner is ever spawned in the
  web pod.
- Health: add `/healthz` (liveness) and `/readyz` (readiness — web ready only when it can reach the
  `scanner` service; scanner ready when its feed/manager is up), matching dt-telekom's probe contract.

This is backward-compatible: with `SCANNER_HOST` unset and `RADAR_SCHED=1` (single pod / local dev /
the current VM), behaviour is identical — the HTTP boundary collapses to localhost.

### 2.2 Per-user scanners in one pod
The scanner stays a **single pod** running the manager that forks per-user subprocesses (today's
model), *not* one pod per user. One-pod-per-user would need a custom controller and is overkill at
this scale. The `scanner` Deployment uses `Recreate` (not rolling) so two managers never fight over
the same FYERS locks; its volume (`/app/data`) holds pidfiles/caches/selections as today.

---

## 3. Database: Postgres → Oracle Autonomous DB

dt-telekom's `core-api` is written with **portable SQLAlchemy Core types so the same schema runs on
Oracle ADB and on SQLite** (`oracle+oracledb://ADMIN:…@<tls-dsn>`; wallet-less TLS; VCN-whitelisted;
app connects as a least-privilege user). We adopt the same pattern. This is the largest work item and
is **mostly orthogonal to the K8s split**, so it is its own phase.

**Porting checklist (Rockstar Radar is Postgres + SQLAlchemy ORM today):**
- **Driver/dialect:** `oracle+oracledb`; connection via the ADB TLS DSN (no wallet), DSN + app
  user/password pulled from Vault. Keep `sqlite` for unit tests.
- **Types:** audit every `Column` — `JSON` → Oracle native JSON (23ai) or `CLOB` with a JSON check;
  `Boolean` → already `Integer` in several models (keep that convention everywhere); `Text`/`String`
  lengths; `DateTime` (store UTC, tz-naive) ; `Float`→`BINARY_DOUBLE`/`NUMBER`.
- **Identifiers:** Oracle ≤128 chars (23ai) — check table/column names; avoid reserved words
  (`number`, `date`, `comment`, `level`, …). `smc_opportunities`/`broker_connections` etc. are fine;
  grep for risky column names.
- **Keys:** `Integer primary_key` → Oracle `GENERATED … AS IDENTITY` (SQLAlchemy handles via dialect).
- **Additive migrations:** `server/db.py` `_ADDED_COLUMNS` currently emits Postgres `ALTER TABLE …
  ADD COLUMN`. Rewrite the dialect-specific DDL for Oracle (idempotent: catch ORA-01430 "column
  already exists", or check `USER_TAB_COLUMNS` first). This is the only bespoke migration code.
- **JSON access:** anywhere we filter/read JSON in SQL (vs in Python) must use portable access or move
  the filter to Python. Most JSON here (`Order.features`, `Settings.data`) is read whole in Python —
  low risk.
- **Connection pool:** `pool_size=5, max_overflow=5, pool_recycle=1800` (dt-telekom's ADB values).
- **Data migration:** export current Postgres → load into ADB (small dataset: users, connections,
  orders, settings, signal logs). One-off script, validated row-counts, run during cutover.

**Risk:** this is a real Postgres→Oracle port. It is gated behind its own phase and its own test pass
(run the full suite on SQLite + an ADB smoke) before cutover.

---

## 4. Secrets, ingress, images
- **Secrets:** OCI Vault (already in use) → **External Secrets Operator** syncs a `rockstar-secrets`
  K8s Secret (FYERS app/secret, Google OAuth, session secret, ADB app password). Pods use **instance
  principal** auth; secret *values* never land in git or a plain env file (same as today's tmpfs).
- **Ingress/TLS:** **Traefik + cert-manager** (replaces Caddy). Same `intraday.live` domain; cutover
  is a DNS A-record change to the OKE load balancer.
- **Registry:** build images in CI, push to **OCIR** (`<region>.ocir.io/<namespace>/rockstar-radar`),
  tag = git SHA. One image, two workloads (same image, different `command`/env).

---

## 5. CI/CD (reuse dt-telekom's shape)
- **`pr-validation`** (on PR): ruff lint, pytest, web build, **`helm lint` + `kubeconform`**,
  **`terraform validate`**, image build, `gitleaks`. Replaces today's build-only CI.
- **`deploy-prod`** (on merge to main): build+push images (SHA tag) → `helm upgrade --install` →
  in-cluster smoke (`/healthz` on both workloads) → Playwright e2e against the live site. A web-only
  change rolls only the `web` Deployment; Helm leaves `scanner` untouched unless its values changed.
- Branch protection stays (1 approval; the user merges). The self-hosted VM runner is retired once
  OKE is live (CI runs on GitHub-hosted runners + an OCI OIDC/instance-principal deploy identity).

---

## 6. Terraform (reuse dt-telekom modules)
`deploy/terraform/`: `oke.tf` (Basic cluster + A1 node pool), `network.tf` (VCN, subnets, service
gateway so ADB/OCIR traffic stays private), `vault.tf` (Vault + secrets), `data.tf` (ADB Always-Free,
wallet-less TLS, VCN-whitelisted), `iam.tf` (dynamic groups + policies for instance principal),
`outputs.tf`. Bootstrap + addon scripts (`cluster-addons.sh`: External Secrets, cert-manager,
Traefik, metrics-server) lifted from dt-telekom and renamed.

---

## 7. Phased execution (each phase = one PR, VM stays live throughout)
- **P0 — this doc.**
- **P1 — Terraform:** OKE + VCN + Vault + ADB + OCIR + IAM, `terraform validate` green. No app change.
  Stand the cluster up *alongside* the running VM.
- **P2 — web/scanner split (code):** the HTTP boundary (§2.1), `/healthz` + `/readyz`, env gating,
  backward-compatible (single-container still works). Unit tests for the proxy/boundary. Ship to the
  **VM first** (still one container) to de-risk the code split before K8s.
- **P3 — Helm chart:** `web` + `scanner` workloads, Service/HPA/PDB/probes, External Secrets, Traefik
  ingress; `helm lint` + `kubeconform` green. Deploy to OKE in parallel (test domain / sslip.io),
  **still pointing at the existing Postgres** (via service gateway) so DB isn't a variable yet.
- **P4 — Oracle ADB port (§3):** dialect + types + migration DDL + data-load script; full test suite
  on SQLite + an ADB smoke. Point the OKE deployment at ADB. Validate end-to-end on the test domain.
- **P5 — CI/CD:** `pr-validation` + `deploy-prod` (helm upgrade) workflows; retire the VM runner.
- **P6 — Cutover:** final data sync Postgres→ADB, flip `intraday.live` DNS to the OKE LB, watch, keep
  the VM as instant rollback for a week, then decommission. **Full runbook: [K8S_CUTOVER.md](K8S_CUTOVER.md).**

> **Build status (2026-11-23):** P1–P6 are code-complete on branch `feat/oke-migration` (PR #53),
> carrying the earlier app fixes too. Validated locally with `terraform validate`, `helm lint` +
> `kubeconform`, and `py_compile`; the split is backward-compatible (the VM keeps working unchanged).
> End-to-end on real OKE + ADB is exercised when the user applies P1 and runs the cutover — nothing has
> been applied to prod.

**Rollback at every phase:** the VM + Compose + Postgres stay fully operational until P6; cutover is a
DNS change, reversible in minutes.

---

## 8. Open questions (resolve before the relevant phase)
- **ADB JSON:** use 23ai native JSON columns or portable CLOB+check? (Affects §3 type audit.)
- **Scanner HA:** single replica is a deliberate SPOF for the stateful feed; acceptable (same as the
  VM today). A warm-standby is a later option, not in scope.
- **Per-user FYERS quota in one scanner pod:** unchanged from today (each user's subprocess has its
  own lock + quota); the pod just co-locates them.
- **A1 capacity:** OKE node pool + ADB + Traefik must fit the 4 OCPU/24 GB Always-Free A1 envelope;
  size node pool to leave headroom for the scanner's per-user subprocesses.
