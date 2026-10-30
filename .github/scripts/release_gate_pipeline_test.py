#!/usr/bin/env python3
"""The collect, teardown, upload sequence of a CaaS job (run: python3 .github/scripts/release_gate_pipeline_test.py).

Teardown deletes RUNNER_TEMP/pull-secret.json and the registry auth files before the
upload action runs, so the release gate can only know those secrets if the collection
step saved a copy first. This runs the real collect-artifacts.sh against a stubbed `oc`,
deletes the secret files the way teardown.sh does, then runs the real "Release gate" step
of the upload-artifacts action.

The canary is a bare token in a ClusterOrder annotation. No shape rule can match that,
so only the known-value layer can censor it; if the snapshot is missing the token is
published. Set RELEASE_GATE_REPO_ROOT to run the same test against another checkout.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(os.environ.get("RELEASE_GATE_REPO_ROOT") or pathlib.Path(__file__).resolve().parents[2])

# Synthetic; not a credential.
USER = "robot+pipeline_access_00000000feedface"
TOKEN = "PIPELINEtokenPIPELINEtoken0123456789abcdefPIPELINEtokenPIPELINE012"
AUTH = base64.b64encode(f"{USER}:{TOKEN}".encode()).decode()
PULL_SECRET = {"auths": {"quay.io": {"auth": AUTH, "email": "pipeline@example.com"}}}

OC_STUB = """#!/bin/bash
case "$*" in
  *"get clusterorders"*"-o json"*) cat "$FIXTURES/clusterorders.json" ;;
  *"get secrets"*) echo '{"items": []}' ;;
  *"get route osac-aap"*) printf 'aap.pipeline.test' ;;
  *"get secret osac-aap-controller-admin-password"*) printf 'cGlwZWxpbmU=' ;;
esac
exit 0
"""
CURL_STUB = """#!/bin/bash
for last; do :; done
case "$last" in
  *"/jobs/?page="*) echo '{"count": 0, "next": null, "results": []}' ;;
  *"project_updates"*) echo '{"results": []}' ;;
esac
exit 0
"""


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def step_script(action_yml: pathlib.Path, step_name: str) -> str:
    """The `run: |` block of one composite-action step, without needing a YAML parser."""
    lines = action_yml.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f"- name: {step_name}")
    run = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[run]) - len(lines[run].lstrip()) + 2
    block = []
    for line in lines[run + 1:]:
        if line.strip() and not line.startswith(" " * indent):
            break
        block.append(line[indent:] if line.strip() else "")
    script = "\n".join(block)
    _assert("release_gate.py" in script, f"could not extract the {step_name!r} step from {action_yml.name}")
    return script


def contains_canary(root: pathlib.Path) -> list[str]:
    needles = [TOKEN.encode(), AUTH.encode()]
    for pad in range(3):
        needles.append(base64.b64encode(b"\0" * pad + TOKEN.encode())[4:-4])
    return [str(p.relative_to(root)) for p in sorted(root.rglob("*"))
            if p.is_file() and any(n in p.read_bytes() for n in needles)]


def main() -> None:
    _assert(shutil.which("jq") is not None, "jq is required to run the collector")
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        runner_temp = base / "runner-temp"
        runner_temp.mkdir()
        (base / "bin").mkdir()
        for name, body in (("oc", OC_STUB), ("curl", CURL_STUB)):
            (base / "bin" / name).write_text(body)
            (base / "bin" / name).chmod(0o755)
        (base / "bin" / "kubectl").symlink_to("oc")
        (base / "kubeconfig").write_text("")
        fixtures = base / "fixtures"
        fixtures.mkdir()
        order = {"metadata": {"name": "co1", "annotations": {"note": f"debug dump {TOKEN} end"}}, "spec": {"releaseImage": "x"}}
        (fixtures / "clusterorders.json").write_text(json.dumps({"items": [order]}))

        # What the workflow's "Write pull secret and registry auth" step leaves behind.
        (runner_temp / "pull-secret.json").write_text(json.dumps(PULL_SECRET))
        (runner_temp / "auth.json").write_text(json.dumps({"auths": {}}))  # legitimately empty

        env = {**os.environ, "PATH": f"{base / 'bin'}{os.pathsep}{os.environ['PATH']}", "FIXTURES": str(fixtures),
               "KUBECONFIG": str(base / "kubeconfig"), "RUNNER_TEMP": str(runner_temp),
               "GITHUB_WORKSPACE": str(REPO), "E2E_NAMESPACE": "osac-e2e-ci"}

        # 1. collect-artifacts.sh, while the secret files still exist.
        done = subprocess.run(["bash", str(REPO / ".github/scripts/collect-artifacts.sh")], cwd=REPO, env=env,
                              capture_output=True, text=True, timeout=300, check=False)
        _assert(done.returncode == 0, f"collection failed: {done.stderr[-300:]}")
        artifacts = runner_temp / "osac-artifacts"
        _assert((artifacts / ".redaction-complete").exists(), "collection did not complete")
        _assert(contains_canary(artifacts), "the collector did not write the canary; the test is not exercising anything")
        print("collected; canary is in:", ", ".join(contains_canary(artifacts)))

        # 2. Teardown (teardown.sh) removes the originals.
        for name in ("pull-secret.json", "auth.json"):
            (runner_temp / name).unlink()

        # 3. the upload action's release gate step.
        script = step_script(REPO / ".github/actions/upload-artifacts/action.yml", "Release gate - censor secrets")
        script = script.replace("${{ github.workspace }}", str(REPO))
        gate_env = {**env, "ARTIFACT_DIR": str(artifacts), "KNOWN_SECRET_FILES": "", "KNOWN_SECRET_ENV": "",
                    "K8S_SECRETS_FILE": "", "FAIL_ON_CENSOR": "false"}
        result = subprocess.run(["bash", "-c", script], env=gate_env, capture_output=True, text=True, timeout=300, check=False)
        print(result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "(no output)")
        _assert(result.returncode == 0, f"the gate step failed ({result.returncode}): {result.stdout[-300:]}{result.stderr[-300:]}")
        _assert(artifacts.is_dir(), "the artifact directory was removed; an empty auth file must not abort the upload")
        _assert(not contains_canary(artifacts),
                f"canary survived the gate: {contains_canary(artifacts)}\ngate output:\n{result.stdout}{result.stderr}")
        report = json.loads((artifacts / "redaction-report.json").read_text())
        rules = {c["rule"].split(":")[0] for c in report["censored"]}
        _assert("known-value" in rules, f"the known-value layer did not act (rules: {rules}, inventory: {report['inventory']})")
        _assert(any(s["source"] == "pull-secret.json" and s["values"] > 0 for s in report["inventory"]),
                f"the pull secret was not in the inventory: {report['inventory']}")
        _assert(not (runner_temp / "osac-secret-inventory").exists(), "the snapshots were left on the runner")
        print("release_gate_pipeline_test.py: ok")


if __name__ == "__main__":
    main()
