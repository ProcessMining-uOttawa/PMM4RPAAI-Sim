"""Aggregation + Taguchi S/N + ranking. Operates on tidy per-replication frames."""
from __future__ import annotations
import csv
import math
from pathlib import Path
import pandas as pd

from .constants import (
    PROSIMOS_SECTION_TASK_STATS, PROSIMOS_COL_TOTAL_COST,
    PROSIMOS_SECTION_OVERALL, PROSIMOS_COL_ACCUMULATED, PROSIMOS_KPI_CYCLE_TIME,
    COL_CYCLE_H, COL_COST, COL_CYCLE_H_MEAN, COL_COST_MEAN,
    COL_TOTAL_CYCLE_S, COL_TOTAL_COST, COL_TOTAL_CYCLE_S_MEAN, COL_TOTAL_COST_MEAN,
)


_NON_FACTOR_COLS = frozenset({
    "scenario_id", "replication", COL_CYCLE_H, COL_COST,
    COL_TOTAL_CYCLE_S, COL_TOTAL_COST,
})


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


def _cost_from_rows(rows: list, n_cases: int) -> float | None:
    """Lenient: returns None if cost data is missing or unparseable."""
    try:
        task_hdr, task_data = _parse_section(rows, PROSIMOS_SECTION_TASK_STATS)
        if task_hdr and task_data:
            total = sum(float(r[task_hdr.index(PROSIMOS_COL_TOTAL_COST)]) for r in task_data)
            return total / n_cases
    except (ValueError, IndexError):
        pass
    return None


def _totals_from_rows(rows: list, source: Path) -> dict:
    """Strict: raises ValueError if any total metric is missing or unparseable."""
    overall_hdr, overall_data = _parse_section(rows, PROSIMOS_SECTION_OVERALL)
    if not overall_hdr or not overall_data:
        raise ValueError(f"'{PROSIMOS_SECTION_OVERALL}' not found in {source}")
    try:
        acc_idx = overall_hdr.index(PROSIMOS_COL_ACCUMULATED)
    except ValueError:
        raise ValueError(f"'{PROSIMOS_COL_ACCUMULATED}' column missing in {source}")
    cycle_row = next((r for r in overall_data if r and r[0].strip() == PROSIMOS_KPI_CYCLE_TIME), None)
    if cycle_row is None:
        raise ValueError(f"'{PROSIMOS_KPI_CYCLE_TIME}' KPI not found in {source}")
    total_cycle_s = float(cycle_row[acc_idx])

    task_hdr, task_data = _parse_section(rows, PROSIMOS_SECTION_TASK_STATS)
    if not task_hdr or not task_data:
        raise ValueError(f"'{PROSIMOS_SECTION_TASK_STATS}' not found in {source}")
    try:
        cost_idx = task_hdr.index(PROSIMOS_COL_TOTAL_COST)
    except ValueError:
        raise ValueError(f"'{PROSIMOS_COL_TOTAL_COST}' column missing in {source}")
    total_cost = 0.0
    for r in task_data:
        try:
            total_cost += float(r[cost_idx])
        except (ValueError, IndexError):
            raise ValueError(f"Non-numeric Total Cost in {source}: {r}")
    return {COL_TOTAL_CYCLE_S: total_cycle_s, COL_TOTAL_COST: total_cost}


def per_log_metrics(log_csv: Path, stats_csv: Path | None = None) -> dict:
    """Summary metrics for one Prosimos replication.

    cycle_h: median per-case cycle time in hours (last end − first start).
    cost: average cost per case — None if stats unavailable or unparseable.
    """
    df = pd.read_csv(log_csv, parse_dates=["start_time", "end_time"])
    per_case = df.groupby("case_id").agg(
        start=("start_time", "min"), end=("end_time", "max"))
    cycle_h = (per_case["end"] - per_case["start"]).dt.total_seconds().div(3600)

    cost: float | None = None
    if stats_csv and Path(stats_csv).exists():
        with open(stats_csv) as f:
            rows = list(csv.reader(f))
        cost = _cost_from_rows(rows, len(per_case))
    return {COL_CYCLE_H: float(cycle_h.median()), COL_COST: cost}


def total_metrics(stats_csv: Path) -> dict:
    """Run-total metrics for one Prosimos replication. Raises ValueError on missing data."""
    with open(stats_csv) as f:
        rows = list(csv.reader(f))
    return _totals_from_rows(rows, stats_csv)


def replication_metrics(log_csv: Path, stats_csv: Path) -> dict:
    """All per-replication metrics in a single stats CSV parse.

    Returns COL_CYCLE_H, COL_COST, COL_TOTAL_CYCLE_S, COL_TOTAL_COST.
    Raises ValueError if total metrics are missing (delegates to _totals_from_rows).
    """
    df = pd.read_csv(log_csv, parse_dates=["start_time", "end_time"])
    per_case = df.groupby("case_id").agg(
        start=("start_time", "min"), end=("end_time", "max"))
    cycle_h = (per_case["end"] - per_case["start"]).dt.total_seconds().div(3600)
    with open(stats_csv) as f:
        rows = list(csv.reader(f))
    return {
        COL_CYCLE_H: float(cycle_h.median()),
        COL_COST: _cost_from_rows(rows, len(per_case)),
        **_totals_from_rows(rows, stats_csv),
    }


def aggregate(results: pd.DataFrame) -> pd.DataFrame:
    """results: scenario_id, replication, cycle_h, cost (+ factor cols)."""
    factor_cols = [c for c in results.columns
                   if c not in _NON_FACTOR_COLS]
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
    return results.groupby(["scenario_id", *factor_cols], as_index=False).agg(**agg_spec)  # type: ignore[call-overload]


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
    if goal_max <= 0:
        raise ValueError(f"goal_max must be positive, got {goal_max}")
    out = agg.copy()
    out["goal_met"] = out[goal_metric].le(goal_max).fillna(False)
    out["score"] = (out[goal_metric] / goal_max).fillna(0)
    return out.sort_values(["goal_met", "score"], ascending=[False, True])
