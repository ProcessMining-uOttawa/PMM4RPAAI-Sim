"""Parallel simulation executor."""

from __future__ import annotations
import dataclasses
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED, Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import runner

# how often run_all wakes to check stop_check while workers run
_STOP_POLL_SECONDS = 0.5


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


class _LiveProcesses:
    """Registry of running simulation subprocesses so a cancel can kill them.

    This is the one piece of worker-thread-written state in the executor —
    worker threads add their Popen on spawn, the calling thread kills them all
    on cancel — so it carries its own lock. The caller-facing callback state
    (on_complete/on_error) stays lock-free, mutated only on the calling thread;
    this registry is internal to run_all and invisible to callers.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._procs: set[subprocess.Popen] = set()
        self._killing = False

    def register(self, proc: subprocess.Popen) -> None:
        """Track a freshly spawned subprocess (called on the worker thread)."""
        with self._lock:
            if not self._killing:
                self._procs.add(proc)
                return
        # Cancel already began: kill this late spawn now rather than let it run
        # and re-block the pool join (the spawn-after-cancel race).
        runner.terminate_process(proc)

    def kill_all(self) -> None:
        """Kill every tracked subprocess (called on the calling thread on cancel).

        Kills run on parallel threads: each terminate_process spawns a taskkill
        (Windows) or blocks on a SIGTERM grace window (POSIX), so serial kills of
        N in-flight workers add up — parallelising keeps the whole kill phase at
        roughly one kill's cost instead of N.
        """
        with self._lock:
            self._killing = True
            procs = list(self._procs)
            self._procs.clear()
        if not procs:
            return
        killers = [
            threading.Thread(target=runner.terminate_process, args=(proc,))
            for proc in procs
        ]
        for t in killers:
            t.start()
        for t in killers:
            t.join()


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
    locks — the one exception is the internal _LiveProcesses registry, which is
    worker-thread-written and carries its own lock. Returns True if all tasks were
    processed, False if stop_check() fired first.

    When stop_check is set, the wait loop polls it every _STOP_POLL_SECONDS and, on
    cancel, kills the in-flight Prosimos subprocesses so the pool join unblocks
    promptly instead of waiting out the longest running replication. With stop_check
    None the loop blocks on FIRST_COMPLETED as before. max_workers defaults to
    os.cpu_count() when None.
    """
    workers = max_workers if max_workers is not None else os.cpu_count()
    live = _LiveProcesses()
    poll_timeout = _STOP_POLL_SECONDS if stop_check is not None else None

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
                on_spawn=live.register,
            )

        pending: dict[Future[Path], SimulationTask] = {
            _submit(task): task for task in tasks
        }

        while pending:
            done_set, _ = wait(
                pending.keys(), timeout=poll_timeout, return_when=FIRST_COMPLETED
            )
            if stop_check is not None and stop_check():
                live.kill_all()  # unblock workers stuck in proc.wait()
                pool.shutdown(wait=False, cancel_futures=True)
                return False
            for future in done_set:
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
