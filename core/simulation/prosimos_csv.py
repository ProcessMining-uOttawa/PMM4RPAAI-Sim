"""Prosimos simulation output reader — parses event-log CSV and stats CSV."""
from __future__ import annotations
import csv
from pathlib import Path

import pandas as pd

from ..constants import (
    COL_CYCLE_H, COL_COST, COL_TOTAL_CYCLE_S, COL_TOTAL_COST,
    COL_REWORK_COUNT, COL_REWORK_RATE,
)

# ── Prosimos stats CSV: section header names ───────────────────────────────────
PROSIMOS_SECTION_TASK_STATS = "Individual Task Statistics"
PROSIMOS_SECTION_OVERALL    = "Overall Scenario Statistics"

# ── Prosimos stats CSV: column and row-key lookup strings ─────────────────────
PROSIMOS_COL_TOTAL_COST  = "Total Cost"        # column in SECTION_TASK_STATS
PROSIMOS_COL_ACCUMULATED = "Accumulated Value"  # column in SECTION_OVERALL
PROSIMOS_KPI_CYCLE_TIME  = "cycle_time"         # KPI row key in SECTION_OVERALL


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


def _rework_metrics(df: pd.DataFrame,
                    bot_task_name: str | None = None,
                    original_task_name: str | None = None) -> dict:
    """Process-wide rework from an event log DataFrame.

    Counts two sources:
    - Standard rework: (occurrences - 1) for any activity appearing more than
      once in the same case.
    - Bot-failure rework: +1 per case where both bot_task_name and
      original_task_name appear (bot ran and failed, human had to redo the work).
    """
    if "activity" not in df.columns:
        return {COL_REWORK_COUNT: 0.0, COL_REWORK_RATE: 0.0}
    activity_counts = df.groupby(["case_id", "activity"]).size()
    excess = activity_counts[activity_counts > 1] - 1
    per_case: pd.Series = (
        excess.groupby(level="case_id").sum()
        if not excess.empty
        else pd.Series(dtype=float)
    )

    if bot_task_name and original_task_name:
        acts_per_case = df.groupby("case_id")["activity"].apply(set)
        bot_failure = acts_per_case.apply(
            lambda acts: bot_task_name in acts and original_task_name in acts
        ).astype(float)
        per_case = per_case.add(bot_failure, fill_value=0.0)

    all_cases = df["case_id"].unique()
    per_case = per_case.reindex(all_cases, fill_value=0.0)
    return {
        COL_REWORK_COUNT: float(per_case.sum()),
        COL_REWORK_RATE:  float((per_case > 0).mean()),
    }


def rework_metrics(log_csv: Path,
                   bot_task_name: str | None = None,
                   original_task_name: str | None = None) -> dict:
    """Rework metrics for one replication. Thin file-reading wrapper over _rework_metrics."""
    df = pd.read_csv(log_csv)
    return _rework_metrics(df, bot_task_name, original_task_name)


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


def replication_metrics(log_csv: Path, stats_csv: Path,
                        bot_task_name: str | None = None,
                        original_task_name: str | None = None) -> dict:
    """All per-replication metrics in a single pass.

    Returns COL_CYCLE_H, COL_COST, COL_TOTAL_CYCLE_S, COL_TOTAL_COST,
    COL_REWORK_COUNT, COL_REWORK_RATE.
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
        **_rework_metrics(df, bot_task_name, original_task_name),
    }
