"""Tests for core/analysis.py — no external tools required."""

from __future__ import annotations
import math

import pandas as pd
import pytest

from core.analysis import (
    aggregate,
    compare_to_baseline,
    main_effects,
    signal_to_noise,
    rank,
)
from core.goals import Goal
from core.metrics import MetricDirection, MetricRegistry
from core.constants import (
    COL_MEAN_CYCLE_H,
    COL_MEAN_COST,
    COL_MEAN_CYCLE_H_MEAN,
    COL_MEAN_COST_MEAN,
    COL_TOTAL_CYCLE_S,
    COL_TOTAL_COST,
    COL_TOTAL_CYCLE_S_MEAN,
    COL_TOTAL_COST_MEAN,
    COL_TOTAL_REWORK_COUNT,
    COL_REWORK_RATE,
    COL_TOTAL_REWORK_COUNT_MEAN,
    COL_REWORK_RATE_MEAN,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _results_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario_id": "S01",
                "replication": 0,
                COL_MEAN_CYCLE_H: 10.0,
                COL_MEAN_COST: 5.0,
                "f_a": "low",
                COL_TOTAL_CYCLE_S: 36000.0,
                COL_TOTAL_COST: 500.0,
                COL_TOTAL_REWORK_COUNT: 2.0,
                COL_REWORK_RATE: 10.0,
            },
            {
                "scenario_id": "S01",
                "replication": 1,
                COL_MEAN_CYCLE_H: 12.0,
                COL_MEAN_COST: 7.0,
                "f_a": "low",
                COL_TOTAL_CYCLE_S: 43200.0,
                COL_TOTAL_COST: 700.0,
                COL_TOTAL_REWORK_COUNT: 4.0,
                COL_REWORK_RATE: 20.0,
            },
            {
                "scenario_id": "S02",
                "replication": 0,
                COL_MEAN_CYCLE_H: 20.0,
                COL_MEAN_COST: 10.0,
                "f_a": "high",
                COL_TOTAL_CYCLE_S: 72000.0,
                COL_TOTAL_COST: 1000.0,
                COL_TOTAL_REWORK_COUNT: 0.0,
                COL_REWORK_RATE: 0.0,
            },
            {
                "scenario_id": "S02",
                "replication": 1,
                COL_MEAN_CYCLE_H: 22.0,
                COL_MEAN_COST: 12.0,
                "f_a": "high",
                COL_TOTAL_CYCLE_S: 79200.0,
                COL_TOTAL_COST: 1200.0,
                COL_TOTAL_REWORK_COUNT: 2.0,
                COL_REWORK_RATE: 10.0,
            },
        ]
    )


# ── signal_to_noise ───────────────────────────────────────────────────────────


class TestSignalToNoise:
    def test_smaller_is_better(self):
        vals = [2.0, 4.0, 4.0]
        expected = -10 * math.log10(sum(v * v for v in vals) / len(vals))
        assert signal_to_noise(vals) == pytest.approx(expected)

    def test_larger_is_better(self):
        vals = [2.0, 4.0]
        expected = -10 * math.log10(sum(1 / (v * v) for v in vals) / len(vals))
        assert signal_to_noise(
            vals, direction=MetricDirection.LARGER_IS_BETTER
        ) == pytest.approx(expected)

    def test_empty_returns_nan(self):
        assert math.isnan(signal_to_noise([]))

    def test_all_none_returns_nan(self):
        assert math.isnan(signal_to_noise([None, None]))

    def test_zeros_return_nan_without_floor(self):
        assert math.isnan(signal_to_noise([0.0, 0.0]))

    def test_floor_prevents_nan_for_zeros(self):
        result = signal_to_noise([0.0, 0.0], floor=0.01)
        assert not math.isnan(result)
        expected = -10 * math.log10(sum(v * v for v in [0.01, 0.01]) / 2)
        assert result == pytest.approx(expected)

    def test_floor_applied_to_nonzero_values(self):
        result = signal_to_noise([2.0, 4.0], floor=0.01)
        expected = -10 * math.log10(sum(v * v for v in [2.01, 4.01]) / 2)
        assert result == pytest.approx(expected)

    def test_none_values_ignored(self):
        assert signal_to_noise([None, 2.0, None, 4.0]) == pytest.approx(
            signal_to_noise([2.0, 4.0])
        )

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError):
            signal_to_noise([1.0], direction="invalid")  # type: ignore[arg-type]


# ── aggregate ─────────────────────────────────────────────────────────────────


class TestAggregate:
    def test_one_row_per_scenario(self):
        assert len(aggregate(_results_df())) == 2

    def test_means_correct(self):
        agg = aggregate(_results_df())
        row = agg[agg["scenario_id"] == "S01"].iloc[0]
        assert row[COL_MEAN_CYCLE_H_MEAN] == pytest.approx(11.0)
        assert row[COL_MEAN_COST_MEAN] == pytest.approx(6.0)

    def test_rework_means_correct(self):
        agg = aggregate(_results_df())
        row = agg[agg["scenario_id"] == "S01"].iloc[0]
        assert row[COL_TOTAL_REWORK_COUNT_MEAN] == pytest.approx(3.0)  # (2 + 4) / 2
        assert row[COL_REWORK_RATE_MEAN] == pytest.approx(15.0)  # (10.0 + 20.0) / 2

    def test_nan_cost_propagates(self):
        df = pd.DataFrame(
            [
                {
                    "scenario_id": "S01",
                    "replication": 0,
                    "f_a": "low",
                    COL_MEAN_CYCLE_H: 10.0,
                    COL_MEAN_COST: float("nan"),
                    COL_TOTAL_CYCLE_S: 36000.0,
                    COL_TOTAL_COST: 500.0,
                    COL_TOTAL_REWORK_COUNT: 2.0,
                    COL_REWORK_RATE: 5.0,
                }
            ]
        )
        agg = aggregate(df)
        assert math.isnan(agg[COL_MEAN_COST_MEAN].iloc[0])


# ── compare_to_baseline ───────────────────────────────────────────────────────


class TestCompareToBaseline:
    def _agg(self):
        return pd.DataFrame(
            [
                {
                    "scenario_id": "S01",
                    "num_cases": 100,
                    COL_TOTAL_CYCLE_S_MEAN: 7200.0,
                    COL_TOTAL_COST_MEAN: 200.0,
                    COL_TOTAL_REWORK_COUNT_MEAN: 5.0,
                    COL_REWORK_RATE_MEAN: 10.0,
                },
                {
                    "scenario_id": "S02",
                    "num_cases": 100,
                    COL_TOTAL_CYCLE_S_MEAN: 3600.0,
                    COL_TOTAL_COST_MEAN: 80.0,
                    COL_TOTAL_REWORK_COUNT_MEAN: 2.0,
                    COL_REWORK_RATE_MEAN: 4.0,
                },
            ]
        )

    def _baseline(self):
        return {
            100: {
                COL_TOTAL_CYCLE_S_MEAN: 3600.0,
                COL_TOTAL_COST_MEAN: 100.0,
                COL_TOTAL_REWORK_COUNT_MEAN: 4.0,
                COL_REWORK_RATE_MEAN: 8.0,
            }
        }

    def test_baseline_row_is_first(self):
        df = compare_to_baseline(self._agg(), self._baseline())
        assert df.iloc[0]["Scenario"] == "Baseline (100 cases)"

    def test_row_count(self):
        df = compare_to_baseline(self._agg(), self._baseline())
        assert len(df) == 3  # baseline + 2 scenarios

    def test_baseline_deltas_are_zero(self):
        df = compare_to_baseline(self._agg(), self._baseline())
        assert df.iloc[0]["Δ Time (h)"] == 0.0
        assert df.iloc[0]["Δ Cost ($)"] == 0.0

    def test_delta_values(self):
        df = compare_to_baseline(self._agg(), self._baseline())
        s02 = df[df["Scenario"] == "S02"].iloc[0]
        assert s02["Total Cycle Time (h)"] == pytest.approx(1.0)
        assert s02["Δ Time (h)"] == pytest.approx(0.0)
        assert s02["Δ Cost ($)"] == pytest.approx(-20.0)
        assert s02["Δ Cost (%)"] == pytest.approx(-20.0)

    def test_baseline_rework_deltas_are_zero(self):
        df = compare_to_baseline(self._agg(), self._baseline())
        baseline = df.iloc[0]
        assert baseline["Δ Rework Count"] == 0.0
        assert baseline["Δ Rate (pp)"] == 0.0

    def test_rework_delta_values(self):
        df = compare_to_baseline(self._agg(), self._baseline())
        s02 = df[df["Scenario"] == "S02"].iloc[0]
        assert s02["Rework Count"] == pytest.approx(2.0)
        assert s02["Δ Rework Count"] == pytest.approx(-2.0)
        assert s02["Δ Rework (%)"] == pytest.approx(-50.0)
        assert s02["Rework Rate (%)"] == pytest.approx(4.0)
        assert s02["Δ Rate (pp)"] == pytest.approx(-4.0)

    def test_multiple_levels_produce_multiple_baseline_rows(self):
        agg = pd.DataFrame(
            [
                {
                    "scenario_id": "S01",
                    "num_cases": 100,
                    COL_TOTAL_CYCLE_S_MEAN: 3600.0,
                    COL_TOTAL_COST_MEAN: 100.0,
                    COL_TOTAL_REWORK_COUNT_MEAN: 4.0,
                    COL_REWORK_RATE_MEAN: 8.0,
                },
                {
                    "scenario_id": "S02",
                    "num_cases": 1000,
                    COL_TOTAL_CYCLE_S_MEAN: 3600.0,
                    COL_TOTAL_COST_MEAN: 100.0,
                    COL_TOTAL_REWORK_COUNT_MEAN: 4.0,
                    COL_REWORK_RATE_MEAN: 8.0,
                },
            ]
        )
        baseline = {
            100: {
                COL_TOTAL_CYCLE_S_MEAN: 3600.0,
                COL_TOTAL_COST_MEAN: 100.0,
                COL_TOTAL_REWORK_COUNT_MEAN: 4.0,
                COL_REWORK_RATE_MEAN: 8.0,
            },
            1000: {
                COL_TOTAL_CYCLE_S_MEAN: 36000.0,
                COL_TOTAL_COST_MEAN: 1000.0,
                COL_TOTAL_REWORK_COUNT_MEAN: 40.0,
                COL_REWORK_RATE_MEAN: 8.0,
            },
        }
        df = compare_to_baseline(agg, baseline)
        baseline_rows = df[df["Scenario"].str.startswith("Baseline")]
        assert len(baseline_rows) == 2
        assert set(baseline_rows["Cases"]) == {100, 1000}


# ── main_effects ──────────────────────────────────────────────────────────────


class TestMainEffects:
    def test_has_required_columns(self):
        me = main_effects(_results_df(), MetricRegistry.CYCLE_TIME)
        assert {"factor", "level", "mean", "sn"} <= set(me.columns)

    def test_correct_factors_and_levels(self):
        me = main_effects(_results_df(), MetricRegistry.CYCLE_TIME)
        assert set(me["factor"].unique()) == {"f_a"}
        assert set(me["level"].unique()) == {"low", "high"}

    def test_level_mean_correct(self):
        me = main_effects(_results_df(), MetricRegistry.CYCLE_TIME)
        low_mean = me[me["level"] == "low"]["mean"].iloc[0]
        assert low_mean == pytest.approx(11.0)

    def test_rework_rate_metric(self):
        me = main_effects(_results_df(), MetricRegistry.REWORK_RATE)
        low_mean = me[me["level"] == "low"]["mean"].iloc[0]
        assert low_mean == pytest.approx(15.0)  # (10.0 + 20.0) / 2


# ── rank ──────────────────────────────────────────────────────────────────────


def _sib_goal(metric: str, baseline: float) -> Goal:
    """Smaller-is-better goal with target=0.9×b, threshold=b, worst=1.1×b."""
    from core.metrics import MetricDirection

    return Goal.from_baseline(metric, baseline, MetricDirection.SMALLER_IS_BETTER)


class TestRank:
    def test_per_goal_score_column_added(self):
        agg = pd.DataFrame([{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 100.0}])
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert f"{COL_MEAN_CYCLE_H_MEAN}_score" in ranked.columns

    def test_per_goal_met_column_added(self):
        agg = pd.DataFrame([{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 100.0}])
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert f"{COL_MEAN_CYCLE_H_MEAN}_met" in ranked.columns

    def test_overall_score_column_added(self):
        agg = pd.DataFrame([{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 100.0}])
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert "score" in ranked.columns

    def test_score_at_target_is_100(self):
        # value = 0.9 × baseline → at target → score 100
        agg = pd.DataFrame([{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 90.0}])
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert ranked.iloc[0][f"{COL_MEAN_CYCLE_H_MEAN}_score"] == pytest.approx(100.0)

    def test_score_at_threshold_is_50(self):
        # value = baseline → at threshold → score 50
        agg = pd.DataFrame([{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 100.0}])
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert ranked.iloc[0][f"{COL_MEAN_CYCLE_H_MEAN}_score"] == pytest.approx(50.0)

    def test_score_at_worst_is_0(self):
        # value = 1.1 × baseline → at worst → score 0
        agg = pd.DataFrame([{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 110.0}])
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert ranked.iloc[0][f"{COL_MEAN_CYCLE_H_MEAN}_score"] == pytest.approx(0.0)

    def test_met_true_when_at_target(self):
        agg = pd.DataFrame([{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 90.0}])
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert ranked.iloc[0][f"{COL_MEAN_CYCLE_H_MEAN}_met"]

    def test_met_false_when_at_threshold(self):
        agg = pd.DataFrame([{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 100.0}])
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert not ranked.iloc[0][f"{COL_MEAN_CYCLE_H_MEAN}_met"]

    def test_nan_gets_score_0(self):
        agg = pd.DataFrame(
            [{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: float("nan")}]
        )
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert ranked.iloc[0][f"{COL_MEAN_CYCLE_H_MEAN}_score"] == pytest.approx(0.0)
        assert not ranked.iloc[0][f"{COL_MEAN_CYCLE_H_MEAN}_met"]

    def test_overall_score_is_min_of_per_goal_scores(self):
        # Goal 1: value=90 (at target) → score 100
        # Goal 2: value=100 (at threshold) → score 50
        # Overall score = min(100, 50) = 50
        agg = pd.DataFrame(
            [
                {
                    "scenario_id": "S01",
                    COL_MEAN_CYCLE_H_MEAN: 90.0,
                    COL_MEAN_COST_MEAN: 100.0,
                }
            ]
        )
        goals = [
            _sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0),
            _sib_goal(COL_MEAN_COST_MEAN, 100.0),
        ]
        ranked = rank(agg, goals)
        assert ranked.iloc[0]["score"] == pytest.approx(50.0)

    def test_sorted_descending_by_score(self):
        # S01: at threshold (score 50); S02: at target (score 100) → S02 ranked first
        agg = pd.DataFrame(
            [
                {"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 100.0},
                {"scenario_id": "S02", COL_MEAN_CYCLE_H_MEAN: 90.0},
            ]
        )
        ranked = rank(agg, [_sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0)])
        assert ranked.iloc[0]["scenario_id"] == "S02"

    def test_per_goal_met_independent_across_goals(self):
        # S01 meets cycle time but not cost
        agg = pd.DataFrame(
            [
                {
                    "scenario_id": "S01",
                    COL_MEAN_CYCLE_H_MEAN: 90.0,
                    COL_MEAN_COST_MEAN: 100.0,
                }
            ]
        )
        goals = [
            _sib_goal(COL_MEAN_CYCLE_H_MEAN, 100.0),  # met (value at target)
            _sib_goal(COL_MEAN_COST_MEAN, 100.0),  # not met (value at threshold)
        ]
        ranked = rank(agg, goals)
        assert ranked.iloc[0][f"{COL_MEAN_CYCLE_H_MEAN}_met"]
        assert not ranked.iloc[0][f"{COL_MEAN_COST_MEAN}_met"]

    def test_empty_goals_produces_zero_score(self):
        agg = pd.DataFrame([{"scenario_id": "S01", COL_MEAN_CYCLE_H_MEAN: 90.0}])
        ranked = rank(agg, [])
        assert ranked.iloc[0]["score"] == pytest.approx(0.0)
