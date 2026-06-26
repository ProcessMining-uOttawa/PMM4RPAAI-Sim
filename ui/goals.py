"""Ordered registry of metrics available as ranking goals in the sidebar."""

from __future__ import annotations

from core.metrics import Metric, MetricRegistry

# Metrics available as goals, in the order they appear in the sidebar selector.
GOAL_METRICS: list[Metric] = [
    MetricRegistry.CYCLE_TIME,
    MetricRegistry.COST,
    MetricRegistry.REWORK_RATE,
]
