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
    pct    = next((v for k, v in scenario.values.items() if k.endswith(".pct_auto")),  50)
    t_auto = next((v for k, v in scenario.values.items() if k.endswith(".t_auto")),    30)
    t_man  = next((v for k, v in scenario.values.items() if k.endswith(".t_manual")), 300)
    # crude model: weighted task time drives cycle; automation cuts cost
    mean_task_s = (pct/100)*t_auto + (1-pct/100)*t_man
    cycle = BASELINE_CYCLE_H * (mean_task_s / 300) * rng.uniform(0.9, 1.1)
    cost  = BASELINE_COST * (1 - 0.6*pct/100) * rng.uniform(0.9, 1.1)
    return DemoResult(scenario.id, replication, round(cycle, 2), round(cost, 2))
