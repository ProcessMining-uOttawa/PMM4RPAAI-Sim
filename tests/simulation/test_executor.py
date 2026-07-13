"""Tests for executor.run_all() — stop_check predicate, completion flag, and on_error callback."""

from __future__ import annotations

import subprocess
import threading
import time

import pytest

from core.simulation import executor, runner


def _tasks(tmp_path, n: int, max_retries: int = 0) -> list[executor.SimulationTask]:
    return [
        executor.SimulationTask(
            bpmn_path=tmp_path / f"{i}.bpmn",
            json_path=tmp_path / f"{i}.json",
            n_cases=1,
            out_log=tmp_path / f"{i}_log.csv",
            out_stat=None,
            proc_log=None,
            max_retries=max_retries,
        )
        for i in range(n)
    ]


class TestRunAllStopCheck:
    def test_returns_true_without_stop_check(self, monkeypatch, tmp_path):
        monkeypatch.setattr(runner, "simulate", lambda *a, **kw: None)
        completed = executor.run_all(_tasks(tmp_path, 3), lambda t: None)
        assert completed is True

    def test_returns_true_when_stop_check_always_false(self, monkeypatch, tmp_path):
        monkeypatch.setattr(runner, "simulate", lambda *a, **kw: None)
        completed = executor.run_all(
            _tasks(tmp_path, 3), lambda t: None, stop_check=lambda: False
        )
        assert completed is True

    def test_returns_false_when_stop_check_fires(self, monkeypatch, tmp_path):
        monkeypatch.setattr(runner, "simulate", lambda *a, **kw: None)
        completed = executor.run_all(
            _tasks(tmp_path, 5), lambda t: None, stop_check=lambda: True
        )
        assert completed is False

    def test_on_complete_not_called_after_stop(self, monkeypatch, tmp_path):
        monkeypatch.setattr(runner, "simulate", lambda *a, **kw: None)
        completed_tasks: list = []
        executor.run_all(
            _tasks(tmp_path, 5),
            lambda t: completed_tasks.append(t),
            stop_check=lambda: True,
        )
        assert len(completed_tasks) == 0

    def test_on_complete_called_for_all_tasks_without_stop_check(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(runner, "simulate", lambda *a, **kw: None)
        completed_tasks: list = []
        executor.run_all(_tasks(tmp_path, 4), lambda t: completed_tasks.append(t))
        assert len(completed_tasks) == 4


def _always_fail(*a, **kw) -> None:
    raise RuntimeError("simfail")


class _FailNTimes:
    """Stateful simulate stub that fails the first `n` calls then succeeds."""

    def __init__(self, n: int) -> None:
        self._remaining = n

    def __call__(self, *a: object, **kw: object) -> None:
        if self._remaining > 0:
            self._remaining -= 1
            raise RuntimeError("simfail")


class _CountingSim:
    """simulate stub that counts invocations and fails the first `fail_first`
    calls. `fail_first=None` means every call fails (an always-failing sim).

    A single-task run retries sequentially (the next attempt is only submitted
    after the previous future resolves on the calling thread), so `calls` is
    written by one worker at a time and read after the pool has joined — no lock
    needed.
    """

    def __init__(self, fail_first: int | None) -> None:
        self.calls = 0
        self._fail_first = fail_first

    def __call__(self, *a: object, **kw: object) -> None:
        self.calls += 1
        if self._fail_first is None or self.calls <= self._fail_first:
            raise RuntimeError("simfail")


class _ProcLogRecorder:
    """simulate stub recording the `proc_log` kwarg of each call; fails the
    first `fail_first` calls so the retry path is exercised."""

    def __init__(self, fail_first: int) -> None:
        self.calls = 0
        self._fail_first = fail_first
        self.proc_logs: list = []

    def __call__(self, *a: object, proc_log: object = None, **kw: object) -> None:
        self.calls += 1
        self.proc_logs.append(proc_log)
        if self.calls <= self._fail_first:
            raise RuntimeError("simfail")


class TestRunAllOnError:
    def test_on_error_called_when_simulate_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(runner, "simulate", _always_fail)
        errors: list = []
        executor.run_all(
            _tasks(tmp_path, 2), lambda t: None, on_error=lambda t, e: errors.append(t)
        )
        assert len(errors) == 2

    def test_on_complete_not_called_for_failed_tasks(self, monkeypatch, tmp_path):
        def _mixed(bpmn_path, *a, **kw) -> None:
            if bpmn_path.name == "0.bpmn":
                raise RuntimeError("simfail")

        monkeypatch.setattr(runner, "simulate", _mixed)
        completed: list = []
        executor.run_all(
            _tasks(tmp_path, 3),
            lambda t: completed.append(t),
            on_error=lambda t, e: None,
        )
        assert len(completed) == 2

    def test_run_all_returns_true_despite_all_failures(self, monkeypatch, tmp_path):
        monkeypatch.setattr(runner, "simulate", _always_fail)
        result = executor.run_all(
            _tasks(tmp_path, 2), lambda t: None, on_error=lambda t, e: None
        )
        assert result is True

    def test_no_on_error_provided_failures_silently_skipped(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(runner, "simulate", _always_fail)
        result = executor.run_all(_tasks(tmp_path, 2), lambda t: None)
        assert result is True


class TestRunAllRetry:
    def test_transient_failure_recovered_via_retry(self, monkeypatch, tmp_path):
        """Task fails once then succeeds — on_complete called, on_error not called."""
        monkeypatch.setattr(runner, "simulate", _FailNTimes(1))
        completed, errors = [], []
        executor.run_all(
            _tasks(tmp_path, 1, max_retries=1),
            lambda t: completed.append(t),
            on_error=lambda t, e: errors.append(t),
        )
        assert len(completed) == 1
        assert len(errors) == 0

    def test_retries_exhausted_calls_on_error_once(self, monkeypatch, tmp_path):
        """Task always fails with max_retries=2 — on_error called exactly once."""
        monkeypatch.setattr(runner, "simulate", _always_fail)
        errors = []
        executor.run_all(
            _tasks(tmp_path, 1, max_retries=2),
            lambda t: None,
            on_error=lambda t, e: errors.append(t),
        )
        assert len(errors) == 1

    def test_zero_retries_calls_on_error_immediately(self, monkeypatch, tmp_path):
        """max_retries=0 — on_error fires on first failure with no retry."""
        monkeypatch.setattr(runner, "simulate", _always_fail)
        errors = []
        executor.run_all(
            _tasks(tmp_path, 1),
            lambda t: None,
            on_error=lambda t, e: errors.append(t),
        )
        assert len(errors) == 1

    def test_on_complete_not_called_for_exhausted_task(self, monkeypatch, tmp_path):
        """Task that exhausts all retries must not call on_complete."""
        monkeypatch.setattr(runner, "simulate", _always_fail)
        completed = []
        executor.run_all(
            _tasks(tmp_path, 1, max_retries=1),
            lambda t: completed.append(t),
            on_error=lambda t, e: None,
        )
        assert len(completed) == 0

    # ── attempt-count contract: attempts == 1 + max_retries ──────────────────

    def test_zero_retries_makes_exactly_one_attempt(self, monkeypatch, tmp_path):
        sim = _CountingSim(fail_first=None)  # always fails
        monkeypatch.setattr(runner, "simulate", sim)
        executor.run_all(
            _tasks(tmp_path, 1, max_retries=0),
            lambda t: None,
            on_error=lambda t, e: None,
        )
        assert sim.calls == 1

    def test_two_retries_makes_exactly_three_attempts(self, monkeypatch, tmp_path):
        sim = _CountingSim(fail_first=None)  # always fails
        monkeypatch.setattr(runner, "simulate", sim)
        executor.run_all(
            _tasks(tmp_path, 1, max_retries=2),
            lambda t: None,
            on_error=lambda t, e: None,
        )
        assert sim.calls == 3

    def test_transient_failure_makes_exactly_two_attempts(self, monkeypatch, tmp_path):
        sim = _CountingSim(fail_first=1)  # fails once, then succeeds
        monkeypatch.setattr(runner, "simulate", sim)
        completed: list = []
        executor.run_all(
            _tasks(tmp_path, 1, max_retries=1),
            lambda t: completed.append(t),
            on_error=lambda t, e: None,
        )
        assert sim.calls == 2
        assert len(completed) == 1


class TestRunAllDocumentedBehaviours:
    """Coverage for three documented run_all behaviours: retry log preservation,
    callback-exception propagation, and metadata survival through the retry replace."""

    def test_retry_resets_proc_log_to_none(self, monkeypatch, tmp_path):
        # The resubmitted task is dataclasses.replace(task, ..., proc_log=None) so
        # the retry does not overwrite the failed attempt's captured subprocess log.
        recorder = _ProcLogRecorder(fail_first=1)
        monkeypatch.setattr(runner, "simulate", recorder)
        proc_log = tmp_path / "0_proc.log"
        task = executor.SimulationTask(
            bpmn_path=tmp_path / "0.bpmn",
            json_path=tmp_path / "0.json",
            n_cases=1,
            out_log=tmp_path / "0_log.csv",
            out_stat=None,
            proc_log=proc_log,
            max_retries=1,
        )
        executor.run_all([task], lambda t: None, on_error=lambda t, e: None)
        # First attempt keeps the original proc_log; the retry passes None.
        assert recorder.proc_logs == [proc_log, None]

    def test_on_complete_exception_propagates(self, monkeypatch, tmp_path):
        monkeypatch.setattr(runner, "simulate", lambda *a, **kw: None)

        def _boom(task: executor.SimulationTask) -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            executor.run_all(_tasks(tmp_path, 2), _boom)

    def test_on_error_receives_task_with_metadata_intact(self, monkeypatch, tmp_path):
        # The task handed to on_error is the retry-replaced copy, but replace()
        # preserves metadata (only max_retries / proc_log change).
        monkeypatch.setattr(runner, "simulate", _always_fail)
        sentinel = object()
        task = executor.SimulationTask(
            bpmn_path=tmp_path / "0.bpmn",
            json_path=tmp_path / "0.json",
            n_cases=1,
            out_log=tmp_path / "0_log.csv",
            out_stat=None,
            proc_log=None,
            metadata=sentinel,
            max_retries=2,
        )
        errored: list = []
        executor.run_all(
            [task], lambda t: None, on_error=lambda t, e: errored.append(t)
        )
        assert len(errored) == 1
        assert errored[0].metadata is sentinel


class TestLiveProcesses:
    """The registry that lets a cancel kill in-flight subprocesses. Deterministic,
    no threads — the primary fence for the register/kill/race logic."""

    def test_register_then_kill_all_kills_each(self, monkeypatch):
        killed: list = []
        monkeypatch.setattr(runner, "terminate_process", lambda p: killed.append(p))
        live = executor._LiveProcesses()
        procs = [object(), object(), object()]
        for p in procs:
            live.register(p)
        live.kill_all()
        assert set(killed) == set(procs)
        assert live._procs == set()  # cleared after kill

    def test_register_after_kill_all_kills_immediately(self, monkeypatch):
        # Spawn-after-cancel race: a proc registered once killing has begun is
        # killed on the spot and NOT stored, so it can't re-block the pool join.
        killed: list = []
        monkeypatch.setattr(runner, "terminate_process", lambda p: killed.append(p))
        live = executor._LiveProcesses()
        live.kill_all()  # nothing registered yet, but flips _killing
        late = object()
        live.register(late)
        assert killed == [late]
        assert late not in live._procs


class _BlockingSim:
    """A runner.simulate stand-in that registers a fake proc then blocks until a
    stubbed terminate_process 'kills' it — models an in-flight Prosimos worker that
    only unblocks when cancelled."""

    def __init__(self) -> None:
        self.released: dict = {}
        self.killed: list = []

    def simulate(self, *a, on_spawn=None, **kw):
        proc = object()
        ev = threading.Event()
        self.released[proc] = ev  # before register, so terminate() always finds it
        if on_spawn is not None:
            on_spawn(proc)
        ev.wait(timeout=5)  # released only by terminate(); 5s is a hang backstop
        raise subprocess.CalledProcessError(1, "killed")

    def terminate(self, proc) -> None:
        self.killed.append(proc)
        self.released[proc].set()


class TestPromptCancel:
    """The cancel path with real threads: the timeout poll sees a cancel even when
    no task completes, kills the running procs, and doesn't retry/error them."""

    def test_cancel_returns_false_while_all_workers_busy(self, monkeypatch, tmp_path):
        # No task ever completes on its own; only the timeout poll can see the
        # cancel. Without it run_all would block ~5s on the sim's ev.wait.
        sim = _BlockingSim()
        monkeypatch.setattr(runner, "simulate", sim.simulate)
        monkeypatch.setattr(runner, "terminate_process", sim.terminate)
        start = time.monotonic()
        completed = executor.run_all(
            _tasks(tmp_path, 4),
            lambda t: None,
            stop_check=lambda: True,
            max_workers=2,
        )
        elapsed = time.monotonic() - start
        assert completed is False
        assert elapsed < 3.0  # ~0.5s poll + instant kill, not the 5s block

    def test_cancel_kills_running_procs(self, monkeypatch, tmp_path):
        # 4 workers, 4 slots → all run and register; cancel kills every one.
        sim = _BlockingSim()
        monkeypatch.setattr(runner, "simulate", sim.simulate)
        monkeypatch.setattr(runner, "terminate_process", sim.terminate)
        executor.run_all(
            _tasks(tmp_path, 4),
            lambda t: None,
            stop_check=lambda: True,
            max_workers=4,
        )
        assert len(sim.killed) == 4

    def test_killed_tasks_not_retried_or_errored(self, monkeypatch, tmp_path):
        # Killed subprocesses raise CalledProcessError, but on cancel we return
        # before processing any future — so no retry and no on_error fires.
        sim = _BlockingSim()
        monkeypatch.setattr(runner, "simulate", sim.simulate)
        monkeypatch.setattr(runner, "terminate_process", sim.terminate)
        on_complete: list = []
        on_error: list = []
        completed = executor.run_all(
            _tasks(tmp_path, 4, max_retries=2),
            lambda t: on_complete.append(t),
            on_error=lambda t, e: on_error.append(t),
            stop_check=lambda: True,
            max_workers=2,
        )
        assert completed is False
        assert on_complete == []
        assert on_error == []
