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
)
from .constants import (
    COL_MEAN_CYCLE_H,
    COL_MEDIAN_CYCLE_H,
    COL_MIN_CYCLE_H,
    COL_MAX_CYCLE_H,
    COL_MEAN_COST,
    COL_TOTAL_CYCLE_S,
    COL_TOTAL_COST,
    COL_TOTAL_REWORK_COUNT,
    COL_REWORK_RATE,
    COL_MEAN_REWORK_COUNT,
    COL_TOTAL_BOT_FAILURE_COUNT,
    COL_MEAN_CYCLE_H_MEAN,
    COL_MEDIAN_CYCLE_H_MEAN,
    COL_MIN_CYCLE_H_MEAN,
    COL_MAX_CYCLE_H_MEAN,
    COL_MEAN_COST_MEAN,
    COL_REWORK_RATE_MEAN,
    COL_MEAN_REWORK_COUNT_MEAN,
)
from .orchestrator import ExperimentCancelledError, ExperimentResult


# Pre-baked demo discovery: a real Simod output (synthetic LoanApp benchmark) so
# demo mode reuses the real activity-list + factor-prepopulation path. See
# demo/README.md for provenance.
_DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"
DEMO_BPMN = _DEMO_DIR / "model.bpmn"
DEMO_JSON = _DEMO_DIR / "params.json"

BASELINE_CYCLE_H = 31.2
# Cycle-time distributions are right-skewed (a few long cases pull the mean up),
# so the synthetic order statistics straddle the mean: min < median < mean < max.
BASELINE_MEDIAN_CYCLE_H = 28.0
BASELINE_MIN_CYCLE_H = 12.0
BASELINE_MAX_CYCLE_H = 70.0
BASELINE_COST = 48.0
BASELINE_REWORK_RATE = 5.0  # percentage (0–100), matches COL_REWORK_RATE storage unit


@dataclass
class _SimResult:
    mean_cycle_h: float
    median_cycle_h: float
    min_cycle_h: float
    max_cycle_h: float
    mean_cost: float
    total_cycle_s: float
    total_cost: float
    total_rework_count: float
    rework_rate: float
    mean_rework_count: float
    total_bot_failure_count: float


def demo_baseline_agg() -> dict[str, float]:
    """Synthetic baseline_agg for goal target computation in demo mode.

    A flat record carrying every per-case indicator key baseline_per_case()
    picks, so app.py can always call it regardless of mode. Kept an explicit
    literal (not a registry comprehension) so the named-constant mapping stays
    readable; baseline_per_case KeyErrors loudly if it ever drifts.
    """
    return {
        COL_MEAN_CYCLE_H_MEAN: BASELINE_CYCLE_H,
        COL_MEDIAN_CYCLE_H_MEAN: BASELINE_MEDIAN_CYCLE_H,
        COL_MIN_CYCLE_H_MEAN: BASELINE_MIN_CYCLE_H,
        COL_MAX_CYCLE_H_MEAN: BASELINE_MAX_CYCLE_H,
        COL_MEAN_COST_MEAN: BASELINE_COST,
        COL_REWORK_RATE_MEAN: BASELINE_REWORK_RATE,
        # Mean rework count per case = rate/100 in the demo's simple rework model
        # (matches _fake_simulate's derived value and the total = mean × n identity).
        COL_MEAN_REWORK_COUNT_MEAN: BASELINE_REWORK_RATE / 100,
    }


def _fake_simulate(
    scenario: Scenario,
    replication: int,
    n_cases: int,
    bot_cost_per_hour: float = 0.0,
) -> _SimResult:
    """Synthetic but monotonic: more automation → faster, cheaper, with noise."""
    rng = random.Random(hash((scenario.id, replication)) & 0xFFFFFFFF)

    pct_auto = scenario.values[F_PCT_AUTO]
    pct_ok = scenario.values[F_PCT_OK]
    t_auto = scenario.values[F_T_AUTO]
    t_man = scenario.values[F_T_MANUAL]
    num_bots = int(scenario.values[F_NUM_BOTS])
    num_man = int(scenario.values[F_NUM_MANUAL_RESOURCES])

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
    # The cycle-time order statistics are scoring-only indicators. Median tracks
    # the mean's scenario dependence but sits ~10 % below it (right-skew); min and
    # max straddle it so min < median < mean < max holds for every draw. Drawn
    # AFTER the metrics above so appending them never shifts their rng sequence.
    median_ratio = BASELINE_MEDIAN_CYCLE_H / BASELINE_CYCLE_H
    median_cycle = cycle * median_ratio * rng.uniform(0.95, 1.05)
    min_cycle = median_cycle * rng.uniform(0.35, 0.5)
    max_cycle = cycle * rng.uniform(1.8, 2.6)

    return _SimResult(
        mean_cycle_h=round(cycle, 2),
        median_cycle_h=round(median_cycle, 2),
        min_cycle_h=round(min_cycle, 2),
        max_cycle_h=round(max_cycle, 2),
        mean_cost=round(cost, 2),
        total_cycle_s=round(cycle * 3600 * n_cases, 2),
        total_cost=round(cost * n_cases, 2),
        total_rework_count=round(rework_rate / 100 * n_cases, 2),
        rework_rate=round(rework_rate, 2),
        # Derived (not drawn): the per-case average of excess occurrences equals
        # total_rework_count / n_cases = rework_rate/100 in this rate-only model.
        mean_rework_count=round(rework_rate / 100, 4),
        total_bot_failure_count=round(bot_failure_count, 2),
    )


def run_experiment(
    scenarios: list[Scenario],
    n_reps: int,
    n_cases: int,
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
            r = _fake_simulate(s, rep, n_cases, bot_cost_per_hour)
            rows.append(
                {
                    "scenario_id": s.id,
                    "replication": rep,
                    COL_MEAN_CYCLE_H: r.mean_cycle_h,
                    COL_MEDIAN_CYCLE_H: r.median_cycle_h,
                    COL_MIN_CYCLE_H: r.min_cycle_h,
                    COL_MAX_CYCLE_H: r.max_cycle_h,
                    COL_MEAN_COST: r.mean_cost,
                    COL_TOTAL_CYCLE_S: r.total_cycle_s,
                    COL_TOTAL_COST: r.total_cost,
                    COL_TOTAL_REWORK_COUNT: r.total_rework_count,
                    COL_REWORK_RATE: r.rework_rate,
                    COL_MEAN_REWORK_COUNT: r.mean_rework_count,
                    COL_TOTAL_BOT_FAILURE_COUNT: r.total_bot_failure_count,
                    **s.values,
                }
            )
            done += 1
            if on_progress:
                on_progress(done, total, s.id, rep)

    return ExperimentResult(results=pd.DataFrame(rows), n_cases=n_cases)
