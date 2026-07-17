"""Ranked-scenario table preparation for the Ranking tab (Panel 5)."""

from __future__ import annotations

import pandas as pd

from core.metrics import IndicatorSpec, Metric, MetricRegistry
from core.parameters import Parameter


def prepare_ranked_display(
    ranked: pd.DataFrame,
    goal_metrics: list[Metric],
    params: list[Parameter],
    selected_extras: dict[str, list[IndicatorSpec]],
    show_factors: bool = False,
) -> pd.DataFrame:
    """Return a display-ready DataFrame from the ranked output of analysis.rank().

    Columns included, in order:
      rank · Scenario · [factor cols] · per-case KPI means (+ each selected extra
      indicator beside its metric) · per-goal score (0–100) · overall score

    selected_extras maps a metric's default-indicator column to the extra
    indicators the user chose for it (keyed by column string, so the st.selectbox
    value-copy identity trap cannot bite).
    """
    include: list[tuple[str, str]] = [("scenario_id", "Scenario")]

    if show_factors:
        include += [(p.id, p.label) for p in params if not p.frozen]

    for m in MetricRegistry.rankable():
        include.append((m.per_case_column, m.per_case_display_name))
        # Each selected extra indicator, shown right after its metric's default
        # KPI so its input to the combined score is visible (dropped by the
        # presence filter below if the column is not in `ranked`).
        for extra in selected_extras.get(m.per_case_column, []):
            include.append((extra.mean.column, extra.mean.display_name))

    for m in goal_metrics:
        include.append(
            (f"{m.per_case_column}_score", f"{m.per_case_compact_label} Score")
        )

    include.append(("score", "Overall Score"))

    present = [(col, name) for col, name in include if col in ranked.columns]
    src_cols = [col for col, _ in present]
    rename = dict(present)

    result = ranked[src_cols].copy()
    result.insert(0, "rank", range(1, len(result) + 1))
    return result.rename(columns=rename)
