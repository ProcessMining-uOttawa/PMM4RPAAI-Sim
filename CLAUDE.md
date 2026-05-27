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
        ▼  pyDOE2 / curated L9, L18 OAs
list[Scenario]  (one per row of the OA)
        │
        ▼  Pattern.apply(scenario)  — mutates BPMN + JSON
        │
        ▼  Prosimos  start-simulation  ×  N replications
Per-replication event-log CSV + stats CSV
        │
        ▼  pm4py-derived metrics  +  Taguchi S/N + ranking
Ranking table + main-effects view
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

- **Job-folder store** ([core/store.py](core/store.py)) — every experiment
  is a folder under `runs/<exp-id>/`. Replications land at
  `runs/<exp-id>/scenarios/<sid>/rep_NNN_log.csv` + `..._stats.csv`. Tidy
  long-format DataFrame in `app.py` is the single source of truth for
  analysis — keeps re-ranking decoupled from re-simulating.

## 3. Module map

| File | Responsibility |
|---|---|
| [app.py](app.py) | Streamlit dashboard (Mockup B): sidebar = experiment state + run config; 4 panels = Activity & pattern · Factor levels · Execution · Ranked scenarios. |
| [core/constants.py](core/constants.py) | Shared constants: XML namespaces, Prosimos JSON keys, and pattern defaults (Taguchi level lists). |
| [core/orchestrator.py](core/orchestrator.py) | Run loop: iterates scenarios × replications, calls `runner.simulate`, collects results into a tidy DataFrame. |
| [core/preflight.py](core/preflight.py) | Detects Python 3.9, Corretto 8 (auto-finds `C:\Program Files\Amazon Corretto\jdk1.8*`), and both venvs. Surfaces per-row fixes in the UI. |
| [core/runner.py](core/runner.py) | Subprocess wrappers: `discover()` (Simod one-shot, XES auto-converted to CSV first), `simulate()` (Prosimos `start-simulation`), `list_activities()` (ET read of BPMN task names). Stdout/stderr captured to log files via `_run_logged()`. |
| [core/transformations.py](core/transformations.py) | `Transformation` ABC + `XORSplitAutomation` impl + `REGISTRY` of available patterns. |
| [core/bpmn_edit.py](core/bpmn_edit.py) | Low-level BPMN XML editing: DI shape/edge creation, process element insertion, sequence-flow rewiring. All `xml.etree.ElementTree` surgery lives here. |
| [core/bpmn_utils.py](core/bpmn_utils.py) | Read-only BPMN helpers: task-by-name lookup, sequenceFlow neighbours, `task_mean_duration_s()` for prepopulating Non-Auto-Time. |
| [core/experiment.py](core/experiment.py) | Hard-coded Taguchi L9 and L18 arrays + `pick_array(n_factors)`. L27 still TODO. |
| [core/parameters.py](core/parameters.py) | `Parameter`, `Scenario`, and `AutomationScenario` dataclasses. `AutomationScenario.from_taguchi_values()` bridges Taguchi output to simulation inputs. |
| [core/analysis.py](core/analysis.py) | `per_log_metrics()` (cycle time from event log, cost from stats), `aggregate()`, `main_effects()` (Taguchi S/N), `rank()` (goals-met then weighted score). |
| [core/store.py](core/store.py) | Experiment directory layout. Each run gets a timestamped folder under `runs/<exp-id>/`; subprocess logs co-located with CSV outputs. |
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
  uniform around `t_auto`. Appends two entries to
  `gateway_branching_probabilities` for XOR1 and XOR2.

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
`None` falls back to `resources[0]` with a warning if multiple resources exist.

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

## 8. What's worth doing next

Known bugs / reliability gaps:

- **~~Silent `cost = 0.0`~~** *(fixed)*: original code looked for section
  `"scenario statistics"` and column `"Average Cost"` — both wrong for the actual
  Prosimos output format (`"Overall Scenario Statistics"` / `"Individual Task
  Statistics"` with `"Total Cost"`). Cost is now computed as sum of `Total Cost`
  across all tasks divided by case count. `per_log_metrics()` returns `None` when
  stats are unavailable; `rank()` handles NaN; UI shows a warning banner.
- **Bot cost is hardcoded to zero** (`core/constants.py`): `BOT_COST_PER_HOUR = "0"`
  means the bot resource never contributes to the cost metric — only human labour
  does. In practice, automation has real costs (licensing, infrastructure, etc.).
  Needs a concrete cost model from the PhD client before implementing; likely
  surfaces as a new Taguchi factor or a fixed input in the UI.
- **Tasks with no resources assigned** (`core/bpmn_utils.py`): `task_resources()`
  returns `[]` if the target task has no entry in `task_resource_distribution`.
  Technically impossible when using Simod-generated models, but not explicitly
  guarded — `apply_params()` silently skips the pool resize in that case.
- **Incomplete cases in cycle time** (`core/analysis.py`): `per_log_metrics()` computes
  cycle time as `max(end_time) − min(start_time)` over all cases with no filter for
  completion. Currently safe because Prosimos runs until `--total_cases N` cases
  **complete**, so the output log should never contain truncated cases. If that
  assumption ever breaks, incomplete cases would have artificially short cycle times
  and pull the median down silently.
- **Bot task uses uniform distribution instead of fix** (`core/transformations.py`):
  `apply_params()` calls `_set_uniform()` for both the manual and bot task entries,
  giving the bot a ±5% jitter around `t_auto`. A bot (deterministic automation script)
  should use `"fix"` with a single value. Note: `BOT_DISTRIBUTION_NAME = "fix"` in
  `constants.py` was the original intent but is dead — `build_base_json` sets it as a
  placeholder and `apply_params` immediately overwrites it. Fix: add a separate
  `_set_fixed(entry, mean_s)` helper and use it for the bot entry in `apply_params()`.

Test gaps:

- `AutomationScenario.from_taguchi_values()` has no test for the new
  `num_bots` / `num_manual_resources` keys.
- `core/analysis.py` has no test coverage at all.
- Demo resource scaling has no monotonicity test (larger pool → shorter cycle).

Feature work:

- **Cost metric**: Prosimos's stats CSV doesn't always include
  `Average Cost`. Compute it ourselves: per-replication, sum
  `resource_seconds × cost_per_hour` from the params JSON. Hook into
  `analysis.per_log_metrics()`.
- **Plots in Panel 4**: a Plotly main-effects plot (factor × level) above
  the ranking table. The data is already in `analysis.main_effects()`.
- **More patterns**: `ParallelHybrid` (auto runs alongside manual review),
  `LoopWithReview` (auto, then human approves N% of cases). Each is a new
  `Transformation` subclass; the rest of the system absorbs it.
- **L27 array**: drop the literal table in `core/experiment.py`. There's a
  textbook listing; `pyDOE2.gsd` is not it.
- **Cancel mid-run**: the discovery cancel works; the simulation run loop
  doesn't yet check a session-state flag between iterations.
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
dead-code removal (`new_id`, `Parameter.inject`, `store.ACTIVE` clobber).*
