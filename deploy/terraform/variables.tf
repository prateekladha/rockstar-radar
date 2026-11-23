variable "region" {
  type    = string
  default = "ap-mumbai-1"
}
variable "oci_profile" {
  type    = string
  default = "DEFAULT"
}
variable "tenancy_ocid" { type = string }
variable "compartment_ocid" {
  type        = string
  description = "Rockstar Radar's own compartment (created by bootstrap.sh) — holds its Vault, OCIR repo and CI identity. The CLUSTER and ADB are NOT here; they are reused from the shared project (see shared_* vars)."
}
variable "name" {
  type    = string
  default = "rockstar-radar"
}

# ---- Shared infra reused from the dt-telekom / dt-selfcare project (same tenancy) ----
# Rockstar runs as its own namespace on the existing OKE cluster and as its own schema in the existing
# Autonomous DB, instead of standing up a second cluster/ADB (the tenancy's Always-Free limits are
# 1 cluster + the ADB free slots, already used by dt-selfcare). See docs/K8S_MIGRATION.md.
variable "shared_compartment_ocid" {
  type        = string
  description = "Compartment holding the shared OKE cluster + ADB (dt-selfcare)."
}
variable "shared_adb_name" {
  type        = string
  default     = "dt-selfcare-adb"
  description = "Display name of the existing Autonomous DB whose instance Rockstar shares (its own ROCKSTAR_APP schema)."
}
variable "shared_node_dynamic_group" {
  type        = string
  default     = "dt-selfcare-nodes"
  description = "Dynamic group of the shared cluster's worker nodes — granted read access to Rockstar's Vault so External Secrets (instance principal) can sync Rockstar's secrets."
}
