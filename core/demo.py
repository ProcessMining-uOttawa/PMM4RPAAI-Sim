"""Demo-mode stand-ins for Simod + Prosimos so the UI is usable offline."""

from __future__ import annotations
import random
import threading
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from .parameters import Scenario
from .constants import (
    F_PCT_AUTO,
    F_PCT_OK,
    F_T_AUTO,
    F_T_MANUAL,
    F_NUM_BOTS,
    F_NUM_MANUAL_RESOURCES,
    F_NUM_CASES,
)
from .constants import (
    COL_MEAN_CYCLE_H,
    COL_MEAN_COST,
    COL_TOTAL_CYCLE_S,
    COL_TOTAL_COST,
    COL_TOTAL_REWORK_COUNT,
    COL_REWORK_RATE,
    COL_TOTAL_CYCLE_S_MEAN,
    COL_TOTAL_COST_MEAN,
    COL_REWORK_RATE_MEAN,
)
from .orchestrator import ExperimentCancelledError, ExperimentResult


DEMO_ACTIVITIES = [
    "Receive application",
    "Validate claim",
    "Check credit",
    "Approve loan",
    "Notify customer",
    "Archive",
]
BASELINE_CYCLE_H = 31.2
BASELINE_COST = 48.0
BASELINE_REWORK_RATE = 5.0  # percentage (0–100), matches COL_REWORK_RATE storage unit


@dataclass
class _SimResult:
    mean_cycle_h: float
    mean_cost: float
    total_cycle_s: float
    total_cost: float
    total_rework_count: float
    rework_rate: float


def demo_baseline_agg() -> dict[int, dict]:
    """Synthetic baseline_agg for goal target computation in demo mode.

    Matches the shape produced by orchestrator.run_experiment() so
    app.py can always call baseline_per_case() regardless of mode.
    n=1 is used as the reference key so the division in baseline_per_case() cancels cleanly.
    """
    return {
        1: {
            COL_TOTAL_CYCLE_S_MEAN: BASELINE_CYCLE_H * 3600,
            COL_TOTAL_COST_MEAN: BASELINE_COST,
            COL_REWORK_RATE_MEAN: BASELINE_REWORK_RATE,
        }
    }


def fake_discovery() -> list[str]:
    return list(DEMO_ACTIVITIES)


def _fake_simulate(
    scenario: Scenario, replication: int, bot_cost_per_hour: float = 0.0
) -> _SimResult:
    """Synthetic but monotonic: more automation → faster, cheaper, with noise."""
    rng = random.Random(hash((scenario.id, replication)) & 0xFFFFFFFF)

    pct_auto = scenario.values[F_PCT_AUTO]
    pct_ok = scenario.values[F_PCT_OK]
    t_auto = scenario.values[F_T_AUTO]
    t_man = scenario.values[F_T_MANUAL]
    num_bots = int(scenario.values[F_NUM_BOTS])
    num_man = int(scenario.values[F_NUM_MANUAL_RESOURCES])
    n_cases = int(scenario.values[F_NUM_CASES])

    mean_task_s = (pct_auto / 100) * t_auto + (1 - pct_auto / 100) * t_man
    # Synthetic stand-in for Prosimos's resource scheduling: more resources reduce
    # cycle time with diminishing returns (sqrt). No counterpart in the real pipeline —
    # the actual effect emerges from event-log timestamps produced by the simulator.
    effective_resources = (pct_auto / 100) * num_bots + (1 - pct_auto / 100) * num_man
    resource_scale = 1.0 / effective_resources**0.5
    cycle = (
        BASELINE_CYCLE_H
        * (mean_task_s / t_man)
        * resource_scale
        * rng.uniform(0.9, 1.1)
    )
    # Expected fraction of cases still handled by a human: direct manual path + bot failures.
    expected_human_fraction = (1 - pct_auto / 100) + (pct_auto / 100) * (
        1 - pct_ok / 100
    )
    human_cost = BASELINE_COST * expected_human_fraction * rng.uniform(0.9, 1.1)
    bot_cost_per_case = (pct_auto / 100) * (t_auto / 3600) * bot_cost_per_hour
    cost = human_cost + bot_cost_per_case
    rework_rate = min(
        (
            pct_auto / 100 * (1 - pct_ok / 100)
            + BASELINE_REWORK_RATE / 100 * (1 - pct_auto / 100)
        )
        * 100.0
        * rng.uniform(0.9, 1.1),
        100.0,
    )

    return _SimResult(
        mean_cycle_h=round(cycle, 2),
        mean_cost=round(cost, 2),
        total_cycle_s=round(cycle * 3600 * n_cases, 2),
        total_cost=round(cost * n_cases, 2),
        total_rework_count=round(rework_rate / 100 * n_cases, 2),
        rework_rate=round(rework_rate, 2),
    )


def run_experiment(
    scenarios: list[Scenario],
    n_reps: int,
    on_progress: Callable[[int, int, str, int], None] | None = None,
    bot_cost_per_hour: float = 0.0,
    stop_event: threading.Event | None = None,
) -> ExperimentResult:
    """Synthetic stand-in for orchestrator.run_experiment — no Simod/Prosimos needed."""
    total = len(scenarios) * n_reps
    done = 0
    rows: list[dict] = []

    for s in scenarios:
        for rep in range(n_reps):
            if stop_event is not None and stop_event.is_set():
                raise ExperimentCancelledError()
            r = _fake_simulate(s, rep, bot_cost_per_hour)
            rows.append(
                {
                    "scenario_id": s.id,
                    "replication": rep,
                    COL_MEAN_CYCLE_H: r.mean_cycle_h,
                    COL_MEAN_COST: r.mean_cost,
                    COL_TOTAL_CYCLE_S: r.total_cycle_s,
                    COL_TOTAL_COST: r.total_cost,
                    COL_TOTAL_REWORK_COUNT: r.total_rework_count,
                    COL_REWORK_RATE: r.rework_rate,
                    **s.values,
                }
            )
            done += 1
            if on_progress:
                on_progress(done, total, s.id, rep)

    return ExperimentResult(results=pd.DataFrame(rows))
