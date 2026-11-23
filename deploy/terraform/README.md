# Rockstar Radar — OKE infrastructure (Terraform)

Phase **P1** of the [OKE migration](../../docs/K8S_MIGRATION.md). Provisions, on OCI Always-Free, in
a dedicated compartment, **alongside** the still-running `intraday.live` VM (nothing here touches it):

- VCN (public API + LB subnets, private worker subnet, NAT + service gateway)
- **OKE** Basic cluster (free control plane) + a worker node pool
- **OCI Vault** + key, with the platform secrets (DB passwords + DSN, session secret)
- **Oracle Autonomous Database** (Always-Free, 23ai) — the P4 target; nothing connects to it until then
- IAM: a CI user (OCIR push + cluster deploy), a worker-node dynamic group (image pull + secret read),
  and one private OCIR repo (`rockstar-radar/app`)

> Modeled on `dt-telekom`'s `deploy/terraform`, stripped of what Rockstar Radar doesn't use (Kafka
> streaming, Object Storage archive, LLM gateway).

## Prerequisites
OCI CLI configured (`~/.oci/config`, DEFAULT profile), `terraform >= 1.12`, `kubectl`, `helm`, `gh`.

## Run
```bash
# 1. Compartment + remote-state bucket; writes backend.hcl + terraform.tfvars
NAME=rockstar-radar REGION=ap-mumbai-1 deploy/scripts/bootstrap.sh

cd deploy/terraform
terraform init -backend-config=backend.hcl
terraform plan      # review
terraform apply

# 2. kubeconfig + platform add-ons (External Secrets, cert-manager, Traefik, metrics-server) + CI RBAC
../scripts/cluster-addons.sh        # prints the LB IP + an <ip>.sslip.io test domain

# 3. Carry the EXISTING app secrets into Vault (hidden input; encryption key MUST match current)
../scripts/put-secrets.sh

# 4. (for P5 CI/CD) push CI creds to GitHub
../scripts/gh-secrets.sh
```

## Capacity note (important during the migration)
Always-Free **A1** is 4 OCPU / 24 GB **per tenancy**, and the current VM already uses that allocation.
While both the VM and this cluster run (P3–P6), either shrink the VM or set the node pool to a small
paid AMD shape:
```bash
terraform apply -var 'node_shape=VM.Standard.E5.Flex' -var 'node_ocpus=1' -var 'node_memory_gb=16'
```
After the VM is decommissioned at the **P6 cutover**, switch the node pool back to `VM.Standard.A1.Flex`
to return to zero cost. `node_count=0` parks the cluster (control plane, Vault and ADB stay) at near-zero.

## State & secrets
State lives in the `rockstar-radar-tfstate` OCI bucket (versioned). `backend.hcl`, `terraform.tfvars`,
`.terraform/` and `*.tfstate` are git-ignored. Third-party/app secret **values** are never in state —
they are set by `put-secrets.sh` directly into Vault.
