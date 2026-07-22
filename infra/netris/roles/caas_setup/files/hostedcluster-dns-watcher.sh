#!/bin/bash
# Watches for CaaS ClusterOrders' HostedCluster kube-apiserver Services and
# dynamically wires DNS for their auto-generated hostnames on mgmt-server's
# dnsmasq.
#
# The hosting cluster's own api./apps. routes get a static wildcard DNS entry
# (see caas_discovery's "Configure OCP DNS on mgmt-server" task) because that
# domain and its target IP (the host's own br-mgmt address) are both fixed
# and known ahead of time. A HostedCluster order's kube-apiserver Service is
# different: MetalLB's caas-address-pool hands out a different IP per Service
# (confirmed live: run 29940857732's first order got 192.168.160.240 from a
# 192.168.160.240-250 pool) -- a static entry can't track that, and without
# any entry at all, worker nodes' kubelets time out trying to join
# ("dial tcp 198.51.100.1:6443: i/o timeout" against the Netris DNAT
# placeholder the hostname resolves to with no wildcard covering it).
#
# Runs as a background poller (started once, for the life of the test job)
# rather than a one-shot task because ClusterOrders are created by the test
# suite itself, after this role has already finished.
set -euo pipefail

KUBECONFIG="${1:?kubeconfig path required}"
OCP_BASE_DOMAIN="${2:?base domain required}"
MGMT_SERVER_IP="${3:?mgmt-server IP required}"
export KUBECONFIG

declare -A seen

while true; do
  orders=$(oc get clusterorder -A -o json 2>/dev/null | python3 -c '
import json, sys
data = json.load(sys.stdin)
for item in data.get("items", []):
    ref = item.get("status", {}).get("clusterReference", {})
    ns = ref.get("namespace")
    name = ref.get("hostedClusterName")
    if ns and name:
        print(f"{ns} {name}")
' 2>/dev/null || true)

  while read -r ns name; do
    [ -z "${ns:-}" ] && continue
    key="${ns}/${name}"
    [ -n "${seen[$key]:-}" ] && continue

    ip=$(oc get svc kube-apiserver -n "${ns}-${name}" \
      -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
    [ -z "$ip" ] && continue

    echo "Wiring DNS for HostedCluster ${name}: api./apps.${name}.${OCP_BASE_DOMAIN} -> ${ip}"
    ssh -o StrictHostKeyChecking=no "root@${MGMT_SERVER_IP}" "
      cat > /etc/dnsmasq.d/hostedcluster-${name}.conf <<DNSEOF
address=/api.${name}.${OCP_BASE_DOMAIN}/${ip}
address=/.apps.${name}.${OCP_BASE_DOMAIN}/${ip}
DNSEOF
      systemctl restart dnsmasq
    " && seen[$key]=1
  done <<< "$orders"

  sleep 10
done
