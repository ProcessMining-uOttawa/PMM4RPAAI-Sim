"""Low-level BPMN XML editing primitives (xml.etree.ElementTree).

Covers two concerns:
- DI (Diagram Interchange): reading/writing BPMNShape and BPMNEdge elements.
- Process operations: adding tasks, gateways, and sequence flows to the
  <bpmn:process> element, and rewiring existing flows.

Callers are responsible for deciding where elements are placed; coordinates
are passed explicitly to add_task_el and add_xor_el rather than computed here.
"""
from __future__ import annotations
import xml.etree.ElementTree as ET

from .constants import BPMN_NS as _BPMN, BPMNDI_NS as _BPMNDI, DC_NS as _DC, DI_NS as _DI

ET.register_namespace("bpmn",   _BPMN)
ET.register_namespace("bpmndi", _BPMNDI)
ET.register_namespace("dc",     _DC)
ET.register_namespace("di",     _DI)

# ── Shape dimensions (public — used by layout functions in sibling modules) ────
TASK_W, TASK_H = 100, 80
GW_W,   GW_H   = 50,  50

# ── Task element tags ──────────────────────────────────────────────────────────
_TASK_TAGS = frozenset({
    f"{{{_BPMN}}}task",             f"{{{_BPMN}}}userTask",
    f"{{{_BPMN}}}serviceTask",      f"{{{_BPMN}}}manualTask",
    f"{{{_BPMN}}}businessRuleTask", f"{{{_BPMN}}}scriptTask",
    f"{{{_BPMN}}}sendTask",         f"{{{_BPMN}}}receiveTask",
})


# ── DI helpers ─────────────────────────────────────────────────────────────────

def get_plane(root: ET.Element) -> ET.Element | None:
    return root.find(f".//{{{_BPMNDI}}}BPMNPlane")


def get_shape_bounds(root: ET.Element, element_id: str) -> dict | None:
    plane = get_plane(root)
    if plane is None:
        return None
    for shape in plane.findall(f"{{{_BPMNDI}}}BPMNShape"):
        if shape.get("bpmnElement") == element_id:
            b = shape.find(f"{{{_DC}}}Bounds")
            if b is not None:
                return {k: float(b.get(k, 0)) for k in ("x", "y", "width", "height")}
    return None


def diagram_extents(root: ET.Element) -> tuple[float, float, float, float]:
    """Return (x_min, y_min, x_max, y_max) over all shapes in the BPMNPlane."""
    plane = get_plane(root)
    xs, ys, xs2, ys2 = [], [], [], []
    if plane is not None:
        for shape in plane.findall(f"{{{_BPMNDI}}}BPMNShape"):
            b = shape.find(f"{{{_DC}}}Bounds")
            if b is None:
                continue
            x, y = float(b.get("x", 0)), float(b.get("y", 0))
            w, h = float(b.get("width", 0)), float(b.get("height", 0))
            xs.append(x); ys.append(y)
            xs2.append(x + w); ys2.append(y + h)
    if not xs:
        return 0.0, 0.0, 400.0, 200.0
    return min(xs), min(ys), max(xs2), max(ys2)


def waypoints_between(root: ET.Element,
                      src_id: str, tgt_id: str) -> list[tuple[float, float]]:
    s = get_shape_bounds(root, src_id)
    t = get_shape_bounds(root, tgt_id)
    if s and t:
        return [(s["x"] + s["width"], s["y"] + s["height"] / 2),
                (t["x"],              t["y"] + t["height"] / 2)]
    return [(300.0, 120.0), (400.0, 120.0)]


def add_shape(plane: ET.Element, element_id: str,
              x: int, y: int, w: int, h: int, marker: bool = False) -> None:
    shape = ET.SubElement(plane, f"{{{_BPMNDI}}}BPMNShape")
    shape.set("id", f"{element_id}_di")
    shape.set("bpmnElement", element_id)
    if marker:
        shape.set("isMarkerVisible", "true")
    b = ET.SubElement(shape, f"{{{_DC}}}Bounds")
    b.set("x", str(x)); b.set("y", str(y))
    b.set("width", str(w)); b.set("height", str(h))
    ET.SubElement(shape, f"{{{_BPMNDI}}}BPMNLabel")


def add_edge(plane: ET.Element,
             flow_id: str, pts: list[tuple[float, float]]) -> None:
    edge = ET.SubElement(plane, f"{{{_BPMNDI}}}BPMNEdge")
    edge.set("id", f"{flow_id}_di")
    edge.set("bpmnElement", flow_id)
    for wx, wy in pts:
        wp = ET.SubElement(edge, f"{{{_DI}}}waypoint")
        wp.set("x", str(int(wx))); wp.set("y", str(int(wy)))


# ── Process helpers ────────────────────────────────────────────────────────────

def find_process(root: ET.Element) -> ET.Element | None:
    return root.find(f".//{{{_BPMN}}}process")


def find_task_in_process(process: ET.Element, name: str) -> ET.Element | None:
    """Search direct children of process for a task element with the given name."""
    for el in process:
        if el.tag in _TASK_TAGS and el.get("name") == name:
            return el
    return None


def flows_targeting(process: ET.Element, target_id: str) -> list[ET.Element]:
    tag = f"{{{_BPMN}}}sequenceFlow"
    return [el for el in process if el.tag == tag and el.get("targetRef") == target_id]


def flows_from(process: ET.Element, source_id: str) -> list[ET.Element]:
    tag = f"{{{_BPMN}}}sequenceFlow"
    return [el for el in process if el.tag == tag and el.get("sourceRef") == source_id]


def add_task_el(root: ET.Element, process: ET.Element,
                task_id: str, name: str, x: int, y: int) -> None:
    el = ET.SubElement(process, f"{{{_BPMN}}}task")
    el.set("id", task_id); el.set("name", name)
    plane = get_plane(root)
    if plane is not None:
        add_shape(plane, task_id, x, y, TASK_W, TASK_H)


def add_xor_el(root: ET.Element, process: ET.Element,
               gw_id: str, name: str, x: int, y: int) -> None:
    el = ET.SubElement(process, f"{{{_BPMN}}}exclusiveGateway")
    el.set("id", gw_id)
    if name:
        el.set("name", name)
    plane = get_plane(root)
    if plane is not None:
        add_shape(plane, gw_id, x, y, GW_W, GW_H, marker=True)


def add_flow_el(root: ET.Element, process: ET.Element,
                flow_id: str, src: str, tgt: str, name: str = "") -> None:
    flow = ET.SubElement(process, f"{{{_BPMN}}}sequenceFlow")
    flow.set("id", flow_id); flow.set("sourceRef", src); flow.set("targetRef", tgt)
    if name:
        flow.set("name", name)
    plane = get_plane(root)
    if plane is not None:
        add_edge(plane, flow_id, waypoints_between(root, src, tgt))


def update_flow_target(root: ET.Element, process: ET.Element,
                       flow_id: str, new_target: str) -> None:
    tag = f"{{{_BPMN}}}sequenceFlow"
    flow = next((el for el in process if el.tag == tag and el.get("id") == flow_id), None)
    if flow is None:
        raise ValueError(f"sequenceFlow '{flow_id}' not found")
    src = flow.get("sourceRef", "")
    flow.set("targetRef", new_target)
    plane = get_plane(root)
    if plane is not None:
        edge = next((e for e in plane.findall(f"{{{_BPMNDI}}}BPMNEdge")
                     if e.get("bpmnElement") == flow_id), None)
        if edge is not None:
            wp_tag = f"{{{_DI}}}waypoint"
            for wp in edge.findall(wp_tag):
                edge.remove(wp)
            for wx, wy in waypoints_between(root, src, new_target):
                wp = ET.SubElement(edge, wp_tag)
                wp.set("x", str(int(wx))); wp.set("y", str(int(wy)))
