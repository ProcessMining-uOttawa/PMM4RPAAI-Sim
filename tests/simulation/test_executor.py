"""Tests for executor.run_all() — stop_check predicate, completion flag, and on_error callback."""

from __future__ import annotations

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
