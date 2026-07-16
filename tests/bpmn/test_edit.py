"""Tests for core/bpmn/edit.py — no external tools required."""

from __future__ import annotations
import xml.etree.ElementTree as ET

import pytest

from core.bpmn.edit import (
    GW_H,
    GW_W,
    TASK_H,
    TASK_W,
    FlowSpec,
    ShapeSpec,
    add_flow_el,
    add_shape,
    add_task_el,
    add_xor_el,
    update_flow_target,
)

_BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
_BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
_DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
_DI_NS = "http://www.omg.org/spec/DD/20100524/DI"

# Minimal BPMN with two tasks (with DI shapes) and one flow between them.
# x/y chosen so that waypoints are predictable:
#   src: x=100, y=100, w=100, h=80 → right_x=200, mid_y=140
#   tgt: x=300, y=100, w=100, h=80 → left_x=300, mid_y=140
# new_tgt is a real node the diagram never drew — a legal retarget destination
# (update_flow_target asserts its target is a node) whose missing shape is what
# makes the rewired edge's waypoints fall back.
_BPMN_XML = f"""\
<?xml version="1.0"?>
<bpmn:definitions
    xmlns:bpmn="{_BPMN_NS}"
    xmlns:bpmndi="{_BPMNDI_NS}"
    xmlns:dc="{_DC_NS}"
    xmlns:di="{_DI_NS}">
  <bpmn:process id="proc_1">
    <bpmn:task id="src_task" name="Source"/>
    <bpmn:task id="tgt_task" name="Target"/>
    <bpmn:task id="new_tgt" name="New Target"/>
    <bpmn:sequenceFlow id="flow_1" sourceRef="src_task" targetRef="tgt_task"/>
  </bpmn:process>
  <bpmndi:BPMNDiagram>
    <bpmndi:BPMNPlane bpmnElement="proc_1">
      <bpmndi:BPMNShape id="src_task_di" bpmnElement="src_task">
        <dc:Bounds x="100" y="100" width="100" height="80"/>
        <bpmndi:BPMNLabel/>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="tgt_task_di" bpmnElement="tgt_task">
        <dc:Bounds x="300" y="100" width="100" height="80"/>
        <bpmndi:BPMNLabel/>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="flow_1_di" bpmnElement="flow_1">
        <di:waypoint x="200" y="140"/>
        <di:waypoint x="300" y="140"/>
      </bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""

# Same process structure, but no BPMNDiagram (schema-legal — DI is minOccurs="0").
# The adders cannot see this case: they take a resolved plane, and
# apply_pattern rejects a DI-less model at its boundary. update_flow_target still
# accepts one, since its process work is real and only the redraw needs a diagram.
_BPMN_XML_NO_DI = f"""\
<?xml version="1.0"?>
<bpmn:definitions xmlns:bpmn="{_BPMN_NS}">
  <bpmn:process id="proc_1">
    <bpmn:task id="src_task" name="Source"/>
    <bpmn:task id="tgt_task" name="Target"/>
    <bpmn:task id="new_tgt" name="New Target"/>
    <bpmn:sequenceFlow id="flow_1" sourceRef="src_task" targetRef="tgt_task"/>
  </bpmn:process>
</bpmn:definitions>
"""

# A model with a diagram that omits shapes for its two nodes. The nodes exist in
# the process — so a flow between them is legal and its refs resolve — but there
# is no geometry to route from, which is what makes _waypoints_between fall back.
_BPMN_XML_UNDRAWN_NODES = f"""\
<?xml version="1.0"?>
<bpmn:definitions
    xmlns:bpmn="{_BPMN_NS}"
    xmlns:bpmndi="{_BPMNDI_NS}"
    xmlns:dc="{_DC_NS}"
    xmlns:di="{_DI_NS}">
  <bpmn:process id="proc_1">
    <bpmn:task id="undrawn_a" name="Undrawn A"/>
    <bpmn:task id="undrawn_b" name="Undrawn B"/>
  </bpmn:process>
  <bpmndi:BPMNDiagram>
    <bpmndi:BPMNPlane bpmnElement="proc_1"/>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""

# Adds a third task (new_task) with a DI shape at distinct coordinates, so a
# rewire onto it yields waypoints recomputed from real shapes (not the fallback).
#   new_task: x=500, y=200, w=100, h=80 → left_x=500, mid_y=240
_BPMN_XML_THREE = f"""\
<?xml version="1.0"?>
<bpmn:definitions
    xmlns:bpmn="{_BPMN_NS}"
    xmlns:bpmndi="{_BPMNDI_NS}"
    xmlns:dc="{_DC_NS}"
    xmlns:di="{_DI_NS}">
  <bpmn:process id="proc_1">
    <bpmn:task id="src_task" name="Source"/>
    <bpmn:task id="tgt_task" name="Target"/>
    <bpmn:task id="new_task" name="New"/>
    <bpmn:sequenceFlow id="flow_1" sourceRef="src_task" targetRef="tgt_task"/>
  </bpmn:process>
  <bpmndi:BPMNDiagram>
    <bpmndi:BPMNPlane bpmnElement="proc_1">
      <bpmndi:BPMNShape id="src_task_di" bpmnElement="src_task">
        <dc:Bounds x="100" y="100" width="100" height="80"/>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="tgt_task_di" bpmnElement="tgt_task">
        <dc:Bounds x="300" y="100" width="100" height="80"/>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="new_task_di" bpmnElement="new_task">
        <dc:Bounds x="500" y="200" width="100" height="80"/>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="flow_1_di" bpmnElement="flow_1">
        <di:waypoint x="200" y="140"/>
        <di:waypoint x="300" y="140"/>
      </bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""


# Mirrors a real model (Apromore-style) whose nodes already carry their
# <incoming>/<outgoing> lists — the case where rewiring a flow can strand a stale
# entry on the old target. src_task also has an <outgoing> already, so inserting
# an <incoming> there must land *before* it (BPMN's tFlowNode child order).
_BPMN_XML_WITH_REFS = f"""\
<?xml version="1.0"?>
<bpmn:definitions
    xmlns:bpmn="{_BPMN_NS}"
    xmlns:bpmndi="{_BPMNDI_NS}"
    xmlns:dc="{_DC_NS}"
    xmlns:di="{_DI_NS}">
  <bpmn:process id="proc_1">
    <bpmn:task id="src_task" name="Source">
      <bpmn:outgoing>flow_1</bpmn:outgoing>
    </bpmn:task>
    <bpmn:task id="tgt_task" name="Target">
      <bpmn:incoming>flow_1</bpmn:incoming>
    </bpmn:task>
    <bpmn:task id="new_task" name="New"/>
    <bpmn:sequenceFlow id="flow_1" sourceRef="src_task" targetRef="tgt_task"/>
  </bpmn:process>
  <bpmndi:BPMNDiagram>
    <bpmndi:BPMNPlane bpmnElement="proc_1">
      <bpmndi:BPMNShape id="src_task_di" bpmnElement="src_task">
        <dc:Bounds x="100" y="100" width="100" height="80"/>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="tgt_task_di" bpmnElement="tgt_task">
        <dc:Bounds x="300" y="100" width="100" height="80"/>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="new_task_di" bpmnElement="new_task">
        <dc:Bounds x="500" y="200" width="100" height="80"/>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="flow_1_di" bpmnElement="flow_1">
        <di:waypoint x="200" y="140"/>
        <di:waypoint x="300" y="140"/>
      </bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""


def _parse(xml: str = _BPMN_XML):
    """Return a fresh (root, process, plane) tuple for each test."""
    root = ET.fromstring(xml)
    process = root.find(f".//{{{_BPMN_NS}}}process")
    plane = root.find(f".//{{{_BPMNDI_NS}}}BPMNPlane")
    assert process is not None
    return root, process, plane


def _task(process: ET.Element, task_id: str) -> ET.Element:
    el = process.find(f"{{{_BPMN_NS}}}task[@id='{task_id}']")
    assert el is not None
    return el


def _refs(node: ET.Element, tag: str) -> list[str | None]:
    """Text of a node's <incoming>/<outgoing> children, in document order."""
    return [child.text for child in node if child.tag == f"{{{_BPMN_NS}}}{tag}"]


def _child_tags(node: ET.Element) -> list[str]:
    return [child.tag.rsplit("}", 1)[-1] for child in node]


# ── add_shape ─────────────────────────────────────────────────────────────────


class TestAddShape:
    def test_creates_shape_with_correct_id_and_ref(self):
        _, _, plane = _parse()
        add_shape(plane, ShapeSpec("new_el", "Label", 50, 60, 100, 80))
        shape = plane.find(f"{{{_BPMNDI_NS}}}BPMNShape[@bpmnElement='new_el']")
        assert shape is not None
        assert shape.get("id") == "new_el_di"

    def test_bounds_set_correctly(self):
        _, _, plane = _parse()
        add_shape(plane, ShapeSpec("el", "Label", 10, 20, 30, 40))
        shape = plane.find(f"{{{_BPMNDI_NS}}}BPMNShape[@bpmnElement='el']")
        bounds = shape.find(f"{{{_DC_NS}}}Bounds")
        assert bounds is not None
        assert bounds.get("x") == "10"
        assert bounds.get("y") == "20"
        assert bounds.get("width") == "30"
        assert bounds.get("height") == "40"

    def test_is_marker_visible_not_set_by_default(self):
        _, _, plane = _parse()
        add_shape(plane, ShapeSpec("el", "Label", 0, 0, 50, 50))
        shape = plane.find(f"{{{_BPMNDI_NS}}}BPMNShape[@bpmnElement='el']")
        assert shape.get("isMarkerVisible") is None

    def test_is_marker_visible_set_when_requested(self):
        _, _, plane = _parse()
        add_shape(plane, ShapeSpec("el", "Label", 0, 0, 50, 50), is_marker_visible=True)
        shape = plane.find(f"{{{_BPMNDI_NS}}}BPMNShape[@bpmnElement='el']")
        assert shape.get("isMarkerVisible") == "true"

    def test_adds_bpmn_label_child(self):
        _, _, plane = _parse()
        add_shape(plane, ShapeSpec("el", "Label", 0, 0, 50, 50))
        shape = plane.find(f"{{{_BPMNDI_NS}}}BPMNShape[@bpmnElement='el']")
        assert shape.find(f"{{{_BPMNDI_NS}}}BPMNLabel") is not None


# ── add_task_el ───────────────────────────────────────────────────────────────


class TestAddTaskEl:
    def test_adds_task_element_to_process(self):
        _, process, plane = _parse()
        add_task_el(
            process, plane, ShapeSpec("t_new", "New Task", 200, 200, TASK_W, TASK_H)
        )
        el = process.find(f"{{{_BPMN_NS}}}task[@id='t_new']")
        assert el is not None
        assert el.get("name") == "New Task"

    def test_adds_shape_to_plane(self):
        _, process, plane = _parse()
        add_task_el(
            process, plane, ShapeSpec("t_new", "New Task", 200, 200, TASK_W, TASK_H)
        )
        assert (
            plane.find(f"{{{_BPMNDI_NS}}}BPMNShape[@bpmnElement='t_new']") is not None
        )

    def test_shape_uses_spec_dimensions(self):
        _, process, plane = _parse()
        add_task_el(
            process, plane, ShapeSpec("t_new", "New Task", 50, 75, TASK_W, TASK_H)
        )
        bounds = plane.find(
            f"{{{_BPMNDI_NS}}}BPMNShape[@bpmnElement='t_new']/{{{_DC_NS}}}Bounds"
        )
        assert bounds.get("x") == "50"
        assert bounds.get("y") == "75"
        assert bounds.get("width") == str(TASK_W)
        assert bounds.get("height") == str(TASK_H)


# ── add_xor_el ────────────────────────────────────────────────────────────────


class TestAddXorEl:
    def test_adds_exclusive_gateway_element(self):
        _, process, plane = _parse()
        add_xor_el(process, plane, ShapeSpec("gw_1", "Decision", 200, 200, GW_W, GW_H))
        el = process.find(f"{{{_BPMN_NS}}}exclusiveGateway[@id='gw_1']")
        assert el is not None
        assert el.get("name") == "Decision"

    def test_empty_name_is_not_set(self):
        _, process, plane = _parse()
        add_xor_el(process, plane, ShapeSpec("gw_1", "", 200, 200, GW_W, GW_H))
        el = process.find(f"{{{_BPMN_NS}}}exclusiveGateway[@id='gw_1']")
        assert el.get("name") is None

    def test_shape_has_marker_visible(self):
        _, process, plane = _parse()
        add_xor_el(process, plane, ShapeSpec("gw_1", "Decision", 200, 200, GW_W, GW_H))
        shape = plane.find(f"{{{_BPMNDI_NS}}}BPMNShape[@bpmnElement='gw_1']")
        assert shape is not None
        assert shape.get("isMarkerVisible") == "true"

    def test_shape_uses_spec_dimensions(self):
        _, process, plane = _parse()
        add_xor_el(process, plane, ShapeSpec("gw_1", "X", 100, 150, GW_W, GW_H))
        bounds = plane.find(
            f"{{{_BPMNDI_NS}}}BPMNShape[@bpmnElement='gw_1']/{{{_DC_NS}}}Bounds"
        )
        assert bounds.get("width") == str(GW_W)
        assert bounds.get("height") == str(GW_H)


# ── add_flow_el ───────────────────────────────────────────────────────────────


class TestAddFlowEl:
    def test_adds_sequence_flow_element(self):
        root, process, plane = _parse()
        add_flow_el(process, plane, FlowSpec("f_new", "src_task", "tgt_task"))
        flow = process.find(f"{{{_BPMN_NS}}}sequenceFlow[@id='f_new']")
        assert flow is not None
        assert flow.get("sourceRef") == "src_task"
        assert flow.get("targetRef") == "tgt_task"

    def test_name_attribute_set_when_provided(self):
        root, process, plane = _parse()
        add_flow_el(
            process, plane, FlowSpec("f_new", "src_task", "tgt_task", "My Flow")
        )
        flow = process.find(f"{{{_BPMN_NS}}}sequenceFlow[@id='f_new']")
        assert flow.get("name") == "My Flow"

    def test_name_attribute_absent_when_empty(self):
        root, process, plane = _parse()
        add_flow_el(process, plane, FlowSpec("f_new", "src_task", "tgt_task"))
        flow = process.find(f"{{{_BPMN_NS}}}sequenceFlow[@id='f_new']")
        assert flow.get("name") is None

    def test_adds_edge_to_plane(self):
        root, process, plane = _parse()
        add_flow_el(process, plane, FlowSpec("f_new", "src_task", "tgt_task"))
        edge = plane.find(f"{{{_BPMNDI_NS}}}BPMNEdge[@bpmnElement='f_new']")
        assert edge is not None
        assert edge.get("id") == "f_new_di"

    def test_edge_waypoints_computed_from_shapes(self):
        # src: x=100, y=100, w=100, h=80 → right_x=200, mid_y=140
        # tgt: x=300, y=100, w=100, h=80 → left_x=300, mid_y=140
        root, process, plane = _parse()
        add_flow_el(process, plane, FlowSpec("f_new", "src_task", "tgt_task"))
        waypoints = plane.find(
            f"{{{_BPMNDI_NS}}}BPMNEdge[@bpmnElement='f_new']"
        ).findall(f"{{{_DI_NS}}}waypoint")
        assert len(waypoints) == 2
        assert waypoints[0].get("x") == "200" and waypoints[0].get("y") == "140"
        assert waypoints[1].get("x") == "300" and waypoints[1].get("y") == "140"

    def test_edge_waypoints_fall_back_when_shapes_missing(self):
        # The endpoints are real process nodes the diagram never drew, so the
        # refs resolve but there is no geometry to route between.
        root, process, plane = _parse(_BPMN_XML_UNDRAWN_NODES)
        add_flow_el(process, plane, FlowSpec("f_new", "undrawn_a", "undrawn_b"))
        waypoints = plane.find(
            f"{{{_BPMNDI_NS}}}BPMNEdge[@bpmnElement='f_new']"
        ).findall(f"{{{_DI_NS}}}waypoint")
        assert waypoints[0].get("x") == "300" and waypoints[0].get("y") == "120"
        assert waypoints[1].get("x") == "400" and waypoints[1].get("y") == "120"

    def test_raises_for_missing_source_node(self):
        root, process, plane = _parse()
        with pytest.raises(AssertionError, match="source 'ghost' not in process"):
            add_flow_el(process, plane, FlowSpec("f_new", "ghost", "tgt_task"))

    def test_raises_for_missing_target_node(self):
        root, process, plane = _parse()
        with pytest.raises(AssertionError, match="target 'ghost' not in process"):
            add_flow_el(process, plane, FlowSpec("f_new", "src_task", "ghost"))

    def test_no_flow_added_when_endpoint_missing(self):
        # The assert fires before the sequenceFlow is built, so a rejected call
        # leaves no half-wired element behind.
        root, process, plane = _parse()
        with pytest.raises(AssertionError):
            add_flow_el(process, plane, FlowSpec("f_new", "src_task", "ghost"))
        assert process.find(f"{{{_BPMN_NS}}}sequenceFlow[@id='f_new']") is None

    def test_raises_when_endpoint_is_a_sequence_flow(self):
        # Flows and nodes share one id namespace, and apply_pattern juggles both
        # — so passing a flow id where a node id belongs is the realistic caller
        # slip. Targeting a flow is still a dangling ref, and it would parent an
        # <incoming> on a <sequenceFlow>, which tSequenceFlow does not permit.
        root, process, plane = _parse()
        with pytest.raises(AssertionError, match="target 'flow_1' not in process"):
            add_flow_el(process, plane, FlowSpec("f_new", "src_task", "flow_1"))
        victim = process.find(f"{{{_BPMN_NS}}}sequenceFlow[@id='flow_1']")
        assert _refs(victim, "incoming") == []


# ── update_flow_target ────────────────────────────────────────────────────────


class TestUpdateFlowTarget:
    def test_updates_target_ref_on_flow(self):
        _, process, plane = _parse()
        update_flow_target(process, plane, "flow_1", "new_tgt")
        flow = process.find(f"{{{_BPMN_NS}}}sequenceFlow[@id='flow_1']")
        assert flow.get("targetRef") == "new_tgt"

    def test_source_ref_is_unchanged(self):
        _, process, plane = _parse()
        update_flow_target(process, plane, "flow_1", "new_tgt")
        flow = process.find(f"{{{_BPMN_NS}}}sequenceFlow[@id='flow_1']")
        assert flow.get("sourceRef") == "src_task"

    def test_edge_waypoints_are_replaced(self):
        # After rewiring to a target with no DI shape, waypoints fall back.
        root, process, plane = _parse()
        update_flow_target(process, plane, "flow_1", "new_tgt")
        waypoints = plane.find(
            f"{{{_BPMNDI_NS}}}BPMNEdge[@bpmnElement='flow_1']"
        ).findall(f"{{{_DI_NS}}}waypoint")
        assert len(waypoints) == 2
        assert waypoints[0].get("x") == "300" and waypoints[0].get("y") == "120"
        assert waypoints[1].get("x") == "400" and waypoints[1].get("y") == "120"

    def test_target_updated_when_no_plane(self):
        # update_flow_target's process work runs unconditionally; only the
        # _redraw_edge DI step no-ops on plane=None, so the flow is still
        # rewired even with no DI diagram.
        root, process, plane = _parse(_BPMN_XML_NO_DI)
        assert plane is None
        update_flow_target(process, plane, "flow_1", "new_tgt")
        flow = process.find(f"{{{_BPMN_NS}}}sequenceFlow[@id='flow_1']")
        assert flow.get("targetRef") == "new_tgt"

    def test_waypoints_recomputed_for_target_with_shape(self):
        # _redraw_edge finds the edge (its edge-missing no-op is NOT taken) and
        # recomputes waypoints from real shapes: rewire onto new_task (x=500, y=200, h=80) →
        # src right-edge (200,140) → new target left-edge (500,240). The existing
        # test covers the no-shape fallback; this covers the has-shape branch.
        root, process, plane = _parse(_BPMN_XML_THREE)
        update_flow_target(process, plane, "flow_1", "new_task")
        waypoints = plane.find(
            f"{{{_BPMNDI_NS}}}BPMNEdge[@bpmnElement='flow_1']"
        ).findall(f"{{{_DI_NS}}}waypoint")
        assert len(waypoints) == 2
        assert waypoints[0].get("x") == "200" and waypoints[0].get("y") == "140"
        assert waypoints[1].get("x") == "500" and waypoints[1].get("y") == "240"

    def test_raises_for_missing_flow(self):
        _, process, plane = _parse()
        with pytest.raises(ValueError, match="nonexistent"):
            update_flow_target(process, plane, "nonexistent", "tgt_task")

    def test_raises_for_target_that_is_not_a_node(self):
        # Retargeting onto a non-node is the same dangling ref add_flow_el
        # asserts against, and it lands worse than a no-op: without the guard the
        # old target's <incoming> is dropped and nothing takes its place.
        _, process, plane = _parse()
        with pytest.raises(AssertionError, match="target 'ghost' not in process"):
            update_flow_target(process, plane, "flow_1", "ghost")

    def test_target_ref_untouched_when_target_is_not_a_node(self):
        _, process, plane = _parse()
        with pytest.raises(AssertionError):
            update_flow_target(process, plane, "flow_1", "ghost")
        flow = process.find(f"{{{_BPMN_NS}}}sequenceFlow[@id='flow_1']")
        assert flow.get("targetRef") == "tgt_task"
        assert _refs(_task(process, "tgt_task"), "incoming") == []


# ── <incoming>/<outgoing> maintenance ─────────────────────────────────────────


class TestFlowRefMaintenance:
    """Every flow added or rewired must leave its endpoints' redundant
    <incoming>/<outgoing> lists true to the edge."""

    def test_add_flow_el_lists_flow_on_both_endpoints(self):
        root, process, plane = _parse()
        add_flow_el(process, plane, FlowSpec("f_new", "src_task", "tgt_task"))
        assert _refs(_task(process, "src_task"), "outgoing") == ["f_new"]
        assert _refs(_task(process, "tgt_task"), "incoming") == ["f_new"]

    def test_rewire_drops_stale_incoming_from_old_target(self):
        # A rewired flow must not stay listed on its old target's <incoming>.
        _, process, plane = _parse(_BPMN_XML_WITH_REFS)
        update_flow_target(process, plane, "flow_1", "new_task")
        assert _refs(_task(process, "tgt_task"), "incoming") == []

    def test_rewire_lists_flow_on_new_target(self):
        _, process, plane = _parse(_BPMN_XML_WITH_REFS)
        update_flow_target(process, plane, "flow_1", "new_task")
        assert _refs(_task(process, "new_task"), "incoming") == ["flow_1"]

    def test_rewire_leaves_an_already_listed_source_alone(self):
        _, process, plane = _parse(_BPMN_XML_WITH_REFS)
        update_flow_target(process, plane, "flow_1", "new_task")
        # Source is unchanged by a retarget — listed once, not duplicated.
        assert _refs(_task(process, "src_task"), "outgoing") == ["flow_1"]

    def test_rewire_backfills_source_outgoing_when_absent(self):
        # Simod writes no lists on tasks; the source gains an accurate entry
        # rather than being left half-listed once the target has one.
        _, process, plane = _parse(_BPMN_XML_THREE)
        update_flow_target(process, plane, "flow_1", "new_task")
        assert _refs(_task(process, "src_task"), "outgoing") == ["flow_1"]

    def test_incoming_is_inserted_before_an_existing_outgoing(self):
        # BPMN's tFlowNode orders incoming* before outgoing*; a bare append would
        # invert that and make the model schema-invalid.
        root, process, plane = _parse(_BPMN_XML_WITH_REFS)
        add_flow_el(process, plane, FlowSpec("f_in", "new_task", "src_task"))
        assert _child_tags(_task(process, "src_task")) == ["incoming", "outgoing"]

    def test_relinking_the_same_flow_is_idempotent(self):
        _, process, plane = _parse(_BPMN_XML_WITH_REFS)
        update_flow_target(process, plane, "flow_1", "new_task")
        update_flow_target(process, plane, "flow_1", "new_task")
        assert _refs(_task(process, "new_task"), "incoming") == ["flow_1"]
        assert _refs(_task(process, "src_task"), "outgoing") == ["flow_1"]

    def test_refs_maintained_without_a_diagram(self):
        # The lists are process-level truth, not DI decoration — a model with no
        # BPMNDiagram still gets accurate refs on rewire.
        root, process, plane = _parse(_BPMN_XML_NO_DI)
        assert plane is None
        update_flow_target(process, plane, "flow_1", "src_task")
        assert _refs(_task(process, "tgt_task"), "incoming") == []
        assert _refs(_task(process, "src_task"), "incoming") == ["flow_1"]
