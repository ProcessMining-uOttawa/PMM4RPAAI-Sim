"""Simulation result analysis: aggregation, Taguchi S/N, ranking, and baseline comparison."""

from __future__ import annotations
import math

import pandas as pd

from .constants import (
    COL_MEAN_CYCLE_H,
    COL_MEAN_COST,
    COL_MEAN_CYCLE_H_MEAN,
    COL_MEAN_COST_MEAN,
    COL_TOTAL_CYCLE_S,
    COL_TOTAL_COST,
    COL_TOTAL_CYCLE_S_MEAN,
    COL_TOTAL_COST_MEAN,
    COL_TOTAL_REWORK_COUNT,
    COL_REWORK_RATE,
    COL_TOTAL_REWORK_COUNT_MEAN,
    COL_REWORK_RATE_MEAN,
)
from .goals import Goal
from .metrics import Metric, MetricDirection, MetricRegistry
from .constants import F_NUM_CASES


_NON_FACTOR_COLS = frozenset(
    {
        "scenario_id",
        "replication",
        COL_MEAN_CYCLE_H,
        COL_MEAN_COST,
        COL_TOTAL_CYCLE_S,
        COL_TOTAL_COST,
        COL_TOTAL_REWORK_COUNT,
        COL_REWORK_RATE,
    }
)


def _factor_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in _NON_FACTOR_COLS]


def aggregate(results: pd.DataFrame) -> pd.DataFrame:
    """results: scenario_id, replication, + all six metric cols (+ factor cols)."""
    factor_cols = _factor_cols(results)
    agg_spec: dict = {
        COL_MEAN_CYCLE_H_MEAN: (COL_MEAN_CYCLE_H, "mean"),
        "mean_cycle_h_std": (COL_MEAN_CYCLE_H, "std"),
        COL_MEAN_COST_MEAN: (COL_MEAN_COST, "mean"),
        "mean_cost_std": (COL_MEAN_COST, "std"),
        COL_TOTAL_CYCLE_S_MEAN: (COL_TOTAL_CYCLE_S, "mean"),
        COL_TOTAL_COST_MEAN: (COL_TOTAL_COST, "mean"),
        COL_TOTAL_REWORK_COUNT_MEAN: (COL_TOTAL_REWORK_COUNT, "mean"),
        COL_REWORK_RATE_MEAN: (COL_REWORK_RATE, "mean"),
    }
    return results.groupby(["scenario_id", *factor_cols], as_index=False).agg(
        **agg_spec
    )  # type: ignore[call-overload]


def _pct_delta(delta: float, baseline: float) -> float:
    return round(delta / baseline * 100, 1) if baseline != 0 else float("nan")


def compare_to_baseline(
    agg: pd.DataFrame, baseline_agg: dict[int, dict]
) -> pd.DataFrame:
    """Build a display DataFrame comparing each scenario's totals to its matching baseline.

    baseline_agg maps {n_cases: {col: value}} for each aggregate MetricSpec column.
    Scenarios are grouped by their cases level; each group is preceded by its baseline row.
    """
    specs = [m.aggregate for m in MetricRegistry.all() if m.aggregate is not None]
    num_cases_col = F_NUM_CASES if F_NUM_CASES in agg.columns else None
    rows: list[dict] = []
    for n_cases in sorted(baseline_agg):
        b = baseline_agg[n_cases]
        b_vals = {s.column: s.display_fn(b[s.column]) for s in specs}
        baseline_row: dict = {
            "Scenario": f"Baseline ({n_cases} cases)",
            "Cases": n_cases,
        }
        for s in specs:
            baseline_row[s.display_name] = round(b_vals[s.column], s.decimal_places)
            if s.delta_name is not None:
                baseline_row[s.delta_name] = 0.0
            if s.pct_change_name is not None:
                baseline_row[s.pct_change_name] = 0.0
        rows.append(baseline_row)
        group = agg if num_cases_col is None else agg[agg[num_cases_col] == n_cases]
        for _, row in group.iterrows():
            s_vals = {s.column: s.display_fn(row[s.column]) for s in specs}
            scenario_row: dict = {"Scenario": row["scenario_id"], "Cases": n_cases}
            for s in specs:
                delta = s_vals[s.column] - b_vals[s.column]
                scenario_row[s.display_name] = round(s_vals[s.column], s.decimal_places)
                if s.delta_name is not None:
                    scenario_row[s.delta_name] = round(delta, s.decimal_places)
                if s.pct_change_name is not None:
                    scenario_row[s.pct_change_name] = _pct_delta(
                        delta, b_vals[s.column]
                    )
            rows.append(scenario_row)
    return pd.DataFrame(rows)


def signal_to_noise(
    values,
    direction: MetricDirection = MetricDirection.SMALLER_IS_BETTER,
    floor: float = 0.0,
) -> float:
    vals = [v + floor for v in values if v is not None and v + floor > 0]
    if not vals:
        return float("nan")
    if direction == MetricDirection.SMALLER_IS_BETTER:
        return -10 * math.log10(sum(v * v for v in vals) / len(vals))
    if direction == MetricDirection.LARGER_IS_BETTER:
        return -10 * math.log10(sum(1 / (v * v) for v in vals) / len(vals))
    raise ValueError(direction)


def main_effects(results: pd.DataFrame, metric: Metric) -> pd.DataFrame:
    """For each factor × level: mean metric and S/N ratio."""
    if metric.per_case is None:
        raise ValueError(f"main_effects() requires a metric with per_case data; got {metric}")
    pc = metric.per_case
    col = pc.results_column
    direction = pc.mean.direction
    floor = metric.sn_floor
    rows = []
    for f in _factor_cols(results):
        for level, sub in results.groupby(f):
            rows.append(
                {
                    "factor": f,
                    "level": level,
                    "mean": sub[col].mean(),
                    "sn": signal_to_noise(sub[col].tolist(), direction, floor),
                }
            )
    return pd.DataFrame(rows)


def rank(agg: pd.DataFrame, goals: list[Goal]) -> pd.DataFrame:
    """Adds per-goal '{metric}_score' and '{metric}_met' columns, plus aggregate 'score'.

    Per-goal score: piecewise linear 0–100 (100 = target met, 50 = at baseline, 0 = at worst).
    Per-goal met: True when the goal's score reaches 100 (metric hits or beats target).
    Aggregate score: min of all per-goal scores (weakest-link rule).
    Scenarios are sorted descending by aggregate score (higher is better).
    """
    out = agg.copy()
    per_goal_scores: list[pd.Series] = []
    for goal in goals:
        goal_scores = out[goal.metric].apply(goal.score)
        out[f"{goal.metric}_score"] = goal_scores.round(1)
        out[f"{goal.metric}_met"] = goal_scores >= 100.0
        per_goal_scores.append(goal_scores)
    if per_goal_scores:
        out["score"] = pd.concat(per_goal_scores, axis=1).min(axis=1).round(1)
    else:
        out["score"] = 0.0
    return out.sort_values("score", ascending=False)
