"""Aggregation + Taguchi S/N + ranking. Operates on tidy per-replication frames."""
from __future__ import annotations
import csv, math
from pathlib import Path
import pandas as pd


def per_log_metrics(log_csv: Path, stats_csv: Path | None = None) -> dict:
    """Summary metrics for one Prosimos replication.

    cycle_h: median per-case cycle time in hours (last end − first start).
    cost: from Scenario Statistics block of the stats CSV if present, else 0.
    """
    df = pd.read_csv(log_csv, parse_dates=["start_time", "end_time"])
    per_case = df.groupby("case_id").agg(
        start=("start_time", "min"), end=("end_time", "max"))
    cycle_h = (per_case["end"] - per_case["start"]).dt.total_seconds().div(3600)

    cost: float | None = None
    if stats_csv and Path(stats_csv).exists():
        with open(stats_csv) as f:
            rows = list(csv.reader(f))
        for i, r in enumerate(rows):
            if r and r[0].strip().lower() == "scenario statistics":
                if i+2 < len(rows):
                    hdr, data = rows[i+1], rows[i+2]
                    try:
                        cost = float(data[hdr.index("Average Cost")])
                    except (ValueError, IndexError):
                        pass
                break
    return {"cycle_h": float(cycle_h.median()), "cost": cost}


def aggregate(results: pd.DataFrame) -> pd.DataFrame:
    """results: scenario_id, replication, cycle_h, cost (+ factor cols)."""
    factor_cols = [c for c in results.columns
                   if c not in {"scenario_id", "replication", "cycle_h", "cost"}]
    agg = (results.groupby(["scenario_id", *factor_cols], as_index=False)
                  .agg(cycle_h_mean=("cycle_h", "mean"),
                       cycle_h_std=("cycle_h", "std"),
                       cost_mean=("cost", "mean"),
                       cost_std=("cost", "std")))
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
                   if c not in {"scenario_id", "replication", "cycle_h", "cost"}]
    rows = []
    for f in factor_cols:
        for level, sub in results.groupby(f):
            rows.append({
                "factor": f, "level": level,
                "mean": sub[metric].mean(),
                "sn": signal_to_noise(sub[metric].tolist(), kind),
            })
    return pd.DataFrame(rows)


def rank(agg: pd.DataFrame, goals: dict) -> pd.DataFrame:
    """goals: {'cycle_h_mean': {'max': 24}, 'cost_mean': {'max': 40}}.
    Adds 'goals_met' and 'score' (lower = better, scaled distance to targets)."""
    out = agg.copy()
    met = pd.Series(True, index=out.index)
    score = pd.Series(0.0, index=out.index)
    for col, g in goals.items():
        if "max" in g:
            met &= out[col].le(g["max"]).fillna(False)
            score += (out[col] / g["max"]).clip(lower=0).fillna(0)
    out["goals_met"] = met
    out["score"] = score
    return out.sort_values(["goals_met", "score"], ascending=[False, True])
