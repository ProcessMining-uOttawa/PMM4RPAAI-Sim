"""Read-only helpers for BPMN files."""

from __future__ import annotations
import xml.etree.ElementTree as ET

from . import (
    BPMN_NS as _BPMN,
    BPMNDI_NS as _BPMNDI,
    DC_NS as _DC,
    BPMN_TASK_TAGS,
)

_TASK_TAG_SET = frozenset(f"{{{_BPMN}}}{t}" for t in BPMN_TASK_TAGS)


def find_process(root: ET.Element) -> ET.Element | None:
    return root.find(f".//{{{_BPMN}}}process")


def find_task_in_process(process: ET.Element, name: str) -> ET.Element | None:
    """Search direct children of process for a task element with the given name."""
    for child in process:
        if child.tag in _TASK_TAG_SET and child.get("name") == name:
            return child
    return None


def find_task_by_name(tree: ET.ElementTree, name: str) -> ET.Element | None:
    process = find_process(tree.getroot())
    return find_task_in_process(process, name) if process is not None else None


def list_activities(bpmn_path) -> list[str]:
    """Pull task names out of a BPMN file without loading pm4py."""
    tree = ET.parse(str(bpmn_path))
    names = []
    for tag in BPMN_TASK_TAGS:
        for el in tree.findall(f".//{{{_BPMN}}}{tag}"):
            name = el.get("name")
            if name:
                names.append(name)
    seen, out = set(), []
    for name in names:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def get_plane(root: ET.Element) -> ET.Element | None:
    return root.find(f".//{{{_BPMNDI}}}BPMNPlane")


def diagram_extents(root: ET.Element) -> tuple[float, float, float, float]:
    """Return (x_min, y_min, x_max, y_max) over all shapes in the BPMNPlane."""
    plane = get_plane(root)
    x_lefts, y_tops, x_rights, y_bottoms = [], [], [], []
    if plane is not None:
        for shape in plane.findall(f"{{{_BPMNDI}}}BPMNShape"):
            bounds = shape.find(f"{{{_DC}}}Bounds")
            if bounds is None:
                continue
            x = float(bounds.get("x", 0))
            y = float(bounds.get("y", 0))
            width = float(bounds.get("width", 0))
            height = float(bounds.get("height", 0))
            x_lefts.append(x)
            y_tops.append(y)
            x_rights.append(x + width)
            y_bottoms.append(y + height)
    if not x_lefts:
        return 0.0, 0.0, 400.0, 200.0
    return min(x_lefts), min(y_tops), max(x_rights), max(y_bottoms)


def flows_targeting(process: ET.Element, target_id: str) -> list[ET.Element]:
    tag = f"{{{_BPMN}}}sequenceFlow"
    return [el for el in process if el.tag == tag and el.get("targetRef") == target_id]


def flows_from(process: ET.Element, source_id: str) -> list[ET.Element]:
    tag = f"{{{_BPMN}}}sequenceFlow"
    return [el for el in process if el.tag == tag and el.get("sourceRef") == source_id]
