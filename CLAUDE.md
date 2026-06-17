# PMM4RPAAI-Sim — project memory for Claude

> Process Mining + Modeling for RPA/AI Simulation.
> Determine, via simulation, whether automating an activity in a discovered
> business process will meet stakeholder goals (cycle time, cost, …) under
> a Taguchi design-of-experiments.

This file is the canonical orientation for anyone (or anyone's Claude) joining
the project. Read it before editing.

---

## 1. What the tool does

```
Event log (XES/CSV)
        │
        ▼  Simod  (one-shot, Java 8 + SplitMiner)
BPMN model + Prosimos simulation-parameters JSON
        │
        ▼  user picks: target activity + substitution pattern
Pattern.parameters(target) → N factors × 3 levels (Taguchi)
        │
        ▼  curated L9, L18, L27 OAs
list[Scenario]  (one per row of the OA)
        │
        ▼  Pattern.apply(scenario)  — mutates BPMN + JSON
        │
        ▼  Prosimos  start-simulation  ×  N replications
Per-replication event-log CSV + stats CSV
        │
        ▼  pandas-derived metrics  +  Taguchi S/N + ranking
Ranking table + main-effects view + export (Statistics CSV, Params ZIP, BPMN, Event logs ZIP, Model ZIP)
```

## 2. Architecture seams

**`XORSplitAutomation` is the only substitution pattern and no second pattern will be added** — it is central to the client's thesis. The `Transformation` ABC and `REGISTRY` exist for clean encapsulation, not extensibility. Three contracts define that boundary:

- **`Transformation`** ([core/transformations.py](core/transformations.py)) — abstract base with four abstract methods:
  - `parameters(target_activity, current_duration_s) → list[Parameter]`
    declares the factors the pattern exposes. The UI auto-renders them; the
    Taguchi designer auto-fits an OA.
  - `prepare_experiment(bpmn_in, json_in, target, out_dir, ...) → BpmnTransformResult`
    mutates the BPMN once and builds the shared scenario-template JSON. Called
    once per experiment. Returns a `BpmnTransformResult` carrying `bpmn_path`,
    `scenario_template`, `ids`, and `selected_resource_id`.
  - `params_from_values(values, result) → ScenarioParams` converts one Taguchi
    row into the pattern's typed params object. Keeps `orchestrator.py` free of
    any concrete subclass imports.
  - `apply_params(template, ids, params, out) → Path` deep-copies the template
    and injects scenario-specific values. Called once per scenario.
  - The only pattern: `XORSplitAutomation` — the 4-gateway / 2-activity
    pattern in §4.

- **`Parameter`** ([core/parameters.py](core/parameters.py)) — `{id, label,
  levels:[3], kind}`. `kind` (`"percentage"`, `"duration_s"`, `"categorical"`,
  `"cost"`) drives `number_input` constraints in the UI via `level_input_kwargs()`
  in `ui/widgets.py` (min/max/step/format). The pattern's `apply()` reads `values` by
  id directly and does not use `kind`.

- **Job-folder store** ([core/simulation/store.py](core/simulation/store.py)) — every experiment
  is a folder under `runs/<exp-id>/`. Replications land at
  `runs/<exp-id>/scenarios/<sid>/rep_NNN_log.csv` + `..._stats.csv`. Tidy
  long-format DataFrame in `app.py` is the single source of truth for
  analysis — keeps re-ranking decoupled from re-simulating.

## 3. Module map

| File | Responsibility |
|---|---|
| [app.py](app.py) | Streamlit dashboard (Mockup B): sidebar = experiment state + run config; 5 panels = Activity & pattern · Factor levels · Execution · Ranked scenarios · Baseline comparison. Panel 4 includes an export row with five buttons: BPMN · Params (ZIP) · Statistics (CSV) · Event logs (ZIP) · Model (ZIP). Event logs (ZIP) is disabled in demo mode; Model (ZIP) bundles BPMN + params + statistics. `_clear_results()` resets all run-level session state keys; `_clear_log()` calls `_clear_results()` then resets log-level keys — new keys belong in one of these helpers, not scattered across reset sites. |
| [.github/workflows/ci.yml](.github/workflows/ci.yml) | GitHub Actions CI: three parallel jobs — **lint** (ruff), **type-check** (`mypy core/ --ignore-missing-imports`), **test** (pytest). Triggered on push and PR to main. The test job installs `pandas`, `plotly`, and `pytest`; lint and type-check install only their respective tool — heavy packages (streamlit, simod, prosimos) are not needed. |
| [core/constants.py](core/constants.py) | Cross-cutting constants only: twelve `COL_*` analysis column names (`cycle_h`, `cost`, their means, `total_cycle_s`, `total_cost`, their means, `rework_count`, `rework_rate`, their means); `KEY_RESOURCE_PROFILES` / `KEY_TASK_RESOURCE_DISTRIBUTION` (used in both `bpmn/utils.py` and `transformations.py`); and seven `F_*` Taguchi factor ID constants (`F_PCT_AUTO` … `F_NUM_CASES`) consumed by `transformations.py`, `analysis.py`, and `demo.py`. Everything else lives in its home module. |
| [core/orchestrator.py](core/orchestrator.py) | Real-pipeline run loop only: pre-generates all scenario JSONs sequentially, then delegates parallel execution to `simulation.pool.run_all()`, collects results into a tidy DataFrame. Also runs the baseline (original, untransformed model) and returns mean total metrics + rework means for Panel 5. No demo awareness — `app.py` routes to `demo.run_experiment()` for demo mode. `ExperimentResult` dataclass carries `results`, `experiment_bpmn_path`, `scenario_json_paths`, `baseline_agg`, `scenario_log_paths` (`dict[str, list[Path]]`), and `baseline_log_paths` (`dict[int, list[Path]]`); new fields default to `{}` so `demo.py` needs no change. |
| [core/preflight.py](core/preflight.py) | Detects Python 3.9, Corretto 8 (auto-finds `C:\Program Files\Amazon Corretto\jdk1.8*`), and both venvs. Surfaces per-row fixes in the UI. |
| [core/transformations.py](core/transformations.py) | `Transformation` ABC + `XORSplitAutomation` impl + `REGISTRY` of available patterns. Also owns `AutomationParams(ScenarioParams)` — the typed simulation parameters for one XORSplitAutomation scenario; `BpmnTransformResult` — returned by `prepare_experiment()`, carries `bpmn_path`, `scenario_template`, `ids`, and `selected_resource_id`; `TransformIds` with computed properties `bot_resource_id`, `bot_resource_name`, and `bot_task_name`; and all XORSplitAutomation-specific constants: `BOT_*`, `GW*_NAME`, sequence flow display labels (`BOT_BRANCH_LABEL`, `HUMAN_BRANCH_LABEL`, `BOT_SUCCESS_LABEL`, `BOT_FAILURE_LABEL`), and Taguchi level lists. `F_*` factor ID constants live in `constants.py`. |
| [core/bpmn/\_\_init\_\_.py](core/bpmn/__init__.py) | BPMN XML namespace constants (`BPMN_NS`, `BPMNDI_NS`, `DC_NS`, `DI_NS`, `BPMN_TASK_TAGS`). |
| [core/bpmn/edit.py](core/bpmn/edit.py) | Low-level BPMN XML editing: DI shape/edge creation, process element insertion, sequence-flow rewiring. All `xml.etree.ElementTree` surgery lives here. |
| [core/bpmn/utils.py](core/bpmn/utils.py) | Read-only BPMN/Prosimos helpers: task-by-name lookup, `list_activities()`, `task_mean_duration_s()` for prepopulating Non-Auto-Time, resource helpers (`task_resources`, `shared_resource_ids`, `resource_pool_size`). |
| [core/simulation/runner.py](core/simulation/runner.py) | Subprocess wrappers: `discover()` (Simod one-shot, XES auto-converted to CSV first via stdlib `xml.etree.ElementTree`) and `simulate()` (Prosimos `start-simulation`). Stdout/stderr captured to log files via `_run_logged()`. |
| [core/simulation/store.py](core/simulation/store.py) | Experiment directory layout. Each run gets a timestamped folder under `runs/<exp-id>/`; subprocess logs co-located with CSV outputs. Export packaging: `json_zip(json_paths)` packs scenario params JSONs; `event_logs_zip(scenario_log_paths, baseline_log_paths)` packs Prosimos event log CSVs (scenarios under `scenarios/<sid>/rep_NNN_log.csv`, baseline under `baseline/cases_<n>/rep_NNN_log.csv`) using `z.write()` for disk-streaming rather than loading into memory; `group_zip(bpmn_path, json_paths, stats_csv)` bundles BPMN + params + statistics CSV. |
| [core/simulation/prosimos_edit.py](core/simulation/prosimos_edit.py) | Prosimos input-JSON mutation helpers — all schema knowledge lives here. `set_uniform`, `set_fixed`, `set_resource_amount` write distribution and pool values; `ensure_calendar`, `upsert_resource_in_profile`, `append_task_distribution`, `add_gateway_probs` handle structural additions. `KEY_RESOURCE_CALENDARS` and `KEY_GATEWAY_BRANCHING_PROBS` are module-level constants here. Mirrors `bpmn/edit.py` for JSON. |
| [core/simulation/pool.py](core/simulation/pool.py) | Parallel simulation executor. `SimulationTask` dataclass: `bpmn_path`, `json_path`, `n_cases`, `out_log`, `out_stat`, `proc_log`, `metadata`. `run_all(tasks, on_complete, max_workers=None, stop_check=None)` submits all tasks to a `ThreadPoolExecutor` (`max_workers` defaults to `os.cpu_count()`); `on_complete` is always called on the calling thread via `as_completed`, so callers can mutate shared state without locks. `stop_check` is a zero-argument predicate polled after each completed task — returns `False` when cancelled. Fails fast via `pool.shutdown(cancel_futures=True)` on first simulation failure. `subprocess.run()` in `runner.simulate` releases the GIL, giving true OS-level parallelism. `TASK_BASELINE`/`TASK_SCENARIO` discriminator constants live in `orchestrator.py`, not here. |
| [core/simulation/prosimos_csv.py](core/simulation/prosimos_csv.py) | Prosimos output reader: parses event-log CSV and stats CSV. `replication_metrics()` returns six per-replication metrics: `COL_CYCLE_H`, `COL_COST`, `COL_TOTAL_CYCLE_S`, `COL_TOTAL_COST`, `COL_REWORK_COUNT`, `COL_REWORK_RATE`. `_rework_metrics()` is the private DataFrame-level helper (called by `replication_metrics()` and tested directly). PROSIMOS_* format constants are defined inline here. |
| [core/experiment.py](core/experiment.py) | Hard-coded Taguchi L9, L18, and L27 arrays + `pick_array(n_factors)`. Supports up to 13 three-level factors. |
| [core/parameters.py](core/parameters.py) | `ScenarioParams` base class, `Parameter`, and `Scenario` dataclasses. `ScenarioParams` is the abstract base paired with `Transformation` — each concrete `Transformation` subclass has a corresponding `ScenarioParams` subclass that holds its typed simulation inputs. `Parameter` and `Scenario` live here as the parameterization layer. |
| [core/metrics.py](core/metrics.py) | Metric definitions — single source of truth for display names, units, and ranking config. `MetricDirection(str, Enum)` with `SMALLER_IS_BETTER`/`LARGER_IS_BETTER` values; a `str` subclass so it passes directly to `signal_to_noise(direction=...)` without conversion. `MetricSpec` NamedTuple: `column`, `display_name`, `decimal_places` required; `direction=SMALLER_IS_BETTER`, `display_fn=_id`, `delta_name=None`, `pct_change_name=None` defaulted — only the one spec that converts units (`_s_to_h`) needs an explicit `display_fn`. `PerCaseMetric` frozen dataclass: `results_column: str` (raw per-replication column, e.g. `COL_CYCLE_H`), `mean: MetricSpec`, `std: MetricSpec | None = None`. `Metric` frozen dataclass (`per_case: PerCaseMetric | None`, `aggregate: MetricSpec | None`, `rankable: bool` — required; `sn_floor: float = 0.0` — defaulted); exposes `per_case_column` and `per_case_display_name` properties as one-level accessors into `per_case.mean.*`. `MetricRegistry` namespace class holding `CYCLE_TIME`, `COST`, `REWORK_COUNT`, `REWORK_RATE` as class-level singletons; `all()`, `rankable()`, `by_column()` classmethods. Only `REWORK_RATE` sets `sn_floor=0.01`. |
| [core/analysis.py](core/analysis.py) | Pure analysis: `aggregate()`, `compare_to_baseline()`, `main_effects()` (Taguchi S/N), `rank(agg, goals)` (multi-goal weighted ratio scoring). `rank()` accepts `list[Goal]` from `core/goals.py`; emits a `{metric}_met` bool column per non-zero-weight goal, aggregate `goal_met` (AND of all per-goal columns), and `score = Σ weight_i × (metric_i / target_i)`; zero-weight goals are excluded from all three. `compare_to_baseline()` includes rework columns (`Rework Count`, `Δ Rework Count`, `Δ Rework (%)`, `Rework Rate (%)`, `Δ Rate (pp)`). No file I/O. `signal_to_noise(values, direction, floor)` takes `direction: MetricDirection` and `floor: float = 0.0`; the floor offsets values before the log so metrics that legitimately reach zero produce a finite S/N instead of NaN. `main_effects(results, metric: Metric)` reads direction and floor from the `Metric` object directly — callers pass one typed argument instead of three independent scalars that could be mismatched. `_factor_cols(df)` private helper returns non-metric columns; shared by `aggregate()` and `main_effects()` to eliminate the duplicated list comprehension. Imports `MetricDirection` and `Metric` from `metrics.py` and `Goal` from `goals.py` — permitted Layer 2 → Layer 1 dependencies. **`main_effects()` dtype note**: factor columns in the results DataFrame have mixed dtypes — integer-valued factors (e.g. `pct_auto` levels 25/50/75) land as `int64` while float-valued factors (e.g. `t_auto` levels 180.0/360.0/720.0) land as `float64`. When `main_effects()` collects group keys from different factor columns into one `level` column, pandas upcasts the whole column to `float64`, so integer levels appear as 25.0 rather than 25. Any display code consuming `main_effects()` output must handle this — use a helper like `_level_str` in `ui/plots.py` that converts whole-number floats to int strings before display. |
| [core/demo.py](core/demo.py) | Synthetic stand-in for the full simulation pipeline. `run_experiment(scenarios, n_reps, on_progress) -> ExperimentResult` owns the complete demo loop and produces all six metrics via synthetic formulas. `fake_discovery()` returns the activity list for the UI. `demo_baseline_agg()` returns a `baseline_agg`-shaped dict (keyed by `n_cases=1`) built from the hardcoded `BASELINE_*` constants — same shape as `orchestrator.run_experiment()` so `app.py` always routes through `baseline_per_case()` regardless of mode. All demo logic lives here — `orchestrator.py` has no demo awareness. |
| [core/goals.py](core/goals.py) | Layer 1 domain type for multi-goal ranking. `Goal` dataclass: `metric: str`, `weight: float`, `target: float` (absolute threshold in the same units as the metric column). `Goal.from_pct_reduction(metric, weight, pct, baseline_val)` converts a percentage-reduction target and a baseline value into an absolute `target`. `baseline_per_case(baseline_agg)` converts the orchestrator's `baseline_agg` dict (aggregate totals keyed by `n_cases`) into per-case metric values, picking the smallest `n_cases` level as representative — per-case metrics are scale-independent across levels up to simulation variance. |
| [ui/runner.py](ui/runner.py) | Background experiment runner for the Streamlit UI. `RunState` holds in-flight progress fields (`done`, `total`, `label`, `rep`) mutated by `on_progress` from the worker thread. `RunOutcome` holds terminal state (`result`, `error`, `cancelled`) — set atomically on the pre-allocated `RunState.outcome` field when the worker finishes (`None` = still running). `start_experiment(ss, fn)` launches a daemon thread; `cancel_experiment`, `commit_result`, `clear_run`, `current_run` are the public lifecycle API. `commit_result(ss, result)` writes all `ExperimentResult` fields into session state — the positive counterpart to `_clear_results()` in `app.py`. No `st.*` API calls are made from the background thread. |
| [ui/goals.py](ui/goals.py) | `GoalOption` NamedTuple (`default_pct`, `default_weight`, `step`, `allow_zero`) and `GOAL_OPTIONS: dict[Metric, GoalOption]` keyed by `MetricRegistry` metric singletons. Config only — no `st.xxx()` calls. The sidebar (in `app.py`) renders a `st.multiselect` to enable 1–3 goals followed by a 3-column pct/weight table for the active subset; option defaults are read from `GOAL_OPTIONS`. The goal column is read from `metric.per_case_column` at the call site. |
| [ui/widgets.py](ui/widgets.py) | `level_input_kwargs(kind, value)` maps `Parameter.kind` to `st.number_input` constraints (min/max/step/format) for the factor-levels panel. |
| [ui/plots.py](ui/plots.py) | Plotly chart helpers for Panel 4: `factor_label_map(params)` maps `Parameter.id → Parameter.label`; `main_effects_chart(me, label_map, metric_label)` returns a faceted line chart of factor-level means (one facet per factor, categorical X-axis sorted by numeric value, independent Y-axes per facet). |
| [ui/table.py](ui/table.py) | `prepare_ranked_display(ranked, goals, params, show_factors) → pd.DataFrame` — inclusion-based table prep for Panel 4. Defines an ordered list of (src_col, display_name) pairs for exactly the columns that belong in the display (rank, Scenario, factor cols when shown, per-case KPI means, per-goal met flags); selects those columns, maps bool→✓/✗ on met columns, inserts `rank`, and renames. No `st.xxx()` calls — returns a plain DataFrame. New columns added to `ranked` by future features will not appear unless explicitly listed here. |
| [samples/IssueTracker.xes](samples/IssueTracker.xes) | 100k-event synthetic log used for testing. Borrowed from the pm4py-ucm project. |
| [mockups/](mockups/) | Three early HTML UI mockups (wizard / dashboard / tabbed). Kept as design history. |
| [tools/simod-venv/](tools/simod-venv/) | (not committed) Python 3.9 venv with `simod` + `pip.ini` trusted-host workaround. |
| [tools/prosimos-venv/](tools/prosimos-venv/) | (not committed) Python 3.9 venv with `prosimos`. |

## 4. The current substitution pattern (`XORSplitAutomation`)

For a target activity *Act*, the pattern produces this fragment:

```
  ─►(XOR1)──%Auto──►[Auto Act]──►(XOR2)──%OK──────────────────►(XOR4)─►
        │                              │
      100-Auto                      100-OK
        │                              │
        └──────────►(XOR3)◄────────────┘
                      │
                      ▼
                    [Act] (the original, non-automated path) ──►(XOR4)
```

**Seven factors** (`parameters()` declares them; UI auto-renders). Seven factors → L27 OA → 27 scenarios.

| Factor | Default levels | Meaning |
|---|---|---|
| `pct_auto` (%) | 25 / 50 / 75 | XOR1 branch probability to the automated task |
| `pct_ok` (%) | 80 / 90 / 95 | XOR2 success probability (skip the fallback) |
| `t_auto` (s) | 5%, 10%, 20% of Simod mean | Automated task mean duration |
| `t_manual` (s) | 80%, 100%, 120% of Simod mean | Non-automated mean (**prepopulated from Simod**) |
| `num_bots` | 1 / 2 / 3 | Bot resource pool size |
| `num_manual_resources` | 1 / 2 / 3 | Human resource pool size |
| `num_cases` | 100 / 500 / 1000 | Cases per Prosimos replication (simulation scale) |

`apply()` does:
- **BPMN**: rewires the target task's incoming → XOR1 and outgoing ← XOR4;
  adds 4 exclusive gateways, 1 task (`"Auto " + original name`), and 7 new
  `<sequenceFlow>` elements. Uses `xml.etree.ElementTree`; preserves the default BPMN namespace.
- **JSON**: keeps the original task's `task_resource_distribution` entry but
  replaces its duration with a small-jitter uniform around `t_manual`. Clones
  the resources list into a second entry for the new `Auto` task with
  uniform around `t_auto`. Appends **four** entries to
  `gateway_branching_probabilities`: XOR1 (split) and XOR2 (split) carry
  scenario-specific probabilities; XOR3 and XOR4 (merges) always carry
  `value: 1.0`. **All four are required** — Prosimos validates that every
  gateway has an explicit probability entry and will reject the params JSON
  if any are missing, even for single-path merges.

**Known limitation:** only tasks with exactly one incoming + one outgoing
sequenceFlow are supported. Tasks fed directly by gateways need a more
careful wiring strategy — `apply()` raises `NotImplementedError` so this
fails loudly rather than producing a broken model.

**Multi-resource design decision:** a target activity may have multiple resources
assigned, but they are always of the same type (all human OR all bot — never mixed).
Rather than scaling all resources together, the UI lets the user pick which single
resource's pool to vary via the `num_manual_resources` factor. Shared resources
(assigned to more than one task) are shown but disabled in the selector — changing
their pool size would affect other tasks and is considered out of scope. If all
resources on the task are shared, `num_manual_resources` is frozen at its current
Prosimos value and excluded from the Taguchi OA. The selected resource ID is passed to `prepare_experiment()`, carried through
`BpmnTransformResult.selected_resource_id`, and forwarded to
`AutomationParams.selected_resource_id` via `params_from_values()`.
`None` means skip the pool resize (leave the human resource pool unchanged).

## 5. Hard-won setup caveats (Windows)

Captured from the bootstrap session — flag these in any new install guide.

1. **Simod requires Python 3.9 + Java 8.**
   - `winget install Python.Python.3.9 --source winget` (the msstore source
     fails certificate verification — `--source winget` is mandatory).
   - `winget install Amazon.Corretto.8.JDK --source winget`.
   - Do **not** set system `JAVA_HOME` to Corretto 8 — the runner injects it
     only into Simod's subprocess via the `JAVA_HOME` override field. Other
     tools on this machine still use the system Java.

2. **TLS-inspecting middlebox.** Fresh Python 3.9 `pip` fails SSL verify
   even after upgrading certifi. The fix shipped in
   [tools/simod-venv/pip.ini](tools/simod-venv/pip.ini) and
   [tools/prosimos-venv/pip.ini](tools/prosimos-venv/pip.ini): pin
   `trusted-host = pypi.org files.pythonhosted.org pypi.python.org`. Without
   it, `pip install simod` will hang on retries forever.

3. **Prosimos needs a tz-aware `--starting_at`.** Passing
   `"2025-01-01T00:00:00"` (naive) crashes inside
   `simulation_stats_calculator.py` comparing naive vs aware datetimes. The
   runner now defaults to `"2025-01-01T00:00:00+00:00"`. Don't drop the
   offset.

4. **Simod accepts CSV only.** XES inputs are converted by
   `runner.xes_to_simod_csv()` using stdlib `xml.etree.ElementTree` (XES is
   well-specified XML; no pm4py needed). The XES from pm4py-ucm has only
   `complete` events, so `start_time` is synthesized per case from the
   previous event's `end_time` (zero-duration for the first event). The
   parser expects namespace `http://www.xes-standard.org/` and raises a clear
   `ValueError` for empty logs or events missing `time:timestamp`.

## 6. The Streamlit rerun trap (the bug that bit us twice)

Streamlit re-runs the whole script top-to-bottom on **every widget
interaction**, even while a long synchronous subprocess is mid-flight.

In our first guard, the upload fingerprint was set *after*
`runner.discover()` returned. During the 2-minute Simod run, any browser
refresh restarted the script, saw `log_fingerprint == None`, and kicked off
another concurrent Simod. We caught one occurrence at **six** concurrent
Simod processes started inside seven seconds.

The current guard (in [app.py](app.py)):
1. Sets `ss.log_fingerprint` and `ss.discovering = True` **before** the
   subprocess call.
2. While `ss.discovering`, the UI shows "discovery is already running" with
   a **Cancel** button instead of starting a second one.
3. A `finally:` block guarantees the lock clears on failure.

**Rule for the codebase: any time you add a synchronous subprocess call
triggered by a widget, claim a session-state lock before the call, not
after.**

## 7. Running locally

Once-only setup (after cloning):

```powershell
winget install Python.Python.3.9        --source winget --silent
winget install Amazon.Corretto.8.JDK    --source winget --silent

py -3.9 -m venv tools\simod-venv
py -3.9 -m venv tools\prosimos-venv
# Copy the trusted-host pip.ini from this repo (preserved across clones)
.\tools\simod-venv\Scripts\pip install simod
.\tools\prosimos-venv\Scripts\pip install prosimos

# host Python (3.12+) for Streamlit itself:
pip install -r requirements.txt
```

Run:

```powershell
python -m streamlit run app.py
```

Then in the browser: toggle **Demo mode** off, upload
`samples/IssueTracker.xes`, pick `Fix Bug` as the target, click ▶ Run.

Dev commands (no external tools required):

```powershell
pytest                                 # run test suite (demo mode only — no Simod/Prosimos required)
ruff check .                           # lint
mypy core/ --ignore-missing-imports    # type-check (--ignore-missing-imports suppresses missing stub warnings)
```

## 8. What's worth doing next

Known bugs / reliability gaps:

- **Incomplete cases in cycle time** (`core/simulation/prosimos_csv.py`): `replication_metrics()` computes
  cycle time as `max(end_time) − min(start_time)` over all cases with no filter for
  completion. Currently safe because Prosimos runs until `--total_cases N` cases
  **complete**, so the output log should never contain truncated cases. If that
  assumption ever breaks, a partial fix (filter cases with any NaT `end_time` from
  the event log) would correct `COL_CYCLE_H` and rework metrics but break the
  stats-CSV-derived metrics: `COL_COST = COL_TOTAL_COST / n_cases` would use a
  contaminated total (the stats CSV aggregates across all Prosimos cases with no
  case-level breakdown) divided by a smaller filtered N, inflating per-case cost.
  `COL_TOTAL_CYCLE_S` and `COL_TOTAL_COST` would remain wrong for the same reason.
  A complete fix requires computing all metrics from the event log (first principles),
  which is not currently worth the complexity given the Prosimos guarantee.
Design decisions:

- **Per-case vs aggregate ranking** (`core/analysis.py`, `app.py`): `rank()` uses per-case metrics (`COL_CYCLE_H_MEAN`, `COL_COST_MEAN`, `COL_REWORK_RATE_MEAN`) rather than aggregate totals (`COL_TOTAL_CYCLE_S_MEAN`, `COL_TOTAL_COST_MEAN`). These are NOT equivalent when `num_cases` is a Taguchi factor. Example: scenario A (`num_cases=1000`, `cycle_h_mean=5h`) has a much larger total cycle time than scenario B (`num_cases=100`, `cycle_h_mean=6h`), so aggregate ranking would prefer B even though A is more efficient per case. Per-case ranking is scale-independent and correctly isolates the automation pattern's efficiency from the simulation scale factor. Aggregate columns ("Total Cycle Time (h)", "Total Cost ($)") are therefore excluded from Panel 4's ranked table — they are misleading for cross-scenario comparison and belong in Panel 5's baseline comparison view, where each `num_cases` level is compared against its own baseline.
- **Multi-goal weighted ranking** (`core/analysis.py`, `core/goals.py`, `ui/goals.py`, `app.py`): `rank(agg, goals)` accepts all three goals simultaneously, each with an independent percentage-reduction target and weight. `score = Σ weight_i × (metric_i / target_i)` — lower is better; `goal_met = True` only when every non-zero-weight goal is individually satisfied. Zero-weight goals are excluded from score, `goal_met`, and per-goal columns. Per-goal `{metric}_met` bool columns (e.g. `cycle_h_mean_met`) are emitted by `rank()` for each non-zero-weight goal; `app.py` formats them as ✓/✗ and names them via `MetricRegistry.by_column()` display names (e.g. "Cycle Time (h/case) ✓"). The aggregate `goal_met` column drives sort order and is dropped from the display — per-goal columns make it redundant. Targets are percentage reductions from baseline (clamped to 0–99% via widget `max_value` to prevent division by zero at 100%) — converted to absolute thresholds at ranking time via `Goal.from_pct_reduction()`. Weights sum to ~1 by convention; a `st.warning` fires when `|sum − 1| > 0.01` — the score is still well-defined with any positive weights, so no enforcement gate is applied. `baseline_per_case()` in `core/goals.py` derives per-case baseline values from the orchestrator's `baseline_agg`; `demo.demo_baseline_agg()` returns the same shape so `app.py` has a single call site: `baseline_per_case(ss.baseline_agg or demo.demo_baseline_agg())`. The goals sidebar section is gated on `ss.activities` — it is hidden until discovery completes (demo or real); `_goal_specs` is initialised as `[]` before the gate so Panel 4 always has a defined list.
- **Results panel recomputation**: `analysis.aggregate()` and `analysis.main_effects()` are called unconditionally on every Streamlit rerun while results exist (no caching). At current scale (L27 × ~5 reps = ~135 rows) the groupby is negligible. If replications are scaled up (client cited 30 reps → ~810 rows) and the results panel becomes sluggish, cache `agg` in session state keyed by `id(ss.results)`, or apply `@st.cache_data` to the analysis functions.
- **Constants placement strategy**: `constants.py` holds only the constants consumed by two or more otherwise-unrelated modules: twelve `COL_*` analysis column names; the two `KEY_*` Prosimos JSON keys (`KEY_RESOURCE_PROFILES`, `KEY_TASK_RESOURCE_DISTRIBUTION`) consumed by both `bpmn/utils.py` and `transformations.py`; and the seven `F_*` Taguchi factor ID constants consumed by `transformations.py`, `analysis.py`, and `demo.py`. Everything else lives in its home module — BPMN namespace constants in `bpmn/__init__.py`, Prosimos CSV format strings in `simulation/prosimos_csv.py`, Prosimos input-JSON key names used only within `prosimos_edit.py` (`KEY_RESOURCE_CALENDARS`, `KEY_GATEWAY_BRANCHING_PROBS`) as module-level constants there, and XORSplitAutomation-specific values (`BOT_*`, `GW*_NAME`, flow display labels, Taguchi level lists) in `transformations.py`. The rule: a constant belongs in `constants.py` only if removing it would require two or more otherwise-unrelated modules to import from each other.
- **`core/` subpackage structure**: `core/` is split into `bpmn/` (BPMN reading and editing) and `simulation/` (Prosimos/Simod subprocess wrappers, store, output parsing). The flat modules (`bpmn_edit.py`, `bpmn_utils.py`, `runner.py`, `store.py`, `prosimos_csv.py`) were merged into these subpackages. `list_activities` moved from `simulation/runner.py` to `bpmn/utils.py` since it reads BPMN XML, not a subprocess concern. `analysis.py`, `transformations.py`, `orchestrator.py`, and the dataclass modules remain at the top level of `core/` because they don't belong cleanly to either subpackage.
- **`prosimos_edit.py` extraction from `transformations.py`**: `core/simulation/prosimos_edit.py` owns all Prosimos input-JSON schema knowledge, mirroring `bpmn/edit.py` for BPMN XML. A second Transformation pattern will never be added, so the original "wait for a second pattern" argument is moot; the extraction is justified by the existing architectural boundary. Precise split: `prosimos_edit.py` receives `set_uniform`, `set_fixed`, `set_resource_amount`, and named helpers for the calendar/resource-profile/task-distribution/gateway-probability dict shapes currently inline in `build_scenario_template` and `apply_params`. `transformations.py` keeps the `Transformation` ABC (typed by `orchestrator.py`), `XORSplitAutomation`, all `BOT_*`/`GW*_NAME`/flow-label/`F_*` constants, and `build_scenario_template`/`apply_params` as thin orchestrators that delegate JSON surgery to `prosimos_edit`. `_xor_bypass_layout` stays in `transformations.py` — it is BPMN geometry coupled to `TransformIds`, not Prosimos JSON. Note: helpers in `prosimos_edit.py` have no `_` prefix because they are legitimately public within the package; `_write_distribution` retains `_` as the only truly private helper.
- **Rework KPI semantics** (`core/simulation/prosimos_csv.py`): two sources are counted process-wide per replication. (1) **Standard rework**: for every (case, activity) pair where the activity appears more than once, count `occurrences − 1`. A case visiting "Fix Bug" three times contributes 2. (2) **Bot-failure rework**: for every case where both `"Auto X"` and `"X"` appear (bot ran and failed, human redid the work), add 1. Neither activity repeats in this path so standard rework would not catch it. The two sources are additive without double-counting because they track different activity-name relationships. `COL_REWORK_RATE` is stored as a percentage (0–100) of cases with any rework (either source). pm4py was rejected: it provides only a binary per-case per-activity flag and no process-wide rate. `_rework_metrics(df, bot_task_name, original_task_name)` is the private DataFrame-level helper (called by `replication_metrics()` and tested directly). A missing `"activity"` column (e.g. synthetic test CSVs) returns `{rework_count: 0, rework_rate: 0}` rather than crashing.
- **`compare_to_baseline` and `aggregate` are data-driven** (`core/analysis.py`): `compare_to_baseline` iterates `MetricRegistry.all()` aggregate specs to build each display row — adding a new metric requires only a new `Metric` entry in `MetricRegistry`. `aggregate` uses pandas named-aggregation syntax (`output_col: (source_col, aggfunc)`) with no conditional guards; all six metric columns are always present in both the demo and real pipelines. `_pct_delta(delta, baseline)` returns `nan` when `baseline == 0` (mathematically undefined percentage, surfaced as a blank cell — the right call for a display helper, not a logic-error path that should raise).
- **`MetricRegistry` architecture** (`core/metrics.py`): `Metric` is a frozen dataclass composing `PerCaseMetric | None` and `MetricSpec | None` — composition over inheritance. `rankable: bool` and `sn_floor: float` both live on `Metric`, not `MetricSpec`: they are policy decisions about the metric as a whole, not properties of any particular representation. `rankable` controls whether the metric appears in the ranking dropdown; `sn_floor` controls whether zero is a valid outcome for S/N computation — both are domain facts true regardless of which column or aggregation you're looking at. `MetricDirection(str, Enum)` eliminates the magic strings `"smaller_is_better"`/`"larger_is_better"` while remaining compatible with `signal_to_noise(direction=...)` since `MetricDirection` is a `str` subclass. `_id` and `_s_to_h` are named functions (not lambdas) so they are picklable — relevant if `MetricSpec` objects ever pass through `multiprocessing` or `@st.cache_data`. `display_fn` and `direction` are defaulted fields on `MetricSpec` (`_id` and `SMALLER_IS_BETTER` respectively) so most specs need only three required fields. `GOAL_OPTIONS` is keyed by `Metric` objects — valid because frozen dataclasses with `NamedTuple` fields are hashable and `MetricRegistry` class-level constants are stable module-level singletons.
- **`COL_REWORK_RATE` stored as percentage (0–100) throughout `core/`** (`core/simulation/prosimos_csv.py`, `core/demo.py`): `_rework_metrics()` multiplies the fraction by 100 at the source; `BASELINE_REWORK_RATE = 5.0` in `demo.py` is in percentage units. Eliminates the former `GoalOption.scale=0.01` bridge and means all `display_fn` values for rework rate are `_id`. Tradeoff: changing storage unit required touching three modules — judged worthwhile because a fractional storage unit with display-time conversion is a leaky abstraction where every new consumer must know to multiply by 100.
- **Panel 4 ranked table column readability** (`app.py`): `scenario_id` column header renamed to `"Scenario"`. KPI columns renamed from raw column names (e.g. `cycle_h_mean`) to display names (e.g. `"Cycle Time (h/case)"`) via a rename map derived from `MetricRegistry.all()` — no second copy of labels. `cycle_h_std` and `cost_std` dropped from the table (hidden by default; future toggle tracked in `PerCaseMetric.std`). Factor columns renamed via `{p.id: p.label for p in params}` as before.
- **Demo extraction — `demo.run_experiment()` owns all synthetic logic** (`core/demo.py`, `core/orchestrator.py`, `app.py`): the original design threaded `demo_mode: bool` through `orchestrator.run_experiment()`, scattering `if demo_mode:` branches across the prepare, apply, simulate, and metric-collection steps. The practical consequence: adding any new metric to the demo required touching both `demo.py` (the formula) and `orchestrator.py` (the NaN placeholder), and `orchestrator.py` was never truly "the real pipeline" — it was the real pipeline plus a synthetic bypass. The refactor gives `demo.py` a public `run_experiment(scenarios, n_reps, on_progress) -> ExperimentResult` that owns the full synthetic loop; `orchestrator.run_experiment()` loses `demo_mode` and becomes a straight real-pipeline path; `app.py` makes one explicit routing decision at the call site. Key design choices: (1) `DemoResult` becomes private `_SimResult` with all six metric fields (`cycle_h`, `cost`, `total_cycle_s`, `total_cost`, `rework_count`, `rework_rate`) — `total_cycle_s = cycle_h × 3600 × n_cases`, `total_cost = cost × n_cases`, rework formula is `(pct_auto × (1 − pct_ok) + BASELINE_REWORK_RATE × (1 − pct_auto)) × noise`; (2) `baseline_agg` stays `None` in demo — Panel 5 is gated on real mode and demo baseline is a separate future enhancement; (3) `ExperimentResult` stays in `orchestrator.py` — `demo.py` imports from it without a cycle because `orchestrator.py` no longer imports from `demo`; (4) `fake_discovery()` stays public — `app.py` still needs it for the activity dropdown; (5) `TestDemoMode` in `tests/test_orchestrator.py` migrates to `tests/test_demo.py` and calls `demo.run_experiment()` directly.
- **`Parameter.id` carries no activity-name prefix** (`core/transformations.py`, `core/parameters.py`, `core/demo.py`, `core/analysis.py`): `Parameter.id` is a bare factor key (e.g. `"pct_auto"`) with no `"{activity}."` prefix. The prefix was removed because: (1) within a single experiment there is only ever one target activity, so the prefix adds no disambiguation; (2) it caused a double-prefix trap in `factor_label_map` where `p.id` already contained the full key but callers tried to prepend the target activity again; (3) it polluted the results DataFrame column names with the activity name, making them unreadable in the ranked table. The activity name is available in session state (`ss.target_activity`) for any display use. Factor IDs are defined as named constants (`F_PCT_AUTO = "pct_auto"` etc.) in `constants.py` — they're consumed by `transformations.py`, `analysis.py`, and `demo.py`, satisfying the cross-module rule. `AutomationParams.from_taguchi_values()` uses direct key lookup (`values.get(F_PCT_AUTO, default)`) rather than the previous suffix-scan (`k.endswith("." + suffix)`) which would have silently fallen back to defaults with bare keys. `analysis.py`'s `compare_to_baseline` identifies the cases column with `c == F_NUM_CASES` rather than `c.endswith(".num_cases")`.
- **Bot cost as experiment-wide input** (`app.py`, `core/transformations.py`, `core/orchestrator.py`, `core/demo.py`): `bot_cost_per_hour: float = 0.0` is treated as a scalar experiment config (like `n_reps`) rather than a Taguchi factor — it applies uniformly to every scenario and doesn't belong in the orthogonal array. Units are $/hr to mirror Simod's cost model. Default 0.0 preserves the prior zero-cost behaviour without a breaking change. Prosimos stores `cost_per_hour` as a string in the resource JSON (confirmed from Prosimos source); the conversion `str(bot_cost_per_hour)` happens at resource-dict construction in `build_scenario_template`. The demo formula replaces a prior magic `0.6` constant with a principled derivation: `expected_human_fraction = (1 − pct_auto/100) + (pct_auto/100) × (1 − pct_ok/100)` (humans handle all non-automated cases plus bot failures); `bot_cost_per_case = (pct_auto/100) × (t_auto / 3600) × bot_cost_per_hour`. This correctly models that bot failures redirect to the human path, avoiding silent cost underestimation at low `pct_ok` values.
- **`ScenarioParams` / `AutomationParams` pairing** (`core/parameters.py`, `core/transformations.py`): `Transformation` ABC is paired with `ScenarioParams` base class — each concrete `Transformation` subclass has a corresponding `ScenarioParams` subclass holding its typed simulation inputs. `AutomationParams` is `XORSplitAutomation`'s concrete params class; it lives in `transformations.py` alongside the pattern that owns it. `Transformation.apply_params` is typed `scenario: ScenarioParams`; the concrete override asserts `isinstance(scenario, AutomationParams)` at entry for runtime safety without narrowing the override signature (which mypy would flag as a Liskov violation). `AutomationParams` is derived FROM a `Scenario` (via `from_taguchi_values()`), not a sibling of it — it is the typed interpretation of a Scenario's raw Taguchi values for the XOR pattern. `ScenarioParams` is a plain base class (no abstract methods); it's a semantic marker, not a protocol. `params_from_values(values, result) -> ScenarioParams` on the ABC is the bridge that keeps `orchestrator.py` free of any concrete `AutomationParams` import — the orchestrator calls `transformation.params_from_values(s.values, bpmn_tr)` and never touches the subclass directly. `selected_resource_id` is a typed field on `BpmnTransformResult` (not an opaque `Any` context) because it is meaningful at the boundary and applies to any automation pattern that varies a human resource pool. n_reps does not go into `BpmnTransformResult` because the transformation layer never uses it — it is consumed entirely by the orchestrator's task-building loop.
- **Parallel simulation** (`core/simulation/pool.py`, `core/orchestrator.py`): all scenario and baseline replications execute in a single `ThreadPoolExecutor`. `subprocess.run()` in `runner.simulate` releases the GIL, giving true OS-level parallelism — `ThreadPoolExecutor` was chosen over `ProcessPoolExecutor` (no benefit for subprocess-bound work; adds serialization constraints) and `asyncio` (propagates `async def` through the call stack, risky Streamlit integration). Scenario JSONs are pre-generated sequentially before any worker starts — XML/JSON mutation is not thread-safe. `wait(FIRST_COMPLETED)` is iterated on the calling thread so `on_complete` and `on_error` can mutate shared state without locks; `wait()` replaces `as_completed()` to allow dynamic future re-submission for retries. Individual failures are retried up to `task.max_retries` times before calling `on_error` — see the failure recovery decision below. `_run_baseline()` was eliminated — baseline and scenario tasks share one pool. Progress total includes baseline runs (e.g. 900 at L27 × 30 reps, not 810).
- **`pool.py` extraction from `orchestrator.py`** (`core/simulation/pool.py`): execution details (thread pool, worker count, `as_completed`) are hidden from `orchestrator.py` behind `run_all(tasks, on_complete, on_error)`. `SimulationTask` carries the full per-replication context (`bpmn_path`, `json_path`, `n_cases`, output paths, typed `metadata`) so `on_complete` can read output files without needing a separate lookup. The fields mirror `runner.simulate`'s signature but `pool.py` treats them as a unit of work — it doesn't reason about BPMN paths or case counts, just forwards them. `metadata: Any` is intentionally opaque to the pool; the orchestrator sets and reads it, and the pool passes it back unchanged.
- **Simulation failure recovery — retry with continue-on-error fallback** (`core/simulation/pool.py`, `core/orchestrator.py`, `app.py`): `SimulationTask` carries `max_retries: int = 0`; `run_all()` decrements it on failure and re-submits the task to the same pool via `dataclasses.replace`. Only when `max_retries` reaches 0 does `on_error` fire. The orchestrator passes `max_retries=2` (3 total attempts) to every task, configurable via `run_experiment(max_retries=...)`. `on_error` is the continue-on-error fallback for permanently failing tasks: the orchestrator's `_on_error` closure appends a `FailedReplication(scenario_id, rep, error)` and ticks progress. After all tasks finish: if every scenario replication permanently failed (empty `rows`), `SimulationError` is raised; otherwise a partial `ExperimentResult` is returned with `failed_replications` populated. `baseline_agg` is returned as `None` (not `{}`) when all baseline replications fail — an empty dict is falsy and would cause `ss.baseline_agg if ss.baseline_agg is not None else demo.demo_baseline_agg()` to silently substitute demo constants for goal targets in real mode; `None` is the unambiguous sentinel. Panel 4 shows a `st.warning` when `ss.failed_replications` is non-empty; Panel 5 shows an explicit `st.warning` in real mode when `baseline_agg is None`. Disk-based checkpoint/resume was considered and rejected: requires a resume UI surface, session-state matching across runs (fragile when the user changes params), and significant infrastructure. `FailedReplication.task_kind` deliberately omitted — callers test `fr.scenario_id == "baseline"` to distinguish. Typed metadata: `BaselineMeta(n_cases, rep)` (frozen=True) and `ScenarioMeta(scenario_id, rep, values: dict[str, object])` (plain `@dataclass` — `frozen=True` on a class with a mutable dict field only prevents field rebinding, not dict mutation, giving a false safety guarantee) replace opaque tuples. `_on_complete` dispatches on `isinstance(meta, BaselineMeta)` directly with `assert task.out_stat is not None` hoisted above the branch; `_unpack_meta` is retained only for `_on_error`. `run_all()` wraps the entire callback dispatch block in `try/except Exception: pool.shutdown(cancel_futures=True); raise`, restoring the cancel-pending-on-callback-exception behaviour from the prior `as_completed` implementation. `TASK_BASELINE`/`TASK_SCENARIO` module-level string constants removed — dead code after the typed dataclass refactor. A shared `_tick(label, rep)` inner function eliminates the duplicated progress-tail.
- **New module creation rule**: prefer a new file when the concern is genuinely distinct enough to deserve its own mental model — a clear boundary (domain type, display context, execution concern) earns a new module. The trigger is whether the concern has a distinct identity, not whether the code is extractable. A small helper with no distinct purpose belongs in the nearest related existing module; non-trivial logic with a clear boundary belongs in its own file. Module boundaries are cheap to reason about but expensive to dissolve later — err on the side of separation when the identity is clear.
- **Main-effects chart in `ui/plots.py`** (`ui/plots.py`, `app.py`): chart logic lives in a dedicated `ui/plots.py` module (two public functions: `factor_label_map` and `main_effects_chart`). The module is justified because Plotly chart construction is a distinct display concern with its own identity — layout config, facet title cleanup, categorical axis handling — separate from widget and table concerns. The chart plots `mean` on the Y-axis only; `sn` (Signal-to-Noise ratio) is computed in `main_effects()` output but not yet displayed — it is ready to surface once a chart toggle is added. `factor_label_map` translates `Parameter.id` values to `Parameter.label` strings using the `params` list already in scope at the call site. The X-axis uses categorical strings sorted by numeric value before string conversion — this guarantees ascending display order regardless of how the user assigned level 1/2/3, and avoids Plotly treating numeric-looking strings as a linear axis (which would auto-generate ticks at round numbers rather than at data points). `type="category"` is set explicitly on all x-axes for the same reason. The `st.dataframe` tables in the three main-effects tabs in Panel 4 are replaced entirely by `st.plotly_chart` — the chart conveys the same information more compactly, and keeping both would make the panel excessively long.
- **Law of Demeter fixes and `results_column` on `PerCaseMetric`** (`core/metrics.py`, `core/analysis.py`, `app.py`): `PerCaseMetric` carries `results_column: str` — the raw per-replication source column (e.g. `COL_CYCLE_H`) that `main_effects()` groups on, distinct from `mean.column` (e.g. `COL_CYCLE_H_MEAN`) which is the aggregated output column. This closes a type-system gap: previously `app.py` maintained an explicit `(Metric, raw_col)` tuple list because the mapping from `Metric` to its raw column was expressed nowhere. `Metric` exposes `per_case_column` and `per_case_display_name` properties, reducing five three-level navigation chains (`_m.per_case.mean.*`) in `app.py` to one-level accessors. `main_effects()` signature changed to `(results, metric: Metric)` — it reads `metric.per_case.results_column`, `metric.per_case.mean.direction`, and `metric.sn_floor` internally, so callers pass one typed argument instead of three independent scalars that could be mismatched. `_factor_cols(df)` private helper extracted in `analysis.py` eliminates the duplicated list comprehension across `aggregate()` and `main_effects()`. The LoD principle applied: don't navigate through intermediate objects to retrieve a value the containing object should expose directly. Properties on `Metric` are domain-neutral (not UI-shaped) — the boundary is navigating *to* `MetricSpec`, not accessing fields *on* it once received.
- **Inclusion-based ranked table in `ui/table.py`** (`ui/table.py`, `app.py`): Panel 4's ranked table was previously built by exclusion — start with all columns in `ranked`, drop std columns, drop aggregate columns, drop factor columns when hidden, drop `goal_met` and `score`, then rename. This required exclusion lists that silently accumulated whenever new columns were added to `ranked`. `prepare_ranked_display()` in `ui/table.py` replaces this with an ordered inclusion list: (src_col, display_name) pairs for exactly what belongs in the display. New columns added to `ranked` by future features are invisible in the table unless explicitly listed. `app.py` Panel 4 reduces to `rank()` + checkbox + `st.dataframe(prepare_ranked_display(...))`. The function contains no `st.xxx()` calls and returns a plain DataFrame — same justification as `ui/plots.py`: display-preparation logic with a distinct identity, testable in isolation without Streamlit.

- **Event log export** (`core/orchestrator.py`, `core/simulation/store.py`, `app.py`): Prosimos writes event log CSVs to disk for every replication (both scenario and baseline) via `SimulationTask.out_log`. `ExperimentResult` now tracks these as `scenario_log_paths: dict[str, list[Path]]` and `baseline_log_paths: dict[int, list[Path]]`, populated in `_on_complete` alongside metric parsing. `store.event_logs_zip()` packages them using `z.write()` (disk-to-ZIP streaming) rather than `z.writestr()` used for small param JSONs — log files can be large. ZIP structure mirrors the on-disk layout: `scenarios/<sid>/rep_NNN_log.csv` and `baseline/cases_<n>/rep_NNN_log.csv`. The export button is a separate "Event logs (ZIP)" in Panel 4's export row (not merged into "Model (ZIP)") — event logs are raw simulation output, not model artifacts. Disabled in demo mode (no real Prosimos output). Button label separation: "Params (ZIP)" for scenario params JSONs, "Model (ZIP)" for BPMN + params + stats, "Event logs (ZIP)" for log CSVs — three distinct scopes.
- **Session state helpers** (`app.py`): the app has four implicit states — IDLE (no log), DISCOVERED (log + activities), RUNNING (background thread alive), DONE (results present). `_clear_results()` resets all run-level keys (`results`, `experiment_bpmn_path`, `scenario_json_paths`, `baseline_agg`, `scenario_log_paths`, `baseline_log_paths`, `failed_replications`); `_clear_log()` calls `_clear_results()` then resets log-level keys (`log_name`, `log_path`, `activities`, `bpmn_path`, `json_path`, `log_fingerprint`). "Reset log" calls `cancel_experiment(ss)` before `_clear_log()` — `cancel_experiment` is a no-op when no run is active, so the reset path is safe regardless of state; without it a background thread could complete and write its result back into `ss.results`, silently undoing the reset. `_clear_results()` is also called at run start so Panel 4 goes blank immediately rather than showing stale results. New session state keys belong in one of these helpers, not scattered across reset sites. A formal FSM library would be overkill for four states.
- **`RunOutcome` discriminated union and `commit_result` helper** (`ui/runner.py`, `app.py`): `RunState` previously mixed in-flight progress fields with terminal outcome fields (`result`, `error`, `cancelled`), forcing `_panel3` to do a two-phase check: `current_run(ss)` (was a run started?) + `is_running(ss)` (is the thread still alive?). `RunOutcome` dataclass holds the terminal fields; `RunState.outcome: RunOutcome | None` starts as `None` (running) and is set atomically by the worker via a single attribute assignment (GIL-safe). `_panel3` checks `_rs.outcome is None` instead of `is_running(ss)` — one check replaces two, and the state machine is self-documenting. `is_running()` removed (no callers). `commit_result(ss, result: ExperimentResult)` writes all six result fields into session state, replacing the 6-field unpack block in `_panel3`. It lives in `ui/runner.py` because it is the positive counterpart of `clear_run` — both enumerate the same lifecycle keys, and `ui/runner.py` already imports `ExperimentResult`. Explicit `_target`/`_selected_resource_id` snapshots added before `def _fn` in the real-mode closure, matching the existing `_bpmn_path`/`_json_path` pattern — all session-state-derived values captured into locals before the thread starts.
- **N-goal selector with per-slot metric dropdowns** (`app.py`, `ui/goals.py`): a `st.radio` (1 / 2 / 3, default 1, `label_visibility="collapsed"`) replaces the `st.multiselect` — goal count is now an explicit choice rather than a derived count from a selection. The radio label is collapsed because `st.subheader("Goals")` already titles the section. Each active slot renders a metric `st.selectbox` in the first column of a `[3, 2, 1.5]` column layout; uniqueness is enforced by sequential filtering: slot N's option list excludes metrics already chosen in slots 0…N-1. Stale session state keys (e.g. `goal_metric_1` holding a value that was just claimed by slot 0) are reset to the first available option before the widget renders. Pre-fills follow `GOAL_OPTIONS` insertion order (cycle time → cost → rework rate). Weight UI adapts per count: (1) one goal — no weight widget; `1.0` is appended to `_goal_specs` implicitly; (2) two or three goals share one `else:` branch — a single loop runs `range(_n_goals)` times; for two goals a `st.slider` (0.0–1.0, step 0.05, default 0.5) is rendered before the loop and the weight column shows `markdown` for slot 0 and `round(1 − w, 2)` for slot 1 (no widget, no session state); for three goals the weight column shows a `st.number_input` plus a post-loop sum warning. The per-slot body (avail filter, stale-key guard, `selectbox`, `pct` `number_input`, append) is not duplicated across the two counts. `_goal_specs` format is unchanged: `list[tuple[str, float, float]]` = (col, pct, weight); all downstream code in Panel 4 is unaffected. `ui/goals.py` is unchanged — `default_pct`, `default_weight`, and `step` are still consumed; the 2-goal slider default (0.5) is not metric-specific and lives inline in `app.py`. All `st.xxx()` calls stay in `app.py`; `ui/goals.py` remains config-only.

Feature work:

- **Cancel mid-run — cancellation latency in the real pipeline**: cancellation is implemented (`threading.Event` checked via `stop_check` predicate in `pool.run_all()`; demo mode checks at each replication). In the real pipeline, cancellation latency equals the duration of the longest currently-running Prosimos replication: `as_completed` only yields between task completions, and `cancel_futures=True` only cancels pending (not in-flight) tasks. Fixing this requires tracking Prosimos subprocess PIDs in `SimulationTask` and calling `process.kill()` on cancel — left as future work because it also requires cleanup of partial output files.
- **Real BPMN preview**: replace the activity dropdown with a clickable
  BPMN canvas (Mockup C had this idea). `bpmn-js` via a Streamlit custom
  component would do it.
- **Workload as a Taguchi factor** (`core/transformations.py`): add an 8th
  factor to `XORSplitAutomation.parameters()` representing demand conditions.
  The Prosimos parameter is `arrival_time_distribution` in the params JSON
  (key confirmed from a real scenario output). Two design approaches were
  considered and one was rejected:
  - **Rejected — vary mean inter-arrival time**: making the mean the factor
    (e.g. 50%, 100%, 200% of Simod's discovered value) makes `num_cases` and
    mean IAT redundant degrees of freedom — both independently control how many
    cases are processed per unit time. The two factors should be orthogonal
    in a Taguchi design, but with a fixed `num_cases`, changing mean IAT also
    changes resource utilization, which conflates "demand volume" with
    "demand pattern." Note: varying simulation wall-clock duration (which
    follows from changing mean IAT) does NOT itself make metrics incomparable —
    all four metrics are per-case or sums over N cases, not per wall-clock
    hour, and calendar effects (working hours) are IAT-independent because the
    fraction of arrivals hitting off-hours is determined by the calendar shape,
    not the arrival rate.
  - **Preferred — vary arrival variance (coefficient of variation)**: keep
    the Simod-discovered mean fixed; vary the spread across three ordered
    levels using coefficient of variation (CV = std / mean) as the common
    scale. Suggested levels: CV=0 (`fix`, deterministic), CV≈0.5 (`norm` or
    `uniform`), CV=1.0 (`expon`, Poisson). Fixing the mean keeps `num_cases`
    independent and tests the research question "does automation ROI hold under
    bursty demand?" without conflating variance with volume. The `kind` for
    this parameter would be `"categorical"` since levels select distribution
    shapes, not a numeric value. `apply_params()` would write both
    `distribution_name` and `distribution_params` into
    `arrival_time_distribution`.
  - **Potential implementation (either approach)**: separate the Taguchi factor
    from the distribution type. The factor levels contain only the numeric value
    that varies (mean IAT for a utilization approach, or CV for the variance
    approach). The distribution type is a `frozen=True` Parameter — visible in
    the UI so the user can change it, held constant across all scenarios, and
    excluded from the OA. Secondary distribution parameters are derived in
    `apply_params()` from the factor value and the frozen distribution type:

    | Distribution | Params derived from mean M, CV c | Constraints |
    |---|---|---|
    | `fix` | `value = M` | CV always 0; no CV input needed |
    | `expon` | `mean = M` | CV always 1.0; no CV input needed |
    | `norm` | `mean = M`, `std = M × c` | Negative samples occur at c ≳ 0.5 |
    | `uniform` | `min = M(1 − √3c)`, `max = M(1 + √3c)` | Requires c ≤ 1/√3 ≈ 0.577 |

    `expon` and `fix` are self-contained (Coefficient of Variation is implicit
    in the distribution). `norm` and `uniform` need a secondary CV input shown
    conditionally in the UI — this is a fixed experiment-wide config stored in
    session state, not a Taguchi factor.

  **Pending client confirmation** on two points: (1) whether the CV-based
  interpretation of "workload" matches their intent (alternative: they want
  volume, in which case `num_cases` and workload should be one degree of
  freedom — derive `num_cases = floor(fixed_window / mean_IAT)` and drop
  `num_cases` as a free factor); (2) the concrete CV levels and whether
  the Simod-discovered mean should be used as-is or adjusted.

## 9. Don't

- Don't reintroduce a `python -m simod` invocation — Simod's package has no
  `__main__.py`; only the `simod.exe` entry-point script works.
- Don't add a "discover on every interaction" code path. See §6.
- Don't add pm4py back to `requirements.txt` — XES parsing uses stdlib `xml.etree.ElementTree` and pm4py is no longer a dependency. If pm4py is needed for a future feature, import it inline and note why.
- Don't commit `runs/`, `tools/simod-venv/`, or `tools/prosimos-venv/`.
  `.gitignore` already excludes them; keep it that way.

---

*Initial scaffold + four wiring sessions (Simod → Prosimos → XORSplitAutomation
→ bug-fixes) completed against the IssueTracker synthetic log. Subsequent
sessions added `num_bots`/`num_manual_resources` as Taguchi factors (L18),
subprocess log capture, XML namespace centralisation in `constants.py`, and
dead-code removal (`new_id`, `Parameter.inject`, `store.ACTIVE` clobber).
Later sessions added code quality tooling (ruff, mypy), a full test suite,
export features (stats CSV, JSON zip, BPMN, group ZIP in Panel 4), GitHub
Actions CI, baseline comparison (Panel 5), Prosimos output parsing split into
`simulation/prosimos_csv.py`, and restructure of `core/` into `bpmn/` and
`simulation/` subpackages. Further sessions added `num_cases` as a Taguchi
factor (L27 OA, 27 scenarios), replaced pm4py with stdlib XML for XES parsing,
and hardened the XES parser against empty logs and missing timestamps (111 tests).
A refactor session extracted Prosimos JSON mutation helpers into `core/simulation/prosimos_edit.py`
(mirrors `bpmn/edit.py`), renamed `build_base_json` → `build_scenario_template` to avoid
ambiguity with the real baseline concept, fixed the bot task distribution bug (`set_fixed`
instead of `set_uniform` — bots are deterministic), and introduced `_write_distribution`
to eliminate the DRY violation. A follow-up session implemented the rework KPI: two new
metrics (`COL_REWORK_COUNT`, `COL_REWORK_RATE`) counting standard repeated-activity rework
and bot-failure rework (bot ran + human redid the work in the same case), wired through
`replication_metrics()`, `_run_baseline()`, `aggregate()`, and `compare_to_baseline()`.
A subsequent session added the rework goal option and main-effects tab: `GoalOption`
NamedTuple and `GOAL_OPTIONS` extracted to `ui/goals.py`; `level_input_kwargs` extracted
to `ui/widgets.py`; "Rework rate (%)" added as a third goal with `scale=0.01` and
`allow_zero=True`; a third main-effects tab added to Panel 4. A simplify pass removed
the dead `rework_metrics()` file-level wrapper, simplified `_rework_metrics` bot-failure
detection to index set operations, and refactored `_run_baseline` from four parallel
accumulator lists to `replication_metrics()` + `pd.DataFrame.mean()`.
A test-coverage session closed both documented test gaps: `TestMultiFlowNotImplemented`
added to `tests/test_transformations.py` (synthetic multi-incoming / multi-outgoing BPMN
fixtures, `match="expected 1 incoming"` for stability); rework columns merged into the
main `_results_df()` fixture and `_agg()`/`_baseline()` helpers in `tests/test_analysis.py`,
covering `COL_REWORK_COUNT_MEAN`/`COL_REWORK_RATE_MEAN` aggregation, rework delta
computations in `compare_to_baseline`, and `main_effects(results, COL_REWORK_RATE)`.
A refactor session replaced the manual `b_x`/`s_x`/`d_x` blocks in `compare_to_baseline()`
with a `_MetricSpec` NamedTuple and `_METRICS` descriptor list, and removed dead conditional
guards from `aggregate()` (all six metric columns are always present in both pipelines).
A feature session implemented the main-effects Plotly charts (`feature/main-effects-plot`): new `ui/plots.py` with `factor_label_map` and `main_effects_chart`; three `st.dataframe` tables in Panel 4 replaced with `st.plotly_chart`; `tests/test_plots.py` added (148 tests total). Several visual bugs fixed iteratively: linked X-axes causing near-vertical curves (`matches=None`), missing top-row tick labels (`showticklabels=True` on x-axes), top/bottom row overlap (`facet_row_spacing=0.2`), missing "Level" title on non-bottom rows (`title_text="Level"`), and Plotly treating numeric-looking strings as a linear axis (`type="category"` + sort before string conversion). CI updated to install `plotly` in the test job.
A refactor session removed the `"{activity}."` prefix from `Parameter.id` (`refactor/parameter-id-prefix`): seven `F_*` named constants added to `transformations.py` for Taguchi factor IDs; `parameters()` now uses bare `F_*` ids and drops the activity-name prefix from labels; `from_taguchi_values()` replaces the suffix-scan `_v()` helper with direct `values.get(F_PCT_AUTO, default)` lookups; `demo.py` imports and uses `F_*` constants; `analysis.py` replaces `c.endswith(".num_cases")` with `c == F_NUM_CASES`; all tests updated. A follow-up cleanup session disambiguated the `F_` prefix: flow display labels renamed from `F_BOT_BRANCH_LABEL` etc. to `BOT_BRANCH_LABEL` etc. so `F_` exclusively marks Taguchi factor ID constants; `target_activity` parameter prefixed with `_` in `XORSplitAutomation.parameters()` to signal it is unused by this implementation (required by the ABC contract).
A feature session introduced `core/metrics.py` as the single source of truth for metric display names, units, and ranking config (`feature/main-effects-plot` continuation): `MetricSpec` NamedTuple, `PerCaseMetric`/`Metric` frozen dataclasses, `MetricRegistry` namespace class with `CYCLE_TIME`/`COST`/`REWORK_COUNT`/`REWORK_RATE` singletons. `COL_REWORK_RATE` storage unit changed from fraction (0–1) to percentage (0–100) throughout `core/` — `_rework_metrics()` multiplies by 100 at the source, eliminating `GoalOption.scale=0.01`. `GoalOption` slimmed to `(default, step, allow_zero)` with `GOAL_OPTIONS` rekeyed from display-label strings to `Metric` objects. `compare_to_baseline` rewritten to iterate `MetricRegistry.all()` aggregate specs. Panel 4 ranked table: `scenario_id` → `"Scenario"`, KPI columns renamed via `MetricRegistry`, `cycle_h_std`/`cost_std` dropped. A follow-up refactor cleaned up `core/metrics.py`: `MetricDirection(str, Enum)` replaces magic direction strings; `_s_to_h` named function replaces the unpicklable `lambda v: v / 3600`; `rankable: bool` moved from `MetricSpec` (dead field — never read) to `Metric` (policy at the right level); `display_fn` and `direction` made defaulted fields on `MetricSpec` so most specs need only three required arguments (148 tests).
A session fixed Panel 4 column renaming (KPI rename map and `_agg_transforms` were built but discarded — now applied), corrected `total_cycle_s_mean` unit display (aggregate `display_fn` now applied to values, not just headers), and drove main-effects tab names and Y-axis labels from `MetricRegistry` instead of hardcoded strings. Fixed a verified L18 orthogonality bug: rows 13–18 had columns 2, 3, 4 cyclically permuted relative to the standard Taguchi table; corrected against published reference values (all three OAs now pass the mathematical orthogonality check).
A feature session implemented parallel simulation (`feature/parallel-simulation`): new `core/simulation/pool.py` with `SimulationTask`, `TASK_BASELINE`/`TASK_SCENARIO` constants, and `run_all()`. All 900 tasks (810 scenario + 90 baseline at L27 × 30 reps) submitted to one `ThreadPoolExecutor`; `_run_baseline()` eliminated. A subsequent refactor introduced `ScenarioParams` base class in `parameters.py` and renamed `AutomationScenario` → `AutomationParams` (inherits `ScenarioParams`), closing the `Any` type in `Transformation.apply_params`.
A fix session (`fix/no-resources-validation`) added a second guard in `build_scenario_template()`: raises `RuntimeError` when the task entry exists but has an empty `resources` list. Pairs with the existing "task missing" guard; closes the silent-skip path in `apply_params()`.
A refactor session (`refactor/factor-ids-to-constants`) moved all seven `F_*` Taguchi factor ID constants from `transformations.py` to `constants.py` — they are consumed by `transformations.py`, `analysis.py`, and `demo.py`, satisfying the cross-module rule. `orchestrator.py`'s `cases_levels` computation switched from `AutomationParams.from_taguchi_values(s.values).num_cases` to direct `int(s.values[F_NUM_CASES])` lookup, removing one concrete-type reference from the orchestrator (160 tests).
A refactor session (`refactor/transform-params-from-values`) eliminated the remaining `AutomationParams` import from `orchestrator.py`. Added abstract `params_from_values(values, result) -> ScenarioParams` to `Transformation` ABC; `XORSplitAutomation` implements it as a one-liner bridge to `from_taguchi_values()`. Added `selected_resource_id: str | None` as a typed field on `BpmnTransformResult`; `prepare_experiment()` now accepts and stores it. Orchestrator calls `transformation.params_from_values(s.values, bpmn_tr)` — no concrete subclass knowledge required. 4 new tests in `TestParamsFromValues` (160 tests).
A fix session (`fix/signal-to-noise`) addressed two S/N correctness gaps. (1) `signal_to_noise` and `main_effects` replace `kind: str` with `direction: MetricDirection` — the typed enum from `metrics.py` propagates all the way down from the call site in `app.py` (which reads `_metric.per_case.mean.direction`) through `main_effects` to `signal_to_noise`. `MetricDirection` is a `str` subclass so it passes to the function without conversion. (2) `signal_to_noise` gains `floor: float = 0.0`: values are offset by the floor before the log computation (`v + floor`), preventing NaN when a metric legitimately reaches zero. `Metric` gains `sn_floor: float = 0.0`; `REWORK_RATE` sets `sn_floor=0.01` (0.01% — below any realistic rework rate, preserving chart scale). `sn_floor` lives on `Metric` rather than `MetricSpec` because "can this metric reach zero?" is a domain fact about the metric as a whole, not a display-representation property — consistent with `rankable` living at the same level. `app.py` threads `floor=_metric.sn_floor` into `main_effects`; the now-unreachable NaN caption is removed. 2 new tests; 162 tests total.
A feature session (`feature/multi-goal-ranking`) replaced single-goal ranking with simultaneous weighted multi-goal ranking across all three metrics (cycle time, cost, rework rate). New `core/goals.py` (Layer 1): `Goal` dataclass with `metric`, `weight`, `target`; `Goal.from_pct_reduction()` converts percentage-reduction target + baseline value → absolute threshold; `baseline_per_case()` converts `baseline_agg` aggregate totals → per-case metric dict. `core/demo.py` adds `demo_baseline_agg()` returning a `baseline_agg`-shaped dict built from `BASELINE_*` constants (n=1 reference key), so `app.py` has a single call site `baseline_per_case(ss.baseline_agg if ss.baseline_agg is not None else demo.demo_baseline_agg())` — no parallel per-case conversion path. `core/analysis.py`: `rank()` signature changed from `(agg, goal_metric, goal_max)` to `(agg, goals: list[Goal])`; weighted-ratio score replaces single-metric threshold. `ui/goals.py`: `GoalOption` gains `default_pct`/`default_weight`; sidebar renders a 3-column table. `app.py`: goals section and Panel 4 ranking block updated; no domain formulas in the UI layer. `tests/test_analysis.py`: `TestRank` rewritten for multi-goal API; new `TestGoal` covers `from_pct_reduction` edge cases. 166 tests.
Three follow-up commits on `feature/multi-goal-ranking` closed the remaining design gaps. (1) Weight sum warning: `app.py` computes `sum(wt for _, _, wt in _goal_specs)` after the goal widget loop and fires `st.warning` when `|sum − 1| > 0.01` — informational only, no enforcement, score is still valid with any positive weights. (2) Per-goal met columns: `rank()` in `core/analysis.py` now emits a `{metric}_met` bool column for each non-zero-weight goal alongside the aggregate `goal_met`; `app.py` formats them as ✓/✗ and names them via `MetricRegistry.by_column().display_name + " ✓"`, replacing the single "Goals" column; 4 new tests cover column presence, per-goal values, independence from the aggregate, and zero-weight exclusion (170 tests). (3) Goals sidebar gate: goals section wrapped in `if ss.activities:` so it is hidden until discovery completes; `_goal_specs` initialised as `[]` before the gate so Panel 4 always has a defined list.
A fix session corrected `COL_CYCLE_H` from `.median()` to `.mean()` in both `per_log_metrics()` and `replication_metrics()` in `core/simulation/prosimos_csv.py`. The median did not satisfy the identity `total_cycle_s = cycle_h × n_cases × 3600` required for goal percentage targets (derived from `COL_TOTAL_CYCLE_S_MEAN / n_cases`) to be consistent with the ranked metric. Test renamed `test_cycle_time_median` → `test_cycle_time_mean`; value unchanged since the fixture used [2h, 4h] where median == mean (170 tests).
A refactor session (`fix/strict-cost-parsing`) deleted `per_log_metrics` (never called by the production pipeline — `orchestrator.py` always uses `replication_metrics`) and `_cost_from_rows` (lenient private helper that silently returned `None` on any stats CSV format change). `replication_metrics` now derives `COL_COST = COL_TOTAL_COST / n_cases` directly from the totals already parsed by `_totals_from_rows`, making cost strict by construction — a missing section or column raises `ValueError`, a missing file raises `FileNotFoundError`. The double-parse of `Individual Task Statistics` is eliminated. `TestPerLogMetrics` removed; `TestReplicationMetrics` gains `test_cycle_time_mean`, `test_cost_per_case`, `test_totals_consistent_with_total_metrics`, `test_missing_stats_file_raises`, `test_malformed_stats_raises` (169 tests). "Cost metric from first principles" removed from future work — Prosimos already handles cost correctly via `cost_per_hour` on resources; strict parsing makes format changes loud rather than silent.
A refactor session closed five Law-of-Demeter violations in the metrics layer: `results_column: str` added to `PerCaseMetric` (raw per-replication source column, distinct from the aggregated `mean.column`); `per_case_column` and `per_case_display_name` properties added to `Metric`; `main_effects()` signature changed from `(results, metric: str, direction, floor)` to `(results, metric: Metric)` reading direction and floor internally; `_factor_cols()` private helper extracted in `analysis.py` eliminating the duplicated list comprehension across `aggregate()` and `main_effects()`; `_per_goal_rename` reduced to one `by_column()` call per goal; `num_cases_col` lookup simplified from `next()` to `in` membership test (169 tests).
A refactor session extracted `prepare_ranked_display()` into new `ui/table.py`, replacing the exclusion-based Panel 4 table build (accumulate drop-lists for std/aggregate/factor/goal cols, rename) with an inclusion-based ordered column list. `app.py` Panel 4 reduces to three lines: `rank()`, checkbox, `st.dataframe(prepare_ranked_display(...))`. No `st.xxx()` calls in the new module — returns a plain DataFrame, testable in isolation (169 tests).
A refactor session (`refactor/session-state-machine`) introduced `_clear_results()` and `_clear_log()` helpers in `app.py`, replacing the 14-line ad-hoc key reset block with two self-documenting calls. "Reset log" now calls `cancel_experiment(ss)` before `_clear_log()` — closes the reset-while-running gap where the background thread could complete after a reset and silently write its result back into session state. `_clear_results()` is also called at run start so Panel 4 goes blank immediately rather than showing stale results from the prior run.
A feature session (`feature/flexible-goals`) added a `st.multiselect` above the goals pct/weight table in `app.py`, allowing users to enable any 1–3 subset of the three goals (default: all three). Options and labels come from `GOAL_OPTIONS.keys()` and `m.per_case_display_name` — no hardcoded strings. `_active` re-sorts by `GOAL_OPTIONS` insertion order to ensure stable table ordering. The pct/weight header, per-metric rows, and weight-sum warning are all gated on `_active` — no false "weights sum to 0.00" warning when selection is cleared. `ui/goals.py` remains config-only; all `st.xxx()` calls stay in `app.py` (169 tests unchanged — no analysis-layer change).
A refactor session (`refactor/simplify-cleanup`) applied three cleanups to `ui/runner.py` and `app.py`: (1) `RunOutcome` dataclass holds terminal run state (`result`/`error`/`cancelled`); `RunState.outcome: RunOutcome | None` replaces the three flat fields — worker sets it atomically when done, `_panel3` checks `_rs.outcome is None` instead of `is_running(ss)`, which is removed; (2) `commit_result(ss, result)` added to `ui/runner.py` — the positive counterpart of `clear_run`, collapsing the 6-field `ExperimentResult` unpack block in `_panel3` to one call; (3) explicit `_target`/`_selected_resource_id` locals added before `def _fn` in the real-mode closure, making all session-state-derived closure captures explicit (174 tests unchanged).
A feature session (`refactor/goals-n-selector`) replaced the `st.multiselect` goals UI with an n-goal selector: a `st.radio` (1/2/3, default 1) controls how many goals are active; each slot gets a per-slot metric `st.selectbox` with uniqueness enforced by sequential filtering (slot N's options exclude metrics already chosen above it); stale session state keys are reset before widget render. Weight UI adapts per count: 1 goal = no weight (implicit 1.0); 2 goals = `st.slider` for first weight, complementary `round(1−w, 2)` shown as markdown; 3 goals = current per-metric number_input fields + sum warning. `_goal_specs` format and all downstream Panel 4 code are unchanged. `ui/goals.py` unchanged (174 tests unchanged).
A quality cleanup pass on `refactor/goals-n-selector` applied two fixes: (1) merged the duplicate `elif _n_goals == 2` / `else: # 3 goals` branches into a single `else:` block — the per-slot loop runs `range(_n_goals)` times with an inline `if _n_goals == 2` check for the weight column, eliminating ~35 lines of duplicated column-header setup and per-slot loop body; (2) added `label_visibility="collapsed"` to `st.radio` — the "Goals" label was rendered twice because `st.subheader("Goals")` already titles the section. Also fixed an incidental label inconsistency: the 2-goal `pct` `number_input` was using `_m.per_case_column` directly where the 3-goal path used `_gcol`; the merged branch always uses `_gcol`. `core/simulation/store.py` `json_zip` lambda-returning-list mypy error fixed by replacing with a named `def _populate` function (174 tests unchanged).
A feature session (`feature/failure-recovery`) replaced fail-fast simulation with retry-then-continue-on-error. `SimulationTask` gains `max_retries: int = 0`; `run_all()` decrements and re-submits on failure (dynamic `wait(FIRST_COMPLETED)` loop replacing fixed `as_completed`), calling `on_error` only after retries are exhausted. The orchestrator adds `BaselineMeta`/`ScenarioMeta` typed dataclasses, `_tick(label, rep)` to eliminate the duplicated progress-tail, and `FailedReplication(scenario_id, rep, error)` to accumulate terminal failures; `SimulationError` is raised only when every scenario replication permanently fails. `ExperimentResult.failed_replications` carries the list; `commit_result` and `_clear_results` were updated; Panel 4 shows `st.warning` when failures occurred. `run_experiment()` gains `max_retries: int = 2` (3 total attempts per replication). A `/simplify` pass followed: `_unpack_meta` module-level helper eliminated duplicated isinstance dispatch; `_bot_task_name`/`_original_task_name` extracted as locals before closures (releasing `bpmn_tr` from closure scope); row dict simplified to `{**m}`; `_submit` moved inside `with` block; `_tasks(tmp_path, n, max_retries=0)` kwarg added, consolidating `TestRunAllRetry._task` helper. 5 new tests in `TestRunAllOnError`, 4 in `TestRunAllRetry` (`test_pool.py`), and 1 in `test_demo.py` (183 tests total).
A code-review session (`/code-review`) on `feature/failure-recovery` found and fixed six issues: (1) `baseline_agg` returned as `None` not `{}` when all baseline replications fail — empty dict is falsy, causing `ss.baseline_agg if ss.baseline_agg is not None else demo.demo_baseline_agg()` to silently use demo constants for goal targets in real mode; Panel 5 now shows an explicit warning when `baseline_agg is None` in real mode. (2) `run_all()` callback dispatch wrapped in `try/except Exception: pool.shutdown(cancel_futures=True); raise` — restores cancel-pending-on-callback-exception behaviour lost when `as_completed` was replaced. (3) `TASK_BASELINE`/`TASK_SCENARIO` string constants deleted — dead code after typed-dataclass refactor. (4) `frozen=True` removed from `ScenarioMeta` — only prevented field rebinding, not mutation of the `values: dict` field, giving a false safety guarantee (`BaselineMeta` retains `frozen=True`). (5) `_on_complete` dispatch inlined: single `isinstance(meta, BaselineMeta)` check replaces `_unpack_meta` call + second isinstance; `assert task.out_stat is not None` hoisted above the branch. (6) `_unpack_meta` retained for `_on_error` only (183 tests unchanged).
