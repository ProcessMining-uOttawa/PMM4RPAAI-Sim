# Metric definitions

This is the reference for **what each KPI the tool reports actually means** —
the clock it uses, what it includes and excludes, whether it ranks scenarios,
and how much we trust it. It is the "what does *Cycle Time* mean" layer that sits
above three things it does **not** duplicate:

- **implementation** — how each metric is computed, in the code it links to;
- **display config** — exact labels, units, and decimals, in
  [`core/metrics.py`](../core/metrics.py) (the single source of truth for those);
- **rationale / history** — why the design is the way it is, in `CLAUDE.md` §8.

So this doc states *definitions* (the durable facts), not formulas or column
names. Where it names a display label it is illustrative — the authoritative
label lives in `core/metrics.py`. It is inside `/doc-rot`'s audit scope, so it
gets checked against the code for drift.

---

## Read this first: one clock, and what it deliberately excludes

Every cycle-time number the tool reports uses **one anchor pair**: the **start
of a case's first activity → the end of its last activity**. This is the
log-based case duration — the same definition the mainstream process-mining
tools use (Celonis anchors `CASE_START` on the first activity of the case;
Apromore's case duration runs from the log's first to last timestamp).

- **Cycle Time (per case)** = the per-case span on that clock. This is what the
  tool **ranks scenarios on** (and feeds the Taguchi signal-to-noise analysis).
- **Total Cycle Time** = the same spans **summed across cases**, so
  `Total Cycle Time = Cycle Time (mean) × number of cases` holds by
  construction, in both real and demo mode. It is a **display / comparison**
  number (Baseline tab) — it does **not** rank scenarios.

**What this tool deliberately does not measure: door-to-door lead time**
(case *arrival* → case completion — the queueing-theory "time in system").
A case's arrival is not an activity, and it is unobservable at every layer of
this pipeline: real-world event logs almost never record it (a log begins at
the first *logged* activity — left truncation is the industry-normal shape),
Simod's input schema (case, activity, start, end, resource) cannot represent
it, and the simulator's internal arrival events are not exported to the event
logs (exporting them pollutes the logs with phantom non-activity rows that
external tools discover as fake activities). Consequently the **head wait**
(arrival → first activity start: Simod's extraneous-delay timer plus any
queueing before the first task grabs a resource) and any **tail wait** (a
trailing non-activity event after the last task) sit outside every reported
number. They still *elapse inside the simulation* — the timers fire and shape
every downstream timestamp — they are just not part of any metric. For a
specific run, Prosimos's own stats CSV still reports its arrival-anchored
`idle_cycle_time` KPI, readable by hand beside the run's outputs; it is not a
product metric and the trust checker does not cover the cycle dimension.

The exclusion is also the right ranking choice: the waits are insensitive to
the intervention under study (automating the target activity does not change
how long a case sits before its *first* activity), so folding them into the
ranked metric would add variation that dilutes the automation signal the
experiment exists to detect.

---

## Metrics

Each metric below gives a plain **definition**, then an **implementation &
trust** note for maintainers.

### Cycle Time — *ranked*

Per-case wall-clock time from the **start of the first activity** to the **end of
the last activity**. Head and tail waits excluded (see above). Scenarios are
ranked on the **mean** across cases; **median**, **min**, and **max** case time
are also available as selectable goal indicators (the ranked/default one is the
mean).

**Total Cycle Time** (the same spans summed across cases — mean × number of
cases) is reported separately as a display-only comparison figure, not a
ranking input.

> **Implementation & trust.** Derived per replication in
> [`core/simulation/prosimos/replication_metrics.py`](../core/simulation/prosimos/replication_metrics.py)
> straight from the event log's timestamps. **The cycle dimension has no
> Prosimos oracle** — Prosimos reports only arrival-anchored cycles, never a
> first-activity one — so its correctness rests on the shared extraction
> machinery (it reads the same timestamps the oracle-checked Cost reconciles
> against) plus unit tests, and the total inherits the mean's trust by
> arithmetic. See "How metrics are trusted" below.

### Cost — *ranked*

Per-case labour cost = each resource's **working time × its hourly rate**,
summed over the case. "Working time" is **calendar-aware**: only the hours a
resource is actually on-shift are charged, **not** wall-clock time. A task that
spans overnight is billed for the working portion only. Scenarios are ranked on
the **mean** cost per case; **Total Cost** is the display-only sum.

> **Implementation & trust.** Cost is computed in
> [`core/simulation/prosimos/calendars.py`](../core/simulation/prosimos/calendars.py),
> which intersects each activity's span with its resource's weekly working
> calendar. It is **oracle-checked** against Prosimos's own cost accounting (and
> its rate-free twin, total working seconds) in the trust checker; on real runs
> the two agree to the cent, though the checker allows a small float-slack band.

### Rework — *rate ranked; count display-only*

Repeated-activity work: for any activity a case performs **more than once**, the
extra performances are rework (a case doing an activity 3 times contributes 2).
Reported as:

- **Rework Rate** — the **percentage of cases** that have *any* repeated-activity
  rework (0–100). This is the **rankable** form.
- **Rework Count** — the total number of extra performances across all cases.
  Display-only.
- **Rework Count per case** — the mean of the above per case. A selectable extra
  indicator under Rework Rate.

**Count and rate collapse differently.** The count accumulates *every* repeat;
the rate is **binary per case**. A case reworked five times and a case reworked
once both count once toward the rate, but contribute 5 and 1 to the count.

**Bot failures are deliberately not counted as rework** — they are a separate
metric (below).

> **Implementation & trust.** Counted in
> [`core/simulation/prosimos/replication_metrics.py`](../core/simulation/prosimos/replication_metrics.py)
> from repeated activity names in the log (no resource/task-name knowledge
> needed). **No Prosimos oracle exists** for rework, so it is validated by unit
> tests, not the trust checker.

### Bot Failures — *display-only*

The count of **cases where the bot ran and a human then redid the same work** —
i.e. both the automated activity and its human original appear in the case. It is
**binary per case**: a case counts once no matter how many times the pair
repeats.

Reported as a **count only** — there is intentionally **no rate**, and it is
**not rankable**. A bot-failure rate is derivable from the scenario's own
configuration in expectation (roughly `pct_auto × (1 − pct_ok)`), so ranking on
it would reward a chosen configuration rather than a discovered simulation
outcome. Its baseline value is structurally **0** (at 0% automation no case ever
reaches the bot).

> **Implementation & trust.** Computed in
> [`core/simulation/prosimos/replication_metrics.py`](../core/simulation/prosimos/replication_metrics.py)
> from the co-occurrence of the automated and original activity in a case. No
> Prosimos oracle; validated by unit tests.

---

## What ranks vs what's display-only

| Metric | Ranks scenarios? | Notes |
|---|---|---|
| Cycle Time (per case, first-start) | **Yes** | mean ranked; median/min/max selectable |
| Cost (per case, mean) | **Yes** | |
| Rework Rate | **Yes** | |
| Total Cycle Time (mean × cases) | No | Baseline comparison only |
| Rework Count | No | Baseline comparison / export |
| Bot Failures | No | count only; config-echo, so not a goal |

Only the ranked metrics form scenario goals and feed the signal-to-noise
analysis. The default/ranked indicator of each rankable metric is always
included in its goal score; the extras (e.g. median cycle time) are optional
weighted additions.

---

## How metrics are trusted

Every metric is derived from first principles — the Prosimos **event log** plus
the simulation **parameters JSON** — never read back from Prosimos's summary
statistics. Those statistics are instead used as an independent **oracle** by a
trust checker that cross-checks our numbers against Prosimos's own accounting:

```
python -m core.simulation.validate <experiment-dir>
```

(see [`core/simulation/validate.py`](../core/simulation/validate.py)).

The checker can only compare a metric against a number Prosimos itself reports,
which splits the metrics into two tiers:

| Trust tier | Metrics | How |
|---|---|---|
| **Oracle-checked** (reconciled against Prosimos) | Cost · working seconds · case count | agreement within a float-slack band (0.5%, or a small floor); case count exact |
| **Unit-tested only** (no Prosimos oracle exists) | Cycle Time (per case and total) · Rework · Bot Failures | hand-derived test fixtures |

The important nuance: the **entire cycle dimension** is in the *unit-tested*
tier, because Prosimos emits only arrival-anchored cycle KPIs and never a
first-activity one to check against. Its correctness is anchored indirectly —
it reads `start_time`/`end_time`, the *same* inputs the oracle-checked Cost
reconciles against (cost bills each activity's `[start, end)` span), so a
drift in those surfaces as a checker failure; only the per-case aggregation
arithmetic is checker-blind, and that is pinned by unit tests. The exact case
count check doubles as a vanished-case detector — a case would have to lose
*all* its rows to change the ranked mean's denominator unnoticed.
