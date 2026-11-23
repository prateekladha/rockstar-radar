# ---------------- Object Storage namespace (for OCIR + tfstate) ----------------
data "oci_objectstorage_namespace" "ns" {
  compartment_id = var.tenancy_ocid
}

# ---------------- Autonomous Database (Always Free) ----------------
# Postgres → Oracle ADB is done in migration phase P4. This provisions the DB now so the schema port
# and data load have a target; nothing connects to it until P4.
resource "random_password" "db_admin" {
  length           = 24
  min_upper        = 2
  min_lower        = 2
  min_numeric      = 2
  min_special      = 2
  override_special = "#_"
}

resource "random_password" "db_app" {
  length           = 24
  min_upper        = 2
  min_lower        = 2
  min_numeric      = 2
  min_special      = 2
  override_special = "#_"
}

resource "oci_database_autonomous_database" "main" {
  compartment_id           = var.compartment_ocid
  db_name                  = "rockstar"
  display_name             = "${var.name}-adb"
  db_workload              = "OLTP"
  db_version               = "23ai"
  is_free_tier             = true
  admin_password           = random_password.db_admin.result
  data_storage_size_in_tbs = 1
  compute_model            = "ECPU"
  compute_count            = 1 # Always Free is fixed-size; scaling = upgrade to paid ADB
  # TLS without a wallet; only our VCN (reached via the service gateway) may connect.
  is_mtls_connection_required = false
  whitelisted_ips             = [oci_core_vcn.main.id]
  lifecycle {
    ignore_changes = [admin_password, compute_count, data_storage_size_in_tbs]
  }
}

locals {
  # SQLAlchemy connects as a least-privilege app user over this TLS (TCPS) DSN, LOW consumer group.
  adb_tls_low = [
    for p in oci_database_autonomous_database.main.connection_strings[0].profiles : p.value
    if p.consumer_group == "LOW" && p.tls_authentication == "SERVER" && p.protocol == "TCPS"
  ][0]
}
