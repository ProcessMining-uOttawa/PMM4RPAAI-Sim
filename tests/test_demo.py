"""Tests for demo.run_experiment — synthetic simulation (no Simod/Prosimos)."""

from __future__ import annotations
import json
import threading
import xml.etree.ElementTree as ET

import pytest

from core import demo
from core.demo import _fake_simulate
from core.parameters import Scenario
from core.bpmn.query import find_task_by_name, list_activities
from core.simulation.prosimos.query import task_mean_duration_s
from core.constants import (
    COL_MEAN_CYCLE_H,
    COL_MEDIAN_CYCLE_H,
    COL_MEAN_COST,
    COL_TOTAL_CYCLE_S,
    COL_TOTAL_COST,
    COL_TOTAL_REWORK_COUNT,
    COL_REWORK_RATE,
    COL_TOTAL_BOT_FAILURE_COUNT,
    COL_TOTAL_CYCLE_S_MEAN,
    COL_MEDIAN_CYCLE_H_MEAN,
    COL_TOTAL_COST_MEAN,
    COL_REWORK_RATE_MEAN,
    F_NUM_CASES,
)
from core.taguchi import build_scenarios
from core.orchestrator import ExperimentCancelledError, ExperimentResult
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
            "scenario_id",
            "replication",
            COL_MEAN_CYCLE_H,
            COL_MEDIAN_CYCLE_H,
            COL_MEAN_COST,
            COL_TOTAL_CYCLE_S,
            COL_TOTAL_COST,
            COL_TOTAL_REWORK_COUNT,
            COL_REWORK_RATE,
            COL_TOTAL_BOT_FAILURE_COUNT,
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
            scenarios,
            n_reps=n_reps,
            on_progress=lambda done, total, sid, rep: calls.append((done, total)),
        )

        expected = len(scenarios) * n_reps
        assert len(calls) == expected
        assert calls[-1] == (expected, expected)

    def test_metric_values_finite_and_nonnegative(self):
        result = demo.run_experiment(_scenarios(), n_reps=1)
        df = result.results
        for col in (COL_MEAN_CYCLE_H, COL_MEAN_COST, COL_TOTAL_CYCLE_S, COL_TOTAL_COST):
            assert (df[col] > 0).all(), f"{col} should be positive"
        assert (df[COL_TOTAL_REWORK_COUNT] >= 0).all()
        assert (df[COL_REWORK_RATE] >= 0).all()
        assert (df[COL_REWORK_RATE] <= 100.0).all()
        assert (df[COL_TOTAL_BOT_FAILURE_COUNT] >= 0).all()

    def test_median_cycle_below_mean(self):
        # The demo assumes right-skewed cycle times, so the synthetic median
        # (a scoring-only second factor) sits below the mean in every row.
        df = demo.run_experiment(_scenarios(), n_reps=1).results
        assert (df[COL_MEDIAN_CYCLE_H] < df[COL_MEAN_CYCLE_H]).all()

    def test_nonzero_bot_cost_increases_cost(self):
        scenarios = _scenarios()
        free = demo.run_experiment(scenarios, n_reps=1, bot_cost_per_hour=0.0)
        costly = demo.run_experiment(scenarios, n_reps=1, bot_cost_per_hour=500.0)
        assert costly.results[COL_MEAN_COST].mean() > free.results[COL_MEAN_COST].mean()

    def test_failed_replications_empty_in_demo(self):
        result = demo.run_experiment(_scenarios(), n_reps=1)
        assert result.failed_replications == []

    def test_cross_field_total_identities(self):
        # The _SimResult totals are documented derivations of the per-case fields.
        # rel tolerance because totals use unrounded intermediates while the
        # per-case fields are rounded to 2 dp.
        df = demo.run_experiment(_scenarios(), n_reps=2).results
        for _, row in df.iterrows():
            n = row[F_NUM_CASES]
            assert row[COL_TOTAL_COST] == pytest.approx(
                row[COL_MEAN_COST] * n, rel=1e-2
            )
            assert row[COL_TOTAL_CYCLE_S] == pytest.approx(
                row[COL_MEAN_CYCLE_H] * 3600 * n, rel=1e-2
            )
            assert row[COL_TOTAL_REWORK_COUNT] == pytest.approx(
                row[COL_REWORK_RATE] / 100 * n, rel=1e-2
            )


class TestDemoBaselineAgg:
    def test_has_n1_key(self):
        agg = demo.demo_baseline_agg()
        assert 1 in agg

    def test_contains_required_sub_keys(self):
        agg = demo.demo_baseline_agg()
        required = {
            COL_TOTAL_CYCLE_S_MEAN,
            COL_MEDIAN_CYCLE_H_MEAN,
            COL_TOTAL_COST_MEAN,
            COL_REWORK_RATE_MEAN,
        }
        assert required <= set(agg[1].keys())

    def test_values_are_positive(self):
        agg = demo.demo_baseline_agg()
        entry = agg[1]
        assert entry[COL_TOTAL_CYCLE_S_MEAN] > 0
        assert entry[COL_TOTAL_COST_MEAN] > 0
        assert entry[COL_REWORK_RATE_MEAN] >= 0


class TestDemoFixtures:
    """The pre-baked demo model must stay loadable by the real prepopulation path."""

    def test_fixtures_exist(self):
        assert demo.DEMO_BPMN.is_file()
        assert demo.DEMO_JSON.is_file()

    def test_activities_discoverable(self):
        activities = list_activities(demo.DEMO_BPMN)
        assert len(activities) > 0
        assert all(isinstance(a, str) for a in activities)

    def test_every_activity_resolves_a_discovered_mean(self):
        # if a task_id mismatch crept in, the demo factor levels would silently
        # fall back to the flat default — so assert all means resolve.
        data = json.loads(demo.DEMO_JSON.read_text())
        tree = ET.parse(str(demo.DEMO_BPMN))
        for activity in list_activities(demo.DEMO_BPMN):
            task = find_task_by_name(tree, activity)
            assert task is not None
            mean = task_mean_duration_s(data, task.get("id"))
            assert mean is not None and mean > 0


class TestExperimentCancellation:
    def test_cancelled_raises_experiment_cancelled_error(self):
        stop = threading.Event()
        stop.set()
        with pytest.raises(ExperimentCancelledError):
            demo.run_experiment(_scenarios(), n_reps=1, stop_event=stop)


# ── Demo monotonicity ─────────────────────────────────────────────────────────


class TestDemoMonotonicity:
    def test_larger_resource_pool_reduces_cycle_time(self):
        def _mean_cycle(num_bots: int, num_man: int, n_reps: int = 20) -> float:
            s = Scenario(
                "S01",
                {
                    "pct_auto": 50,
                    "pct_ok": 90,
                    "t_auto": 30,
                    "t_manual": 300,
                    "num_bots": num_bots,
                    "num_manual_resources": num_man,
                    "num_cases": 500,
                },
                "t_id",
                "Act",
            )
            return (
                sum(_fake_simulate(s, r).mean_cycle_h for r in range(n_reps)) / n_reps
            )

        assert _mean_cycle(3, 3) < _mean_cycle(1, 1)

    def test_more_automation_reduces_cycle_time(self):
        # Equal pools (num_bots == num_manual_resources) keep effective_resources
        # constant across pct_auto, so cycle time varies only through the faster
        # bot task: mean_task_s/t_manual = 1.0 at pct_auto=0 vs 0.55 at pct_auto=50.
        # The [0.9, 1.1] jitter cannot reorder those (0.605 < 0.9 worst-case).
        def _mean_cycle(pct_auto: int, n_reps: int = 20) -> float:
            s = Scenario(
                "S01",
                {
                    "pct_auto": pct_auto,
                    "pct_ok": 90,
                    "t_auto": 30,
                    "t_manual": 300,
                    "num_bots": 2,
                    "num_manual_resources": 2,
                    "num_cases": 500,
                },
                "t_id",
                "Act",
            )
            return (
                sum(_fake_simulate(s, r).mean_cycle_h for r in range(n_reps)) / n_reps
            )

        assert _mean_cycle(50) < _mean_cycle(0)


class TestDemoBotFailures:
    @staticmethod
    def _simulate(pct_auto: int, pct_ok: int):
        s = Scenario(
            "S01",
            {
                "pct_auto": pct_auto,
                "pct_ok": pct_ok,
                "t_auto": 30,
                "t_manual": 300,
                "num_bots": 2,
                "num_manual_resources": 2,
                "num_cases": 500,
            },
            "t_id",
            "Act",
        )
        return _fake_simulate(s, 0)

    def test_perfect_bot_has_zero_failures(self):
        assert self._simulate(pct_auto=50, pct_ok=100).total_bot_failure_count == 0.0

    def test_zero_automation_has_zero_failures(self):
        assert self._simulate(pct_auto=0, pct_ok=80).total_bot_failure_count == 0.0

    def test_lower_pct_ok_means_more_failures(self):
        assert (
            self._simulate(pct_auto=50, pct_ok=80).total_bot_failure_count
            > self._simulate(pct_auto=50, pct_ok=95).total_bot_failure_count
        )
