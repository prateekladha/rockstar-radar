locals {
  cpt = "compartment id ${var.compartment_ocid}"
}

# ---- CI identity (GitHub Actions): push images to OCIR, deploy to the cluster ----
resource "tls_private_key" "ci" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "oci_identity_user" "ci" {
  compartment_id = var.tenancy_ocid
  name           = "${var.name}-ci"
  description    = "GitHub Actions deployer for ${var.name}"
  email          = "${var.name}-ci@example.invalid"
}

resource "oci_identity_group" "ci" {
  compartment_id = var.tenancy_ocid
  name           = "${var.name}-ci"
  description    = "CI deployers for ${var.name}"
}

resource "oci_identity_user_group_membership" "ci" {
  user_id  = oci_identity_user.ci.id
  group_id = oci_identity_group.ci.id
}

resource "oci_identity_api_key" "ci" {
  user_id   = oci_identity_user.ci.id
  key_value = tls_private_key.ci.public_key_pem
}

resource "oci_identity_auth_token" "ci" {
  user_id     = oci_identity_user.ci.id
  description = "ocir push"
}

# ---- Worker nodes (instance principal): pull images, read secrets (for External Secrets) ----
resource "oci_identity_dynamic_group" "nodes" {
  compartment_id = var.tenancy_ocid
  name           = "${var.name}-nodes"
  description    = "OKE worker nodes of ${var.name}"
  matching_rule  = "ALL {instance.compartment.id = '${var.compartment_ocid}'}"
}

resource "oci_identity_policy" "workloads" {
  compartment_id = var.compartment_ocid
  name           = "${var.name}-workloads"
  description    = "Least-privilege access for ${var.name} workloads and CI"
  statements = [
    # worker nodes: pull private images, read Vault secrets via instance principal (External Secrets)
    "Allow dynamic-group ${oci_identity_dynamic_group.nodes.name} to read repos in ${local.cpt}",
    "Allow dynamic-group ${oci_identity_dynamic_group.nodes.name} to read secret-family in ${local.cpt}",
    # CI: push/manage images, deploy to the cluster, read secrets for smoke config
    "Allow group ${oci_identity_group.ci.name} to manage repos in ${local.cpt}",
    "Allow group ${oci_identity_group.ci.name} to use clusters in ${local.cpt}",
    "Allow group ${oci_identity_group.ci.name} to read secret-family in ${local.cpt}",
  ]
}

resource "oci_identity_policy" "ocir_tenancy" {
  # OCIR namespace-level listing is a tenancy permission
  compartment_id = var.tenancy_ocid
  name           = "${var.name}-ocir"
  description    = "Let ${var.name} identities authenticate to OCIR"
  statements = [
    "Allow group ${oci_identity_group.ci.name} to read objectstorage-namespaces in tenancy",
    "Allow dynamic-group ${oci_identity_dynamic_group.nodes.name} to read objectstorage-namespaces in tenancy",
  ]
}

# ---- Container registry (private): one image, two workloads (web + scanner) ----
resource "oci_artifacts_container_repository" "app" {
  compartment_id = var.compartment_ocid
  display_name   = "${var.name}/app"
  is_public      = false
  is_immutable   = false
}
