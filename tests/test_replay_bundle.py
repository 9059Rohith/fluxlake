"""Portable audit checks use controlled test inputs, never replacement public data."""

import copy
import hashlib
import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from fluxlake.api import create_app
from fluxlake.workspace import PublicWorkspace, canonical
from test_replay import NOW, RUN, evidence, receipt


def bundle():
    from fluxlake.replay_bundle import create_bundle

    bronze, silver = evidence()
    return create_bundle([receipt()], [bronze], [silver], [], {"id": "1:2:", "captured_at": NOW})


def resign(value):
    value["bundle_sha256"] = hashlib.sha256(
        canonical({key: item for key, item in value.items() if key != "bundle_sha256"})
    ).hexdigest()


def test_bundle_reproduces_normalization_receipts_and_survives_json_roundtrip():
    from fluxlake.replay_bundle import verify_bundle

    exported = bundle()
    before = copy.deepcopy(exported)
    result = verify_bundle(json.loads(json.dumps(exported)))
    assert exported == before
    assert exported["evidence"]["bronze"][0]["raw"]["repo"]["name"] == "test/repo"
    assert result["verification"] == "reproduced"
    assert result["publication_status"] == "consistent"
    assert result["counts"]["retained_events"] == 1


@pytest.mark.parametrize("section", ["bronze", "silver", "runs", "source_snapshot", "report"])
def test_changed_export_fails_manifest_integrity(section):
    from fluxlake.replay_bundle import verify_bundle

    exported = bundle()
    if section in exported["evidence"]:
        exported["evidence"][section][0]["altered"] = True
    else:
        exported[section]["altered"] = True
    with pytest.raises(ValueError, match="fingerprint"):
        verify_bundle(exported)


@pytest.mark.parametrize("change", ["source", "silver", "receipt", "report"])
def test_rehashed_changes_still_fail_independent_report_reconstruction(change):
    from fluxlake.replay_bundle import verify_bundle

    exported = bundle()
    if change == "source":
        exported["evidence"]["bronze"][0]["raw"]["repo"]["name"] = "changed/repo"
    elif change == "silver":
        exported["evidence"]["silver"][0]["repository"] = "changed/repo"
    elif change == "receipt":
        exported["evidence"]["runs"][0]["inserted"] = 2
    else:
        exported["report"]["counts"]["affected_events"] = 2
    resign(exported)
    with pytest.raises(ValueError, match="reconstruction"):
        verify_bundle(exported)


def test_genuine_publication_difference_is_reproduced_instead_of_claiming_consistency():
    from fluxlake.replay_bundle import create_bundle, verify_bundle

    bronze, silver = evidence()
    silver["repository"] = "damaged/repo"
    exported = create_bundle([receipt()], [bronze], [silver], [], {"id": "1:2:"})
    result = verify_bundle(exported)
    assert result["verification"] == "reproduced"
    assert result["publication_status"] == "differences"
    assert result["counts"]["affected_events"] == 1
    assert exported["report"]["events"][0]["differences"] == [
        {"field": "repository", "expected": "test/repo", "actual": "damaged/repo"}
    ]


def test_pin_rejects_fully_recomputed_but_different_evidence():
    from fluxlake.replay_bundle import create_bundle, verify_bundle

    original = bundle()
    bronze, silver = evidence("11")
    replacement = create_bundle([receipt()], [bronze], [silver], [], {"id": "1:2:"})
    with pytest.raises(ValueError, match="expected fingerprint"):
        verify_bundle(replacement, expected_sha256=original["bundle_sha256"])
    assert verify_bundle(original, expected_sha256=original["bundle_sha256"])


@pytest.mark.parametrize("change", ["version", "shape", "capacity", "identity", "private"])
def test_malformed_or_overbudget_exports_are_bounded_and_rejected(change):
    from fluxlake.replay_bundle import verify_bundle

    exported = bundle()
    if change == "version":
        exported["schema_version"] = "unknown"
    elif change == "shape":
        exported["evidence"]["silver"] = {}
    elif change == "capacity":
        exported["evidence"]["bronze"] *= 201
    elif change == "identity":
        exported["evidence"]["silver"][0]["event_id"] = "not-numeric"
    else:
        exported["evidence"]["bronze"][0]["raw"]["public"] = False
    resign(exported)
    with pytest.raises(ValueError):
        verify_bundle(exported)


def test_offline_cli_checks_bytes_duplicate_keys_exit_codes_and_pin(tmp_path):
    exported = bundle()
    path = tmp_path / "public-evidence.json"

    def run(*extra):
        return subprocess.run(
            [sys.executable, "-m", "fluxlake.replay_bundle", str(path), *extra],
            capture_output=True,
            text=True,
            timeout=20,
        )

    path.write_text(json.dumps(exported), encoding="utf-8")
    valid = run("--expected-sha256", exported["bundle_sha256"])
    assert valid.returncode == 0, valid.stderr
    assert json.loads(valid.stdout)["publication_status"] == "consistent"
    assert run("--expected-sha256", "0" * 64).returncode == 2
    # Valid JSON with trailing whitespace must still respect the whole-file byte budget.
    encoded = json.dumps(exported).encode("utf-8")
    path.write_bytes(encoded + b" " * (4 * 1024 * 1024 + 1 - len(encoded)))
    assert run().returncode == 2
    path.write_text('{"schema_version":"one","schema_version":"two"}', encoding="utf-8")
    assert run().returncode == 2
    path.write_text('{"number":NaN}', encoding="utf-8")
    assert run().returncode == 2
    path.write_bytes(b" " * (4 * 1024 * 1024 + 1))
    assert run().returncode == 2
    path.write_text("[" * 2000, encoding="utf-8")
    assert run().returncode == 2


def test_bundle_download_selects_bounded_public_snapshot_and_keeps_mutations_private(
    tmp_path, monkeypatch
):
    exported = None

    def replay(self, run_ids=None, *, bundle=False):
        assert run_ids == [RUN]
        assert bundle is True
        return exported

    monkeypatch.setattr(PublicWorkspace, "replay", replay)
    client = TestClient(create_app(tmp_path))
    missing = client.get("/api/workspace/replay/bundle", params={"run": RUN})
    assert missing.status_code == 404
    exported = bundle()
    response = client.get("/api/workspace/replay/bundle", params={"run": RUN})
    assert response.status_code == 200
    assert response.json()["evidence"]["bronze"][0]["raw"]["id"] == "10"
    assert response.headers["content-disposition"].endswith('"fluxlake-replay-bundle.json"')
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/workspace/replay/bundle?run=invalid").status_code == 422
    assert client.get("/api/workspace/replay/bundle", params={"run": [RUN] * 2}).status_code == 422
    assert client.get("/api/workspace/replay/bundle", params={"run": [RUN] * 3}).status_code == 422
    assert client.post("/api/workspace/ingest").status_code in {401, 503}
