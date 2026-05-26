"""On-disk experiment store. Each experiment is a folder; status via files."""
from __future__ import annotations
import json, time, uuid
from pathlib import Path

ROOT = Path("runs")


def new_experiment(name: str) -> Path:
    eid = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    d = ROOT / eid
    (d / "scenarios").mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"id": eid, "name": name}))
    return d


def scenario_dir(exp: Path, scenario_id: str) -> Path:
    d = exp / "scenarios" / scenario_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def replication_log(exp: Path, scenario_id: str, replication: int) -> Path:
    return scenario_dir(exp, scenario_id) / f"rep_{replication:03d}_log.csv"


def replication_stats(exp: Path, scenario_id: str, replication: int) -> Path:
    return scenario_dir(exp, scenario_id) / f"rep_{replication:03d}_stats.csv"


def replication_subprocess_log(exp: Path, scenario_id: str, replication: int) -> Path:
    return scenario_dir(exp, scenario_id) / f"rep_{replication:03d}_prosimos.log"


def discovery_log(exp: Path) -> Path:
    return exp / "simod.log"
