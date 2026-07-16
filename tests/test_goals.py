"""Tests for core/goals.py — Goal and baseline_per_case."""

from __future__ import annotations


import pytest

from core.goals import Goal, baseline_per_case
from core.metrics import MetricDirection, MetricRegistry
from core.constants import (
    COL_MEAN_CYCLE_H_MEAN,
    COL_MEDIAN_CYCLE_H_MEAN,
    COL_MEAN_COST_MEAN,
    COL_REWORK_RATE_MEAN,
    COL_TOTAL_CYCLE_S_MEAN,
    COL_TOTAL_COST_MEAN,
)

# ── Goal.from_metric ─────────────────────────────────────────────────────────


class TestFromMetric:
    def test_delegates_to_from_baseline_correctly(self):
        baseline = {
            "mean_cycle_h_mean": 100.0,
            "mean_cost_mean": 50.0,
            "rework_rate_mean": 5.0,
        }
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
        goal = Goal.from_baseline(
            "mean_cycle_h_mean", 10.0, MetricDirection.SMALLER_IS_BETTER
        )
        assert goal.metric == "mean_cycle_h_mean"

    def test_zero_baseline_produces_all_zero_breakpoints(self):
        goal = Goal.from_baseline("col", 0.0, MetricDirection.SMALLER_IS_BETTER)
        assert goal.target == pytest.approx(0.0)
        assert goal.baseline_ref == pytest.approx(0.0)
        assert goal.worst == pytest.approx(0.0)


# ── Goal ordering guard ──────────────────────────────────────────────────────


class TestGoalOrderingGuard:
    """__post_init__ rejects breakpoints score() cannot interpolate coherently."""

    def test_baseline_above_both_raises(self):
        # SIB shape but baseline beyond worst: score() would cliff, so construction fails.
        with pytest.raises(ValueError, match="must lie between"):
            Goal(metric="col", target=90.0, baseline_ref=120.0, worst=110.0)

    def test_baseline_below_both_raises(self):
        with pytest.raises(ValueError, match="must lie between"):
            Goal(metric="col", target=90.0, baseline_ref=80.0, worst=110.0)

    def test_error_names_the_metric(self):
        with pytest.raises(ValueError, match="mean_cost_mean"):
            Goal(metric="mean_cost_mean", target=5.0, baseline_ref=20.0, worst=10.0)

    def test_baseline_equal_target_is_allowed(self):
        goal = Goal(metric="col", target=100.0, baseline_ref=100.0, worst=110.0)
        assert goal.baseline_ref == pytest.approx(100.0)

    def test_baseline_equal_worst_is_allowed(self):
        goal = Goal(metric="col", target=90.0, baseline_ref=110.0, worst=110.0)
        assert goal.baseline_ref == pytest.approx(110.0)

    def test_degenerate_all_equal_is_allowed(self):
        # from_baseline(0.0) produces this shape; score() handles the zero spans.
        goal = Goal(metric="col", target=0.0, baseline_ref=0.0, worst=0.0)
        assert goal.score(0.0) == pytest.approx(100.0)

    def test_lib_ordering_is_allowed(self):
        # Larger-is-better: target above worst, baseline between.
        goal = Goal(metric="col", target=110.0, baseline_ref=100.0, worst=90.0)
        assert goal.score(100.0) == pytest.approx(50.0)


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


# ── baseline_per_case ─────────────────────────────────────────────────────────


class TestBaselinePerCase:
    def _record(self, **overrides) -> dict:
        """A flat baseline_agg record: per-case means beside the totals."""
        record = {
            COL_MEAN_CYCLE_H_MEAN: 1.0,
            COL_MEDIAN_CYCLE_H_MEAN: 28.0,
            COL_MEAN_COST_MEAN: 5.0,
            COL_REWORK_RATE_MEAN: 5.0,
            COL_TOTAL_CYCLE_S_MEAN: 360000.0,
            COL_TOTAL_COST_MEAN: 500.0,
        }
        record.update(overrides)
        return record

    def test_per_case_values_picked_through(self):
        result = baseline_per_case(
            self._record(
                **{
                    COL_MEAN_CYCLE_H_MEAN: 1.5,
                    COL_MEDIAN_CYCLE_H_MEAN: 27.5,
                    COL_MEAN_COST_MEAN: 7.0,
                    COL_REWORK_RATE_MEAN: 12.5,
                }
            )
        )
        assert result[COL_MEAN_CYCLE_H_MEAN] == pytest.approx(1.5)
        assert result[COL_MEDIAN_CYCLE_H_MEAN] == pytest.approx(27.5)
        assert result[COL_MEAN_COST_MEAN] == pytest.approx(7.0)
        assert result[COL_REWORK_RATE_MEAN] == pytest.approx(12.5)

    def test_totals_filtered_out(self):
        # A filter, not a pass-through: Goal.from_metric gets exactly the
        # per-case keys, never the totals riding along in the record.
        result = baseline_per_case(self._record())
        assert COL_TOTAL_CYCLE_S_MEAN not in result
        assert COL_TOTAL_COST_MEAN not in result

    def test_missing_per_case_key_raises(self):
        # A record without a per-case key is malformed — loud, not defaulted.
        record = self._record()
        del record[COL_MEAN_COST_MEAN]
        with pytest.raises(KeyError):
            baseline_per_case(record)


# ── Goal.weighted_score (two-factor goal) ─────────────────────────────────────


class TestWeightedGoal:
    """Goal.secondary + weight — the two-factor time goal's weighted scoring."""

    def _secondary(self) -> Goal:
        # SIB: target=90, baseline=100, worst=110
        return Goal.from_baseline(
            COL_MEDIAN_CYCLE_H_MEAN, 100.0, MetricDirection.SMALLER_IS_BETTER
        )

    def _two_factor(self, weight: float) -> Goal:
        return Goal(
            metric=COL_MEAN_CYCLE_H_MEAN,
            target=90.0,
            baseline_ref=100.0,
            worst=110.0,
            secondary=self._secondary(),
            weight=weight,
        )

    def test_single_factor_weighted_score_is_just_score(self):
        goal = Goal.from_baseline(
            COL_MEAN_CYCLE_H_MEAN, 100.0, MetricDirection.SMALLER_IS_BETTER
        )
        assert goal.weighted_score(100.0) == pytest.approx(goal.score(100.0))

    def test_weighted_sum_of_two_factors(self):
        # primary at target (100), secondary at worst (0), weight 0.75 → 75.
        assert self._two_factor(0.75).weighted_score(90.0, 110.0) == pytest.approx(75.0)

    def test_weight_one_ignores_secondary(self):
        # secondary at worst would drag it down, but weight 1.0 ignores it.
        assert self._two_factor(1.0).weighted_score(90.0, 110.0) == pytest.approx(100.0)

    def test_nesting_beyond_two_factors_raises(self):
        inner = self._two_factor(0.5)  # already has a secondary
        with pytest.raises(ValueError, match="at most one secondary"):
            Goal(metric="b", target=1.0, baseline_ref=2.0, worst=3.0, secondary=inner)

    def test_weight_out_of_range_raises(self):
        with pytest.raises(ValueError, match="weight must be in"):
            self._two_factor(1.5)

    def test_from_metric_builds_median_factor(self):
        goal = Goal.from_metric(
            MetricRegistry.CYCLE_TIME_MEDIAN, {COL_MEDIAN_CYCLE_H_MEAN: 50.0}
        )
        assert goal.metric == COL_MEDIAN_CYCLE_H_MEAN
        assert goal.baseline_ref == pytest.approx(50.0)
