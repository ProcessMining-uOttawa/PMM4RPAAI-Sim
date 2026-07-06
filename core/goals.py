"""Goal specification for piecewise-linear goal satisfaction scoring."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .constants import (
    COL_MEAN_CYCLE_H_MEAN,
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
        COL_MEAN_COST_MEAN: b_ref[COL_TOTAL_COST_MEAN] / n_ref,
        COL_REWORK_RATE_MEAN: b_ref[COL_REWORK_RATE_MEAN],
    }
