"""Goal metric options for the sidebar goal selector."""
from __future__ import annotations
from typing import NamedTuple

from core.metrics import Metric, MetricRegistry


class GoalOption(NamedTuple):
    default: float
    step: float = 1.0
    allow_zero: bool = False


GOAL_OPTIONS: dict[Metric, GoalOption] = {
    MetricRegistry.CYCLE_TIME:  GoalOption(default=40.0),
    MetricRegistry.COST:        GoalOption(default=25.0),
    MetricRegistry.REWORK_RATE: GoalOption(default=10.0, step=0.1, allow_zero=True),
}
