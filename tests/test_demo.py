"""Tests for demo.run_experiment — synthetic simulation (no Simod/Prosimos)."""
from __future__ import annotations

from core import demo
from core.constants import (
    COL_CYCLE_H, COL_COST, COL_TOTAL_CYCLE_S, COL_TOTAL_COST,
    COL_REWORK_COUNT, COL_REWORK_RATE,
)
from core.experiment import build_scenarios
from core.orchestrator import ExperimentResult
from core.transformations import XORSplitAutomation


def _scenarios():
    transformation = XORSplitAutomation()
    params = transformation.parameters("Test Task", current_duration_s=3600.0)
    _, scenarios = build_scenarios(params, transformation.id, "Test Task")
    return scenarios


class TestDemoRunExperiment:

    def test_returns_experiment_result(self):
        result = demo.run_experiment(_scenarios(), n_reps=2)
        assert isinstance(result, ExperimentResult)

    def test_dataframe_row_count(self):
        scenarios = _scenarios()
        n_reps = 3
        result = demo.run_experiment(scenarios, n_reps=n_reps)
        assert len(result.results) == len(scenarios) * n_reps

    def test_dataframe_required_columns(self):
        result = demo.run_experiment(_scenarios(), n_reps=1)
        required = {
            "scenario_id", "replication",
            COL_CYCLE_H, COL_COST,
            COL_TOTAL_CYCLE_S, COL_TOTAL_COST,
            COL_REWORK_COUNT, COL_REWORK_RATE,
        }
        assert required <= set(result.results.columns)

    def test_bpmn_path_and_json_paths_empty(self):
        result = demo.run_experiment(_scenarios(), n_reps=1)
        assert result.experiment_bpmn_path is None
        assert result.scenario_json_paths == {}

    def test_baseline_agg_is_none(self):
        result = demo.run_experiment(_scenarios(), n_reps=1)
        assert result.baseline_agg is None

    def test_on_progress_called_once_per_replication(self):
        scenarios = _scenarios()
        n_reps = 2
        calls: list[tuple] = []

        demo.run_experiment(
            scenarios, n_reps=n_reps,
            on_progress=lambda done, total, sid, rep: calls.append((done, total)),
        )

        expected = len(scenarios) * n_reps
        assert len(calls) == expected
        assert calls[-1] == (expected, expected)

    def test_metric_values_finite_and_nonnegative(self):
        result = demo.run_experiment(_scenarios(), n_reps=1)
        df = result.results
        for col in (COL_CYCLE_H, COL_COST, COL_TOTAL_CYCLE_S, COL_TOTAL_COST):
            assert (df[col] > 0).all(), f"{col} should be positive"
        assert (df[COL_REWORK_COUNT] >= 0).all()
        assert (df[COL_REWORK_RATE] >= 0).all()
        assert (df[COL_REWORK_RATE] <= 100.0).all()

    def test_nonzero_bot_cost_increases_cost(self):
        scenarios = _scenarios()
        free   = demo.run_experiment(scenarios, n_reps=1, bot_cost_per_hour=0.0)
        costly = demo.run_experiment(scenarios, n_reps=1, bot_cost_per_hour=500.0)
        assert costly.results[COL_COST].mean() > free.results[COL_COST].mean()
