"""Subprocess wrappers around Simod and Prosimos."""
from __future__ import annotations
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from .constants import BPMN_NS


def _tail_lines(path: Path, n: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return "(log unreadable)"


def _run_logged(cmd: list, proc_log: Path | None, **kwargs) -> None:
    """Run a subprocess, optionally capturing stdout+stderr to proc_log.
    Raises CalledProcessError with the last 20 log lines on failure."""
    if proc_log is None:
        subprocess.run(cmd, check=True, **kwargs)
        return
    with open(proc_log, "w", encoding="utf-8", errors="replace") as lf:
        result = subprocess.run(cmd, check=False, stdout=lf, stderr=lf, **kwargs)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=_tail_lines(proc_log, 20))

SIMOD_EXE    = Path("tools/simod-venv/Scripts/simod.exe")
PROSIMOS_EXE = Path("tools/prosimos-venv/Scripts/prosimos.exe")


def xes_to_simod_csv(xes_path: Path, csv_path: Path) -> Path:
    """Convert an XES log to the CSV schema Simod expects.

    Simod requires columns: case_id, activity, start_time, end_time, resource.
    XES typically carries only `complete` events with a single timestamp;
    we derive `start_time` as the previous event's end_time per case (0
    duration for the first event in each case).
    """
    import pm4py
    df = pm4py.read_xes(str(xes_path))
    rename = {
        "case:concept:name": "case_id",
        "concept:name":      "activity",
        "org:resource":      "resource",
        "time:timestamp":    "end_time",
    }
    df = df.rename(columns=rename)[["case_id", "activity", "resource", "end_time"]]
    df = df.sort_values(["case_id", "end_time"]).reset_index(drop=True)
    df["start_time"] = df.groupby("case_id")["end_time"].shift(1)
    df["start_time"] = df["start_time"].fillna(df["end_time"])
    df = df[["case_id", "activity", "start_time", "end_time", "resource"]]
    df.to_csv(csv_path, index=False)
    return csv_path


# --- Simod -------------------------------------------------------------------

def _subproc_env(java_home_override: str | None) -> dict:
    env = os.environ.copy()
    if java_home_override:
        env["JAVA_HOME"] = java_home_override
        env["PATH"] = str(Path(java_home_override) / "bin") + os.pathsep + env.get("PATH", "")
    return env


def discover(log_path: Path, run_dir: Path,
             java_home: str | None = None,
             proc_log: Path | None = None) -> tuple[Path, Path]:
    """Run Simod one-shot on `log_path`; return (bpmn, prosimos_json).

    `--one-shot` skips Simod's hyperparameter optimization and runs a single
    discovery pass with defaults — fast enough for an interactive UI.
    Log columns required (CSV): case_id, activity, start_time, end_time, resource.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    out_dir = run_dir / "outputs"
    if log_path.suffix.lower() == ".xes":
        csv_path = run_dir / (log_path.stem + ".csv")
        xes_to_simod_csv(log_path, csv_path)
        log_for_simod = csv_path
    else:
        log_for_simod = log_path
    _run_logged(
        [str(SIMOD_EXE.resolve()),
         "--one-shot",
         "--event-log", str(log_for_simod.resolve()),
         "--output", str(out_dir.resolve())],
        proc_log,
        cwd=str(run_dir),
        env=_subproc_env(java_home),
    )
    bpmns = list(out_dir.rglob("*.bpmn"))
    if len(bpmns) != 1:
        raise RuntimeError(f"Expected exactly 1 BPMN from Simod, found {len(bpmns)}: {bpmns}")
    bpmn = bpmns[0]
    # Prosimos simulation params JSON sits next to the BPMN with the same stem.
    params = bpmn.with_suffix(".json")
    if not params.exists():
        # Fallback: any sibling JSON that isn't runtimes/canonical.
        cands = [p for p in bpmn.parent.glob("*.json")
                 if p.name not in {"runtimes.json", "canonical_model.json"}]
        if not cands:
            raise RuntimeError(f"No Prosimos params JSON next to {bpmn}")
        params = cands[0]
    return bpmn, params


def list_activities(bpmn_path: Path) -> list[str]:
    """Pull task names out of a BPMN file without loading pm4py."""
    tree = ET.parse(str(bpmn_path))
    names = []
    for tag in ("task", "userTask", "serviceTask", "manualTask",
                "businessRuleTask", "scriptTask", "sendTask", "receiveTask"):
        for el in tree.findall(f".//{{{BPMN_NS}}}{tag}"):
            n = el.get("name")
            if n:
                names.append(n)
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


# --- Prosimos ---------------------------------------------------------------

def simulate(bpmn: Path, params_json: Path, n_cases: int,
             out_log: Path, stat_out: Path | None = None,
             starting_at: str = "2025-01-01T00:00:00+00:00",
             proc_log: Path | None = None) -> Path:
    """Run one Prosimos replication; returns the event-log CSV path."""
    out_log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(PROSIMOS_EXE.resolve()), "start-simulation",
           "--bpmn_path", str(bpmn.resolve()),
           "--json_path", str(params_json.resolve()),
           "--total_cases", str(n_cases),
           "--log_out_path", str(out_log.resolve()),
           "--starting_at", starting_at]
    if stat_out is not None:
        cmd += ["--stat_out_path", str(stat_out.resolve())]
    _run_logged(cmd, proc_log)
    return out_log
