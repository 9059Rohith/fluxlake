import pytest


def test_synthetic_evaluation_is_reproducible_and_measures_false_alarms_separately():
    from fluxlake.drift_scenarios import evaluate

    result = evaluate(seed=71, trials=8, samples=300)
    assert result == evaluate(seed=71, trials=8, samples=300)
    assert result["synthetic"] is True
    assert result["scenarios"]["no_shift"]["alarm_rate"] <= 0.25
    assert result["scenarios"]["amount_shift"]["target_detection_rate"] >= 0.875
    assert result["scenarios"]["currency_mix"]["target_detection_rate"] >= 0.875
    assert all(len(value["trials"]) == 8 for value in result["scenarios"].values())
    assert "no source population or production accuracy guarantee" in result["caveat"]


def test_currency_mix_scenario_keeps_conditional_amount_law_and_records_fingerprints():
    from fluxlake.drift_scenarios import generate_scenario
    from fluxlake.drift import compare_events

    req, left, right = generate_scenario("currency_mix", seed=3, samples=1000)
    report = compare_events(req, left, right)
    assert report.currency_mix.effect_detected
    assert not any(group.amount_effect_detected for group in report.currencies)
    assert len(report.fingerprint) == 64
    assert all(event.amount_minor > 0 for event in left + right)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"trials": 0},
        {"trials": 101},
        {"samples": 199},
        {"samples": 2001},
        {"seed": True},
        {"seed": -1},
        {"trials": "10"},
    ],
)
def test_scenario_evaluation_refuses_invalid_or_excessive_work(kwargs):
    from fluxlake.drift_scenarios import evaluate

    with pytest.raises(ValueError):
        evaluate(**kwargs)


def test_wilson_interval_uses_trial_count_and_is_non_degenerate_at_extremes():
    from fluxlake.drift_scenarios import wilson_interval

    assert wilson_interval(0, 10) == pytest.approx((0, 0.2775327998628892))
    assert wilson_interval(10, 10) == pytest.approx((0.7224672001371107, 1))
    assert wilson_interval(5, 10) == pytest.approx((0.236593090512564, 0.763406909487436))
    with pytest.raises(ValueError):
        wilson_interval(1, 0)
