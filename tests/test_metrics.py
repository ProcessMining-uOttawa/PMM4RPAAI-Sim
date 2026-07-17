"""Tests for core/metrics.py — MetricRegistry, Metric/IndicatorSpec, reader coherence."""

from __future__ import annotations

import dataclasses

import pytest

from core.metrics import IndicatorSpec, Metric, MetricSpec, MetricRegistry
from core.simulation.prosimos.reader import ReplicationMetrics
from core.constants import (
    COL_MEAN_CYCLE_H_MEAN,
    COL_MEDIAN_CYCLE_H_MEAN,
    COL_MIN_CYCLE_H_MEAN,
    COL_MAX_CYCLE_H_MEAN,
    COL_MEAN_COST_MEAN,
    COL_REWORK_RATE_MEAN,
    COL_MEAN_REWORK_COUNT_MEAN,
)


class TestMetricRegistryRankable:
    def test_rankable_excludes_rework_count(self):
        assert not MetricRegistry.REWORK_COUNT.rankable

    def test_rankable_excludes_bot_failure_count(self):
        assert not MetricRegistry.BOT_FAILURE_COUNT.rankable

    def test_all_includes_bot_failure_count(self):
        assert MetricRegistry.BOT_FAILURE_COUNT in MetricRegistry.all()

    def test_rankable_includes_cycle_time(self):
        columns = {m.per_case_column for m in MetricRegistry.rankable()}
        assert COL_MEAN_CYCLE_H_MEAN in columns

    def test_rankable_includes_cost(self):
        columns = {m.per_case_column for m in MetricRegistry.rankable()}
        assert COL_MEAN_COST_MEAN in columns

    def test_rankable_includes_rework_rate(self):
        aggregate_columns = {
            m.aggregate.column for m in MetricRegistry.rankable() if m.aggregate
        }
        assert COL_REWORK_RATE_MEAN in aggregate_columns


class TestMetricPerCaseProperties:
    def test_per_case_column_raises_for_rework_count(self):
        # REWORK_COUNT has indicators=(); the accessors raise (instead of
        # returning None) so rankable()-gated consumers need no assert-narrowing.
        with pytest.raises(ValueError, match="indicator"):
            _ = MetricRegistry.REWORK_COUNT.per_case_column

    def test_per_case_display_name_raises_for_rework_count(self):
        with pytest.raises(ValueError, match="indicator"):
            _ = MetricRegistry.REWORK_COUNT.per_case_display_name

    def test_per_case_column_returns_string_for_cycle_time(self):
        assert MetricRegistry.CYCLE_TIME.per_case_column == COL_MEAN_CYCLE_H_MEAN

    def test_per_case_display_name_returns_string_for_cycle_time(self):
        assert MetricRegistry.CYCLE_TIME.per_case_display_name == "Cycle Time (h/case)"

    def test_per_case_compact_label_returns_short_label_when_set(self):
        # CYCLE_TIME's default indicator has short_label="Cycle Time"
        assert MetricRegistry.CYCLE_TIME.per_case_compact_label == "Cycle Time"

    def test_per_case_compact_label_falls_back_to_display_name_when_short_label_none(
        self,
    ):
        # An indicator whose MetricSpec has no short_label
        indicator = IndicatorSpec(
            results_column="col",
            mean=MetricSpec(
                column="col_mean",
                display_name="Full Display Name",
                decimal_places=2,
            ),
        )
        m = Metric(indicators=(indicator,), aggregate=None, rankable=False)
        assert m.per_case_compact_label == "Full Display Name"

    def test_per_case_compact_label_raises_when_no_indicators(self):
        with pytest.raises(ValueError, match="indicator"):
            _ = MetricRegistry.REWORK_COUNT.per_case_compact_label

    def test_rework_rate_default_indicator_dp_is_1(self):
        # The only rankable default with dp != 2 — drives the step-0.1 threshold
        # widget kwargs (which read indicator.decimal_places directly).
        assert MetricRegistry.REWORK_RATE.default_indicator.decimal_places == 1


class TestIndicators:
    """Each metric carries an ordered indicator list; indicators[0] is the locked default."""

    def test_cycle_time_indicators_in_registry_order(self):
        columns = [ind.mean.column for ind in MetricRegistry.CYCLE_TIME.indicators]
        assert columns == [
            COL_MEAN_CYCLE_H_MEAN,
            COL_MEDIAN_CYCLE_H_MEAN,
            COL_MIN_CYCLE_H_MEAN,
            COL_MAX_CYCLE_H_MEAN,
        ]

    def test_default_indicator_is_first(self):
        default = MetricRegistry.CYCLE_TIME.default_indicator
        assert default.mean.column == COL_MEAN_CYCLE_H_MEAN

    def test_extra_indicators_exclude_default(self):
        cycle = MetricRegistry.CYCLE_TIME
        assert cycle.default_indicator not in cycle.extra_indicators
        assert len(cycle.extra_indicators) == 3

    def test_cost_is_single_indicator(self):
        assert len(MetricRegistry.COST.indicators) == 1
        assert MetricRegistry.COST.extra_indicators == ()

    def test_rework_rate_has_count_extra(self):
        columns = [ind.mean.column for ind in MetricRegistry.REWORK_RATE.indicators]
        assert columns == [COL_REWORK_RATE_MEAN, COL_MEAN_REWORK_COUNT_MEAN]

    def test_display_only_metrics_have_no_indicators(self):
        assert MetricRegistry.REWORK_COUNT.indicators == ()
        assert MetricRegistry.BOT_FAILURE_COUNT.indicators == ()

    def test_default_indicator_raises_when_empty(self):
        with pytest.raises(ValueError, match="indicator"):
            _ = MetricRegistry.REWORK_COUNT.default_indicator


class TestIndicatorUpperBound:
    def test_rework_rate_indicator_capped_at_100(self):
        # A percentage of cases — the domain ceiling that clamps goal-threshold
        # widget seeds (a worst default of baseline × 1.1 can exceed 100). Lives
        # on the indicator, not the metric: rework *rate* caps, rework *count* does not.
        assert MetricRegistry.REWORK_RATE.default_indicator.upper_bound == 100.0

    def test_rework_count_indicator_unbounded(self):
        count = MetricRegistry.REWORK_RATE.extra_indicators[0]
        assert count.mean.column == COL_MEAN_REWORK_COUNT_MEAN
        assert count.upper_bound is None

    def test_cycle_time_indicators_unbounded(self):
        assert all(
            ind.upper_bound is None for ind in MetricRegistry.CYCLE_TIME.indicators
        )

    def test_cost_indicator_unbounded(self):
        assert MetricRegistry.COST.default_indicator.upper_bound is None


class TestRegistryReaderCoherence:
    """The registry's indicators must line up with ReplicationMetrics — no data-driven
    reader couples them, so this loud check stands in for that coupling."""

    def test_every_results_column_is_a_replication_field(self):
        fields = {f.name for f in dataclasses.fields(ReplicationMetrics)}
        for metric in MetricRegistry.all():
            for indicator in metric.indicators:
                assert indicator.results_column in fields, indicator.results_column

    def test_mean_column_is_results_column_plus_mean(self):
        for metric in MetricRegistry.all():
            for indicator in metric.indicators:
                assert indicator.mean.column == f"{indicator.results_column}_mean"
