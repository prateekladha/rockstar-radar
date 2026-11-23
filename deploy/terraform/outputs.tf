output "cluster_id" { value = oci_containerengine_cluster.main.id }
output "namespace" { value = data.oci_objectstorage_namespace.ns.namespace }
output "ocir_registry" { value = "${var.region}.ocir.io/${data.oci_objectstorage_namespace.ns.namespace}/${var.name}" }
output "vault_id" { value = oci_kms_vault.main.id }
output "key_id" { value = oci_kms_key.main.id }
output "adb_id" { value = oci_database_autonomous_database.main.id }
output "compartment_id" { value = var.compartment_ocid }

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
