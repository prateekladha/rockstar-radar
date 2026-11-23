terraform {
  required_version = ">= 1.12"
  required_providers {
    oci    = { source = "oracle/oci", version = ">= 6.0" }
    random = { source = "hashicorp/random", version = ">= 3.6" }
    tls    = { source = "hashicorp/tls", version = ">= 4.0" }
  }
  # Remote state in OCI Object Storage (bucket created by scripts/bootstrap.sh).
  # Values supplied with: terraform init -backend-config=backend.hcl
  backend "oci" {}
}

provider "oci" {
  region              = var.region
  config_file_profile = var.oci_profile
}
