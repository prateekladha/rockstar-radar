output "namespace" { value = data.oci_objectstorage_namespace.ns.namespace }
output "ocir_registry" { value = "${var.region}.ocir.io/${data.oci_objectstorage_namespace.ns.namespace}/${var.name}" }
output "vault_id" { value = oci_kms_vault.main.id }
output "key_id" { value = oci_kms_key.main.id }
output "compartment_id" { value = var.compartment_ocid }

# Shared infra Rockstar attaches to (reused, not created by this stack)
output "shared_adb_id" { value = local.shared_adb.id }

output "ocir_username_ci" { value = "${data.oci_objectstorage_namespace.ns.namespace}/${oci_identity_user.ci.name}" }
output "ci_user_ocid" { value = oci_identity_user.ci.id }
output "ci_fingerprint" { value = oci_identity_api_key.ci.fingerprint }
output "ci_private_key" {
  value     = tls_private_key.ci.private_key_pem
  sensitive = true
}
output "ci_auth_token" {
  value     = oci_identity_auth_token.ci.token
  sensitive = true
}
