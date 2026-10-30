"""Resolve exact installed versions into reviewable runtime and development locks.

Run only after pip install -e '.[dev]'. Produces version locks (not wheel hashes).
The runtime graph includes the binary Psycopg extra and active platform markers;
Windows-only harmless dependencies are included for cross-platform installs.
"""

from importlib.metadata import distribution, distributions
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

roots = [
    "fastapi",
    "uvicorn",
    "pyarrow",
    "duckdb",
    "psycopg[binary]",
    "filelock",
    "prometheus-client",
]
seen = set()
versions = {}


def visit(raw):
    requirement = Requirement(raw)
    name = canonicalize_name(requirement.name)
    extras = tuple(sorted(requirement.extras))
    if (name, extras) in seen:
        return
    seen.add((name, extras))
    package = distribution(name)
    versions[name] = package.version
    for dependency in package.requires or []:
        child = Requirement(dependency)
        if child.marker is None or any(
            child.marker.evaluate({"extra": extra}) for extra in ["", *extras]
        ):
            visit(dependency)


for root in roots:
    visit(root)
header = "# Generated from the verified Python 3.12 environment by scripts/lock.py\n"
Path("requirements.lock").write_text(
    header + "".join(f"{name}=={version}\n" for name, version in sorted(versions.items()))
)
dev = {}
for package in distributions():
    name = canonicalize_name(package.metadata["Name"])
    if name not in {"fluxlake", "pip", "setuptools"}:
        dev[name] = package.version
Path("requirements-dev.lock").write_text(
    header + "".join(f"{name}=={version}\n" for name, version in sorted(dev.items()))
)

# A minimal, fully pinned test harness for the Python 3.15 container verification target.
seen.clear()
versions.clear()
for root in ("pytest", "httpx"):
    visit(root)
Path("requirements-test.lock").write_text(
    header + "".join(f"{name}=={version}\n" for name, version in sorted(versions.items()))
)
