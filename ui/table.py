"""Ranked-scenario table preparation for Panel 4."""

from __future__ import annotations

import pandas as pd

from core.goals import Goal
from core.metrics import MetricRegistry
from core.parameters import Parameter


def prepare_ranked_display(
    ranked: pd.DataFrame,
    goals: list[Goal],
    params: list[Parameter],
    show_factors: bool = False,
) -> pd.DataFrame:
    """Return a display-ready DataFrame from the ranked output of analysis.rank().

    Columns included, in order:
      rank · scenario_id · [factor cols] · per-case KPI means · per-goal met flags
    """
    include: list[tuple[str, str]] = [("scenario_id", "Scenario")]

    if show_factors:
        include += [(p.id, p.label) for p in params if not p.frozen]

    for m in MetricRegistry.rankable():
        include.append((m.per_case_column, m.per_case_display_name))  # type: ignore[arg-type]

    for g in goals:
        if g.weight == 0:
            continue
        met_col = f"{g.metric}_met"
        if met_col not in ranked.columns:
            continue
        spec = MetricRegistry.by_column(g.metric)
        label = ((spec.short_label or spec.display_name) if spec else g.metric) + " ✓"
        include.append((met_col, label))

    src_cols = [col for col, _ in include if col in ranked.columns]
    rename = {col: name for col, name in include if col in ranked.columns}

    result = ranked[src_cols].copy()
    for g in goals:
        col = f"{g.metric}_met"
        if g.weight != 0 and col in result.columns:
            result[col] = result[col].map({True: "✓", False: "✗"})

    result.insert(0, "rank", range(1, len(result) + 1))
    return result.rename(columns=rename)
