"""Integration tests for orchestrator.run_experiment — demo mode only (no Simod/Prosimos)."""
from __future__ import annotations
from pathlib import Path

from core.constants import COL_CYCLE_H, COL_COST
from core.experiment import build_scenarios
from core.orchestrator import ExperimentResult, run_experiment
from core.transformations import XORSplitAutomation


def _scenarios():
    transformation = XORSplitAutomation()
    params = transformation.parameters("Test Task", current_duration_s=3600.0)
    _, scenarios = build_scenarios(params, transformation.id, "Test Task")
    return transformation, scenarios


class TestDemoMode:

    def test_returns_experiment_result(self):
        transformation, scenarios = _scenarios()
        result = run_experiment(
            transformation=transformation,
            bpmn_path=None, json_path=None, target="Test Task",
            scenarios=scenarios, n_reps=2,
            exp_dir=Path("irrelevant"), demo_mode=True,
        )
        assert isinstance(result, ExperimentResult)

    def test_dataframe_row_count(self):
        transformation, scenarios = _scenarios()
        n_reps = 3
        result = run_experiment(
            transformation=transformation,
            bpmn_path=None, json_path=None, target="Test Task",
            scenarios=scenarios, n_reps=n_reps,
            exp_dir=Path("irrelevant"), demo_mode=True,
        )
        assert len(result.results) == len(scenarios) * n_reps

    def test_dataframe_required_columns(self):
        transformation, scenarios = _scenarios()
        result = run_experiment(
            transformation=transformation,
            bpmn_path=None, json_path=None, target="Test Task",
            scenarios=scenarios, n_reps=1,
            exp_dir=Path("irrelevant"), demo_mode=True,
        )
        assert {"scenario_id", "replication", COL_CYCLE_H, COL_COST} <= set(result.results.columns)

    def test_bpmn_path_and_json_paths_empty_in_demo(self):
        transformation, scenarios = _scenarios()
        result = run_experiment(
            transformation=transformation,
            bpmn_path=None, json_path=None, target="Test Task",
            scenarios=scenarios, n_reps=1,
            exp_dir=Path("irrelevant"), demo_mode=True,
        )
        assert result.experiment_bpmn_path is None
        assert result.scenario_json_paths == {}

    def test_on_progress_called_once_per_replication(self):
        transformation, scenarios = _scenarios()
        n_reps = 2
        calls: list[tuple] = []

        run_experiment(
            transformation=transformation,
            bpmn_path=None, json_path=None, target="Test Task",
            scenarios=scenarios, n_reps=n_reps,
            exp_dir=Path("irrelevant"), demo_mode=True,
            on_progress=lambda done, total, sid, rep: calls.append((done, total)),
        )

        expected = len(scenarios) * n_reps
        assert len(calls) == expected
        assert calls[-1] == (expected, expected)

    def test_metric_values_are_positive(self):
        transformation, scenarios = _scenarios()
        result = run_experiment(
            transformation=transformation,
            bpmn_path=None, json_path=None, target="Test Task",
            scenarios=scenarios, n_reps=1,
            exp_dir=Path("irrelevant"), demo_mode=True,
        )
        assert (result.results[COL_CYCLE_H] > 0).all()
        assert (result.results[COL_COST] > 0).all()
