"""Metric definitions — single source of truth for display names, units, and ranking config."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, NamedTuple

from .constants import (
    COL_MEAN_CYCLE_H,
    COL_MEAN_COST,
    COL_REWORK_RATE,
    COL_MEAN_CYCLE_H_MEAN,
    COL_MEAN_COST_MEAN,
    COL_REWORK_RATE_MEAN,
    COL_TOTAL_CYCLE_S_MEAN,
    COL_TOTAL_COST_MEAN,
    COL_TOTAL_REWORK_COUNT_MEAN,
    COL_TOTAL_BOT_FAILURE_COUNT_MEAN,
)


class MetricDirection(str, Enum):
    SMALLER_IS_BETTER = "smaller_is_better"
    LARGER_IS_BETTER = "larger_is_better"


def _identity(value: float) -> float:
    return value


def _seconds_to_hours(value: float) -> float:
    return value / 3600


class MetricSpec(NamedTuple):
    """One displayable representation of a metric: a column plus its display config.

    display_fn converts the stored value to display units (only the aggregate
    cycle-time spec converts — seconds to hours); named functions, not lambdas,
    so specs stay picklable.
    """

    column: str
    display_name: str
    decimal_places: int
    direction: MetricDirection = MetricDirection.SMALLER_IS_BETTER
    display_fn: Callable[[float], float] = _identity
    delta_name: str | None = None
    pct_change_name: str | None = None
    short_label: str | None = None  # name without unit, for compact displays


@dataclass(frozen=True)
class PerCaseMetric:
    """A metric's per-case representation: its raw results column + display specs."""

    results_column: str  # column in the raw per-replication results DataFrame
    mean: MetricSpec
    std: MetricSpec | None = None  # hidden by default; registered for future toggle


@dataclass(frozen=True)
class Metric:
    """A KPI composed of optional per-case and aggregate representations.

    rankable and sn_floor are policy about the metric as a whole: whether it can
    be a ranking goal, and the offset that keeps S/N finite for metrics that
    legitimately reach zero.
    """

    per_case: PerCaseMetric | None
    aggregate: MetricSpec | None
    rankable: bool
    sn_floor: float = 0.0

    def _require_per_case(self) -> PerCaseMetric:
        """per_case, raising on metrics without one (REWORK_COUNT, BOT_FAILURE_COUNT).

        The per-case accessors below are non-Optional so consumers gated on
        rankable() need no assert-narrowing; calling them on a per_case-less
        metric is a programming error, surfaced loudly.
        """
        if self.per_case is None:
            raise ValueError(
                f"per-case accessor requires a metric with per_case data; got {self}"
            )
        return self.per_case

    @property
    def per_case_column(self) -> str:
        return self._require_per_case().mean.column

    @property
    def per_case_display_name(self) -> str:
        return self._require_per_case().mean.display_name

    @property
    def per_case_compact_label(self) -> str:
        """short_label when available, falling back to display_name."""
        mean = self._require_per_case().mean
        return mean.short_label or mean.display_name


class MetricRegistry:
    """The four KPIs as class-level singletons; all() order is the display order."""

    CYCLE_TIME: Metric = Metric(
        per_case=PerCaseMetric(
            results_column=COL_MEAN_CYCLE_H,
            mean=MetricSpec(
                column=COL_MEAN_CYCLE_H_MEAN,
                display_name="Cycle Time (h/case)",
                decimal_places=2,
                short_label="Cycle Time",
            ),
            std=MetricSpec(
                column="mean_cycle_h_std",
                display_name="Cycle Time Std Dev (h)",
                decimal_places=2,
            ),
        ),
        aggregate=MetricSpec(
            column=COL_TOTAL_CYCLE_S_MEAN,
            display_name="Total Cycle Time (h)",
            decimal_places=2,
            display_fn=_seconds_to_hours,
            delta_name="Δ Time (h)",
            pct_change_name="Δ Time (%)",
        ),
        rankable=True,
    )

    COST: Metric = Metric(
        per_case=PerCaseMetric(
            results_column=COL_MEAN_COST,
            mean=MetricSpec(
                column=COL_MEAN_COST_MEAN,
                display_name="Cost ($/case)",
                decimal_places=2,
                short_label="Cost",
            ),
            std=MetricSpec(
                column="mean_cost_std",
                display_name="Cost Std Dev ($)",
                decimal_places=2,
            ),
        ),
        aggregate=MetricSpec(
            column=COL_TOTAL_COST_MEAN,
            display_name="Total Cost ($)",
            decimal_places=2,
            delta_name="Δ Cost ($)",
            pct_change_name="Δ Cost (%)",
        ),
        rankable=True,
    )

    REWORK_COUNT: Metric = Metric(
        per_case=None,
        aggregate=MetricSpec(
            column=COL_TOTAL_REWORK_COUNT_MEAN,
            display_name="Rework Count",
            decimal_places=2,
            delta_name="Δ Rework Count",
            pct_change_name="Δ Rework (%)",
        ),
        rankable=False,
    )

    REWORK_RATE: Metric = Metric(
        per_case=PerCaseMetric(
            results_column=COL_REWORK_RATE,
            mean=MetricSpec(
                column=COL_REWORK_RATE_MEAN,
                display_name="Rework Rate (%)",
                decimal_places=1,
                short_label="Rework Rate",
            ),
            std=None,
        ),
        aggregate=MetricSpec(
            column=COL_REWORK_RATE_MEAN,
            display_name="Rework Rate (%)",
            decimal_places=1,
            delta_name="Δ Rate (pp)",
        ),
        rankable=True,
        sn_floor=0.01,
    )

    # Display-only, like REWORK_COUNT. Not rankable — the count is input-derivable
    # in expectation, so a goal on it would reward configuration, not discovery.
    # No pct_change_name: the baseline value is structurally 0 (see CLAUDE.md §8).
    BOT_FAILURE_COUNT: Metric = Metric(
        per_case=None,
        aggregate=MetricSpec(
            column=COL_TOTAL_BOT_FAILURE_COUNT_MEAN,
            display_name="Bot Failures",
            decimal_places=2,
            delta_name="Δ Bot Failures",
        ),
        rankable=False,
    )

    @classmethod
    def all(cls) -> list[Metric]:
        return [
            cls.CYCLE_TIME,
            cls.COST,
            cls.REWORK_COUNT,
            cls.REWORK_RATE,
            cls.BOT_FAILURE_COUNT,
        ]

    @classmethod
    def rankable(cls) -> list[Metric]:
        return [metric for metric in cls.all() if metric.rankable]
