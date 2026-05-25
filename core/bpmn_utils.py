"""Read-only helpers for BPMN files and Prosimos JSON."""
from __future__ import annotations
import uuid
import xml.etree.ElementTree as ET

_BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"

_TASK_TAGS = ("task", "userTask", "serviceTask", "manualTask")


def new_id(prefix: str = "node") -> str:
    return f"{prefix}_{uuid.uuid4()}"


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


def task_mean_duration_s(prosimos_json: dict, task_id: str) -> float | None:
    """Return the average mean duration (over resources) for a task, or None."""
    for entry in prosimos_json.get("task_resource_distribution", []):
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
