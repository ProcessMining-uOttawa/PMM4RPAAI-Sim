"""Goal metric options for the sidebar goal selector."""
from __future__ import annotations
from typing import NamedTuple

from core.constants import COL_CYCLE_H_MEAN, COL_COST_MEAN, COL_REWORK_RATE_MEAN


class GoalOption(NamedTuple):
    col: str
    default: float
    scale: float = 1.0       # converts user input to the column's stored unit
    step: float = 1.0        # st.number_input increment
    allow_zero: bool = False  # whether goal_max = 0 is a valid target


GOAL_OPTIONS: dict[str, GoalOption] = {
    "Cycle time (hours)": GoalOption(COL_CYCLE_H_MEAN, default=40.0),
    "Cost ($/case)":      GoalOption(COL_COST_MEAN,    default=25.0),
    "Rework rate (%)":    GoalOption(COL_REWORK_RATE_MEAN, default=10.0,
                                     scale=0.01, step=0.1, allow_zero=True),
}
