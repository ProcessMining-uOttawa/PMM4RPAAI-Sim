"""Tests for core/analysis.py — no external tools required."""
from __future__ import annotations
import csv
import math
from pathlib import Path

import pandas as pd
import pytest

from core.analysis import (
    _parse_section,
    per_log_metrics,
    total_metrics,
    aggregate,
    main_effects,
    signal_to_noise,
    rank,
)
from core.constants import (
    PROSIMOS_SECTION_TASK_STATS, PROSIMOS_COL_TOTAL_COST,
    PROSIMOS_SECTION_OVERALL, PROSIMOS_COL_ACCUMULATED, PROSIMOS_KPI_CYCLE_TIME,
    COL_CYCLE_H, COL_COST, COL_CYCLE_H_MEAN, COL_COST_MEAN,
    COL_TOTAL_CYCLE_S, COL_TOTAL_COST,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _write_full_stats(path: Path, tasks: list[tuple], accumulated_cycle_s: float) -> None:
    """Write a stats CSV with both Individual Task Statistics and Overall Scenario Statistics."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([PROSIMOS_SECTION_TASK_STATS])
        w.writerow(["task_id", PROSIMOS_COL_TOTAL_COST])
        for task_id, total_cost in tasks:
            w.writerow([task_id, str(total_cost)])
        w.writerow([])
        w.writerow([PROSIMOS_SECTION_OVERALL])
        w.writerow(["KPI", "Min", "Max", "Average", PROSIMOS_COL_ACCUMULATED, "Trace Occurrences"])
        w.writerow([PROSIMOS_KPI_CYCLE_TIME, "0", "0", "0", str(accumulated_cycle_s), "100"])
        w.writerow([])


def _results_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"scenario_id": "S01", "replication": 0, COL_CYCLE_H: 10.0, COL_COST:  5.0, "f_a": "low"},
        {"scenario_id": "S01", "replication": 1, COL_CYCLE_H: 12.0, COL_COST:  7.0, "f_a": "low"},
        {"scenario_id": "S02", "replication": 0, COL_CYCLE_H: 20.0, COL_COST: 10.0, "f_a": "high"},
        {"scenario_id": "S02", "replication": 1, COL_CYCLE_H: 22.0, COL_COST: 12.0, "f_a": "high"},
    ])


# ── signal_to_noise ───────────────────────────────────────────────────────────

class TestSignalToNoise:

    def test_smaller_is_better(self):
        vals = [2.0, 4.0, 4.0]
        expected = -10 * math.log10(sum(v * v for v in vals) / len(vals))
        assert signal_to_noise(vals) == pytest.approx(expected)

    def test_larger_is_better(self):
        vals = [2.0, 4.0]
        expected = -10 * math.log10(sum(1 / (v * v) for v in vals) / len(vals))
        assert signal_to_noise(vals, kind="larger_is_better") == pytest.approx(expected)

    def test_empty_returns_nan(self):
        assert math.isnan(signal_to_noise([]))

    def test_all_none_returns_nan(self):
        assert math.isnan(signal_to_noise([None, None]))

    def test_zeros_return_nan(self):
        # known limitation: v > 0 excludes zero costs (e.g. all-bot scenarios)
        assert math.isnan(signal_to_noise([0.0, 0.0]))

    def test_none_values_ignored(self):
        assert signal_to_noise([None, 2.0, None, 4.0]) == pytest.approx(
            signal_to_noise([2.0, 4.0])
        )

    def test_invalid_kind_raises(self):
        with pytest.raises(ValueError):
            signal_to_noise([1.0], kind="invalid")


# ── _parse_section ────────────────────────────────────────────────────────────

class TestParseSection:

    def test_section_found(self):
        rows = [
            [PROSIMOS_SECTION_TASK_STATS],
            ["task_id", PROSIMOS_COL_TOTAL_COST, "other"],
            ["task_a", "100.0", "x"],
            ["task_b",  "50.0", "y"],
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
            [],        # blank — stop here
            ["row2"],  # must not appear in data
        ]
        _, data = _parse_section(rows, "My Section")
        assert len(data) == 1

    def test_section_at_end_of_file(self):
        rows = [["My Section"]]   # no column header after it
        hdrs, data = _parse_section(rows, "My Section")
        assert hdrs == [] and data == []


# ── per_log_metrics ───────────────────────────────────────────────────────────

class TestPerLogMetrics:

    def test_cycle_time_median(self, tmp_path):
        log = tmp_path / "log.csv"
        _write_log(log, [
            ("c1", "2025-01-01T08:00:00", "2025-01-01T10:00:00"),  # 2 h
            ("c2", "2025-01-01T08:00:00", "2025-01-01T12:00:00"),  # 4 h
        ])
        assert per_log_metrics(log)[COL_CYCLE_H] == pytest.approx(3.0)

    def test_cost_from_stats(self, tmp_path):
        log = tmp_path / "log.csv"
        stats = tmp_path / "stats.csv"
        _write_log(log, [
            ("c1", "2025-01-01T08:00:00", "2025-01-01T09:00:00"),
            ("c2", "2025-01-01T08:00:00", "2025-01-01T09:00:00"),
        ])
        _write_stats(stats, [("task_a", 100.0), ("task_b", 50.0)])
        # total 150 / 2 cases = 75.0 per case
        assert per_log_metrics(log, stats)[COL_COST] == pytest.approx(75.0)

    def test_cost_none_without_stats(self, tmp_path):
        log = tmp_path / "log.csv"
        _write_log(log, [("c1", "2025-01-01T08:00:00", "2025-01-01T09:00:00")])
        assert per_log_metrics(log)[COL_COST] is None

    def test_cost_none_when_stats_file_missing(self, tmp_path):
        log = tmp_path / "log.csv"
        _write_log(log, [("c1", "2025-01-01T08:00:00", "2025-01-01T09:00:00")])
        assert per_log_metrics(log, tmp_path / "nonexistent.csv")[COL_COST] is None

    def test_cost_none_when_stats_malformed(self, tmp_path):
        log = tmp_path / "log.csv"
        stats = tmp_path / "stats.csv"
        _write_log(log, [("c1", "2025-01-01T08:00:00", "2025-01-01T09:00:00")])
        stats.write_text("no recognisable sections here\n")
        assert per_log_metrics(log, stats)[COL_COST] is None


# ── total_metrics ─────────────────────────────────────────────────────────────

class TestTotalMetrics:

    def test_total_cycle_s(self, tmp_path):
        stats = tmp_path / "stats.csv"
        _write_full_stats(stats, [("task_a", 50.0)], accumulated_cycle_s=3600.0)
        assert total_metrics(stats)[COL_TOTAL_CYCLE_S] == pytest.approx(3600.0)

    def test_total_cost_sum(self, tmp_path):
        stats = tmp_path / "stats.csv"
        _write_full_stats(stats, [("task_a", 100.0), ("task_b", 50.0)], accumulated_cycle_s=1.0)
        assert total_metrics(stats)[COL_TOTAL_COST] == pytest.approx(150.0)

    def test_missing_overall_section_raises(self, tmp_path):
        stats = tmp_path / "stats.csv"
        _write_stats(stats, [("task_a", 50.0)])  # only task stats, no overall section
        with pytest.raises(ValueError, match="Overall Scenario Statistics"):
            total_metrics(stats)

    def test_missing_cost_column_raises(self, tmp_path):
        stats = tmp_path / "stats.csv"
        with open(stats, "w", newline="") as f:
            import csv as _csv
            w = _csv.writer(f)
            w.writerow([PROSIMOS_SECTION_TASK_STATS])
            w.writerow(["task_id", "Some Other Column"])
            w.writerow(["task_a", "50.0"])
            w.writerow([])
            w.writerow([PROSIMOS_SECTION_OVERALL])
            w.writerow(["KPI", "Min", "Max", "Average", PROSIMOS_COL_ACCUMULATED, "Trace Occurrences"])
            w.writerow([PROSIMOS_KPI_CYCLE_TIME, "0", "0", "0", "3600.0", "100"])
        with pytest.raises(ValueError, match="Total Cost"):
            total_metrics(stats)


# ── aggregate ─────────────────────────────────────────────────────────────────

class TestAggregate:

    def test_one_row_per_scenario(self):
        assert len(aggregate(_results_df())) == 2

    def test_means_correct(self):
        agg = aggregate(_results_df())
        row = agg[agg["scenario_id"] == "S01"].iloc[0]
        assert row[COL_CYCLE_H_MEAN] == pytest.approx(11.0)
        assert row[COL_COST_MEAN]    == pytest.approx(6.0)

    def test_nan_cost_propagates(self):
        df = pd.DataFrame([{
            "scenario_id": "S01", "replication": 0,
            COL_CYCLE_H: 10.0, COL_COST: float("nan"), "f_a": "low",
        }])
        agg = aggregate(df)
        assert math.isnan(agg[COL_COST_MEAN].iloc[0])


# ── main_effects ──────────────────────────────────────────────────────────────

class TestMainEffects:

    def test_has_required_columns(self):
        me = main_effects(_results_df(), COL_CYCLE_H)
        assert {"factor", "level", "mean", "sn"} <= set(me.columns)

    def test_correct_factors_and_levels(self):
        me = main_effects(_results_df(), COL_CYCLE_H)
        assert set(me["factor"].unique()) == {"f_a"}
        assert set(me["level"].unique()) == {"low", "high"}

    def test_level_mean_correct(self):
        me = main_effects(_results_df(), COL_CYCLE_H)
        low_mean = me[me["level"] == "low"]["mean"].iloc[0]
        assert low_mean == pytest.approx(11.0)


# ── rank ──────────────────────────────────────────────────────────────────────

class TestRank:

    def test_goals_met_flag(self):
        agg = pd.DataFrame([
            {"scenario_id": "S01", COL_CYCLE_H_MEAN: 20.0},
            {"scenario_id": "S02", COL_CYCLE_H_MEAN: 30.0},
        ])
        ranked = rank(agg, COL_CYCLE_H_MEAN, 24.0)
        by_sid = ranked.set_index("scenario_id")
        assert by_sid.loc["S01", "goal_met"]
        assert not by_sid.loc["S02", "goal_met"]

    def test_goals_met_sorted_first(self):
        agg = pd.DataFrame([
            {"scenario_id": "S01", COL_CYCLE_H_MEAN: 30.0},
            {"scenario_id": "S02", COL_CYCLE_H_MEAN: 10.0},
        ])
        ranked = rank(agg, COL_CYCLE_H_MEAN, 24.0)
        assert ranked.iloc[0]["scenario_id"] == "S02"

    def test_nan_treated_as_unmet(self):
        agg = pd.DataFrame([{
            "scenario_id": "S01", COL_CYCLE_H_MEAN: float("nan"),
        }])
        ranked = rank(agg, COL_CYCLE_H_MEAN, 24.0)
        assert not ranked.iloc[0]["goal_met"]

    def test_cost_mean_metric(self):
        agg = pd.DataFrame([
            {"scenario_id": "S01", COL_COST_MEAN: 10.0},
            {"scenario_id": "S02", COL_COST_MEAN: 30.0},
        ])
        ranked = rank(agg, COL_COST_MEAN, 20.0)
        by_sid = ranked.set_index("scenario_id")
        assert by_sid.loc["S01", "goal_met"]
        assert not by_sid.loc["S02", "goal_met"]

    def test_score_value(self):
        agg = pd.DataFrame([{"scenario_id": "S01", COL_CYCLE_H_MEAN: 20.0}])
        ranked = rank(agg, COL_CYCLE_H_MEAN, 40.0)
        assert ranked.iloc[0]["score"] == pytest.approx(0.5)

    def test_zero_goal_max_raises(self):
        agg = pd.DataFrame([{"scenario_id": "S01", COL_CYCLE_H_MEAN: 20.0}])
        with pytest.raises(ValueError):
            rank(agg, COL_CYCLE_H_MEAN, 0.0)
