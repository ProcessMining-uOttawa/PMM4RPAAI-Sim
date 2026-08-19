"""Interactive main-effects charts for the Main effects tab (Panel 5 · Results).

Part of ui/interactive/, so this module renders st.* widgets directly. It shows one
tab per rankable metric, each with a faceted main-effects chart. Consumes the pure
ui/plots helpers (factor_label_map, main_effects_chart) — a ui/interactive -> ui/
(presentation primitives) dependency. Has no pure surface, so it is exercised
manually like app.py rather than unit-tested.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from core.analysis import main_effects
from core.metrics import MetricRegistry
from core.parameters import Parameter
from ui.plots import factor_label_map, main_effects_chart


def render_main_effects(results: pd.DataFrame, parameters: list[Parameter]) -> None:
    """Render one main-effects chart tab per rankable metric."""
    label_map = factor_label_map(parameters)
    metrics = MetricRegistry.rankable()
    labels = [metric.per_case_display_name for metric in metrics]
    tabs = st.tabs(labels)
    for tab, metric, label in zip(tabs, metrics, labels):
        with tab:
            effects = main_effects(results, metric)
            if effects.empty:
                st.caption(
                    "Every factor was held constant in this run — "
                    "no main effects to plot."
                )
                continue
            st.plotly_chart(
                main_effects_chart(effects, label_map, label),
                use_container_width=True,
            )
