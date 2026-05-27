"""Demo-mode stand-ins for Simod + Prosimos so the UI is usable offline."""
from __future__ import annotations
import random
from dataclasses import dataclass
from .parameters import Scenario


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


@dataclass
class DemoResult:
    scenario_id: str
    replication: int
    cycle_h: float
    cost: float


def fake_discovery():
    return [name for name, _ in DEMO_ACTIVITIES]


def fake_simulate(scenario: Scenario, replication: int, n_cases: int) -> DemoResult:
    """Synthetic but monotonic: more automation → faster, cheaper, with noise."""
    rng = random.Random(hash((scenario.id, replication)) & 0xffffffff)

    def _v(suffix, default):
        return next((v for k, v in scenario.values.items() if k.endswith("." + suffix)), default)

    pct      = _v("pct_auto", 50)
    t_auto   = _v("t_auto",   30)
    t_man    = _v("t_manual", 300)
    num_bots = int(_v("num_bots", 1))
    num_man  = int(_v("num_manual_resources", 1))
    # weighted task time drives cycle; automation cuts cost
    mean_task_s = (pct/100)*t_auto + (1-pct/100)*t_man
    # sqrt scaling approximates diminishing queuing gains from larger resource pools;
    # normalises to 1.0 when both pool sizes are 1
    bot_share      = pct / 100
    resource_scale = 1.0 / (bot_share * num_bots**0.5 + (1 - bot_share) * num_man**0.5)
    cycle = BASELINE_CYCLE_H * (mean_task_s / 300) * resource_scale * rng.uniform(0.9, 1.1)
    cost  = BASELINE_COST * (1 - 0.6*pct/100) * rng.uniform(0.9, 1.1)
    return DemoResult(scenario.id, replication, round(cycle, 2), round(cost, 2))
