"""Interactive ranked-scenarios table for the Ranking tab (Panel 5 · Results).

Part of ui/interactive/, so this module renders st.* widgets directly. It ranks
what it is given: goals are constructed upstream (Panel 3's goal configuration)
and baseline availability is app.py's concern (the baseline-failed error lives
in app.py's Panel 5 warning cluster). Consumes the pure ui/table helper — a
ui/interactive -> ui/ (presentation primitives) dependency. Has no pure surface,
so it is exercised manually like app.py rather than unit-tested.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from core import analysis
from core.goals import MetricGoal
from core.metrics import IndicatorSpec, Metric
from core.parameters import Parameter
from ui.table import prepare_ranked_display


def render_ranked_scenarios(
    agg: pd.DataFrame,
    goal_metrics: list[Metric],
    scorable_goals: list[MetricGoal],
    selected_extras: dict[str, list[IndicatorSpec]],
    parameters: list[Parameter],
) -> pd.DataFrame:
    """Render the goal-scored ranked-scenarios table.

    goal_metrics + selected_extras drive the display columns; scorable_goals (a
    subset when a slot's thresholds failed validation) drives the scoring.
    Returns the ranked DataFrame (also used by app.py for the Statistics CSV
    export). With no scorable goals the table degrades to KPIs only.
    """
    ranked = analysis.rank(agg, scorable_goals)
    if not scorable_goals:
        # rank() fabricates an all-zero aggregate score when there is nothing
        # to score; presented as data it misleads — and the Statistics CSV
        # built from this frame escapes Panel 5's error banner — so drop it.
        # The display's presence filter then yields a KPI-only table.
        ranked = ranked.drop(columns=["score"])

    show_factors = st.checkbox("Show Taguchi factors", value=False, key="show_factors")
    st.dataframe(
        prepare_ranked_display(
            ranked, goal_metrics, parameters, selected_extras, show_factors
        ),
        use_container_width=True,
        hide_index=True,
    )
    return ranked
