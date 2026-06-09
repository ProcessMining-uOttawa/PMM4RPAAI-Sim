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
  `"cost"`) drives `number_input` constraints in the UI via `_level_input_kwargs()`
  in `app.py` (min/max/step/format). The pattern's `apply()` reads `values` by
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
| [.github/workflows/ci.yml](.github/workflows/ci.yml) | GitHub Actions CI: three parallel jobs — **lint** (ruff), **type-check** (`mypy core/ --ignore-missing-imports`), **test** (pytest). Triggered on push and PR to main. Only `pandas` and the respective tool are installed per job — heavy packages (streamlit, simod, prosimos) are not needed for the test suite. |
| [core/constants.py](core/constants.py) | Cross-cutting constants only: twelve `COL_*` analysis column names (`cycle_h`, `cost`, their means, `total_cycle_s`, `total_cost`, their means, `rework_count`, `rework_rate`, their means) and `KEY_RESOURCE_PROFILES` / `KEY_TASK_RESOURCE_DISTRIBUTION` (used in both `bpmn/utils.py` and `transformations.py`). Everything else lives in its home module. |
| [core/orchestrator.py](core/orchestrator.py) | Run loop: iterates scenarios × replications, calls `simulation.runner.simulate`, collects results into a tidy DataFrame. Also runs the baseline (original, untransformed model) before the scenarios and returns mean total metrics + rework means for Panel 5. |
| [core/preflight.py](core/preflight.py) | Detects Python 3.9, Corretto 8 (auto-finds `C:\Program Files\Amazon Corretto\jdk1.8*`), and both venvs. Surfaces per-row fixes in the UI. |
| [core/transformations.py](core/transformations.py) | `Transformation` ABC + `XORSplitAutomation` impl + `REGISTRY` of available patterns. Owns all XORSplitAutomation-specific constants inline (BOT_*, GW*_NAME, F_*, Taguchi level lists). `TransformIds` has computed properties `bot_resource_id`, `bot_resource_name`, and `bot_task_name` (`"Auto " + task_name`). |
| [core/bpmn/\_\_init\_\_.py](core/bpmn/__init__.py) | BPMN XML namespace constants (`BPMN_NS`, `BPMNDI_NS`, `DC_NS`, `DI_NS`, `BPMN_TASK_TAGS`). |
| [core/bpmn/edit.py](core/bpmn/edit.py) | Low-level BPMN XML editing: DI shape/edge creation, process element insertion, sequence-flow rewiring. All `xml.etree.ElementTree` surgery lives here. |
| [core/bpmn/utils.py](core/bpmn/utils.py) | Read-only BPMN/Prosimos helpers: task-by-name lookup, `list_activities()`, `task_mean_duration_s()` for prepopulating Non-Auto-Time, resource helpers (`task_resources`, `shared_resource_ids`, `resource_pool_size`). |
| [core/simulation/runner.py](core/simulation/runner.py) | Subprocess wrappers: `discover()` (Simod one-shot, XES auto-converted to CSV first via stdlib `xml.etree.ElementTree`) and `simulate()` (Prosimos `start-simulation`). Stdout/stderr captured to log files via `_run_logged()`. |
| [core/simulation/store.py](core/simulation/store.py) | Experiment directory layout. Each run gets a timestamped folder under `runs/<exp-id>/`; subprocess logs co-located with CSV outputs. |
| [core/simulation/prosimos_edit.py](core/simulation/prosimos_edit.py) | Prosimos input-JSON mutation helpers — all schema knowledge lives here. `set_uniform`, `set_fixed`, `set_resource_amount` write distribution and pool values; `ensure_calendar`, `upsert_resource_in_profile`, `append_task_distribution`, `add_gateway_probs` handle structural additions. `KEY_RESOURCE_CALENDARS` and `KEY_GATEWAY_BRANCHING_PROBS` are module-level constants here. Mirrors `bpmn/edit.py` for JSON. |
| [core/simulation/prosimos_csv.py](core/simulation/prosimos_csv.py) | Prosimos output reader: parses event-log CSV and stats CSV. `replication_metrics()` returns six per-replication metrics: `COL_CYCLE_H`, `COL_COST`, `COL_TOTAL_CYCLE_S`, `COL_TOTAL_COST`, `COL_REWORK_COUNT`, `COL_REWORK_RATE`. `rework_metrics()` is the public file-level wrapper used by `_run_baseline()`. `_rework_metrics()` is the private DataFrame-level helper (used internally and in tests). PROSIMOS_* format constants are defined inline here. |
| [core/experiment.py](core/experiment.py) | Hard-coded Taguchi L9, L18, and L27 arrays + `pick_array(n_factors)`. Supports up to 13 three-level factors. |
| [core/parameters.py](core/parameters.py) | `Parameter`, `Scenario`, and `AutomationScenario` dataclasses. `AutomationScenario.from_taguchi_values()` bridges Taguchi output to simulation inputs. |
| [core/analysis.py](core/analysis.py) | Pure analysis: `aggregate()`, `compare_to_baseline()`, `main_effects()` (Taguchi S/N), `rank()` (single-goal: goals-met flag + ratio-to-target score). `compare_to_baseline()` includes rework columns (`Rework Count`, `Δ Rework Count`, `Δ Rework (%)`, `Rework Rate (%)`, `Δ Rate (pp)`). No file I/O. |
| [core/demo.py](core/demo.py) | Synthetic simulator behind the Demo-mode toggle — lets you click through the UI with no Simod/Prosimos installed. Resource pool size affects cycle time via sqrt scaling. |
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
pytest                                 # run test suite (125 tests, demo mode only)
ruff check .                           # lint
mypy core/ --ignore-missing-imports    # type-check (--ignore-missing-imports suppresses missing stub warnings)
```

## 8. What's worth doing next

Known bugs / reliability gaps:

- **Bot cost is hardcoded to zero** (`core/transformations.py`): `BOT_COST_PER_HOUR = "0"`
  means the bot resource never contributes to the cost metric — only human labour
  does. In practice, automation has real costs (licensing, infrastructure, etc.).
  Needs a concrete cost model from the PhD client before implementing; likely
  surfaces as a new Taguchi factor or a fixed input in the UI.
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
- **`signal_to_noise` drops zero costs** (`core/analysis.py`): the filter `v > 0`
  in `signal_to_noise` excludes zero-cost values. For fully-automated scenarios
  where `BOT_COST_PER_HOUR = "0"`, every replication has `cost = 0.0`, so `vals`
  is empty and the function returns `NaN` — silently voiding S/N analysis for the
  most-automated scenarios. The log formula requires positive inputs, so a floor
  (e.g. `max(v, 1e-9)`) or a special-case for zero is needed. Deferred pending
  decision on bot cost model (see "Bot cost hardcoded to zero" above).
Test gaps:

- **`apply_pattern()` multi-flow `NotImplementedError` untested** (`tests/test_transformations.py`): `XORSplitAutomation.apply_pattern()` raises `NotImplementedError` when the target task has more than one incoming or outgoing `sequenceFlow`. The conftest fixture uses a simple single-flow task, so this path is never exercised. A test would need a synthetic BPMN with a gateway feeding directly into the target task.

Design decisions:

- **Single-goal ranking**: `rank()` optimises for one metric at a time (cycle time or cost), selected via a sidebar dropdown. The original two-goal design used a combined normalised score, but the scales differ enough (hours vs $/case) that cost dominated silently. Tradeoff: you lose the ability to surface scenarios that satisfy *both* goals simultaneously — if that matters, consider adding a secondary "also meets" flag column without letting it affect the score.
- **Results panel recomputation**: `analysis.aggregate()` and `analysis.main_effects()` are called unconditionally on every Streamlit rerun while results exist (no caching). At current scale (L27 × ~5 reps = ~135 rows) the groupby is negligible. If replications are scaled up (client cited 30 reps → ~810 rows) and the results panel becomes sluggish, cache `agg` in session state keyed by `id(ss.results)`, or apply `@st.cache_data` to the analysis functions.
- **Constants placement strategy**: `constants.py` holds only the eight `COL_*` analysis columns and the two `KEY_*` Prosimos JSON keys (`KEY_RESOURCE_PROFILES`, `KEY_TASK_RESOURCE_DISTRIBUTION`) that are consumed by both `bpmn/utils.py` and `simulation/prosimos_edit.py`. Everything else lives in its home module — BPMN namespace constants in `bpmn/__init__.py`, Prosimos CSV format strings in `simulation/prosimos_csv.py`, Prosimos input-JSON key names used only within `prosimos_edit.py` (`KEY_RESOURCE_CALENDARS`, `KEY_GATEWAY_BRANCHING_PROBS`) as module-level constants there, and XORSplitAutomation-specific values (BOT_*, GW*_NAME, F_*, Taguchi defaults) inline in `transformations.py`. The rule: a constant belongs in `constants.py` only if removing it would require two or more otherwise-unrelated modules to import from each other.
- **`core/` subpackage structure**: `core/` is split into `bpmn/` (BPMN reading and editing) and `simulation/` (Prosimos/Simod subprocess wrappers, store, output parsing). The flat modules (`bpmn_edit.py`, `bpmn_utils.py`, `runner.py`, `store.py`, `prosimos_csv.py`) were merged into these subpackages. `list_activities` moved from `simulation/runner.py` to `bpmn/utils.py` since it reads BPMN XML, not a subprocess concern. `analysis.py`, `transformations.py`, `orchestrator.py`, and the dataclass modules remain at the top level of `core/` because they don't belong cleanly to either subpackage.
- **`prosimos_edit.py` extraction from `transformations.py`**: `core/simulation/prosimos_edit.py` owns all Prosimos input-JSON schema knowledge, mirroring `bpmn/edit.py` for BPMN XML. A second Transformation pattern will never be added, so the original "wait for a second pattern" argument is moot; the extraction is justified by the existing architectural boundary. Precise split: `prosimos_edit.py` receives `set_uniform`, `set_fixed`, `set_resource_amount`, and named helpers for the calendar/resource-profile/task-distribution/gateway-probability dict shapes currently inline in `build_scenario_template` and `apply_params`. `transformations.py` keeps the `Transformation` ABC (typed by `orchestrator.py`), `XORSplitAutomation`, all `BOT_*`/`GW*_NAME`/`F_*` constants, and `build_scenario_template`/`apply_params` as thin orchestrators that delegate JSON surgery to `prosimos_edit`. `_xor_bypass_layout` stays in `transformations.py` — it is BPMN geometry coupled to `TransformIds`, not Prosimos JSON. Note: helpers in `prosimos_edit.py` have no `_` prefix because they are legitimately public within the package; `_write_distribution` retains `_` as the only truly private helper.
- **Rework KPI semantics** (`core/simulation/prosimos_csv.py`): two sources are counted process-wide per replication. (1) **Standard rework**: for every (case, activity) pair where the activity appears more than once, count `occurrences − 1`. A case visiting "Fix Bug" three times contributes 2. (2) **Bot-failure rework**: for every case where both `"Auto X"` and `"X"` appear (bot ran and failed, human redid the work), add 1. Neither activity repeats in this path so standard rework would not catch it. The two sources are additive without double-counting because they track different activity-name relationships. `COL_REWORK_RATE` is the fraction of cases with any rework (either source). pm4py was rejected: it provides only a binary per-case per-activity flag and no process-wide rate. `_rework_metrics(df, bot_task_name, original_task_name)` is the private DataFrame-level helper (testable directly); `rework_metrics(log_csv, ...)` is the thin public wrapper used by `_run_baseline()`. A missing `"activity"` column (e.g. synthetic test CSVs) returns `{rework_count: 0, rework_rate: 0}` rather than crashing.

Feature work:

- **Rework KPI — display in UI** (`app.py`): `COL_REWORK_COUNT_MEAN` and `COL_REWORK_RATE_MEAN` are now present in the aggregated results DataFrame and `compare_to_baseline()` output, but not yet surfaced in any UI panel. Add an informational rework row to Panel 5 (baseline comparison table) and optionally a rework column to Panel 4 (ranking table).
- **Cost metric from first principles**: cost is currently read from Prosimos's stats CSV (`Individual Task Statistics` / `Total Cost`). A more reliable alternative is to compute it ourselves: per-replication, sum `resource_seconds × cost_per_hour` from the params JSON and the event log. This would also enable bot cost once `BOT_COST_PER_HOUR` is non-zero. Hook into `simulation.prosimos_csv.per_log_metrics()`.
- **Plots in Panel 4**: a Plotly main-effects plot (factor × level) above
  the ranking table. The data is already in `analysis.main_effects()`.
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
`replication_metrics()`, `_run_baseline()`, `aggregate()`, and `compare_to_baseline()`
(125 tests).*
