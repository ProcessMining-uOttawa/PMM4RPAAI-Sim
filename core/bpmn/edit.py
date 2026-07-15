"""Low-level BPMN XML editing primitives (xml.etree.ElementTree).

Covers two concerns:
- DI (Diagram Interchange): reading/writing BPMNShape and BPMNEdge elements.
- Process operations: adding tasks, gateways, and sequence flows to the
  <bpmn:process> element, and rewiring existing flows.

Every flow added or rewired here also keeps its endpoints' redundant
<incoming>/<outgoing> child lists true to the edge, so a model stays internally
consistent after an edit rather than drifting — see _insert_flow_ref for the
child ordering BPMN imposes.

Callers are responsible for deciding where elements are placed; coordinates
are passed explicitly via ShapeSpec rather than computed here.

The adders take an already-resolved `plane`: whether the model carries a
diagram at all is settled once by the caller at its trust boundary (see
XORSplitAutomation.apply_pattern), so nothing here re-checks it. Skipping the
process work on a DI-less model — the shape these once had — silently emitted a
broken model rather than no model, since rewiring runs regardless.
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
from .query import get_plane, get_shape_bounds

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


def _waypoints_between(
    root: ET.Element, src_id: str, tgt_id: str
) -> list[tuple[float, float]]:
    src_bounds = get_shape_bounds(root, src_id)
    tgt_bounds = get_shape_bounds(root, tgt_id)
    if src_bounds and tgt_bounds:
        return [
            (
                src_bounds["x"] + src_bounds["width"],
                src_bounds["y"] + src_bounds["height"] / 2,
            ),
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


def _set_waypoints(edge: ET.Element, pts: list[tuple[float, float]]) -> None:
    """Replace an edge's waypoints with pts (the clear is a no-op on a new edge)."""
    waypoint_tag = f"{{{_DI}}}waypoint"
    for waypoint in edge.findall(waypoint_tag):
        edge.remove(waypoint)
    for pt_x, pt_y in pts:
        waypoint = ET.SubElement(edge, waypoint_tag)
        waypoint.set("x", str(int(pt_x)))
        waypoint.set("y", str(int(pt_y)))


def _add_edge(plane: ET.Element, flow_id: str, pts: list[tuple[float, float]]) -> None:
    edge = ET.SubElement(plane, f"{{{_BPMNDI}}}BPMNEdge")
    edge.set("id", f"{flow_id}_di")
    edge.set("bpmnElement", flow_id)
    _set_waypoints(edge, pts)


def _redraw_edge(root: ET.Element, flow_id: str, src: str, tgt: str) -> None:
    """Re-lay a flow's DI edge between its (possibly moved) endpoints.

    A no-op when the model carries no diagram, or no edge for this flow.
    """
    plane = get_plane(root)
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
    _set_waypoints(edge, _waypoints_between(root, src, tgt))


# ── Process lookups ───────────────────────────────────────────────────────────
# The read half of the mutations below — locating the element about to change,
# not a general query surface. Reads meant for callers live in query.py.


def _find_node_by_id(process: ET.Element, node_id: str) -> ET.Element | None:
    return next((el for el in process if el.get("id") == node_id), None)


def _find_flow(process: ET.Element, flow_id: str) -> ET.Element | None:
    tag = f"{{{_BPMN}}}sequenceFlow"
    return next(
        (el for el in process if el.tag == tag and el.get("id") == flow_id), None
    )


# ── <incoming>/<outgoing> maintenance ─────────────────────────────────────────
# BPMN nodes carry redundant <incoming>/<outgoing> child lists alongside each
# sequenceFlow's sourceRef/targetRef. Prosimos routes off the refs and ignores
# the lists, but a spec-strict external engine or editor may trust them — so
# every edit here keeps them true to the edges instead of letting them drift.

_INCOMING = f"{{{_BPMN}}}incoming"
_OUTGOING = f"{{{_BPMN}}}outgoing"

# tFlowNode orders its children: inherited header elements, then every
# <incoming>, then every <outgoing>, then subtype content (a task's
# ioSpecification, say). A bare append would land an <incoming> after an existing
# <outgoing> and make the model schema-invalid — the very strictness this
# maintenance exists to serve — so inserts are positioned, never appended.
_HEADER_TAGS = frozenset(
    f"{{{_BPMN}}}{tag}"
    for tag in (
        "documentation",
        "extensionElements",
        "auditing",
        "monitoring",
        "categoryValueRef",
    )
)


def _flow_refs(node: ET.Element, tag: str) -> list[ET.Element]:
    return [child for child in node if child.tag == tag]


def _insert_flow_ref(node: ET.Element, tag: str, flow_id: str) -> None:
    """Add an <incoming>/<outgoing> ref for flow_id, keeping BPMN's child order.

    Idempotent: a flow already listed is left alone, so re-linking an unchanged
    endpoint never duplicates it.
    """
    if any(ref.text == flow_id for ref in _flow_refs(node, tag)):
        return
    # Insert after the last child that must precede this tag; anything the
    # subtype adds after <outgoing> therefore stays behind the new ref.
    precede = _HEADER_TAGS | {tag}
    if tag == _OUTGOING:
        precede = precede | {_INCOMING}
    index = 0
    for position, child in enumerate(node):
        if child.tag in precede:
            index = position + 1
    ref = ET.Element(tag)
    ref.text = flow_id
    node.insert(index, ref)


def _link_flow_refs(process: ET.Element, flow_id: str, src: str, tgt: str) -> None:
    """Record flow_id on both endpoints: <outgoing> on src, <incoming> on tgt."""
    src_el = _find_node_by_id(process, src)
    if src_el is not None:
        _insert_flow_ref(src_el, _OUTGOING, flow_id)
    tgt_el = _find_node_by_id(process, tgt)
    if tgt_el is not None:
        _insert_flow_ref(tgt_el, _INCOMING, flow_id)


def _unlink_incoming(process: ET.Element, flow_id: str, node_id: str) -> None:
    """Drop a stale <incoming> ref from a node the flow no longer targets."""
    node = _find_node_by_id(process, node_id)
    if node is None:
        return
    for ref in _flow_refs(node, _INCOMING):
        if ref.text == flow_id:
            node.remove(ref)


# ── Process helpers ────────────────────────────────────────────────────────────


def add_task_el(process: ET.Element, plane: ET.Element, spec: ShapeSpec) -> None:
    el = ET.SubElement(process, f"{{{_BPMN}}}task")
    el.set("id", spec.element_id)
    el.set("name", spec.name)
    add_shape(plane, spec)


def add_xor_el(process: ET.Element, plane: ET.Element, spec: ShapeSpec) -> None:
    el = ET.SubElement(process, f"{{{_BPMN}}}exclusiveGateway")
    el.set("id", spec.element_id)
    if spec.name:
        el.set("name", spec.name)
    add_shape(plane, spec, is_marker_visible=True)


def add_flow_el(
    root: ET.Element, process: ET.Element, plane: ET.Element, spec: FlowSpec
) -> None:
    """Add a sequenceFlow between two existing nodes, with refs and a DI edge.

    Both endpoints must already be in the process: a flow referencing a node
    that isn't there is a dangling ref — the corruption class this module
    exists to avoid — so it is a caller bug, asserted rather than tolerated.
    """
    assert _find_node_by_id(process, spec.src) is not None, (
        f"flow {spec.element_id!r}: source {spec.src!r} not in process"
    )
    assert _find_node_by_id(process, spec.tgt) is not None, (
        f"flow {spec.element_id!r}: target {spec.tgt!r} not in process"
    )
    flow = ET.SubElement(process, f"{{{_BPMN}}}sequenceFlow")
    flow.set("id", spec.element_id)
    flow.set("sourceRef", spec.src)
    flow.set("targetRef", spec.tgt)
    if spec.name:
        flow.set("name", spec.name)
    _link_flow_refs(process, spec.element_id, spec.src, spec.tgt)
    _add_edge(plane, spec.element_id, _waypoints_between(root, spec.src, spec.tgt))


def update_flow_target(
    root: ET.Element, process: ET.Element, flow_id: str, new_target: str
) -> None:
    """Retarget a flow: rewire the ref, fix both endpoints' lists, redraw the edge."""
    flow = _find_flow(process, flow_id)
    if flow is None:
        raise ValueError(f"sequenceFlow '{flow_id}' not found")
    src = flow.get("sourceRef", "")
    old_target = flow.get("targetRef", "")
    flow.set("targetRef", new_target)
    # The old target no longer receives this flow; the new one does. The source
    # is unchanged, but _link_flow_refs also backfills its <outgoing> when the
    # model never listed it — leaving a node half-listed is its own kind of lie.
    _unlink_incoming(process, flow_id, old_target)
    _link_flow_refs(process, flow_id, src, new_target)
    _redraw_edge(root, flow_id, src, new_target)
