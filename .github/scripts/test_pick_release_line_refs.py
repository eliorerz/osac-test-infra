#!/usr/bin/env python3
"""Tests for the pick-release-line-refs action: which osac refs the tests and installer come from.

Focus: a chart X.Y.Z or X.Y.Z-rc.N maps to release-X.Y when that branch exists and to main when it does not, and a
failed branch lookup is never mistaken for a missing branch (that would test a release chart with main's content).
The shell of the step runs here with stand-ins for `git` and `sleep` that answer from the environment.

Run directly: python3 .github/scripts/test_pick_release_line_refs.py
Stdlib unittest only.
"""
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ACTION = Path(__file__).resolve().parents[1] / "actions" / "pick-release-line-refs" / "action.yml"

GIT = r"""#!/bin/bash
echo "git $*" >> "$GIT_LOG"
if [ "$1" = ls-remote ]; then
  [ -n "$LS_ERR" ] && echo "$LS_ERR" >&2
  exit "${LS_RC:-0}"
fi
if [ "$1" = init ]; then mkdir -p "$2"; exit 0; fi
if [ "$1" = -C ]; then
  dir="$2"; shift 2
  case "$1" in
    checkout) mkdir -p "$dir/tests"; echo release > "$dir/tests/marker" ;;
    rev-parse) echo 0123456789abcdef0123456789abcdef01234567 ;;
  esac
  exit 0
fi
exit 0
"""

SLEEP = "#!/bin/bash\necho \"sleep $*\" >> \"$GIT_LOG\"\n"


def step_script() -> str:
    """The `run` block of the step with id "pick", as text (no YAML parser needed)."""
    lines = ACTION.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "- id: pick")
    run = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[run + 1]) - len(lines[run + 1].lstrip())
    block: list[str] = []
    for line in lines[run + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        block.append(line[indent:] if line.strip() else "")
    return "\n".join(block)


def run(
    *, version: str, test_ref: str = "auto", installer_ref: str = "auto", ls_rc: int = 0, ls_err: str = ""
) -> subprocess.CompletedProcess[str]:
    """Run the step for a chart version, with `git ls-remote` answering the given status."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work"
        (work / "tests").mkdir(parents=True)
        (work / "tests" / "marker").write_text("main", encoding="utf-8")
        for name, body in (("git", GIT), ("sleep", SLEEP)):
            fake = Path(tmp) / name
            fake.write_text(body, encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        out = Path(tmp) / "output"
        out.write_text("", encoding="utf-8")
        env = {
            **os.environ,
            "PATH": f"{tmp}:{os.environ['PATH']}",
            "RUNNER_TEMP": tmp,
            "GITHUB_OUTPUT": str(out),
            "GITHUB_STEP_SUMMARY": str(Path(tmp) / "summary"),
            "GIT_LOG": str(Path(tmp) / "git.log"),
            "CHART_VERSION": version,
            "TEST_REF_INPUT": test_ref,
            "INSTALLER_REF_INPUT": installer_ref,
            "TEST_REPOSITORY": "osac-project/osac",
            "INSTALLER_REPO": "osac-project/osac",
            "LS_RC": str(ls_rc),
            "LS_ERR": ls_err,
        }
        done = subprocess.run(
            ["bash", "-e", "-c", step_script()], cwd=work, env=env, capture_output=True, text=True, check=False
        )
        outputs: dict[str, str] = {}
        for line in out.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            outputs[key] = value
        log = Path(tmp) / "git.log"
        done.outputs = outputs  # type: ignore[attr-defined]
        done.calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []  # type: ignore[attr-defined]
        done.marker = (work / "tests" / "marker").read_text(encoding="utf-8")  # type: ignore[attr-defined]
        return done


def lookups(done: subprocess.CompletedProcess[str]) -> int:
    return sum(1 for call in done.calls if call.startswith("git ls-remote"))  # type: ignore[attr-defined]


class PickReleaseLineRefs(unittest.TestCase):
    """Which refs a chart version selects."""

    def test_the_step_is_found(self) -> None:
        """The shell of the step can be read from the action."""
        self.assertIn("branch_exists", step_script())

    def test_a_release_chart_selects_its_release_branch_and_its_tests(self) -> None:
        """0.4.0 and 0.4.0-rc.5 with release-0.4 present: both refs, and tests/ is replaced."""
        for version in ("0.4.0", "0.4.0-rc.5", "12.3.4-rc.10"):
            done = run(version=version)
            line = "release-" + ".".join(version.split(".")[:2])
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertEqual(done.outputs["test-ref"], line)  # type: ignore[attr-defined]
            self.assertEqual(done.outputs["installer-ref"], line)  # type: ignore[attr-defined]
            self.assertEqual(done.outputs["test-sha"], "0123456789abcdef0123456789abcdef01234567")  # type: ignore[attr-defined]
            self.assertEqual(done.marker, "release\n")  # type: ignore[attr-defined]

    def test_a_missing_release_branch_falls_back_to_main(self) -> None:
        """Status 2 is git's "no such ref": main, tests/ untouched, no retry."""
        done = run(version="0.5.0-rc.1", ls_rc=2)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(done.outputs["test-ref"], "main")  # type: ignore[attr-defined]
        self.assertEqual(done.outputs["installer-ref"], "main")  # type: ignore[attr-defined]
        self.assertEqual(done.outputs["test-sha"], "")  # type: ignore[attr-defined]
        self.assertEqual(done.marker, "main")  # type: ignore[attr-defined]
        self.assertEqual(lookups(done), 2)  # one per repository, no retries

    def test_a_failed_lookup_fails_the_job_instead_of_selecting_main(self) -> None:
        """Any status but 2 is retried and then fails, keeping git's own message; no refs are written."""
        for status in (1, 128):
            done = run(version="0.4.0-rc.5", ls_rc=status, ls_err="fatal: unable to access github.com")
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("unable to access github.com", done.stderr)
            self.assertIn(f"status {status}", done.stderr)
            self.assertEqual(lookups(done), 3)  # three attempts
            self.assertNotIn("installer-ref", done.outputs)  # type: ignore[attr-defined]
            self.assertEqual(done.marker, "main")  # type: ignore[attr-defined]

    def test_versions_without_a_release_line_select_main_without_a_lookup(self) -> None:
        """Nightly, other schemes and anything malformed: main, and git is not asked."""
        for version in ("0.0.150", "weird", "", "0.4", "0.4.0-nightly.3", "v0.4.0", "0.4.0;x"):
            done = run(version=version) if version != "0.0.150" else run(version=version, ls_rc=2)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertEqual(done.outputs["test-ref"], "main")  # type: ignore[attr-defined]
            if version != "0.0.150":
                self.assertEqual(lookups(done), 0)

    def test_explicit_refs_are_kept_as_given(self) -> None:
        """Only "auto" is derived; an explicit ref is neither looked up nor overlaid."""
        done = run(version="0.4.0-rc.5", test_ref="feature-x", installer_ref="main")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(done.outputs["test-ref"], "feature-x")  # type: ignore[attr-defined]
        self.assertEqual(done.outputs["installer-ref"], "main")  # type: ignore[attr-defined]
        self.assertEqual(lookups(done), 0)
        self.assertEqual(done.marker, "main")  # type: ignore[attr-defined]

    def test_a_mix_derives_only_the_auto_side(self) -> None:
        """Explicit tests with an auto installer: tests kept, installer derived."""
        done = run(version="0.4.0", test_ref="feature-x")
        self.assertEqual(done.outputs["test-ref"], "feature-x")  # type: ignore[attr-defined]
        self.assertEqual(done.outputs["installer-ref"], "release-0.4")  # type: ignore[attr-defined]
        self.assertEqual(done.marker, "main")  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
