"""Tests for the simulation trust checker (core/simulation/validate.py).

Layer 1 trusts the checker via hand-authored reconciling triples + targeted
mutations. Layer 2 spends that trust on committed real-Prosimos goldens (a fix
and an expon arrival run), pinning the empirical reconciliation in CI with no
Prosimos needed at test time.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from core.simulation.validate import Severity, check_experiment, check_replication

FIXTURES = Path(__file__).parent / "fixtures"
_ALLDAY = [
    {"from": "MONDAY", "to": "SUNDAY", "beginTime": "00:00:00", "endTime": "24:00:00"}
]
_NINE_TO_FIVE = [
    {"from": "MONDAY", "to": "FRIDAY", "beginTime": "09:00:00", "endTime": "17:00:00"}
]

_LOG_COLUMNS = [
    "case_id",
    "activity",
    "enable_time",
    "start_time",
    "end_time",
    "resource",
]


def _write_log(path: Path, rows: list[tuple]) -> Path:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(_LOG_COLUMNS)
        w.writerows(rows)
    return path


def _write_params(
    path: Path, calendar=_ALLDAY, rate: float = 10.0, arrival_calendar=None
) -> Path:
    path.write_text(
        json.dumps(
            {
                "resource_calendars": [{"id": "cal", "time_periods": calendar}],
                "resource_profiles": [
                    {
                        "resource_list": [
                            {
                                "id": "R",
                                "name": "R",
                                "cost_per_hour": rate,
                                "calendar": "cal",
                            }
                        ]
                    }
                ],
                "arrival_time_calendar": arrival_calendar or calendar,
            }
        )
    )
    return path


def _write_stats(path: Path, tasks: list[tuple], kpis: list[tuple]) -> Path:
    """tasks: (name, cost, processing_s). kpis: (name, min, max, avg, accumulated, count)."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Individual Task Statistics"])
        w.writerow(["Name", "Total Cost", "Total Processing Time"])
        for name, cost, processing in tasks:
            w.writerow([name, str(cost), str(processing)])
        w.writerow([])
        w.writerow(["Overall Scenario Statistics"])
        w.writerow(
            ["KPI", "Min", "Max", "Average", "Accumulated Value", "Trace Ocurrences"]
        )
        for row in kpis:
            w.writerow([str(cell) for cell in row])
        w.writerow([])
    return path


# A reconciling triple: two 24/7 tasks (1 h + 2 h) at $10/hr, arrival == start.
#   cost 30, processing 10800 s, arrival cycle [3600, 7200] (total 10800), 2 cases.
_RECON_LOG = [
    (
        "c1",
        "A",
        "2025-01-06T08:00:00",
        "2025-01-06T08:00:00",
        "2025-01-06T09:00:00",
        "R",
    ),
    (
        "c2",
        "A",
        "2025-01-06T08:00:00",
        "2025-01-06T08:00:00",
        "2025-01-06T10:00:00",
        "R",
    ),
]
_RECON_TASKS = [("A", 30.0, 10800.0)]
_RECON_KPIS = [("idle_cycle_time", 3600.0, 7200.0, 5400.0, 10800.0, 2)]


def _triple(
    tmp_path,
    tasks=_RECON_TASKS,
    kpis=_RECON_KPIS,
    calendar=_ALLDAY,
    arrival_calendar=None,
):
    log = _write_log(tmp_path / "log.csv", _RECON_LOG)
    params = _write_params(
        tmp_path / "params.json", calendar, arrival_calendar=arrival_calendar
    )
    stats = _write_stats(tmp_path / "stats.csv", tasks, kpis)
    return log, params, stats


def _by_label(checks, prefix):
    return next(c for c in checks if c.label.startswith(prefix))


# ── Layer 1: trust the checker ─────────────────────────────────────────────────


class TestReconcilingTriple:
    def test_all_checks_ok(self, tmp_path):
        checks = check_replication(*_triple(tmp_path))
        assert all(c.ok for c in checks), [c.label for c in checks if not c.ok]

    def test_cost_check_is_error_severity(self, tmp_path):
        assert (
            _by_label(check_replication(*_triple(tmp_path)), "total cost").severity
            is Severity.ERROR
        )

    def test_per_task_processing_is_warning(self, tmp_path):
        assert (
            _by_label(
                check_replication(*_triple(tmp_path)), "processing seconds ["
            ).severity
            is Severity.WARNING
        )


class TestMutations:
    def test_wrong_cost_fails(self, tmp_path):
        checks = check_replication(*_triple(tmp_path, tasks=[("A", 999.0, 10800.0)]))
        cost = _by_label(checks, "total cost")
        assert not cost.ok and cost.severity is Severity.ERROR

    def test_wrong_processing_fails(self, tmp_path):
        # Processing seconds is a distinct ERROR oracle (stats Total Processing
        # Time), not the cost column -- flip it, keep cost right, so the cost
        # check stays ok and only the processing check catches the mismatch.
        checks = check_replication(*_triple(tmp_path, tasks=[("A", 30.0, 99999.0)]))
        proc = _by_label(checks, "total processing seconds")
        assert not proc.ok and proc.severity is Severity.ERROR

    def test_cost_within_tolerance_passes(self, tmp_path):
        # 30.0 → 30.1: inside max(1.0, 0.5%·30) = 1.0 floor.
        assert _by_label(
            check_replication(*_triple(tmp_path, tasks=[("A", 30.1, 10800.0)])),
            "total cost",
        ).ok

    def test_case_count_mismatch_fails(self, tmp_path):
        kpis = [("idle_cycle_time", 3600.0, 7200.0, 5400.0, 10800.0, 3)]  # 3 ≠ 2 cases
        count = _by_label(
            check_replication(*_triple(tmp_path, kpis=kpis)), "case count"
        )
        assert not count.ok and count.severity is Severity.ERROR

    def test_arrival_total_mismatch_fails(self, tmp_path):
        kpis = [("idle_cycle_time", 3600.0, 7200.0, 5400.0, 99999.0, 2)]
        assert not _by_label(
            check_replication(*_triple(tmp_path, kpis=kpis)), "arrival cycle total"
        ).ok

    def test_arrival_outside_window_warns_not_errors(self, tmp_path):
        # Resources stay 24/7 (cost reconciles) but the arrival calendar is 9-5, so
        # the 08:00 arrivals fall outside it → WARNING only, no ERROR.
        checks = check_replication(*_triple(tmp_path, arrival_calendar=_NINE_TO_FIVE))
        window = _by_label(checks, "arrivals inside arrival window")
        assert not window.ok and window.severity is Severity.WARNING
        assert window.ours == 2.0  # both case arrivals outside a window
        # The report still passes — no ERROR check failed.
        assert all(c.ok for c in checks if c.severity is Severity.ERROR)


# ── Layer 2: real-Prosimos goldens ─────────────────────────────────────────────


@pytest.mark.parametrize("golden", ["golden_fix", "golden_expon"])
def test_golden_reconciles(golden):
    d = FIXTURES / golden
    checks = check_replication(d / "log.csv", d / "params.json", d / "stats.csv")
    failed = [c.label for c in checks if not c.ok and c.severity is Severity.ERROR]
    assert not failed, failed
    # Real flag-on arrivals all land in the arrival window (distribution-independent).
    assert _by_label(checks, "arrivals inside arrival window").ours == 0.0


# ── Experiment-dir walk ────────────────────────────────────────────────────────


def test_check_experiment_reconciles(tmp_path):
    # check_experiment walks store's runs/<exp>/ layout (scenarios + baseline) and
    # wraps each replication in a ReplicationReport. Reconciling triples in both a
    # scenario and the baseline -> every report ok, both names present.
    exp = tmp_path / "exp"
    for base in (exp / "scenarios" / "s1", exp / "baseline"):
        base.mkdir(parents=True)
        _write_log(base / "rep_001_log.csv", _RECON_LOG)
        _write_params(base / "params.json")
        _write_stats(base / "rep_001_stats.csv", _RECON_TASKS, _RECON_KPIS)

    reports = check_experiment(exp)
    assert {r.name for r in reports} == {"s1/rep_001_log", "baseline/rep_001_log"}
    assert all(r.ok for r in reports), [r.name for r in reports if not r.ok]
