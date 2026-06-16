"""Tests for pool.run_all() — stop_check predicate and completion flag."""
from __future__ import annotations

import pytest

from core.simulation import pool, runner


def _tasks(tmp_path, n: int) -> list[pool.SimulationTask]:
    return [
        pool.SimulationTask(
            bpmn_path=tmp_path / f"{i}.bpmn",
            json_path=tmp_path / f"{i}.json",
            n_cases=1,
            out_log=tmp_path / f"{i}_log.csv",
            out_stat=None,
            proc_log=None,
        )
        for i in range(n)
    ]


class TestRunAllStopCheck:

    def test_returns_true_without_stop_check(self, monkeypatch, tmp_path):
        monkeypatch.setattr(runner, "simulate", lambda *a, **kw: None)
        completed = pool.run_all(_tasks(tmp_path, 3), lambda t: None)
        assert completed is True

    def test_returns_true_when_stop_check_always_false(self, monkeypatch, tmp_path):
        monkeypatch.setattr(runner, "simulate", lambda *a, **kw: None)
        completed = pool.run_all(
            _tasks(tmp_path, 3), lambda t: None, stop_check=lambda: False
        )
        assert completed is True

    def test_returns_false_when_stop_check_fires(self, monkeypatch, tmp_path):
        monkeypatch.setattr(runner, "simulate", lambda *a, **kw: None)
        completed = pool.run_all(
            _tasks(tmp_path, 5), lambda t: None, stop_check=lambda: True
        )
        assert completed is False

    def test_on_complete_not_called_after_stop(self, monkeypatch, tmp_path):
        monkeypatch.setattr(runner, "simulate", lambda *a, **kw: None)
        completed_tasks: list = []
        pool.run_all(
            _tasks(tmp_path, 5),
            lambda t: completed_tasks.append(t),
            stop_check=lambda: True,
        )
        assert len(completed_tasks) == 0

    def test_on_complete_called_for_all_tasks_without_stop_check(self, monkeypatch, tmp_path):
        monkeypatch.setattr(runner, "simulate", lambda *a, **kw: None)
        completed_tasks: list = []
        pool.run_all(_tasks(tmp_path, 4), lambda t: completed_tasks.append(t))
        assert len(completed_tasks) == 4
