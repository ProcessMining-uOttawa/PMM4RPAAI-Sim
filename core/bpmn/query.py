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


def find_task_by_name(tree: ET.ElementTree[ET.Element], name: str) -> ET.Element | None:
    # The type narrows the param to a rooted tree (what every caller passes via
    # ET.parse / ET.fromstring), so getroot() is non-None. A tree with no
    # <process> still returns None via the find_process guard below.
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


def _bounds_of(shape: ET.Element) -> dict[str, float] | None:
    """Parse a BPMNShape's DC:Bounds into {x, y, width, height}."""
    bounds = shape.find(f"{{{_DC}}}Bounds")
    if bounds is None:
        return None
    return {key: float(bounds.get(key, 0)) for key in ("x", "y", "width", "height")}


def get_shape_bounds(plane: ET.Element, element_id: str) -> dict[str, float] | None:
    """Return {x, y, width, height} for one element's BPMNShape in this plane.

    None when the shape, or its Bounds, are absent — a node the diagram never
    drew. Takes the plane, not the root: whether the model has a diagram at all
    is its caller's question, settled once at a boundary (see
    XORSplitAutomation.apply_pattern), so this never re-resolves it. Reading DI
    lives here beside diagram_extents; edit.py writes DI but reads it through this.
    """
    for shape in plane.findall(f"{{{_BPMNDI}}}BPMNShape"):
        if shape.get("bpmnElement") == element_id:
            return _bounds_of(shape)
    return None


def diagram_extents(root: ET.Element) -> tuple[float, float, float, float]:
    """Return (x_min, y_min, x_max, y_max) over all shapes in the BPMNPlane."""
    plane = get_plane(root)
    x_lefts, y_tops, x_rights, y_bottoms = [], [], [], []
    if plane is not None:
        for shape in plane.findall(f"{{{_BPMNDI}}}BPMNShape"):
            bounds = _bounds_of(shape)
            if bounds is None:
                continue
            x_lefts.append(bounds["x"])
            y_tops.append(bounds["y"])
            x_rights.append(bounds["x"] + bounds["width"])
            y_bottoms.append(bounds["y"] + bounds["height"])
    if not x_lefts:
        return 0.0, 0.0, 400.0, 200.0
    return min(x_lefts), min(y_tops), max(x_rights), max(y_bottoms)


def flows_targeting(process: ET.Element, target_id: str) -> list[ET.Element]:
    tag = f"{{{_BPMN}}}sequenceFlow"
    return [el for el in process if el.tag == tag and el.get("targetRef") == target_id]


def flows_from(process: ET.Element, source_id: str) -> list[ET.Element]:
    tag = f"{{{_BPMN}}}sequenceFlow"
    return [el for el in process if el.tag == tag and el.get("sourceRef") == source_id]
