"""Deterministic distribution effects, deliberately without IID significance claims."""

from __future__ import annotations

import hashlib
import math
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Mapping, Sequence

from fluxlake.drift_contracts import (
    MAX_CURRENCIES,
    MAX_INDEX,
    AmountEffects,
    AmountSummary,
    CategoryCount,
    CategoryEffects,
    CompareRequest,
    CurrencyEffects,
    DriftReport,
    EventWindow,
    EvidenceEvent,
    SourceSnapshot,
    WindowEvidence,
)
from fluxlake.lake import canonical

SEMANTICS = (
    "Inclusive identity allocation-index ranges in one source observation; IDs and occurred_at "
    "are not commit order. These are not temporal or commit-complete windows.",
    "Retained visible insert/update event payloads, not current entity population. "
    "Repeated revisions are event-weighted; deletes are excluded and counted.",
    "Gaps can reflect rollback, pruning or invisible commits; completeness is unknown. "
    "Late commits or history edits can change fingerprints on later observations.",
    "Descriptive effects only: strict greater-than thresholds, minimum samples per currency; "
    "no p-values, significance, IID assumption or multiple-test error guarantee.",
    "Amounts remain integer minor units, separated by currency; JS uses log base 2, "
    "PSI uses natural log with a pseudocount in every fixed baseline cell.",
    "Fingerprints identify supplied evidence and analysis configuration; they do not "
    "authenticate source history, prove completeness or provide a tamper-proof audit log.",
)


def _amounts(values: Sequence[int]) -> list[int]:
    if (
        not values
        or len(values) > 2000
        or any(type(value) is not int or not 0 <= value <= MAX_INDEX for value in values)
    ):
        raise ValueError("Expected 1 to 2000 bounded integer minor-unit amounts")
    return sorted(values)


def ks_distance(baseline: Sequence[int], candidate: Sequence[int]) -> float:
    """Exact ECDF supremum for finite samples, evaluating ties together.

    Integer comparisons retain adjacent PostgreSQL bigint values. No continuous-null
    p-value is attached: ties and repeated CDC revisions make that interpretation unsafe.
    """
    left, right = _amounts(baseline), _amounts(candidate)
    n, m = len(left), len(right)
    i = j = numerator = 0
    for value in sorted(set(left) | set(right)):
        i = bisect_right(left, value, lo=i)
        j = bisect_right(right, value, lo=j)
        numerator = max(numerator, abs(i * m - j * n))
    return numerator / (n * m)


def js_divergence(baseline: Mapping[str, int], candidate: Mapping[str, int]) -> float:
    """Symmetric categorical Jensen-Shannon divergence in bits (not its square root)."""
    for counts in (baseline, candidate):
        if (
            not counts
            or len(counts) > MAX_CURRENCIES
            or any(
                not isinstance(key, str) or type(count) is not int or count < 0
                for key, count in counts.items()
            )
            or sum(counts.values()) == 0
        ):
            raise ValueError("Expected nonempty finite positive-total categorical counts")
    n, m = sum(baseline.values()), sum(candidate.values())
    terms = []
    for key in sorted(set(baseline) | set(candidate)):
        p, q = baseline.get(key, 0) / n, candidate.get(key, 0) / m
        midpoint = (p + q) / 2
        if p:
            terms.append(0.5 * p * math.log2(p / midpoint))
        if q:
            terms.append(0.5 * q * math.log2(q / midpoint))
    return max(0.0, min(1.0, math.fsum(terms)))


def _summary(values: list[int]) -> AmountSummary:
    return AmountSummary(
        count=len(values),
        minimum=values[0],
        maximum=values[-1],
        p50_nearest_rank=values[(len(values) + 1) // 2 - 1],
        p90_nearest_rank=values[(9 * len(values) + 9) // 10 - 1],
    )


def amount_effects(
    baseline: Sequence[int], candidate: Sequence[int], bins: int, smoothing: float
) -> AmountEffects:
    left, right = _amounts(baseline), _amounts(candidate)
    if (
        type(bins) is not int
        or not 2 <= bins <= 20
        or isinstance(smoothing, bool)
        or (
            not isinstance(smoothing, (int, float))
            or not math.isfinite(smoothing)
            or not 0 < smoothing <= 10
        )
    ):
        raise ValueError("Invalid histogram policy")
    # Integer nearest-rank indexing, including max. Duplicate quantiles collapse cells.
    cuts = tuple(sorted({left[(k * len(left) + bins - 1) // bins - 1] for k in range(1, bins + 1)}))

    def histogram(values):
        counts = [0] * (len(cuts) + 2)
        for value in values:
            if value < left[0]:
                cell = 0
            elif value > left[-1]:
                cell = len(cuts) + 1
            else:
                cell = bisect_left(cuts, value) + 1
            counts[cell] += 1
        return tuple(counts)

    p_counts, q_counts = histogram(left), histogram(right)
    p_total = len(left) + smoothing * len(p_counts)
    q_total = len(right) + smoothing * len(q_counts)
    terms = []
    for p_count, q_count in zip(p_counts, q_counts, strict=True):
        p, q = (p_count + smoothing) / p_total, (q_count + smoothing) / q_total
        terms.append((q - p) * math.log(q / p))
    return AmountEffects(
        ks_distance=ks_distance(left, right),
        psi=max(0.0, math.fsum(terms)),
        baseline=_summary(left),
        candidate=_summary(right),
        bin_cuts=cuts,
        baseline_counts=p_counts,
        candidate_counts=q_counts,
        smoothing_pseudocount=float(smoothing),
    )


def _hash(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _window(window: EventWindow, events: Sequence[EvidenceEvent]) -> tuple:
    if len(events) > window.end - window.start + 1:
        raise ValueError("Too many events for identity window")
    ordered = sorted(events, key=lambda event: event.index)
    if len({event.index for event in ordered}) != len(ordered) or any(
        not window.start <= event.index <= window.end for event in ordered
    ):
        raise ValueError("Evidence has duplicate or out-of-window identity")
    live = [event for event in ordered if event.operation != "delete"]
    keys = {event.key for event in live}
    times = sorted(event.occurred_at for event in ordered)
    evidence = WindowEvidence(
        window=window,
        observed_rows=len(ordered),
        analyzed_events=len(live),
        tombstones=len(ordered) - len(live),
        distinct_keys=len(keys),
        repeated_key_events=len(live) - len(keys),
        missing_identity_positions=window.end - window.start + 1 - len(ordered),
        observed_min_index=ordered[0].index if ordered else None,
        observed_max_index=ordered[-1].index if ordered else None,
        occurred_at_min=times[0] if times else None,
        occurred_at_max=times[-1] if times else None,
        evidence_sha256=_hash([event.model_dump() for event in ordered]),
    )
    return evidence, live


def _categorical(left: Counter, right: Counter, minimum: int, threshold: float):
    sufficient = min(sum(left.values()), sum(right.values())) >= minimum
    effect = js_divergence(left, right) if sufficient else None
    return CategoryEffects(
        js_divergence=effect,
        sufficient_samples=sufficient,
        effect_detected=effect is not None and effect > threshold,
        counts=tuple(
            CategoryCount(category=key, baseline=left[key], candidate=right[key])
            for key in sorted(set(left) | set(right))
        ),
    )


def compare_events(
    request: CompareRequest,
    baseline: Sequence[EvidenceEvent],
    candidate: Sequence[EvidenceEvent],
    source_snapshot: SourceSnapshot | None = None,
) -> DriftReport:
    """Compare event-weighted observations; source snapshot is provenance, not an input effect."""
    baseline_evidence, left = _window(request.baseline, baseline)
    candidate_evidence, right = _window(request.candidate, candidate)
    codes = sorted({event.currency for event in [*left, *right]})
    if len(codes) > MAX_CURRENCIES:
        raise ValueError("Currency cardinality exceeds capacity")
    policy = request.policy
    mix = _categorical(
        Counter(event.currency for event in left),
        Counter(event.currency for event in right),
        policy.min_samples,
        policy.currency_js_threshold,
    )
    groups = []
    for code in codes:
        before = [event for event in left if event.currency == code]
        after = [event for event in right if event.currency == code]
        sufficient = min(len(before), len(after)) >= policy.min_samples
        amount = (
            amount_effects(
                [event.amount_minor for event in before],
                [event.amount_minor for event in after],
                policy.bins,
                policy.smoothing,
            )
            if sufficient
            else None
        )
        status = (
            _categorical(
                Counter(event.status for event in before),
                Counter(event.status for event in after),
                policy.min_samples,
                policy.status_js_threshold,
            )
            if sufficient
            else None
        )
        groups.append(
            CurrencyEffects(
                currency=code,
                baseline_samples=len(before),
                candidate_samples=len(after),
                sufficient_samples=sufficient,
                amount=amount,
                status=status,
                amount_effect_detected=amount is not None
                and (amount.ks_distance > policy.ks_threshold or amount.psi > policy.psi_threshold),
                status_effect_detected=status.effect_detected if status else False,
            )
        )
    detected = mix.effect_detected or any(
        group.amount_effect_detected or group.status_effect_detected for group in groups
    )
    complete = bool(groups) and all(group.sufficient_samples for group in groups)
    disposition = (
        "effect_detected"
        if detected
        else ("no_effect_detected" if complete else "insufficient_samples")
    )
    content = dict(
        semantics=SEMANTICS,
        request=request,
        baseline=baseline_evidence,
        candidate=candidate_evidence,
        currency_mix=mix,
        currencies=tuple(groups),
        disposition=disposition,
        source_snapshot=source_snapshot,
    )
    # Acquisition clock/snapshot ID vary even for identical evidence. Keep them in the
    # report, but fingerprint the versioned reproducible analysis and explicit ranges.
    fingerprint = _hash(
        {
            "algorithm": "fluxlake-drift-v1",
            "request": request.model_dump(),
            "baseline": baseline_evidence.model_dump(),
            "candidate": candidate_evidence.model_dump(),
            "currency_mix": mix.model_dump(),
            "currencies": [group.model_dump() for group in groups],
            "disposition": disposition,
        }
    )
    return DriftReport(**content, fingerprint=fingerprint)
