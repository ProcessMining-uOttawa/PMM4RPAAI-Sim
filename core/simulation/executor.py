"""Parallel simulation executor."""

from __future__ import annotations
import dataclasses
import os
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED, Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import runner


@dataclass
class SimulationTask:
    bpmn_path: Path
    json_path: Path
    n_cases: int
    out_log: Path
    out_stat: Path | None
    proc_log: Path | None
    metadata: Any = None
    max_retries: int = 0


def run_all(
    tasks: list[SimulationTask],
    on_complete: Callable[[SimulationTask], None],
    on_error: Callable[[SimulationTask, BaseException], None] | None = None,
    max_workers: int | None = None,
    stop_check: Callable[[], bool] | None = None,
) -> bool:
    """Run all simulation tasks in parallel, retrying each up to task.max_retries times
    on failure before calling on_error. on_complete and on_error are always called on
    the calling thread (via wait()), so callers can safely mutate shared state without
    locks. Returns True if all tasks were processed, False if stop_check() fired first.
    max_workers defaults to os.cpu_count() when None.
    """
    workers = max_workers if max_workers is not None else os.cpu_count()

    with ThreadPoolExecutor(max_workers=workers) as pool:

        def _submit(task: SimulationTask) -> Future[Path]:
            return pool.submit(
                runner.simulate,
                task.bpmn_path,
                task.json_path,
                task.n_cases,
                task.out_log,
                stat_out=task.out_stat,
                proc_log=task.proc_log,
            )

        pending: dict[Future[Path], SimulationTask] = {
            _submit(task): task for task in tasks
        }

        while pending:
            done_set, _ = wait(pending.keys(), return_when=FIRST_COMPLETED)
            for future in done_set:
                if stop_check is not None and stop_check():
                    pool.shutdown(wait=False, cancel_futures=True)
                    return False
                task = pending.pop(future)
                try:
                    exc = future.exception()
                    if exc is not None:
                        if task.max_retries > 0:
                            # proc_log=None so the retry doesn't overwrite the
                            # failed attempt's captured subprocess log.
                            retried = dataclasses.replace(
                                task, max_retries=task.max_retries - 1, proc_log=None
                            )
                            pending[_submit(retried)] = retried
                        elif on_error is not None:
                            on_error(task, exc)
                    else:
                        on_complete(task)
                except Exception:
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise

    return True
