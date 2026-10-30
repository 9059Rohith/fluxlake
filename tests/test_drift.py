import math

import pytest
from pydantic import ValidationError


def record(index, amount=10, currency="USD", status="settled", operation="insert", key=None):
    from fluxlake.drift_contracts import EvidenceEvent

    return EvidenceEvent(
        index=index,
        event_id=f"00000000-0000-0000-0000-{index:012d}",
        key=key or f"tx-{index}",
        version=1,
        operation=operation,
        occurred_at="2026-10-30T00:00:00+00:00",
        amount_minor=amount,
        currency=currency,
        status=status,
        payload_sha256="a" * 64,
    )


def request(**policy):
    from fluxlake.drift_contracts import CompareRequest

    return CompareRequest.model_validate(
        {
            "baseline": {"start": 1, "end": 100},
            "candidate": {"start": 101, "end": 200},
            "policy": {"min_samples": 10, **policy},
        }
    )


def test_ks_tied_ecdf_reference_and_bigint_precision():
    from fluxlake.drift import ks_distance

    assert ks_distance([1, 1, 2, 3], [1, 2, 2, 4]) == 0.25
    assert ks_distance([2, 2], [2, 2]) == 0
    assert ks_distance([2**63 - 2], [2**63 - 1]) == 1
    assert ks_distance([1, 3], [2]) == 0.5


def test_js_is_divergence_not_distance_and_handles_zero_cells():
    from fluxlake.drift import js_divergence

    assert js_divergence({"a": 1}, {"b": 1}) == 1
    assert js_divergence({"a": 10}, {"a": 20}) == 0
    # P=(1,0), Q=(1/2,1/2): 0.5 log2(4/3)+0.25 log2(2/3)+0.25.
    assert js_divergence({"a": 2}, {"a": 1, "b": 1}) == pytest.approx(0.3112781244591328)


def test_psi_uses_fixed_baseline_bins_smoothing_and_explicit_tails():
    from fluxlake.drift import amount_effects

    effects = amount_effects([10, 10], [20, 20], bins=5, smoothing=0.5)
    assert effects.bin_cuts == (10,)
    assert effects.baseline_counts == (0, 2, 0)
    assert effects.candidate_counts == (0, 0, 2)
    assert effects.psi == pytest.approx(8 / 7 * math.log(5))
    assert effects.ks_distance == 1
    assert amount_effects([10, 10], [10, 10], 5, 0.5).psi == 0


@pytest.mark.parametrize("values", [[], [True], [float("nan")], [float("inf")], [-1], [1.0]])
def test_numeric_statistics_fail_closed_for_invalid_minor_units(values):
    from fluxlake.drift import ks_distance

    with pytest.raises(ValueError):
        ks_distance(values, [1])


@pytest.mark.parametrize(
    "change",
    [
        {"baseline": {"start": True, "end": 100}},
        {"baseline": {"start": "1", "end": 100}},
        {"baseline": {"start": 0, "end": 100}},
        {"baseline": {"start": 1, "end": 2001}},
        {"candidate": {"start": 100, "end": 200}},
        {"policy": {"ks_threshold": float("nan")}},
        {"policy": {"smoothing": 0}},
        {"policy": {"min_samples": 1}},
        {"sql": "select anything"},
    ],
)
def test_request_rejects_coercion_overlap_unbounded_and_unknown_fields(change):
    from fluxlake.drift_contracts import CompareRequest

    payload = {
        "baseline": {"start": 1, "end": 100},
        "candidate": {"start": 101, "end": 200},
        **change,
    }
    with pytest.raises(ValidationError):
        CompareRequest.model_validate(payload)


def test_report_is_immutable_reproducible_and_currency_isolated():
    from fluxlake.drift import compare_events

    baseline = [
        record(i, 10 if i <= 50 else 1000, "USD" if i <= 50 else "INR") for i in range(1, 101)
    ]
    candidate = [
        record(i, 10 if i <= 120 else 1000, "USD" if i <= 120 else "INR") for i in range(101, 201)
    ]
    report = compare_events(request(), baseline, candidate)
    assert report.currency_mix.js_divergence > 0.05
    assert report.currency_mix.effect_detected
    # Count pseudocount smoothing gives a small sample-size effect for unequal n.
    assert all(
        item.amount.ks_distance == 0 and item.amount.psi < 0.03 for item in report.currencies
    )
    assert report.disposition == "effect_detected"
    assert report.fingerprint == compare_events(request(), baseline[::-1], candidate).fingerprint
    assert report.baseline.evidence_sha256 != report.candidate.evidence_sha256
    assert "p_value" not in report.model_dump_json()
    with pytest.raises(ValidationError):
        report.disposition = "no_effect_detected"


def test_low_samples_delete_gaps_repeated_keys_and_empty_currency_are_explicit():
    from fluxlake.drift import compare_events

    baseline = [record(1), record(3, operation="delete"), record(4, key="tx-1")]
    report = compare_events(request(), baseline, [record(101, 999, currency="EUR")])
    assert report.baseline.observed_rows == 3
    assert report.baseline.missing_identity_positions == 97
    assert report.baseline.tombstones == 1
    assert report.baseline.distinct_keys == 1
    assert report.baseline.repeated_key_events == 1
    assert report.disposition == "insufficient_samples"
    assert all(not group.sufficient_samples for group in report.currencies)
    assert all(group.amount is None and group.status is None for group in report.currencies)


def test_engine_rejects_duplicate_out_of_window_and_excess_currency_evidence():
    from fluxlake.drift import compare_events

    for baseline in (
        [record(1), record(1)],
        [record(101)],
        [record(i + 1, currency="A" + chr(65 + i // 26) + chr(65 + i % 26)) for i in range(33)],
    ):
        with pytest.raises(ValueError):
            compare_events(request(), baseline, [record(101)])


def test_policy_changes_fingerprint_and_effect_decision():
    from fluxlake.drift import compare_events

    baseline = [record(i, 10) for i in range(1, 101)]
    candidate = [record(i, 20) for i in range(101, 201)]
    first = compare_events(request(), baseline, candidate)
    second = compare_events(request(ks_threshold=1.0, psi_threshold=100.0), baseline, candidate)
    assert first.currencies[0].amount_effect_detected
    assert not second.currencies[0].amount_effect_detected
    assert first.fingerprint != second.fingerprint
    assert first.baseline.evidence_sha256 == second.baseline.evidence_sha256


def test_status_effect_requires_minimum_samples_and_does_not_leak_across_currencies():
    from fluxlake.drift import compare_events

    baseline = [record(i, currency="USD" if i <= 10 else "EUR") for i in range(1, 21)]
    candidate = [
        record(i, status="failed", currency="USD" if i <= 110 else "EUR") for i in range(101, 120)
    ]
    report = compare_events(request(), baseline, candidate)
    by_currency = {group.currency: group for group in report.currencies}
    assert by_currency["USD"].status.js_divergence == 1
    assert by_currency["USD"].status_effect_detected
    assert not by_currency["USD"].amount_effect_detected
    assert by_currency["EUR"].status is None
    assert not by_currency["EUR"].status_effect_detected
    assert report.disposition == "effect_detected"


def test_histogram_quantiles_and_right_closed_support_reference():
    from fluxlake.drift import amount_effects, compare_events

    effects = amount_effects([10, 20, 30, 40], [0, 10, 20, 21, 40, 41], 2, 0.5)
    assert effects.bin_cuts == (20, 40)
    assert effects.baseline_counts == (0, 2, 2, 0)
    assert effects.candidate_counts == (1, 2, 2, 1)
    assert effects.baseline.p50_nearest_rank == 20
    assert effects.baseline.p90_nearest_rank == 40
    empty = compare_events(request(), [], [])
    assert empty.disposition == "insufficient_samples"
    assert empty.currency_mix.js_divergence is None
    assert empty.currencies == ()


@pytest.mark.parametrize(
    "left,right",
    [
        ({}, {"a": 1}),
        ({"a": True}, {"a": 1}),
        ({"a": -1}, {"a": 1}),
        ({"a": 0}, {"a": 1}),
        ({"a": float("nan")}, {"a": 1}),
    ],
)
def test_categorical_statistics_reject_invalid_counts(left, right):
    from fluxlake.drift import js_divergence

    with pytest.raises(ValueError):
        js_divergence(left, right)
