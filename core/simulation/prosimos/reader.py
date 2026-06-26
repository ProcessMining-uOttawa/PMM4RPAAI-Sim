"""Prosimos simulation output reader — parses event-log CSV and stats CSV."""

from __future__ import annotations
import csv
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ...constants import (
    COL_TOTAL_CYCLE_S,
    COL_TOTAL_COST,
    COL_TOTAL_REWORK_COUNT,
    COL_REWORK_RATE,
)


@dataclass(frozen=True)
class ReplicationMetrics:
    """All per-replication metrics for one Prosimos simulation run."""

    mean_cycle_h: float
    mean_cost: float
    total_cycle_s: float
    total_cost: float
    total_rework_count: float
    rework_rate: float


# ── Prosimos stats CSV: section header names ───────────────────────────────────
PROSIMOS_SECTION_TASK_STATS = "Individual Task Statistics"
PROSIMOS_SECTION_OVERALL = "Overall Scenario Statistics"

# ── Prosimos stats CSV: column and row-key lookup strings ─────────────────────
PROSIMOS_COL_TOTAL_COST = "Total Cost"  # column in SECTION_TASK_STATS
PROSIMOS_COL_ACCUMULATED = "Accumulated Value"  # column in SECTION_OVERALL
PROSIMOS_KPI_CYCLE_TIME = "cycle_time"  # KPI row key in SECTION_OVERALL


def _parse_section(rows: list, header: str) -> tuple[list[str], list[list[str]]]:
    """Return (col_headers, data_rows) for a named section, or ([], []) if not found.
    Sections are terminated by a blank/empty row."""
    for i, r in enumerate(rows):
        if r and r[0].strip() == header:
            if i + 1 >= len(rows):
                return [], []
            col_hdrs = [c.strip() for c in rows[i + 1]]
            data = []
            for row in rows[i + 2 :]:
                if not row or row == [""]:
                    break
                data.append(row)
            return col_hdrs, data
    return [], []


def _totals_from_rows(rows: list, source: Path) -> dict:
    """Strict: raises ValueError if any total metric is missing or unparseable."""
    overall_hdr, overall_data = _parse_section(rows, PROSIMOS_SECTION_OVERALL)
    if not overall_hdr or not overall_data:
        raise ValueError(f"'{PROSIMOS_SECTION_OVERALL}' not found in {source}")
    try:
        acc_idx = overall_hdr.index(PROSIMOS_COL_ACCUMULATED)
    except ValueError:
        raise ValueError(f"'{PROSIMOS_COL_ACCUMULATED}' column missing in {source}")
    cycle_row = next(
        (r for r in overall_data if r and r[0].strip() == PROSIMOS_KPI_CYCLE_TIME), None
    )
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


def _rework_metrics(
    df: pd.DataFrame,
    bot_task_name: str | None = None,
    original_task_name: str | None = None,
) -> dict:
    """Process-wide rework from an event log DataFrame.

    Counts two sources:
    - Standard rework: (occurrences - 1) for any activity appearing more than
      once in the same case.
    - Bot-failure rework: +1 per case where both bot_task_name and
      original_task_name appear (bot ran and failed, human had to redo the work).
    """
    if "activity" not in df.columns:
        return {COL_TOTAL_REWORK_COUNT: 0.0, COL_REWORK_RATE: 0.0}
    activity_counts = df.groupby(["case_id", "activity"]).size()
    excess = activity_counts[activity_counts > 1] - 1  # type: ignore[index]
    per_case: pd.Series = excess.groupby(level="case_id").sum()  # type: ignore[assignment]

    if bot_task_name and original_task_name:
        idx = activity_counts.index
        cases_with_bot = set(
            idx.get_level_values("case_id")[
                idx.get_level_values("activity") == bot_task_name
            ]
        )
        cases_with_orig = set(
            idx.get_level_values("case_id")[
                idx.get_level_values("activity") == original_task_name
            ]
        )
        bot_failure_cases = cases_with_bot & cases_with_orig
        if bot_failure_cases:
            per_case = per_case.add(
                pd.Series(1.0, index=list(bot_failure_cases), dtype=float),
                fill_value=0.0,
            )

    all_cases = df["case_id"].unique()
    per_case = per_case.reindex(all_cases, fill_value=0.0)
    return {
        COL_TOTAL_REWORK_COUNT: float(per_case.sum()),
        COL_REWORK_RATE: float((per_case > 0).mean()) * 100.0,
    }


def total_metrics(stats_csv: Path) -> dict:
    """Run-total metrics for one Prosimos replication. Raises ValueError on missing data."""
    with open(stats_csv) as f:
        rows = list(csv.reader(f))
    return _totals_from_rows(rows, stats_csv)


def replication_metrics(
    log_csv: Path,
    stats_csv: Path,
    bot_task_name: str | None = None,
    original_task_name: str | None = None,
) -> ReplicationMetrics:
    """All per-replication metrics in a single pass.

    Raises ValueError if stats are missing or malformed.
    Raises FileNotFoundError if stats_csv does not exist.
    """
    df = pd.read_csv(log_csv, parse_dates=["start_time", "end_time"])
    per_case = df.groupby("case_id").agg(
        start=("start_time", "min"), end=("end_time", "max")
    )
    cycle_h = (per_case["end"] - per_case["start"]).dt.total_seconds().div(3600)
    with open(stats_csv) as f:
        rows = list(csv.reader(f))
    totals = _totals_from_rows(rows, stats_csv)
    rework = _rework_metrics(df, bot_task_name, original_task_name)
    return ReplicationMetrics(
        mean_cycle_h=float(cycle_h.mean()),
        mean_cost=totals[COL_TOTAL_COST] / len(per_case),
        total_cycle_s=totals[COL_TOTAL_CYCLE_S],
        total_cost=totals[COL_TOTAL_COST],
        total_rework_count=rework[COL_TOTAL_REWORK_COUNT],
        rework_rate=rework[COL_REWORK_RATE],
    )
