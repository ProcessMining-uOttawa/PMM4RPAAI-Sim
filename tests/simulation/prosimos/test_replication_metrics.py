"""Tests for core/simulation/prosimos/replication_metrics.py — no external tools required."""

from __future__ import annotations
import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from core.simulation.prosimos.replication_metrics import (
    _parse_section,
    _rework_metrics,
    _bot_failure_count,
    task_totals,
    overall_kpis,
    replication_metrics,
    ReplicationMetrics,
    NO_RESOURCE,
    PROSIMOS_SECTION_TASK_STATS,
    PROSIMOS_COL_TOTAL_COST,
    PROSIMOS_COL_TOTAL_PROCESSING,
    PROSIMOS_SECTION_OVERALL,
    PROSIMOS_COL_ACCUMULATED,
    PROSIMOS_COL_TRACE_COUNT,
    PROSIMOS_KPI_IDLE_CYCLE_TIME,
)
from core.constants import (
    COL_TOTAL_REWORK_COUNT,
    COL_REWORK_RATE,
    COL_MEAN_REWORK_COUNT,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

BOT = "Auto Fix Bug"
ORIG = "Fix Bug"
_ALLDAY = [
    {"from": "MONDAY", "to": "SUNDAY", "beginTime": "00:00:00", "endTime": "24:00:00"}
]
_NINE_TO_FIVE = [
    {"from": "MONDAY", "to": "FRIDAY", "beginTime": "09:00:00", "endTime": "17:00:00"}
]

_LOG_COLUMNS = [
    "case_id",
    "activity",
    "enable_time",
    "start_time",
    "end_time",
    "resource",
]


def _write_log(path: Path, rows: list[tuple]) -> Path:
    """rows: (case_id, activity, enable, start, end, resource)."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(_LOG_COLUMNS)
        for row in rows:
            w.writerow(row)
    return path


def _write_params(path: Path, calendar=_ALLDAY, rate: float = 10.0) -> Path:
    """One resource 'R' at the given rate on the given calendar (name == id)."""
    params = {
        "resource_calendars": [{"id": "cal", "time_periods": calendar}],
        "resource_profiles": [
            {
                "resource_list": [
                    {"id": "R", "name": "R", "cost_per_hour": rate, "calendar": "cal"}
                ]
            }
        ],
        "arrival_time_calendar": _ALLDAY,
    }
    path.write_text(json.dumps(params))
    return path


def _metrics(
    tmp_path: Path, rows: list[tuple], calendar=_ALLDAY, **kwargs
) -> ReplicationMetrics:
    log = _write_log(tmp_path / "log.csv", rows)
    params = _write_params(tmp_path / "params.json", calendar)
    return replication_metrics(log, params, **kwargs)


def _row(case, start, end, activity="T", enable=None, resource="R") -> tuple:
    return (case, activity, enable or start, start, end, resource)


def _write_task_stats(path: Path, tasks: list[tuple]) -> Path:
    """tasks: (name, total_cost, total_processing_s)."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([PROSIMOS_SECTION_TASK_STATS])
        w.writerow(["Name", PROSIMOS_COL_TOTAL_COST, PROSIMOS_COL_TOTAL_PROCESSING])
        for name, cost, processing in tasks:
            w.writerow([name, str(cost), str(processing)])
        w.writerow([])
    return path


def _write_overall(path: Path, kpis: list[tuple], mode: str = "w") -> Path:
    """kpis: (name, min, max, average, accumulated, count). mode 'a' appends."""
    with open(path, mode, newline="") as f:
        w = csv.writer(f)
        w.writerow([PROSIMOS_SECTION_OVERALL])
        w.writerow(
            [
                "KPI",
                "Min",
                "Max",
                "Average",
                PROSIMOS_COL_ACCUMULATED,
                PROSIMOS_COL_TRACE_COUNT,
            ]
        )
        for row in kpis:
            w.writerow([str(cell) for cell in row])
        w.writerow([])
    return path


# ── _parse_section ────────────────────────────────────────────────────────────


class TestParseSection:
    def test_section_found(self):
        rows = [
            [PROSIMOS_SECTION_TASK_STATS],
            ["Name", PROSIMOS_COL_TOTAL_COST, "other"],
            ["task_a", "100.0", "x"],
            ["task_b", "50.0", "y"],
            [],
        ]
        hdrs, data = _parse_section(rows, PROSIMOS_SECTION_TASK_STATS)
        assert hdrs == ["Name", PROSIMOS_COL_TOTAL_COST, "other"]
        assert len(data) == 2
        assert data[0][1] == "100.0"

    def test_section_not_found(self):
        rows = [["Other Section"], ["col"], ["val"]]
        hdrs, data = _parse_section(rows, "Missing")
        assert hdrs == [] and data == []

    def test_terminates_at_blank_row(self):
        rows = [["My Section"], ["col"], ["row1"], [], ["row2"]]
        _, data = _parse_section(rows, "My Section")
        assert len(data) == 1

    def test_section_at_end_of_file(self):
        rows = [["My Section"]]
        hdrs, data = _parse_section(rows, "My Section")
        assert hdrs == [] and data == []


# ── task_totals / overall_kpis (checker oracle accessors) ─────────────────────


class TestTaskTotals:
    def test_returns_cost_and_processing(self, tmp_path):
        stats = _write_task_stats(
            tmp_path / "s.csv", [("A", 100.0, 3600.0), ("B", 50.0, 1800.0)]
        )
        result = task_totals(stats)
        assert result["A"] == {"cost": 100.0, "processing_s": 3600.0}
        assert result["B"] == {"cost": 50.0, "processing_s": 1800.0}

    def test_missing_task_section_raises(self, tmp_path):
        stats = _write_overall(tmp_path / "s.csv", [("cycle_time", 0, 0, 0, 1.0, 1)])
        with pytest.raises(ValueError, match="Individual Task Statistics"):
            task_totals(stats)

    def test_missing_cost_column_raises(self, tmp_path):
        stats = tmp_path / "s.csv"
        with open(stats, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([PROSIMOS_SECTION_TASK_STATS])
            w.writerow(["Name", "Some Other Column", PROSIMOS_COL_TOTAL_PROCESSING])
            w.writerow(["A", "50.0", "10.0"])
            w.writerow([])
        with pytest.raises(ValueError, match="Total Cost"):
            task_totals(stats)

    def test_missing_processing_column_raises(self, tmp_path):
        stats = tmp_path / "s.csv"
        with open(stats, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([PROSIMOS_SECTION_TASK_STATS])
            w.writerow(["Name", PROSIMOS_COL_TOTAL_COST])
            w.writerow(["A", "50.0"])
            w.writerow([])
        with pytest.raises(ValueError, match="Total Processing Time"):
            task_totals(stats)

    def test_non_numeric_raises(self, tmp_path):
        stats = _write_task_stats(tmp_path / "s.csv", [("A", "oops", 10.0)])
        with pytest.raises(ValueError, match="Non-numeric Total Cost"):
            task_totals(stats)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            task_totals(tmp_path / "nope.csv")


class TestOverallKpis:
    def test_returns_kpis(self, tmp_path):
        stats = _write_overall(
            tmp_path / "s.csv",
            [(PROSIMOS_KPI_IDLE_CYCLE_TIME, 1.0, 9.0, 5.0, 500.0, 100)],
        )
        result = overall_kpis(stats)[PROSIMOS_KPI_IDLE_CYCLE_TIME]
        assert result == {
            "min": 1.0,
            "max": 9.0,
            "average": 5.0,
            "accumulated": 500.0,
            "count": 100.0,
        }

    def test_missing_overall_section_raises(self, tmp_path):
        stats = _write_task_stats(tmp_path / "s.csv", [("A", 1.0, 1.0)])
        with pytest.raises(ValueError, match="Overall Scenario Statistics"):
            overall_kpis(stats)

    def test_missing_accumulated_column_raises(self, tmp_path):
        stats = tmp_path / "s.csv"
        with open(stats, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([PROSIMOS_SECTION_OVERALL])
            w.writerow(["KPI", "Min", "Max", "Average", PROSIMOS_COL_TRACE_COUNT])
            w.writerow(["cycle_time", "0", "0", "0", "100"])
            w.writerow([])
        with pytest.raises(ValueError, match="Accumulated Value"):
            overall_kpis(stats)

    def test_missing_trace_count_column_raises(self, tmp_path):
        stats = tmp_path / "s.csv"
        with open(stats, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([PROSIMOS_SECTION_OVERALL])
            w.writerow(["KPI", "Min", "Max", "Average", PROSIMOS_COL_ACCUMULATED])
            w.writerow(["cycle_time", "0", "0", "0", "1.0"])
            w.writerow([])
        with pytest.raises(ValueError, match="Trace Ocurrences"):
            overall_kpis(stats)


# ── replication_metrics ───────────────────────────────────────────────────────


class TestReplicationMetrics:
    def test_returns_replication_metrics(self, tmp_path):
        m = _metrics(
            tmp_path, [_row("c1", "2025-01-06T08:00:00", "2025-01-06T10:00:00")]
        )
        assert isinstance(m, ReplicationMetrics)

    def test_cycle_time_mean(self, tmp_path):
        m = _metrics(
            tmp_path,
            [
                _row("c1", "2025-01-06T08:00:00", "2025-01-06T10:00:00"),  # 2 h
                _row("c2", "2025-01-06T08:00:00", "2025-01-06T12:00:00"),  # 4 h
            ],
        )
        assert m.mean_cycle_h == pytest.approx(3.0)

    def test_cycle_time_median_and_order_stats(self, tmp_path):
        m = _metrics(
            tmp_path,
            [
                _row("c1", "2025-01-06T08:00:00", "2025-01-06T10:00:00"),  # 2 h
                _row("c2", "2025-01-06T08:00:00", "2025-01-06T10:00:00"),  # 2 h
                _row("c3", "2025-01-06T08:00:00", "2025-01-06T16:00:00"),  # 8 h
            ],
        )
        # Asymmetric [2, 2, 8]: the tail pulls the mean to 4.0 while median stays 2.0.
        assert m.mean_cycle_h == pytest.approx(4.0)
        assert m.median_cycle_h == pytest.approx(2.0)
        assert m.min_cycle_h == pytest.approx(2.0)
        assert m.max_cycle_h == pytest.approx(8.0)

    def test_cycle_time_groups_by_case(self, tmp_path):
        # c1 has two events with a 30-min gap; its span includes the gap.
        m = _metrics(
            tmp_path,
            [
                _row("c1", "2025-01-06T08:00:00", "2025-01-06T09:00:00"),
                _row("c1", "2025-01-06T09:30:00", "2025-01-06T10:00:00"),
                _row("c2", "2025-01-06T08:00:00", "2025-01-06T09:00:00"),
            ],
        )
        # per-case spans: c1 = 2 h, c2 = 1 h → mean 1.5 h (a per-event mutant → 0.833).
        assert m.mean_cycle_h == pytest.approx(1.5)

    def test_mean_cost_is_mean_of_per_case_series(self, tmp_path):
        # rate 10/hr, 24/7 calendar. c1 has 2 one-hour events ($20), c2 & c3 one each
        # ($10). Per-case series [20, 10, 10] → mean 13.333, total 40. Discriminates
        # a per-event mean (40/4 = 10) and a per-case count.
        m = _metrics(
            tmp_path,
            [
                _row("c1", "2025-01-06T08:00:00", "2025-01-06T09:00:00"),
                _row("c1", "2025-01-06T09:00:00", "2025-01-06T10:00:00"),
                _row("c2", "2025-01-06T08:00:00", "2025-01-06T09:00:00"),
                _row("c3", "2025-01-06T08:00:00", "2025-01-06T09:00:00"),
            ],
        )
        assert m.mean_cost == pytest.approx(40.0 / 3)
        assert m.total_cost == pytest.approx(40.0)

    def test_cost_is_calendar_aware(self, tmp_path):
        # 9-5 calendar: a Mon 16:00 → Tue 10:00 task is 18 h wall but 2 h working
        # (Mon 16-17 + Tue 9-10) → cost 2 h × $10 = $20, not 18 × $10.
        m = _metrics(
            tmp_path,
            [_row("c1", "2025-01-06T16:00:00", "2025-01-07T10:00:00")],
            calendar=_NINE_TO_FIVE,
        )
        assert m.total_cost == pytest.approx(20.0)

    def test_total_cycle_s_is_arrival_based(self, tmp_path):
        # enable (arrival) 07:00, first start 08:00, end 10:00. total_cycle_s counts
        # from arrival (3 h) while mean_cycle_h counts from first start (2 h).
        m = _metrics(
            tmp_path,
            [
                _row(
                    "c1",
                    "2025-01-06T08:00:00",
                    "2025-01-06T10:00:00",
                    enable="2025-01-06T07:00:00",
                )
            ],
        )
        assert m.total_cycle_s == pytest.approx(3 * 3600.0)
        assert m.mean_cycle_h == pytest.approx(2.0)

    def test_total_cycle_s_completion_is_last_event(self, tmp_path):
        # A trailing timer (event row) ends AFTER the last task. total_cycle_s runs
        # to that completion — the last event of any kind, matching Prosimos's
        # idle_cycle_time — while mean_cycle_h stops at the last TASK end.
        m = _metrics(
            tmp_path,
            [
                _row(
                    "c1",
                    "2025-01-06T08:00:00",
                    "2025-01-06T10:00:00",
                    activity="Fix Bug",
                ),
                (
                    "c1",
                    "Event_x",
                    "2025-01-06T10:00:00",
                    "2025-01-06T10:00:00",
                    "2025-01-06T11:00:00",
                    NO_RESOURCE,
                ),
            ],
        )
        assert m.total_cycle_s == pytest.approx(
            3 * 3600.0
        )  # 08:00 → 11:00 (trailing event)
        assert m.mean_cycle_h == pytest.approx(2.0)  # 08:00 → 10:00 (last task only)

    def test_event_rows_excluded_but_source_arrival(self, tmp_path):
        # A looped intermediate-event row (resource "No assigned resource") carries
        # the raw arrival at 07:00. It must be excluded from cost/cycle/rework but
        # supply the arrival.
        m = _metrics(
            tmp_path,
            [
                (
                    "c1",
                    "Event_x",
                    "2025-01-06T07:00:00",
                    "2025-01-06T07:00:00",
                    "2025-01-06T07:30:00",
                    NO_RESOURCE,
                ),
                (
                    "c1",
                    "Event_x",
                    "2025-01-06T07:30:00",
                    "2025-01-06T07:30:00",
                    "2025-01-06T08:00:00",
                    NO_RESOURCE,
                ),
                _row(
                    "c1",
                    "2025-01-06T08:00:00",
                    "2025-01-06T10:00:00",
                    activity="Fix Bug",
                ),
            ],
        )
        assert m.total_cycle_s == pytest.approx(3 * 3600.0)  # arrival 07:00 → end 10:00
        assert m.mean_cycle_h == pytest.approx(2.0)  # first task start 08:00 → 10:00
        assert m.total_cost == pytest.approx(20.0)  # only the 2 h task row
        assert (
            m.total_rework_count == 0.0
        )  # the repeated Event_x is excluded, not rework

    def test_bot_failure_count_field(self, tmp_path):
        m = _metrics(
            tmp_path,
            [
                _row("c1", "2025-01-06T08:00:00", "2025-01-06T09:00:00", activity=BOT),
                _row("c1", "2025-01-06T09:00:00", "2025-01-06T10:00:00", activity=ORIG),
                _row("c2", "2025-01-06T08:00:00", "2025-01-06T09:00:00", activity=BOT),
            ],
            bot_task_name=BOT,
            original_task_name=ORIG,
        )
        assert m.total_bot_failure_count == 1.0
        assert m.total_rework_count == 0.0  # the failure pair is not rework

    def test_missing_params_file_raises(self, tmp_path):
        log = _write_log(
            tmp_path / "log.csv",
            [_row("c1", "2025-01-06T08:00:00", "2025-01-06T09:00:00")],
        )
        with pytest.raises(FileNotFoundError):
            replication_metrics(log, tmp_path / "nonexistent.json")

    def test_malformed_params_raises(self, tmp_path):
        log = _write_log(
            tmp_path / "log.csv",
            [_row("c1", "2025-01-06T08:00:00", "2025-01-06T09:00:00")],
        )
        params = tmp_path / "params.json"
        params.write_text("{ not valid json")
        with pytest.raises(ValueError):
            replication_metrics(log, params)


# ── _rework_metrics ───────────────────────────────────────────────────────────


def _df(*rows: tuple[str, str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["case_id", "activity"])


class TestReworkMetrics:
    def test_no_rework_count_zero(self):
        assert (
            _rework_metrics(_df(("C1", ORIG), ("C2", ORIG)))[COL_TOTAL_REWORK_COUNT]
            == 0.0
        )

    def test_no_rework_rate_zero(self):
        assert _rework_metrics(_df(("C1", ORIG), ("C2", ORIG)))[COL_REWORK_RATE] == 0.0

    def test_standard_rework_count(self):
        df = _df(("C1", ORIG), ("C1", ORIG), ("C2", ORIG))
        assert _rework_metrics(df)[COL_TOTAL_REWORK_COUNT] == 1.0

    def test_standard_rework_rate(self):
        df = _df(("C1", ORIG), ("C1", ORIG), ("C2", ORIG))
        assert _rework_metrics(df)[COL_REWORK_RATE] == pytest.approx(50.0)

    def test_mean_rework_count(self):
        df = _df(("C1", ORIG), ("C1", ORIG), ("C2", ORIG))
        assert _rework_metrics(df)[COL_MEAN_REWORK_COUNT] == pytest.approx(0.5)

    def test_standard_rework_three_repeats(self):
        df = _df(("C1", ORIG), ("C1", ORIG), ("C1", ORIG))
        assert _rework_metrics(df)[COL_TOTAL_REWORK_COUNT] == 2.0

    def test_standard_rework_multiple_activities(self):
        df = _df(("C1", "A"), ("C1", "A"), ("C1", "B"), ("C1", "B"))
        assert _rework_metrics(df)[COL_TOTAL_REWORK_COUNT] == 2.0

    def test_bot_failure_pair_is_not_rework(self):
        df = _df(("C1", BOT), ("C1", ORIG), ("C2", BOT))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 0.0
        assert r[COL_REWORK_RATE] == 0.0

    def test_repeated_activity_alongside_bot_pair(self):
        df = _df(("C1", BOT), ("C1", ORIG), ("C1", ORIG))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 1.0
        assert r[COL_REWORK_RATE] == 100.0

    def test_rework_count_sums_across_cases(self):
        df = _df(("C1", ORIG), ("C1", ORIG), ("C2", BOT), ("C2", ORIG), ("C3", ORIG))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 1.0
        assert r[COL_REWORK_RATE] == pytest.approx(100 / 3)

    def test_missing_activity_column_zero(self):
        r = _rework_metrics(pd.DataFrame({"case_id": ["C1"]}))
        assert r[COL_TOTAL_REWORK_COUNT] == 0.0
        assert r[COL_REWORK_RATE] == 0.0
        assert r[COL_MEAN_REWORK_COUNT] == 0.0


# ── _bot_failure_count ────────────────────────────────────────────────────────


class TestBotFailureCount:
    def test_failure_pair_counts_one(self):
        assert (
            _bot_failure_count(_df(("C1", BOT), ("C1", ORIG), ("C2", BOT)), BOT, ORIG)
            == 1.0
        )

    def test_bot_success_zero(self):
        assert _bot_failure_count(_df(("C1", BOT), ("C2", BOT)), BOT, ORIG) == 0.0

    def test_manual_only_zero(self):
        assert _bot_failure_count(_df(("C1", ORIG), ("C2", ORIG)), BOT, ORIG) == 0.0

    def test_binary_per_case(self):
        df = _df(("C1", BOT), ("C1", ORIG), ("C1", BOT), ("C1", ORIG))
        assert _bot_failure_count(df, BOT, ORIG) == 1.0

    def test_sums_across_cases(self):
        df = _df(("C1", BOT), ("C1", ORIG), ("C2", BOT), ("C2", ORIG), ("C3", BOT))
        assert _bot_failure_count(df, BOT, ORIG) == 2.0

    def test_unknown_task_names_zero(self):
        assert _bot_failure_count(_df(("C1", BOT), ("C1", ORIG)), None, None) == 0.0

    def test_missing_activity_column_zero(self):
        assert _bot_failure_count(pd.DataFrame({"case_id": ["C1"]}), BOT, ORIG) == 0.0
