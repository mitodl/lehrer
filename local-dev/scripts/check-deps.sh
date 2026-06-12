#!/usr/bin/env bash
# Verify that all required tools are installed and meet minimum version requirements.
set -euo pipefail

ERRORS=0

check_cmd() {
    local cmd="$1"
    local min_version="$2"
    local version_flag="${3:---version}"

    if ! command -v "$cmd" &>/dev/null; then
        echo "MISSING: $cmd (required >= $min_version)" >&2
        ERRORS=$((ERRORS + 1))
        return
    fi
    local installed
    installed=$("$cmd" "$version_flag" 2>&1 | head -1)
    echo "OK:      $cmd — $installed"
}

check_cmd k3d    "5.0"  version
check_cmd kubectl "1.26" version
check_cmd tilt   "0.33" version
check_cmd helm   "3.12" version
check_cmd dagger "0.9"  version
check_cmd docker "24.0" "--version"

if [[ $ERRORS -gt 0 ]]; then
    echo ""
    echo "$ERRORS missing dependency/ies. Install them before running setup.sh." >&2
    exit 1
fi

echo ""
echo "All dependencies present."
