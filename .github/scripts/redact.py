#!/usr/bin/env python3
"""Replace every secret value found by gitleaks with a literal [REDACTED]
marker across a copy of the scanned logs.

Usage: redact.py <gitleaks-findings.json> <dir-to-redact-in-place>
"""
import json
import pathlib
import sys


def main() -> None:
    """Redact every finding's secret value in-place across redacted_dir."""
    findings_path, redacted_dir = sys.argv[1], sys.argv[2]
    findings = json.loads(pathlib.Path(findings_path).read_text() or "[]")
    # Longest first: if one finding's secret happens to be a substring of
    # another's (e.g. a truncated token vs. the full one), redacting the
    # shorter one first would leave a partial fragment of the longer one
    # behind in the "redacted" output.
    secrets = sorted(
        {f["Secret"] for f in findings if f.get("Secret")},
        key=len,
        reverse=True,
    )

    for path in pathlib.Path(redacted_dir).rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError as exc:
            # Fail loudly, don't silently skip: this directory gets uploaded
            # as an artifact afterwards, so a file we couldn't read (and
            # therefore couldn't redact) would ship with its original,
            # un-redacted secret still in it if we just moved on.
            print(f"redact.py: cannot read {path}, aborting: {exc}", file=sys.stderr)
            sys.exit(1)
        changed = False
        for secret in secrets:
            if secret and secret in text:
                text = text.replace(secret, "[REDACTED]")
                changed = True
        if changed:
            path.write_text(text)


if __name__ == "__main__":
    main()
