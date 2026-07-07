"""Tests for core/metrics.py — MetricRegistry classmethods and Metric properties."""

from __future__ import annotations

import pytest

from core.metrics import MetricRegistry
from core.constants import (
    COL_MEAN_CYCLE_H_MEAN,
    COL_MEAN_COST_MEAN,
    COL_REWORK_RATE_MEAN,
)


class TestMetricRegistryRankable:
    def test_rankable_excludes_rework_count(self):
        assert not MetricRegistry.REWORK_COUNT.rankable

    def test_rankable_excludes_bot_failure_count(self):
        assert not MetricRegistry.BOT_FAILURE_COUNT.rankable

    def test_all_includes_bot_failure_count(self):
        assert MetricRegistry.BOT_FAILURE_COUNT in MetricRegistry.all()

    def test_rankable_includes_cycle_time(self):
        rankable_columns = {
            m.per_case.mean.column for m in MetricRegistry.rankable() if m.per_case
        }
        assert COL_MEAN_CYCLE_H_MEAN in rankable_columns

    def test_rankable_includes_cost(self):
        rankable_columns = {
            m.per_case.mean.column for m in MetricRegistry.rankable() if m.per_case
        }
        assert COL_MEAN_COST_MEAN in rankable_columns

    def test_rankable_includes_rework_rate(self):
        aggregate_columns = {
            m.aggregate.column for m in MetricRegistry.rankable() if m.aggregate
        }
        assert COL_REWORK_RATE_MEAN in aggregate_columns


class TestMetricPerCaseProperties:
    def test_per_case_column_raises_for_rework_count(self):
        # REWORK_COUNT has per_case=None; the accessors raise (instead of
        # returning None) so rankable()-gated consumers need no assert-narrowing.
        with pytest.raises(ValueError, match="per_case"):
            _ = MetricRegistry.REWORK_COUNT.per_case_column

    def test_per_case_display_name_raises_for_rework_count(self):
        with pytest.raises(ValueError, match="per_case"):
            _ = MetricRegistry.REWORK_COUNT.per_case_display_name

    def test_per_case_column_returns_string_for_cycle_time(self):
        assert MetricRegistry.CYCLE_TIME.per_case_column == COL_MEAN_CYCLE_H_MEAN

    def test_per_case_display_name_returns_string_for_cycle_time(self):
        assert MetricRegistry.CYCLE_TIME.per_case_display_name == "Cycle Time (h/case)"

    def test_per_case_compact_label_returns_short_label_when_set(self):
        # CYCLE_TIME has short_label="Cycle Time"
        assert MetricRegistry.CYCLE_TIME.per_case_compact_label == "Cycle Time"

    def test_per_case_compact_label_falls_back_to_display_name_when_short_label_none(
        self,
    ):
        # Construct a Metric whose PerCaseMetric has no short_label
        from core.metrics import Metric, PerCaseMetric, MetricSpec

        m = Metric(
            per_case=PerCaseMetric(
                results_column="col",
                mean=MetricSpec(
                    column="col_mean",
                    display_name="Full Display Name",
                    decimal_places=2,
                ),
            ),
            aggregate=None,
            rankable=False,
        )
        assert m.per_case_compact_label == "Full Display Name"

    def test_per_case_compact_label_raises_when_per_case_none(self):
        with pytest.raises(ValueError, match="per_case"):
            _ = MetricRegistry.REWORK_COUNT.per_case_compact_label

    def test_per_case_decimal_places_returns_int_for_cycle_time(self):
        assert MetricRegistry.CYCLE_TIME.per_case_decimal_places == 2

    def test_per_case_decimal_places_rework_rate_is_1(self):
        # The only metric with dp != 2 — drives the step-0.1 / %.1f widget kwargs.
        assert MetricRegistry.REWORK_RATE.per_case_decimal_places == 1

    def test_per_case_decimal_places_raises_when_per_case_none(self):
        with pytest.raises(ValueError, match="per_case"):
            _ = MetricRegistry.REWORK_COUNT.per_case_decimal_places


class TestMetricUpperBound:
    def test_rework_rate_is_capped_at_100(self):
        # A percentage of cases — the domain ceiling that clamps goal-threshold
        # widget seeds (a worst default of baseline × 1.1 can exceed 100).
        assert MetricRegistry.REWORK_RATE.upper_bound == 100.0

    def test_cycle_time_is_unbounded(self):
        assert MetricRegistry.CYCLE_TIME.upper_bound is None

    def test_cost_is_unbounded(self):
        assert MetricRegistry.COST.upper_bound is None
