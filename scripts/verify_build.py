"""Run the offline release checks and write a receipt only after they pass."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


def read_junit(path):
    """Count actual cases; refuse failed, empty or inconsistent reports."""
    document = path.read_bytes()
    if b"<!DOCTYPE" in document or b"<!ENTITY" in document:
        raise ValueError("DTD declarations are not permitted in test reports")
    root = ET.fromstring(document)
    cases = list(root.iter("testcase"))
    result = {
        "total": len(cases),
        "passed": 0,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "skips": [],
    }
    for case in cases:
        if case.find("failure") is not None:
            result["failures"] += 1
        elif case.find("error") is not None:
            result["errors"] += 1
        elif (skipped := case.find("skipped")) is not None:
            result["skipped"] += 1
            result["skips"].append(
                {
                    "test": ".".join(filter(None, [case.get("classname"), case.get("name")])),
                    "reason": skipped.get("message", ""),
                }
            )
        else:
            result["passed"] += 1
    suites = [suite for suite in root.iter("testsuite") if suite.find("testsuite") is None]
    reported = sum(int(suite.get("tests", "0")) for suite in suites)
    if reported != len(cases) or not result["passed"] or result["failures"] or result["errors"]:
        raise ValueError("test report is failing, empty, all skipped or inconsistent")
    return result


def fingerprint(root, inputs):
    """Hash names and bytes of the exact source, tests and locks in this build."""
    files = []
    for path in inputs:
        if path.is_dir():
            files.extend(
                p
                for p in path.rglob("*")
                if p.is_file()
                and "__pycache__" not in p.parts
                and p.suffix != ".pyc"
                and not any(part.endswith(".egg-info") for part in p.parts)
            )
        elif path.is_file():
            files.append(path)
    if not files:
        raise ValueError("fingerprint input is empty")
    digest = hashlib.sha256()
    for path in sorted(set(files), key=lambda item: item.relative_to(root).as_posix()):
        name = path.relative_to(root).as_posix().encode()
        payload = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big") + name)
        digest.update(len(payload).to_bytes(8, "big") + payload)
    return {"sha256": digest.hexdigest(), "files": len(set(files))}


def run_gate(root, output):
    output.unlink(missing_ok=True)
    # Subprocesses cannot inherit database/provider credentials or opt-in flags.
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "PYTHONPATH"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    lint = [sys.executable, "-m", "ruff", "check", "src", "scripts/verify_build.py"]
    subprocess.run(lint, cwd=root, env=environment, check=True)
    with tempfile.TemporaryDirectory(prefix="fluxlake-verification-") as temporary:
        report = Path(temporary) / "junit.xml"
        tests = [sys.executable, "-m", "pytest", "-q", "--tb=short", "-rs", f"--junitxml={report}"]
        subprocess.run(tests, cwd=root, env=environment, check=True)
        counts = read_junit(report)
    receipt = {
        "schema_version": 1,
        "project": "fluxlake",
        "gate": "offline-release-build",
        "status": "passed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "checks": ["ruff check src scripts/verify_build.py", "pytest (full default suite)"],
        "pytest": counts,
        "fingerprints": {
            "source": fingerprint(root, [root / "src", root / "sql", root / "pyproject.toml"]),
            "tests": fingerprint(root, [root / "tests"]),
            "locks": fingerprint(root, list(root.glob("requirements*.lock"))),
            "gate": fingerprint(
                root,
                [
                    root / "scripts" / "verify_build.py",
                    root / "Dockerfile",
                    root / ".dockerignore",
                    root / ".vercelignore",
                ],
            ),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print("BUILD_VERIFICATION_RECEIPT=" + json.dumps(receipt, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_gate(args.root.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
