"""Display-table preparation: the Panel 5 ranked table and the fidelity panel's
per-replication and comparison tables. No st.* calls — plain DataFrames in and
out, testable without Streamlit."""

from __future__ import annotations

import pandas as pd

from core.constants import COL_MAX_CYCLE_H, COL_MIN_CYCLE_H
from core.metrics import IndicatorSpec, Metric, MetricRegistry
from core.parameters import Parameter

# Extreme order statistics are per-replication noise, not model information —
# the same reasoning that keeps them out of the fidelity comparison (see
# analysis.fidelity_table). They stay registered (goal indicators in the
# experiment flow); only this display culls them.
_EXCLUDED_REPLICATION_COLS = frozenset({COL_MIN_CYCLE_H, COL_MAX_CYCLE_H})


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


def prepare_replication_display(results: pd.DataFrame) -> pd.DataFrame:
    """Display-named per-replication table for the fidelity panel.

    One row per as-discovered replication, one column per registered indicator
    minus the min/max cycle extremes (exclusion-based, so a new indicator still
    appears with no edit here). Run totals are deliberately absent — at a fixed
    case count per replication they are the per-case means rescaled — and bot
    failures have no indicator, which rightly excludes them from a patternless
    run.
    """
    out = pd.DataFrame({"Replication": results["replication"]})
    for metric in MetricRegistry.all():
        for indicator in metric.indicators:
            if indicator.results_column in _EXCLUDED_REPLICATION_COLS:
                continue
            spec = indicator.mean
            out[spec.display_name] = (
                results[indicator.results_column]
                .map(spec.display_fn)
                .round(spec.decimal_places)
            )
    return out


def prepare_fidelity_display(fidelity: pd.DataFrame, n_reps: int) -> pd.DataFrame:
    """Format analysis.fidelity_table()'s numeric frame for display.

    Folds the Model (mean)/(std) columns into one "mean ± std" string column —
    the per-replication std is the yardstick for whether Δ is systematic misfit
    or run-to-run noise, so it renders beside the mean rather than as a separate
    column. A single replication has no std (NaN) and renders an em dash.
    """

    def _mean_pm_std(mean: float, std: float) -> str:
        return f"{mean} ± {'—' if pd.isna(std) else std}"

    return pd.DataFrame(
        {
            "Metric": fidelity["Metric"],
            "Log (observed)": fidelity["Log (observed)"],
            f"Model (mean ± std of {n_reps} reps)": [
                _mean_pm_std(mean, std)
                for mean, std in zip(fidelity["Model (mean)"], fidelity["Model (std)"])
            ],
            "Δ": fidelity["Δ"],
            "Δ %": fidelity["Δ %"],
        }
    )
