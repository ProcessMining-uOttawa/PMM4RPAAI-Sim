# Plan — in-path structural validation gate + the SoC refactor it rides on

> Scope: wire `core/bpmn/validate.py`'s **structural** checks into the run path so a
> mis-wired transform fails loudly with a durable, inspectable error instead of
> silently producing a broken model. This is CLAUDE.md §8's deferred "plan item 4".
> Context for this plan lives in the conversation that produced it; the essentials
> are captured below so a fresh session needs only this file + `CLAUDE.md`.

## Background — four findings that shape everything below

1. **`validate.py` is currently a maintainer trust tool, not in the app path.** Nothing
   in production verifies the transformed BPMN. `verify_fragment(bpmn_path, target) ->
   VerificationResult` is a pure-stdlib structural oracle with tiered
   `Severity.ERROR`/`WARNING` violations, already trusted via a two-layer test strategy
   in `tests/bpmn/test_validate.py`. Its ERROR/WARNING split **is** the soft-vs-hard
   decision, made deliberately: ERROR = executability (dangling refs, wrong topology —
   what Prosimos routes on); WARNING = representation drift Prosimos ignores.

2. **`verify_fragment` is meaningless before the transform.** It anchors on the target
   task and walks outward expecting the XOR fragment (four gateways + an `Auto X` task).
   Run on a pristine Simod discovery it reports `MISSING_GATEWAY` — the fragment doesn't
   exist yet. **So the gate cannot live "after discovery"; its only correct site is at
   the end of the transform, once the fragment exists.**

3. **The run path swallows hard failures.** A hard exception during a run becomes
   `RunOutcome(error)` → `execution_panel.py` `st.toast("Simulation failed: …")` →
   `clear_run(ss)` destroys it → rerun. It flashes and is gone; nothing persists it to
   session state. This is **pre-existing and independent of the gate** — it's how the run
   path reports *any* hard failure today. #105 built the durable pattern we need, but on
   the **discovery** path (`app.py:159-177`: `st.error` + `st.exception` + a log-tail
   expander), not the run path. The gate raises on the run path, so it needs the run-path
   surface to exist first.

4. **The realistic hard-failure population is tiny — so the surface is severity-driven,
   not frequency-driven.** Two classes of hard failure exist: **setup** (raises in
   `prepare_experiment` / JSON pre-gen, before any simulation) and **total execution**
   (`orchestrator.SimulationError`, raised only when *every* replication permanently fails
   after retries — a partial failure is absorbed into the already-durable
   `ss.failed_replications` warning, not this path). On a real Simod discovery the setup
   class is **effectively unreachable**: every `apply_pattern` boundary raise is a
   malformed-input net, and the arity guard (`!= 1` incoming/outgoing) only fires on an
   *uncontrolled merge/split* — a spec-legal but non-canonical **representation** of
   branching (the canonical form routes branching through an explicit gateway, leaving the
   task 1-in/1-out). No BPMN is ever uploaded (the pipeline input is an event *log*;
   `discover(log_path) -> (bpmn, json)`), so the only BPMN in the system is SplitMiner's own
   output, which it *generates* already in the canonical form — explicit gateways, 1-in/1-out
   tasks (the demo model: all-1/1, 6 XOR + 2 parallel gateways). `TestMultiFlowNotImplemented`
   is hand-authored synthetic BPMN precisely because a discovery can't produce the shape.
   **The guard's justification is not "it fires sometimes" — it effectively never does — but
   that it is our *independent backstop* for an assumption about a third-party miner we cannot
   fully verify.** "SplitMiner always emits explicit gateways" is its documented design plus
   one inspected output, not an exhaustive guarantee across every Simod/SplitMiner config
   (loops, aggressive filtering, post-processing). We don't rely on that guarantee; the arity
   guard is our own check, and if the assumption is ever wrong the failure mode is the benign
   one — a loud, actionable `NotImplementedError` ("this activity isn't supported"), never a
   silently corrupted export. So the realistic hard-failure population is **total
   Prosimos/environment breakdown** plus the **future validation gate**, with the arity guard
   as a third, near-zero-probability contributor whose value is catching the case our
   assumptions miss. All are rare and non-transient (retries already spent; re-running won't
   help). The surface should therefore be **invisible until it fires, and own the results slot
   when it does** (a hard failure means *no results*, categorically unlike the
   `failed_replications` warning that annotates *beside* real results). Loudness is justified
   by severity — a total, unrecoverable, actionable failure — not by how often it happens.

   *(Earlier-session correction folded in here: the guard was mis-described — by me and by
   CLAUDE.md §4 / the code message — as rejecting "tasks fed by gateways directly." A
   gateway-fed task has arity 1 and transforms fine; the guard fires only on uncontrolled
   merge/split. The CLAUDE.md §4 + `NotImplementedError` wording fix is a separate small
   doc amend, pending — see the conversation for the proposed text.)*

## The SoC decomposition (settled — do this shape, not the alternatives)

`apply_pattern` today already does four things: `mkdir`, `ET.parse` (read), the mutation,
`tree.write` (write `model.bpmn`). The **new** concerns (verify, write a report, raise)
change for a *different reason* than the transform does — validation policy / error
surface, not pattern topology — so by SRP-as-reason-to-change they must not land in
`apply_pattern`. The split:

- **`apply_pattern`** (XOR impl) — **unchanged.** Produces `model.bpmn`. Read → mutate →
  write of one artifact is *one* cohesive concern that changes for one reason (the pattern
  topology), so the model write **stays here** — extracting it would be false decomposition
  (a pure `transform(tree)` plus a writer that only ever pairs with it), and it is the
  tested ABC contract `(paths) -> (path, ids)` plus the DI-guard boundary.
- **`verify_transformed(bpmn_path, target) -> VerificationResult`** — **new abstract method**
  on the `Transformation` ABC; `XORSplitAutomation` implements it by calling
  `verify_fragment`. Pure verification (reads the file, returns the result, no other I/O).
  It **must** be abstract, not a direct `verify_fragment` call in `prepare_experiment`:
  `prepare_experiment` lives on the **pattern-agnostic ABC**, and `verify_fragment` is
  XOR-specific — calling it there hardcodes XOR into the ABC (the same smell we avoided by
  keeping `AutomationParams` out of the orchestrator). Symmetric with `apply_pattern` /
  `build_scenario_template` already being abstract; keeps `validate` imported **only** by
  the subclass (no cycle — `validate` imports neither `transformations` nor `query`'s flow
  helpers).
- **`prepare_experiment`** (concrete ABC coordinator) — after `apply_pattern`, calls
  `self.verify_transformed(bpmn_out, target)`; on ERROR-tier violations it **delegates the
  write** to `store.py` and raises a compact `TransformValidationError`. The reporting
  concern, with the file write pushed out to the module that owns on-disk layout.
- **`store.py`** — gains `validation_report(exp, result) -> Path` (path + write). It already
  owns `runs/<exp-id>/` layout (`discovery_log -> simod.log`, `replication_subprocess_log`,
  `baseline_params_path`), so `validation.log` is the same species of artifact and belongs
  here — this is the "separate helper module" the writing goes to, and it already exists.

**Debugging bonus preserved:** `apply_pattern` writes `model.bpmn`; verification then finds
it mis-wired; `store` writes `validation.log` beside it. Both artifacts land on disk — the
broken model next to the verdict explaining why — mirroring the maintainer-trust ethos.

**Rejected shapes:** (a) verify+write+raise inside `apply_pattern` — piles a 5th/6th concern
on an already-loaded function, wrong SRP axis. (b) extracting the `model.bpmn` write into a
writer module — cohesive with the mutation, same reason to change, false decomposition.
(c) `verify_fragment` called directly in `prepare_experiment` — hardcodes XOR into the
agnostic ABC. (d) gate in the orchestrator — the orchestrator is deliberately
pattern-agnostic; it should only let the exception propagate, as it does for the DI-less
`ValueError` today.

## Work items

### Phase A — durable run-error surface (PREREQUISITE; independently valuable)
Fixes the vanishing-toast gap for *every* hard run failure, not just the gate. Mirrors
#105's discovery surface. Per finding 4, the design driver is **severity, not frequency**:
rare but total, so the surface owns the results slot when it fires and is absent otherwise.
Note this phase is **not UI-only** — step 0 touches `orchestrator.py` — so the plan's
original "UI change" framing for Phase A was wrong; see the corrected blast radius.

0. **Preserve the failure detail through the orchestrator (found in pre-impl review — the
   plan originally assumed the surface could render a tail, but the tail is discarded).**
   `runner.simulate` raises `CalledProcessError(..., output=_tail_lines(proc_log, 20))` —
   the useful Prosimos-log tail rides on `.output`. But `_on_error` (`orchestrator.py:229`)
   stores `FailedReplication(..., error=str(exc))`, and `str(CalledProcessError)` is only
   `"Command '…' returned non-zero exit status N"` — the tail is dropped there, and
   `SimulationError` (`orchestrator.py:246`) then wraps just that useless first string. The
   tail *does* exist on disk (`store.replication_subprocess_log`), and `task.proc_log` is in
   scope at the drop site. **Fix:** carry the tail (or the proc_log path) through
   `FailedReplication` → `SimulationError` (e.g. `SimulationError(msg, log_tail=…)`) so the
   step-2 expander has real content. **Bonus:** this also repairs the *existing*
   `failed_replications` `st.warning`, which today says "Check the run logs for details" and
   surfaces none. The setup class (`ValueError`/`NotImplementedError` from
   `prepare_experiment`) needs no change — it reaches `RunOutcome(error)` as a *live*
   exception with a useful message.
1. **Persist the run error.** In `ui/run_manager.py`, on the worker's
   `RunOutcome(error=exc)` path, write the error to a durable session key (`ss.run_error`)
   at the point `execution_panel` currently toasts — *before* `clear_run` runs.
   **Clearing site (corrected — the plan's original "`clear_run` clears it too" was a bug):**
   `execution_panel` does `set outcome → clear_run(ss) → st.rerun(scope="app")` in one pass,
   so if `clear_run` cleared `ss.run_error` it would wipe it *before* the app rerun renders
   it. The correct home — mirroring how `ss.results`/`baseline_agg` already survive
   `clear_run` — is **`clear_results`** (runs at the next run's start), which
   `_clear_process_state()` already calls, so log-reset is covered for free. Net: add
   `ss.run_error = None` to `clear_results`, leave `clear_run` alone. (`ss.run_error` isn't
   an `ExperimentResult` field, but it is run-scoped display state occupying the results
   slot, so it clears alongside `ss.results`.)
2. **Render it durably, owning the results slot.** A hard failure means there are *no*
   results, so — unlike the `ss.failed_replications` `st.warning` that annotates beside real
   results — this **replaces** the results area while `ss.run_error` is set. Render as
   `st.error` with a compact message, and a two-branch body mirroring #105's discovery
   surface: a clean-message error (setup `ValueError` / the pattern `NotImplementedError`)
   shows the message alone, no traceback; a log-carrying error (`SimulationError` → Prosimos
   subprocess tail from step 0; the future `TransformValidationError` → `validation.log`
   tail) adds an `st.expander` with the tail. One surface, two producers — the same split
   #105 already makes between a `ValueError` and a `CalledProcessError.output`.
3. **Relabel.** The current string is `"Simulation failed: …"`, which lies when the failure
   is pre-simulation (setup/validation — and per finding 4, the realistic setup failure is
   the *total-execution* class or the future gate, both pre- or post- but not "simulation"
   per se). Use a neutral `"Run failed"` and let the message body carry specifics.
4. **Clean out residual dead code along the touched path.** The error-path restructure will
   strand code; remove what it does rather than leaving it vestigial. Concrete candidates
   (verified at plan time, re-verify at impl time): **(a)** `FailedReplication.error: str`
   is read at *exactly one* site — the `SimulationError` "First error" message
   (`orchestrator.py:246`); the `failed_replications` warning shows only `len(...)`, never
   the strings. Once step 0 carries a tail, decide whether `error: str` survives or is
   superseded (it currently holds the useless `str(CalledProcessError)`). **(b)** the toast
   line in `execution_panel` is deleted, not kept beside the durable surface (it orphans no
   import — `st.toast` is just `st`). **(c)** re-check `_unpack_meta` and any `_on_error`
   helpers for orphaning if that closure's shape changes. This is a Craft/side-effect-hygiene
   pass scoped to the diff, not a repo-wide hunt.

### Phase B — the SoC decomposition (no behaviour change yet)
Land the split *before* the gate so the gate is a small addition, not a tangle. Each step
is behaviour-preserving and independently testable.

4. **`store.validation_report(exp, result) -> Path`.** Writes one line per violation
   (`f"{sev} {code}: {message}" + optional element id`) to `exp / "validation.log"`,
   returns the path. Pure serialization of a `VerificationResult`; no `verify` dependency.
5. **`Transformation.verify_transformed`** — new `@abstractmethod`
   `(bpmn_path: Path, target_activity: str) -> VerificationResult`. `XORSplitAutomation`
   implements it as a one-liner over `verify_fragment`. `transformations` imports `validate`
   only in the subclass. (ABC stays agnostic; mirrors `params_from_values` as the
   ABC-keeps-orchestrator-clean bridge precedent.)
6. **`TransformValidationError`** — a small exception type (home: `transformations.py`
   beside the ABC, or `validate.py` if it reads more naturally as a validation type). Carries
   the compact summary string and the `validation.log` path. This is what Phase A's surface
   renders — so a Prosimos `CalledProcessError` (`.output` tail) and a
   `TransformValidationError` (`validation.log` tail) render through **one** surface, two
   producers.

### Phase C — wire the gate
7. **`prepare_experiment` calls the gate.** After `apply_pattern` returns `bpmn_out`:
   `result = self.verify_transformed(bpmn_out, target_activity)`; if `result.errors`,
   `path = store.validation_report(out_dir, result)` then
   `raise TransformValidationError(summary, path)`. (`out_dir` **is** the experiment dir —
   the orchestrator passes `experiment_dir` down.) No retry: the transform is a
   deterministic pure function of its inputs, so a re-run fails identically; retry only
   makes sense for transient subprocess faults, and this raises *before* the pool exists.
8. **WARNING tier — do nothing in the UI yet.** Since #93 the transform emits **zero**
   warnings (Layer 2 asserts `violations == ()`), so a warning-rendering surface would be
   speculative. Decide: either (a) log warnings to `validation.log` without raising and stop
   there, or (b) leave warnings entirely unhandled until one actually fires. Recommend (a) —
   one `store` write, no UI, and the file is already being written on error anyway.

## Blast radius
- **Phase A core (corrected — not UI-only):** `orchestrator.py` (`FailedReplication` +
  `SimulationError` carry the log tail; audit `error: str`), `run_manager.py` (`ss.run_error`
  persist, cleared in `clear_results`). `execution_panel.py` (drop the toast) + `app.py`
  (render `ss.run_error`, owning the results slot) are the UI half.
- **Phase B/C core:** `transformations.py` (+1 abstract method, +1 impl, ~6 lines in
  `prepare_experiment`, +exception type), `store.py` (+1 writer). `apply_pattern` untouched.
  The gate's own raise propagates through `orchestrator.py` unchanged (as the DI-less
  `ValueError` already does). `demo.py` untouched (never calls `apply_pattern` — verified).
- **UI:** `execution_panel.py` (drop the toast for errors), `app.py` (render `ss.run_error`).
- **`validate.py` status change (the real cost):** maintainer trust tool → production gate.
  Its false positives now **block legitimate runs**, raising the bar on its own correctness.
  Its two-layer test strategy already establishes trust; the new risk is a *false ERROR* on a
  valid transform. Mitigant: the demo model transforms to `0` violations today (verified), and
  Layer 2 asserts `violations == ()` on the applied pattern — so a regression that would false-
  positive in production fails the suite first. CLAUDE.md §8's oracle-independence bullet and
  the §3 `validate.py` row both need a note that it is now in-path.

## Tests
- **`store.validation_report`** — round-trip a `VerificationResult` with mixed
  ERROR/WARNING violations; assert file contents + returned path (`tests/simulation/test_store.py`).
- **`verify_transformed`** — XOR impl delegates to `verify_fragment` and returns its result
  unchanged (thin, but pins the ABC wiring) (`tests/test_transformations.py`).
- **Gate raises** — `prepare_experiment` on a deliberately mis-wired model raises
  `TransformValidationError`, `validation.log` exists beside `model.bpmn`, and (regression
  guard) `model.bpmn` **is** written (the broken artifact is kept for inspection).
- **Gate passes** — `prepare_experiment` on the demo model raises nothing and writes no
  `validation.log` (or an empty/OK one, per the Phase B/8 warning decision).
- **Phase A** — `run_manager` persists `ss.run_error` and `clear_run`/reset helpers clear it;
  the `app.py` render path is exercised manually (Streamlit, like the rest of the UI).
- Full suite + coverage floor, `ruff check .`, `ruff format --check .`,
  `mypy core/ ui/ tests/ app.py --ignore-missing-imports`. Drive it end-to-end with a real
  mis-wired model (probe-style, as with the DI guard) — confirm the durable `st.error`
  renders and `validation.log` is on disk.

## Suggested sequencing (each lands as its own commit / small PR)
Phase A (surface) → Phase B (store writer, then `verify_transformed`, then the exception
type) → Phase C (the ~6-line gate). A is shippable alone and fixes a live gap; C is trivial
once A and B exist. Do **not** fold them — A changes the UI, C changes core, and mixing a
product change into a correctness gate is the altitude mistake we avoided on the DI branch.

## One-line summary for the next session
Durable `ss.run_error` surface first (mirror #105) → SoC split (`store.validation_report`
+ abstract `verify_transformed` + `TransformValidationError`, `apply_pattern` untouched) →
~6-line gate in `prepare_experiment` that verifies, writes `validation.log` via `store`, and
raises. ERROR raises, WARNING logs-only (zero warnings today), no retry (deterministic).
