"""Tests for core/goals.py — Goal, MetricGoal, and baseline_per_case."""

from __future__ import annotations


import pytest

from core.goals import Goal, MetricGoal, baseline_per_case
from core.metrics import MetricDirection, MetricRegistry
from core.constants import (
    COL_MEAN_CYCLE_H_MEAN,
    COL_MEDIAN_CYCLE_H_MEAN,
    COL_MIN_CYCLE_H_MEAN,
    COL_MAX_CYCLE_H_MEAN,
    COL_MEAN_COST_MEAN,
    COL_REWORK_RATE_MEAN,
    COL_MEAN_REWORK_COUNT_MEAN,
    COL_TOTAL_CYCLE_S_MEAN,
    COL_TOTAL_COST_MEAN,
)

# ── Goal.from_indicator ──────────────────────────────────────────────────────


class TestFromIndicator:
    def test_reads_column_and_direction_from_indicator(self):
        indicator = MetricRegistry.CYCLE_TIME.default_indicator
        goal = Goal.from_indicator(indicator, {COL_MEAN_CYCLE_H_MEAN: 100.0})
        assert goal.indicator_column == COL_MEAN_CYCLE_H_MEAN
        assert goal.target == pytest.approx(90.0)
        assert goal.baseline_ref == pytest.approx(100.0)
        assert goal.worst == pytest.approx(110.0)

    def test_reads_an_extra_indicator(self):
        # The median indicator (an extra) reads its own column from the baseline.
        median = MetricRegistry.CYCLE_TIME.extra_indicators[0]
        assert median.mean.column == COL_MEDIAN_CYCLE_H_MEAN
        goal = Goal.from_indicator(median, {COL_MEDIAN_CYCLE_H_MEAN: 50.0})
        assert goal.indicator_column == COL_MEDIAN_CYCLE_H_MEAN
        assert goal.baseline_ref == pytest.approx(50.0)


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

    def test_indicator_column_preserved(self):
        goal = Goal.from_baseline(
            "mean_cycle_h_mean", 10.0, MetricDirection.SMALLER_IS_BETTER
        )
        assert goal.indicator_column == "mean_cycle_h_mean"

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
            Goal(indicator_column="col", target=90.0, baseline_ref=120.0, worst=110.0)

    def test_baseline_below_both_raises(self):
        with pytest.raises(ValueError, match="must lie between"):
            Goal(indicator_column="col", target=90.0, baseline_ref=80.0, worst=110.0)

    def test_error_names_the_indicator_column(self):
        with pytest.raises(ValueError, match="mean_cost_mean"):
            Goal(
                indicator_column="mean_cost_mean",
                target=5.0,
                baseline_ref=20.0,
                worst=10.0,
            )

    def test_baseline_equal_target_is_allowed(self):
        goal = Goal(
            indicator_column="col", target=100.0, baseline_ref=100.0, worst=110.0
        )
        assert goal.baseline_ref == pytest.approx(100.0)

    def test_baseline_equal_worst_is_allowed(self):
        goal = Goal(
            indicator_column="col", target=90.0, baseline_ref=110.0, worst=110.0
        )
        assert goal.baseline_ref == pytest.approx(110.0)

    def test_degenerate_all_equal_is_allowed(self):
        # from_baseline(0.0) produces this shape; score() handles the zero spans.
        goal = Goal(indicator_column="col", target=0.0, baseline_ref=0.0, worst=0.0)
        assert goal.score(0.0) == pytest.approx(100.0)

    def test_lib_ordering_is_allowed(self):
        # Larger-is-better: target above worst, baseline between.
        goal = Goal(
            indicator_column="col", target=110.0, baseline_ref=100.0, worst=90.0
        )
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


# ── MetricGoal (weighted indicators) ──────────────────────────────────────────


class TestMetricGoal:
    """MetricGoal weights its indicator Goals and scores them together."""

    @staticmethod
    def _goal(column: str, baseline: float) -> Goal:
        return Goal.from_baseline(column, baseline, MetricDirection.SMALLER_IS_BETTER)

    def test_single_indicator_score_is_just_the_goal_score(self):
        mg = MetricGoal(
            indicator_goals=(self._goal(COL_MEAN_CYCLE_H_MEAN, 100.0),), weights=(1,)
        )
        assert mg.score({COL_MEAN_CYCLE_H_MEAN: 100.0}) == pytest.approx(50.0)

    def test_weighted_mean_discriminates_weight_and_arg_swap(self):
        # primary (mean) at target → 100; secondary (median) at worst → 0.
        # weights 3:1 → 0.75·100 + 0.25·0 = 75. A 1:3 weight-swap → 25.
        primary = self._goal(COL_MEAN_CYCLE_H_MEAN, 100.0)
        secondary = self._goal(COL_MEDIAN_CYCLE_H_MEAN, 200.0)
        values = {COL_MEAN_CYCLE_H_MEAN: 90.0, COL_MEDIAN_CYCLE_H_MEAN: 220.0}
        assert MetricGoal((primary, secondary), (3, 1)).score(values) == pytest.approx(
            75.0
        )
        assert MetricGoal((primary, secondary), (1, 3)).score(values) == pytest.approx(
            25.0
        )

    def test_equal_weights_is_plain_mean(self):
        primary = self._goal(COL_MEAN_CYCLE_H_MEAN, 100.0)
        secondary = self._goal(COL_MEDIAN_CYCLE_H_MEAN, 200.0)
        values = {COL_MEAN_CYCLE_H_MEAN: 90.0, COL_MEDIAN_CYCLE_H_MEAN: 220.0}
        assert MetricGoal((primary, secondary), (1, 1)).score(values) == pytest.approx(
            50.0
        )  # (100 + 0) / 2

    def test_score_column_keyed_by_default_indicator(self):
        primary = self._goal(COL_MEAN_CYCLE_H_MEAN, 100.0)
        secondary = self._goal(COL_MEDIAN_CYCLE_H_MEAN, 200.0)
        mg = MetricGoal((primary, secondary), (2, 1))
        assert mg.score_column == f"{COL_MEAN_CYCLE_H_MEAN}_score"

    def test_empty_indicators_raises(self):
        with pytest.raises(ValueError, match="at least one"):
            MetricGoal(indicator_goals=(), weights=())

    def test_weight_length_mismatch_raises(self):
        g = self._goal(COL_MEAN_CYCLE_H_MEAN, 100.0)
        with pytest.raises(ValueError, match="must match"):
            MetricGoal(indicator_goals=(g,), weights=(1, 1))

    def test_zero_weight_raises(self):
        # 0 would be a second way to express "don't score this" (deselecting
        # the extra indicator already does that) and all-zeros divides by zero.
        g = self._goal(COL_MEAN_CYCLE_H_MEAN, 100.0)
        with pytest.raises(ValueError, match="> 0"):
            MetricGoal(indicator_goals=(g,), weights=(0.0,))

    def test_negative_weight_raises(self):
        g = self._goal(COL_MEAN_CYCLE_H_MEAN, 100.0)
        with pytest.raises(ValueError, match="> 0"):
            MetricGoal(indicator_goals=(g,), weights=(-1.0,))

    def test_fractional_weights_equal_integer_ratio(self):
        # Sum-normalisation makes 0.75:0.25 identical to 3:1 — floats add
        # input convenience, not expressive power.
        primary = self._goal(COL_MEAN_CYCLE_H_MEAN, 100.0)
        secondary = self._goal(COL_MEDIAN_CYCLE_H_MEAN, 200.0)
        values = {COL_MEAN_CYCLE_H_MEAN: 100.0, COL_MEDIAN_CYCLE_H_MEAN: 200.0}
        fractional = MetricGoal(
            indicator_goals=(primary, secondary), weights=(0.75, 0.25)
        )
        integer = MetricGoal(indicator_goals=(primary, secondary), weights=(3, 1))
        assert fractional.score(values) == pytest.approx(integer.score(values))


# ── baseline_per_case ─────────────────────────────────────────────────────────


class TestBaselinePerCase:
    def _record(self, **overrides) -> dict:
        """A flat baseline_agg record: every per-case indicator mean, beside the totals."""
        record = {
            COL_MEAN_CYCLE_H_MEAN: 1.0,
            COL_MEDIAN_CYCLE_H_MEAN: 0.9,
            COL_MIN_CYCLE_H_MEAN: 0.5,
            COL_MAX_CYCLE_H_MEAN: 3.0,
            COL_MEAN_COST_MEAN: 5.0,
            COL_REWORK_RATE_MEAN: 5.0,
            COL_MEAN_REWORK_COUNT_MEAN: 0.05,
            COL_TOTAL_CYCLE_S_MEAN: 360000.0,
            COL_TOTAL_COST_MEAN: 500.0,
        }
        record.update(overrides)
        return record

    def test_every_indicator_key_picked_through(self):
        result = baseline_per_case(self._record())
        for metric in MetricRegistry.all():
            for indicator in metric.indicators:
                assert indicator.mean.column in result

    def test_values_picked_through(self):
        result = baseline_per_case(
            self._record(
                **{COL_MEAN_CYCLE_H_MEAN: 1.5, COL_MEAN_REWORK_COUNT_MEAN: 0.2}
            )
        )
        assert result[COL_MEAN_CYCLE_H_MEAN] == pytest.approx(1.5)
        assert result[COL_MEAN_REWORK_COUNT_MEAN] == pytest.approx(0.2)

    def test_totals_filtered_out(self):
        # A filter, not a pass-through: only per-case indicator keys survive.
        result = baseline_per_case(self._record())
        assert COL_TOTAL_CYCLE_S_MEAN not in result
        assert COL_TOTAL_COST_MEAN not in result

    def test_missing_indicator_key_raises(self):
        # A record without a per-case indicator key is malformed — loud, not defaulted.
        record = self._record()
        del record[COL_MEAN_COST_MEAN]
        with pytest.raises(KeyError):
            baseline_per_case(record)
