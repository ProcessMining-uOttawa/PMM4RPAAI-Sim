"""Simulation run loop — pure business logic, no Streamlit dependency."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from . import analysis, demo, runner, store
from .constants import COL_CYCLE_H, COL_COST
from .parameters import AutomationScenario, Scenario
from .transformations import Transformation


@dataclass
class ExperimentResult:
    results: pd.DataFrame
    experiment_bpmn_path: Path | None = None
    scenario_json_paths: dict[str, Path] = field(default_factory=dict)


def run_experiment(
    transformation: Transformation,
    bpmn_path: Path | None,
    json_path: Path | None,
    target: str,
    scenarios: list[Scenario],
    n_reps: int,
    n_cases: int,
    exp_dir: Path,
    demo_mode: bool,
    on_progress: Callable[[int, int, str, int], None] | None = None,
    selected_resource_id: str | None = None,
) -> ExperimentResult:
    """Run all scenario replications and return aggregated results.

    on_progress(done, total, scenario_id, rep) is called after each replication
    if provided — lets the caller update a progress bar without a Streamlit import here.
    """
    total = len(scenarios) * n_reps
    done  = 0
    rows: list[dict] = []
    scenario_json_paths: dict[str, Path] = {}
    experiment_bpmn_path: Path | None = None

    bpmn_tr = None
    if not demo_mode:
        bpmn_tr = transformation.prepare_experiment(
            bpmn_path, json_path, target, exp_dir)
        experiment_bpmn_path = bpmn_tr.bpmn_path

    for s in scenarios:
        s_json: Path | None = None
        for rep in range(n_reps):
            if demo_mode:
                r = demo.fake_simulate(s, rep, n_cases)
                cycle_h, cost = r.cycle_h, r.cost
            else:
                if rep == 0:
                    s_json = transformation.apply_params(
                        bpmn_tr.base_json, bpmn_tr.ids,
                        AutomationScenario.from_taguchi_values(
                            s.values, selected_resource_id=selected_resource_id),
                        store.scenario_dir(exp_dir, s.id) / "params.json",
                    )
                    scenario_json_paths[s.id] = s_json
                out_log  = store.replication_log(exp_dir, s.id, rep)
                out_stat = store.replication_stats(exp_dir, s.id, rep)
                proc_log = store.replication_subprocess_log(exp_dir, s.id, rep)
                runner.simulate(bpmn_tr.bpmn_path, s_json,
                                int(n_cases), out_log, stat_out=out_stat,
                                proc_log=proc_log)
                m = analysis.per_log_metrics(out_log, out_stat)
                cycle_h, cost = m[COL_CYCLE_H], m[COL_COST]

            rows.append({
                "scenario_id": s.id,
                "replication":  rep,
                COL_CYCLE_H:    cycle_h,
                COL_COST:       cost,
                **s.values,
            })
            done += 1
            if on_progress:
                on_progress(done, total, s.id, rep)

    return ExperimentResult(
        results=pd.DataFrame(rows),
        experiment_bpmn_path=experiment_bpmn_path,
        scenario_json_paths=scenario_json_paths,
    )
