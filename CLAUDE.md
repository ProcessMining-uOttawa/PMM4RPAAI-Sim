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
        ▼  curated L9, L18 OAs
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
| [.github/workflows/ci.yml](.github/workflows/ci.yml) | GitHub Actions CI: three parallel jobs — **lint** (ruff), **type-check** (`mypy core/ --ignore-missing-imports`), **test** (pytest). Triggered on push and PR to main. Only `pandas` and the respective tool are installed per job — heavy packages (streamlit, pm4py) are not needed for the test suite. |
| [core/constants.py](core/constants.py) | Cross-cutting constants only: eight `COL_*` analysis column names and `KEY_RESOURCE_PROFILES` / `KEY_TASK_RESOURCE_DISTRIBUTION` (used in both `bpmn/utils.py` and `transformations.py`). Everything else lives in its home module. |
| [core/orchestrator.py](core/orchestrator.py) | Run loop: iterates scenarios × replications, calls `simulation.runner.simulate`, collects results into a tidy DataFrame. Also runs the baseline (original, untransformed model) before the scenarios and returns mean total metrics for Panel 5. |
| [core/preflight.py](core/preflight.py) | Detects Python 3.9, Corretto 8 (auto-finds `C:\Program Files\Amazon Corretto\jdk1.8*`), and both venvs. Surfaces per-row fixes in the UI. |
| [core/transformations.py](core/transformations.py) | `Transformation` ABC + `XORSplitAutomation` impl + `REGISTRY` of available patterns. Owns all XORSplitAutomation-specific constants inline (BOT_*, GW*_NAME, F_*, Taguchi level lists). |
| [core/bpmn/\_\_init\_\_.py](core/bpmn/__init__.py) | BPMN XML namespace constants (`BPMN_NS`, `BPMNDI_NS`, `DC_NS`, `DI_NS`, `BPMN_TASK_TAGS`). |
| [core/bpmn/edit.py](core/bpmn/edit.py) | Low-level BPMN XML editing: DI shape/edge creation, process element insertion, sequence-flow rewiring. All `xml.etree.ElementTree` surgery lives here. |
| [core/bpmn/utils.py](core/bpmn/utils.py) | Read-only BPMN/Prosimos helpers: task-by-name lookup, `list_activities()`, `task_mean_duration_s()` for prepopulating Non-Auto-Time, resource helpers (`task_resources`, `shared_resource_ids`, `resource_pool_size`). |
| [core/simulation/runner.py](core/simulation/runner.py) | Subprocess wrappers: `discover()` (Simod one-shot, XES auto-converted to CSV first) and `simulate()` (Prosimos `start-simulation`). Stdout/stderr captured to log files via `_run_logged()`. |
| [core/simulation/store.py](core/simulation/store.py) | Experiment directory layout. Each run gets a timestamped folder under `runs/<exp-id>/`; subprocess logs co-located with CSV outputs. |
| [core/simulation/prosimos_csv.py](core/simulation/prosimos_csv.py) | Prosimos output reader: parses event-log CSV and stats CSV. `replication_metrics()` does a single stats CSV parse to return all four per-replication metrics (`COL_CYCLE_H`, `COL_COST`, `COL_TOTAL_CYCLE_S`, `COL_TOTAL_COST`). PROSIMOS_* format constants are defined inline here. |
| [core/experiment.py](core/experiment.py) | Hard-coded Taguchi L9 and L18 arrays + `pick_array(n_factors)`. L27 still TODO. |
| [core/parameters.py](core/parameters.py) | `Parameter`, `Scenario`, and `AutomationScenario` dataclasses. `AutomationScenario.from_taguchi_values()` bridges Taguchi output to simulation inputs. |
| [core/analysis.py](core/analysis.py) | Pure analysis: `aggregate()`, `compare_to_baseline()`, `main_effects()` (Taguchi S/N), `rank()` (single-goal: goals-met flag + ratio-to-target score). No file I/O. |
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

**Six factors** (`parameters()` declares them; UI auto-renders). Six factors → L18 OA → 18 scenarios.

| Factor | Default levels | Meaning |
|---|---|---|
| `pct_auto` (%) | 25 / 50 / 75 | XOR1 branch probability to the automated task |
| `pct_ok` (%) | 80 / 90 / 95 | XOR2 success probability (skip the fallback) |
| `t_auto` (s) | 5%, 10%, 20% of Simod mean | Automated task mean duration |
| `t_manual` (s) | 80%, 100%, 120% of Simod mean | Non-automated mean (**prepopulated from Simod**) |
| `num_bots` | 1 / 2 / 3 | Bot resource pool size |
| `num_manual_resources` | 1 / 2 / 3 | Human resource pool size |

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
   `runner.xes_to_simod_csv()` using pm4py. The XES from pm4py-ucm has only
   `complete` events, so `start_time` is synthesized per case from the
   previous event's `end_time` (zero-duration for the first event).

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
pytest                                 # run test suite (105 tests, demo mode only)
ruff check .                           # lint
mypy core/ --ignore-missing-imports    # type-check (--ignore-missing-imports suppresses pm4py stub warning)
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
- **Bot task uses uniform distribution instead of fix** (`core/transformations.py`):
  `apply_params()` calls `_set_uniform()` for both the manual and bot task entries,
  giving the bot a ±5% jitter around `t_auto`. A bot (deterministic automation script)
  should use `"fix"` with a single value. Note: `BOT_DISTRIBUTION_NAME = "fix"` in
  `transformations.py` was the original intent but is dead — `build_base_json` sets it as a
  placeholder and `apply_params` immediately overwrites it. Fix: add a separate
  `_set_fixed(entry, mean_s)` helper and use it for the bot entry in `apply_params()`.

Test gaps:

- **`apply_pattern()` multi-flow `NotImplementedError` untested** (`tests/test_transformations.py`): `XORSplitAutomation.apply_pattern()` raises `NotImplementedError` when the target task has more than one incoming or outgoing `sequenceFlow`. The conftest fixture uses a simple single-flow task, so this path is never exercised. A test would need a synthetic BPMN with a gateway feeding directly into the target task.

Design decisions:

- **Single-goal ranking**: `rank()` optimises for one metric at a time (cycle time or cost), selected via a sidebar dropdown. The original two-goal design used a combined normalised score, but the scales differ enough (hours vs $/case) that cost dominated silently. Tradeoff: you lose the ability to surface scenarios that satisfy *both* goals simultaneously — if that matters, consider adding a secondary "also meets" flag column without letting it affect the score.
- **Results panel recomputation**: `analysis.aggregate()` and `analysis.main_effects()` are called unconditionally on every Streamlit rerun while results exist (no caching). At current scale (L18 × ~5 reps = ~90 rows) the groupby is negligible. If the project adds L27 with many replications and the results panel becomes sluggish, cache `agg` in session state keyed by `id(ss.results)`, or apply `@st.cache_data` to the analysis functions.
- **Constants placement strategy**: `constants.py` holds only the eight `COL_*` analysis columns and the two `KEY_*` Prosimos JSON keys that are consumed by both `bpmn/utils.py` and `transformations.py`. Everything else lives in its home module — BPMN namespace constants in `bpmn/__init__.py`, Prosimos CSV format strings in `simulation/prosimos_csv.py`, and XORSplitAutomation-specific values (BOT_*, GW*_NAME, F_*, Taguchi defaults) inline in `transformations.py`. The rule: a constant belongs in `constants.py` only if removing it would require two or more otherwise-unrelated modules to import from each other.
- **`core/` subpackage structure**: `core/` is split into `bpmn/` (BPMN reading and editing) and `simulation/` (Prosimos/Simod subprocess wrappers, store, output parsing). The flat modules (`bpmn_edit.py`, `bpmn_utils.py`, `runner.py`, `store.py`, `prosimos_csv.py`) were merged into these subpackages. `list_activities` moved from `simulation/runner.py` to `bpmn/utils.py` since it reads BPMN XML, not a subprocess concern. `analysis.py`, `transformations.py`, `orchestrator.py`, and the dataclass modules remain at the top level of `core/` because they don't belong cleanly to either subpackage.

Feature work:

- **Rework KPI** (`core/simulation/prosimos_csv.py`, `core/constants.py`): add process-wide
  rework as an informational metric (not wired into ranking). Compute two values per
  replication from the event log CSV: `COL_REWORK_COUNT` (total extra occurrences —
  sum of `occurrences − 1` across all case/activity pairs where an activity repeats)
  and `COL_REWORK_RATE` (fraction of cases with at least one rework event). Source is
  always the log CSV, not the stats CSV — rework requires per-case activity counts.
  Use pandas directly; pm4py was considered and rejected: it requires renaming
  `case_id → case:concept:name` and `activity → concept:name`, returns only a
  per-activity "cases-with-rework" count (not total extra occurrences), and provides
  no process-wide rate — pandas covers all three needs in one pass with no friction.
  Hook the two new columns into `replication_metrics()` alongside the existing four.
  **Pending client confirmation before implementing**: pm4py's rework definition counts
  the number of *cases* where an activity appears more than once (binary per case per
  activity). Our `COL_REWORK_COUNT` definition counts total extra occurrences
  (a case that visits "Fix Bug" three times contributes 2, not 1). These diverge
  whenever any case repeats an activity more than twice. Confirm which semantics the
  client expects — the implementation differs depending on the answer.
- **Cost metric from first principles**: cost is currently read from Prosimos's stats CSV (`Individual Task Statistics` / `Total Cost`). A more reliable alternative is to compute it ourselves: per-replication, sum `resource_seconds × cost_per_hour` from the params JSON and the event log. This would also enable bot cost once `BOT_COST_PER_HOUR` is non-zero. Hook into `simulation.prosimos_csv.per_log_metrics()`.
- **Plots in Panel 4**: a Plotly main-effects plot (factor × level) above
  the ranking table. The data is already in `analysis.main_effects()`.
- **More patterns**: `ParallelHybrid` (auto runs alongside manual review),
  `LoopWithReview` (auto, then human approves N% of cases). Each is a new
  `Transformation` subclass; the rest of the system absorbs it.
- **L27 array**: drop the literal table in `core/experiment.py`. There's a
  textbook listing; `pyDOE2.gsd` is not it.
- **Cancel mid-run**: the discovery cancel works; the simulation run loop
  doesn't yet check a session-state flag between iterations.
- **Parallel simulation runs**: at the client-cited 30 replications, the full
  experiment is 540 scenario runs + 90 baseline runs = 630 Prosimos invocations.
  With `num_cases` levels of 100/500/1000, the weighted sequential runtime is
  roughly 9 hours on a real-world process (optimistic 10s per 100-case run,
  scaling linearly). Every replication is fully independent — this is an
  embarrassingly parallel problem. `concurrent.futures.ProcessPoolExecutor`
  across all scenario×replication pairs would reduce runtime to approximately
  `9h / num_cores` (~90 min on 8 cores). Scenarios are currently run
  sequentially in `orchestrator.run_experiment()`; baseline runs per cases-level
  are also independent and can be parallelised the same way.
- **Real BPMN preview**: replace the activity dropdown with a clickable
  BPMN canvas (Mockup C had this idea). `bpmn-js` via a Streamlit custom
  component would do it.

## 9. Don't

- Don't reintroduce a `python -m simod` invocation — Simod's package has no
  `__main__.py`; only the `simod.exe` entry-point script works.
- Don't add a "discover on every interaction" code path. See §6.
- Don't read pm4py inside the Simod or Prosimos venvs — those are pinned to
  Python 3.9 and tightly constrained. pm4py belongs in the host venv only.
- Don't commit `runs/`, `tools/simod-venv/`, or `tools/prosimos-venv/`.
  `.gitignore` already excludes them; keep it that way.

---

*Initial scaffold + four wiring sessions (Simod → Prosimos → XORSplitAutomation
→ bug-fixes) completed against the IssueTracker synthetic log. Subsequent
sessions added `num_bots`/`num_manual_resources` as Taguchi factors (L18),
subprocess log capture, XML namespace centralisation in `constants.py`, and
dead-code removal (`new_id`, `Parameter.inject`, `store.ACTIVE` clobber).
Later sessions added code quality tooling (ruff, mypy), a full test suite
(105 tests across all core modules), export features (stats CSV, JSON zip,
BPMN, group ZIP in Panel 4), GitHub Actions CI, baseline comparison (Panel 5),
Prosimos output parsing split into `simulation/prosimos_csv.py`, and
restructure of `core/` into `bpmn/` and `simulation/` subpackages.*
