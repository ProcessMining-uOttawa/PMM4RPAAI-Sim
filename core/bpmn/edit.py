"""Low-level BPMN XML editing primitives (xml.etree.ElementTree).

Covers two concerns:
- DI (Diagram Interchange): reading/writing BPMNShape and BPMNEdge elements.
- Process operations: adding tasks, gateways, and sequence flows to the
  <bpmn:process> element, and rewiring existing flows.

Callers are responsible for deciding where elements are placed; coordinates
are passed explicitly via ShapeSpec rather than computed here.
"""

from __future__ import annotations
from dataclasses import dataclass
import xml.etree.ElementTree as ET

from . import (
    BPMN_NS as _BPMN,
    BPMNDI_NS as _BPMNDI,
    DC_NS as _DC,
    DI_NS as _DI,
)
from .query import get_plane

ET.register_namespace("bpmn", _BPMN)
ET.register_namespace("bpmndi", _BPMNDI)
ET.register_namespace("dc", _DC)
ET.register_namespace("di", _DI)

# ── Shape dimensions (public — used by layout functions in sibling modules) ────
TASK_W, TASK_H = 100, 80
GW_W, GW_H = 50, 50


# ── Parameter bundles ──────────────────────────────────────────────────────────


@dataclass
class ElementSpec:
    """Base spec for any BPMN element being added to the model."""

    element_id: str


@dataclass
class ShapeSpec(ElementSpec):
    """Spec for a task or gateway: logical identity, label, position, and size."""

    name: str
    x: int
    y: int
    w: int
    h: int


@dataclass
class FlowSpec(ElementSpec):
    """Spec for a sequence flow: identity, endpoints, and optional label."""

    src: str
    tgt: str
    name: str = ""


# ── DI helpers ─────────────────────────────────────────────────────────────────


def _get_shape_bounds(root: ET.Element, element_id: str) -> dict | None:
    plane = get_plane(root)
    if plane is None:
        return None
    for shape in plane.findall(f"{{{_BPMNDI}}}BPMNShape"):
        if shape.get("bpmnElement") == element_id:
            bounds = shape.find(f"{{{_DC}}}Bounds")
            if bounds is not None:
                return {k: float(bounds.get(k, 0)) for k in ("x", "y", "width", "height")}
            return None
    return None


def _waypoints_between(
    root: ET.Element, src_id: str, tgt_id: str
) -> list[tuple[float, float]]:
    src_bounds = _get_shape_bounds(root, src_id)
    tgt_bounds = _get_shape_bounds(root, tgt_id)
    if src_bounds and tgt_bounds:
        return [
            (src_bounds["x"] + src_bounds["width"], src_bounds["y"] + src_bounds["height"] / 2),
            (tgt_bounds["x"], tgt_bounds["y"] + tgt_bounds["height"] / 2),
        ]
    return [(300.0, 120.0), (400.0, 120.0)]


def add_shape(
    plane: ET.Element, spec: ShapeSpec, is_marker_visible: bool = False
) -> None:
    shape = ET.SubElement(plane, f"{{{_BPMNDI}}}BPMNShape")
    shape.set("id", f"{spec.element_id}_di")
    shape.set("bpmnElement", spec.element_id)
    if is_marker_visible:
        shape.set("isMarkerVisible", "true")
    bounds = ET.SubElement(shape, f"{{{_DC}}}Bounds")
    bounds.set("x", str(spec.x))
    bounds.set("y", str(spec.y))
    bounds.set("width", str(spec.w))
    bounds.set("height", str(spec.h))
    ET.SubElement(shape, f"{{{_BPMNDI}}}BPMNLabel")


def _add_edge(plane: ET.Element, flow_id: str, pts: list[tuple[float, float]]) -> None:
    edge = ET.SubElement(plane, f"{{{_BPMNDI}}}BPMNEdge")
    edge.set("id", f"{flow_id}_di")
    edge.set("bpmnElement", flow_id)
    for pt_x, pt_y in pts:
        waypoint = ET.SubElement(edge, f"{{{_DI}}}waypoint")
        waypoint.set("x", str(int(pt_x)))
        waypoint.set("y", str(int(pt_y)))


# ── Process helpers ────────────────────────────────────────────────────────────


def add_task_el(root: ET.Element, process: ET.Element, spec: ShapeSpec) -> None:
    plane = get_plane(root)
    if plane is None:
        return
    el = ET.SubElement(process, f"{{{_BPMN}}}task")
    el.set("id", spec.element_id)
    el.set("name", spec.name)
    add_shape(plane, spec)


def add_xor_el(root: ET.Element, process: ET.Element, spec: ShapeSpec) -> None:
    plane = get_plane(root)
    if plane is None:
        return
    el = ET.SubElement(process, f"{{{_BPMN}}}exclusiveGateway")
    el.set("id", spec.element_id)
    if spec.name:
        el.set("name", spec.name)
    add_shape(plane, spec, is_marker_visible=True)


def add_flow_el(root: ET.Element, process: ET.Element, spec: FlowSpec) -> None:
    plane = get_plane(root)
    if plane is None:
        return
    flow = ET.SubElement(process, f"{{{_BPMN}}}sequenceFlow")
    flow.set("id", spec.element_id)
    flow.set("sourceRef", spec.src)
    flow.set("targetRef", spec.tgt)
    if spec.name:
        flow.set("name", spec.name)
    _add_edge(plane, spec.element_id, _waypoints_between(root, spec.src, spec.tgt))


def update_flow_target(
    root: ET.Element, process: ET.Element, flow_id: str, new_target: str
) -> None:
    plane = get_plane(root)
    tag = f"{{{_BPMN}}}sequenceFlow"
    flow = next(
        (el for el in process if el.tag == tag and el.get("id") == flow_id), None
    )
    if flow is None:
        raise ValueError(f"sequenceFlow '{flow_id}' not found")
    src = flow.get("sourceRef", "")
    flow.set("targetRef", new_target)
    if plane is None:
        return
    edge = next(
        (
            edge
            for edge in plane.findall(f"{{{_BPMNDI}}}BPMNEdge")
            if edge.get("bpmnElement") == flow_id
        ),
        None,
    )
    if edge is None:
        return
    waypoint_tag = f"{{{_DI}}}waypoint"
    for waypoint in edge.findall(waypoint_tag):
        edge.remove(waypoint)
    for pt_x, pt_y in _waypoints_between(root, src, new_target):
        waypoint = ET.SubElement(edge, waypoint_tag)
        waypoint.set("x", str(int(pt_x)))
        waypoint.set("y", str(int(pt_y)))
