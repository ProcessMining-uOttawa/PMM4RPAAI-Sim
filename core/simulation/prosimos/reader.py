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
    median_cycle_h: float
    mean_cost: float
    total_cycle_s: float
    total_cost: float
    total_rework_count: float
    rework_rate: float
    total_bot_failure_count: float


# ── Prosimos stats CSV: section header names ───────────────────────────────────
PROSIMOS_SECTION_TASK_STATS = "Individual Task Statistics"
PROSIMOS_SECTION_OVERALL = "Overall Scenario Statistics"

# ── Prosimos stats CSV: column and row-key lookup strings ─────────────────────
PROSIMOS_COL_TOTAL_COST = "Total Cost"  # column in SECTION_TASK_STATS
PROSIMOS_COL_ACCUMULATED = "Accumulated Value"  # column in SECTION_OVERALL
PROSIMOS_KPI_CYCLE_TIME = "cycle_time"  # KPI row key in SECTION_OVERALL


def _parse_section(rows: list, header: str) -> tuple[list[str], list[list[str]]]:
    """Return (column_headers, data_rows) for a named section, or ([], []) if not found.
    Sections are terminated by a blank/empty row."""
    for header_index, row in enumerate(rows):
        if row and row[0].strip() == header:
            if header_index + 1 >= len(rows):
                return [], []
            column_headers = [cell.strip() for cell in rows[header_index + 1]]
            data_rows = []
            for data_row in rows[header_index + 2 :]:
                if not data_row or data_row == [""]:
                    break
                data_rows.append(data_row)
            return column_headers, data_rows
    return [], []


def _require_section(
    rows: list, header: str, source: Path
) -> tuple[list[str], list[list[str]]]:
    """Return a named section's (headers, data), or raise if it is absent/empty."""
    column_headers, data_rows = _parse_section(rows, header)
    if not column_headers or not data_rows:
        raise ValueError(f"'{header}' not found in {source}")
    return column_headers, data_rows


def _require_column(headers: list[str], column: str, source: Path) -> int:
    """Return the index of a required column, or raise if it is absent."""
    try:
        return headers.index(column)
    except ValueError:
        raise ValueError(f"'{column}' column missing in {source}")


def _rework_metrics(event_log: pd.DataFrame) -> dict:
    """Process-wide repeated-activity rework from an event log DataFrame.

    Counts (occurrences - 1) for any activity appearing more than once in the
    same case. Bot failures are deliberately NOT rework — they are tracked
    separately by _bot_failure_count().
    """
    if "activity" not in event_log.columns:
        return {COL_TOTAL_REWORK_COUNT: 0.0, COL_REWORK_RATE: 0.0}

    # Each repeat of an activity within a case counts once.
    activity_counts = event_log.groupby(["case_id", "activity"]).size()
    excess = activity_counts[activity_counts > 1] - 1  # type: ignore[index]
    rework_per_case: pd.Series = excess.groupby(level="case_id").sum()  # type: ignore[assignment]

    # Restore cases with no rework so the rate denominator is every case.
    rework_per_case = rework_per_case.reindex(
        event_log["case_id"].unique(), fill_value=0.0
    )
    return {
        COL_TOTAL_REWORK_COUNT: float(rework_per_case.sum()),
        COL_REWORK_RATE: float((rework_per_case > 0).mean()) * 100.0,
    }


def _bot_failure_count(
    event_log: pd.DataFrame,
    bot_task_name: str | None,
    original_task_name: str | None,
) -> float:
    """Cases where the bot ran AND a human redid the work (both tasks appear).

    Binary per case: a case counts once regardless of how often the pair
    appears. Returns 0.0 when the task names are unknown or the log has no
    activity column.
    """
    if not bot_task_name or not original_task_name:
        return 0.0
    if "activity" not in event_log.columns:
        return 0.0
    cases_with_bot = set(
        event_log.loc[event_log["activity"] == bot_task_name, "case_id"]
    )
    cases_with_original = set(
        event_log.loc[event_log["activity"] == original_task_name, "case_id"]
    )
    return float(len(cases_with_bot & cases_with_original))


def total_metrics(stats_csv: Path) -> dict:
    """Run-total metrics for one Prosimos replication.

    Strict: raises ValueError if any total metric is missing or unparseable,
    FileNotFoundError if stats_csv does not exist.
    """
    with open(stats_csv) as f:
        rows = list(csv.reader(f))

    overall_headers, overall_rows = _require_section(
        rows, PROSIMOS_SECTION_OVERALL, stats_csv
    )
    accumulated_index = _require_column(
        overall_headers, PROSIMOS_COL_ACCUMULATED, stats_csv
    )
    cycle_row = next(
        (
            row
            for row in overall_rows
            if row and row[0].strip() == PROSIMOS_KPI_CYCLE_TIME
        ),
        None,
    )
    if cycle_row is None:
        raise ValueError(f"'{PROSIMOS_KPI_CYCLE_TIME}' KPI not found in {stats_csv}")
    total_cycle_s = float(cycle_row[accumulated_index])

    task_headers, task_rows = _require_section(
        rows, PROSIMOS_SECTION_TASK_STATS, stats_csv
    )
    cost_index = _require_column(task_headers, PROSIMOS_COL_TOTAL_COST, stats_csv)
    total_cost = 0.0
    for row in task_rows:
        try:
            total_cost += float(row[cost_index])
        except (ValueError, IndexError):
            raise ValueError(f"Non-numeric Total Cost in {stats_csv}: {row}")
    return {COL_TOTAL_CYCLE_S: total_cycle_s, COL_TOTAL_COST: total_cost}


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
    event_log = pd.read_csv(log_csv, parse_dates=["start_time", "end_time"])
    per_case = event_log.groupby("case_id").agg(
        start=("start_time", "min"), end=("end_time", "max")
    )
    cycle_h = (per_case["end"] - per_case["start"]).dt.total_seconds().div(3600)
    totals = total_metrics(stats_csv)
    rework = _rework_metrics(event_log)
    return ReplicationMetrics(
        mean_cycle_h=float(cycle_h.mean()),
        # median is a scoring-only second factor; it feeds no total (see constants)
        median_cycle_h=float(cycle_h.median()),
        mean_cost=totals[COL_TOTAL_COST] / len(per_case),
        total_cycle_s=totals[COL_TOTAL_CYCLE_S],
        total_cost=totals[COL_TOTAL_COST],
        total_rework_count=rework[COL_TOTAL_REWORK_COUNT],
        rework_rate=rework[COL_REWORK_RATE],
        total_bot_failure_count=_bot_failure_count(
            event_log, bot_task_name, original_task_name
        ),
    )
