# Demo model fixtures

Pre-baked discovery output used by **demo mode** (`core/demo.py` → `app.py`) so the
UI can run offline without Simod/Prosimos. These are *not* related to the logs in
`samples/` (those are input event logs you upload to run the real pipeline);
these two files are an already-discovered model.

| File | What it is |
|---|---|
| `model.bpmn` | The discovered BPMN process. |
| `params.json` | The Prosimos simulation-parameters JSON (resource profiles, task-resource distributions, gateway probabilities). |

**Source / provenance:** a real Simod one-shot discovery on the **LoanApp** process —
a widely-used *synthetic* loan-application benchmark (no real or personal data).
Renamed from `LoanApp_simplified_train.{bpmn,json}` to generic names; contents
unchanged.

In demo mode the app points the demo `LogIdentity` (`ss.log`) at these files, so
the real `list_activities` + factor-prepopulation path runs (per-activity
discovered durations, resource selector, `num_manual` centering). Only the **simulation** is
synthetic — `core/demo._fake_simulate` still produces the metrics.

To regenerate: run Simod on the LoanApp log and copy the resulting BPMN +
parameters JSON here.
