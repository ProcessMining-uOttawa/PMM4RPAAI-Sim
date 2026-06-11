"""Simulation result analysis: aggregation, Taguchi S/N, ranking, and baseline comparison."""
from __future__ import annotations
import math
from typing import Callable, NamedTuple

import pandas as pd

from .constants import (
    COL_CYCLE_H, COL_COST, COL_CYCLE_H_MEAN, COL_COST_MEAN,
    COL_TOTAL_CYCLE_S, COL_TOTAL_COST, COL_TOTAL_CYCLE_S_MEAN, COL_TOTAL_COST_MEAN,
    COL_REWORK_COUNT, COL_REWORK_RATE, COL_REWORK_COUNT_MEAN, COL_REWORK_RATE_MEAN,
)
from .transformations import F_NUM_CASES


_NON_FACTOR_COLS = frozenset({
    "scenario_id", "replication", COL_CYCLE_H, COL_COST,
    COL_TOTAL_CYCLE_S, COL_TOTAL_COST, COL_REWORK_COUNT, COL_REWORK_RATE,
})


class _MetricSpec(NamedTuple):
    col:         str
    label:       str
    fn:          Callable[[float], float]  # raw value → display unit
    delta_label: str
    pct_label:   str | None  # None = no relative-% column (rework rate uses pp instead)
    dp:          int = 2     # decimal places for displayed value and absolute delta


_METRICS: list[_MetricSpec] = [
    _MetricSpec(COL_TOTAL_CYCLE_S_MEAN, "Total Cycle Time (h)", lambda v: v / 3600, "Δ Time (h)",     "Δ Time (%)"),
    _MetricSpec(COL_TOTAL_COST_MEAN,    "Total Cost ($)",        lambda v: v,        "Δ Cost ($)",     "Δ Cost (%)"),
    _MetricSpec(COL_REWORK_COUNT_MEAN,  "Rework Count",          lambda v: v,        "Δ Rework Count", "Δ Rework (%)"),
    _MetricSpec(COL_REWORK_RATE_MEAN,   "Rework Rate (%)",       lambda v: v * 100,  "Δ Rate (pp)",    None,          1),
]


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

    baseline_agg maps {n_cases: {COL_TOTAL_CYCLE_S_MEAN, COL_TOTAL_COST_MEAN,
    COL_REWORK_COUNT_MEAN, COL_REWORK_RATE_MEAN}}.
    Scenarios are grouped by their cases level; each group is preceded by its baseline row.
    """
    num_cases_col = next((c for c in agg.columns if c == F_NUM_CASES), None)
    rows: list[dict] = []
    for n_cases in sorted(baseline_agg):
        b = baseline_agg[n_cases]
        b_vals = {m.col: m.fn(b[m.col]) for m in _METRICS}
        baseline_row: dict = {"Scenario": f"Baseline ({n_cases} cases)", "Cases": n_cases}
        for m in _METRICS:
            baseline_row[m.label]       = round(b_vals[m.col], m.dp)
            baseline_row[m.delta_label] = 0.0
            if m.pct_label:
                baseline_row[m.pct_label] = 0.0
        rows.append(baseline_row)
        group = agg if num_cases_col is None else agg[agg[num_cases_col] == n_cases]
        for _, row in group.iterrows():
            s_vals = {m.col: m.fn(row[m.col]) for m in _METRICS}
            scenario_row: dict = {"Scenario": row["scenario_id"], "Cases": n_cases}
            for m in _METRICS:
                delta = s_vals[m.col] - b_vals[m.col]
                scenario_row[m.label]       = round(s_vals[m.col], m.dp)
                scenario_row[m.delta_label] = round(delta, m.dp)
                if m.pct_label:
                    scenario_row[m.pct_label] = _pct_delta(delta, b_vals[m.col])
            rows.append(scenario_row)
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
