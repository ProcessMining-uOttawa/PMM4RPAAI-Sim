"""Simulation run loop — pure business logic, no Streamlit dependency."""

from __future__ import annotations
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from .simulation import prosimos_csv, store
from .simulation.pool import SimulationTask, run_all
from .constants import (
    COL_CYCLE_H,
    COL_COST,
    COL_TOTAL_CYCLE_S,
    COL_TOTAL_COST,
    COL_TOTAL_CYCLE_S_MEAN,
    COL_TOTAL_COST_MEAN,
    COL_REWORK_COUNT,
    COL_REWORK_RATE,
    COL_REWORK_COUNT_MEAN,
    COL_REWORK_RATE_MEAN,
    F_NUM_CASES,
)
from .parameters import Scenario
from .transformations import Transformation


TASK_BASELINE = "baseline"
TASK_SCENARIO = "scenario"


class ExperimentCancelledError(RuntimeError):
    """Raised when a running experiment is stopped by the caller."""


@dataclass
class ExperimentResult:
    results: pd.DataFrame
    experiment_bpmn_path: Path | None = None
    scenario_json_paths: dict[str, Path] = field(default_factory=dict)
    baseline_agg: dict[int, dict] | None = None  # {n_cases: mean totals}


def run_experiment(
    transformation: Transformation,
    bpmn_path: Path,
    json_path: Path,
    target: str,
    scenarios: list[Scenario],
    n_reps: int,
    exp_dir: Path,
    on_progress: Callable[[int, int, str, int], None] | None = None,
    selected_resource_id: str | None = None,
    bot_cost_per_hour: float = 0.0,
    stop_event: threading.Event | None = None,
) -> ExperimentResult:
    """Run all scenario replications and return aggregated results.

    on_progress(done, total, scenario_id, rep) is called after each replication
    if provided — lets the caller update a progress bar without a Streamlit import here.
    """
    bpmn_tr = transformation.prepare_experiment(
        bpmn_path, json_path, target, exp_dir,
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
            store.scenario_dir(exp_dir, s.id) / "params.json",
        )
        scenario_json_paths[s.id] = s_json

    total = len(scenarios) * n_reps + len(cases_levels) * n_reps
    done = 0
    rows: list[dict] = []
    baseline_reps: dict[int, list[dict]] = {n: [] for n in cases_levels}

    tasks: list[SimulationTask] = []
    for n_cases in cases_levels:
        for rep in range(n_reps):
            tasks.append(
                SimulationTask(
                    bpmn_path=bpmn_path,
                    json_path=json_path,
                    n_cases=n_cases,
                    out_log=store.baseline_log(exp_dir, rep, n_cases),
                    out_stat=store.baseline_stats(exp_dir, rep, n_cases),
                    proc_log=store.baseline_subprocess_log(exp_dir, rep, n_cases),
                    metadata=(TASK_BASELINE, n_cases, rep),
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
                    out_log=store.replication_log(exp_dir, s.id, rep),
                    out_stat=store.replication_stats(exp_dir, s.id, rep),
                    proc_log=store.replication_subprocess_log(exp_dir, s.id, rep),
                    metadata=(TASK_SCENARIO, s.id, rep, s.values),
                )
            )

    def _on_complete(task: SimulationTask) -> None:
        nonlocal done
        kind = task.metadata[0]
        if kind == TASK_BASELINE:
            _, n_cases, rep = task.metadata
            assert task.out_stat is not None
            baseline_reps[n_cases].append(
                prosimos_csv.replication_metrics(task.out_log, task.out_stat)
            )
            label = "baseline"
        else:
            _, sid, rep, values = task.metadata
            assert task.out_stat is not None
            m = prosimos_csv.replication_metrics(
                task.out_log,
                task.out_stat,
                bot_task_name=bpmn_tr.ids.bot_task_name,
                original_task_name=bpmn_tr.ids.task_name,
            )
            rows.append(
                {
                    "scenario_id": sid,
                    "replication": rep,
                    COL_CYCLE_H: m[COL_CYCLE_H],
                    COL_COST: m[COL_COST],
                    COL_TOTAL_CYCLE_S: m[COL_TOTAL_CYCLE_S],
                    COL_TOTAL_COST: m[COL_TOTAL_COST],
                    COL_REWORK_COUNT: m[COL_REWORK_COUNT],
                    COL_REWORK_RATE: m[COL_REWORK_RATE],
                    **values,
                }
            )
            label = sid
        done += 1
        if on_progress:
            on_progress(done, total, label, rep)

    stop_check = (lambda: stop_event.is_set()) if stop_event is not None else None
    completed = run_all(tasks, _on_complete, stop_check=stop_check)
    if not completed:
        raise ExperimentCancelledError()

    baseline_agg: dict[int, dict] = {}
    for n_cases, rep_list in baseline_reps.items():
        means = pd.DataFrame(rep_list).mean()
        baseline_agg[n_cases] = {
            COL_TOTAL_CYCLE_S_MEAN: means[COL_TOTAL_CYCLE_S],
            COL_TOTAL_COST_MEAN: means[COL_TOTAL_COST],
            COL_REWORK_COUNT_MEAN: means[COL_REWORK_COUNT],
            COL_REWORK_RATE_MEAN: means[COL_REWORK_RATE],
        }

    return ExperimentResult(
        results=pd.DataFrame(rows),
        experiment_bpmn_path=experiment_bpmn_path,
        scenario_json_paths=scenario_json_paths,
        baseline_agg=baseline_agg,
    )
