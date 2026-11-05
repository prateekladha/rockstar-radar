"""One-shot secrets bootstrap for OCI.

Reads each secret from OCI Vault using the VM's instance principal (no stored credentials) and
writes them to a tmpfs (RAM-only) directory so neither the app nor Postgres ever keeps a secret on
disk. Re-runs on every boot.

Config (all NON-secret — safe to keep in deploy/oci/.env):
  OCI_REGION                  e.g. ap-mumbai-1   (optional; instance principal usually infers it)
  SECRET_OCID_<NAME>=<ocid>   one per secret, e.g.
      SECRET_OCID_SESSION_SECRET=ocid1.vaultsecret.oc1...
      SECRET_OCID_ENCRYPTION_KEY=ocid1.vaultsecret.oc1...
      SECRET_OCID_GOOGLE_CLIENT_ID=ocid1.vaultsecret.oc1...
      SECRET_OCID_GOOGLE_CLIENT_SECRET=ocid1.vaultsecret.oc1...
      SECRET_OCID_POSTGRES_PASSWORD=ocid1.vaultsecret.oc1...

Writes to $SECRETS_DIR (default /secrets, a tmpfs mount):
  app.env         -> `export NAME='value'` lines (sourced by the app entrypoint)
  db_password     -> the Postgres password only (for POSTGRES_PASSWORD_FILE)
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
    client = oci.secrets.SecretsClient(cfg, signer=signer)
    out = {}
    for key, ocid in os.environ.items():
        if not key.startswith('SECRET_OCID_') or not ocid.strip():
            continue
        name = key[len('SECRET_OCID_'):]
        content = client.get_secret_bundle(ocid.strip()).data.secret_bundle_content.content
        out[name] = base64.b64decode(content).decode('utf-8')
    return out


def main() -> int:
    os.makedirs(SECRETS_DIR, exist_ok=True)
    try:
        secrets = _fetch_all()
    except Exception as e:  # fail loudly — the stack must not start with missing secrets
        print(f'[secrets-init] FAILED to read OCI Vault: {type(e).__name__}: {e}', file=sys.stderr)
        return 1
    if not secrets:
        print('[secrets-init] no SECRET_OCID_* configured — nothing to fetch', file=sys.stderr)
        return 1
    lines = []
    for name, val in secrets.items():
        esc = val.replace("'", "'\"'\"'")   # safe single-quote escaping for shell sourcing
        lines.append(f"export {name}='{esc}'")
    with open(os.path.join(SECRETS_DIR, 'app.env'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    if 'POSTGRES_PASSWORD' in secrets:
        with open(os.path.join(SECRETS_DIR, 'db_password'), 'w', encoding='utf-8') as f:
            f.write(secrets['POSTGRES_PASSWORD'])
    print(f'[secrets-init] wrote {len(secrets)} secret(s) to {SECRETS_DIR} (tmpfs)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
