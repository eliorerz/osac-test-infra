#!/usr/bin/env bash
# vault-health-check.sh -- Health check for the OSAC Vault instance.
#
# Detects whether this machine runs a central (local) vault or an agent
# (SSH tunnel to central vault) and adjusts checks accordingly.
#
# Detection logic:
#   - vault-tunnel.service active  -> agent mode
#   - vault.service active         -> central mode
#   - neither                      -> unknown (checks what it can)
set -euo pipefail

VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
export VAULT_ADDR

VAULT_HOME="${HOME}/.vault-server"
APPROLE_DIR="${VAULT_HOME}/.approle"

# Authenticated checks need a token.  Try init JSON first, then env var.
INIT_JSON="${VAULT_HOME}/.vault-init.json"
if [[ -f "${INIT_JSON}" ]]; then
    export VAULT_TOKEN
    VAULT_TOKEN=$(jq -r '.root_token' "${INIT_JSON}")
elif [[ -z "${VAULT_TOKEN:-}" ]]; then
    echo "WARNING: No VAULT_TOKEN set and ${INIT_JSON} not found."
    echo "         Authenticated checks will fail."
fi

passed=0
failed=0

check() {
    local num="$1" name="$2"
    shift 2
    if "$@" >/dev/null 2>&1; then
        echo "  [PASS] ${num}. ${name}"
        passed=$(( passed + 1 ))
    else
        echo "  [FAIL] ${num}. ${name}"
        failed=$(( failed + 1 ))
    fi
}

###############################################################################
# Detect mode
###############################################################################
IS_AGENT=false
IS_CENTRAL=false

if systemctl --user is-active vault-tunnel.service &>/dev/null; then
    IS_AGENT=true
elif systemctl --user is-active vault.service &>/dev/null; then
    IS_CENTRAL=true
fi

if [[ "${IS_AGENT}" == "true" ]]; then
    echo "=== Vault Health Check (Agent — tunnel mode) ==="
elif [[ "${IS_CENTRAL}" == "true" ]]; then
    echo "=== Vault Health Check (Central) ==="
else
    echo "=== Vault Health Check (unknown mode) ==="
fi
echo ""

###############################################################################
# Common checks (run on all machines)
###############################################################################
CHECK_NUM=1

# 1. Vault reachable
check ${CHECK_NUM} "Vault is reachable" vault status -format=json
CHECK_NUM=$(( CHECK_NUM + 1 ))

# 2. Vault unsealed
check ${CHECK_NUM} "Vault is unsealed" \
    bash -c 'test "$(vault status -format=json | jq -r .sealed)" = "false"'
CHECK_NUM=$(( CHECK_NUM + 1 ))

# 3. Vault initialized
check ${CHECK_NUM} "Vault is initialized" \
    bash -c 'test "$(vault status -format=json | jq -r .initialized)" = "true"'
CHECK_NUM=$(( CHECK_NUM + 1 ))

# 4. Vault version reported
check ${CHECK_NUM} "Vault version reported" \
    bash -c 'vault status -format=json | jq -e .version'
CHECK_NUM=$(( CHECK_NUM + 1 ))

# 5. JWT auth enabled
check ${CHECK_NUM} "JWT auth method enabled" \
    bash -c 'vault auth list -format=json | jq -e ".\"jwt/\""'
CHECK_NUM=$(( CHECK_NUM + 1 ))

# 6. osac-e2e role exists
check ${CHECK_NUM} "osac-e2e role exists" \
    vault read auth/jwt/role/osac-e2e
CHECK_NUM=$(( CHECK_NUM + 1 ))

# 7. osac-e2e policy exists
check ${CHECK_NUM} "osac-e2e policy exists" \
    vault policy read osac-e2e
CHECK_NUM=$(( CHECK_NUM + 1 ))

# 8. KV v2 at secret/
check ${CHECK_NUM} "KV v2 secrets engine at secret/" \
    bash -c 'vault secrets list -format=json | jq -e ".\"secret/\""'
CHECK_NUM=$(( CHECK_NUM + 1 ))

# 9. AppRole auth enabled
check ${CHECK_NUM} "AppRole auth method enabled" \
    bash -c 'vault auth list -format=json | jq -e ".\"approle/\""'
CHECK_NUM=$(( CHECK_NUM + 1 ))

# 10. AppRole credentials exist
check ${CHECK_NUM} "AppRole credentials present" \
    bash -c 'test -f "'"${APPROLE_DIR}/role-id"'" && test -f "'"${APPROLE_DIR}/secret-id"'"'
CHECK_NUM=$(( CHECK_NUM + 1 ))

# 11. AppRole login works
check ${CHECK_NUM} "AppRole login succeeds" \
    bash -c 'vault write -format=json auth/approle/login \
        role_id="$(cat "'"${APPROLE_DIR}/role-id"'")" \
        secret_id="$(cat "'"${APPROLE_DIR}/secret-id"'")" \
        | jq -e ".auth.client_token"'
CHECK_NUM=$(( CHECK_NUM + 1 ))

###############################################################################
# Mode-specific checks
###############################################################################
if [[ "${IS_CENTRAL}" == "true" ]]; then
    # Central: local vault.service and backup timer
    check ${CHECK_NUM} "vault.service is active" \
        systemctl --user is-active vault.service
    CHECK_NUM=$(( CHECK_NUM + 1 ))

    check ${CHECK_NUM} "vault-backup.timer is active" \
        systemctl --user is-active vault-backup.timer
    CHECK_NUM=$(( CHECK_NUM + 1 ))

elif [[ "${IS_AGENT}" == "true" ]]; then
    # Agent: tunnel service
    check ${CHECK_NUM} "vault-tunnel.service is active" \
        systemctl --user is-active vault-tunnel.service
    CHECK_NUM=$(( CHECK_NUM + 1 ))

    check ${CHECK_NUM} "vault-tunnel.service is enabled" \
        systemctl --user is-enabled vault-tunnel.service
    CHECK_NUM=$(( CHECK_NUM + 1 ))

    # Verify local vault is NOT running (would conflict)
    check ${CHECK_NUM} "local vault.service is not active (expected)" \
        bash -c '! systemctl --user is-active vault.service'
    CHECK_NUM=$(( CHECK_NUM + 1 ))
fi

###############################################################################
# Summary
###############################################################################
echo ""
echo "=== Results: ${passed} passed, ${failed} failed ==="

if (( failed > 0 )); then
    echo ""
    echo "Troubleshooting:"
    if [[ "${IS_AGENT}" == "true" ]]; then
        echo "  systemctl --user status vault-tunnel.service  # Check tunnel"
        echo "  journalctl --user -u vault-tunnel.service     # Tunnel logs"
    else
        echo "  systemctl --user status vault.service         # Check vault"
        echo "  podman logs systemd-vault                     # Container logs"
    fi
    echo "  vault status                                  # Vault status"
    exit 1
fi
