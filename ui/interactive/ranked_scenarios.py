"""Interactive ranked-scenarios table for Panel 4.

Part of ui/interactive/, so this module renders st.* widgets directly. It resolves
goal targets from the baseline, ranks scenarios, and renders the "Show Taguchi
factors" checkbox + ranked table. Consumes the pure ui/table helper — a
ui/interactive -> ui/ (presentation primitives) dependency. Has no pure surface, so
it is exercised manually like app.py rather than unit-tested.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from core import analysis, demo
from core.goals import Goal, baseline_per_case
from core.metrics import Metric
from core.parameters import Parameter
from ui.table import prepare_ranked_display


def render_ranked_scenarios(
    agg: pd.DataFrame,
    goal_specs: list[Metric],
    parameters: list[Parameter],
    baseline_agg: dict[int, dict] | None,
    demo_mode: bool,
) -> pd.DataFrame:
    """Render the goal-scored ranked-scenarios table.

    Returns the ranked DataFrame (also used by app.py for the Statistics CSV
    export). Goal targets come from the baseline. In demo mode there is no real
    baseline, so demo constants are the correct reference. In real mode a missing
    baseline means every baseline replication failed — refuse to score goals
    against fabricated demo targets, and say so loudly.
    """
    if baseline_agg is not None:
        baseline: dict[str, float] | None = baseline_per_case(baseline_agg)
    elif demo_mode:
        baseline = baseline_per_case(demo.demo_baseline_agg())
    else:
        baseline = None

    if baseline is None:
        st.error(
            "Goal scoring is unavailable — all baseline replications failed, so "
            "there are no real targets to score against. Re-run to restore goal "
            "rankings. Scenario KPIs, main effects, and exports below remain valid.",
            icon="🚫",
        )
        goals: list[Goal] = []
    else:
        goals = [Goal.from_metric(metric, baseline) for metric in goal_specs]
    ranked = analysis.rank(agg, goals)

    show_factors = st.checkbox("Show Taguchi factors", value=False, key="show_factors")
    st.dataframe(
        prepare_ranked_display(ranked, goal_specs, parameters, show_factors),
        use_container_width=True,
        hide_index=True,
    )
    return ranked
