"""Tests for core/goals.py — Goal and baseline_per_case."""

from __future__ import annotations

import pytest

from core.goals import Goal, baseline_per_case
from core.constants import (
    COL_MEAN_CYCLE_H_MEAN,
    COL_MEAN_COST_MEAN,
    COL_REWORK_RATE_MEAN,
    COL_TOTAL_CYCLE_S_MEAN,
    COL_TOTAL_COST_MEAN,
)


class TestGoal:
    def test_from_pct_reduction_absolute_target(self):
        goal = Goal.from_pct_reduction("col", weight=0.5, pct=20.0, baseline_val=25.0)
        assert goal.target == pytest.approx(20.0)  # 25 * 0.8

    def test_from_pct_reduction_zero_pct(self):
        goal = Goal.from_pct_reduction("col", weight=1.0, pct=0.0, baseline_val=25.0)
        assert goal.target == pytest.approx(25.0)  # 25 * 1.0

    def test_from_pct_reduction_preserves_metric_and_weight(self):
        goal = Goal.from_pct_reduction(
            "mean_cycle_h_mean", weight=0.4, pct=10.0, baseline_val=30.0
        )
        assert goal.metric == "mean_cycle_h_mean"
        assert goal.weight == pytest.approx(0.4)


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
