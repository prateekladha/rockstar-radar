#!/usr/bin/env bash
# Stores the EXISTING app secrets in OCI Vault WITHOUT echoing them or writing them to disk/state.
#   ./deploy/scripts/put-secrets.sh            (prompts for each value, input hidden)
# These MUST carry over from the current VM deployment unchanged — in particular the Fernet/encryption
# key, which decrypts every stored FYERS token in broker_connections (a new key = everyone re-logs in).
# Re-running creates a new secret version (rotation); pods pick it up via External Secrets.
set -euo pipefail
export SUPPRESS_LABEL_WARNING=True
cd "$(dirname "$0")/../terraform"
NAME="${NAME:-rockstar-radar}"
CPT=$(terraform output -raw compartment_id)
VAULT=$(terraform output -raw vault_id)
KEY=$(terraform output -raw key_id)

put() {
  local name="$NAME-$1" prompt="$2" value
  read -r -s -p "$prompt (leave empty to skip): " value; echo
  [[ -z "$value" ]] && { echo "  skipped $name"; return; }
  local b64; b64=$(printf '%s' "$value" | base64)
  local id; id=$(oci vault secret list --compartment-id "$CPT" --vault-id "$VAULT" --name "$name" \
                 --lifecycle-state ACTIVE --query 'data[0].id' --raw-output 2>/dev/null || true)
  if [[ -n "$id" && "$id" != "null" ]]; then
    oci vault secret update-base64 --secret-id "$id" --secret-content-content "$b64" >/dev/null
    echo "  updated $name (new version)"
  else
    oci vault secret create-base64 --compartment-id "$CPT" --vault-id "$VAULT" --key-id "$KEY" \
        --secret-name "$name" --secret-content-content "$b64" >/dev/null
    echo "  created $name"
  fi
  unset value b64
}

# Carry these over from the current deployment's RAM secrets (see deploy/oci): the SAME values.
put encryption-key        "App encryption/Fernet key (decrypts stored FYERS tokens — MUST match current)"
put google-client-id      "Google OAuth client id"
put google-client-secret  "Google OAuth client secret"
echo "done - secrets sync into the cluster within ~1 minute (via External Secrets)"
