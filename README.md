# PMM4RPAAI-Sim

**Goal-oriented Process Automation via Simulation** (repo name: Process
Mining + Modeling for RPA/AI Simulation).
A local web tool that uses an event log to decide — via simulation — whether
automating a chosen activity in a business process would meet stakeholder
goals (cycle time, cost, …).

The pipeline: **Simod** discovers a BPMN model and Prosimos parameters from
the log → the user picks a target activity → a **Taguchi orthogonal array**
generates scenarios from the fixed `XORSplitAutomation` pattern's factors →
**Prosimos** runs N replications per scenario → metrics are aggregated and
ranked against user goals.

## Quick start (Windows)

```powershell
# system deps (one-time)
winget install Python.Python.3.9     --source winget --silent
winget install Amazon.Corretto.8.JDK --source winget --silent

# tool venvs
py -3.9 -m venv tools\simod-venv
py -3.9 -m venv tools\prosimos-venv
.\tools\simod-venv\Scripts\pip install simod
.\tools\prosimos-venv\Scripts\pip install prosimos

# host (use your normal Python 3.12+)
pip install -r requirements.txt
python -m streamlit run app.py
```

## Quick start (macOS)

```bash
# system deps (one-time)
brew install python@3.9        # keg-only; not linked onto PATH — that's fine
# JDK 8 for SplitMiner (arm64 tarball; no sudo needed — user-level JVM dir).
# Intel Macs: swap aarch64 → x64 in the URL.
mkdir -p ~/Library/Java/JavaVirtualMachines
curl -sSL https://corretto.aws/downloads/latest/amazon-corretto-8-aarch64-macos-jdk.tar.gz \
  | tar xz -C ~/Library/Java/JavaVirtualMachines

# tool venvs (brew --prefix works on both Apple Silicon and Intel)
"$(brew --prefix python@3.9)/bin/python3.9" -m venv tools/simod-venv
"$(brew --prefix python@3.9)/bin/python3.9" -m venv tools/prosimos-venv
tools/simod-venv/bin/pip install simod
tools/prosimos-venv/bin/pip install prosimos

# host (use your normal Python 3.12+; macOS has no bare `python` — use python3)
python3 -m pip install -r requirements.txt
python3 -m streamlit run app.py     # or just: streamlit run app.py
```

The app's preflight auto-detects the JDK 8 in `~/Library/Java/JavaVirtualMachines`
and injects it as `JAVA_HOME` for Simod's subprocess only — your system Java
(11/17/21/…) is untouched.

## The main flow

**Two-minute pass, no external tools** — Demo mode is on by default, uses a
real pre-baked discovery, and fakes only the simulation:

1. Click **Use sample log** in the sidebar. The demo model loads; the page
   splits into **Experiment** and **Model fidelity** tabs.
2. **1 · Activity & pattern** — pick the target activity to automate.
3. **2 · Factor levels** — the Low/Mid/High grid is prepopulated from the
   discovered durations. Optionally **Pin** a factor to one value: it leaves
   the design, and the Panel 4 badge shows the design shrinking (L18 → L9).
4. **3 · Goals** — choose 1–3 goal metrics and edit their Target/Worst
   thresholds (defaulted around the measured baseline).
5. **4 · Execution** — ▶ Run all scenarios (instant in demo).
6. **5 · Results** — the ranked table (goal scores, weakest-link overall
   score), the Main effects charts (which factors matter), the export
   buttons. Demo results are labeled illustrative.

**The real pipeline** (after the setup above):

1. Toggle **Demo mode off**; the sidebar's Simod preflight must be all green.
2. Upload [`samples/PurchasingExample.csv`](samples/PurchasingExample.csv) —
   discovery starts automatically (Fast mode, a few minutes; time scales
   with log size).
3. Recommended before trusting results: open the **Model fidelity** tab and
   run the as-discovered simulation to compare the model against your log.
   If the fit is poor, switch Discovery to **Calibrated** in the sidebar and
   click **Reset log** to re-discover.
4. Then the same Panels 1–5 flow. Runs execute real Prosimos replications in
   parallel (plus the 0%-automation baseline); Panel 5 gains the Baseline
   comparison tab and the event-log exports.

Other sample logs: [`LoanApp_simplified_train.csv`](samples/LoanApp_simplified_train.csv)
(the demo model's log family) and
[`Claims Management.csv`](samples/Claims%20Management.csv) (kept with its
original capitalised headers — uploading it as-is demonstrates the automatic
header normalization: `Case_ID`, `Start_Time`, … are rewritten to the
lowercase names Simod requires).

## Project documentation

- **[docs/architecture.md](docs/architecture.md)** — how the system is built
  and how the method works: the pipeline, the Taguchi design, the pattern,
  and the limits of discovery and simulation.
- **[docs/metrics.md](docs/metrics.md)** — what each reported KPI means: the
  clock it uses, inclusions/exclusions, and how far it is validated against
  Prosimos. Start there if a number in the results table is surprising.
- **[CLAUDE.md](CLAUDE.md)** — the design record and project memory: why
  things are shaped the way they are, rejected alternatives, setup caveats,
  and orientation for AI-assisted work. Read it before making changes.

## License

MIT — see [LICENSE](LICENSE).
