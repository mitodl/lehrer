#!/usr/bin/env bash
# Bootstrap the lehrer-dev k3d cluster for local Open edX development.
# Run this once before `tilt up`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DEV_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "==> Checking dependencies..."
bash "$SCRIPT_DIR/check-deps.sh"

# ---------------------------------------------------------------------------
# Cluster
# ---------------------------------------------------------------------------

if k3d cluster list 2>/dev/null | grep -q "lehrer-dev"; then
    echo "==> Cluster lehrer-dev already exists — skipping creation."
else
    echo "==> Creating k3d cluster lehrer-dev..."
    k3d cluster create --config "$LOCAL_DEV_DIR/k3d-config.yaml"
fi

echo "==> Switching kubectl context to k3d-lehrer-dev..."
kubectl config use-context k3d-lehrer-dev

echo "==> Waiting for nodes to be ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=120s

# ---------------------------------------------------------------------------
# Namespace
# ---------------------------------------------------------------------------

echo "==> Creating openedx namespace..."
kubectl apply -f "$LOCAL_DEV_DIR/manifests/namespace.yaml"

# ---------------------------------------------------------------------------
# Helm repos
# ---------------------------------------------------------------------------

echo "==> Adding Helm repositories..."
helm repo add opensearch-helm https://opensearch-project.github.io/helm-charts 2>/dev/null || true
helm repo add mariadb https://helm.mariadb.com/mariadb-operator 2>/dev/null || true
helm repo add mongodb https://mongodb.github.io/helm-charts 2>/dev/null || true
helm repo add valkey https://valkey.io/valkey-helm/ 2>/dev/null || true
helm repo update

# ---------------------------------------------------------------------------
# Secrets
# Below are safe local-dev defaults. Override by setting env vars before running.
# ---------------------------------------------------------------------------

MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-"openedx-dev"}"  # pragma: allowlist secret
MYSQL_PASSWORD="${MYSQL_PASSWORD:-"openedx-dev"}"            # pragma: allowlist secret
DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-"insecure-local-dev-key-change-for-staging"}"  # pragma: allowlist secret
MONGO_PASSWORD="${MONGO_PASSWORD:-"openedx-dev"}"            # pragma: allowlist secret
NOTES_OAUTH_CLIENT_ID="${NOTES_OAUTH_CLIENT_ID:-"notes"}"  # pragma: allowlist secret
NOTES_OAUTH_CLIENT_SECRET="${NOTES_OAUTH_CLIENT_SECRET:-"notes-dev-secret"}"  # pragma: allowlist secret

echo "==> Creating openedx-secrets Secret..."
kubectl -n openedx create secret generic openedx-secrets \
    --from-literal=MYSQL_ROOT_PASSWORD="$MYSQL_ROOT_PASSWORD" \
    --from-literal=MYSQL_PASSWORD="$MYSQL_PASSWORD" \
    --from-literal=DB_PASSWORD="$MYSQL_PASSWORD" \
    --from-literal=DJANGO_SECRET_KEY="$DJANGO_SECRET_KEY" \
    --from-literal=MONGO_PASSWORD="$MONGO_PASSWORD" \
    --from-literal=NOTES_OAUTH_CLIENT_ID="$NOTES_OAUTH_CLIENT_ID" \
    --from-literal=NOTES_OAUTH_CLIENT_SECRET="$NOTES_OAUTH_CLIENT_SECRET" \
    --dry-run=client -o yaml | kubectl apply -f -

echo ""
echo "==> Setup complete!"
echo ""
echo "Start the dev environment with:"
echo "    cd $LOCAL_DEV_DIR && tilt up"
echo ""
echo "To use a custom deployment config:"
echo "    tilt up -- --deployment-config ../deployments/<name>"
echo ""
echo "To tear down:"
echo "    bash $SCRIPT_DIR/teardown.sh"
