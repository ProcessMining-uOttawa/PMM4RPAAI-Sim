"""Simulation run loop — pure business logic, no Streamlit dependency."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from . import demo
from .simulation import prosimos_csv, runner, store
from .constants import (
    COL_CYCLE_H, COL_COST, COL_TOTAL_CYCLE_S, COL_TOTAL_COST,
    COL_TOTAL_CYCLE_S_MEAN, COL_TOTAL_COST_MEAN,
)
from .parameters import Scenario
from .transformations import AutomationScenario, Transformation


@dataclass
class ExperimentResult:
    results: pd.DataFrame
    experiment_bpmn_path: Path | None = None
    scenario_json_paths: dict[str, Path] = field(default_factory=dict)
    baseline_agg: dict[int, dict] | None = None  # {n_cases: mean totals}; None in demo mode


def _run_baseline(bpmn_path: Path, json_path: Path, n_reps: int,
                  cases_levels: list[int], exp_dir: Path) -> dict[int, dict]:
    """Run the original untransformed model for each unique cases level.

    Returns {n_cases: {COL_TOTAL_CYCLE_S_MEAN: ..., COL_TOTAL_COST_MEAN: ...}} so
    each scenario can be compared to a baseline at the same case count.
    """
    result: dict[int, dict] = {}
    for n_cases in cases_levels:
        totals_cycle: list[float] = []
        totals_cost: list[float] = []
        for rep in range(n_reps):
            out_log  = store.baseline_log(exp_dir, rep, n_cases)
            out_stat = store.baseline_stats(exp_dir, rep, n_cases)
            proc_log = store.baseline_subprocess_log(exp_dir, rep, n_cases)
            runner.simulate(bpmn_path, json_path, n_cases, out_log,
                            stat_out=out_stat, proc_log=proc_log)
            m = prosimos_csv.total_metrics(out_stat)
            totals_cycle.append(m[COL_TOTAL_CYCLE_S])
            totals_cost.append(m[COL_TOTAL_COST])
        result[n_cases] = {
            COL_TOTAL_CYCLE_S_MEAN: sum(totals_cycle) / len(totals_cycle),
            COL_TOTAL_COST_MEAN:    sum(totals_cost)  / len(totals_cost),
        }
    return result


def run_experiment(
    transformation: Transformation,
    bpmn_path: Path | None,
    json_path: Path | None,
    target: str,
    scenarios: list[Scenario],
    n_reps: int,
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

    baseline_agg = None
    bpmn_tr = None
    if not demo_mode:
        assert bpmn_path is not None and json_path is not None
        bpmn_tr = transformation.prepare_experiment(
            bpmn_path, json_path, target, exp_dir)
        experiment_bpmn_path = bpmn_tr.bpmn_path
        cases_levels = sorted({
            AutomationScenario.from_taguchi_values(s.values).num_cases
            for s in scenarios
        })
        baseline_agg = _run_baseline(bpmn_path, json_path, n_reps, cases_levels, exp_dir)

    for s in scenarios:
        s_json: Path | None = None
        automation_scenario: AutomationScenario | None = None
        for rep in range(n_reps):
            if demo_mode:
                r = demo.fake_simulate(s, rep)
                cycle_h, cost = r.cycle_h, r.cost
                total_cycle_s, total_cost = float("nan"), float("nan")
            else:
                assert bpmn_tr is not None
                if rep == 0:
                    automation_scenario = AutomationScenario.from_taguchi_values(
                        s.values, selected_resource_id=selected_resource_id)
                    s_json = transformation.apply_params(
                        bpmn_tr.base_json, bpmn_tr.ids,
                        automation_scenario,
                        store.scenario_dir(exp_dir, s.id) / "params.json",
                    )
                    scenario_json_paths[s.id] = s_json
                assert automation_scenario is not None
                out_log  = store.replication_log(exp_dir, s.id, rep)
                out_stat = store.replication_stats(exp_dir, s.id, rep)
                proc_log = store.replication_subprocess_log(exp_dir, s.id, rep)
                assert s_json is not None
                runner.simulate(bpmn_tr.bpmn_path, s_json,
                                automation_scenario.num_cases, out_log,
                                stat_out=out_stat, proc_log=proc_log)
                m = prosimos_csv.replication_metrics(out_log, out_stat)
                cycle_h, cost = m[COL_CYCLE_H], m[COL_COST]
                total_cycle_s, total_cost = m[COL_TOTAL_CYCLE_S], m[COL_TOTAL_COST]

            rows.append({
                "scenario_id":   s.id,
                "replication":   rep,
                COL_CYCLE_H:     cycle_h,
                COL_COST:        cost,
                COL_TOTAL_CYCLE_S: total_cycle_s,
                COL_TOTAL_COST:    total_cost,
                **s.values,
            })
            done += 1
            if on_progress:
                on_progress(done, total, s.id, rep)

    return ExperimentResult(
        results=pd.DataFrame(rows),
        experiment_bpmn_path=experiment_bpmn_path,
        scenario_json_paths=scenario_json_paths,
        baseline_agg=baseline_agg,
    )
