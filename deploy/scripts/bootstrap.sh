#!/usr/bin/env bash
# One-time, idempotent: dedicated compartment + Terraform state bucket, then write backend.hcl + tfvars.
set -euo pipefail
export SUPPRESS_LABEL_WARNING=True
NAME="${NAME:-rockstar-radar}"
REGION="${REGION:-ap-mumbai-1}"
DIR="$(cd "$(dirname "$0")/../terraform" && pwd)"
TENANCY=$(grep -m1 '^tenancy' ~/.oci/config | cut -d= -f2 | tr -d ' ')
NS=$(oci os ns get --query data --raw-output)

CPT=$(oci iam compartment list --compartment-id "$TENANCY" --name "$NAME" --lifecycle-state ACTIVE \
      --query 'data[0].id' --raw-output 2>/dev/null || true)
if [[ -z "$CPT" || "$CPT" == "null" ]]; then
  CPT=$(oci iam compartment create --compartment-id "$TENANCY" --name "$NAME" \
        --description "Rockstar Radar (OKE, isolated from the legacy VM)" --wait-for-state ACTIVE \
        --query 'data.id' --raw-output)
  echo "created compartment $CPT"
fi

if ! oci os bucket get --bucket-name "$NAME-tfstate" --namespace "$NS" >/dev/null 2>&1; then
  oci os bucket create --compartment-id "$CPT" --name "$NAME-tfstate" --namespace "$NS" \
      --versioning Enabled --public-access-type NoPublicAccess >/dev/null
  echo "created state bucket $NAME-tfstate"
fi

cat > "$DIR/backend.hcl" <<HCL
bucket    = "$NAME-tfstate"
namespace = "$NS"
key       = "$NAME/terraform.tfstate"
region    = "$REGION"
HCL
# Shared project (dt-selfcare) compartment — holds the OKE cluster + ADB that Rockstar reuses.
SHARED_NAME="${SHARED_NAME:-dt-selfcare}"
SHARED_CPT=$(oci iam compartment list --compartment-id "$TENANCY" --compartment-id-in-subtree true \
  --name "$SHARED_NAME" --lifecycle-state ACTIVE --query 'data[0].id' --raw-output 2>/dev/null || true)

cat > "$DIR/terraform.tfvars" <<TF
tenancy_ocid            = "$TENANCY"
compartment_ocid        = "$CPT"
region                  = "$REGION"
shared_compartment_ocid = "$SHARED_CPT"
TF
echo "compartment=$CPT shared=$SHARED_CPT namespace=$NS -> wrote backend.hcl and terraform.tfvars"
echo "next: cd $DIR && terraform init -backend-config=backend.hcl && terraform apply"
