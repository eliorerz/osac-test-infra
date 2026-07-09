#!/usr/bin/env python3
"""Replace every secret value found by gitleaks with a literal [REDACTED]
marker across a copy of the scanned logs.

Usage: redact.py <gitleaks-findings.json> <dir-to-redact-in-place>
"""
import json
import pathlib
import sys


def main() -> None:
    findings_path, redacted_dir = sys.argv[1], sys.argv[2]
    findings = json.loads(pathlib.Path(findings_path).read_text() or "[]")
    secrets = {f["Secret"] for f in findings if f.get("Secret")}

    for path in pathlib.Path(redacted_dir).rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        changed = False
        for secret in secrets:
            if secret and secret in text:
                text = text.replace(secret, "[REDACTED]")
                changed = True
        if changed:
            path.write_text(text)


if __name__ == "__main__":
    main()
