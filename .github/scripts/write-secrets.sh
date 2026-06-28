#!/usr/bin/env bash
# Write pull-secret and AAP license to disk for test container mounts,
# and set up podman registry auth for flavor/image pulls.
#
# Required env: PULL_SECRET, AAP_LICENSE
set -euo pipefail

: "${PULL_SECRET:?PULL_SECRET is required}"
: "${AAP_LICENSE:?AAP_LICENSE is required}"

# Set up podman registry auth for flavor pull and test image pulls
mkdir -p "${HOME}/.config/containers"
printf '%s' "${PULL_SECRET}" > "${HOME}/.config/containers/auth.json"
chmod 600 "${HOME}/.config/containers/auth.json"

# Write secrets for test container mounts
printf '%s' "${PULL_SECRET}" > "$RUNNER_TEMP/pull-secret.json"
chmod 600 "$RUNNER_TEMP/pull-secret.json"

printf '%s' "${AAP_LICENSE}" | base64 -d > "$RUNNER_TEMP/aap-license.zip"
chmod 600 "$RUNNER_TEMP/aap-license.zip"
