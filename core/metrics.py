"""Metric definitions — single source of truth for display names, units, and ranking config."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, NamedTuple

from .constants import (
    COL_MEAN_CYCLE_H,
    COL_MEDIAN_CYCLE_H,
    COL_MIN_CYCLE_H,
    COL_MAX_CYCLE_H,
    COL_MEAN_COST,
    COL_REWORK_RATE,
    COL_MEAN_REWORK_COUNT,
    COL_MEAN_CYCLE_H_MEAN,
    COL_MEDIAN_CYCLE_H_MEAN,
    COL_MIN_CYCLE_H_MEAN,
    COL_MAX_CYCLE_H_MEAN,
    COL_MEAN_COST_MEAN,
    COL_REWORK_RATE_MEAN,
    COL_MEAN_REWORK_COUNT_MEAN,
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

    display_fn converts the stored value to display units; named functions, not
    lambdas, so specs stay picklable.
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
class IndicatorSpec:
    """One selectable indicator of a metric: its raw results column + display specs.

    An indicator is a per-case factor that can contribute to a metric's goal
    score (e.g. mean / median / min / max case time for the time metric). Its
    across-replication mean is `mean.column`; the raw per-replication column it
    aggregates from is `results_column`.

    upper_bound is the indicator's value-domain ceiling (None = unbounded above;
    only the rework-rate percentage caps, at 100) — it lives here, not on Metric,
    because the ceiling is a fact about the indicator's own values (rework *rate*
    caps at 100, rework *count* does not), and it drives the goal-threshold
    widgets' max_value and seed clamp.
    """

    results_column: str  # column in the raw per-replication results DataFrame
    mean: MetricSpec
    upper_bound: float | None = None

    # Display accessors used by the UI; the data column/direction are read
    # directly off `.mean` (one settled idiom for those, no facade).
    @property
    def display_name(self) -> str:
        return self.mean.display_name

    @property
    def compact_label(self) -> str:
        """short_label when available, falling back to display_name."""
        return self.mean.short_label or self.mean.display_name

    @property
    def decimal_places(self) -> int:
        return self.mean.decimal_places


@dataclass(frozen=True)
class Metric:
    """A KPI composed of an ordered indicator list and an optional aggregate.

    indicators[0] is the locked default indicator (always in the metric's goal
    score, ranked, and S/N-analysed); indicators[1:] are optional extras the
    user may add with weights. An empty tuple marks a display-only metric with
    no per-case representation (REWORK_COUNT, BOT_FAILURE_COUNT).

    rankable and sn_floor are policy/domain facts about the metric as a whole:
    whether it can be a ranking goal, and the offset that keeps S/N finite for
    metrics that legitimately reach zero.
    """

    indicators: tuple[IndicatorSpec, ...]
    aggregate: MetricSpec | None
    rankable: bool
    sn_floor: float = 0.0

    @property
    def default_indicator(self) -> IndicatorSpec:
        """The locked first indicator, raising on a metric that has none.

        The per-case accessors below are non-Optional so consumers gated on
        rankable() need no assert-narrowing; calling them on an indicator-less
        metric is a programming error, surfaced loudly.
        """
        if not self.indicators:
            raise ValueError(
                f"metric accessor requires a metric with indicators; got {self}"
            )
        return self.indicators[0]

    @property
    def extra_indicators(self) -> tuple[IndicatorSpec, ...]:
        """The optional (non-default) indicators, in registry order."""
        return self.indicators[1:]

    @property
    def per_case_column(self) -> str:
        return self.default_indicator.mean.column

    @property
    def per_case_display_name(self) -> str:
        return self.default_indicator.display_name

    @property
    def per_case_compact_label(self) -> str:
        return self.default_indicator.compact_label


class MetricRegistry:
    """The KPIs as class-level singletons; all() order is the display order."""

    CYCLE_TIME: Metric = Metric(
        indicators=(
            IndicatorSpec(
                results_column=COL_MEAN_CYCLE_H,
                mean=MetricSpec(
                    column=COL_MEAN_CYCLE_H_MEAN,
                    display_name="Cycle Time (h/case)",
                    decimal_places=2,
                    short_label="Cycle Time",
                ),
            ),
            IndicatorSpec(
                results_column=COL_MEDIAN_CYCLE_H,
                mean=MetricSpec(
                    column=COL_MEDIAN_CYCLE_H_MEAN,
                    display_name="Median Cycle Time (h/case)",
                    decimal_places=2,
                    short_label="Median Cycle Time",
                ),
            ),
            IndicatorSpec(
                results_column=COL_MIN_CYCLE_H,
                mean=MetricSpec(
                    column=COL_MIN_CYCLE_H_MEAN,
                    display_name="Min Cycle Time (h/case)",
                    decimal_places=2,
                    short_label="Min Cycle Time",
                ),
            ),
            IndicatorSpec(
                results_column=COL_MAX_CYCLE_H,
                mean=MetricSpec(
                    column=COL_MAX_CYCLE_H_MEAN,
                    display_name="Max Cycle Time (h/case)",
                    decimal_places=2,
                    short_label="Max Cycle Time",
                ),
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
        indicators=(
            IndicatorSpec(
                results_column=COL_MEAN_COST,
                mean=MetricSpec(
                    column=COL_MEAN_COST_MEAN,
                    display_name="Cost ($/case)",
                    decimal_places=2,
                    short_label="Cost",
                ),
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
        indicators=(),
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
        indicators=(
            IndicatorSpec(
                results_column=COL_REWORK_RATE,
                mean=MetricSpec(
                    column=COL_REWORK_RATE_MEAN,
                    display_name="Rework Rate (%)",
                    decimal_places=1,
                    short_label="Rework Rate",
                ),
                upper_bound=100.0,  # a percentage of cases
            ),
            IndicatorSpec(
                results_column=COL_MEAN_REWORK_COUNT,
                mean=MetricSpec(
                    column=COL_MEAN_REWORK_COUNT_MEAN,
                    display_name="Rework Count (/case)",
                    decimal_places=2,
                    short_label="Rework Count/case",
                ),
            ),
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
        indicators=(),
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
