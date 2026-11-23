#!/usr/bin/env bash
# Pushes CI credentials from Terraform outputs into GitHub Actions secrets/variables (piped, never printed).
# Used by the P5 deploy workflow (build image -> push OCIR -> helm upgrade on OKE).
set -euo pipefail
export SUPPRESS_LABEL_WARNING=True
cd "$(dirname "$0")/../terraform"
REPO="${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
TENANCY=$(grep -E '^tenancy_ocid' terraform.tfvars | cut -d'"' -f2)
terraform output -raw ci_private_key | gh secret set OCI_CI_PRIVATE_KEY -R "$REPO"
terraform output -raw ci_auth_token  | gh secret set OCIR_TOKEN -R "$REPO"
gh secret set OCI_CI_USER_OCID   -R "$REPO" -b "$(terraform output -raw ci_user_ocid)"
gh secret set OCI_CI_FINGERPRINT -R "$REPO" -b "$(terraform output -raw ci_fingerprint)"
gh secret set OCI_TENANCY_OCID   -R "$REPO" -b "$TENANCY"
gh secret set OCIR_USERNAME      -R "$REPO" -b "$(terraform output -raw ocir_username_ci)"
gh variable set OCI_CLUSTER_ID   -R "$REPO" -b "$(terraform output -raw cluster_id)"
gh variable set OCIR_REGISTRY    -R "$REPO" -b "$(terraform output -raw ocir_registry)"
echo "GitHub secrets/variables set for $REPO"
