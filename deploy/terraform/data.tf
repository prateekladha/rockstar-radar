# ---------------- Object Storage namespace (for OCIR + tfstate) ----------------
data "oci_objectstorage_namespace" "ns" {
  compartment_id = var.tenancy_ocid
}

# ---------------- Shared Autonomous Database (reused, not created) ----------------
# Rockstar does NOT create its own ADB (the tenancy's Always-Free ADB slots are used by dt-selfcare).
# It reuses the existing dt-selfcare ADB *instance* and gets its own least-privilege schema/user
# (ROCKSTAR_APP), created out-of-band by deploy/scripts/migrate_db.py --bootstrap-user. Here we only
# read the instance to build the app's TLS DSN; nothing about the shared ADB is managed by Terraform.
data "oci_database_autonomous_databases" "shared" {
  compartment_id = var.shared_compartment_ocid
  display_name   = var.shared_adb_name
}

resource "random_password" "db_app" {
  length           = 24
  min_upper        = 2
  min_lower        = 2
  min_numeric      = 2
  min_special      = 2
  override_special = "#_"
}

locals {
  shared_adb = data.oci_database_autonomous_databases.shared.autonomous_databases[0]
  # SQLAlchemy connects as ROCKSTAR_APP over this wallet-less TLS (TCPS) DSN, LOW consumer group.
  adb_tls_low = [
    for p in local.shared_adb.connection_strings[0].profiles : p.value
    if p.consumer_group == "LOW" && p.tls_authentication == "SERVER" && p.protocol == "TCPS"
  ][0]
}
