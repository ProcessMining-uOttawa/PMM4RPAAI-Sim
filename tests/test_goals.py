"""Tests for core/goals.py — Goal and baseline_per_case."""

from __future__ import annotations

import math

import pytest

from core.goals import Goal, baseline_per_case
from core.metrics import MetricDirection, MetricRegistry
from core.constants import (
    COL_MEAN_CYCLE_H_MEAN,
    COL_MEAN_COST_MEAN,
    COL_REWORK_RATE_MEAN,
    COL_TOTAL_CYCLE_S_MEAN,
    COL_TOTAL_COST_MEAN,
)

# ── Goal.from_metric ─────────────────────────────────────────────────────────


class TestFromMetric:
    def test_delegates_to_from_baseline_correctly(self):
        baseline = {"mean_cycle_h_mean": 100.0, "mean_cost_mean": 50.0, "rework_rate_mean": 5.0}
        goal = Goal.from_metric(MetricRegistry.CYCLE_TIME, baseline)
        assert goal.metric == "mean_cycle_h_mean"
        assert goal.target == pytest.approx(90.0)
        assert goal.baseline_ref == pytest.approx(100.0)
        assert goal.worst == pytest.approx(110.0)

    def test_raises_when_metric_has_no_per_case(self):
        baseline = {"total_rework_count_mean": 5.0}
        with pytest.raises(ValueError, match="per_case data"):
            Goal.from_metric(MetricRegistry.REWORK_COUNT, baseline)


# ── Goal.from_baseline ────────────────────────────────────────────────────────


class TestFromBaseline:
    def test_sib_target_is_10pct_below_baseline(self):
        goal = Goal.from_baseline("col", 100.0, MetricDirection.SMALLER_IS_BETTER)
        assert goal.target == pytest.approx(90.0)

    def test_sib_baseline_ref_is_baseline(self):
        goal = Goal.from_baseline("col", 100.0, MetricDirection.SMALLER_IS_BETTER)
        assert goal.baseline_ref == pytest.approx(100.0)

    def test_sib_worst_is_10pct_above_baseline(self):
        goal = Goal.from_baseline("col", 100.0, MetricDirection.SMALLER_IS_BETTER)
        assert goal.worst == pytest.approx(110.0)

    def test_lib_target_is_10pct_above_baseline(self):
        goal = Goal.from_baseline("col", 100.0, MetricDirection.LARGER_IS_BETTER)
        assert goal.target == pytest.approx(110.0)

    def test_lib_baseline_ref_is_baseline(self):
        goal = Goal.from_baseline("col", 100.0, MetricDirection.LARGER_IS_BETTER)
        assert goal.baseline_ref == pytest.approx(100.0)

    def test_lib_worst_is_10pct_below_baseline(self):
        goal = Goal.from_baseline("col", 100.0, MetricDirection.LARGER_IS_BETTER)
        assert goal.worst == pytest.approx(90.0)

    def test_metric_name_preserved(self):
        goal = Goal.from_baseline("mean_cycle_h_mean", 10.0, MetricDirection.SMALLER_IS_BETTER)
        assert goal.metric == "mean_cycle_h_mean"

    def test_zero_baseline_produces_all_zero_breakpoints(self):
        goal = Goal.from_baseline("col", 0.0, MetricDirection.SMALLER_IS_BETTER)
        assert goal.target == pytest.approx(0.0)
        assert goal.baseline_ref == pytest.approx(0.0)
        assert goal.worst == pytest.approx(0.0)


# ── Goal.score ────────────────────────────────────────────────────────────────


class TestGoalScore:
    def _sib_goal(self) -> Goal:
        # target=90, baseline_ref=100, worst=110
        return Goal.from_baseline("col", 100.0, MetricDirection.SMALLER_IS_BETTER)

    def test_at_target_is_100(self):
        assert self._sib_goal().score(90.0) == pytest.approx(100.0)

    def test_below_target_is_100(self):
        assert self._sib_goal().score(80.0) == pytest.approx(100.0)

    def test_at_baseline_ref_is_50(self):
        assert self._sib_goal().score(100.0) == pytest.approx(50.0)

    def test_at_worst_is_0(self):
        assert self._sib_goal().score(110.0) == pytest.approx(0.0)

    def test_beyond_worst_is_0(self):
        assert self._sib_goal().score(120.0) == pytest.approx(0.0)

    def test_midpoint_target_baseline_ref_is_75(self):
        # midpoint of [90, 100] = 95 → score = (100-95)/(100-90)*50+50 = 5/10*50+50 = 75
        assert self._sib_goal().score(95.0) == pytest.approx(75.0)

    def test_midpoint_baseline_ref_worst_is_25(self):
        # midpoint of [100, 110] = 105 → score = -(105-100)/(110-100)*50+50 = -5/10*50+50 = 25
        assert self._sib_goal().score(105.0) == pytest.approx(25.0)

    def test_nan_returns_0(self):
        assert self._sib_goal().score(float("nan")) == pytest.approx(0.0)

    def test_lib_at_target_is_100(self):
        # LIB: target=110, baseline_ref=100, worst=90
        goal = Goal.from_baseline("col", 100.0, MetricDirection.LARGER_IS_BETTER)
        assert goal.score(110.0) == pytest.approx(100.0)

    def test_lib_beyond_target_is_100(self):
        goal = Goal.from_baseline("col", 100.0, MetricDirection.LARGER_IS_BETTER)
        assert goal.score(120.0) == pytest.approx(100.0)

    def test_lib_at_baseline_ref_is_50(self):
        goal = Goal.from_baseline("col", 100.0, MetricDirection.LARGER_IS_BETTER)
        assert goal.score(100.0) == pytest.approx(50.0)

    def test_lib_at_worst_is_0(self):
        goal = Goal.from_baseline("col", 100.0, MetricDirection.LARGER_IS_BETTER)
        assert goal.score(90.0) == pytest.approx(0.0)

    def test_lib_midpoint_baseline_ref_target_is_75(self):
        # midpoint of [100, 110] = 105 → score = (105-100)/(110-100)*50+50 = 75
        goal = Goal.from_baseline("col", 100.0, MetricDirection.LARGER_IS_BETTER)
        assert goal.score(105.0) == pytest.approx(75.0)


# ── Goal.is_met ───────────────────────────────────────────────────────────────


class TestGoalIsMet:
    def _sib_goal(self) -> Goal:
        return Goal.from_baseline("col", 100.0, MetricDirection.SMALLER_IS_BETTER)

    def test_at_target_is_met(self):
        assert self._sib_goal().is_met(90.0)

    def test_below_target_is_met(self):
        assert self._sib_goal().is_met(50.0)

    def test_at_baseline_ref_not_met(self):
        assert not self._sib_goal().is_met(100.0)

    def test_nan_not_met(self):
        assert not self._sib_goal().is_met(float("nan"))


# ── baseline_per_case ─────────────────────────────────────────────────────────


class TestBaselinePerCase:
    def _agg(self, total_cycle_s: float, total_cost: float, rework_rate: float) -> dict:
        return {
            COL_TOTAL_CYCLE_S_MEAN: total_cycle_s,
            COL_TOTAL_COST_MEAN: total_cost,
            COL_REWORK_RATE_MEAN: rework_rate,
        }

    def test_cycle_time_per_case(self):
        agg = {100: self._agg(total_cycle_s=360000.0, total_cost=0.0, rework_rate=0.0)}
        result = baseline_per_case(agg)
        # 360000 s / 3600 / 100 cases = 1.0 h/case
        assert result[COL_MEAN_CYCLE_H_MEAN] == pytest.approx(1.0)

    def test_cost_per_case(self):
        agg = {100: self._agg(total_cycle_s=1.0, total_cost=500.0, rework_rate=0.0)}
        result = baseline_per_case(agg)
        # 500 / 100 cases = 5.0 $/case
        assert result[COL_MEAN_COST_MEAN] == pytest.approx(5.0)

    def test_rework_rate_passed_through(self):
        agg = {100: self._agg(total_cycle_s=1.0, total_cost=0.0, rework_rate=12.5)}
        result = baseline_per_case(agg)
        assert result[COL_REWORK_RATE_MEAN] == pytest.approx(12.5)

    def test_picks_smallest_n_cases_when_multiple(self):
        agg = {
            100: self._agg(total_cycle_s=360000.0, total_cost=500.0, rework_rate=5.0),
            500: self._agg(total_cycle_s=1800000.0, total_cost=2500.0, rework_rate=5.0),
        }
        result = baseline_per_case(agg)
        # n_ref=100: 360000/3600/100 = 1.0 h/case (not 500 entry)
        assert result[COL_MEAN_CYCLE_H_MEAN] == pytest.approx(1.0)
