# PMM4RPAAI-Sim

**Process Mining + Modeling for RPA/AI Simulation.**
A local web tool that uses an event log to decide — via simulation — whether
automating a chosen activity in a business process would meet stakeholder
goals (cycle time, cost, …).

The pipeline: **Simod** discovers a BPMN model and Prosimos parameters from
the log → the user picks a target activity and a substitution pattern → a
**Taguchi orthogonal array** generates scenarios from the pattern's factors
→ **Prosimos** runs N replications per scenario → metrics are aggregated
and ranked against user goals.

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

# tool venvs
/opt/homebrew/opt/python@3.9/bin/python3.9 -m venv tools/simod-venv
/opt/homebrew/opt/python@3.9/bin/python3.9 -m venv tools/prosimos-venv
tools/simod-venv/bin/pip install simod
tools/prosimos-venv/bin/pip install prosimos

# host (use your normal Python 3.12+; macOS has no bare `python` — use python3)
python3 -m pip install -r requirements.txt
python3 -m streamlit run app.py     # or just: streamlit run app.py
```

On Intel Macs the Homebrew prefix is `/usr/local` instead of `/opt/homebrew`.
The app's preflight auto-detects the JDK 8 in `~/Library/Java/JavaVirtualMachines`
and injects it as `JAVA_HOME` for Simod's subprocess only — your system Java
(11/17/21/…) is untouched.

Then upload [`samples/IssueTracker.xes`](samples/IssueTracker.xes) in the
sidebar and try the Demo-mode toggle if you want to explore the UI without
running real simulations.

## Project documentation for Claude / contributors

Read **[CLAUDE.md](CLAUDE.md)** before making changes — it's the project
memory: architecture seams, the substitution-pattern interface, hard-won
Windows setup caveats, and the Streamlit rerun trap (it has bitten us
twice).

## License

MIT — see [LICENSE](LICENSE).
