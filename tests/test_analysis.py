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
    aggregate,
    main_effects,
    signal_to_noise,
    rank,
)
from core.constants import PROSIMOS_SECTION_TASK_STATS, PROSIMOS_COL_TOTAL_COST


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


def _results_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"scenario_id": "S01", "replication": 0, "cycle_h": 10.0, "cost":  5.0, "f_a": "low"},
        {"scenario_id": "S01", "replication": 1, "cycle_h": 12.0, "cost":  7.0, "f_a": "low"},
        {"scenario_id": "S02", "replication": 0, "cycle_h": 20.0, "cost": 10.0, "f_a": "high"},
        {"scenario_id": "S02", "replication": 1, "cycle_h": 22.0, "cost": 12.0, "f_a": "high"},
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
        assert per_log_metrics(log)["cycle_h"] == pytest.approx(3.0)

    def test_cost_from_stats(self, tmp_path):
        log = tmp_path / "log.csv"
        stats = tmp_path / "stats.csv"
        _write_log(log, [
            ("c1", "2025-01-01T08:00:00", "2025-01-01T09:00:00"),
            ("c2", "2025-01-01T08:00:00", "2025-01-01T09:00:00"),
        ])
        _write_stats(stats, [("task_a", 100.0), ("task_b", 50.0)])
        # total 150 / 2 cases = 75.0 per case
        assert per_log_metrics(log, stats)["cost"] == pytest.approx(75.0)

    def test_cost_none_without_stats(self, tmp_path):
        log = tmp_path / "log.csv"
        _write_log(log, [("c1", "2025-01-01T08:00:00", "2025-01-01T09:00:00")])
        assert per_log_metrics(log)["cost"] is None

    def test_cost_none_when_stats_file_missing(self, tmp_path):
        log = tmp_path / "log.csv"
        _write_log(log, [("c1", "2025-01-01T08:00:00", "2025-01-01T09:00:00")])
        assert per_log_metrics(log, tmp_path / "nonexistent.csv")["cost"] is None

    def test_cost_none_when_stats_malformed(self, tmp_path):
        log = tmp_path / "log.csv"
        stats = tmp_path / "stats.csv"
        _write_log(log, [("c1", "2025-01-01T08:00:00", "2025-01-01T09:00:00")])
        stats.write_text("no recognisable sections here\n")
        assert per_log_metrics(log, stats)["cost"] is None


# ── aggregate ─────────────────────────────────────────────────────────────────

class TestAggregate:

    def test_one_row_per_scenario(self):
        assert len(aggregate(_results_df())) == 2

    def test_means_correct(self):
        agg = aggregate(_results_df())
        row = agg[agg["scenario_id"] == "S01"].iloc[0]
        assert row["cycle_h_mean"] == pytest.approx(11.0)
        assert row["cost_mean"]    == pytest.approx(6.0)

    def test_nan_cost_propagates(self):
        df = pd.DataFrame([{
            "scenario_id": "S01", "replication": 0,
            "cycle_h": 10.0, "cost": float("nan"), "f_a": "low",
        }])
        agg = aggregate(df)
        assert math.isnan(agg["cost_mean"].iloc[0])


# ── main_effects ──────────────────────────────────────────────────────────────

class TestMainEffects:

    def test_has_required_columns(self):
        me = main_effects(_results_df(), "cycle_h")
        assert {"factor", "level", "mean", "sn"} <= set(me.columns)

    def test_correct_factors_and_levels(self):
        me = main_effects(_results_df(), "cycle_h")
        assert set(me["factor"].unique()) == {"f_a"}
        assert set(me["level"].unique()) == {"low", "high"}

    def test_level_mean_correct(self):
        me = main_effects(_results_df(), "cycle_h")
        low_mean = me[me["level"] == "low"]["mean"].iloc[0]
        assert low_mean == pytest.approx(11.0)


# ── rank ──────────────────────────────────────────────────────────────────────

class TestRank:

    def test_goals_met_flag(self):
        agg = pd.DataFrame([
            {"scenario_id": "S01", "cycle_h_mean": 20.0},
            {"scenario_id": "S02", "cycle_h_mean": 30.0},
        ])
        ranked = rank(agg, "cycle_h_mean", 24.0)
        by_sid = ranked.set_index("scenario_id")
        assert bool(by_sid.loc["S01", "goals_met"]) is True
        assert bool(by_sid.loc["S02", "goals_met"]) is False

    def test_goals_met_sorted_first(self):
        agg = pd.DataFrame([
            {"scenario_id": "S01", "cycle_h_mean": 30.0},
            {"scenario_id": "S02", "cycle_h_mean": 10.0},
        ])
        ranked = rank(agg, "cycle_h_mean", 24.0)
        assert ranked.iloc[0]["scenario_id"] == "S02"

    def test_nan_treated_as_unmet(self):
        agg = pd.DataFrame([{
            "scenario_id": "S01", "cycle_h_mean": float("nan"),
        }])
        ranked = rank(agg, "cycle_h_mean", 24.0)
        assert bool(ranked.iloc[0]["goals_met"]) is False
