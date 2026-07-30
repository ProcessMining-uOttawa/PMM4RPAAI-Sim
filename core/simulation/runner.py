"""Subprocess wrappers around Simod and Prosimos, plus Simod's event-log input
contract (CSV schema pre-flight, XES conversion)."""

from __future__ import annotations
import csv
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Callable

# POSIX: grace period after SIGTERM before escalating to SIGKILL when killing a
# runaway simulation subprocess (see terminate_process).
_KILL_GRACE_SECONDS = 2.0

# Venv layout differs by platform: Windows puts console scripts in Scripts\*.exe,
# POSIX puts them in bin/ with no suffix.
_VENV_BIN, _EXE_SUFFIX = ("Scripts", ".exe") if os.name == "nt" else ("bin", "")
SIMOD_EXE = Path("tools/simod-venv") / _VENV_BIN / f"simod{_EXE_SUFFIX}"
PROSIMOS_EXE = Path("tools/prosimos-venv") / _VENV_BIN / f"prosimos{_EXE_SUFFIX}"

# The CSV column schema Simod's reader requires, in the order the converter
# emits them. Column names are matched exactly (lowercase) — Simod reads by
# name, not position.
SIMOD_LOG_COLUMNS = ("case_id", "activity", "start_time", "end_time", "resource")


def _tail_lines(path: Path, n: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return "(log unreadable)"


def _spawn(cmd: list[str], new_session: bool = False, **kwargs) -> subprocess.Popen:
    """Launch a subprocess. `new_session=True` (POSIX only) puts it in its own
    process group so terminate_process can group-kill it without signalling the
    parent (e.g. the Streamlit server). Windows kills the PID tree by id instead,
    so it needs no session change."""
    if new_session and os.name != "nt":
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def _run_logged(
    cmd: list[str],
    proc_log: Path | None,
    on_spawn: Callable[[subprocess.Popen], None] | None = None,
    **kwargs,
) -> None:
    """Run a subprocess, optionally capturing stdout+stderr to proc_log.
    Raises CalledProcessError on failure — with the last 20 log lines attached
    as ``.output`` when proc_log is given (the bare branch attaches nothing).

    `on_spawn`, when given, is called with the live Popen right after launch so
    the executor can register it for cancellation; such a process is spawned in
    its own session (POSIX) so terminate_process can group-kill it. When
    `on_spawn` is None (e.g. discover()): no session change, no callback."""
    new_session = on_spawn is not None
    if proc_log is None:
        with _spawn(cmd, new_session=new_session, **kwargs) as proc:
            if on_spawn is not None:
                on_spawn(proc)
            returncode = proc.wait()
        if returncode != 0:
            raise subprocess.CalledProcessError(returncode, cmd)
        return
    with open(proc_log, "w", encoding="utf-8", errors="replace") as lf:
        with _spawn(
            cmd, new_session=new_session, stdout=lf, stderr=lf, **kwargs
        ) as proc:
            if on_spawn is not None:
                on_spawn(proc)
            returncode = proc.wait()
    if returncode != 0:
        raise subprocess.CalledProcessError(
            returncode, cmd, output=_tail_lines(proc_log, 20)
        )


def terminate_process(proc: subprocess.Popen) -> None:
    """Kill a running subprocess and any children, cross-platform. A no-op if the
    process already exited — safe to call in the finish/kill race."""
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            # taskkill /T walks the PID tree — the prosimos.exe console-script
            # launcher spawns a child python.exe that a bare kill would orphan.
            # The timeout bounds a hung taskkill.
            try:
                result = subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=_KILL_GRACE_SECONDS,
                )
            except subprocess.TimeoutExpired:
                result = None
            # taskkill hung (None) or reported failure (non-zero exit); if the
            # target is still alive, force the tracked launcher directly so
            # proc.wait() (and the pool join) can't block on it.
            if (result is None or result.returncode != 0) and proc.poll() is None:
                proc.kill()
        else:
            pgid = os.getpgid(proc.pid)
            if pgid == os.getpgid(0):
                # Defense-in-depth: a registered proc is always spawned in its
                # own session (on_spawn <-> start_new_session), so its group is
                # never ours. If that invariant is ever broken, refuse rather
                # than killpg the parent's (Streamlit server's) own group.
                return
            os.killpg(pgid, signal.SIGTERM)
            try:
                proc.wait(timeout=_KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def xes_to_simod_csv(xes_path: Path, csv_path: Path) -> Path:
    """Convert an XES log to the CSV schema Simod expects.

    Simod requires the SIMOD_LOG_COLUMNS schema.
    XES typically carries only `complete` events with a single timestamp;
    we derive `start_time` as the previous event's end_time per case (0
    duration for the first event in each case).
    """
    import xml.etree.ElementTree as ET
    import pandas as pd

    NS = "{http://www.xes-standard.org/}"

    def _attr(elem, tag: str, key: str) -> str | None:
        tag_name = f"{NS}{tag}"
        child = next(
            (c for c in elem if c.tag == tag_name and c.get("key") == key), None
        )
        return child.get("value") if child is not None else None

    root = ET.parse(str(xes_path)).getroot()
    rows = []
    for trace in root:
        if trace.tag != f"{NS}trace":
            continue
        case_id = _attr(trace, "string", "concept:name")
        for event in trace:
            if event.tag != f"{NS}event":
                continue
            rows.append(
                {
                    "case_id": case_id,
                    "activity": _attr(event, "string", "concept:name"),
                    "resource": _attr(event, "string", "org:resource"),
                    "end_time": _attr(event, "date", "time:timestamp"),
                }
            )

    if not rows:
        raise ValueError(
            f"No events parsed from {xes_path}. "
            "Expected XES namespace http://www.xes-standard.org/ with <trace>/<event> elements."
        )

    df = pd.DataFrame(rows)
    df["end_time"] = pd.to_datetime(df["end_time"], utc=True)
    nat_count = int(df["end_time"].isna().sum())
    if nat_count:
        raise ValueError(
            f"{nat_count} event(s) in {xes_path} are missing a time:timestamp attribute."
        )
    df = df.sort_values(["case_id", "end_time"]).reset_index(drop=True)
    df["start_time"] = df.groupby("case_id")["end_time"].shift(1)
    df["start_time"] = df["start_time"].fillna(df["end_time"])
    df = df[list(SIMOD_LOG_COLUMNS)]
    df.to_csv(csv_path, index=False)
    return csv_path


# --- Simod -------------------------------------------------------------------


def validate_simod_csv(csv_path: Path) -> None:
    """Pre-flight-check a CSV log against the column schema Simod's reader
    requires, so a malformed upload fails with an actionable message here
    instead of an opaque subprocess crash inside Simod.

    Checks: the file decodes as UTF-8; it has at least one non-blank row; that
    row's header contains every name in SIMOD_LOG_COLUMNS — matched as a set
    (order, duplicates, and extra columns are all fine) but cell-exactly, with
    no case or whitespace normalisation, because Simod's reader does none
    either; and at least one event row follows the header. Raises ValueError
    describing the problem; hints are informational only — columns are never
    renamed or remapped.
    """
    try:
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            # First non-blank row is the header; stop at the first event row —
            # the file may be huge and the rest of it is Simod's to read.
            header = next((row for row in reader if row), None)
            has_events = any(row for row in reader)
    except UnicodeDecodeError as e:
        raise ValueError(
            f"{csv_path.name} is not UTF-8-encoded CSV ({e}). Re-export it as "
            "UTF-8 CSV — Excel's 'Unicode text' export is UTF-16 and will not "
            "parse."
        ) from e

    if header is None:
        raise ValueError(f"{csv_path.name} is empty — no header row found.")

    missing = sorted(set(SIMOD_LOG_COLUMNS) - set(header))
    if missing:
        parts = [
            f"{csv_path.name} is missing required column(s): {', '.join(missing)}.",
            f"Found columns: {', '.join(header)}.",
            "Simod requires exactly these lowercase column names: "
            f"{', '.join(SIMOD_LOG_COLUMNS)}.",
        ]
        # Hint map is normalised; the membership check above deliberately is
        # not — repr makes a whitespace culprit visible in the hint.
        variants = {cell.strip().lower(): cell for cell in header}
        for col in missing:
            variant = variants.get(col)
            if variant is not None:
                parts.append(f"Found {variant!r} — Simod requires exactly {col!r}.")
        if len(header) == 1 and ";" in header[0]:
            parts.append(
                "The header parsed as a single column — the file looks "
                "semicolon-delimited; Simod requires comma-separated CSV."
            )
        raise ValueError("\n\n".join(parts))

    if not has_events:
        raise ValueError(f"{csv_path.name} has a header but no event rows.")


def _subproc_env(java_home_override: str | None) -> dict:
    env = os.environ.copy()
    if java_home_override:
        env["JAVA_HOME"] = java_home_override
        # Prepend Corretto-8's bin so Simod's child `java` resolves to it ahead
        # of any system Java on PATH (JAVA_HOME alone doesn't affect PATH lookup).
        env["PATH"] = (
            str(Path(java_home_override) / "bin") + os.pathsep + env.get("PATH", "")
        )
    return env


def _locate_simod_outputs(out_dir: Path) -> tuple[Path, Path]:
    """Find the (BPMN, Prosimos params JSON) pair in Simod's output tree.

    Simod writes exactly one BPMN; the params JSON normally sits beside it with
    the same stem, falling back to any sibling JSON that isn't one of Simod's
    bookkeeping files (runtimes / canonical model).
    """
    bpmns = list(out_dir.rglob("*.bpmn"))
    if len(bpmns) != 1:
        raise RuntimeError(
            f"Expected exactly 1 BPMN from Simod, found {len(bpmns)}: {bpmns}"
        )
    bpmn = bpmns[0]
    params_path = bpmn.with_suffix(".json")
    if not params_path.exists():
        candidates = [
            p
            for p in bpmn.parent.glob("*.json")
            if p.name not in {"runtimes.json", "canonical_model.json"}
        ]
        if not candidates:
            raise RuntimeError(f"No Prosimos params JSON next to {bpmn}")
        params_path = candidates[0]
    return bpmn, params_path


def simod_csv_case_count(csv_path: Path) -> int:
    """Number of distinct cases in a Simod-schema CSV log.

    The model fidelity check pins its n_cases to this — extreme-value cycle
    statistics (min/max) are sample-size-dependent, so the comparison is only
    valid at equal case counts. Expects the SIMOD_LOG_COLUMNS schema (the
    converted / pre-flighted log discover() feeds Simod).
    """
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = csv.reader(f)
        # First non-blank row is the header — the same skip validate_simod_csv
        # applies, so every file the pre-flight accepts counts cleanly.
        header = next((row for row in rows if row), None)
        if header is None:
            return 0
        case_column = header.index("case_id")
        return len({row[case_column] for row in rows if row})


def discover(
    log_path: Path,
    run_dir: Path,
    java_home: str | None = None,
    proc_log: Path | None = None,
) -> tuple[Path, Path, Path]:
    """Run Simod one-shot on `log_path`; return (bpmn, prosimos_json, simod_csv).

    `--one-shot` skips Simod's hyperparameter optimization and runs a single
    discovery pass with defaults — fast enough for an interactive UI.
    Log columns required (CSV): SIMOD_LOG_COLUMNS — a direct CSV upload is
    pre-flighted by validate_simod_csv before the subprocess spawns.
    simod_csv is the Simod-ready log the subprocess actually read: the
    converted CSV for an XES upload, the upload itself for CSV — the file the
    model fidelity check computes its observed statistics from.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    out_dir = run_dir / "outputs"
    if log_path.suffix.lower() == ".xes":
        csv_path = run_dir / (log_path.stem + ".csv")
        xes_to_simod_csv(log_path, csv_path)
        log_for_simod = csv_path
    else:
        validate_simod_csv(log_path)
        log_for_simod = log_path
    _run_logged(
        [
            str(SIMOD_EXE.resolve()),
            "--one-shot",
            "--event-log",
            str(log_for_simod.resolve()),
            "--output",
            str(out_dir.resolve()),
        ],
        proc_log,
        cwd=str(run_dir),
        env=_subproc_env(java_home),
    )
    bpmn, params_json = _locate_simod_outputs(out_dir)
    return bpmn, params_json, log_for_simod


# --- Prosimos ---------------------------------------------------------------


def simulate(
    bpmn: Path,
    params_json: Path,
    n_cases: int,
    out_log: Path,
    stat_out: Path | None = None,
    starting_at: str = "2025-01-01T00:00:00+00:00",
    proc_log: Path | None = None,
    on_spawn: Callable[[subprocess.Popen], None] | None = None,
) -> Path:
    """Run one Prosimos replication; returns the event-log CSV path."""
    out_log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(PROSIMOS_EXE.resolve()),
        "start-simulation",
        "--bpmn_path",
        str(bpmn.resolve()),
        "--json_path",
        str(params_json.resolve()),
        "--total_cases",
        str(n_cases),
        "--log_out_path",
        str(out_log.resolve()),
        "--starting_at",
        starting_at,
        # No --is_event_added_to_log: intermediate-event rows (e.g. Simod's
        # extraneous-delay timer firings) would pollute the exported logs with
        # phantom activities, and replication_metrics rejects logs containing
        # them. Prosimos parses the flag's value truthily — even
        # "--is_event_added_to_log false" would ENABLE it — so omission is the
        # only way to keep it off.
    ]
    if stat_out is not None:
        cmd += ["--stat_out_path", str(stat_out.resolve())]
    _run_logged(cmd, proc_log, on_spawn=on_spawn)
    return out_log
