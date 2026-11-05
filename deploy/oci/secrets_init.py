"""One-shot secrets bootstrap for OCI.

Lists every secret in the configured OCI Vault and fetches it using the VM's instance principal
(no stored credentials), writing them to a tmpfs (RAM-only) directory so neither the app nor
Postgres keeps a secret on disk. Because it lists the whole Vault, secrets you add later (e.g. the
Google ones) are picked up on the next run (a reboot / `compose up`) with NO config change.

Config (all NON-secret — safe to keep in deploy/oci/.env):
  OCI_REGION                   e.g. ap-mumbai-1   (optional; instance principal usually infers it)
  SECRETS_COMPARTMENT_OCID     compartment holding the Vault
  SECRETS_VAULT_OCID           the Vault OCID

Writes to $SECRETS_DIR (default /secrets, a tmpfs mount):
  app.env       -> `export NAME='value'` lines (sourced by the app entrypoint)
  db_password   -> the Postgres password only (for POSTGRES_PASSWORD_FILE)

Each Vault secret's NAME becomes the env var name (e.g. a secret named SESSION_SECRET -> $SESSION_SECRET).
"""
from __future__ import annotations
import base64
import os
import sys

SECRETS_DIR = os.environ.get('SECRETS_DIR', '/secrets')


def _fetch_all():
    import oci
    signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    cfg = {'region': os.environ['OCI_REGION']} if os.environ.get('OCI_REGION') else {}
    vaults = oci.vault.VaultsClient(cfg, signer=signer)
    secrets = oci.secrets.SecretsClient(cfg, signer=signer)
    comp = os.environ['SECRETS_COMPARTMENT_OCID']
    vault_id = os.environ['SECRETS_VAULT_OCID']
    listed = oci.pagination.list_call_get_all_results(
        vaults.list_secrets, comp, vault_id=vault_id).data
    out = {}
    for s in listed:
        if getattr(s, 'lifecycle_state', None) != 'ACTIVE':
            continue
        content = secrets.get_secret_bundle(s.id).data.secret_bundle_content.content
        out[s.secret_name] = base64.b64decode(content).decode('utf-8')
    return out


def main() -> int:
    os.makedirs(SECRETS_DIR, exist_ok=True)
    try:
        found = _fetch_all()
    except Exception as e:  # fail loudly — the stack must not start with missing secrets
        print(f'[secrets-init] FAILED to read OCI Vault: {type(e).__name__}: {e}', file=sys.stderr)
        return 1
    if not found:
        print('[secrets-init] no ACTIVE secrets found in the Vault', file=sys.stderr)
        return 1
    lines = []
    for name, val in found.items():
        esc = val.replace("'", "'\"'\"'")   # safe single-quote escaping for shell sourcing
        lines.append(f"export {name}='{esc}'")
    with open(os.path.join(SECRETS_DIR, 'app.env'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    if 'POSTGRES_PASSWORD' in found:
        with open(os.path.join(SECRETS_DIR, 'db_password'), 'w', encoding='utf-8') as f:
            f.write(found['POSTGRES_PASSWORD'])
    print(f'[secrets-init] loaded {len(found)} secret(s) from Vault into {SECRETS_DIR} (tmpfs): '
          + ', '.join(sorted(found)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
