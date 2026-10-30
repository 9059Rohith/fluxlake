import pytest

from fluxlake.lake import Lake


def event(event_id="e1", version=1, op="insert", key="tx1", **attrs):
    return {
        "event_id": event_id,
        "key": key,
        "version": version,
        "op": op,
        "occurred_at": "2026-10-30T10:00:00+00:00",
        "data": {"amount_minor": 12500, "currency": "USD", "status": "settled", **attrs},
    }


def test_insert_update_delete_stale_and_duplicate(tmp_path):
    lake = Lake(tmp_path)
    assert lake.apply([event()]) == {"applied": 1, "duplicate": 0, "stale": 0, "quarantined": 0}
    assert lake.apply([event()])["duplicate"] == 1
    lake.apply([event("e3", 3, "update", amount_minor=25000)])
    assert lake.apply([event("e2", 2, "update")])["stale"] == 1
    assert lake.current()[0]["amount_minor"] == 25000
    lake.apply([event("e4", 4, "delete")])
    assert lake.current() == []
    lake = Lake(tmp_path)
    assert lake.apply([event("late", 2)])["stale"] == 1
    assert lake.current() == []


def test_collision_equal_version_and_invalid_are_quarantined(tmp_path):
    lake = Lake(tmp_path)
    lake.apply([event()])
    assert lake.apply([event(amount_minor=42)])["quarantined"] == 1
    assert lake.apply([event("conflict", 1, amount_minor=42)])["quarantined"] == 1
    assert (
        lake.apply([event("bad", 2, amount_minor="NaN"), {"unexpected": True}])["quarantined"] == 2
    )
    assert lake.current()[0]["amount_minor"] == 12500
    assert len(list((tmp_path / "bronze").glob("*.json"))) == 5
    assert len(lake.quarantine()) == 4


def test_additive_schema_and_gold_currency_aggregation(tmp_path):
    lake = Lake(tmp_path)
    lake.apply(
        [
            event(region="APAC"),
            event("e2", key="tx2", amount_minor=300),
            event("e3", key="tx3", currency="INR", amount_minor=500),
        ]
    )
    assert lake.current()[0]["attributes"]["region"] == "APAC"
    assert lake.gold() == [
        {"currency": "INR", "transaction_count": 1, "total_minor": 500},
        {"currency": "USD", "transaction_count": 2, "total_minor": 12800},
    ]
    assert "region" in lake.schema()["attributes"]


def test_recover_after_state_commit_before_snapshot(tmp_path, monkeypatch):
    lake = Lake(tmp_path)

    def crash():
        raise OSError("simulated disk interruption")

    monkeypatch.setattr(lake, "_publish", crash)
    with pytest.raises(OSError):
        lake.apply([event()])
    restarted = Lake(tmp_path)
    assert restarted.current()[0]["key"] == "tx1"
    assert restarted.apply([event()])["duplicate"] == 1
    assert restarted.gold()[0]["total_minor"] == 12500


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"version": 0},
        {"op": "truncate"},
        {"key": "../escape"},
        {"occurred_at": "yesterday"},
        {"data": {"amount_minor": -1, "currency": "USD"}},
        {"data": {"amount_minor": True, "currency": "USD", "status": "settled"}},
    ],
)
def test_bad_contract_never_reaches_silver(tmp_path, change):
    lake = Lake(tmp_path)
    record = event()
    record.update(change)
    assert lake.apply([record])["quarantined"] == 1
    assert lake.current() == []


def test_manifest_uses_real_parquet_and_keeps_previous_snapshot(tmp_path):
    import json
    import pyarrow.parquet as pq

    lake = Lake(tmp_path)
    lake.apply([event()])
    manifest = json.loads((tmp_path / "silver" / "manifest.json").read_text())
    first = tmp_path / "silver" / manifest["file"]
    assert pq.read_table(first).to_pylist()[0]["amount_minor"] == 12500
    lake.apply([event("e2", 2, "update", amount_minor=17)])
    assert first.exists()
    assert pq.read_table(first).to_pylist()[0]["amount_minor"] == 12500


def test_attribute_type_drift_is_quarantined_without_changing_schema(tmp_path):
    lake = Lake(tmp_path)
    lake.apply([event(region="APAC")])
    assert lake.apply([event("e2", 2, "update", region=42)])["quarantined"] == 1
    assert lake.schema() == {"attributes": {"region": "str"}}
    assert lake.current()[0]["attributes"]["region"] == "APAC"


def test_empty_delete_tombstone_blocks_older_insert(tmp_path):
    lake = Lake(tmp_path)
    deleted = event("delete-first", 9, "delete")
    deleted["data"] = {}
    lake.apply([deleted])
    assert lake.apply([event("older", 8)])["stale"] == 1
    assert Lake(tmp_path).current() == []


def test_multiple_local_writers_do_not_lose_rows(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    first, second = Lake(tmp_path), Lake(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [
            pool.submit(first.apply, [event("a", key="a")]),
            pool.submit(second.apply, [event("b", key="b")]),
        ]
        for job in jobs:
            assert job.result()["applied"] == 1
    assert [row["key"] for row in first.current()] == ["a", "b"]


def test_bronze_corruption_is_not_overwritten(tmp_path):
    import hashlib
    from fluxlake.lake import canonical

    lake = Lake(tmp_path)
    digest = hashlib.sha256(canonical(event())).hexdigest()
    raw = tmp_path / "bronze" / f"{digest}.json"
    raw.write_text("corrupted")
    with pytest.raises(OSError, match="immutable"):
        lake.apply([event()])
    assert raw.read_text() == "corrupted"
    assert lake.current() == []


@pytest.mark.parametrize(
    "name,value",
    [
        ("key", "other"),
        ("version", 900),
        ("occurred_at", "2025-01-01T00:00:00+00:00"),
        ("attributes", "bad"),
    ],
)
def test_attributes_cannot_override_envelope_fields(tmp_path, name, value):
    lake = Lake(tmp_path)
    record = event()
    record["data"][name] = value
    assert lake.apply([record])["quarantined"] == 1
    assert lake.current() == []


def test_gold_excludes_pending_failed_and_deleted_rows(tmp_path):
    lake = Lake(tmp_path)
    lake.apply(
        [
            event(),
            event("pending", key="p", status="pending"),
            event("failed", key="f", status="failed"),
            event("gone", key="g"),
            event("delete", 2, "delete", key="g"),
        ]
    )
    assert lake.gold() == [{"currency": "USD", "transaction_count": 1, "total_minor": 12500}]


@pytest.mark.parametrize("location", ["attribute", "envelope", "nested_envelope", "envelope_key"])
def test_invalid_utf8_quarantines_before_commit_and_restart(tmp_path, location):
    lake = Lake(tmp_path)
    lake.apply([event(region="APAC")])
    baseline = lake.current()
    bad = event("bad-unicode", 2, "update", region="APAC")
    if location == "attribute":
        bad["data"]["region"] = "\ud800"
    elif location == "envelope":
        bad["ignored_extra"] = "\udc00"
    elif location == "nested_envelope":
        bad["ignored_extra"] = {"nested": ["\ud800"]}
    else:
        bad["\ud800"] = "unsafe key"
    assert lake.apply([bad])["quarantined"] == 1
    assert lake.current() == baseline
    restarted = Lake(tmp_path)
    assert restarted.current() == baseline
    assert len(restarted.quarantine()) == 1
    assert restarted.apply([event("valid-next", 2, "update", region="EMEA")])["applied"] == 1
    assert restarted.current()[0]["attributes"]["region"] == "EMEA"


def test_bronze_directory_sync_failure_keeps_state_uncommitted(tmp_path, monkeypatch):
    import fluxlake.lake as storage

    lake = Lake(tmp_path)
    native = getattr(storage, "fsync_directory", lambda _: None)

    def fail_bronze(path):
        if path == lake.root / "bronze":
            raise OSError("simulated bronze directory sync failure")
        native(path)

    monkeypatch.setattr(storage, "fsync_directory", fail_bronze, raising=False)
    for _ in range(2):
        with pytest.raises(OSError, match="bronze directory"):
            lake.apply([event()])
        assert lake.current() == []
    monkeypatch.setattr(storage, "fsync_directory", native)
    assert Lake(tmp_path).apply([event()])["applied"] == 1


def test_silver_directory_sync_failure_preserves_manifest_until_recovery(tmp_path, monkeypatch):
    import fluxlake.lake as storage

    lake = Lake(tmp_path)
    lake.apply([event()])
    manifest = (tmp_path / "silver" / "manifest.json").read_bytes()
    native = getattr(storage, "fsync_directory", lambda _: None)

    def fail_silver(path):
        if path == lake.root / "silver":
            raise OSError("simulated silver directory sync failure")
        native(path)

    monkeypatch.setattr(storage, "fsync_directory", fail_silver, raising=False)
    with pytest.raises(OSError, match="silver directory"):
        lake.apply([event("e2", 2, "update", amount_minor=999)])
    assert (tmp_path / "silver" / "manifest.json").read_bytes() == manifest
    assert lake.current()[0]["amount_minor"] == 12500
    monkeypatch.setattr(storage, "fsync_directory", native)
    restarted = Lake(tmp_path)
    assert restarted.current()[0]["amount_minor"] == 999
    assert restarted.apply([event("e2", 2, "update", amount_minor=999)])["duplicate"] == 1


def test_valid_multibyte_utf8_attribute_survives_restart(tmp_path):
    lake = Lake(tmp_path)
    assert lake.apply([event(region="東京 🚀")])["applied"] == 1
    assert Lake(tmp_path).current()[0]["attributes"]["region"] == "東京 🚀"


def test_attribute_and_schema_growth_is_bounded_before_state_commit(tmp_path):
    lake = Lake(tmp_path)
    lake.apply([event()])
    too_wide = event("wide", 2, "update", **{f"field{i}": i for i in range(33)})
    assert lake.apply([too_wide])["quarantined"] == 1
    assert lake.current()[0]["version"] == 1
    for batch in range(8):
        lake.apply(
            [event(f"schema-{batch}", key=f"s{batch}", **{f"k{batch}_{i}": i for i in range(32)})]
        )
    assert lake.apply([event("overflow", key="extra", extra_field=1)])["quarantined"] == 1
    assert len(lake.schema()["attributes"]) == 256


def test_synthetic_marker_is_boolean_and_large_strings_are_quarantined(tmp_path):
    lake = Lake(tmp_path)
    assert lake.apply([event(synthetic="true")])["quarantined"] == 1
    assert lake.apply([event("large", region="x" * 5000)])["quarantined"] == 1
    assert lake.current() == []
