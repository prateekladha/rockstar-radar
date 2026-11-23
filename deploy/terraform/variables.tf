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
  description = "Dedicated compartment for Rockstar Radar (created by bootstrap.sh) — isolates it from the existing VM deployment and other workloads."
}
variable "name" {
  type    = string
  default = "rockstar-radar"
}
variable "kubernetes_version" {
  type    = string
  default = "v1.37.1"
}
variable "node_count" {
  type        = number
  default     = 1
  description = "Worker nodes. Set to 0 to park the cluster at near-zero cost (control plane, Vault and ADB stay)."
}
variable "node_shape" {
  type        = string
  default     = "VM.Standard.A1.Flex"
  description = <<-DESC
    A1.Flex (ARM) is Always-Free eligible (4 OCPU / 24 GB total per tenancy). NOTE: the current
    intraday.live VM already consumes the Always-Free A1 allocation, so while BOTH the VM and this
    cluster run (migration phases P3–P6) either shrink the VM or set this to "VM.Standard.E5.Flex"
    (AMD, small hourly cost) for the node pool, then switch back to A1.Flex after the VM is
    decommissioned at cutover.
  DESC
}
variable "node_ocpus" {
  type    = number
  default = 2
}
variable "node_memory_gb" {
  type    = number
  default = 12
}
variable "api_allowed_cidrs" {
  type        = list(string)
  default     = ["0.0.0.0/0"]
  description = "Who may reach the Kubernetes API endpoint (auth is still OCI IAM)."
}
