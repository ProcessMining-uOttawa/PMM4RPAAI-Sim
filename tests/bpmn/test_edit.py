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

# Same process structure, but no BPMNDiagram — used to test early-return behaviour.
_BPMN_XML_NO_DI = f"""\
<?xml version="1.0"?>
<bpmn:definitions xmlns:bpmn="{_BPMN_NS}">
  <bpmn:process id="proc_1">
    <bpmn:task id="src_task" name="Source"/>
    <bpmn:task id="tgt_task" name="Target"/>
    <bpmn:sequenceFlow id="flow_1" sourceRef="src_task" targetRef="tgt_task"/>
  </bpmn:process>
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


def _parse(xml: str = _BPMN_XML):
    """Return a fresh (root, process, plane) tuple for each test."""
    root = ET.fromstring(xml)
    process = root.find(f".//{{{_BPMN_NS}}}process")
    plane = root.find(f".//{{{_BPMNDI_NS}}}BPMNPlane")
    assert process is not None
    return root, process, plane


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
        root, process, _ = _parse()
        add_task_el(
            root, process, ShapeSpec("t_new", "New Task", 200, 200, TASK_W, TASK_H)
        )
        el = process.find(f"{{{_BPMN_NS}}}task[@id='t_new']")
        assert el is not None
        assert el.get("name") == "New Task"

    def test_adds_shape_to_plane(self):
        root, process, plane = _parse()
        add_task_el(
            root, process, ShapeSpec("t_new", "New Task", 200, 200, TASK_W, TASK_H)
        )
        assert (
            plane.find(f"{{{_BPMNDI_NS}}}BPMNShape[@bpmnElement='t_new']") is not None
        )

    def test_shape_uses_spec_dimensions(self):
        root, process, plane = _parse()
        add_task_el(
            root, process, ShapeSpec("t_new", "New Task", 50, 75, TASK_W, TASK_H)
        )
        bounds = plane.find(
            f"{{{_BPMNDI_NS}}}BPMNShape[@bpmnElement='t_new']/{{{_DC_NS}}}Bounds"
        )
        assert bounds.get("x") == "50"
        assert bounds.get("y") == "75"
        assert bounds.get("width") == str(TASK_W)
        assert bounds.get("height") == str(TASK_H)

    def test_no_op_when_no_plane(self):
        root, process, _ = _parse(_BPMN_XML_NO_DI)
        children_before = list(process)
        add_task_el(
            root, process, ShapeSpec("t_new", "New Task", 200, 200, TASK_W, TASK_H)
        )
        assert list(process) == children_before


# ── add_xor_el ────────────────────────────────────────────────────────────────


class TestAddXorEl:
    def test_adds_exclusive_gateway_element(self):
        root, process, _ = _parse()
        add_xor_el(root, process, ShapeSpec("gw_1", "Decision", 200, 200, GW_W, GW_H))
        el = process.find(f"{{{_BPMN_NS}}}exclusiveGateway[@id='gw_1']")
        assert el is not None
        assert el.get("name") == "Decision"

    def test_empty_name_is_not_set(self):
        root, process, _ = _parse()
        add_xor_el(root, process, ShapeSpec("gw_1", "", 200, 200, GW_W, GW_H))
        el = process.find(f"{{{_BPMN_NS}}}exclusiveGateway[@id='gw_1']")
        assert el.get("name") is None

    def test_shape_has_marker_visible(self):
        root, process, plane = _parse()
        add_xor_el(root, process, ShapeSpec("gw_1", "Decision", 200, 200, GW_W, GW_H))
        shape = plane.find(f"{{{_BPMNDI_NS}}}BPMNShape[@bpmnElement='gw_1']")
        assert shape is not None
        assert shape.get("isMarkerVisible") == "true"

    def test_shape_uses_spec_dimensions(self):
        root, process, plane = _parse()
        add_xor_el(root, process, ShapeSpec("gw_1", "X", 100, 150, GW_W, GW_H))
        bounds = plane.find(
            f"{{{_BPMNDI_NS}}}BPMNShape[@bpmnElement='gw_1']/{{{_DC_NS}}}Bounds"
        )
        assert bounds.get("width") == str(GW_W)
        assert bounds.get("height") == str(GW_H)

    def test_no_op_when_no_plane(self):
        root, process, _ = _parse(_BPMN_XML_NO_DI)
        children_before = list(process)
        add_xor_el(root, process, ShapeSpec("gw_1", "X", 200, 200, GW_W, GW_H))
        assert list(process) == children_before


# ── add_flow_el ───────────────────────────────────────────────────────────────


class TestAddFlowEl:
    def test_adds_sequence_flow_element(self):
        root, process, _ = _parse()
        add_flow_el(root, process, FlowSpec("f_new", "src_task", "tgt_task"))
        flow = process.find(f"{{{_BPMN_NS}}}sequenceFlow[@id='f_new']")
        assert flow is not None
        assert flow.get("sourceRef") == "src_task"
        assert flow.get("targetRef") == "tgt_task"

    def test_name_attribute_set_when_provided(self):
        root, process, _ = _parse()
        add_flow_el(root, process, FlowSpec("f_new", "src_task", "tgt_task", "My Flow"))
        flow = process.find(f"{{{_BPMN_NS}}}sequenceFlow[@id='f_new']")
        assert flow.get("name") == "My Flow"

    def test_name_attribute_absent_when_empty(self):
        root, process, _ = _parse()
        add_flow_el(root, process, FlowSpec("f_new", "src_task", "tgt_task"))
        flow = process.find(f"{{{_BPMN_NS}}}sequenceFlow[@id='f_new']")
        assert flow.get("name") is None

    def test_adds_edge_to_plane(self):
        root, process, plane = _parse()
        add_flow_el(root, process, FlowSpec("f_new", "src_task", "tgt_task"))
        edge = plane.find(f"{{{_BPMNDI_NS}}}BPMNEdge[@bpmnElement='f_new']")
        assert edge is not None
        assert edge.get("id") == "f_new_di"

    def test_edge_waypoints_computed_from_shapes(self):
        # src: x=100, y=100, w=100, h=80 → right_x=200, mid_y=140
        # tgt: x=300, y=100, w=100, h=80 → left_x=300, mid_y=140
        root, process, plane = _parse()
        add_flow_el(root, process, FlowSpec("f_new", "src_task", "tgt_task"))
        waypoints = plane.find(
            f"{{{_BPMNDI_NS}}}BPMNEdge[@bpmnElement='f_new']"
        ).findall(f"{{{_DI_NS}}}waypoint")
        assert len(waypoints) == 2
        assert waypoints[0].get("x") == "200" and waypoints[0].get("y") == "140"
        assert waypoints[1].get("x") == "300" and waypoints[1].get("y") == "140"

    def test_edge_waypoints_fall_back_when_shapes_missing(self):
        root, process, plane = _parse()
        add_flow_el(root, process, FlowSpec("f_new", "unknown_a", "unknown_b"))
        waypoints = plane.find(
            f"{{{_BPMNDI_NS}}}BPMNEdge[@bpmnElement='f_new']"
        ).findall(f"{{{_DI_NS}}}waypoint")
        assert waypoints[0].get("x") == "300" and waypoints[0].get("y") == "120"
        assert waypoints[1].get("x") == "400" and waypoints[1].get("y") == "120"

    def test_no_op_when_no_plane(self):
        root, process, _ = _parse(_BPMN_XML_NO_DI)
        children_before = list(process)
        add_flow_el(root, process, FlowSpec("f_new", "src_task", "tgt_task"))
        assert list(process) == children_before


# ── update_flow_target ────────────────────────────────────────────────────────


class TestUpdateFlowTarget:
    def test_updates_target_ref_on_flow(self):
        root, process, _ = _parse()
        update_flow_target(root, process, "flow_1", "new_tgt")
        flow = process.find(f"{{{_BPMN_NS}}}sequenceFlow[@id='flow_1']")
        assert flow.get("targetRef") == "new_tgt"

    def test_source_ref_is_unchanged(self):
        root, process, _ = _parse()
        update_flow_target(root, process, "flow_1", "new_tgt")
        flow = process.find(f"{{{_BPMN_NS}}}sequenceFlow[@id='flow_1']")
        assert flow.get("sourceRef") == "src_task"

    def test_edge_waypoints_are_replaced(self):
        # After rewiring to a target with no DI shape, waypoints fall back.
        root, process, plane = _parse()
        update_flow_target(root, process, "flow_1", "new_tgt")
        waypoints = plane.find(
            f"{{{_BPMNDI_NS}}}BPMNEdge[@bpmnElement='flow_1']"
        ).findall(f"{{{_DI_NS}}}waypoint")
        assert len(waypoints) == 2
        assert waypoints[0].get("x") == "300" and waypoints[0].get("y") == "120"
        assert waypoints[1].get("x") == "400" and waypoints[1].get("y") == "120"

    def test_target_updated_when_no_plane(self):
        # First early return (`if plane is None`): targetRef is set *before* the
        # plane lookup, so the flow is still rewired even with no DI diagram.
        root, process, plane = _parse(_BPMN_XML_NO_DI)
        assert plane is None
        update_flow_target(root, process, "flow_1", "new_tgt")
        flow = process.find(f"{{{_BPMN_NS}}}sequenceFlow[@id='flow_1']")
        assert flow.get("targetRef") == "new_tgt"

    def test_waypoints_recomputed_for_target_with_shape(self):
        # Second early return NOT taken (edge present) + waypoints recomputed
        # from real shapes: rewire onto new_task (x=500, y=200, h=80) →
        # src right-edge (200,140) → new target left-edge (500,240). The existing
        # test covers the no-shape fallback; this covers the has-shape branch.
        root, process, plane = _parse(_BPMN_XML_THREE)
        update_flow_target(root, process, "flow_1", "new_task")
        waypoints = plane.find(
            f"{{{_BPMNDI_NS}}}BPMNEdge[@bpmnElement='flow_1']"
        ).findall(f"{{{_DI_NS}}}waypoint")
        assert len(waypoints) == 2
        assert waypoints[0].get("x") == "200" and waypoints[0].get("y") == "140"
        assert waypoints[1].get("x") == "500" and waypoints[1].get("y") == "240"

    def test_raises_for_missing_flow(self):
        root, process, _ = _parse()
        with pytest.raises(ValueError, match="nonexistent"):
            update_flow_target(root, process, "nonexistent", "tgt_task")
