#!/usr/bin/env bash
# One-time cluster platform setup (run by an admin after `terraform apply`): kubeconfig + add-ons + CI RBAC.
#   External Secrets (OCI Vault -> k8s Secrets via instance principal), cert-manager (Let's Encrypt),
#   Traefik ingress on the Always-Free flexible LB (10 Mbps), metrics-server (for the web HPA).
set -euo pipefail
export SUPPRESS_LABEL_WARNING=True
cd "$(dirname "$0")/../terraform"
NAME="${NAME:-rockstar-radar}"
CLUSTER=$(terraform output -raw cluster_id)
CI_USER=$(terraform output -raw ci_user_ocid)
REGION=$(grep -E '^region' terraform.tfvars | cut -d'"' -f2)

kubectl config get-contexts "$NAME" >/dev/null 2>&1 || oci ce cluster create-kubeconfig \
  --cluster-id "$CLUSTER" --region "$REGION" --file "$HOME/.kube/config" \
  --token-version 2.0.0 --kube-endpoint PUBLIC_ENDPOINT --overwrite >/dev/null
kubectl config rename-context "$(kubectl config current-context)" "$NAME" >/dev/null 2>&1 || true
kubectl config use-context "$NAME" >/dev/null

helm repo add external-secrets https://charts.external-secrets.io >/dev/null
helm repo add jetstack https://charts.jetstack.io >/dev/null
helm repo add traefik https://traefik.github.io/charts >/dev/null
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/ >/dev/null
helm repo update >/dev/null

helm upgrade --install external-secrets external-secrets/external-secrets -n external-secrets --create-namespace \
  --set installCRDs=true --set resources.requests.cpu=20m --set resources.requests.memory=64Mi --wait
helm upgrade --install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
  --set crds.enabled=true --set resources.requests.cpu=10m --set resources.requests.memory=64Mi --wait
helm upgrade --install metrics-server metrics-server/metrics-server -n kube-system --wait
helm upgrade --install traefik traefik/traefik -n traefik --create-namespace --wait \
  --set-string 'service.annotations.service\.beta\.kubernetes\.io/oci-load-balancer-shape=flexible' \
  --set-string 'service.annotations.service\.beta\.kubernetes\.io/oci-load-balancer-shape-flex-min=10' \
  --set-string 'service.annotations.service\.beta\.kubernetes\.io/oci-load-balancer-shape-flex-max=10' \
  --set 'ports.web.http.redirections.entryPoint.to=websecure' --set 'ports.web.http.redirections.entryPoint.scheme=https' \
  --set 'ports.web.allowACMEByPass=true' \
  --set service.spec.externalTrafficPolicy=Local \
  --set resources.requests.cpu=50m --set resources.requests.memory=64Mi

kubectl create namespace "$NAME" --dry-run=client -o yaml | kubectl apply -f -
# CI deploys only into the app namespace: namespace-scoped admin, nothing cluster-wide.
kubectl -n "$NAME" create rolebinding ci-deployer --clusterrole=admin --user="$CI_USER" \
  --dry-run=client -o yaml | kubectl apply -f -

for i in $(seq 1 60); do
  IP=$(kubectl -n traefik get svc traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
  [[ -n "$IP" ]] && break; sleep 5
done
echo "load balancer IP: ${IP:-pending}  -> test domain ${IP:+$IP.sslip.io}"
echo "point intraday.live at this IP only at the P6 cutover."
