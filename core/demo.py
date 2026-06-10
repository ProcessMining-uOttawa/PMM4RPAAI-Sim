"""Demo-mode stand-ins for Simod + Prosimos so the UI is usable offline."""
from __future__ import annotations
import random
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from .parameters import Scenario
from .constants import (
    COL_CYCLE_H, COL_COST, COL_TOTAL_CYCLE_S, COL_TOTAL_COST,
    COL_REWORK_COUNT, COL_REWORK_RATE,
)
from .orchestrator import ExperimentResult


DEMO_ACTIVITIES = [
    ("Receive application", 6),
    ("Validate claim", 42),
    ("Check credit", 18),
    ("Approve loan", 120),
    ("Notify customer", 3),
    ("Archive", 1),
]
BASELINE_CYCLE_H = 31.2
BASELINE_COST = 48.0
BASELINE_REWORK_RATE = 0.05


@dataclass
class _SimResult:
    scenario_id: str
    replication: int
    cycle_h: float
    cost: float
    total_cycle_s: float
    total_cost: float
    rework_count: float
    rework_rate: float


def fake_discovery() -> list[str]:
    return [name for name, _ in DEMO_ACTIVITIES]


def _fake_simulate(scenario: Scenario, replication: int) -> _SimResult:
    """Synthetic but monotonic: more automation → faster, cheaper, with noise."""
    rng = random.Random(hash((scenario.id, replication)) & 0xffffffff)

    def _v(suffix, default):
        return next((v for k, v in scenario.values.items() if k.endswith("." + suffix)), default)

    pct      = _v("pct_auto", 50)
    pct_ok   = _v("pct_ok", 90)
    t_auto   = _v("t_auto",   30)
    t_man    = _v("t_manual", 300)
    num_bots = int(_v("num_bots", 1))
    num_man  = int(_v("num_manual_resources", 1))
    n_cases  = int(_v("num_cases", 500))

    mean_task_s    = (pct/100)*t_auto + (1 - pct/100)*t_man
    bot_share      = pct / 100
    resource_scale = 1.0 / (bot_share * num_bots**0.5 + (1 - bot_share) * num_man**0.5)
    cycle = BASELINE_CYCLE_H * (mean_task_s / 300) * resource_scale * rng.uniform(0.9, 1.1)
    cost  = BASELINE_COST * (1 - 0.6*pct/100) * rng.uniform(0.9, 1.1)
    rework_rate = min(
        (pct/100 * (1 - pct_ok/100) + BASELINE_REWORK_RATE * (1 - pct/100))
        * rng.uniform(0.9, 1.1),
        1.0,
    )

    return _SimResult(
        scenario_id=scenario.id,
        replication=replication,
        cycle_h=round(cycle, 2),
        cost=round(cost, 2),
        total_cycle_s=round(cycle * 3600 * n_cases, 2),
        total_cost=round(cost * n_cases, 2),
        rework_count=round(rework_rate * n_cases, 2),
        rework_rate=round(rework_rate, 4),
    )


def run_experiment(
    scenarios: list[Scenario],
    n_reps: int,
    on_progress: Callable[[int, int, str, int], None] | None = None,
) -> ExperimentResult:
    """Synthetic stand-in for orchestrator.run_experiment — no Simod/Prosimos needed."""
    total = len(scenarios) * n_reps
    done  = 0
    rows: list[dict] = []

    for s in scenarios:
        for rep in range(n_reps):
            r = _fake_simulate(s, rep)
            rows.append({
                "scenario_id":     r.scenario_id,
                "replication":     r.replication,
                COL_CYCLE_H:       r.cycle_h,
                COL_COST:          r.cost,
                COL_TOTAL_CYCLE_S: r.total_cycle_s,
                COL_TOTAL_COST:    r.total_cost,
                COL_REWORK_COUNT:  r.rework_count,
                COL_REWORK_RATE:   r.rework_rate,
                **s.values,
            })
            done += 1
            if on_progress:
                on_progress(done, total, s.id, rep)

    return ExperimentResult(results=pd.DataFrame(rows))
