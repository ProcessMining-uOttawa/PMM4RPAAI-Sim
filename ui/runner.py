"""Background experiment runner for the Streamlit UI.

Encapsulates the threading primitives so app.py sees only start/cancel/clear.
The background thread communicates exclusively through the RunState object,
which is pre-allocated in session state before the thread starts — no Streamlit
API calls are made from the background thread.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from core.orchestrator import ExperimentCancelledError, ExperimentResult


@dataclass
class RunState:
    done: int = 0
    total: int = 0
    label: str = "starting"
    rep: int = 0
    result: ExperimentResult | None = None
    error: Exception | None = None
    cancelled: bool = False


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
            run_state.result = fn(on_progress, stop_event)
        except ExperimentCancelledError:
            run_state.cancelled = True
        except Exception as exc:
            run_state.error = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    ss.run_thread = thread


def current_run(ss: Any) -> RunState | None:
    """Return the active RunState, or None if no run is in progress."""
    return getattr(ss, "run_state", None)


def is_running(ss: Any) -> bool:
    """True while the background thread is still alive."""
    thread = getattr(ss, "run_thread", None)
    return thread is not None and thread.is_alive()


def cancel_experiment(ss: Any) -> None:
    """Signal the running experiment to stop after its next completed task."""
    if getattr(ss, "stop_event", None) is not None:
        ss.stop_event.set()


def clear_run(ss: Any) -> None:
    """Remove all run-related keys from session state after a run finishes."""
    ss.run_thread = None
    ss.run_state = None
    ss.stop_event = None
