"""Simulation run loop — pure business logic, no Streamlit dependency."""

from __future__ import annotations
import dataclasses
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from .simulation import prosimos_csv, store
from .simulation.pool import SimulationTask, run_all
from .constants import (
    COL_TOTAL_CYCLE_S,
    COL_TOTAL_COST,
    COL_TOTAL_CYCLE_S_MEAN,
    COL_TOTAL_COST_MEAN,
    COL_TOTAL_REWORK_COUNT,
    COL_REWORK_RATE,
    COL_TOTAL_REWORK_COUNT_MEAN,
    COL_REWORK_RATE_MEAN,
    F_NUM_CASES,
)
from .parameters import Scenario
from .transformations import Transformation


class ExperimentCancelledError(RuntimeError):
    """Raised when a running experiment is stopped by the caller."""


class SimulationError(RuntimeError):
    """Raised when all simulation replications fail with no results to return."""


@dataclass(frozen=True)
class BaselineMeta:
    n_cases: int
    rep: int


@dataclass
class ScenarioMeta:
    scenario_id: str
    rep: int
    values: dict[str, object]


@dataclass
class FailedReplication:
    scenario_id: str    # scenario id, or "baseline" for baseline tasks
    rep: int
    error: str          # str(exception)


def _unpack_meta(meta: object) -> tuple[str, int]:
    """Extract (label, rep) from task metadata; raises TypeError for unknown types."""
    if isinstance(meta, BaselineMeta):
        return "baseline", meta.rep
    if isinstance(meta, ScenarioMeta):
        return meta.scenario_id, meta.rep
    raise TypeError(f"Unexpected metadata type: {type(meta)}")


@dataclass
class ExperimentResult:
    results: pd.DataFrame
    experiment_bpmn_path: Path | None = None
    scenario_json_paths: dict[str, Path] = field(default_factory=dict)
    baseline_agg: dict[int, dict] | None = None  # {n_cases: mean totals}
    scenario_log_paths: dict[str, list[Path]] = field(default_factory=dict)
    baseline_log_paths: dict[int, list[Path]] = field(default_factory=dict)
    failed_replications: list[FailedReplication] = field(default_factory=list)


def run_experiment(
    transformation: Transformation,
    bpmn_path: Path,
    json_path: Path,
    target_activity: str,
    scenarios: list[Scenario],
    n_reps: int,
    experiment_dir: Path,
    on_progress: Callable[[int, int, str, int], None] | None = None,
    selected_resource_id: str | None = None,
    bot_cost_per_hour: float = 0.0,
    stop_event: threading.Event | None = None,
    max_workers: int = 1,
    max_retries: int = 2,
) -> ExperimentResult:
    """Run all scenario replications and return aggregated results.

    on_progress(done, total, scenario_id, rep) is called after each replication
    if provided — lets the caller update a progress bar without a Streamlit import here.
    """
    bpmn_tr = transformation.prepare_experiment(
        bpmn_path, json_path, target_activity, experiment_dir,
        bot_cost_per_hour=bot_cost_per_hour,
        selected_resource_id=selected_resource_id,
    )
    experiment_bpmn_path = bpmn_tr.bpmn_path
    cases_levels = sorted({int(s.values[F_NUM_CASES]) for s in scenarios})

    # Pre-generate all scenario JSONs sequentially — XML/JSON mutation is not
    # thread-safe and must complete before workers read the output files.
    scenario_json_paths: dict[str, Path] = {}
    for s in scenarios:
        params = transformation.params_from_values(s.values, bpmn_tr)
        s_json = transformation.apply_params(
            bpmn_tr.scenario_template,
            bpmn_tr.ids,
            params,
            store.scenario_dir(experiment_dir, s.id) / "params.json",
        )
        scenario_json_paths[s.id] = s_json

    total = len(scenarios) * n_reps + len(cases_levels) * n_reps
    done = 0
    rows: list[dict] = []
    baseline_reps: dict[int, list[dict]] = {n: [] for n in cases_levels}
    scenario_log_paths: dict[str, list[Path]] = {s.id: [] for s in scenarios}
    baseline_log_paths: dict[int, list[Path]] = {n: [] for n in cases_levels}

    tasks: list[SimulationTask] = []
    for n_cases in cases_levels:
        for rep in range(n_reps):
            tasks.append(
                SimulationTask(
                    bpmn_path=bpmn_path,
                    json_path=json_path,
                    n_cases=n_cases,
                    out_log=store.baseline_log(experiment_dir, rep, n_cases),
                    out_stat=store.baseline_stats(experiment_dir, rep, n_cases),
                    proc_log=store.baseline_subprocess_log(experiment_dir, rep, n_cases),
                    metadata=BaselineMeta(n_cases=n_cases, rep=rep),
                    max_retries=max_retries,
                )
            )
    for s in scenarios:
        s_json = scenario_json_paths[s.id]
        n_cases = int(s.values[F_NUM_CASES])
        for rep in range(n_reps):
            tasks.append(
                SimulationTask(
                    bpmn_path=bpmn_tr.bpmn_path,
                    json_path=s_json,
                    n_cases=n_cases,
                    out_log=store.replication_log(experiment_dir, s.id, rep),
                    out_stat=store.replication_stats(experiment_dir, s.id, rep),
                    proc_log=store.replication_subprocess_log(experiment_dir, s.id, rep),
                    metadata=ScenarioMeta(scenario_id=s.id, rep=rep, values=s.values),
                    max_retries=max_retries,
                )
            )

    _bot_task_name = bpmn_tr.ids.bot_task_name
    _original_task_name = bpmn_tr.ids.task_name
    failures: list[FailedReplication] = []

    def _tick(label: str, rep: int) -> None:
        nonlocal done
        done += 1
        if on_progress:
            on_progress(done, total, label, rep)

    def _on_complete(task: SimulationTask) -> None:
        meta = task.metadata
        assert task.out_stat is not None
        if isinstance(meta, BaselineMeta):
            baseline_reps[meta.n_cases].append(
                dataclasses.asdict(prosimos_csv.replication_metrics(task.out_log, task.out_stat))
            )
            baseline_log_paths[meta.n_cases].append(task.out_log)
            _tick("baseline", meta.rep)
        else:  # ScenarioMeta
            m = dataclasses.asdict(prosimos_csv.replication_metrics(
                task.out_log,
                task.out_stat,
                bot_task_name=_bot_task_name,
                original_task_name=_original_task_name,
            ))
            rows.append({"scenario_id": meta.scenario_id, "replication": meta.rep, **m, **meta.values})
            scenario_log_paths[meta.scenario_id].append(task.out_log)
            _tick(meta.scenario_id, meta.rep)

    def _on_error(task: SimulationTask, exc: BaseException) -> None:
        label, rep = _unpack_meta(task.metadata)
        failures.append(FailedReplication(scenario_id=label, rep=rep, error=str(exc)))
        _tick(label, rep)

    stop_check = stop_event.is_set if stop_event is not None else None
    completed = run_all(
        tasks, _on_complete, on_error=_on_error,
        max_workers=max_workers, stop_check=stop_check,
    )
    if not completed:
        raise ExperimentCancelledError()

    if not rows and failures:
        raise SimulationError(
            f"All {len(failures)} simulation replications failed. "
            f"First error: {failures[0].error}"
        )

    baseline_agg: dict[int, dict] = {}
    for n_cases, rep_list in baseline_reps.items():
        if not rep_list:
            continue  # all baseline replications for this n_cases level failed
        means = pd.DataFrame(rep_list).mean()
        baseline_agg[n_cases] = {
            COL_TOTAL_CYCLE_S_MEAN:      means[COL_TOTAL_CYCLE_S],
            COL_TOTAL_COST_MEAN:         means[COL_TOTAL_COST],
            COL_TOTAL_REWORK_COUNT_MEAN: means[COL_TOTAL_REWORK_COUNT],
            COL_REWORK_RATE_MEAN:        means[COL_REWORK_RATE],
        }

    return ExperimentResult(
        results=pd.DataFrame(rows),
        experiment_bpmn_path=experiment_bpmn_path,
        scenario_json_paths=scenario_json_paths,
        baseline_agg=baseline_agg or None,  # {} → None when all baseline reps failed
        scenario_log_paths=scenario_log_paths,
        baseline_log_paths=baseline_log_paths,
        failed_replications=failures,
    )
