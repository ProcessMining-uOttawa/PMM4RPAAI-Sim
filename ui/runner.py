"""Background experiment runner for the Streamlit UI.

Encapsulates the threading primitives so app.py sees only start/cancel/clear/commit.
The background thread communicates exclusively through the RunState object,
which is pre-allocated in session state before the thread starts — no Streamlit
API calls are made from the background thread.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

from core.orchestrator import ExperimentCancelledError, ExperimentResult


@dataclass
class RunOutcome:
    """Terminal state of a finished run. Exactly one of result/error/cancelled is set."""
    result: ExperimentResult | None = None
    error: Exception | None = None
    cancelled: bool = False


@dataclass
class RunState:
    """Mutable run state written by the background thread via on_progress/worker."""
    done: int = 0
    total: int = 0
    label: str = "starting"
    rep: int = 0
    outcome: RunOutcome | None = None  # None = still running; set atomically when done


def start_experiment(
    ss: Any,
    fn: Callable[[Callable[..., None], threading.Event], ExperimentResult],
) -> None:
    """Launch a background experiment run.

    fn receives (on_progress, stop_event) and must return ExperimentResult.
    Progress is written to ss.run_state; the thread handle lives in ss.run_thread.
    """
    run_state = RunState()
    stop_event = threading.Event()
    ss.run_state = run_state
    ss.stop_event = stop_event

    def on_progress(done: int, total: int, label: str, rep: int) -> None:
        run_state.done = done
        run_state.total = total
        run_state.label = label
        run_state.rep = rep

    def worker() -> None:
        try:
            run_state.outcome = RunOutcome(result=fn(on_progress, stop_event))
        except ExperimentCancelledError:
            run_state.outcome = RunOutcome(cancelled=True)
        except Exception as exc:
            run_state.outcome = RunOutcome(error=exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    ss.run_thread = thread


def current_run(ss: Any) -> RunState | None:
    """Return the active RunState, or None if no run has been started."""
    return ss.get("run_state")


def cancel_experiment(ss: Any) -> None:
    """Signal the running experiment to stop after its next completed task."""
    ev = ss.get("stop_event")
    if ev is not None:
        ev.set()


def commit_result(ss: Any, result: ExperimentResult) -> None:
    """Write an ExperimentResult's fields into session state. Counterpart to _clear_results()."""
    ss.results = result.results
    ss.experiment_bpmn_path = result.experiment_bpmn_path
    ss.scenario_json_paths = result.scenario_json_paths
    ss.baseline_agg = result.baseline_agg
    ss.scenario_log_paths = result.scenario_log_paths
    ss.baseline_log_paths = result.baseline_log_paths


def clear_run(ss: Any) -> None:
    """Remove all run-related keys from session state after a run finishes."""
    ss.run_thread = None
    ss.run_state = None
    ss.stop_event = None
