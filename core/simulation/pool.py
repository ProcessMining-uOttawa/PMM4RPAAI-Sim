"""Parallel simulation executor."""
from __future__ import annotations
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import runner

TASK_BASELINE = "baseline"
TASK_SCENARIO = "scenario"


@dataclass
class SimulationTask:
    bpmn_path: Path
    json_path: Path
    n_cases: int
    out_log: Path
    out_stat: Path | None
    proc_log: Path | None
    metadata: Any = field(default=None)


def run_all(
    tasks: list[SimulationTask],
    on_complete: Callable[[SimulationTask], None],
    max_workers: int | None = None,
) -> None:
    """Run all simulation tasks in parallel and call on_complete after each.

    on_complete is always called on the calling thread (via as_completed),
    so callers can safely mutate shared state without locks.

    Raises on the first simulation failure after cancelling pending tasks.
    max_workers defaults to os.cpu_count() when None.
    """
    workers = max_workers if max_workers is not None else os.cpu_count()
    future_to_task: dict = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for task in tasks:
            f = pool.submit(
                runner.simulate,
                task.bpmn_path, task.json_path, task.n_cases, task.out_log,
                stat_out=task.out_stat, proc_log=task.proc_log,
            )
            future_to_task[f] = task

        try:
            for f in as_completed(future_to_task):
                f.result()  # re-raises CalledProcessError on simulation failure
                on_complete(future_to_task[f])
        except Exception:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
