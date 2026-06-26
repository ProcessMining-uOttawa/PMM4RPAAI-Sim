"""Read-only helpers for BPMN files."""

from __future__ import annotations
import xml.etree.ElementTree as ET

from . import BPMN_NS as _BPMN, BPMN_TASK_TAGS as _TASK_TAGS


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
