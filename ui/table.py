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
      rank · Scenario · [factor cols] · per-case KPI means (+ the median second
      factor when the two-factor time goal is active) · per-goal score (0–100) ·
      overall score
    """
    include: list[tuple[str, str]] = [("scenario_id", "Scenario")]

    if show_factors:
        include += [(p.id, p.label) for p in params if not p.frozen]

    for m in MetricRegistry.rankable():
        include.append((m.per_case_column, m.per_case_display_name))
        # The two-factor time goal's median second factor, shown beside its
        # primary when that goal is active so its input to the combined score is
        # visible (dropped by the presence filter below if not in `ranked`).
        second = MetricRegistry.second_factor(m)
        if second is not None and m in goal_metrics:
            include.append((second.per_case_column, second.per_case_display_name))

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
