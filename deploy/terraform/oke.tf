data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

data "oci_containerengine_node_pool_option" "opts" {
  node_pool_option_id = "all"
  compartment_id      = var.compartment_ocid
}

locals {
  k8s_minor = trimprefix(var.kubernetes_version, "v")
  is_arm    = length(regexall("A1", var.node_shape)) > 0
  # Latest Oracle Linux OKE image for our Kubernetes version and the node CPU architecture.
  node_image_id = [
    for s in data.oci_containerengine_node_pool_option.opts.sources : s.image_id
    if(length(regexall("aarch64", s.source_name)) > 0) == local.is_arm
    && length(regexall("OKE-${local.k8s_minor}-", s.source_name)) > 0
    && length(regexall("GPU", s.source_name)) == 0
  ][0]
}

# BASIC cluster: managed control plane at no charge.
resource "oci_containerengine_cluster" "main" {
  compartment_id     = var.compartment_ocid
  name               = "${var.name}-oke"
  kubernetes_version = var.kubernetes_version
  vcn_id             = oci_core_vcn.main.id
  type               = "BASIC_CLUSTER"

  cluster_pod_network_options { cni_type = "FLANNEL_OVERLAY" }

  endpoint_config {
    subnet_id            = oci_core_subnet.api.id
    is_public_ip_enabled = true
  }

  options {
    service_lb_subnet_ids = [oci_core_subnet.lb.id]
    kubernetes_network_config {
      pods_cidr     = local.pods_cidr
      services_cidr = "10.96.0.0/16"
    }
  }
}

resource "oci_containerengine_node_pool" "nodes" {
  compartment_id     = var.compartment_ocid
  cluster_id         = oci_containerengine_cluster.main.id
  name               = "${var.name}-np"
  kubernetes_version = var.kubernetes_version
  node_shape         = var.node_shape

  node_shape_config {
    ocpus         = var.node_ocpus
    memory_in_gbs = var.node_memory_gb
  }

  node_source_details {
    source_type             = "IMAGE"
    image_id                = local.node_image_id
    boot_volume_size_in_gbs = 80
  }

  node_config_details {
    size = var.node_count
    placement_configs {
      availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
      subnet_id           = oci_core_subnet.workers.id
    }
  }

  # OKE bootstrap + grow the root filesystem to the full boot volume (OKE does not do it by default)
  node_metadata = {
    user_data = base64encode(<<-EOT
      #!/bin/bash
      curl --fail -H "Authorization: Bearer Oracle" -L0 http://169.254.169.254/opc/v2/instance/metadata/oke_init_script | base64 --decode >/var/run/oke-init.sh
      bash /var/run/oke-init.sh
      /usr/libexec/oci-growfs -y
    EOT
    )
  }

  initial_node_labels {
    key   = "pool"
    value = "main"
  }
}
