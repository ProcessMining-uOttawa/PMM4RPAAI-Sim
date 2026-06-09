"""Simulation result analysis: aggregation, Taguchi S/N, ranking, and baseline comparison."""
from __future__ import annotations
import math

import pandas as pd

from .constants import (
    COL_CYCLE_H, COL_COST, COL_CYCLE_H_MEAN, COL_COST_MEAN,
    COL_TOTAL_CYCLE_S, COL_TOTAL_COST, COL_TOTAL_CYCLE_S_MEAN, COL_TOTAL_COST_MEAN,
    COL_REWORK_COUNT, COL_REWORK_RATE, COL_REWORK_COUNT_MEAN, COL_REWORK_RATE_MEAN,
)


_NON_FACTOR_COLS = frozenset({
    "scenario_id", "replication", COL_CYCLE_H, COL_COST,
    COL_TOTAL_CYCLE_S, COL_TOTAL_COST, COL_REWORK_COUNT, COL_REWORK_RATE,
})


def aggregate(results: pd.DataFrame) -> pd.DataFrame:
    """results: scenario_id, replication, cycle_h, cost (+ factor cols)."""
    factor_cols = [c for c in results.columns if c not in _NON_FACTOR_COLS]
    agg_spec: dict = {
        COL_CYCLE_H_MEAN: (COL_CYCLE_H, "mean"),
        "cycle_h_std":    (COL_CYCLE_H, "std"),
        COL_COST_MEAN:    (COL_COST,    "mean"),
        "cost_std":       (COL_COST,    "std"),
    }
    if COL_TOTAL_CYCLE_S in results.columns:
        agg_spec[COL_TOTAL_CYCLE_S_MEAN] = (COL_TOTAL_CYCLE_S, "mean")
    if COL_TOTAL_COST in results.columns:
        agg_spec[COL_TOTAL_COST_MEAN] = (COL_TOTAL_COST, "mean")
    if COL_REWORK_COUNT in results.columns:
        agg_spec[COL_REWORK_COUNT_MEAN] = (COL_REWORK_COUNT, "mean")
    if COL_REWORK_RATE in results.columns:
        agg_spec[COL_REWORK_RATE_MEAN] = (COL_REWORK_RATE, "mean")
    return results.groupby(["scenario_id", *factor_cols], as_index=False).agg(**agg_spec)  # type: ignore[call-overload]


def _pct_delta(delta: float, baseline: float) -> float:
    return round(delta / baseline * 100, 1) if baseline != 0 else float("nan")


def compare_to_baseline(agg: pd.DataFrame, baseline_agg: dict[int, dict]) -> pd.DataFrame:
    """Build a display DataFrame comparing each scenario's totals to its matching baseline.

    baseline_agg maps {n_cases: {COL_TOTAL_CYCLE_S_MEAN, COL_TOTAL_COST_MEAN,
    COL_REWORK_COUNT_MEAN, COL_REWORK_RATE_MEAN}}.
    Scenarios are grouped by their cases level; each group is preceded by its baseline row.
    """
    num_cases_col = next((c for c in agg.columns if c.endswith(".num_cases")), None)
    rows: list[dict] = []
    for n_cases in sorted(baseline_agg):
        b = baseline_agg[n_cases]
        b_cycle_h      = b[COL_TOTAL_CYCLE_S_MEAN] / 3600
        b_cost         = b[COL_TOTAL_COST_MEAN]
        b_rework_count = b.get(COL_REWORK_COUNT_MEAN, float("nan"))
        b_rework_rate  = b.get(COL_REWORK_RATE_MEAN,  float("nan"))
        rows.append({"Scenario": f"Baseline ({n_cases} cases)",
                     "Cases": n_cases,
                     "Total Cycle Time (h)": round(b_cycle_h, 2),
                     "Δ Time (h)": 0.0, "Δ Time (%)": 0.0,
                     "Total Cost ($)": round(b_cost, 2),
                     "Δ Cost ($)": 0.0, "Δ Cost (%)": 0.0,
                     "Rework Count": round(b_rework_count, 2),
                     "Δ Rework Count": 0.0, "Δ Rework (%)": 0.0,
                     "Rework Rate (%)": round(b_rework_rate * 100, 1),
                     "Δ Rate (pp)": 0.0})
        group = agg if num_cases_col is None else agg[agg[num_cases_col] == n_cases]
        for _, row in group.iterrows():
            s_cycle_h      = row[COL_TOTAL_CYCLE_S_MEAN] / 3600
            s_cost         = row[COL_TOTAL_COST_MEAN]
            s_rework_count = row.get(COL_REWORK_COUNT_MEAN, float("nan"))
            s_rework_rate  = row.get(COL_REWORK_RATE_MEAN,  float("nan"))
            d_cycle        = s_cycle_h - b_cycle_h
            d_cost         = s_cost - b_cost
            d_rework_count = s_rework_count - b_rework_count
            d_rework_rate  = s_rework_rate  - b_rework_rate
            rows.append({
                "Scenario":             row["scenario_id"],
                "Cases":                n_cases,
                "Total Cycle Time (h)": round(s_cycle_h, 2),
                "Δ Time (h)":           round(d_cycle, 2),
                "Δ Time (%)":           _pct_delta(d_cycle, b_cycle_h),
                "Total Cost ($)":       round(s_cost, 2),
                "Δ Cost ($)":           round(d_cost, 2),
                "Δ Cost (%)":           _pct_delta(d_cost, b_cost),
                "Rework Count":         round(s_rework_count, 2),
                "Δ Rework Count":       round(d_rework_count, 2),
                "Δ Rework (%)":         _pct_delta(d_rework_count, b_rework_count),
                "Rework Rate (%)":      round(s_rework_rate * 100, 1),
                "Δ Rate (pp)":          round(d_rework_rate * 100, 1),
            })
    return pd.DataFrame(rows)


def signal_to_noise(values, kind="smaller_is_better") -> float:
    vals = [v for v in values if v is not None and v > 0]
    if not vals:
        return float("nan")
    if kind == "smaller_is_better":
        return -10 * math.log10(sum(v*v for v in vals) / len(vals))
    if kind == "larger_is_better":
        return -10 * math.log10(sum(1/(v*v) for v in vals) / len(vals))
    raise ValueError(kind)


def main_effects(results: pd.DataFrame, metric: str,
                 kind: str = "smaller_is_better") -> pd.DataFrame:
    """For each factor × level: mean metric and S/N ratio."""
    factor_cols = [c for c in results.columns if c not in _NON_FACTOR_COLS]
    rows = []
    for f in factor_cols:
        for level, sub in results.groupby(f):
            rows.append({
                "factor": f, "level": level,
                "mean": sub[metric].mean(),
                "sn": signal_to_noise(sub[metric].tolist(), kind),
            })
    return pd.DataFrame(rows)


def rank(agg: pd.DataFrame, goal_metric: str, goal_max: float) -> pd.DataFrame:
    """Adds 'goal_met' and 'score' (lower = better) ranked by a single goal metric."""
    if goal_max <= 0:
        raise ValueError(f"goal_max must be positive, got {goal_max}")
    out = agg.copy()
    out["goal_met"] = out[goal_metric].le(goal_max).fillna(False)
    out["score"] = (out[goal_metric] / goal_max).fillna(0)
    return out.sort_values(["goal_met", "score"], ascending=[False, True])
