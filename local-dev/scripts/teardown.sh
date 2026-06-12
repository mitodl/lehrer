#!/usr/bin/env bash
# Delete the lehrer-dev k3d cluster and clean up local temp files.
set -euo pipefail

echo "==> Deleting k3d cluster lehrer-dev..."
k3d cluster delete lehrer-dev 2>/dev/null || echo "Cluster lehrer-dev not found — nothing to delete."

echo "==> Cleaning up MFE temp build directories..."
rm -rf /tmp/lehrer-mfe-dist

echo "==> Done."
