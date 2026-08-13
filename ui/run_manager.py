"""Background run lifecycle for the Streamlit UI, shared by both run species
(RunState.kind: the experiment run and the as-discovered fidelity run).

Encapsulates the threading primitives behind start/cancel/clear/commit.
The background thread communicates exclusively through the RunState object,
which is pre-allocated in session state before the thread starts — no Streamlit
API calls are made from the background thread.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Literal

from core.orchestrator import (
    AsDiscoveredResult,
    ExperimentCancelledError,
    ExperimentResult,
)

# The two run species sharing this one background-thread lifecycle. A Literal,
# not an Enum (the ParameterKind precedent): a declaration-time tag determined
# at the two start_experiment call sites (one explicit, one defaulted) and
# branched on by the two panels' kind guards.
RunKind = Literal["experiment", "as_discovered"]


@dataclass
class RunOutcome:
    """Terminal state of a finished run. Exactly one of result/error/cancelled is set."""

    result: ExperimentResult | AsDiscoveredResult | None = None
    error: Exception | None = None
    cancelled: bool = False


@dataclass
class RunState:
    """Mutable run state written by the background thread via on_progress/worker.

    kind routes the two panels: each polls / commits only its own species, and
    disables its Run button while the other kind is in flight (the runs are
    mutually exclusive — both saturate max_workers subprocesses, and a second
    start would clobber this object under a live worker).
    """

    done: int = 0
    total: int = 0
    label: str = "starting"
    rep: int = 0
    kind: RunKind = "experiment"
    outcome: RunOutcome | None = None  # None = still running; set atomically when done


def start_experiment(
    ss: Any,
    fn: Callable[
        [Callable[..., None], threading.Event], ExperimentResult | AsDiscoveredResult
    ],
    kind: RunKind = "experiment",
) -> None:
    """Launch a background run of either kind.

    fn receives (on_progress, stop_event) and must return the result matching
    `kind`. Progress is written to ss.run_state; the thread handle lives in
    ss.run_thread.
    """
    run_state = RunState(kind=kind)
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
    """Signal the in-flight run (either kind) to stop.

    Sets the stop event the executor's stop_check polls; a real-pipeline cancel
    kills in-flight simulation subprocesses (see executor.run_all), so it takes
    effect promptly rather than waiting out running replications.
    """
    ev = ss.get("stop_event")
    if ev is not None:
        ev.set()


def is_cancelling(ss: Any) -> bool:
    """True while a cancellation is in flight: the stop_event has been set but the
    run has not yet been torn down (clear_run nulls the event). Drives the run
    panels' "Cancelling…" feedback between the click and the terminal
    cancelled outcome."""
    ev = ss.get("stop_event")
    return ev is not None and ev.is_set()


def clear_results(ss: Any) -> None:
    """Reset the run-level session state.

    The negative counterpart to commit_result(). Called both to blank Panel 5
    at the start of a new run and, via app._clear_process_state(), when the
    loaded log is reset or replaced.

    Two deliberate asymmetries against commit_result(): baseline_agg is
    written there but NOT cleared here — its validity is log-scoped, not
    run-scoped (the same discovered model means the previous run's baseline
    stays a correct reference while a re-run is in flight; nulling it at run
    start would collapse Panel 3's goal-threshold rows to metric pickers on
    any mid-run rerun; app._clear_process_state() clears it where the process
    actually changes). run_error is cleared here but never committed — it is
    run-scoped display state occupying the results slot, not a result field.
    """
    ss.experiment_result = None
    ss.run_error = None


def commit_result(ss: Any, result: ExperimentResult) -> None:
    """Commit a finished experiment run into session state.

    The dataclass is committed whole (ss.experiment_result), mirroring
    commit_as_discovered — a new ExperimentResult field reaches consumers with
    no edit here. baseline_agg is additionally copied out beside it because
    its lifecycle differs from its carrier's: log-scoped, surviving the
    clear_results at the next run start (see clear_results).
    """
    ss.experiment_result = result
    ss.baseline_agg = result.baseline_agg


def commit_as_discovered(ss: Any, result: AsDiscoveredResult) -> None:
    """Write a finished as-discovered run's result into session state.

    The dataclass is committed whole (ss.as_discovered_result) — one consumer
    (the fidelity panel), so no per-field unpacking like commit_result's.
    """
    ss.as_discovered_result = result


def clear_as_discovered(ss: Any) -> None:
    """Reset the as-discovered result and its failure slot.

    Called at fidelity-run start (blank slate, mirroring clear_results) and
    from app._clear_process_state() — the artifact is log-scoped, so
    clear_results, which runs at every *experiment* run start, deliberately
    leaves it alone (the baseline_agg asymmetry precedent).
    """
    ss.as_discovered_result = None
    ss.as_discovered_error = None


def clear_run(ss: Any) -> None:
    """Remove all run-related keys from session state after a run finishes."""
    ss.run_thread = None
    ss.run_state = None
    ss.stop_event = None
