"""Simulation run loops — pure business logic, no Streamlit dependency."""

from __future__ import annotations
import dataclasses
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import CalledProcessError
from typing import Callable

import pandas as pd

from .simulation import store
from .simulation.prosimos.replication_metrics import (
    ObservedStats,
    observed_log_stats,
    replication_metrics,
)
from .simulation.executor import SimulationTask, run_all
from .constants import (
    COL_TOTAL_CYCLE_S,
    COL_TOTAL_COST,
    COL_TOTAL_CYCLE_S_MEAN,
    COL_TOTAL_COST_MEAN,
    COL_TOTAL_REWORK_COUNT,
    COL_TOTAL_REWORK_COUNT_MEAN,
    COL_TOTAL_BOT_FAILURE_COUNT,
    COL_TOTAL_BOT_FAILURE_COUNT_MEAN,
)
from .metrics import MetricRegistry
from .parameters import Scenario
from .transformations import Transformation


class ExperimentCancelledError(RuntimeError):
    """Raised when a running experiment is stopped by the caller."""


class SimulationError(RuntimeError):
    """Raised when every scenario replication fails with no results to return.

    Carries the first failure's `log_tail` (the Prosimos subprocess-log tail from
    a CalledProcessError) so the caller can surface real diagnostic detail —
    `str(CalledProcessError)` is only the exit-status line, not the captured log.
    """

    def __init__(self, message: str, log_tail: str | None = None) -> None:
        super().__init__(message)
        self.log_tail = log_tail


@dataclass(frozen=True)
class BaselineMeta:
    rep: int


@dataclass
class ScenarioMeta:
    scenario_id: str
    rep: int
    values: dict[str, object]


@dataclass
class FailedReplication:
    scenario_id: str  # scenario id, "baseline", or "as_discovered"
    rep: int
    error: str  # str(exception) — the short message
    log_tail: str | None = None  # CalledProcessError.output (Prosimos log tail), if any


def _unpack_meta(meta: object) -> tuple[str, int]:
    """Extract (label, rep) from task metadata; raises TypeError for unknown types."""
    if isinstance(meta, BaselineMeta):
        return "baseline", meta.rep
    if isinstance(meta, ScenarioMeta):
        return meta.scenario_id, meta.rep
    raise TypeError(f"Unexpected metadata type: {type(meta)}")


def _log_tail(exc: BaseException) -> str | None:
    """The Prosimos subprocess-log tail a failure carries, if any.

    runner.simulate attaches it as CalledProcessError.output; str(exc) drops
    it, so it must be read off the live exception.
    """
    return exc.output if isinstance(exc, CalledProcessError) else None


def _raise_if_all_failed(rows: list[dict], failures: list[FailedReplication]) -> None:
    """Raise SimulationError when a run produced no results at all."""
    if not rows and failures:
        first = failures[0]
        raise SimulationError(
            f"All {len(failures)} simulation replications failed. "
            f"First error: {first.error}",
            log_tail=first.log_tail,
        )


@dataclass
class ExperimentResult:
    results: pd.DataFrame
    # Cases per replication the run executed at — the totals' scale, recorded so
    # consumers of a committed result read the run's own value, not the current
    # run config.
    n_cases: int
    experiment_bpmn_path: Path | None = None
    scenario_json_paths: dict[str, Path] = field(default_factory=dict)
    baseline_agg: dict[str, float] | None = None  # per-case + total means, one record
    scenario_log_paths: dict[str, list[Path]] = field(default_factory=dict)
    baseline_log_paths: list[Path] = field(default_factory=list)
    failed_replications: list[FailedReplication] = field(default_factory=list)


@dataclass
class AsDiscoveredResult:
    """One as-discovered run: the model exactly as Simod discovered it, untransformed.

    ``observed`` doubles as the mode discriminant: set when the run was a model
    fidelity check (the uploaded log's statistics, for the comparison table),
    None for a free exploration run. NOT the experiment baseline — the baseline
    is the transformed model at 0% automation (see CLAUDE.md §8).
    """

    results: pd.DataFrame
    n_cases: int
    experiment_dir: Path
    log_paths: list[Path] = field(default_factory=list)
    observed: ObservedStats | None = None
    failed_replications: list[FailedReplication] = field(default_factory=list)


def run_as_discovered(
    bpmn_path: Path,
    json_path: Path,
    n_reps: int,
    n_cases: int,
    experiment_dir: Path,
    log_csv: Path | None = None,
    on_progress: Callable[[int, int, str, int], None] | None = None,
    stop_event: threading.Event | None = None,
    max_workers: int = 1,
    max_retries: int = 2,
) -> AsDiscoveredResult:
    """Run the discovered model, untransformed, for n_reps replications.

    ``log_csv`` switches fidelity mode on: the uploaded log's statistics are
    computed first, and n_cases must equal its case count — every compared
    statistic's sampling noise scales with n, so the per-replication spread
    (the comparison's yardstick for systematic-misfit vs noise) only measures
    the log's one-realization noise at equal n. The check lives here, before
    any file is written: the UI's pinned widget is courtesy, this is the
    guarantee.

    experiment_dir must be a fresh run dir (store.new_experiment): stale
    rep_* files from a prior run would survive the copy-in and contaminate
    the trust-checker walk and the exports.
    """
    observed: ObservedStats | None = None
    if log_csv is not None:
        observed = observed_log_stats(log_csv)
        if n_cases != observed.n_cases:
            raise ValueError(
                "Fidelity check requires n_cases to equal the log's case count "
                f"({observed.n_cases}); got {n_cases}."
            )

    # Copy the discovered model + params in, so the run dir is a complete,
    # reproducible artifact (the prepare_experiment precedent) and the trust
    # checker can walk its (log, params, stats) triples.
    experiment_dir.mkdir(parents=True, exist_ok=True)
    model_copy = experiment_dir / "model.bpmn"
    shutil.copyfile(bpmn_path, model_copy)
    params_copy = store.as_discovered_params_path(experiment_dir)
    shutil.copyfile(json_path, params_copy)

    tasks = [
        SimulationTask(
            bpmn_path=model_copy,
            json_path=params_copy,
            n_cases=n_cases,
            out_log=store.as_discovered_log(experiment_dir, rep),
            out_stat=store.as_discovered_stats(experiment_dir, rep),
            proc_log=store.as_discovered_subprocess_log(experiment_dir, rep),
            metadata=rep,  # one task species — the bare replication index
            max_retries=max_retries,
        )
        for rep in range(n_reps)
    ]

    done = 0
    rows: list[dict] = []
    log_paths: list[Path] = []
    failures: list[FailedReplication] = []

    def _tick(rep: int) -> None:
        nonlocal done
        done += 1
        if on_progress:
            on_progress(done, n_reps, "as_discovered", rep)

    def _on_complete(task: SimulationTask) -> None:
        rep: int = task.metadata
        # Same "the run finished" guard as run_experiment: a Prosimos run that
        # died between the log and the stats must fail loudly, not parse a
        # truncated log.
        assert task.out_stat is not None and task.out_stat.exists()
        rows.append(
            {
                "replication": rep,
                **dataclasses.asdict(replication_metrics(task.out_log, task.json_path)),
            }
        )
        log_paths.append(task.out_log)
        _tick(rep)

    def _on_error(task: SimulationTask, exc: BaseException) -> None:
        failures.append(
            FailedReplication(
                scenario_id="as_discovered",
                rep=task.metadata,
                error=str(exc),
                log_tail=_log_tail(exc),
            )
        )
        _tick(task.metadata)

    stop_check = stop_event.is_set if stop_event is not None else None
    completed = run_all(
        tasks,
        _on_complete,
        on_error=_on_error,
        max_workers=max_workers,
        stop_check=stop_check,
    )
    if not completed:
        raise ExperimentCancelledError()

    _raise_if_all_failed(rows, failures)

    return AsDiscoveredResult(
        results=pd.DataFrame(rows),
        n_cases=n_cases,
        experiment_dir=experiment_dir,
        log_paths=log_paths,
        observed=observed,
        failed_replications=failures,
    )


def run_experiment(
    transformation: Transformation,
    bpmn_path: Path,
    json_path: Path,
    target_activity: str,
    scenarios: list[Scenario],
    n_reps: int,
    n_cases: int,
    experiment_dir: Path,
    on_progress: Callable[[int, int, str, int], None] | None = None,
    selected_resource_id: str | None = None,
    bot_cost_per_hour: float = 0.0,
    stop_event: threading.Event | None = None,
    max_workers: int = 1,
    max_retries: int = 2,
) -> ExperimentResult:
    """Run all scenario and baseline replications.

    Every replication simulates `n_cases` cases. Scenario replications land as
    per-replication rows in `results`; baseline replications are aggregated
    into `baseline_agg` — one flat record of per-case and total means.

    on_progress(done, total, scenario_id, rep) is called after each replication
    if provided — lets the caller update a progress bar without a Streamlit import here.
    """
    bpmn_tr = transformation.prepare_experiment(
        bpmn_path,
        json_path,
        target_activity,
        experiment_dir,
        bot_cost_per_hour=bot_cost_per_hour,
        selected_resource_id=selected_resource_id,
    )
    experiment_bpmn_path = bpmn_tr.bpmn_path

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

    # The baseline is the pattern applied with 0% automation — generated once
    # (cases-per-rep is a CLI arg, not in the JSON).
    baseline_json_path = transformation.apply_params(
        bpmn_tr.scenario_template,
        bpmn_tr.ids,
        transformation.baseline_params(bpmn_tr),
        store.baseline_params_path(experiment_dir),
    )

    total = len(scenarios) * n_reps + n_reps
    done = 0
    rows: list[dict] = []
    baseline_reps: list[dict] = []
    scenario_log_paths: dict[str, list[Path]] = {s.id: [] for s in scenarios}
    baseline_log_paths: list[Path] = []

    tasks: list[SimulationTask] = []
    for rep in range(n_reps):
        tasks.append(
            SimulationTask(
                bpmn_path=bpmn_tr.bpmn_path,
                json_path=baseline_json_path,
                n_cases=n_cases,
                out_log=store.baseline_log(experiment_dir, rep),
                out_stat=store.baseline_stats(experiment_dir, rep),
                proc_log=store.baseline_subprocess_log(experiment_dir, rep),
                metadata=BaselineMeta(rep=rep),
                max_retries=max_retries,
            )
        )
    for s in scenarios:
        s_json = scenario_json_paths[s.id]
        for rep in range(n_reps):
            tasks.append(
                SimulationTask(
                    bpmn_path=bpmn_tr.bpmn_path,
                    json_path=s_json,
                    n_cases=n_cases,
                    out_log=store.replication_log(experiment_dir, s.id, rep),
                    out_stat=store.replication_stats(experiment_dir, s.id, rep),
                    proc_log=store.replication_subprocess_log(
                        experiment_dir, s.id, rep
                    ),
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
        # Metrics come from the event log + params JSON; the stats CSV is written
        # by Prosimos and cross-checked out-of-band. Asserting its existence is a
        # cheap "the run finished" guard — a Prosimos run that died between the log
        # and the stats must fail loudly, not parse a truncated log.
        assert task.out_stat is not None and task.out_stat.exists()
        if isinstance(meta, BaselineMeta):
            baseline_reps.append(
                dataclasses.asdict(
                    replication_metrics(
                        task.out_log,
                        task.json_path,
                        bot_task_name=_bot_task_name,
                        original_task_name=_original_task_name,
                    )
                )
            )
            baseline_log_paths.append(task.out_log)
            _tick("baseline", meta.rep)
        else:  # ScenarioMeta
            m = dataclasses.asdict(
                replication_metrics(
                    task.out_log,
                    task.json_path,
                    bot_task_name=_bot_task_name,
                    original_task_name=_original_task_name,
                )
            )
            rows.append(
                {
                    "scenario_id": meta.scenario_id,
                    "replication": meta.rep,
                    **m,
                    **meta.values,
                }
            )
            scenario_log_paths[meta.scenario_id].append(task.out_log)
            _tick(meta.scenario_id, meta.rep)

    def _on_error(task: SimulationTask, exc: BaseException) -> None:
        label, rep = _unpack_meta(task.metadata)
        failures.append(
            FailedReplication(
                scenario_id=label, rep=rep, error=str(exc), log_tail=_log_tail(exc)
            )
        )
        _tick(label, rep)

    stop_check = stop_event.is_set if stop_event is not None else None
    completed = run_all(
        tasks,
        _on_complete,
        on_error=_on_error,
        max_workers=max_workers,
        stop_check=stop_check,
    )
    if not completed:
        raise ExperimentCancelledError()

    _raise_if_all_failed(rows, failures)

    # One flat record: every registered indicator's per-case mean stored at
    # source (so consumers never derive per-case by dividing a total), beside the
    # four run-total means. The per-case half is registry-driven — a new
    # indicator flows in without touching this block; the totals are hand-listed
    # because they never grow with the indicator set (CLAUDE.md §8).
    baseline_agg: dict[str, float] | None = None
    if baseline_reps:  # stays None (never {}) when all baseline reps failed —
        # app.py gates the Baseline tab and goal seeding on "is not None"
        means = pd.DataFrame(baseline_reps).mean()
        baseline_agg = {
            indicator.mean.column: means[indicator.results_column]
            for metric in MetricRegistry.all()
            for indicator in metric.indicators
        }
        baseline_agg.update(
            {
                COL_TOTAL_CYCLE_S_MEAN: means[COL_TOTAL_CYCLE_S],
                COL_TOTAL_COST_MEAN: means[COL_TOTAL_COST],
                COL_TOTAL_REWORK_COUNT_MEAN: means[COL_TOTAL_REWORK_COUNT],
                # Bot failures are structurally 0 at 0% automation (no case
                # reaches the bot), but read from the data — Panel 5 needs the key.
                COL_TOTAL_BOT_FAILURE_COUNT_MEAN: means[COL_TOTAL_BOT_FAILURE_COUNT],
            }
        )

    return ExperimentResult(
        results=pd.DataFrame(rows),
        n_cases=n_cases,
        experiment_bpmn_path=experiment_bpmn_path,
        scenario_json_paths=scenario_json_paths,
        baseline_agg=baseline_agg,
        scenario_log_paths=scenario_log_paths,
        baseline_log_paths=baseline_log_paths,
        failed_replications=failures,
    )
