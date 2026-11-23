# Vault with a software-protected key (no charge). Terraform generates platform-internal secrets
# (DB passwords + DSN, session secret). The EXISTING app secrets that must carry over unchanged —
# the Fernet/encryption key for broker token_enc (rotating it would break every stored FYERS token),
# Google OAuth client id/secret — are loaded by scripts/put-secrets.sh so their values never touch
# Terraform state.
resource "oci_kms_vault" "main" {
  compartment_id = var.compartment_ocid
  display_name   = "${var.name}-vault"
  vault_type     = "DEFAULT"
}

resource "oci_kms_key" "main" {
  compartment_id      = var.compartment_ocid
  display_name        = "${var.name}-key"
  management_endpoint = oci_kms_vault.main.management_endpoint
  protection_mode     = "SOFTWARE"
  key_shape {
    algorithm = "AES"
    length    = 32
  }
}

resource "random_password" "session_secret" {
  length  = 48
  special = false
}

locals {
  secrets = {
    "db-admin-password" = random_password.db_admin.result
    "db-app-password"   = random_password.db_app.result
    "db-dsn"            = local.adb_tls_low
    "session-secret"    = random_password.session_secret.result
  }
}

resource "oci_vault_secret" "platform" {
  for_each       = local.secrets
  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.main.id
  key_id         = oci_kms_key.main.id
  secret_name    = "${var.name}-${each.key}"
  secret_content {
    content_type = "BASE64"
    content      = base64encode(each.value)
  }
}
