#!/usr/bin/env bash
# Delete the lehrer-dev k3d cluster and clean up all local state.
set -euo pipefail

echo "==> Stopping Tilt (if running)..."
# tilt down gracefully removes k8s resources; if tilt isn't running, kill any
# leftover process from the local-dev directory.
if tilt down --file "$(dirname "$0")/../Tiltfile" 2>/dev/null; then
    echo "    Tilt resources removed."
else
    pkill -f "tilt up" 2>/dev/null && echo "    Killed tilt process." || true
fi

echo "==> Deleting k3d cluster lehrer-dev..."
k3d cluster delete lehrer-dev 2>/dev/null || echo "    Cluster lehrer-dev not found — nothing to delete."

echo "==> Removing kubeconfig context..."
kubectl config delete-context k3d-lehrer-dev 2>/dev/null || true
kubectl config delete-cluster k3d-lehrer-dev 2>/dev/null || true
kubectl config delete-user admin@k3d-lehrer-dev 2>/dev/null || true

echo "==> Cleaning up Helm repo cache entries..."
helm repo remove mariadb 2>/dev/null || true
helm repo remove mongodb 2>/dev/null || true
helm repo remove valkey 2>/dev/null || true
helm repo remove opensearch-helm 2>/dev/null || true

echo "==> Cleaning up temp build artifacts..."
rm -rf /tmp/lehrer-mfe-dist
rm -f /tmp/lehrer-platform-*.tar
rm -f /tmp/lehrer-codejail-*.tar
rm -f /tmp/lehrer-notes-*.tar

echo "==> Done. Run scripts/setup.sh to create a fresh environment."
