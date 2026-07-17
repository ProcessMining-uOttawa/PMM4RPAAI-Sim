"""Goal specification for piecewise-linear goal satisfaction scoring."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from .metrics import IndicatorSpec, MetricDirection, MetricRegistry

# Percentage by which target beats the baseline (and worst lags it).
# Exported so the UI caption can stay in sync without duplicating the value.
GOAL_IMPROVEMENT_PCT: int = 10

_TARGET_MULTIPLIER = 1 - GOAL_IMPROVEMENT_PCT / 100
_WORST_MULTIPLIER = 1 + GOAL_IMPROVEMENT_PCT / 100


@dataclass(frozen=True)
class Goal:
    """Piecewise-linear scoring for one indicator (one column, three breakpoints)."""

    indicator_column: str  # the indicator's column in the agg/results frame
    target: float  # best-case breakpoint → score 100
    baseline_ref: float  # reference breakpoint → score 50 (baseline value)
    worst: float  # unacceptable breakpoint → score 0

    def __post_init__(self) -> None:
        """Reject breakpoints that cannot score coherently.

        score() interpolates target → baseline_ref → worst; a baseline_ref
        outside the [target, worst] span (either direction) would make the
        interpolation discontinuous — a 75-point cliff across an epsilon —
        so such a Goal is unconstructible. Callers taking user input must
        validate before constructing.
        """
        if not (
            min(self.target, self.worst)
            <= self.baseline_ref
            <= max(self.target, self.worst)
        ):
            raise ValueError(
                f"Goal breakpoints out of order for {self.indicator_column!r}: baseline_ref "
                f"({self.baseline_ref}) must lie between target ({self.target}) "
                f"and worst ({self.worst})"
            )

    def score(self, value: float) -> float:
        """Piecewise linear score in [0, 100]: 100 at target, 50 at baseline_ref, 0 at worst.

        Works for both smaller-is-better (target < worst) and
        larger-is-better (target > worst) by normalising sign internally.
        Returns 0 for NaN values.
        """
        if math.isnan(value):
            return 0.0
        # Negate for larger-is-better so we always work in smaller-is-better space:
        # after negation, target_ ≤ baseline_ref_ ≤ worst_.
        sign = -1.0 if self.target > self.worst else 1.0
        val = sign * value
        target_ = sign * self.target
        baseline_ref_ = sign * self.baseline_ref
        worst_ = sign * self.worst
        if val <= target_:
            return 100.0
        if val >= worst_:
            return 0.0
        if val <= baseline_ref_:  # between target and baseline_ref
            span = baseline_ref_ - target_
            return (baseline_ref_ - val) / span * 50.0 + 50.0 if span else 100.0
        # between baseline_ref and worst
        span = worst_ - baseline_ref_
        return -(val - baseline_ref_) / span * 50.0 + 50.0 if span else 0.0

    @classmethod
    def from_indicator(
        cls, indicator: IndicatorSpec, baseline: dict[str, float]
    ) -> Goal:
        """Construct a Goal for one indicator using its per-case baseline value.

        Reads the indicator's mean column and direction internally; the baseline
        dict must carry that column (baseline_per_case guarantees it).
        """
        return cls.from_baseline(
            indicator.mean.column,
            baseline[indicator.mean.column],
            indicator.mean.direction,
        )

    @classmethod
    def from_baseline(
        cls, indicator_column: str, baseline_val: float, direction: MetricDirection
    ) -> Goal:
        """Construct a Goal from a baseline value using fixed ±GOAL_IMPROVEMENT_PCT breakpoints.

        For smaller-is-better: target = (1 - GOAL_IMPROVEMENT_PCT/100) × baseline,
                                worst  = (1 + GOAL_IMPROVEMENT_PCT/100) × baseline.
        For larger-is-better:  roles are reversed.
        baseline_ref is always 1.0 × baseline (the baseline itself scores 50).
        """
        if direction == MetricDirection.SMALLER_IS_BETTER:
            return cls(
                indicator_column=indicator_column,
                target=baseline_val * _TARGET_MULTIPLIER,
                baseline_ref=baseline_val,
                worst=baseline_val * _WORST_MULTIPLIER,
            )
        return cls(
            indicator_column=indicator_column,
            target=baseline_val * _WORST_MULTIPLIER,
            baseline_ref=baseline_val,
            worst=baseline_val * _TARGET_MULTIPLIER,
        )


@dataclass(frozen=True)
class MetricGoal:
    """One metric's goal: a weighted set of per-indicator Goals scored together.

    indicator_goals[0] is the metric's locked default indicator's Goal; the rest
    are the user's added extras. weights are parallel integers (each ≥ 1),
    normalised by their sum at scoring — so a weight of 3 counts 3× a weight of 1.
    The metric's score is Σ wᵢ·score(vᵢ) / Σ wᵢ. The cross-metric aggregate
    (analysis.rank) stays a weakest-link min across MetricGoals — these weights
    are strictly intra-metric.
    """

    indicator_goals: tuple[Goal, ...]
    weights: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.indicator_goals:
            raise ValueError("a MetricGoal needs at least one indicator")
        if len(self.weights) != len(self.indicator_goals):
            raise ValueError(
                f"weights ({len(self.weights)}) must match indicators "
                f"({len(self.indicator_goals)})"
            )
        if any(weight < 1 for weight in self.weights):
            raise ValueError(f"indicator weights must be >= 1; got {self.weights}")

    @property
    def score_column(self) -> str:
        """The '{column}_score' column key, keyed by the default indicator."""
        return f"{self.indicator_goals[0].indicator_column}_score"

    def score(self, values: Mapping[str, float]) -> float:
        """Weight-normalised 0–100 score across the indicators.

        values maps each indicator's column to the scenario's value; a pandas row
        Series is a valid Mapping here.
        """
        total_weight = sum(self.weights)
        weighted = sum(
            weight * goal.score(values[goal.indicator_column])
            for goal, weight in zip(self.indicator_goals, self.weights)
        )
        return weighted / total_weight


def baseline_per_case(baseline_agg: dict[str, float]) -> dict[str, float]:
    """Pick the per-case indicator values out of the flat baseline_agg record.

    The record carries per-case means at source (beside the totals), so this is
    a filter, not a conversion — it returns exactly every registered indicator's
    mean column, which Goal.from_indicator reads. A missing key is malformed
    input and raises loudly.
    """
    return {
        indicator.mean.column: baseline_agg[indicator.mean.column]
        for metric in MetricRegistry.all()
        for indicator in metric.indicators
    }
