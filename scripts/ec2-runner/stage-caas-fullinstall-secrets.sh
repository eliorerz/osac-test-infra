#!/bin/bash

# stage-caas-fullinstall-secrets.sh -- Copy the CaaS full-install secrets
# push-caas-fullinstall-secrets.sh already staged on this box (before the
# JIT runner even started, since no checkout/RUNNER_TEMP existed yet at
# that point) into $RUNNER_TEMP, where the test job's later steps expect
# them (matching e2e-vmaas-full-install.yml's/e2e-caas-full-install.yml's
# own $RUNNER_TEMP/pull-secret.json, $RUNNER_TEMP/aap-license.zip
# convention). Runs on the ephemeral box itself, as part of the test job,
# after its own checkout.
#
# Required env vars:
#   RUNNER_TEMP_DIR      destination directory (use $RUNNER_TEMP)
#
# Optional env vars:
#   REMOTE_STAGING_DIR   must match push-caas-fullinstall-secrets.sh's
#                        value (default: /root/caas-fullinstall-secrets)

set -euo pipefail

RESET="\e[0m"
BOLD="\e[1m"
GREEN="\e[32m"

: "${RUNNER_TEMP_DIR:?RUNNER_TEMP_DIR is required}"

REMOTE_STAGING_DIR="${REMOTE_STAGING_DIR:-/root/caas-fullinstall-secrets}"

echo -e "${BOLD}Staging CaaS full-install secrets into place...${RESET}"

cp "${REMOTE_STAGING_DIR}/pull-secret.json" "${RUNNER_TEMP_DIR}/pull-secret.json"
cp "${REMOTE_STAGING_DIR}/aap-license.zip" "${RUNNER_TEMP_DIR}/aap-license.zip"
cp "${REMOTE_STAGING_DIR}/aws-credentials.env" "${RUNNER_TEMP_DIR}/aws-credentials.env"
chmod 600 "${RUNNER_TEMP_DIR}/pull-secret.json" "${RUNNER_TEMP_DIR}/aap-license.zip" "${RUNNER_TEMP_DIR}/aws-credentials.env"

# Remove the staging copies once they're in their final place -- a second
# copy lying around outside $RUNNER_TEMP's own access patterns is
# unnecessary exposure on an otherwise single-tenant box.
rm -rf "${REMOTE_STAGING_DIR}"

echo -e "${GREEN}${BOLD}CaaS full-install secrets in place.${RESET}"
