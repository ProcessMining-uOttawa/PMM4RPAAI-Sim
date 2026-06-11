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
Ranking table + main-effects view + export (stats CSV, JSON zip, BPMN, group ZIP)
```

## 2. Architecture seams (the parts designed for "it will get more complex")

The whole point of the design is that **adding a new substitution pattern or
a new parameter should not require touching the runner, the UI, or the
Taguchi designer**. Three contracts make that work:

- **`Transformation`** ([core/transformations.py](core/transformations.py)) — abstract base:
  - `parameters(target_activity, current_duration_s) → list[Parameter]`
    declares the factors the pattern exposes. The UI auto-renders them; the
    Taguchi designer auto-fits an OA.
  - `apply(bpmn_in, json_in, target_activity, values, out_dir) → TransformResult`
    produces a mutated (BPMN, JSON) pair for one scenario. **All XML/JSON
    surgery for the pattern lives here, nowhere else.**
  - The only built-in today: `XORSplitAutomation` — the 4-gateway / 2-activity
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
| [app.py](app.py) | Streamlit dashboard (Mockup B): sidebar = experiment state + run config; 5 panels = Activity & pattern · Factor levels · Execution · Ranked scenarios · Baseline comparison. Panel 4 includes an export row: stats CSV, scenario JSON zip, BPMN, and group ZIP (all three combined). |
| [.github/workflows/ci.yml](.github/workflows/ci.yml) | GitHub Actions CI: three parallel jobs — **lint** (ruff), **type-check** (`mypy core/ --ignore-missing-imports`), **test** (pytest). Triggered on push and PR to main. The test job installs `pandas`, `plotly`, and `pytest`; lint and type-check install only their respective tool — heavy packages (streamlit, simod, prosimos) are not needed. |
| [core/constants.py](core/constants.py) | Cross-cutting constants only: twelve `COL_*` analysis column names (`cycle_h`, `cost`, their means, `total_cycle_s`, `total_cost`, their means, `rework_count`, `rework_rate`, their means) and `KEY_RESOURCE_PROFILES` / `KEY_TASK_RESOURCE_DISTRIBUTION` (used in both `bpmn/utils.py` and `transformations.py`). Everything else lives in its home module. |
| [core/orchestrator.py](core/orchestrator.py) | Real-pipeline run loop only: iterates scenarios × replications, calls `simulation.runner.simulate`, collects results into a tidy DataFrame. Also runs the baseline (original, untransformed model) before the scenarios and returns mean total metrics + rework means for Panel 5. No demo awareness — `app.py` routes to `demo.run_experiment()` for demo mode. |
| [core/preflight.py](core/preflight.py) | Detects Python 3.9, Corretto 8 (auto-finds `C:\Program Files\Amazon Corretto\jdk1.8*`), and both venvs. Surfaces per-row fixes in the UI. |
| [core/transformations.py](core/transformations.py) | `Transformation` ABC + `XORSplitAutomation` impl + `REGISTRY` of available patterns. Owns all XORSplitAutomation-specific constants inline: `BOT_*`, `GW*_NAME`, sequence flow display labels (`BOT_BRANCH_LABEL`, `HUMAN_BRANCH_LABEL`, `BOT_SUCCESS_LABEL`, `BOT_FAILURE_LABEL`), Taguchi factor IDs (`F_PCT_AUTO` … `F_NUM_CASES`), and Taguchi level lists. The `F_` prefix exclusively marks Taguchi factor ID constants; flow labels use no prefix. `TransformIds` has computed properties `bot_resource_id`, `bot_resource_name`, and `bot_task_name` (`"Auto " + task_name`). |
| [core/bpmn/\_\_init\_\_.py](core/bpmn/__init__.py) | BPMN XML namespace constants (`BPMN_NS`, `BPMNDI_NS`, `DC_NS`, `DI_NS`, `BPMN_TASK_TAGS`). |
| [core/bpmn/edit.py](core/bpmn/edit.py) | Low-level BPMN XML editing: DI shape/edge creation, process element insertion, sequence-flow rewiring. All `xml.etree.ElementTree` surgery lives here. |
| [core/bpmn/utils.py](core/bpmn/utils.py) | Read-only BPMN/Prosimos helpers: task-by-name lookup, `list_activities()`, `task_mean_duration_s()` for prepopulating Non-Auto-Time, resource helpers (`task_resources`, `shared_resource_ids`, `resource_pool_size`). |
| [core/simulation/runner.py](core/simulation/runner.py) | Subprocess wrappers: `discover()` (Simod one-shot, XES auto-converted to CSV first via stdlib `xml.etree.ElementTree`) and `simulate()` (Prosimos `start-simulation`). Stdout/stderr captured to log files via `_run_logged()`. |
| [core/simulation/store.py](core/simulation/store.py) | Experiment directory layout. Each run gets a timestamped folder under `runs/<exp-id>/`; subprocess logs co-located with CSV outputs. |
| [core/simulation/prosimos_edit.py](core/simulation/prosimos_edit.py) | Prosimos input-JSON mutation helpers — all schema knowledge lives here. `set_uniform`, `set_fixed`, `set_resource_amount` write distribution and pool values; `ensure_calendar`, `upsert_resource_in_profile`, `append_task_distribution`, `add_gateway_probs` handle structural additions. `KEY_RESOURCE_CALENDARS` and `KEY_GATEWAY_BRANCHING_PROBS` are module-level constants here. Mirrors `bpmn/edit.py` for JSON. |
| [core/simulation/prosimos_csv.py](core/simulation/prosimos_csv.py) | Prosimos output reader: parses event-log CSV and stats CSV. `replication_metrics()` returns six per-replication metrics: `COL_CYCLE_H`, `COL_COST`, `COL_TOTAL_CYCLE_S`, `COL_TOTAL_COST`, `COL_REWORK_COUNT`, `COL_REWORK_RATE`. `_rework_metrics()` is the private DataFrame-level helper (called by `replication_metrics()` and tested directly). PROSIMOS_* format constants are defined inline here. |
| [core/experiment.py](core/experiment.py) | Hard-coded Taguchi L9, L18, and L27 arrays + `pick_array(n_factors)`. Supports up to 13 three-level factors. |
| [core/parameters.py](core/parameters.py) | `Parameter`, `Scenario`, and `AutomationScenario` dataclasses. `AutomationScenario.from_taguchi_values()` bridges Taguchi output to simulation inputs. |
| [core/analysis.py](core/analysis.py) | Pure analysis: `aggregate()`, `compare_to_baseline()`, `main_effects()` (Taguchi S/N), `rank()` (single-goal: goals-met flag + ratio-to-target score). `compare_to_baseline()` includes rework columns (`Rework Count`, `Δ Rework Count`, `Δ Rework (%)`, `Rework Rate (%)`, `Δ Rate (pp)`). No file I/O. **`main_effects()` dtype note**: factor columns in the results DataFrame have mixed dtypes — integer-valued factors (e.g. `pct_auto` levels 25/50/75) land as `int64` while float-valued factors (e.g. `t_auto` levels 180.0/360.0/720.0) land as `float64`. When `main_effects()` collects group keys from different factor columns into one `level` column, pandas upcasts the whole column to `float64`, so integer levels appear as 25.0 rather than 25. Any display code consuming `main_effects()` output must handle this — use a helper like `_level_str` in `ui/plots.py` that converts whole-number floats to int strings before display. |
| [core/demo.py](core/demo.py) | Synthetic stand-in for the full simulation pipeline. `run_experiment(scenarios, n_reps, on_progress) -> ExperimentResult` owns the complete demo loop and produces all six metrics via synthetic formulas. `fake_discovery()` returns the activity list for the UI. All demo logic lives here — `orchestrator.py` has no demo awareness. |
| [ui/goals.py](ui/goals.py) | `GoalOption` NamedTuple (`col`, `default`, `scale`, `step`, `allow_zero`) and `GOAL_OPTIONS` dict mapping display label → GoalOption for the sidebar goal selector. `scale` bridges user input units to stored column units (e.g. percentage → fraction for rework rate). |
| [ui/widgets.py](ui/widgets.py) | `level_input_kwargs(kind, value)` maps `Parameter.kind` to `st.number_input` constraints (min/max/step/format) for the factor-levels panel. |
| [ui/plots.py](ui/plots.py) | Plotly chart helpers for Panel 4: `factor_label_map(params)` maps `Parameter.id → Parameter.label`; `main_effects_chart(me, label_map, metric_label)` returns a faceted line chart of factor-level means (one facet per factor, categorical X-axis sorted by numeric value, independent Y-axes per facet). |
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
Prosimos value and excluded from the Taguchi OA. The selected resource ID is carried
through `AutomationScenario.selected_resource_id` and used in `apply_params()`;
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

- **Tasks with no resources assigned** (`core/bpmn/utils.py`): `task_resources()`
  returns `[]` if the target task has no entry in `task_resource_distribution`.
  Technically impossible when using Simod-generated models, but not explicitly
  guarded — `apply_params()` silently skips the pool resize in that case.
- **Incomplete cases in cycle time** (`core/simulation/prosimos_csv.py`): `per_log_metrics()` computes
  cycle time as `max(end_time) − min(start_time)` over all cases with no filter for
  completion. Currently safe because Prosimos runs until `--total_cases N` cases
  **complete**, so the output log should never contain truncated cases. If that
  assumption ever breaks, incomplete cases would have artificially short cycle times
  and pull the median down silently.
- **`signal_to_noise` drops zero rework** (`core/analysis.py`): the filter `v > 0`
  in `signal_to_noise` excludes zero values because the log formula is undefined at
  zero. For zero rework rate — a legitimate best-case outcome where automation
  eliminated all rework entirely — S/N goes blank for the best-performing factor
  levels, the exact place where the Taguchi table is most informative. The
  display-layer caption in `app.py` (`me["sn"].isna().any()`) acknowledges this but
  does not fix it. The right fix is a `floor` parameter on `signal_to_noise`
  (e.g. `floor: float = 0.0`) so callers can pass `floor=1e-9` when the metric
  legitimately reaches zero. Note: zero cost is now a valid user choice
  (bot_cost_per_hour defaults to 0.0), not a data anomaly.
Design decisions:

- **Single-goal ranking**: `rank()` optimises for one metric at a time (cycle time, cost, or rework rate), selected via a sidebar dropdown. The original two-goal design used a combined normalised score, but the scales differ enough (hours vs $/case) that cost dominated silently. Tradeoff: you lose the ability to surface scenarios that satisfy *both* goals simultaneously — if that matters, consider adding a secondary "also meets" flag column without letting it affect the score.
- **Results panel recomputation**: `analysis.aggregate()` and `analysis.main_effects()` are called unconditionally on every Streamlit rerun while results exist (no caching). At current scale (L27 × ~5 reps = ~135 rows) the groupby is negligible. If replications are scaled up (client cited 30 reps → ~810 rows) and the results panel becomes sluggish, cache `agg` in session state keyed by `id(ss.results)`, or apply `@st.cache_data` to the analysis functions.
- **Constants placement strategy**: `constants.py` holds only the eight `COL_*` analysis columns and the two `KEY_*` Prosimos JSON keys (`KEY_RESOURCE_PROFILES`, `KEY_TASK_RESOURCE_DISTRIBUTION`) that are consumed by both `bpmn/utils.py` and `simulation/prosimos_edit.py`. Everything else lives in its home module — BPMN namespace constants in `bpmn/__init__.py`, Prosimos CSV format strings in `simulation/prosimos_csv.py`, Prosimos input-JSON key names used only within `prosimos_edit.py` (`KEY_RESOURCE_CALENDARS`, `KEY_GATEWAY_BRANCHING_PROBS`) as module-level constants there, and XORSplitAutomation-specific values (`BOT_*`, `GW*_NAME`, flow display labels, Taguchi factor IDs (`F_*`), Taguchi defaults) inline in `transformations.py`. The rule: a constant belongs in `constants.py` only if removing it would require two or more otherwise-unrelated modules to import from each other.
- **`core/` subpackage structure**: `core/` is split into `bpmn/` (BPMN reading and editing) and `simulation/` (Prosimos/Simod subprocess wrappers, store, output parsing). The flat modules (`bpmn_edit.py`, `bpmn_utils.py`, `runner.py`, `store.py`, `prosimos_csv.py`) were merged into these subpackages. `list_activities` moved from `simulation/runner.py` to `bpmn/utils.py` since it reads BPMN XML, not a subprocess concern. `analysis.py`, `transformations.py`, `orchestrator.py`, and the dataclass modules remain at the top level of `core/` because they don't belong cleanly to either subpackage.
- **`prosimos_edit.py` extraction from `transformations.py`**: `core/simulation/prosimos_edit.py` owns all Prosimos input-JSON schema knowledge, mirroring `bpmn/edit.py` for BPMN XML. A second Transformation pattern will never be added, so the original "wait for a second pattern" argument is moot; the extraction is justified by the existing architectural boundary. Precise split: `prosimos_edit.py` receives `set_uniform`, `set_fixed`, `set_resource_amount`, and named helpers for the calendar/resource-profile/task-distribution/gateway-probability dict shapes currently inline in `build_scenario_template` and `apply_params`. `transformations.py` keeps the `Transformation` ABC (typed by `orchestrator.py`), `XORSplitAutomation`, all `BOT_*`/`GW*_NAME`/flow-label/`F_*` constants, and `build_scenario_template`/`apply_params` as thin orchestrators that delegate JSON surgery to `prosimos_edit`. `_xor_bypass_layout` stays in `transformations.py` — it is BPMN geometry coupled to `TransformIds`, not Prosimos JSON. Note: helpers in `prosimos_edit.py` have no `_` prefix because they are legitimately public within the package; `_write_distribution` retains `_` as the only truly private helper.
- **Rework KPI semantics** (`core/simulation/prosimos_csv.py`): two sources are counted process-wide per replication. (1) **Standard rework**: for every (case, activity) pair where the activity appears more than once, count `occurrences − 1`. A case visiting "Fix Bug" three times contributes 2. (2) **Bot-failure rework**: for every case where both `"Auto X"` and `"X"` appear (bot ran and failed, human redid the work), add 1. Neither activity repeats in this path so standard rework would not catch it. The two sources are additive without double-counting because they track different activity-name relationships. `COL_REWORK_RATE` is the fraction of cases with any rework (either source). pm4py was rejected: it provides only a binary per-case per-activity flag and no process-wide rate. `_rework_metrics(df, bot_task_name, original_task_name)` is the private DataFrame-level helper (called by `replication_metrics()` and tested directly). A missing `"activity"` column (e.g. synthetic test CSVs) returns `{rework_count: 0, rework_rate: 0}` rather than crashing.
- **`compare_to_baseline` and `aggregate` are data-driven** (`core/analysis.py`): display metrics are described by `_MetricSpec` NamedTuples (`col`, `label`, `fn`, `delta_label`, `pct_label`, `dp`) collected in a module-level `_METRICS` list. `compare_to_baseline` iterates `_METRICS` to build each display row — adding a new metric is a one-line addition to `_METRICS`, not eight scattered edits. `aggregate` uses pandas named-aggregation syntax (`output_col: (source_col, aggfunc)`) with no conditional guards; all six metric columns are always present in both the demo and real pipelines. `_pct_delta(delta, baseline)` returns `nan` when `baseline == 0` (mathematically undefined percentage, surfaced as a blank cell — the right call for a display helper, not a logic-error path that should raise).
- **`GoalOption.scale` as a unit bridge** (`ui/goals.py`): `scale=0.01` converts the user's percentage input (0–100) to the stored fraction (0.0–1.0) before calling `rank()`. The cleaner approach would store all goal metrics in a consistent display unit, but `COL_REWORK_RATE_MEAN` is stored as a fraction throughout `core/` (and converted `* 100` only at display time in `compare_to_baseline`). Changing the storage unit would require touching `prosimos_csv.py`, `analysis.py`, and `compare_to_baseline` display formatting. The `scale` field is a deliberate narrow bridge that keeps all unit conversion in `GoalOption` without propagating the change across `core/`. If a second fractional metric is added, reconsider whether a consistent display unit is worth the refactor.
- **Demo extraction — `demo.run_experiment()` owns all synthetic logic** (`core/demo.py`, `core/orchestrator.py`, `app.py`): the original design threaded `demo_mode: bool` through `orchestrator.run_experiment()`, scattering `if demo_mode:` branches across the prepare, apply, simulate, and metric-collection steps. The practical consequence: adding any new metric to the demo required touching both `demo.py` (the formula) and `orchestrator.py` (the NaN placeholder), and `orchestrator.py` was never truly "the real pipeline" — it was the real pipeline plus a synthetic bypass. The refactor gives `demo.py` a public `run_experiment(scenarios, n_reps, on_progress) -> ExperimentResult` that owns the full synthetic loop; `orchestrator.run_experiment()` loses `demo_mode` and becomes a straight real-pipeline path; `app.py` makes one explicit routing decision at the call site. Key design choices: (1) `DemoResult` becomes private `_SimResult` with all six metric fields (`cycle_h`, `cost`, `total_cycle_s`, `total_cost`, `rework_count`, `rework_rate`) — `total_cycle_s = cycle_h × 3600 × n_cases`, `total_cost = cost × n_cases`, rework formula is `(pct_auto × (1 − pct_ok) + BASELINE_REWORK_RATE × (1 − pct_auto)) × noise`; (2) `baseline_agg` stays `None` in demo — Panel 5 is gated on real mode and demo baseline is a separate future enhancement; (3) `ExperimentResult` stays in `orchestrator.py` — `demo.py` imports from it without a cycle because `orchestrator.py` no longer imports from `demo`; (4) `fake_discovery()` stays public — `app.py` still needs it for the activity dropdown; (5) `TestDemoMode` in `tests/test_orchestrator.py` migrates to `tests/test_demo.py` and calls `demo.run_experiment()` directly.
- **`Parameter.id` carries no activity-name prefix** (`core/transformations.py`, `core/parameters.py`, `core/demo.py`, `core/analysis.py`): `Parameter.id` is a bare factor key (e.g. `"pct_auto"`) with no `"{activity}."` prefix. The prefix was removed because: (1) within a single experiment there is only ever one target activity, so the prefix adds no disambiguation; (2) it caused a double-prefix trap in `factor_label_map` where `p.id` already contained the full key but callers tried to prepend the target activity again; (3) it polluted the results DataFrame column names with the activity name, making them unreadable in the ranked table. The activity name is available in session state (`ss.target_activity`) for any display use. Factor IDs are defined as named constants (`F_PCT_AUTO = "pct_auto"` etc.) in `transformations.py` alongside the other `F_*`/`BOT_*`/`GW*_NAME` constants — this means `demo.py` and any other consumer can import the constant rather than repeating the string literal. `AutomationScenario.from_taguchi_values()` uses direct key lookup (`values.get(F_PCT_AUTO, default)`) rather than the previous suffix-scan (`k.endswith("." + suffix)`) which would have silently fallen back to defaults with bare keys. `analysis.py`'s `compare_to_baseline` identifies the cases column with `c == F_NUM_CASES` rather than `c.endswith(".num_cases")`.
- **Bot cost as experiment-wide input** (`app.py`, `core/transformations.py`, `core/orchestrator.py`, `core/demo.py`): `bot_cost_per_hour: float = 0.0` is treated as a scalar experiment config (like `n_reps`) rather than a Taguchi factor — it applies uniformly to every scenario and doesn't belong in the orthogonal array. Units are $/hr to mirror Simod's cost model. Default 0.0 preserves the prior zero-cost behaviour without a breaking change. Prosimos stores `cost_per_hour` as a string in the resource JSON (confirmed from Prosimos source); the conversion `str(bot_cost_per_hour)` happens at resource-dict construction in `build_scenario_template`. The demo formula replaces a prior magic `0.6` constant with a principled derivation: `expected_human_fraction = (1 − pct_auto/100) + (pct_auto/100) × (1 − pct_ok/100)` (humans handle all non-automated cases plus bot failures); `bot_cost_per_case = (pct_auto/100) × (t_auto / 3600) × bot_cost_per_hour`. This correctly models that bot failures redirect to the human path, avoiding silent cost underestimation at low `pct_ok` values.
- **Main-effects chart in `ui/plots.py`** (`ui/plots.py`, `app.py`): chart logic lives in a dedicated `ui/plots.py` module (two public functions: `factor_label_map` and `main_effects_chart`). The module is justified by the complexity of the chart function today — layout config, facet title cleanup, categorical axis handling — not by anticipated future reuse (preemptive organisation, not preemptive abstraction). The chart plots `mean` on the Y-axis only; `sn` (Signal-to-Noise ratio) is intentionally omitted from display because it has NaN gaps for zero rework rate (see §8 known bug), but it remains in `main_effects()` output so it can be surfaced once the `floor` fix lands. `factor_label_map` translates `Parameter.id` values to `Parameter.label` strings using the `params` list already in scope at the call site. The X-axis uses categorical strings sorted by numeric value before string conversion — this guarantees ascending display order regardless of how the user assigned level 1/2/3, and avoids Plotly treating numeric-looking strings as a linear axis (which would auto-generate ticks at round numbers rather than at data points). `type="category"` is set explicitly on all x-axes for the same reason. The `st.dataframe` tables in the three main-effects tabs in Panel 4 are replaced entirely by `st.plotly_chart` — the chart conveys the same information more compactly, and keeping both would make the panel excessively long.

Feature work:

- **Rework KPI — Panel 4 column visibility**: rework columns (`Rework Count`, `Δ Rework Count`, `Δ Rework (%)`, `Rework Rate (%)`, `Δ Rate (pp)`) surface in Panel 5 and the ranking table in Panel 4. The rework rate goal option and main-effects tab are also implemented. The remaining question is whether to add explicit column formatting or hide rework columns from Panel 4's ranking table default view if they clutter it.
- **Cost metric from first principles**: cost is currently read from Prosimos's stats CSV (`Individual Task Statistics` / `Total Cost`). A more reliable alternative is to compute it ourselves: per-replication, sum `resource_seconds × cost_per_hour` from the params JSON and the event log. This would also enable bot cost once `BOT_COST_PER_HOUR` is non-zero. Hook into `simulation.prosimos_csv.per_log_metrics()`.
- **More patterns**: `ParallelHybrid` (auto runs alongside manual review),
  `LoopWithReview` (auto, then human approves N% of cases). Each is a new
  `Transformation` subclass; the rest of the system absorbs it.
- **Cancel mid-run**: the discovery cancel works; the simulation run loop
  doesn't yet check a session-state flag between iterations.
- **Parallel simulation runs**: at the client-cited 30 replications, the full
  experiment is 810 scenario runs (27 scenarios × 30 reps) + 90 baseline runs
  (3 cases-levels × 30 reps) = 900 Prosimos invocations. Weighted sequential
  runtime is roughly 14 hours on a real-world process (optimistic 10s per
  100-case run, scaling linearly across the three cases levels). Every
  replication is fully independent — this is an embarrassingly parallel
  problem. `concurrent.futures.ProcessPoolExecutor` across all
  scenario×replication pairs would reduce runtime to approximately
  `14h / num_cores` (~105 min on 8 cores). Scenarios are currently run
  sequentially in `orchestrator.run_experiment()`; baseline runs per
  cases-level are also independent and can be parallelised the same way.
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
A refactor session removed the `"{activity}."` prefix from `Parameter.id` (`refactor/parameter-id-prefix`): seven `F_*` named constants added to `transformations.py` for Taguchi factor IDs; `parameters()` now uses bare `F_*` ids and drops the activity-name prefix from labels; `from_taguchi_values()` replaces the suffix-scan `_v()` helper with direct `values.get(F_PCT_AUTO, default)` lookups; `demo.py` imports and uses `F_*` constants; `analysis.py` replaces `c.endswith(".num_cases")` with `c == F_NUM_CASES`; all tests updated. A follow-up cleanup session disambiguated the `F_` prefix: flow display labels renamed from `F_BOT_BRANCH_LABEL` etc. to `BOT_BRANCH_LABEL` etc. so `F_` exclusively marks Taguchi factor ID constants; `target_activity` parameter prefixed with `_` in `XORSplitAutomation.parameters()` to signal it is unused by this implementation (required by the ABC contract).*
