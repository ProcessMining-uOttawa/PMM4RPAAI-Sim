"""Tests for core/metrics.py — MetricRegistry classmethods and Metric properties."""

from __future__ import annotations

from core.metrics import MetricRegistry
from core.constants import (
    COL_MEAN_CYCLE_H_MEAN,
    COL_MEAN_COST_MEAN,
    COL_REWORK_RATE_MEAN,
    COL_TOTAL_REWORK_COUNT_MEAN,
)


class TestMetricRegistryRankable:
    def test_rankable_excludes_rework_count(self):
        rankable_columns = {m.aggregate.column for m in MetricRegistry.rankable() if m.aggregate}
        assert COL_TOTAL_REWORK_COUNT_MEAN not in rankable_columns

    def test_rankable_includes_cycle_time(self):
        rankable_columns = {m.per_case.mean.column for m in MetricRegistry.rankable() if m.per_case}
        assert COL_MEAN_CYCLE_H_MEAN in rankable_columns

    def test_rankable_includes_cost(self):
        rankable_columns = {m.per_case.mean.column for m in MetricRegistry.rankable() if m.per_case}
        assert COL_MEAN_COST_MEAN in rankable_columns

    def test_rankable_includes_rework_rate(self):
        aggregate_columns = {m.aggregate.column for m in MetricRegistry.rankable() if m.aggregate}
        assert COL_REWORK_RATE_MEAN in aggregate_columns


class TestMetricRegistryByColumn:
    def test_finds_per_case_mean_column(self):
        spec = MetricRegistry.by_column(COL_MEAN_CYCLE_H_MEAN)
        assert spec is not None
        assert spec.column == COL_MEAN_CYCLE_H_MEAN

    def test_finds_aggregate_column(self):
        spec = MetricRegistry.by_column(COL_TOTAL_REWORK_COUNT_MEAN)
        assert spec is not None
        assert spec.column == COL_TOTAL_REWORK_COUNT_MEAN

    def test_returns_none_for_unknown_column(self):
        assert MetricRegistry.by_column("nonexistent_column") is None

    def test_finds_cost_per_case_mean(self):
        spec = MetricRegistry.by_column(COL_MEAN_COST_MEAN)
        assert spec is not None
        assert spec.column == COL_MEAN_COST_MEAN


class TestMetricPerCaseProperties:
    def test_per_case_column_returns_none_for_rework_count(self):
        # REWORK_COUNT has per_case=None; property must return None, not raise
        assert MetricRegistry.REWORK_COUNT.per_case_column is None

    def test_per_case_display_name_returns_none_for_rework_count(self):
        assert MetricRegistry.REWORK_COUNT.per_case_display_name is None

    def test_per_case_column_returns_string_for_cycle_time(self):
        assert MetricRegistry.CYCLE_TIME.per_case_column == COL_MEAN_CYCLE_H_MEAN

    def test_per_case_display_name_returns_string_for_cycle_time(self):
        assert MetricRegistry.CYCLE_TIME.per_case_display_name == "Cycle Time (h/case)"
