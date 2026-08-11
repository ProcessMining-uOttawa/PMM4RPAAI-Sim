"""Background Simod-discovery runner + state machine for the Streamlit UI.

The discovery counterpart to run_manager. Discovery runs in a daemon thread so a
mid-discovery rerun cannot interrupt it: Streamlit's runner.fastReruns turns a
sidebar interaction (e.g. nudging a run-config widget before discovery finishes)
into a fresh script thread, which would otherwise abort a discovery running
synchronously in the main thread. A background thread is immune.

The lifecycle is an explicit **state machine keyed by the upload fingerprint**.
A single session-state key `ss.discovery` holds one `DiscoverySession` (or None);
`discovery_phase(ss, upload_fp)` is the sole router. Bundling the fingerprint
*into* the session is the load-bearing design choice: "is this discovery state
relevant to the file currently in the uploader?" is one always-correct check
(`session.fingerprint == upload_fp`), so a cancelled/failed session for file A is
automatically irrelevant the moment file B is uploaded — no separate fingerprint
flag to drift out of sync (the bug that motivated this). The worker thread never
touches st.* — it writes only `session.outcome` and `session.process` (single
GIL-safe assignments each).
"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable

from core.simulation.runner import terminate_process

Fingerprint = tuple[str, int]  # (upload name, size) — identity of an uploaded log


class DiscoveryPhase(Enum):
    """The phase of the current upload's discovery. None (no member) = no
    relevant session: the upload is idle (never discovered) or already done."""

    RUNNING = auto()  # thread in flight, or succeeded and awaiting commit
    FAILED = auto()  # Simod raised
    CANCELLED = auto()  # user abandoned the wait


@dataclass
class DiscoveryResult:
    """What the discovery worker computes for session state.

    The run's construction-time identity (fingerprint, search mode) is
    committed from the session, not from here — see commit_discovery.
    simod_csv_path / log_case_count feed the model fidelity check: the
    Simod-ready CSV the discovery actually ran on (the observed side's source
    file) and its distinct-case count (the pinned cases-per-replication).
    Demo mode bypasses this module entirely — app.py owns its session keys.
    """

    bpmn_path: Path
    json_path: Path
    activities: list[str]
    log_name: str
    log_path: Path
    simod_csv_path: Path
    log_case_count: int


@dataclass
class DiscoveryOutcome:
    """Terminal state of the worker. Exactly one of result/error is set."""

    result: DiscoveryResult | None = None
    error: Exception | None = None


@dataclass
class DiscoverySession:
    """One discovery, tied to the upload it is about.

    outcome is None while the thread runs; the worker sets it once. cancelled is
    set by the UI. Kept in ss.discovery; superseded (overwritten) when discovery
    starts for a different upload.
    """

    fingerprint: Fingerprint
    # The discovery mode this session started with (None = fast) —
    # construction-time identity like fingerprint, not lifecycle state. The
    # progress fragment's duration caption and the commit read it here, never
    # the live widget: the session is the run's own record, whatever the UI
    # currently renders.
    search_iterations: int | None
    outcome: DiscoveryOutcome | None = None
    cancelled: bool = False
    thread: threading.Thread | None = None
    # The live Simod Popen, worker-written via the register hook (a single
    # GIL-safe assignment, like outcome) — cancel_discovery's kill handle.
    process: subprocess.Popen | None = None


def start_discovery(
    ss: Any,
    fingerprint: Fingerprint,
    fn: Callable[[Callable[[subprocess.Popen], None]], DiscoveryResult],
    search_iterations: int | None,
) -> None:
    """Launch discovery for `fingerprint` in a daemon thread.

    fn receives a register callback to pass as runner.discover's on_spawn (the
    run_manager fn-receives-hooks shape) and returns the result. Overwrites any
    prior session, so a new upload cleanly supersedes a stale one.
    """
    session = DiscoverySession(
        fingerprint=fingerprint, search_iterations=search_iterations
    )
    ss.discovery = session

    def register(process: subprocess.Popen) -> None:
        # Store first, then check cancelled — cancel_discovery does the
        # mirror (set cancelled, then read the stored process), so whichever
        # order the two interleave in, at least one side performs the kill;
        # a cancel clicked before the spawn cannot orphan the subprocess.
        session.process = process
        if session.cancelled:
            terminate_process(process)

    def worker() -> None:
        try:
            session.outcome = DiscoveryOutcome(result=fn(register))
        except Exception as exc:  # surfaced to the user via the outcome
            session.outcome = DiscoveryOutcome(error=exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    session.thread = thread


def current_discovery(ss: Any) -> DiscoverySession | None:
    """The stored discovery session, or None. Prefer discovery_phase() for routing."""
    return ss.get("discovery")


def discovery_phase(ss: Any, fingerprint: Fingerprint | None) -> DiscoveryPhase | None:
    """The phase of discovery for the upload currently in the uploader.

    None when there is no session, or the session is about a *different* upload
    (the fingerprint-keying that makes a stale terminal state irrelevant).
    """
    session = current_discovery(ss)
    if session is None or session.fingerprint != fingerprint:
        return None
    if session.cancelled:
        return DiscoveryPhase.CANCELLED
    if session.outcome is not None and session.outcome.error is not None:
        return DiscoveryPhase.FAILED
    return DiscoveryPhase.RUNNING


def discovery_error(ss: Any) -> Exception | None:
    """The exception from a failed discovery, or None. Keeps the outcome.error
    navigation next to discovery_phase() rather than in the composition root."""
    session = current_discovery(ss)
    if session is None or session.outcome is None:
        return None
    return session.outcome.error


def commit_discovery(
    ss: Any,
    result: DiscoveryResult,
    fingerprint: Fingerprint,
    search_iterations: int | None,
) -> None:
    """Write a successful discovery's result into session state.

    The positive counterpart to clear_discovery(), mirroring run_manager's
    commit_result(); stamps log_fingerprint so the upload reads as
    already-discovered. fingerprint and search_iterations come from the
    session, not the result — they are the run's construction-time identity,
    which the worker's output never carries.
    """
    ss.bpmn_path = result.bpmn_path
    ss.json_path = result.json_path
    ss.activities = result.activities
    ss.log_name = result.log_name
    ss.log_path = result.log_path
    ss.simod_csv_path = result.simod_csv_path
    ss.log_case_count = result.log_case_count
    ss.discovery_search_iterations = search_iterations
    ss.log_fingerprint = fingerprint


def cancel_discovery(ss: Any) -> None:
    """Mark the in-flight discovery cancelled and kill its Simod subprocess.

    Set cancelled first, then kill: the worker's register hook does the mirror
    (store the process, then check cancelled), so a spawn racing this call is
    killed by one side or the other. A killed Simod exits nonzero → the worker
    records an error outcome, which the cancelled flag outranks in
    discovery_phase — the user sees CANCELLED, not FAILED.
    """
    session = current_discovery(ss)
    if session is not None:
        session.cancelled = True
        if session.process is not None:
            terminate_process(session.process)


def clear_discovery(ss: Any) -> None:
    """Drop the session — the transition back to idle (retry, success, log reset)."""
    ss.discovery = None
