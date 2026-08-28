from __future__ import annotations

import ipaddress
import logging
import os
from typing import Any
from uuid import uuid4

from tests.core.grpc_client import GRPCClient
from tests.core.helpers import wait_for_external_ip_allocated, wait_for_external_ip_cr
from tests.core.k8s_client import K8sClient

logger = logging.getLogger(__name__)

# This network is a portion of the RFC 1918 private range
IPV4_NETWORK: str = "172.27.0.0/16"


def allocate_worker_subnet(prefix: int = 24) -> ipaddress.IPv4Network:
    """
    Allocate subnet with worker-based namespacing to prevent conflicts in parallel execution.

    172.27.0.0/16 is split into two halves: /24 blocks from the lower half
    (172.27.0.0 - 172.27.127.255) and /30 blocks from the upper half
    (172.27.128.0 - 172.27.255.255), each half divided evenly across the
    ACTUAL number of concurrent pytest-xdist workers (PYTEST_XDIST_WORKER_COUNT),
    not a fixed count. This used to hardcode 4 workers; running with -n 6
    made worker gw4 compute third_octet=128 on its very first /24 allocation
    (already past the old fixed 127 ceiling) and crash immediately with
    "exhausted /24 address space" before allocating anything -- confirmed
    against a real failed run.

    Within each worker, a sequential counter allocates unique, deterministic
    CIDRs from that worker's own slice; going past the slice raises
    RuntimeError rather than silently wrapping into the next worker's range
    (the old fixed-4 version only checked the absolute ceiling of the whole
    half-space, not each worker's own slice boundary, so a worker other than
    the last one could in principle overflow into its neighbor's range
    without raising -- not just a fixed-worker-count problem).
    """
    # Get pytest-xdist worker ID (e.g., "gw0", "gw1", etc.) and total worker
    # count. pytest-xdist (this repo pins >=3.0, locked at 3.8.0) sets both
    # PYTEST_XDIST_WORKER and PYTEST_XDIST_WORKER_COUNT together in the same
    # code path (xdist/remote.py's setup_config), so if one is present so is
    # the other; both default to the single-process case (gw0 of 1 worker)
    # when running outside xdist.
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    worker_num = int(worker_id.replace("gw", "")) if worker_id.startswith("gw") else 0
    worker_count = int(os.environ.get("PYTEST_XDIST_WORKER_COUNT", "1"))

    # Use a sequential counter within this worker's address space
    if not hasattr(allocate_worker_subnet, "_counter"):
        allocate_worker_subnet._counter = 0

    counter = allocate_worker_subnet._counter
    allocate_worker_subnet._counter += 1

    if prefix == 24:
        # 128 third-octet values (172.27.0.0/24 .. 172.27.127.0/24) split
        # evenly across worker_count workers. At worker_count=4 this
        # reproduces the exact previous scheme (32 blocks/worker) --
        # verified directly, not assumed.
        blocks_per_worker = 128 // worker_count
        if counter >= blocks_per_worker:
            raise RuntimeError(
                f"Worker {worker_id} exhausted /24 address space "
                f"(counter={counter}, {blocks_per_worker} blocks/worker at worker_count={worker_count})"
            )
        third_octet = worker_num * blocks_per_worker + counter
        cidr = f"172.27.{third_octet}.0/24"
    elif prefix == 30:
        # Same 128-value split applied to the upper half's third octet
        # (172.27.128.0 .. 172.27.255.255), each third octet holding 64
        # /30 blocks. At worker_count=4 this reproduces the exact previous
        # scheme (32 third octets/worker, 2048 /30 blocks/worker).
        third_octets_per_worker = 128 // worker_count
        blocks_per_worker = third_octets_per_worker * 64
        if counter >= blocks_per_worker:
            raise RuntimeError(
                f"Worker {worker_id} exhausted /30 address space "
                f"(counter={counter}, {blocks_per_worker} blocks/worker at worker_count={worker_count})"
            )
        third_octet = 128 + worker_num * third_octets_per_worker + (counter // 64)
        fourth_octet = (counter % 64) * 4
        cidr = f"172.27.{third_octet}.{fourth_octet}/30"
    else:
        raise NotImplementedError(f"Prefix /{prefix} not supported")

    return ipaddress.IPv4Network(cidr)


def pool_status(private_grpc: GRPCClient, pool_id: str) -> dict[str, Any]:
    pool = private_grpc.get_external_ip_pool(pool_id=pool_id)
    raw = pool["object"]["status"]
    return {
        "total": int(raw.get("total", 0)),
        "allocated": int(raw.get("allocated", 0)),
        "available": int(raw.get("available", 0)),
    }


def create_ip(
    grpc: GRPCClient, k8s: K8sClient, pool_id: str
) -> tuple[str, str]:
    ip_name: str = f"test-ip-{uuid4().hex[:8]}"
    ip_id: str = grpc.create_external_ip(name=ip_name, pool=pool_id)
    ip_cr_name: str = wait_for_external_ip_cr(k8s=k8s, uuid=ip_id)
    wait_for_external_ip_allocated(k8s=k8s, name=ip_cr_name)
    return ip_id, ip_cr_name


def delete_ip(grpc: GRPCClient, ip_id: str) -> None:
    grpc.delete_external_ip(external_ip_id=ip_id)
