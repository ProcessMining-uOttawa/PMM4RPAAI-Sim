"""Per-replication metrics from Prosimos output — derives them from the event-log
CSV (calendar-aware, via the params JSON), and provides strict stats-CSV
accessors for the simulation trust checker (core/simulation/validate.py).

Every product metric is computed from the event log: cycle time and rework from
the log directly, cost from the log intersected with the resource calendars in
the params JSON (see calendars.py). The stats CSV is not a product source —
its parsers here exist so the checker can cross-check our numbers against
Prosimos's own accounting.

Every log row is an activity: the runner simulates without
``--is_event_added_to_log``, so Prosimos writes no intermediate-event rows
(which would carry ``resource == "No assigned resource"`` and represent e.g.
Simod's extraneous-delay timer firings, not work). ``replication_metrics``
rejects a log that does contain them — such a log came from a flag-on run and
must be re-simulated — rather than silently counting looped timers as rework.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ...constants import (
    COL_TOTAL_REWORK_COUNT,
    COL_REWORK_RATE,
    COL_MEAN_REWORK_COUNT,
)
from . import calendars

# Prosimos writes this in the resource column of intermediate-event rows (events
# have no resource). No such row belongs in a log this module reads — its
# presence marks a --is_event_added_to_log run, which the guard rejects.
NO_RESOURCE = "No assigned resource"


@dataclass(frozen=True)
class ReplicationMetrics:
    """All per-replication metrics for one Prosimos simulation run.

    Field names mirror the COL_* constant string values so dataclasses.asdict()
    produces the exact DataFrame column keys downstream expects.
    """

    mean_cycle_h: float
    median_cycle_h: float
    min_cycle_h: float
    max_cycle_h: float
    mean_cost: float
    total_cycle_s: float
    total_cost: float
    total_rework_count: float
    rework_rate: float
    mean_rework_count: float
    total_bot_failure_count: float


# ── Prosimos stats CSV: section header names ───────────────────────────────────
PROSIMOS_SECTION_TASK_STATS = "Individual Task Statistics"
PROSIMOS_SECTION_OVERALL = "Overall Scenario Statistics"

# ── Prosimos stats CSV: column and row-key lookup strings ─────────────────────
PROSIMOS_COL_TOTAL_COST = "Total Cost"  # column in SECTION_TASK_STATS
PROSIMOS_COL_TOTAL_PROCESSING = "Total Processing Time"  # column in SECTION_TASK_STATS
PROSIMOS_COL_ACCUMULATED = "Accumulated Value"  # column in SECTION_OVERALL
PROSIMOS_COL_MIN = "Min"  # column in SECTION_OVERALL
PROSIMOS_COL_MAX = "Max"  # column in SECTION_OVERALL
PROSIMOS_COL_AVERAGE = "Average"  # column in SECTION_OVERALL
PROSIMOS_COL_TRACE_COUNT = (
    "Trace Ocurrences"  # column in SECTION_OVERALL (Prosimos's spelling)
)


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


def _numeric(value: str, label: str, source: Path) -> float:
    """Parse a stats-CSV cell as float, raising a labelled error otherwise."""
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Non-numeric {label} in {source}: {value!r}")


def _read_rows(stats_csv: Path) -> list[list[str]]:
    with open(stats_csv) as f:
        return list(csv.reader(f))


def _rework_metrics(event_log: pd.DataFrame) -> dict:
    """Process-wide repeated-activity rework from an event log DataFrame.

    Counts (occurrences - 1) for any activity appearing more than once in the
    same case. Bot failures are deliberately NOT rework — they are tracked
    separately by _bot_failure_count().
    """
    if "activity" not in event_log.columns:
        return {
            COL_TOTAL_REWORK_COUNT: 0.0,
            COL_REWORK_RATE: 0.0,
            COL_MEAN_REWORK_COUNT: 0.0,
        }

    # Each repeat of an activity within a case counts once.
    activity_counts = event_log.groupby(["case_id", "activity"]).size()
    excess = activity_counts[activity_counts > 1] - 1  # type: ignore[index]
    rework_per_case: pd.Series = excess.groupby(level="case_id").sum()  # type: ignore[assignment]

    # Restore cases with no rework so the rate/mean denominator is every case.
    rework_per_case = rework_per_case.reindex(
        event_log["case_id"].unique(), fill_value=0.0
    )
    return {
        COL_TOTAL_REWORK_COUNT: float(rework_per_case.sum()),
        COL_REWORK_RATE: float((rework_per_case > 0).mean()) * 100.0,
        COL_MEAN_REWORK_COUNT: float(rework_per_case.mean()),
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


def task_totals(stats_csv: Path) -> dict[str, dict[str, float]]:
    """Per-task {cost, processing_s} from the Individual Task Statistics section.

    Strict: raises ValueError on a missing section/column or a non-numeric cell,
    FileNotFoundError if stats_csv does not exist. Used by the trust checker as
    the oracle for the log-derived cost / working-time numbers.
    """
    rows = _read_rows(stats_csv)
    headers, data = _require_section(rows, PROSIMOS_SECTION_TASK_STATS, stats_csv)
    cost_index = _require_column(headers, PROSIMOS_COL_TOTAL_COST, stats_csv)
    processing_index = _require_column(
        headers, PROSIMOS_COL_TOTAL_PROCESSING, stats_csv
    )
    return {
        row[0].strip(): {
            "cost": _numeric(row[cost_index], "Total Cost", stats_csv),
            "processing_s": _numeric(
                row[processing_index], "Total Processing Time", stats_csv
            ),
        }
        for row in data
    }


def overall_kpis(stats_csv: Path) -> dict[str, dict[str, float]]:
    """Per-KPI {min, max, average, accumulated, count} from the Overall section.

    Strict, like task_totals. Parses the full section for shape-fidelity (a
    missing column is format drift worth failing on); the checker currently
    reads only the trace count.
    """
    rows = _read_rows(stats_csv)
    headers, data = _require_section(rows, PROSIMOS_SECTION_OVERALL, stats_csv)
    columns = {
        "min": _require_column(headers, PROSIMOS_COL_MIN, stats_csv),
        "max": _require_column(headers, PROSIMOS_COL_MAX, stats_csv),
        "average": _require_column(headers, PROSIMOS_COL_AVERAGE, stats_csv),
        "accumulated": _require_column(headers, PROSIMOS_COL_ACCUMULATED, stats_csv),
        "count": _require_column(headers, PROSIMOS_COL_TRACE_COUNT, stats_csv),
    }
    return {
        row[0].strip(): {
            field: _numeric(row[index], field, stats_csv)
            for field, index in columns.items()
        }
        for row in data
    }


def replication_metrics(
    log_csv: Path,
    params_json: Path,
    bot_task_name: str | None = None,
    original_task_name: str | None = None,
) -> ReplicationMetrics:
    """All per-replication metrics from the event log + params, in a single pass.

    All clocks share one anchor pair: the case's first task start → last task
    end (the log-based case duration — what Celonis/Apromore report). The
    cycle-time indicators (mean/median/min/max) are the per-case spans; the
    total is their sum, so ``total_cycle_s = mean_cycle_h × n_cases × 3600`` by
    construction. Cost is calendar-aware working time × rate, per case.

    Raises ValueError if the log contains intermediate-event rows (a
    ``--is_event_added_to_log`` run — re-simulate without the flag), if the
    params JSON is malformed, or if a log resource that did work is absent
    from it;
    FileNotFoundError if a path does not exist.
    """
    event_log = pd.read_csv(log_csv, parse_dates=["start_time", "end_time"])
    if (event_log["resource"] == NO_RESOURCE).any():
        raise ValueError(
            f"{log_csv} contains intermediate-event rows "
            f"(resource == {NO_RESOURCE!r}), which Prosimos emits under "
            "--is_event_added_to_log; this pipeline reads activity-only logs — "
            "re-simulate without the flag."
        )
    params = json.loads(Path(params_json).read_text())

    # Per-case span: first task start → last task end.
    per_case = event_log.groupby("case_id").agg(
        start=("start_time", "min"), end=("end_time", "max")
    )
    cycle_h = (per_case["end"] - per_case["start"]).dt.total_seconds().div(3600)
    total_cycle_s = float(cycle_h.sum()) * 3600

    # Per-case cost from calendar-aware working time. mean_cost is stored at
    # source as the mean of the series, not total/n (the "stored at source" rule).
    case_cost = (
        calendars.event_costs(event_log, params)["cost"]
        .groupby(event_log["case_id"])
        .sum()
    )

    rework = _rework_metrics(event_log)
    return ReplicationMetrics(
        mean_cycle_h=float(cycle_h.mean()),
        median_cycle_h=float(cycle_h.median()),
        min_cycle_h=float(cycle_h.min()),
        max_cycle_h=float(cycle_h.max()),
        mean_cost=float(case_cost.mean()),
        total_cycle_s=total_cycle_s,
        total_cost=float(case_cost.sum()),
        total_rework_count=rework[COL_TOTAL_REWORK_COUNT],
        rework_rate=rework[COL_REWORK_RATE],
        mean_rework_count=rework[COL_MEAN_REWORK_COUNT],
        total_bot_failure_count=_bot_failure_count(
            event_log, bot_task_name, original_task_name
        ),
    )
