"""Tests for orchestrator pieces that need no subprocess.

The run loops themselves require Simod/Prosimos and stay outside the unit
suite (the documented coverage-floor exclusion); what is unit-testable is the
pure logic around them — pre-flight guards and the module-level failure
helpers both loops share.
"""

from __future__ import annotations

import csv
from pathlib import Path
from subprocess import CalledProcessError

import pytest

from core.orchestrator import (
    FailedReplication,
    SimulationError,
    _log_tail,
    _raise_if_all_failed,
    run_as_discovered,
)


def _write_activity_log(path: Path, n_cases: int) -> Path:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["case_id", "activity", "enable_time", "start_time", "end_time", "resource"]
        )
        for i in range(n_cases):
            writer.writerow(
                [
                    f"c{i}",
                    "A",
                    "2025-01-06T08:00:00",
                    "2025-01-06T08:00:00",
                    "2025-01-06T09:00:00",
                    "R",
                ]
            )
    return path


class TestRunAsDiscoveredFidelityGuard:
    def test_n_mismatch_raises_before_any_write(self, tmp_path):
        # The equal-n invariant lives in core (min/max are sample-size-
        # dependent statistics): a mismatch fails before the run dir or any
        # model/params copy exists — the UI's pinned widget is courtesy only.
        log = _write_activity_log(tmp_path / "log.csv", n_cases=2)
        exp = tmp_path / "exp"
        with pytest.raises(ValueError, match="case count"):
            run_as_discovered(
                bpmn_path=tmp_path / "model.bpmn",  # never read — the raise comes first
                json_path=tmp_path / "params.json",
                n_reps=1,
                n_cases=999,
                experiment_dir=exp,
                log_csv=log,
            )
        assert not exp.exists()


class TestLogTail:
    def test_called_process_error_carries_its_output(self):
        exc = CalledProcessError(1, ["prosimos"], output="the captured tail")
        assert _log_tail(exc) == "the captured tail"

    def test_other_exceptions_carry_none(self):
        assert _log_tail(ValueError("boom")) is None


class TestRaiseIfAllFailed:
    def test_all_failed_raises_with_count_and_first_tail(self):
        failures = [
            FailedReplication("as_discovered", 0, "first boom", log_tail="tail 0"),
            FailedReplication("as_discovered", 1, "second boom"),
        ]
        with pytest.raises(
            SimulationError, match="All 2 .* First error: first boom"
        ) as exc_info:
            _raise_if_all_failed([], failures)
        assert exc_info.value.log_tail == "tail 0"

    def test_partial_success_is_silent(self):
        _raise_if_all_failed(
            [{"scenario_id": "S01"}], [FailedReplication("S01", 1, "boom")]
        )

    def test_no_rows_and_no_failures_is_silent(self):
        # An empty run is not an all-failed run — the raise needs failures.
        _raise_if_all_failed([], [])
