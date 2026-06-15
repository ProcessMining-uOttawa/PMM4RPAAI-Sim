"""Goal specification for multi-metric ranking."""
from __future__ import annotations

from dataclasses import dataclass

from .constants import (
    COL_CYCLE_H_MEAN, COL_COST_MEAN, COL_REWORK_RATE_MEAN,
    COL_TOTAL_CYCLE_S_MEAN, COL_TOTAL_COST_MEAN,
)


@dataclass
class Goal:
    metric: str
    weight: float
    target: float  # absolute threshold (same units as metric column)

    @classmethod
    def from_pct_reduction(
        cls, metric: str, weight: float, pct: float, baseline_val: float
    ) -> Goal:
        """Construct a Goal from a percentage-reduction target and a baseline value."""
        return cls(metric=metric, weight=weight, target=baseline_val * (1 - pct / 100))


def baseline_per_case(baseline_agg: dict[int, dict]) -> dict[str, float]:
    """Convert baseline_agg (aggregate totals keyed by n_cases) to per-case metric values.

    Uses the smallest n_cases level as representative; per-case metrics are
    scale-independent across n_cases levels up to simulation variance.
    """
    n_ref = sorted(baseline_agg)[0]
    b_ref = baseline_agg[n_ref]
    return {
        COL_CYCLE_H_MEAN:    b_ref[COL_TOTAL_CYCLE_S_MEAN] / 3600 / n_ref,
        COL_COST_MEAN:       b_ref[COL_TOTAL_COST_MEAN] / n_ref,
        COL_REWORK_RATE_MEAN: b_ref[COL_REWORK_RATE_MEAN],
    }
