"""Tests for the on-disk experiment store layout (core/simulation/store.py).

Covers iter_replication_triples -- the folder walk the trust checker relies on
to enumerate every replication without re-encoding the runs/<exp>/ layout --
and validation_report, the transform-verification serializer.
"""

from __future__ import annotations

from pathlib import Path

from core.bpmn.validate import Severity, VerificationResult, Violation
from core.simulation import store


def _touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _replication(base: Path, rep: int, *, stats: bool = True) -> None:
    """Write a rep_NNN_log.csv, and its _stats.csv sibling unless stats=False."""
    _touch(base / f"rep_{rep:03d}_log.csv")
    if stats:
        _touch(base / f"rep_{rep:03d}_stats.csv")


class TestIterReplicationTriples:
    def test_yields_scenarios_then_baseline_in_order(self, tmp_path):
        exp = tmp_path / "exp"
        for sid in ("s1", "s2"):
            _touch(exp / "scenarios" / sid / "params.json")
            _replication(exp / "scenarios" / sid, 1)
        _replication(exp / "scenarios" / "s1", 2)
        _touch(exp / "baseline" / "params.json")
        _replication(exp / "baseline", 1)

        names = [name for name, *_ in store.iter_replication_triples(exp)]
        assert names == [
            "s1/rep_001_log",
            "s1/rep_002_log",
            "s2/rep_001_log",
            "baseline/rep_001_log",
        ]

    def test_stats_path_is_the_log_sibling(self, tmp_path):
        # The _log.csv -> _stats.csv rewrite and the once-per-scenario params.
        exp = tmp_path / "exp"
        _touch(exp / "scenarios" / "s1" / "params.json")
        _replication(exp / "scenarios" / "s1", 1)

        _name, log, params, stats = next(iter(store.iter_replication_triples(exp)))
        assert log.name == "rep_001_log.csv"
        assert stats.name == "rep_001_stats.csv"
        assert stats.parent == log.parent
        assert params.name == "params.json"

    def test_replication_missing_stats_is_skipped(self, tmp_path):
        exp = tmp_path / "exp"
        _touch(exp / "scenarios" / "s1" / "params.json")
        _replication(exp / "scenarios" / "s1", 1, stats=False)  # log, no stats

        assert list(store.iter_replication_triples(exp)) == []

    def test_scenario_missing_params_is_skipped(self, tmp_path):
        exp = tmp_path / "exp"
        _replication(exp / "scenarios" / "s1", 1)  # log + stats, no params.json

        assert list(store.iter_replication_triples(exp)) == []

    def test_empty_experiment_yields_nothing(self, tmp_path):
        assert list(store.iter_replication_triples(tmp_path / "exp")) == []


class TestValidationReport:
    def test_writes_one_line_per_violation(self, tmp_path):
        result = VerificationResult(
            target_activity="Fix Bug",
            violations=(
                Violation(
                    "MISSING_GATEWAY",
                    Severity.ERROR,
                    "no split gateway before task",
                    element_id="gw1",
                ),
                Violation("IO_LIST_DRIFT", Severity.WARNING, "incoming list drift"),
            ),
        )
        path = store.validation_report(tmp_path / "exp", result)

        assert path == tmp_path / "exp" / "validation.log"
        assert path.read_text(encoding="utf-8").splitlines() == [
            "ERROR MISSING_GATEWAY: no split gateway before task [element: gw1]",
            "WARNING IO_LIST_DRIFT: incoming list drift",
        ]

    def test_empty_result_writes_empty_file(self, tmp_path):
        result = VerificationResult(target_activity="Fix Bug", violations=())
        path = store.validation_report(tmp_path / "exp", result)
        assert path.read_text(encoding="utf-8") == ""
