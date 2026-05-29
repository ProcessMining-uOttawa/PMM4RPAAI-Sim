"""Aggregation + Taguchi S/N + ranking. Operates on tidy per-replication frames."""
from __future__ import annotations
import csv
import math
from pathlib import Path
import pandas as pd

from .constants import (
    PROSIMOS_SECTION_TASK_STATS, PROSIMOS_COL_TOTAL_COST,
    COL_CYCLE_H, COL_COST, COL_CYCLE_H_MEAN, COL_COST_MEAN,
)


_NON_FACTOR_COLS = frozenset({"scenario_id", "replication", COL_CYCLE_H, COL_COST})


def _parse_section(rows: list, header: str) -> tuple[list[str], list[list[str]]]:
    """Return (col_headers, data_rows) for a named section, or ([], []) if not found.
    Sections are terminated by a blank/empty row."""
    for i, r in enumerate(rows):
        if r and r[0].strip() == header:
            if i + 1 >= len(rows):
                return [], []
            col_hdrs = [c.strip() for c in rows[i + 1]]
            data = []
            for row in rows[i + 2:]:
                if not row or row == ['']:
                    break
                data.append(row)
            return col_hdrs, data
    return [], []


def per_log_metrics(log_csv: Path, stats_csv: Path | None = None) -> dict:
    """Summary metrics for one Prosimos replication.

    cycle_h: median per-case cycle time in hours (last end − first start).
    cost: average cost per case — sum of Total Cost across all tasks from
          Individual Task Statistics, divided by case count from the event log.
          None if stats unavailable or unparseable.
    """
    df = pd.read_csv(log_csv, parse_dates=["start_time", "end_time"])
    per_case = df.groupby("case_id").agg(
        start=("start_time", "min"), end=("end_time", "max"))
    cycle_h = (per_case["end"] - per_case["start"]).dt.total_seconds().div(3600)

    cost: float | None = None
    if stats_csv and Path(stats_csv).exists():
        with open(stats_csv) as f:
            rows = list(csv.reader(f))
        try:
            task_hdr, task_data = _parse_section(rows, PROSIMOS_SECTION_TASK_STATS)
            if task_hdr and task_data:
                total_cost = sum(
                    float(r[task_hdr.index(PROSIMOS_COL_TOTAL_COST)]) for r in task_data
                )
                cost = total_cost / len(per_case)
        except (ValueError, IndexError):
            pass
    return {COL_CYCLE_H: float(cycle_h.median()), COL_COST: cost}


def aggregate(results: pd.DataFrame) -> pd.DataFrame:
    """results: scenario_id, replication, cycle_h, cost (+ factor cols)."""
    factor_cols = [c for c in results.columns
                   if c not in _NON_FACTOR_COLS]
    agg = (results.groupby(["scenario_id", *factor_cols], as_index=False)
                  .agg(**{
                      COL_CYCLE_H_MEAN:  (COL_CYCLE_H, "mean"),
                      "cycle_h_std":     (COL_CYCLE_H, "std"),
                      COL_COST_MEAN:     (COL_COST,    "mean"),
                      "cost_std":        (COL_COST,    "std"),
                  }))
    return agg


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
    factor_cols = [c for c in results.columns
                   if c not in _NON_FACTOR_COLS]
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
    out = agg.copy()
    out["goal_met"] = out[goal_metric].le(goal_max).fillna(False)
    out["score"] = (out[goal_metric] / goal_max).clip(lower=0).fillna(0)
    return out.sort_values(["goal_met", "score"], ascending=[False, True])
