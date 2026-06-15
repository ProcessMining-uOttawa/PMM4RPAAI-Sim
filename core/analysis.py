"""Simulation result analysis: aggregation, Taguchi S/N, ranking, and baseline comparison."""
from __future__ import annotations
import math

import pandas as pd

from .constants import (
    COL_CYCLE_H, COL_COST, COL_CYCLE_H_MEAN, COL_COST_MEAN,
    COL_TOTAL_CYCLE_S, COL_TOTAL_COST, COL_TOTAL_CYCLE_S_MEAN, COL_TOTAL_COST_MEAN,
    COL_REWORK_COUNT, COL_REWORK_RATE, COL_REWORK_COUNT_MEAN, COL_REWORK_RATE_MEAN,
)
from .metrics import MetricDirection, MetricRegistry
from .constants import F_NUM_CASES


_NON_FACTOR_COLS = frozenset({
    "scenario_id", "replication", COL_CYCLE_H, COL_COST,
    COL_TOTAL_CYCLE_S, COL_TOTAL_COST, COL_REWORK_COUNT, COL_REWORK_RATE,
})


def aggregate(results: pd.DataFrame) -> pd.DataFrame:
    """results: scenario_id, replication, + all six metric cols (+ factor cols)."""
    factor_cols = [c for c in results.columns if c not in _NON_FACTOR_COLS]
    agg_spec: dict = {
        COL_CYCLE_H_MEAN:       (COL_CYCLE_H,       "mean"),
        "cycle_h_std":          (COL_CYCLE_H,       "std"),
        COL_COST_MEAN:          (COL_COST,          "mean"),
        "cost_std":             (COL_COST,          "std"),
        COL_TOTAL_CYCLE_S_MEAN: (COL_TOTAL_CYCLE_S, "mean"),
        COL_TOTAL_COST_MEAN:    (COL_TOTAL_COST,    "mean"),
        COL_REWORK_COUNT_MEAN:  (COL_REWORK_COUNT,  "mean"),
        COL_REWORK_RATE_MEAN:   (COL_REWORK_RATE,   "mean"),
    }
    return results.groupby(["scenario_id", *factor_cols], as_index=False).agg(**agg_spec)  # type: ignore[call-overload]


def _pct_delta(delta: float, baseline: float) -> float:
    return round(delta / baseline * 100, 1) if baseline != 0 else float("nan")


def compare_to_baseline(agg: pd.DataFrame, baseline_agg: dict[int, dict]) -> pd.DataFrame:
    """Build a display DataFrame comparing each scenario's totals to its matching baseline.

    baseline_agg maps {n_cases: {col: value}} for each aggregate MetricSpec column.
    Scenarios are grouped by their cases level; each group is preceded by its baseline row.
    """
    specs = [m.aggregate for m in MetricRegistry.all() if m.aggregate is not None]
    num_cases_col = next((c for c in agg.columns if c == F_NUM_CASES), None)
    rows: list[dict] = []
    for n_cases in sorted(baseline_agg):
        b = baseline_agg[n_cases]
        b_vals = {s.column: s.display_fn(b[s.column]) for s in specs}
        baseline_row: dict = {"Scenario": f"Baseline ({n_cases} cases)", "Cases": n_cases}
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
                    scenario_row[s.pct_change_name] = _pct_delta(delta, b_vals[s.column])
            rows.append(scenario_row)
    return pd.DataFrame(rows)


def signal_to_noise(
    values,
    direction: MetricDirection = MetricDirection.SMALLER_IS_BETTER,
) -> float:
    vals = [v for v in values if v is not None and v > 0]
    if not vals:
        return float("nan")
    if direction == MetricDirection.SMALLER_IS_BETTER:
        return -10 * math.log10(sum(v*v for v in vals) / len(vals))
    if direction == MetricDirection.LARGER_IS_BETTER:
        return -10 * math.log10(sum(1/(v*v) for v in vals) / len(vals))
    raise ValueError(direction)


def main_effects(
    results: pd.DataFrame,
    metric: str,
    direction: MetricDirection = MetricDirection.SMALLER_IS_BETTER,
) -> pd.DataFrame:
    """For each factor × level: mean metric and S/N ratio."""
    factor_cols = [c for c in results.columns if c not in _NON_FACTOR_COLS]
    rows = []
    for f in factor_cols:
        for level, sub in results.groupby(f):
            rows.append({
                "factor": f, "level": level,
                "mean": sub[metric].mean(),
                "sn": signal_to_noise(sub[metric].tolist(), direction),
            })
    return pd.DataFrame(rows)


def rank(agg: pd.DataFrame, goal_metric: str, goal_max: float) -> pd.DataFrame:
    """Adds 'goal_met' and 'score' (lower = better) ranked by a single goal metric.

    When goal_max > 0, score = metric / goal_max (ratio to target).
    When goal_max = 0, score = metric directly (raw value; ratio is undefined).
    """
    if goal_max < 0:
        raise ValueError(f"goal_max must be non-negative, got {goal_max}")
    out = agg.copy()
    out["goal_met"] = out[goal_metric].le(goal_max).fillna(False)
    if goal_max == 0:
        out["score"] = out[goal_metric].fillna(float("inf"))
    else:
        out["score"] = (out[goal_metric] / goal_max).fillna(0)
    return out.sort_values(["goal_met", "score"], ascending=[False, True])
