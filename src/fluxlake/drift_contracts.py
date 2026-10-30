"""Immutable, bounded contracts for descriptive retained-event comparisons."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_INDEX = 2**63 - 1
MAX_WINDOW_SPAN = 2000
MAX_CURRENCIES = 32
Index = Annotated[int, Field(ge=1, le=MAX_INDEX)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
UnitEffect = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class FrozenContract(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class EventWindow(FrozenContract):
    start: Index
    end: Index

    @model_validator(mode="after")
    def bounded_range(self):
        if not 1 <= self.end - self.start + 1 <= MAX_WINDOW_SPAN:
            raise ValueError("Window must span 1 to 2000 inclusive identity positions")
        return self


class DriftPolicy(FrozenContract):
    min_samples: Annotated[int, Field(ge=10, le=1000)] = 30
    bins: Annotated[int, Field(ge=2, le=20)] = 5
    smoothing: Annotated[float, Field(gt=0, le=10, allow_inf_nan=False)] = 0.5
    ks_threshold: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)] = 0.25
    psi_threshold: Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)] = 0.2
    status_js_threshold: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)] = 0.1
    currency_js_threshold: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)] = 0.05


class CompareRequest(FrozenContract):
    baseline: EventWindow
    candidate: EventWindow
    policy: DriftPolicy = Field(default_factory=DriftPolicy)

    @model_validator(mode="after")
    def nonoverlapping(self):
        if max(self.baseline.start, self.candidate.start) <= min(
            self.baseline.end, self.candidate.end
        ):
            raise ValueError("Windows must not overlap")
        return self


class EvidenceEvent(FrozenContract):
    index: Index
    event_id: Annotated[str, Field(pattern=r"^[0-9a-fA-F-]{36}$")]
    key: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    version: Index
    operation: Literal["insert", "update", "delete"]
    occurred_at: Annotated[str, Field(min_length=1, max_length=64)]
    amount_minor: Annotated[int, Field(ge=0, le=MAX_INDEX)]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    status: Literal["pending", "settled", "failed"]
    payload_sha256: Digest


class SourceSnapshot(FrozenContract):
    id: str
    captured_at: str
    isolation: Literal["repeatable read"] = "repeatable read"
    read_only: Literal[True] = True


class WindowEvidence(FrozenContract):
    window: EventWindow
    observed_rows: int
    analyzed_events: int
    tombstones: int
    distinct_keys: int
    repeated_key_events: int
    missing_identity_positions: int
    observed_min_index: int | None
    observed_max_index: int | None
    occurred_at_min: str | None
    occurred_at_max: str | None
    evidence_sha256: Digest


class AmountSummary(FrozenContract):
    count: int
    minimum: int
    maximum: int
    p50_nearest_rank: int
    p90_nearest_rank: int


class AmountEffects(FrozenContract):
    ks_distance: UnitEffect
    psi: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    baseline: AmountSummary
    candidate: AmountSummary
    bin_cuts: tuple[int, ...]
    baseline_counts: tuple[int, ...]
    candidate_counts: tuple[int, ...]
    smoothing_pseudocount: float
    bin_semantics: str = (
        "Baseline nearest-rank quantile upper cuts, duplicate cuts collapsed; "
        "first/last cells are strictly below/above baseline support. "
        "Interior cells are right-closed; candidate uses unchanged cuts."
    )


class CategoryCount(FrozenContract):
    category: str
    baseline: int
    candidate: int


class CategoryEffects(FrozenContract):
    js_divergence: UnitEffect | None
    sufficient_samples: bool
    effect_detected: bool
    counts: tuple[CategoryCount, ...]


class CurrencyEffects(FrozenContract):
    currency: str
    baseline_samples: int
    candidate_samples: int
    sufficient_samples: bool
    amount: AmountEffects | None
    status: CategoryEffects | None
    amount_effect_detected: bool
    status_effect_detected: bool


class DriftReport(FrozenContract):
    algorithm: Literal["fluxlake-drift-v1"] = "fluxlake-drift-v1"
    scope: Literal["retained_outbox_event_index_windows"] = "retained_outbox_event_index_windows"
    semantics: tuple[str, ...]
    request: CompareRequest
    source_snapshot: SourceSnapshot | None
    baseline: WindowEvidence
    candidate: WindowEvidence
    currency_mix: CategoryEffects
    currencies: tuple[CurrencyEffects, ...]
    disposition: Literal["effect_detected", "no_effect_detected", "insufficient_samples"]
    fingerprint: Digest
