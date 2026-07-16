"""Demo-mode stand-ins for Simod + Prosimos so the UI is usable offline."""

from __future__ import annotations
import random
import threading
from dataclasses import dataclass
from pathlib import Path
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
    COL_MEDIAN_CYCLE_H,
    COL_MEAN_COST,
    COL_TOTAL_CYCLE_S,
    COL_TOTAL_COST,
    COL_TOTAL_REWORK_COUNT,
    COL_REWORK_RATE,
    COL_TOTAL_BOT_FAILURE_COUNT,
    COL_TOTAL_CYCLE_S_MEAN,
    COL_MEDIAN_CYCLE_H_MEAN,
    COL_TOTAL_COST_MEAN,
    COL_REWORK_RATE_MEAN,
)
from .orchestrator import ExperimentCancelledError, ExperimentResult


# Pre-baked demo discovery: a real Simod output (synthetic LoanApp benchmark) so
# demo mode reuses the real activity-list + factor-prepopulation path. See
# demo/README.md for provenance.
_DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"
DEMO_BPMN = _DEMO_DIR / "model.bpmn"
DEMO_JSON = _DEMO_DIR / "params.json"

BASELINE_CYCLE_H = 31.2
# Below the mean — cycle-time distributions are right-skewed (a few long cases
# pull the mean up), so the synthetic median sits below the mean.
BASELINE_MEDIAN_CYCLE_H = 28.0
BASELINE_COST = 48.0
BASELINE_REWORK_RATE = 5.0  # percentage (0–100), matches COL_REWORK_RATE storage unit


@dataclass
class _SimResult:
    mean_cycle_h: float
    median_cycle_h: float
    mean_cost: float
    total_cycle_s: float
    total_cost: float
    total_rework_count: float
    rework_rate: float
    total_bot_failure_count: float


def demo_baseline_agg() -> dict[int, dict]:
    """Synthetic baseline_agg for goal target computation in demo mode.

    Matches the shape produced by orchestrator.run_experiment() so
    app.py can always call baseline_per_case() regardless of mode.
    n=1 is used as the reference key so the division in baseline_per_case() cancels cleanly.
    """
    return {
        1: {
            COL_TOTAL_CYCLE_S_MEAN: BASELINE_CYCLE_H * 3600,
            COL_MEDIAN_CYCLE_H_MEAN: BASELINE_MEDIAN_CYCLE_H,
            COL_TOTAL_COST_MEAN: BASELINE_COST,
            COL_REWORK_RATE_MEAN: BASELINE_REWORK_RATE,
        }
    }


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
    # Expected fraction of cases the bot attempts but fails (redirected to a human).
    bot_failure_fraction = (pct_auto / 100) * (1 - pct_ok / 100)
    # Expected fraction of cases still handled by a human: direct manual path + bot failures.
    expected_human_fraction = (1 - pct_auto / 100) + bot_failure_fraction
    human_cost = BASELINE_COST * expected_human_fraction * rng.uniform(0.9, 1.1)
    bot_cost_per_case = (pct_auto / 100) * (t_auto / 3600) * bot_cost_per_hour
    cost = human_cost + bot_cost_per_case
    # Rework is repeated-activity work by humans, so it scales with the full
    # human-touched fraction (direct path + failed-bot redos) — mirroring the
    # cost model. Bot failures themselves are a separate metric, not rework.
    rework_rate = min(
        BASELINE_REWORK_RATE * expected_human_fraction * rng.uniform(0.9, 1.1),
        100.0,
    )
    bot_failure_count = bot_failure_fraction * n_cases * rng.uniform(0.9, 1.1)
    # Median tracks the mean's scenario dependence but sits ~10 % below it
    # (right-skew), with its own jitter. Drawn LAST so it does not shift the rng
    # sequence of the metrics above. Scoring-only second factor.
    median_ratio = BASELINE_MEDIAN_CYCLE_H / BASELINE_CYCLE_H
    median_cycle = cycle * median_ratio * rng.uniform(0.95, 1.05)

    return _SimResult(
        mean_cycle_h=round(cycle, 2),
        median_cycle_h=round(median_cycle, 2),
        mean_cost=round(cost, 2),
        total_cycle_s=round(cycle * 3600 * n_cases, 2),
        total_cost=round(cost * n_cases, 2),
        total_rework_count=round(rework_rate / 100 * n_cases, 2),
        rework_rate=round(rework_rate, 2),
        total_bot_failure_count=round(bot_failure_count, 2),
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
                    COL_MEDIAN_CYCLE_H: r.median_cycle_h,
                    COL_MEAN_COST: r.mean_cost,
                    COL_TOTAL_CYCLE_S: r.total_cycle_s,
                    COL_TOTAL_COST: r.total_cost,
                    COL_TOTAL_REWORK_COUNT: r.total_rework_count,
                    COL_REWORK_RATE: r.rework_rate,
                    COL_TOTAL_BOT_FAILURE_COUNT: r.total_bot_failure_count,
                    **s.values,
                }
            )
            done += 1
            if on_progress:
                on_progress(done, total, s.id, rep)

    return ExperimentResult(results=pd.DataFrame(rows))
