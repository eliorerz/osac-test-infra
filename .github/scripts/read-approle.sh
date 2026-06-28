#!/usr/bin/env bash
# Read Vault AppRole credentials from the runner's local filesystem.
# Outputs: role-id, secret-id (GITHUB_OUTPUT)
set -euo pipefail

APPROLE_DIR="${HOME}/.vault-server/.approle"
echo "role-id=$(cat "${APPROLE_DIR}/role-id")" >> "$GITHUB_OUTPUT"
echo "::add-mask::$(cat "${APPROLE_DIR}/secret-id")"
echo "secret-id=$(cat "${APPROLE_DIR}/secret-id")" >> "$GITHUB_OUTPUT"
