"""Goal metric options for the sidebar goal selector."""

from __future__ import annotations
from typing import NamedTuple

from core.metrics import Metric, MetricRegistry


class GoalOption(NamedTuple):
    default_pct: float
    default_weight: float
    step: float = 1.0
    allow_zero: bool = False


GOAL_OPTIONS: dict[Metric, GoalOption] = {
    MetricRegistry.CYCLE_TIME: GoalOption(default_pct=20.0, default_weight=0.33),
    MetricRegistry.COST: GoalOption(default_pct=20.0, default_weight=0.33),
    MetricRegistry.REWORK_RATE: GoalOption(
        default_pct=20.0, default_weight=0.33, step=0.1, allow_zero=True
    ),
}
