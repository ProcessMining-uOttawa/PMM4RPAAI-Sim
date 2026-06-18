"""Read-only helpers for BPMN files and Prosimos JSON."""
from __future__ import annotations
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass

from . import BPMN_NS as _BPMN, BPMN_TASK_TAGS as _TASK_TAGS
from ..constants import KEY_TASK_RESOURCE_DISTRIBUTION, KEY_RESOURCE_PROFILES


def find_task_by_name(tree: ET.ElementTree, name: str) -> ET.Element | None:
    for tag in _TASK_TAGS:
        for el in tree.findall(f".//{{{_BPMN}}}{tag}"):
            if el.get("name") == name:
                return el
    return None


def list_activities(bpmn_path) -> list[str]:
    """Pull task names out of a BPMN file without loading pm4py."""
    tree = ET.parse(str(bpmn_path))
    names = []
    for tag in _TASK_TAGS:
        for el in tree.findall(f".//{{{_BPMN}}}{tag}"):
            n = el.get("name")
            if n:
                names.append(n)
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def task_resources(prosimos_json: dict, task_id: str) -> list[dict]:
    """Return [{id, name}] for resources assigned to task_id, in assignment order."""
    name_by_id = {
        r["id"]: r.get("name", r["id"])
        for profile in prosimos_json.get(KEY_RESOURCE_PROFILES, [])
        for r in profile.get("resource_list", [])
    }
    for entry in prosimos_json.get(KEY_TASK_RESOURCE_DISTRIBUTION, []):
        if entry.get("task_id") == task_id:
            return [
                {"id": r["resource_id"], "name": name_by_id.get(r["resource_id"], r["resource_id"])}
                for r in entry.get("resources", [])
            ]
    return []


def shared_resource_ids(prosimos_json: dict) -> set[str]:
    """Return resource IDs that appear in more than one task's distribution entry."""
    counts: Counter = Counter(
        r["resource_id"]
        for entry in prosimos_json.get(KEY_TASK_RESOURCE_DISTRIBUTION, [])
        for r in entry.get("resources", [])
    )
    return {rid for rid, n in counts.items() if n > 1}


def resource_pool_size(prosimos_json: dict, resource_id: str) -> int | None:
    """Return the current pool size (amount) for a resource, or None if not found."""
    for profile in prosimos_json.get(KEY_RESOURCE_PROFILES, []):
        for r in profile.get("resource_list", []):
            if r.get("id") == resource_id:
                return int(r.get("amount", 1))
    return None


@dataclass
class ResourceSelectorConfig:
    """Classification of a task's resources for the UI resource selector."""
    selectable: list[dict]        # [{id, name}] — resources the user can choose from
    frozen: list[dict]            # [{id, name}] — shared resources (displayed but not pickable)
    frozen_pool_size: int | None  # current pool size when all resources are shared


def resource_selector_config(prosimos_json: dict, task_id: str) -> ResourceSelectorConfig:
    """Classify task resources into selectable vs. shared-frozen.

    Returns a config the UI can render directly; no domain decisions need to
    live in app.py.
    """
    resources = task_resources(prosimos_json, task_id)
    if len(resources) <= 1:
        return ResourceSelectorConfig(selectable=resources, frozen=[], frozen_pool_size=None)
    shared = shared_resource_ids(prosimos_json)
    selectable = [r for r in resources if r["id"] not in shared]
    frozen = [r for r in resources if r["id"] in shared]
    frozen_pool_size: int | None = None
    if not selectable:
        frozen_pool_size = resource_pool_size(prosimos_json, resources[0]["id"])
    return ResourceSelectorConfig(selectable=selectable, frozen=frozen, frozen_pool_size=frozen_pool_size)


def task_mean_duration_s(prosimos_json: dict, task_id: str) -> float | None:
    """Return the average mean duration (over resources) for a task, or None."""
    for entry in prosimos_json.get(KEY_TASK_RESOURCE_DISTRIBUTION, []):
        if entry.get("task_id") != task_id:
            continue
        means = []
        for r in entry.get("resources", []):
            dn = r.get("distribution_name", "")
            params = [p["value"] for p in r.get("distribution_params", [])]
            if dn == "uniform" and len(params) == 2:
                means.append((params[0] + params[1]) / 2)
            elif dn in ("fix", "fixed") and len(params) == 1:
                means.append(params[0])
            elif dn in ("expon", "exponential") and len(params) >= 1:
                means.append(params[0])
            elif dn in ("norm", "normal") and len(params) >= 1:
                means.append(params[0])
        if means:
            return sum(means) / len(means)
    return None
