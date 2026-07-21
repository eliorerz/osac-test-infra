#!/bin/bash

# push-caas-fullinstall-secrets.sh -- Fetch secrets on the orchestrator
# (which has working Vault access) and push them to the freshly-provisioned
# ephemeral EC2 box via SCP, before the JIT runner even starts.
#
# Same rationale as push-caas-netris-secrets.sh (see that file's header):
# the ephemeral box never talks to Vault itself, so the orchestrator pushes
# what the box needs instead. This is the trimmed set for the Netris-free
# "CaaS full install" mechanism (cluster-tool + local agent VM, no Netris
# lab): pull-secret, AAP license, and AWS credentials (for HyperShift
# hosted-cluster creation on AWS-backed infra) -- no Netris license, no
# Route53 creds, no lab_name/DNS config.
#
# Uses real scp file transfer, not an SSH command with the secret value
# embedded in argv -- scp streams file bytes over SSH's data channel, so
# secret content never appears as a process argument on either machine.
#
# Required env vars:
#   SSH_KEY_PATH        path to the orchestrator's SSH private key
#   SSH_USER            SSH user on the box (from provision.sh output)
#   PUBLIC_IP           the box's public IP (from provision.sh output)
#   KNOWN_HOSTS_FILE     the same run-specific known_hosts path provision.sh
#                        used to establish trust with this box
#   AWS_ACCESS_KEY_ID    AWS access key id for HyperShift hosted-cluster
#                        creation (cluster-fulfillment-ig secret)
#   AWS_SECRET_ACCESS_KEY  matching secret access key
#   AAP_LICENSE_ZIP_PATH  local path to the already-fetched, already
#                        base64-decoded AAP license zip (written by
#                        fetch-and-write-secrets to
#                        $RUNNER_TEMP/aap-license.zip)
#   PULL_SECRET_JSON_PATH  local path to the already-fetched pull secret
#                        JSON (written by fetch-and-write-secrets to
#                        $RUNNER_TEMP/pull-secret.json)
#
# Optional env vars:
#   REMOTE_STAGING_DIR    fixed path on the box to stage secrets at
#                        (default: /root/caas-fullinstall-secrets) -- must
#                        match stage-caas-fullinstall-secrets.sh's value

set -euo pipefail

RESET="\e[0m"
BOLD="\e[1m"
GREEN="\e[32m"

: "${SSH_KEY_PATH:?SSH_KEY_PATH is required}"
: "${SSH_USER:?SSH_USER is required}"
: "${PUBLIC_IP:?PUBLIC_IP is required}"
: "${KNOWN_HOSTS_FILE:?KNOWN_HOSTS_FILE is required}"
: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID is required}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY is required}"
: "${AAP_LICENSE_ZIP_PATH:?AAP_LICENSE_ZIP_PATH is required}"
: "${PULL_SECRET_JSON_PATH:?PULL_SECRET_JSON_PATH is required}"

REMOTE_STAGING_DIR="${REMOTE_STAGING_DIR:-/root/caas-fullinstall-secrets}"

ssh_exec() {
    ssh -i "$SSH_KEY_PATH" \
        -o StrictHostKeyChecking=accept-new \
        -o UserKnownHostsFile="${KNOWN_HOSTS_FILE}" \
        -o BatchMode=yes \
        -o ConnectTimeout=10 \
        "${SSH_USER}@${PUBLIC_IP}" "$@"
}

scp_to_box() {
    # -p preserves the source file's mode (all sources below are 600,
    # written by mktemp or an explicit chmod) instead of falling back to
    # sftp's default create mode.
    scp -p -i "$SSH_KEY_PATH" \
        -o StrictHostKeyChecking=accept-new \
        -o UserKnownHostsFile="${KNOWN_HOSTS_FILE}" \
        -o BatchMode=yes \
        -o ConnectTimeout=10 \
        "$1" "${SSH_USER}@${PUBLIC_IP}:$2"
}

echo -e "${BOLD}Staging CaaS full-install secrets on ${PUBLIC_IP}...${RESET}"

AWS_CREDS_FILE=$(mktemp)
trap 'rm -f "$AWS_CREDS_FILE"' EXIT

umask 077
cat > "$AWS_CREDS_FILE" <<EOF
AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
EOF

ssh_exec "mkdir -p '${REMOTE_STAGING_DIR}' && chmod 700 '${REMOTE_STAGING_DIR}'"

scp_to_box "$AAP_LICENSE_ZIP_PATH" "${REMOTE_STAGING_DIR}/aap-license.zip"
scp_to_box "$PULL_SECRET_JSON_PATH" "${REMOTE_STAGING_DIR}/pull-secret.json"
scp_to_box "$AWS_CREDS_FILE" "${REMOTE_STAGING_DIR}/aws-credentials.env"

ssh_exec "chmod 600 '${REMOTE_STAGING_DIR}'/*"

echo -e "${GREEN}${BOLD}CaaS full-install secrets staged at ${REMOTE_STAGING_DIR} on the box.${RESET}"
