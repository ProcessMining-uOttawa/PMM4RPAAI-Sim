"""On-disk experiment store. Each experiment is a folder; status via files."""

from __future__ import annotations
import io
import json
import time
import uuid
import zipfile
from pathlib import Path
from typing import Callable

ROOT = Path("runs")


def _rep_path(base: Path, rep: int, suffix: str) -> Path:
    return base / f"rep_{rep:03d}_{suffix}"


# ── Experiment lifecycle ───────────────────────────────────────────────────────


def new_experiment(name: str) -> Path:
    eid = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    d = ROOT / eid
    (d / "scenarios").mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"id": eid, "name": name}))
    return d


def discovery_log(exp: Path) -> Path:
    return exp / "simod.log"


# ── Scenario replication paths ─────────────────────────────────────────────────


def scenario_dir(exp: Path, scenario_id: str) -> Path:
    d = exp / "scenarios" / scenario_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def replication_log(exp: Path, scenario_id: str, replication: int) -> Path:
    return _rep_path(scenario_dir(exp, scenario_id), replication, "log.csv")


def replication_stats(exp: Path, scenario_id: str, replication: int) -> Path:
    return _rep_path(scenario_dir(exp, scenario_id), replication, "stats.csv")


def replication_subprocess_log(exp: Path, scenario_id: str, replication: int) -> Path:
    return _rep_path(scenario_dir(exp, scenario_id), replication, "prosimos.log")


# ── Baseline replication paths ─────────────────────────────────────────────────


def baseline_dir(exp: Path, n_cases: int) -> Path:
    d = exp / "baseline" / f"cases_{n_cases}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def baseline_params_path(exp: Path) -> Path:
    """The single shared baseline params.json — one config reused across all n_cases."""
    d = exp / "baseline"
    d.mkdir(parents=True, exist_ok=True)
    return d / "params.json"


def baseline_log(exp: Path, replication: int, n_cases: int) -> Path:
    return _rep_path(baseline_dir(exp, n_cases), replication, "log.csv")


def baseline_stats(exp: Path, replication: int, n_cases: int) -> Path:
    return _rep_path(baseline_dir(exp, n_cases), replication, "stats.csv")


def baseline_subprocess_log(exp: Path, replication: int, n_cases: int) -> Path:
    return _rep_path(baseline_dir(exp, n_cases), replication, "prosimos.log")


# ── Export packaging ──────────────────────────────────────────────────────────


def _build_zip(populate: Callable[[zipfile.ZipFile], None]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        populate(z)
    return buf.getvalue()


def json_zip(json_paths: dict[str, Path]) -> bytes:
    """Pack scenario params.json files into a ZIP archive. Returns b"" if empty."""
    if not json_paths:
        return b""

    def _populate(z: zipfile.ZipFile) -> None:
        for sid, p in sorted(json_paths.items()):
            z.writestr(f"scenarios/{sid}_params.json", p.read_text())

    return _build_zip(_populate)


def group_zip(bpmn_path: Path, json_paths: dict[str, Path], stats_csv: str) -> bytes:
    """Pack BPMN, scenario params, and statistics CSV into a single ZIP archive."""

    def _populate(z: zipfile.ZipFile) -> None:
        z.write(str(bpmn_path), arcname="model.bpmn")
        z.writestr("statistics.csv", stats_csv)
        for sid, p in sorted(json_paths.items()):
            z.writestr(f"scenarios/{sid}_params.json", p.read_text())

    return _build_zip(_populate)


def event_logs_zip(
    scenario_log_paths: dict[str, list[Path]],
    baseline_log_paths: dict[int, list[Path]],
) -> bytes:
    """Pack Prosimos event log CSVs into a ZIP archive. Returns b"" if both are empty."""
    if not scenario_log_paths and not baseline_log_paths:
        return b""

    def _populate(z: zipfile.ZipFile) -> None:
        for sid, paths in sorted(scenario_log_paths.items()):
            for p in paths:
                if p.exists():
                    z.write(p, arcname=f"scenarios/{sid}/{p.name}")
        for n_cases, paths in sorted(baseline_log_paths.items()):
            for p in paths:
                if p.exists():
                    z.write(p, arcname=f"baseline/cases_{n_cases}/{p.name}")

    return _build_zip(_populate)
