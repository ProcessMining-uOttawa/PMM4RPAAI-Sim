"""Read-only helpers for BPMN files and Prosimos JSON."""
from __future__ import annotations
from collections import Counter
import xml.etree.ElementTree as ET

from .constants import BPMN_NS, KEY_TASK_RESOURCE_DISTRIBUTION, KEY_RESOURCE_PROFILES

_BPMN = BPMN_NS

_TASK_TAGS = ("task", "userTask", "serviceTask", "manualTask")


def find_task_by_name(tree: ET.ElementTree, name: str) -> ET.Element | None:
    for tag in _TASK_TAGS:
        for el in tree.findall(f".//{{{_BPMN}}}{tag}"):
            if el.get("name") == name:
                return el
    return None


def find_flows(tree: ET.ElementTree, node_id: str) -> tuple[list, list]:
    """Return (incoming_flows, outgoing_flows) sequenceFlow elements for node_id."""
    incoming, outgoing = [], []
    for fl in tree.findall(f".//{{{_BPMN}}}sequenceFlow"):
        if fl.get("targetRef") == node_id:
            incoming.append(fl)
        if fl.get("sourceRef") == node_id:
            outgoing.append(fl)
    return incoming, outgoing


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


def resource_pool_size(prosimos_json: dict, resource_id: str) -> int:
    """Return the current pool size (amount) for a resource, defaulting to 1."""
    for profile in prosimos_json.get(KEY_RESOURCE_PROFILES, []):
        for r in profile.get("resource_list", []):
            if r.get("id") == resource_id:
                return int(r.get("amount", 1))
    return 1


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
