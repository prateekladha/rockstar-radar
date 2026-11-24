locals {
  cpt = "compartment id ${var.compartment_ocid}"
}

# ---- CI identity (GitHub Actions): push images to Rockstar's OCIR repo ----
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

# ---- Access grants ----
# Rockstar reuses the shared cluster's worker nodes (dynamic group `dt-selfcare-nodes`), so THOSE nodes
# — not a Rockstar-owned node group — must be allowed to read Rockstar's Vault (External Secrets uses
# the node instance principal) and pull from Rockstar's OCIR repo.
resource "oci_identity_policy" "workloads" {
  compartment_id = var.compartment_ocid
  name           = "${var.name}-workloads"
  description    = "Least-privilege access for ${var.name} workloads (on the shared cluster) and CI"
  statements = [
    "Allow dynamic-group ${var.shared_node_dynamic_group} to read repos in ${local.cpt}",
    "Allow dynamic-group ${var.shared_node_dynamic_group} to read secret-family in ${local.cpt}",
    # CI: push/manage images, read secrets for smoke config
    "Allow group ${oci_identity_group.ci.name} to manage repos in ${local.cpt}",
    "Allow group ${oci_identity_group.ci.name} to read secret-family in ${local.cpt}",
  ]
}

# CI runs `helm upgrade` from GitHub Actions, which needs a kubeconfig token for the SHARED cluster
# (dt-selfcare-oke). The cluster lives in the shared compartment, so this grant is scoped there.
# "use clusters" is only enough to fetch a token + reach the API server — what the token can actually
# DO is limited by in-cluster RBAC (a RoleBinding to the rockstar-radar namespace only; see
# deploy/k8s/ci-rolebinding.yaml). So CI cannot touch dt-telekom's workloads.
resource "oci_identity_policy" "ci_cluster" {
  compartment_id = var.shared_compartment_ocid
  name           = "${var.name}-ci-cluster"
  description    = "Let ${var.name} CI fetch a kubeconfig token for the shared OKE cluster"
  statements = [
    "Allow group ${oci_identity_group.ci.name} to use clusters in compartment id ${var.shared_compartment_ocid}",
  ]
}

resource "oci_identity_policy" "ocir_tenancy" {
  # OCIR namespace-level listing is a tenancy permission
  compartment_id = var.tenancy_ocid
  name           = "${var.name}-ocir"
  description    = "Let ${var.name} identities authenticate to OCIR"
  statements = [
    "Allow group ${oci_identity_group.ci.name} to read objectstorage-namespaces in tenancy",
    "Allow dynamic-group ${var.shared_node_dynamic_group} to read objectstorage-namespaces in tenancy",
  ]
}

# ---- Container registry (private): one image, two workloads (web + scanner) ----
resource "oci_artifacts_container_repository" "app" {
  compartment_id = var.compartment_ocid
  display_name   = "${var.name}/app"
  is_public      = false
  is_immutable   = false
}
