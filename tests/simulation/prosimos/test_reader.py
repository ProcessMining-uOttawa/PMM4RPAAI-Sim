"""Tests for core/simulation/prosimos/reader.py — no external tools required."""

from __future__ import annotations
import csv
from pathlib import Path

import pandas as pd
import pytest

from core.simulation.prosimos.reader import (
    _parse_section,
    _rework_metrics,
    _bot_failure_count,
    total_metrics,
    replication_metrics,
    ReplicationMetrics,
    PROSIMOS_SECTION_TASK_STATS,
    PROSIMOS_COL_TOTAL_COST,
    PROSIMOS_SECTION_OVERALL,
    PROSIMOS_COL_ACCUMULATED,
    PROSIMOS_KPI_CYCLE_TIME,
)
from core.constants import (
    COL_TOTAL_CYCLE_S,
    COL_TOTAL_COST,
    COL_TOTAL_REWORK_COUNT,
    COL_REWORK_RATE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

BOT = "Auto Fix Bug"
ORIG = "Fix Bug"


def _write_log(path: Path, cases: list[tuple]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "start_time", "end_time"])
        for row in cases:
            w.writerow(row)


def _write_stats(path: Path, tasks: list[tuple]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([PROSIMOS_SECTION_TASK_STATS])
        w.writerow(["task_id", PROSIMOS_COL_TOTAL_COST])
        for task_id, total_cost in tasks:
            w.writerow([task_id, str(total_cost)])
        w.writerow([])


def _write_full_stats(
    path: Path, tasks: list[tuple], accumulated_cycle_s: float
) -> None:
    """Write a stats CSV with both Individual Task Statistics and Overall Scenario Statistics."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([PROSIMOS_SECTION_TASK_STATS])
        w.writerow(["task_id", PROSIMOS_COL_TOTAL_COST])
        for task_id, total_cost in tasks:
            w.writerow([task_id, str(total_cost)])
        w.writerow([])
        w.writerow([PROSIMOS_SECTION_OVERALL])
        w.writerow(
            [
                "KPI",
                "Min",
                "Max",
                "Average",
                PROSIMOS_COL_ACCUMULATED,
                "Trace Occurrences",
            ]
        )
        w.writerow(
            [PROSIMOS_KPI_CYCLE_TIME, "0", "0", "0", str(accumulated_cycle_s), "100"]
        )
        w.writerow([])


# ── _parse_section ────────────────────────────────────────────────────────────


class TestParseSection:
    def test_section_found(self):
        rows = [
            [PROSIMOS_SECTION_TASK_STATS],
            ["task_id", PROSIMOS_COL_TOTAL_COST, "other"],
            ["task_a", "100.0", "x"],
            ["task_b", "50.0", "y"],
            [],
        ]
        hdrs, data = _parse_section(rows, PROSIMOS_SECTION_TASK_STATS)
        assert hdrs == ["task_id", PROSIMOS_COL_TOTAL_COST, "other"]
        assert len(data) == 2
        assert data[0][1] == "100.0"

    def test_section_not_found(self):
        rows = [["Other Section"], ["col"], ["val"]]
        hdrs, data = _parse_section(rows, "Missing")
        assert hdrs == [] and data == []

    def test_terminates_at_blank_row(self):
        rows = [
            ["My Section"],
            ["col"],
            ["row1"],
            [],  # blank — stop here
            ["row2"],  # must not appear in data
        ]
        _, data = _parse_section(rows, "My Section")
        assert len(data) == 1

    def test_section_at_end_of_file(self):
        rows = [["My Section"]]  # no column header after it
        hdrs, data = _parse_section(rows, "My Section")
        assert hdrs == [] and data == []


# ── total_metrics ─────────────────────────────────────────────────────────────


class TestTotalMetrics:
    def test_total_cycle_s(self, tmp_path):
        stats = tmp_path / "stats.csv"
        _write_full_stats(stats, [("task_a", 50.0)], accumulated_cycle_s=3600.0)
        assert total_metrics(stats)[COL_TOTAL_CYCLE_S] == pytest.approx(3600.0)

    def test_total_cost_sum(self, tmp_path):
        stats = tmp_path / "stats.csv"
        _write_full_stats(
            stats, [("task_a", 100.0), ("task_b", 50.0)], accumulated_cycle_s=1.0
        )
        assert total_metrics(stats)[COL_TOTAL_COST] == pytest.approx(150.0)

    def test_missing_overall_section_raises(self, tmp_path):
        stats = tmp_path / "stats.csv"
        _write_stats(stats, [("task_a", 50.0)])  # only task stats, no overall section
        with pytest.raises(ValueError, match="Overall Scenario Statistics"):
            total_metrics(stats)

    def test_missing_cost_column_raises(self, tmp_path):
        stats = tmp_path / "stats.csv"
        with open(stats, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([PROSIMOS_SECTION_TASK_STATS])
            w.writerow(["task_id", "Some Other Column"])
            w.writerow(["task_a", "50.0"])
            w.writerow([])
            w.writerow([PROSIMOS_SECTION_OVERALL])
            w.writerow(
                [
                    "KPI",
                    "Min",
                    "Max",
                    "Average",
                    PROSIMOS_COL_ACCUMULATED,
                    "Trace Occurrences",
                ]
            )
            w.writerow([PROSIMOS_KPI_CYCLE_TIME, "0", "0", "0", "3600.0", "100"])
        with pytest.raises(ValueError, match="Total Cost"):
            total_metrics(stats)

    def test_missing_accumulated_column_raises(self, tmp_path):
        stats = tmp_path / "stats.csv"
        with open(stats, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([PROSIMOS_SECTION_TASK_STATS])
            w.writerow(["task_id", PROSIMOS_COL_TOTAL_COST])
            w.writerow(["task_a", "50.0"])
            w.writerow([])
            w.writerow([PROSIMOS_SECTION_OVERALL])
            # "Accumulated Value" column intentionally absent
            w.writerow(["KPI", "Min", "Max", "Average", "Trace Occurrences"])
            w.writerow([PROSIMOS_KPI_CYCLE_TIME, "0", "0", "0", "100"])
        with pytest.raises(ValueError, match="Accumulated Value"):
            total_metrics(stats)

    def test_missing_cycle_kpi_row_raises(self, tmp_path):
        stats = tmp_path / "stats.csv"
        with open(stats, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([PROSIMOS_SECTION_TASK_STATS])
            w.writerow(["task_id", PROSIMOS_COL_TOTAL_COST])
            w.writerow(["task_a", "50.0"])
            w.writerow([])
            w.writerow([PROSIMOS_SECTION_OVERALL])
            w.writerow(
                [
                    "KPI",
                    "Min",
                    "Max",
                    "Average",
                    PROSIMOS_COL_ACCUMULATED,
                    "Trace Occurrences",
                ]
            )
            # cycle_time row intentionally absent
            w.writerow(["some_other_kpi", "0", "0", "0", "999.0", "100"])
        with pytest.raises(ValueError, match="cycle_time"):
            total_metrics(stats)

    def test_missing_task_stats_section_raises(self, tmp_path):
        stats = tmp_path / "stats.csv"
        with open(stats, "w", newline="") as f:
            w = csv.writer(f)
            # Only overall section — no task stats section at all
            w.writerow([PROSIMOS_SECTION_OVERALL])
            w.writerow(
                [
                    "KPI",
                    "Min",
                    "Max",
                    "Average",
                    PROSIMOS_COL_ACCUMULATED,
                    "Trace Occurrences",
                ]
            )
            w.writerow([PROSIMOS_KPI_CYCLE_TIME, "0", "0", "0", "3600.0", "100"])
        with pytest.raises(ValueError, match="Individual Task Statistics"):
            total_metrics(stats)

    def test_non_numeric_cost_raises(self, tmp_path):
        stats = tmp_path / "stats.csv"
        with open(stats, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([PROSIMOS_SECTION_TASK_STATS])
            w.writerow(["task_id", PROSIMOS_COL_TOTAL_COST])
            w.writerow(["task_a", "not_a_number"])
            w.writerow([])
            w.writerow([PROSIMOS_SECTION_OVERALL])
            w.writerow(
                [
                    "KPI",
                    "Min",
                    "Max",
                    "Average",
                    PROSIMOS_COL_ACCUMULATED,
                    "Trace Occurrences",
                ]
            )
            w.writerow([PROSIMOS_KPI_CYCLE_TIME, "0", "0", "0", "3600.0", "100"])
        with pytest.raises(ValueError, match="Non-numeric Total Cost"):
            total_metrics(stats)


# ── replication_metrics ───────────────────────────────────────────────────────


class TestReplicationMetrics:
    def test_returns_replication_metrics(self, tmp_path):
        log = tmp_path / "log.csv"
        stats = tmp_path / "stats.csv"
        _write_log(log, [("c1", "2025-01-01T08:00:00", "2025-01-01T10:00:00")])
        _write_full_stats(stats, [("task_a", 100.0)], accumulated_cycle_s=3600.0)
        assert isinstance(replication_metrics(log, stats), ReplicationMetrics)

    def test_cycle_time_mean(self, tmp_path):
        log = tmp_path / "log.csv"
        stats = tmp_path / "stats.csv"
        _write_log(
            log,
            [
                ("c1", "2025-01-01T08:00:00", "2025-01-01T10:00:00"),  # 2 h
                ("c2", "2025-01-01T08:00:00", "2025-01-01T12:00:00"),  # 4 h
            ],
        )
        _write_full_stats(stats, [("task_a", 0.0)], accumulated_cycle_s=1.0)
        assert replication_metrics(log, stats).mean_cycle_h == pytest.approx(3.0)

    def test_cost_per_case(self, tmp_path):
        log = tmp_path / "log.csv"
        stats = tmp_path / "stats.csv"
        _write_log(
            log,
            [
                ("c1", "2025-01-01T08:00:00", "2025-01-01T09:00:00"),
                ("c2", "2025-01-01T08:00:00", "2025-01-01T09:00:00"),
            ],
        )
        _write_full_stats(
            stats, [("task_a", 100.0), ("task_b", 50.0)], accumulated_cycle_s=1.0
        )
        # total 150 / 2 cases = 75.0 per case
        assert replication_metrics(log, stats).mean_cost == pytest.approx(75.0)

    def test_totals_consistent_with_total_metrics(self, tmp_path):
        log = tmp_path / "log.csv"
        stats = tmp_path / "stats.csv"
        _write_log(
            log,
            [
                ("c1", "2025-01-01T08:00:00", "2025-01-01T10:00:00"),
                ("c2", "2025-01-01T08:00:00", "2025-01-01T12:00:00"),
            ],
        )
        _write_full_stats(
            stats, [("task_a", 100.0), ("task_b", 50.0)], accumulated_cycle_s=7200.0
        )
        combined = replication_metrics(log, stats)
        total = total_metrics(stats)
        assert combined.total_cycle_s == pytest.approx(total[COL_TOTAL_CYCLE_S])
        assert combined.total_cost == pytest.approx(total[COL_TOTAL_COST])

    def test_bot_failure_count_field(self, tmp_path):
        log = tmp_path / "log.csv"
        stats = tmp_path / "stats.csv"
        with open(log, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["case_id", "activity", "start_time", "end_time"])
            w.writerow(["c1", BOT, "2025-01-01T08:00:00", "2025-01-01T09:00:00"])
            w.writerow(["c1", ORIG, "2025-01-01T09:00:00", "2025-01-01T10:00:00"])
            w.writerow(["c2", BOT, "2025-01-01T08:00:00", "2025-01-01T09:00:00"])
        _write_full_stats(stats, [("task_a", 100.0)], accumulated_cycle_s=3600.0)
        m = replication_metrics(log, stats, bot_task_name=BOT, original_task_name=ORIG)
        assert m.total_bot_failure_count == 1.0
        assert m.total_rework_count == 0.0  # the failure pair is not rework

    def test_missing_stats_file_raises(self, tmp_path):
        log = tmp_path / "log.csv"
        _write_log(log, [("c1", "2025-01-01T08:00:00", "2025-01-01T09:00:00")])
        with pytest.raises(FileNotFoundError):
            replication_metrics(log, tmp_path / "nonexistent.csv")

    def test_malformed_stats_raises(self, tmp_path):
        log = tmp_path / "log.csv"
        stats = tmp_path / "stats.csv"
        _write_log(log, [("c1", "2025-01-01T08:00:00", "2025-01-01T09:00:00")])
        stats.write_text("no recognisable sections here\n")
        with pytest.raises(ValueError, match="Overall Scenario Statistics"):
            replication_metrics(log, stats)


# ── _rework_metrics ───────────────────────────────────────────────────────────


def _df(*rows: tuple[str, str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["case_id", "activity"])


class TestReworkMetrics:
    def test_no_rework_count_zero(self):
        df = _df(("C1", ORIG), ("C2", ORIG))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 0.0

    def test_no_rework_rate_zero(self):
        df = _df(("C1", ORIG), ("C2", ORIG))
        r = _rework_metrics(df)
        assert r[COL_REWORK_RATE] == 0.0

    def test_standard_rework_count(self):
        df = _df(("C1", ORIG), ("C1", ORIG), ("C2", ORIG))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 1.0

    def test_standard_rework_rate(self):
        df = _df(("C1", ORIG), ("C1", ORIG), ("C2", ORIG))
        r = _rework_metrics(df)
        assert r[COL_REWORK_RATE] == pytest.approx(50.0)

    def test_standard_rework_three_repeats(self):
        df = _df(("C1", ORIG), ("C1", ORIG), ("C1", ORIG))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 2.0

    def test_standard_rework_multiple_activities(self):
        df = _df(("C1", "A"), ("C1", "A"), ("C1", "B"), ("C1", "B"))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 2.0

    def test_bot_failure_pair_is_not_rework(self):
        # A bot run followed by a human redo is NOT rework — neither activity
        # repeats, and bot failures are their own metric (_bot_failure_count).
        df = _df(("C1", BOT), ("C1", ORIG), ("C2", BOT))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 0.0
        assert r[COL_REWORK_RATE] == 0.0

    def test_repeated_activity_alongside_bot_pair(self):
        # Only the repeated ORIG counts; the bot pair contributes nothing.
        df = _df(("C1", BOT), ("C1", ORIG), ("C1", ORIG))
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 1.0
        assert r[COL_REWORK_RATE] == 100.0

    def test_rework_count_sums_across_cases(self):
        df = _df(
            ("C1", ORIG),
            ("C1", ORIG),
            ("C2", BOT),
            ("C2", ORIG),
            ("C3", ORIG),
        )
        r = _rework_metrics(df)
        assert r[COL_TOTAL_REWORK_COUNT] == 1.0  # C1's repeat; C2's pair is not rework
        assert r[COL_REWORK_RATE] == pytest.approx(100 / 3)


# ── _bot_failure_count ────────────────────────────────────────────────────────


class TestBotFailureCount:
    def test_failure_pair_counts_one(self):
        df = _df(("C1", BOT), ("C1", ORIG), ("C2", BOT))
        assert _bot_failure_count(df, BOT, ORIG) == 1.0

    def test_bot_success_zero(self):
        df = _df(("C1", BOT), ("C2", BOT))
        assert _bot_failure_count(df, BOT, ORIG) == 0.0

    def test_manual_only_zero(self):
        df = _df(("C1", ORIG), ("C2", ORIG))
        assert _bot_failure_count(df, BOT, ORIG) == 0.0

    def test_binary_per_case(self):
        # A case counts once no matter how often the pair appears.
        df = _df(("C1", BOT), ("C1", ORIG), ("C1", BOT), ("C1", ORIG))
        assert _bot_failure_count(df, BOT, ORIG) == 1.0

    def test_sums_across_cases(self):
        df = _df(("C1", BOT), ("C1", ORIG), ("C2", BOT), ("C2", ORIG), ("C3", BOT))
        assert _bot_failure_count(df, BOT, ORIG) == 2.0

    def test_unknown_task_names_zero(self):
        df = _df(("C1", BOT), ("C1", ORIG))
        assert _bot_failure_count(df, None, None) == 0.0

    def test_missing_activity_column_zero(self):
        df = pd.DataFrame({"case_id": ["C1"]})
        assert _bot_failure_count(df, BOT, ORIG) == 0.0
