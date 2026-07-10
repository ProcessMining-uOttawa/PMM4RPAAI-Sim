"""Tests for ui/table.py — prepare_ranked_display column selection and renaming."""

from __future__ import annotations

import pandas as pd

from core.constants import (
    COL_MEAN_COST_MEAN,
    COL_MEAN_CYCLE_H_MEAN,
    COL_MEDIAN_CYCLE_H_MEAN,
)
from core.metrics import MetricRegistry
from core.parameters import Parameter
from ui.table import prepare_ranked_display


def _ranked() -> pd.DataFrame:
    """Minimal rank() output: scenario, the cycle-time KPI, its goal score, overall."""
    return pd.DataFrame(
        {
            "scenario_id": ["S01", "S02"],
            COL_MEAN_CYCLE_H_MEAN: [5.0, 6.0],
            f"{COL_MEAN_CYCLE_H_MEAN}_score": [100.0, 50.0],
            "score": [100.0, 50.0],
        }
    )


def _factor_param() -> Parameter:
    return Parameter(
        id="pct_auto", label="Auto %", levels=[25, 50, 75], kind="percentage"
    )


class TestPrepareRankedDisplay:
    def test_columns_and_order(self):
        result = prepare_ranked_display(
            _ranked(), [MetricRegistry.CYCLE_TIME], [], show_factors=False
        )
        assert list(result.columns) == [
            "rank",
            "Scenario",
            "Cycle Time (h/case)",
            "Cycle Time Score",
            "Overall Score",
        ]

    def test_rank_is_one_based(self):
        result = prepare_ranked_display(_ranked(), [MetricRegistry.CYCLE_TIME], [])
        assert result["rank"].tolist() == [1, 2]

    def test_scenario_id_renamed(self):
        result = prepare_ranked_display(_ranked(), [MetricRegistry.CYCLE_TIME], [])
        assert "Scenario" in result.columns
        assert "scenario_id" not in result.columns

    def test_factors_hidden_by_default(self):
        ranked = _ranked()
        ranked["pct_auto"] = [25, 50]
        result = prepare_ranked_display(
            ranked, [MetricRegistry.CYCLE_TIME], [_factor_param()]
        )
        assert "Auto %" not in result.columns

    def test_factors_shown_when_requested(self):
        ranked = _ranked()
        ranked["pct_auto"] = [25, 50]
        result = prepare_ranked_display(
            ranked, [MetricRegistry.CYCLE_TIME], [_factor_param()], show_factors=True
        )
        assert "Auto %" in result.columns

    def test_frozen_factor_excluded_even_when_shown(self):
        # The `if not p.frozen` guard: a frozen factor is held constant across
        # scenarios (excluded from the OA) so it carries no per-scenario signal
        # and must not appear as a column even with show_factors=True. Both
        # columns exist in `ranked`, so only the guard can drop the frozen one.
        ranked = _ranked()
        ranked["pct_auto"] = [25, 50]
        ranked["num_cases"] = [100, 100]
        frozen = Parameter(
            id="num_cases",
            label="Cases (frozen)",
            levels=[100],
            kind="categorical",
            frozen=True,
        )
        result = prepare_ranked_display(
            ranked,
            [MetricRegistry.CYCLE_TIME],
            [_factor_param(), frozen],
            show_factors=True,
        )
        assert "Auto %" in result.columns
        assert "Cases (frozen)" not in result.columns

    def test_factor_columns_between_scenario_and_kpis(self):
        # Contract order: rank · Scenario · [factor cols] · KPI means · … — pin
        # the factor column's position so a reorder that shifts factors after the
        # KPIs is caught.
        ranked = _ranked()
        ranked["pct_auto"] = [25, 50]
        result = prepare_ranked_display(
            ranked, [MetricRegistry.CYCLE_TIME], [_factor_param()], show_factors=True
        )
        cols = list(result.columns)
        assert (
            cols.index("Scenario")
            < cols.index("Auto %")
            < cols.index("Cycle Time (h/case)")
        )

    def test_metric_absent_from_ranked_is_skipped(self):
        # Only cycle-time columns exist; Cost's KPI column does not, so it must be
        # silently filtered out (the `col in ranked.columns` guard).
        result = prepare_ranked_display(_ranked(), [MetricRegistry.CYCLE_TIME], [])
        assert "Cost ($/case)" not in result.columns

    def test_median_shown_beside_cycle_when_time_goal_active(self):
        # The two-factor time goal's median second factor appears right after the
        # mean-cycle KPI so its input to the combined Cycle Time Score is visible.
        ranked = _ranked()
        ranked[COL_MEDIAN_CYCLE_H_MEAN] = [4.0, 5.0]
        result = prepare_ranked_display(ranked, [MetricRegistry.CYCLE_TIME], [])
        cols = list(result.columns)
        assert "Median Cycle Time (h/case)" in cols
        assert (
            cols.index("Median Cycle Time (h/case)")
            == cols.index("Cycle Time (h/case)") + 1
        )

    def test_median_hidden_when_time_goal_not_active(self):
        # Median is the time goal's factor, not a standalone KPI — suppressed
        # when Cycle Time is not among the chosen goals, even if the column exists.
        ranked = _ranked()
        ranked[COL_MEDIAN_CYCLE_H_MEAN] = [4.0, 5.0]
        ranked[COL_MEAN_COST_MEAN] = [3.0, 4.0]
        result = prepare_ranked_display(ranked, [MetricRegistry.COST], [])
        assert "Median Cycle Time (h/case)" not in result.columns

    def test_dropped_goal_keeps_kpi_but_skips_score_column(self):
        # The dropped-goal shape from ui/interactive/goal_config.py: a goal whose
        # thresholds failed validation is excluded from rank(), so its metric is
        # in goal_metrics and its KPI column exists but its _score column does
        # not — the display must keep the KPI and skip only the score.
        ranked = _ranked()
        ranked[COL_MEAN_COST_MEAN] = [3.0, 4.0]  # Cost KPI present, no cost score
        result = prepare_ranked_display(
            ranked, [MetricRegistry.CYCLE_TIME, MetricRegistry.COST], []
        )
        assert "Cost ($/case)" in result.columns
        assert "Cost Score" not in result.columns
        assert "Cycle Time Score" in result.columns
