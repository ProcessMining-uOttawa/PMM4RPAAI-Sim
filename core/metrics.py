"""Metric definitions — single source of truth for display names, units, and ranking config."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, NamedTuple

from .constants import (
    COL_CYCLE_H_MEAN, COL_COST_MEAN, COL_REWORK_RATE_MEAN,
    COL_TOTAL_CYCLE_S_MEAN, COL_TOTAL_COST_MEAN, COL_REWORK_COUNT_MEAN,
)


class MetricSpec(NamedTuple):
    column: str
    display_name: str
    display_fn: Callable[[float], float]   # raw stored value → display unit
    decimal_places: int
    kind: str                              # "smaller_is_better" | "larger_is_better"
    rankable: bool
    delta_name: str | None = None          # None for specs that don't appear in Panel 5
    pct_change_name: str | None = None     # None when pp delta is used instead of %


def _id(v: float) -> float:
    return v


@dataclass(frozen=True)
class PerCaseMetric:
    """Per-simulation-case representation of a metric (Panel 4)."""
    mean: MetricSpec
    std: MetricSpec | None = None  # hidden by default; registered for future toggle


@dataclass(frozen=True)
class Metric:
    """One business metric with optional per-case and aggregate representations."""
    per_case: PerCaseMetric | None   # used for ranking and the ranked table
    aggregate: MetricSpec | None     # used for Panel 5 baseline comparison


class MetricRegistry:
    CYCLE_TIME: Metric = Metric(
        per_case=PerCaseMetric(
            mean=MetricSpec(
                column=COL_CYCLE_H_MEAN,
                display_name="Cycle Time (h/case)",
                display_fn=_id,
                decimal_places=2,
                kind="smaller_is_better",
                rankable=True,
            ),
            std=MetricSpec(
                column="cycle_h_std",
                display_name="Cycle Time Std Dev (h)",
                display_fn=_id,
                decimal_places=2,
                kind="smaller_is_better",
                rankable=False,
            ),
        ),
        aggregate=MetricSpec(
            column=COL_TOTAL_CYCLE_S_MEAN,
            display_name="Total Cycle Time (h)",
            display_fn=lambda v: v / 3600,
            decimal_places=2,
            kind="smaller_is_better",
            rankable=False,
            delta_name="Δ Time (h)",
            pct_change_name="Δ Time (%)",
        ),
    )

    COST: Metric = Metric(
        per_case=PerCaseMetric(
            mean=MetricSpec(
                column=COL_COST_MEAN,
                display_name="Cost ($/case)",
                display_fn=_id,
                decimal_places=2,
                kind="smaller_is_better",
                rankable=True,
            ),
            std=MetricSpec(
                column="cost_std",
                display_name="Cost Std Dev ($)",
                display_fn=_id,
                decimal_places=2,
                kind="smaller_is_better",
                rankable=False,
            ),
        ),
        aggregate=MetricSpec(
            column=COL_TOTAL_COST_MEAN,
            display_name="Total Cost ($)",
            display_fn=_id,
            decimal_places=2,
            kind="smaller_is_better",
            rankable=False,
            delta_name="Δ Cost ($)",
            pct_change_name="Δ Cost (%)",
        ),
    )

    REWORK_COUNT: Metric = Metric(
        per_case=None,
        aggregate=MetricSpec(
            column=COL_REWORK_COUNT_MEAN,
            display_name="Rework Count",
            display_fn=_id,
            decimal_places=2,
            kind="smaller_is_better",
            rankable=False,
            delta_name="Δ Rework Count",
            pct_change_name="Δ Rework (%)",
        ),
    )

    REWORK_RATE: Metric = Metric(
        per_case=PerCaseMetric(
            mean=MetricSpec(
                column=COL_REWORK_RATE_MEAN,
                display_name="Rework Rate (%)",
                display_fn=_id,
                decimal_places=1,
                kind="smaller_is_better",
                rankable=True,
            ),
            std=None,
        ),
        # aggregate shares the same column as per_case — stored as percentage in both contexts
        aggregate=MetricSpec(
            column=COL_REWORK_RATE_MEAN,
            display_name="Rework Rate (%)",
            display_fn=_id,
            decimal_places=1,
            kind="smaller_is_better",
            rankable=False,
            delta_name="Δ Rate (pp)",
            pct_change_name=None,   # pp delta used instead of relative %
        ),
    )

    @classmethod
    def all(cls) -> list[Metric]:
        return [cls.CYCLE_TIME, cls.COST, cls.REWORK_COUNT, cls.REWORK_RATE]

    @classmethod
    def rankable(cls) -> list[Metric]:
        """Metrics that have a per-case representation and can be used as a ranking goal."""
        return [m for m in cls.all() if m.per_case is not None]

    @classmethod
    def by_column(cls, col: str) -> MetricSpec | None:
        """Return the first MetricSpec matching col, searching per_case then aggregate."""
        for m in cls.all():
            if m.per_case:
                if m.per_case.mean.column == col:
                    return m.per_case.mean
                if m.per_case.std and m.per_case.std.column == col:
                    return m.per_case.std
            if m.aggregate and m.aggregate.column == col:
                return m.aggregate
        return None
