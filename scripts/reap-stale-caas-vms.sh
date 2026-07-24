#!/usr/bin/env bash
# reap-stale-caas-vms.sh -- backstop cleanup for CaaS e2e agent/cluster VMs
# that survived teardown.sh (e.g. a crashed/cancelled job, or teardown's own
# agent-VM cleanup missing a `-c qemu:///system` connection and silently
# no-op'ing against the wrong libvirt session). Installed by machine-init.sh
# and run on a systemd timer, once per fleet machine -- no cross-host calls,
# no GitHub API access, nothing beyond what's local to this box.
#
# Age-based rather than correlated against live GitHub Actions job status,
# same choice ec2-runner-orphan-watchdog.yml already made for EC2 instances:
# simpler and more robust than trying to determine "is a job still using
# this VM" from the host alone. No legitimate e2e-caas-full-install run
# should take anywhere near MAX_AGE_HOURS.
#
# Usage: reap-stale-caas-vms.sh
# Env:   MAX_AGE_HOURS (default 4), AGENT_VM_STORAGE_DIR (default
#        /data/osac-storage), DRY_RUN=true to log without acting.
set -euo pipefail

MAX_AGE_HOURS="${MAX_AGE_HOURS:-4}"
MAX_AGE_SECONDS=$((MAX_AGE_HOURS * 3600))
STORAGE_DIR="${AGENT_VM_STORAGE_DIR:-/data/osac-storage}"
DRY_RUN="${DRY_RUN:-false}"
VIRSH="virsh -c qemu:///system"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

# Domain age = the qemu process's own elapsed runtime, not any libvirt XML
# timestamp (transient/persistent domain XML doesn't reliably record
# creation time). Matches the process by its `guest=<name>,` -name argument.
domain_age_seconds() {
    local name="$1" pid
    pid=$(pgrep -f "guest=${name}," | head -1) || true
    if [[ -z "${pid}" ]]; then
        # Domain defined but no running process (e.g. shut off) -- treat as
        # unconditionally stale, nothing legitimate leaves it in this state.
        echo "$((MAX_AGE_SECONDS + 1))"
        return
    fi
    ps -o etimes= -p "${pid}" 2>/dev/null | tr -d ' ' || echo "0"
}

reap_domain() {
    local name="$1" age_seconds
    age_seconds=$(domain_age_seconds "${name}")

    if [[ "${age_seconds}" -le "${MAX_AGE_SECONDS}" ]]; then
        return 0
    fi

    log "Reaping stale domain '${name}' (age: $((age_seconds / 3600))h, threshold: ${MAX_AGE_HOURS}h)"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "  DRY_RUN: would destroy/undefine ${name}"
        return 0
    fi
    ${VIRSH} destroy "${name}" 2>/dev/null || true
    ${VIRSH} undefine "${name}" 2>/dev/null || true
}

# --- CaaS agent VMs and their single-node cluster VMs ---
mapfile -t DOMAINS < <(${VIRSH} list --all --name 2>/dev/null \
    | grep -E '^agent-[a-zA-Z0-9]+-caas$|^test-infra-cluster-[a-zA-Z0-9]+-caas-master-[0-9]+$' || true)

for domain in "${DOMAINS[@]}"; do
    [[ -n "${domain}" ]] && reap_domain "${domain}"
done

# --- Orphaned disk files: no matching domain at all, regardless of age ---
# -mmin filter avoids racing setup-caas-agents.sh's own
# qemu-img create -> virt-install window (seconds, not the hour+ this
# script requires before it'll even look at a file).
if [[ -d "${STORAGE_DIR}" ]]; then
    while IFS= read -r -d '' f; do
        base=$(basename "${f}")
        vm_name="${base%.qcow2}"
        vm_name="${vm_name%-discovery.iso}"
        if ! ${VIRSH} dominfo "${vm_name}" &>/dev/null; then
            log "Removing orphaned disk file with no matching domain: ${f}"
            [[ "${DRY_RUN}" == "true" ]] || rm -f "${f}"
        fi
    done < <(find "${STORAGE_DIR}" -maxdepth 1 -type f \
        \( -name 'agent-*-caas.qcow2' -o -name 'agent-*-caas-discovery.iso' \) \
        -mmin "+$((MAX_AGE_HOURS * 60))" -print0 2>/dev/null)
fi

log "Reap pass complete."
