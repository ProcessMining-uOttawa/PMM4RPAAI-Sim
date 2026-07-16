"""On-disk experiment store: per-experiment folder layout under runs/ and the
export ZIP packagers."""

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
    exp_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    exp_dir = ROOT / exp_id
    (exp_dir / "scenarios").mkdir(parents=True)
    (exp_dir / "meta.json").write_text(json.dumps({"id": exp_id, "name": name}))
    return exp_dir


def discovery_log(exp: Path) -> Path:
    return exp / "simod.log"


# ── Scenario replication paths ─────────────────────────────────────────────────


def scenario_dir(exp: Path, scenario_id: str) -> Path:
    path = exp / "scenarios" / scenario_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def replication_log(exp: Path, scenario_id: str, replication: int) -> Path:
    return _rep_path(scenario_dir(exp, scenario_id), replication, "log.csv")


def replication_stats(exp: Path, scenario_id: str, replication: int) -> Path:
    return _rep_path(scenario_dir(exp, scenario_id), replication, "stats.csv")


def replication_subprocess_log(exp: Path, scenario_id: str, replication: int) -> Path:
    return _rep_path(scenario_dir(exp, scenario_id), replication, "prosimos.log")


# ── Baseline replication paths ─────────────────────────────────────────────────


def baseline_dir(exp: Path, n_cases: int) -> Path:
    path = exp / "baseline" / f"cases_{n_cases}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def baseline_params_path(exp: Path) -> Path:
    """The single shared baseline params.json — one config reused across all n_cases."""
    base_dir = exp / "baseline"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "params.json"


def baseline_log(exp: Path, n_cases: int, replication: int) -> Path:
    return _rep_path(baseline_dir(exp, n_cases), replication, "log.csv")


def baseline_stats(exp: Path, n_cases: int, replication: int) -> Path:
    return _rep_path(baseline_dir(exp, n_cases), replication, "stats.csv")


def baseline_subprocess_log(exp: Path, n_cases: int, replication: int) -> Path:
    return _rep_path(baseline_dir(exp, n_cases), replication, "prosimos.log")


# ── Export packaging ──────────────────────────────────────────────────────────


def _build_zip(populate: Callable[[zipfile.ZipFile], None]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        populate(archive)
    return buf.getvalue()


def _write_scenario_params(
    archive: zipfile.ZipFile, json_paths: dict[str, Path]
) -> None:
    for sid, params_path in sorted(json_paths.items()):
        archive.writestr(f"scenarios/{sid}_params.json", params_path.read_text())


def json_zip(json_paths: dict[str, Path]) -> bytes:
    """Pack scenario params.json files into a ZIP archive. Returns b"" if empty."""
    if not json_paths:
        return b""

    def _populate(archive: zipfile.ZipFile) -> None:
        _write_scenario_params(archive, json_paths)

    return _build_zip(_populate)


def group_zip(
    bpmn_path: Path, json_paths: dict[str, Path], stats_csv: str, sn_csv: str
) -> bytes:
    """Pack BPMN, scenario params, statistics CSV, and S/N CSV into one ZIP archive."""

    def _populate(archive: zipfile.ZipFile) -> None:
        archive.write(bpmn_path, arcname="model.bpmn")
        archive.writestr("statistics.csv", stats_csv)
        archive.writestr("signal_to_noise.csv", sn_csv)
        _write_scenario_params(archive, json_paths)

    return _build_zip(_populate)


def event_logs_zip(
    scenario_log_paths: dict[str, list[Path]],
    baseline_log_paths: dict[int, list[Path]],
) -> bytes:
    """Pack Prosimos event log CSVs into a ZIP archive. Returns b"" if both are empty."""
    if not scenario_log_paths and not baseline_log_paths:
        return b""

    def _populate(archive: zipfile.ZipFile) -> None:
        for sid, paths in sorted(scenario_log_paths.items()):
            for log_path in paths:
                if log_path.exists():
                    archive.write(log_path, arcname=f"scenarios/{sid}/{log_path.name}")
        for n_cases, paths in sorted(baseline_log_paths.items()):
            for log_path in paths:
                if log_path.exists():
                    archive.write(
                        log_path, arcname=f"baseline/cases_{n_cases}/{log_path.name}"
                    )

    return _build_zip(_populate)
