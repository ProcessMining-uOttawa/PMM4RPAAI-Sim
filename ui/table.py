"""Ranked-scenario table preparation for Panel 4."""

from __future__ import annotations

import pandas as pd

from core.metrics import Metric, MetricRegistry
from core.parameters import Parameter


def prepare_ranked_display(
    ranked: pd.DataFrame,
    goal_metrics: list[Metric],
    params: list[Parameter],
    show_factors: bool = False,
) -> pd.DataFrame:
    """Return a display-ready DataFrame from the ranked output of analysis.rank().

    Columns included, in order:
      rank · Scenario · [factor cols] · per-case KPI means ·
      per-goal score (0–100) · per-goal met flags · overall score
    """
    include: list[tuple[str, str]] = [("scenario_id", "Scenario")]

    if show_factors:
        include += [(p.id, p.label) for p in params if not p.frozen]

    for m in MetricRegistry.rankable():
        col_r, name_r = m.per_case_column, m.per_case_display_name
        assert (
            col_r is not None and name_r is not None
        )  # rankable() guarantees per_case
        include.append((col_r, name_r))

    met_cols: list[str] = []
    for m in goal_metrics:
        col = m.per_case_column
        label = m.per_case_compact_label
        assert (
            col is not None and label is not None
        )  # goal_metrics are rankable metrics with per_case
        met_col = f"{col}_met"
        include.append((f"{col}_score", f"{label} Score"))
        include.append((met_col, f"{label} ✓"))
        met_cols.append(met_col)

    include.append(("score", "Overall Score"))

    src_cols = [col for col, _ in include if col in ranked.columns]
    rename = {col: name for col, name in include if col in ranked.columns}

    result = ranked[src_cols].copy()
    for met_col in met_cols:
        if met_col in result.columns:
            result[met_col] = result[met_col].map({True: "✓", False: "✗"})

    result.insert(0, "rank", range(1, len(result) + 1))
    return result.rename(columns=rename)
