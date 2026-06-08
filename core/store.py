"""On-disk experiment store. Each experiment is a folder; status via files."""
from __future__ import annotations
import json
import time
import uuid
from pathlib import Path

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

def baseline_dir(exp: Path) -> Path:
    d = exp / "baseline"
    d.mkdir(parents=True, exist_ok=True)
    return d


def baseline_log(exp: Path, replication: int) -> Path:
    return _rep_path(baseline_dir(exp), replication, "log.csv")


def baseline_stats(exp: Path, replication: int) -> Path:
    return _rep_path(baseline_dir(exp), replication, "stats.csv")


def baseline_subprocess_log(exp: Path, replication: int) -> Path:
    return _rep_path(baseline_dir(exp), replication, "prosimos.log")
