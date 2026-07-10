"""Goal specification for piecewise-linear goal satisfaction scoring."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .constants import (
    COL_MEAN_CYCLE_H_MEAN,
    COL_MEDIAN_CYCLE_H_MEAN,
    COL_MEAN_COST_MEAN,
    COL_REWORK_RATE_MEAN,
    COL_TOTAL_CYCLE_S_MEAN,
    COL_TOTAL_COST_MEAN,
)
from .metrics import Metric, MetricDirection

# Percentage by which target beats the baseline (and worst lags it).
# Exported so the UI caption can stay in sync without duplicating the value.
GOAL_IMPROVEMENT_PCT: int = 10

_TARGET_MULTIPLIER = 1 - GOAL_IMPROVEMENT_PCT / 100
_WORST_MULTIPLIER = 1 + GOAL_IMPROVEMENT_PCT / 100


@dataclass(frozen=True)
class Goal:
    metric: str
    target: float  # best-case breakpoint → score 100
    baseline_ref: float  # reference breakpoint → score 50 (baseline value)
    worst: float  # unacceptable breakpoint → score 0
    # Optional second factor: a full Goal (its own metric column + breakpoints)
    # weighted against this (primary) one — only the time goal uses it for now.
    # weight applies to THIS factor; the secondary gets 1 - weight. This is an
    # *intra-goal* weight between two factors of one goal, NOT the cross-goal
    # weight that was deliberately removed — the inter-goal aggregate stays a
    # weakest-link min (see analysis.rank). A Goal used *as* a secondary ignores
    # its own weight/secondary fields; only the primary's weight is read.
    secondary: Goal | None = None
    weight: float = 1.0

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
                f"Goal breakpoints out of order for {self.metric!r}: baseline_ref "
                f"({self.baseline_ref}) must lie between target ({self.target}) "
                f"and worst ({self.worst})"
            )
        if self.secondary is not None and self.secondary.secondary is not None:
            raise ValueError("a Goal may have at most one secondary factor")
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError(f"Goal weight must be in [0, 1]; got {self.weight}")

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

    def weighted_score(
        self, primary_value: float, secondary_value: float = float("nan")
    ) -> float:
        """Combined 0–100 score across this goal's one or two weighted factors.

        Single-factor (secondary is None): just score(primary_value). Two-factor:
        weight·score(primary) + (1 - weight)·secondary.score(secondary_value),
        each factor judged against its own breakpoints. secondary_value is unused
        (and irrelevant) when there is no secondary factor.
        """
        primary = self.score(primary_value)
        if self.secondary is None:
            return primary
        secondary = self.secondary.score(secondary_value)
        return self.weight * primary + (1 - self.weight) * secondary

    @classmethod
    def from_metric(cls, metric: Metric, baseline: dict[str, float]) -> Goal:
        """Construct a Goal for a Metric using its per-case baseline value from a baseline dict.

        Reads the per-case column and direction from the Metric internally.
        Raises ValueError if the metric has no per_case data.
        """
        if metric.per_case is None:
            raise ValueError(
                f"Goal.from_metric() requires a metric with per_case data; got {metric}"
            )
        pc = metric.per_case
        return cls.from_baseline(
            pc.mean.column, baseline[pc.mean.column], pc.mean.direction
        )

    @classmethod
    def from_baseline(
        cls, metric: str, baseline_val: float, direction: MetricDirection
    ) -> Goal:
        """Construct a Goal from a baseline value using fixed ±GOAL_IMPROVEMENT_PCT breakpoints.

        For smaller-is-better: target = (1 - GOAL_IMPROVEMENT_PCT/100) × baseline,
                                worst  = (1 + GOAL_IMPROVEMENT_PCT/100) × baseline.
        For larger-is-better:  roles are reversed.
        baseline_ref is always 1.0 × baseline (the baseline itself scores 50).
        """
        if direction == MetricDirection.SMALLER_IS_BETTER:
            return cls(
                metric=metric,
                target=baseline_val * _TARGET_MULTIPLIER,
                baseline_ref=baseline_val,
                worst=baseline_val * _WORST_MULTIPLIER,
            )
        return cls(
            metric=metric,
            target=baseline_val * _WORST_MULTIPLIER,
            baseline_ref=baseline_val,
            worst=baseline_val * _TARGET_MULTIPLIER,
        )


def baseline_per_case(baseline_agg: dict[int, dict]) -> dict[str, float]:
    """Convert baseline_agg (aggregate totals keyed by n_cases) to per-case metric values.

    Uses the smallest n_cases level as representative; per-case metrics are
    scale-independent across n_cases levels up to simulation variance.
    """
    n_ref = sorted(baseline_agg)[0]
    b_ref = baseline_agg[n_ref]
    return {
        COL_MEAN_CYCLE_H_MEAN: b_ref[COL_TOTAL_CYCLE_S_MEAN] / 3600 / n_ref,
        # Pass-through, NOT total ÷ N: median is per-case already and never
        # carried the total-cycle identity (the reason it is a separate column).
        COL_MEDIAN_CYCLE_H_MEAN: b_ref[COL_MEDIAN_CYCLE_H_MEAN],
        COL_MEAN_COST_MEAN: b_ref[COL_TOTAL_COST_MEAN] / n_ref,
        COL_REWORK_RATE_MEAN: b_ref[COL_REWORK_RATE_MEAN],
    }
