"""Tests for ui/run_manager — the run-kind discriminant and the as-discovered
commit/clear pair, including the clear_results asymmetry (the as-discovered
artifact is log-scoped, so the run-level reset must leave it alone)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.orchestrator import AsDiscoveredResult, ExperimentResult
from ui.run_manager import (
    RunState,
    clear_as_discovered,
    clear_results,
    commit_as_discovered,
    commit_result,
    start_experiment,
)


class _FakeSession(dict):
    """Attribute-style dict standing in for st.session_state."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


def _as_discovered_result() -> AsDiscoveredResult:
    return AsDiscoveredResult(
        results=pd.DataFrame({"replication": [0]}),
        n_cases=5,
        experiment_dir=Path("runs/x"),
    )


class TestRunKind:
    def test_default_kind_is_experiment(self):
        assert RunState().kind == "experiment"

    def test_start_experiment_records_kind(self):
        ss = _FakeSession()
        result = _as_discovered_result()
        start_experiment(ss, lambda cb, ev: result, kind="as_discovered")
        ss.run_thread.join(timeout=5)  # thread hygiene — kind is set synchronously
        assert ss.run_state.kind == "as_discovered"
        # The widened result union round-trips: the worker stores the
        # AsDiscoveredResult, not the error arm.
        outcome = ss.run_state.outcome
        assert outcome is not None and outcome.result is result

    def test_start_experiment_defaults_to_experiment_kind(self):
        ss = _FakeSession()
        experiment_result = ExperimentResult(
            results=pd.DataFrame({"scenario_id": ["S01"]}), n_cases=5
        )
        start_experiment(ss, lambda cb, ev: experiment_result)
        ss.run_thread.join(timeout=5)  # thread hygiene — kind is set synchronously
        assert ss.run_state.kind == "experiment"
        outcome = ss.run_state.outcome
        assert outcome is not None and outcome.result is experiment_result


class TestCommitClearResult:
    def test_commit_sets_the_result_whole_and_copies_baseline(self):
        # The dataclass is committed whole (the as-discovered precedent);
        # baseline_agg is additionally copied out because its lifecycle is
        # log-scoped, not run-scoped.
        ss = _FakeSession()
        result = ExperimentResult(
            results=pd.DataFrame({"scenario_id": ["S01"]}),
            n_cases=5,
            baseline_agg={"mean_cycle_h": 1.0},
        )
        commit_result(ss, result)
        assert ss.experiment_result is result
        assert ss.baseline_agg == {"mean_cycle_h": 1.0}

    def test_clear_resets_result_and_error_but_not_baseline(self):
        # baseline_agg survives clear_results (run start): the previous run's
        # baseline keeps seeding Panel 3's thresholds while a re-run is in
        # flight. Only _clear_process_state clears it (log reset/replacement).
        ss = _FakeSession()
        ss.experiment_result = object()
        ss.run_error = RuntimeError("boom")
        ss.baseline_agg = {"mean_cycle_h": 1.0}
        clear_results(ss)
        assert ss.experiment_result is None
        assert ss.run_error is None
        assert ss.baseline_agg == {"mean_cycle_h": 1.0}


class TestCommitClearAsDiscovered:
    def test_commit_sets_the_result_whole(self):
        ss = _FakeSession()
        result = _as_discovered_result()
        commit_as_discovered(ss, result)
        assert ss.as_discovered_result is result

    def test_clear_resets_result_and_error(self):
        ss = _FakeSession()
        ss.as_discovered_result = _as_discovered_result()
        ss.as_discovered_error = RuntimeError("boom")
        clear_as_discovered(ss)
        assert ss.as_discovered_result is None
        assert ss.as_discovered_error is None


class TestClearResultsAsymmetry:
    def test_clear_results_leaves_the_as_discovered_artifact(self):
        # clear_results runs at every experiment-run start; the as-discovered
        # result is log-scoped (the baseline_agg precedent), so an experiment
        # re-run must not wipe it.
        ss = _FakeSession()
        result = _as_discovered_result()
        error = RuntimeError("boom")
        ss.as_discovered_result = result
        ss.as_discovered_error = error
        clear_results(ss)
        assert ss.as_discovered_result is result
        assert ss.as_discovered_error is error
