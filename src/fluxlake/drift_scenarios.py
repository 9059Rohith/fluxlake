"""Seeded synthetic calibration experiments for the same production effect rules.

The generator deliberately samples independent synthetic events. This is a useful
controlled experiment, not a model of correlated operational CDC traffic.
"""

from __future__ import annotations

import hashlib
import math
import platform
import random
from typing import Literal

from fluxlake.drift import compare_events
from fluxlake.drift_contracts import CompareRequest, EvidenceEvent
from fluxlake.lake import canonical

SCENARIOS = ("no_shift", "amount_shift", "currency_mix")
Scenario = Literal["no_shift", "amount_shift", "currency_mix"]


def _bounds(seed: int, samples: int):
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("Seed must be an integer between 0 and 2**32-1")
    if type(samples) is not int or not 200 <= samples <= 2000:
        raise ValueError("Samples must be an integer between 200 and 2000 per window")


def generate_scenario(
    scenario: Scenario, seed: int = 20261030, samples: int = 400
) -> tuple[CompareRequest, list[EvidenceEvent], list[EvidenceEvent]]:
    _bounds(seed, samples)
    if scenario not in SCENARIOS:
        raise ValueError("Unknown synthetic scenario")
    rng = random.Random(seed)
    request = CompareRequest.model_validate(
        {
            "baseline": {"start": 1, "end": samples},
            "candidate": {"start": samples + 1, "end": samples * 2},
        }
    )

    def sample(start: int, candidate: bool):
        events = []
        usd_probability = 0.15 if candidate and scenario == "currency_mix" else 0.65
        multiplier = 2.5 if candidate and scenario == "amount_shift" else 1
        for offset in range(samples):
            currency = "USD" if rng.random() < usd_probability else "INR"
            # Same conditional distribution by currency for no_shift/currency_mix.
            base = rng.lognormvariate(math.log(1000), 0.4)
            amount = max(1, round(base * (1 if currency == "USD" else 70) * multiplier))
            status_draw = rng.random()
            status = (
                "settled" if status_draw < 0.75 else ("pending" if status_draw < 0.95 else "failed")
            )
            index = start + offset
            payload = {
                "amount_minor": amount,
                "currency": currency,
                "status": status,
                "synthetic": True,
            }
            events.append(
                EvidenceEvent(
                    index=index,
                    event_id=f"00000000-0000-0000-0000-{index:012d}",
                    key=f"synthetic-{index}",
                    version=1,
                    operation="insert",
                    occurred_at="2026-10-30T00:00:00+00:00",
                    amount_minor=amount,
                    currency=currency,
                    status=status,
                    payload_sha256=hashlib.sha256(canonical(payload)).hexdigest(),
                )
            )
        return events

    return request, sample(1, False), sample(samples + 1, True)


def wilson_interval(successes: int, trials: int) -> tuple[float, float]:
    """95% Wilson interval for a measured Bernoulli trial rate, not source inference."""
    if (
        type(trials) is not int
        or type(successes) is not int
        or not 0 <= successes <= trials
        or trials < 1
    ):
        raise ValueError("Expected 0 <= successes <= positive trials")
    z = 1.959963984540054
    rate = successes / trials
    denominator = 1 + z * z / trials
    center = (rate + z * z / (2 * trials)) / denominator
    half = z * math.sqrt(rate * (1 - rate) / trials + z * z / (4 * trials * trials)) / denominator
    return max(0.0, center - half), min(1.0, center + half)


def evaluate(seed: int = 20261030, trials: int = 60, samples: int = 400) -> dict:
    _bounds(seed, samples)
    if type(trials) is not int or not 1 <= trials <= 100:
        raise ValueError("Trials must be an integer between 1 and 100")
    results = {}
    for scenario in SCENARIOS:
        observations = []
        for trial in range(trials):
            trial_seed = (seed + trial * 104729) % 2**32
            request, left, right = generate_scenario(scenario, trial_seed, samples)
            report = compare_events(request, left, right)
            amount = any(group.amount_effect_detected for group in report.currencies)
            status = any(group.status_effect_detected for group in report.currencies)
            mix = report.currency_mix.effect_detected
            target = (
                amount
                if scenario == "amount_shift"
                else (
                    mix if scenario == "currency_mix" else report.disposition == "effect_detected"
                )
            )
            observations.append(
                {
                    "trial": trial,
                    "seed": trial_seed,
                    "fingerprint": report.fingerprint,
                    "alarm": report.disposition == "effect_detected",
                    "target_detected": target,
                    "amount_alarm": amount,
                    "status_alarm": status,
                    "currency_mix_alarm": mix,
                    "insufficient_currency_groups": sum(
                        not group.sufficient_samples for group in report.currencies
                    ),
                }
            )
        alarms = sum(observation["alarm"] for observation in observations)
        target_detections = sum(observation["target_detected"] for observation in observations)
        results[scenario] = {
            "alarm_count": alarms,
            "alarm_rate": alarms / trials,
            "alarm_rate_wilson95": wilson_interval(alarms, trials),
            "target_detection_count": target_detections,
            "target_detection_rate": target_detections / trials,
            "target_detection_rate_wilson95": wilson_interval(target_detections, trials),
            "metric_alarm_counts": {
                metric: sum(observation[metric] for observation in observations)
                for metric in ("amount_alarm", "status_alarm", "currency_mix_alarm")
            },
            "trials": observations,
        }
    return {
        "synthetic": True,
        "generator": "fluxlake-lognormal-events-v1",
        "algorithm": "fluxlake-drift-v1",
        "python": platform.python_version(),
        "seed": seed,
        "trials_per_scenario": trials,
        "samples_per_window": samples,
        "policy": request.policy.model_dump(),
        "distribution": {
            "baseline": "USD probability .65; amount lognormal(log(1000),.4), INR scaled by 70",
            "status": "settled .75, pending .20, failed .05, unchanged across all scenarios",
            "no_shift": "Independent draws from identical conditional laws and currency mix",
            "amount_shift": "Candidate amount multiplier 2.5 in each currency; unchanged mix",
            "currency_mix": "Candidate USD probability .15; unchanged conditional amount/status laws",
        },
        "caveat": "Independent synthetic trials; no source population or production accuracy guarantee. "
        "No-shift alarm rate is the observed false-positive rate for this generator and "
        "policy; target detection means amount alarm or currency-mix alarm respectively. "
        "Wilson intervals quantify Monte Carlo trial-rate uncertainty, not CDC significance. "
        "Finite samples can trigger unrelated metrics; all metric alarms are retained.",
        "scenarios": results,
    }
