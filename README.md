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
