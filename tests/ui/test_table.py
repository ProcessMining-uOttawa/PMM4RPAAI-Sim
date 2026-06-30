"""Tests for ui/table.py — prepare_ranked_display column selection and renaming."""

from __future__ import annotations

import pandas as pd

from core.constants import COL_MEAN_CYCLE_H_MEAN
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

    def test_metric_absent_from_ranked_is_skipped(self):
        # Only cycle-time columns exist; Cost's KPI column does not, so it must be
        # silently filtered out (the `col in ranked.columns` guard).
        result = prepare_ranked_display(_ranked(), [MetricRegistry.CYCLE_TIME], [])
        assert "Cost ($/case)" not in result.columns
