"""Trust checker — cross-check our log-derived metrics against Prosimos's stats CSV.

Unlike ``core/bpmn/validate.py`` (which re-encodes the transform's expectations
because both sides of *its* comparison are our own code), this checker's oracle
is Prosimos's OWN stats CSV: a foreign codebase's internal accounting, derived
from state our code never touches (the sampled task durations). So the checker
deliberately IMPORTS the product engine — ``replication_metrics`` and
``calendars.event_costs`` — rather than re-deriving cost/cycle: a re-
implementation would verify a sibling, not the product. Independence lives in
the oracle side, not in code duplication.

Maintainer tool — run it, don't wire it into the app:

    python -m core.simulation.validate <experiment-dir>
    python -m core.simulation.validate --log L.csv --params P.json --stats S.csv

Checks per replication (ERROR = a real disagreement; WARNING = a diagnostic):
total cost, total working seconds (+ per task), and the case count. The cycle-time dimension is UNCHECKED: Prosimos reports only
arrival-anchored cycle KPIs (cycle_time / idle_cycle_time), and our clock is the
first-task-start → last-task-end case duration, which matches neither — no
oracle exists. The cost and working-seconds reconciliations anchor the same
start/end columns the cycle reads, and the exact case count doubles as a
vanished-case detector (a case completing with zero task rows would disappear
from the log entirely). Rework / bot-failure likewise have no stats-CSV oracle
and are noted, not checked.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import pandas as pd

from . import store
from .prosimos import calendars
from .prosimos.replication_metrics import (
    overall_kpis,
    replication_metrics,
    task_totals,
)

_REL_TOLERANCE = 0.005  # 0.5% — the engine reconciles exactly; this is float slack


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Check:
    """One oracle comparison. ``ours``/``oracle`` are None for a not-checkable case.

    ``label`` doubles as the stable key tests bind to (the labels are terse and
    identifier-like), so reword with care.
    """

    label: str
    severity: Severity
    ours: float | None
    oracle: float | None
    tolerance: float

    @property
    def skipped(self) -> bool:
        return self.ours is None or self.oracle is None

    @property
    def ok(self) -> bool:
        # Inlined (not `if self.skipped`) so mypy narrows ours/oracle to non-None.
        if self.ours is None or self.oracle is None:  # not-checkable → not a failure
            return True
        return abs(self.ours - self.oracle) <= self.tolerance


@dataclass
class ReplicationReport:
    name: str
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when no ERROR-severity check failed (warnings don't gate)."""
        return all(c.ok for c in self.checks if c.severity is Severity.ERROR)


def _tolerance(oracle: float, floor: float) -> float:
    return max(floor, abs(oracle) * _REL_TOLERANCE)


def check_replication(log_csv: Path, params_json: Path, stats_csv: Path) -> list[Check]:
    """Compare the metrics we derive from (log, params) against the stats CSV."""
    event_log = pd.read_csv(log_csv, parse_dates=["start_time", "end_time"])
    params = json.loads(Path(params_json).read_text())

    # replication_metrics also rejects a flag-on log with its named error —
    # keep it before event_costs sees the unfiltered frame, whose unknown-
    # resource raise would be misleading for that case.
    metrics = replication_metrics(log_csv, params_json)
    costs = calendars.event_costs(event_log, params)
    tasks = task_totals(stats_csv)
    kpis = overall_kpis(stats_csv)

    checks: list[Check] = []

    # 1 — total cost (the product's own number vs the summed stats task cost).
    oracle_cost = sum(task["cost"] for task in tasks.values())
    checks.append(
        Check(
            "total cost",
            Severity.ERROR,
            metrics.total_cost,
            oracle_cost,
            _tolerance(oracle_cost, floor=1.0),
        )
    )

    # 2 — total working seconds, the rate-free twin of check 1 (isolates a
    #     calendar-engine bug from a rate-join bug). Then per task (WARNING: a
    #     single boundary-noise event on a 2-event task blows a relative band).
    ours_processing = float(costs["work_s"].sum())
    oracle_processing = sum(task["processing_s"] for task in tasks.values())
    checks.append(
        Check(
            "total processing seconds",
            Severity.ERROR,
            ours_processing,
            oracle_processing,
            _tolerance(oracle_processing, floor=300.0),
        )
    )
    ours_by_activity = costs["work_s"].groupby(event_log["activity"]).sum()
    for activity, oracle_task in tasks.items():
        checks.append(
            Check(
                f"processing seconds [{activity}]",
                Severity.WARNING,
                float(ours_by_activity.get(activity, 0.0)),
                oracle_task["processing_s"],
                _tolerance(oracle_task["processing_s"], floor=60.0),
            )
        )

    # 3 — case count (exact).
    oracle_count = next(iter(kpis.values()))["count"] if kpis else None
    checks.append(
        Check(
            "case count",
            Severity.ERROR,
            float(event_log["case_id"].nunique()),
            oracle_count,
            0.0,
        )
    )
    return checks


# ── Experiment-dir walk ────────────────────────────────────────────────────────


def check_experiment(exp_dir: Path) -> list[ReplicationReport]:
    # store owns the runs/<exp>/ layout; it enumerates its own triples.
    return [
        ReplicationReport(name, check_replication(log, params, stats))
        for name, log, params, stats in store.iter_replication_triples(exp_dir)
    ]


# ── CLI ─────────────────────────────────────────────────────────────────────


def _print_report(report: ReplicationReport) -> None:
    print(f"\n{report.name}: {'OK' if report.ok else 'FAIL'}")
    for check in report.checks:
        if check.skipped:
            verdict = "skip"
        elif check.ok:
            verdict = "OK" if check.severity is Severity.ERROR else "ok"
        else:
            verdict = "FAIL" if check.severity is Severity.ERROR else "warn"
        detail = ""
        if not check.skipped:
            assert check.ours is not None and check.oracle is not None
            detail = (
                f": ours={check.ours:.4f} oracle={check.oracle:.4f} "
                f"(tol ±{check.tolerance:.4f})"
            )
        print(f"  [{verdict:4s}] {check.label}{detail}")


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m core.simulation.validate",
        description="Cross-check log-derived metrics against Prosimos's stats CSV.",
    )
    parser.add_argument(
        "exp_dir", type=Path, nargs="?", help="An experiment dir under runs/."
    )
    parser.add_argument("--log", type=Path, help="Event-log CSV (single-triple mode).")
    parser.add_argument("--params", type=Path, help="Params JSON (single-triple mode).")
    parser.add_argument("--stats", type=Path, help="Stats CSV (single-triple mode).")
    args = parser.parse_args(argv)

    if args.log or args.params or args.stats:
        if not (args.log and args.params and args.stats):
            parser.error("--log, --params and --stats must be given together")
        reports = [
            ReplicationReport(
                "triple", check_replication(args.log, args.params, args.stats)
            )
        ]
    elif args.exp_dir is not None:
        reports = check_experiment(args.exp_dir)
        if not reports:
            parser.error(
                f"no (log, params, stats) replications found under {args.exp_dir}"
            )
    else:
        parser.error("give an experiment dir, or --log/--params/--stats")

    for report in reports:
        _print_report(report)
    failed = [r for r in reports if not r.ok]
    print(f"\n{len(reports) - len(failed)}/{len(reports)} replications OK.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_cli())
