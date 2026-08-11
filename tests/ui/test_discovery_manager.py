"""Tests for ui/discovery_manager — the session lifecycle: commit_discovery's
session-key contract, the session's construction-time identity, and the
cancel/supersede kill semantics.

The fidelity panel reads ss.simod_csv_path / ss.log_case_count by exact name
(its toggle disables when either is None), so the producer side must be pinned
— the commit_as_discovered precedent in test_run_manager.py.
"""

from __future__ import annotations

import threading
from pathlib import Path

from ui import discovery_manager
from ui.discovery_manager import (
    DiscoveryResult,
    cancel_discovery,
    commit_discovery,
    start_discovery,
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


def _result() -> DiscoveryResult:
    return DiscoveryResult(
        bpmn_path=Path("outputs/model.bpmn"),
        json_path=Path("outputs/params.json"),
        activities=["Fix Bug"],
        log_name="log.csv",
        log_path=Path("log.csv"),
        simod_csv_path=Path("log.csv"),
        log_case_count=42,
    )


class TestCommitDiscovery:
    def test_writes_the_fidelity_keys(self):
        ss = _FakeSession()
        commit_discovery(
            ss, _result(), fingerprint=("log.csv", 10), search_iterations=None
        )
        assert ss.simod_csv_path == Path("log.csv")
        assert ss.log_case_count == 42

    def test_stamps_the_fingerprint(self):
        # log_fingerprint is what makes the upload read as already-discovered.
        ss = _FakeSession()
        commit_discovery(
            ss, _result(), fingerprint=("log.csv", 10), search_iterations=None
        )
        assert ss.log_fingerprint == ("log.csv", 10)

    def test_commit_writes_search_iterations(self):
        # The discovery-mode provenance the sidebar's mismatch caption and
        # Loaded caption read by exact key name. Passed from the session (the
        # fingerprint shape), not carried on the result.
        ss = _FakeSession()
        commit_discovery(
            ss, _result(), fingerprint=("log.csv", 10), search_iterations=10
        )
        assert ss.discovery_search_iterations == 10


class TestStartDiscovery:
    def test_start_discovery_stores_search_iterations(self):
        # The progress fragment's duration caption and the commit read the
        # session's value — the mode the run actually started with, never the
        # live widget.
        ss = _FakeSession()
        start_discovery(
            ss, ("log.csv", 10), lambda register: _result(), search_iterations=7
        )
        assert ss.discovery.search_iterations == 7
        ss.discovery.thread.join(timeout=5)  # reap the daemon; the field is
        # set at construction, before the thread starts — not worker-written.

    def test_start_discovery_does_not_stamp_fingerprint(self):
        # log_fingerprint means "the committed model came from this file" and
        # is claimed at commit only — a failed/cancelled discovery must leave
        # the previous log's identity intact so retry genuinely re-discovers.
        # (Pins the manager seam only; app.py's routing half is not
        # AppTest-reachable and is covered by the manual smoke.)
        ss = _FakeSession()
        start_discovery(
            ss, ("log.csv", 10), lambda register: _result(), search_iterations=None
        )
        ss.discovery.thread.join(timeout=5)
        assert "log_fingerprint" not in ss

    def test_start_discovery_cancels_a_live_predecessor(self, monkeypatch):
        # Overwrite means cancel: a superseded in-flight discovery must not
        # run (and its Simod burn) to completion unobserved.
        killed: list = []
        monkeypatch.setattr(discovery_manager, "terminate_process", killed.append)
        ss = _FakeSession()
        first_process = object()
        registered = threading.Event()
        release = threading.Event()

        def first_fn(register):
            register(first_process)
            registered.set()
            assert release.wait(timeout=5)
            return _result()

        start_discovery(ss, ("a.csv", 1), first_fn, search_iterations=None)
        first_session = ss.discovery
        assert registered.wait(timeout=5)
        start_discovery(
            ss, ("b.csv", 2), lambda register: _result(), search_iterations=None
        )
        assert first_session.cancelled
        assert killed == [first_process]
        release.set()
        first_session.thread.join(timeout=5)
        ss.discovery.thread.join(timeout=5)


class TestCancelDiscovery:
    """The cancel-kill handshake: cancel sets the flag then kills the stored
    process; the worker's register hook stores then checks the flag — the two
    mirrored orders mean a spawn racing a cancel is killed by one side."""

    def test_cancel_kills_the_registered_process(self, monkeypatch):
        killed: list = []
        monkeypatch.setattr(discovery_manager, "terminate_process", killed.append)
        ss = _FakeSession()
        process = object()

        def fn(register):
            register(process)
            return _result()

        start_discovery(ss, ("log.csv", 10), fn, search_iterations=None)
        ss.discovery.thread.join(timeout=5)
        cancel_discovery(ss)
        assert killed == [process]
        assert ss.discovery.cancelled

    def test_cancel_before_spawn_kills_on_register(self, monkeypatch):
        # The pre-spawn window: cancel lands while the worker is still writing
        # the log / converting / validating (no process yet) — the registration itself
        # must kill, or the spawn would be orphaned.
        killed: list = []
        monkeypatch.setattr(discovery_manager, "terminate_process", killed.append)
        ss = _FakeSession()
        process = object()
        cancelled_first = threading.Event()

        def fn(register):
            assert cancelled_first.wait(timeout=5)
            register(process)
            return _result()

        start_discovery(ss, ("log.csv", 10), fn, search_iterations=None)
        cancel_discovery(ss)  # session.process is still None here
        cancelled_first.set()
        ss.discovery.thread.join(timeout=5)
        assert killed == [process]

    def test_cancel_with_no_process_is_safe(self, monkeypatch):
        killed: list = []
        monkeypatch.setattr(discovery_manager, "terminate_process", killed.append)
        ss = _FakeSession()
        start_discovery(
            ss, ("log.csv", 10), lambda register: _result(), search_iterations=None
        )
        ss.discovery.thread.join(timeout=5)
        cancel_discovery(ss)  # fn never registered a process
        assert killed == []
        assert ss.discovery.cancelled
