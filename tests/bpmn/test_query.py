"""Tests for core/bpmn/query.py — no external tools required."""

from __future__ import annotations
import xml.etree.ElementTree as ET

import pytest

from core.bpmn.query import (
    diagram_extents,
    find_process,
    find_task_by_name,
    find_task_in_process,
    flows_from,
    flows_targeting,
    get_plane,
    list_activities,
)

_BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
_BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
_DC_NS = "http://www.omg.org/spec/DD/20100524/DC"

# Minimal BPMN with no DI — used for the task/activity tests.
_BPMN_XML = f"""\
<?xml version="1.0"?>
<bpmn:definitions xmlns:bpmn="{_BPMN_NS}">
  <bpmn:process>
    <bpmn:task     id="task_1" name="My Task"/>
    <bpmn:userTask id="task_2" name="User Task"/>
  </bpmn:process>
</bpmn:definitions>
"""

# BPMN with a process, two tasks, a flow between them, and DI shapes.
_BPMN_DI_XML = f"""\
<?xml version="1.0"?>
<bpmn:definitions
    xmlns:bpmn="{_BPMN_NS}"
    xmlns:bpmndi="{_BPMNDI_NS}"
    xmlns:dc="{_DC_NS}">
  <bpmn:process id="proc_1">
    <bpmn:task     id="task_a" name="Task A"/>
    <bpmn:userTask id="task_b" name="Task B"/>
    <bpmn:sequenceFlow id="flow_1" name="Flow One" sourceRef="task_a" targetRef="task_b"/>
  </bpmn:process>
  <bpmndi:BPMNDiagram>
    <bpmndi:BPMNPlane bpmnElement="proc_1">
      <bpmndi:BPMNShape bpmnElement="task_a">
        <dc:Bounds x="100" y="80" width="100" height="80"/>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape bpmnElement="task_b">
        <dc:Bounds x="300" y="80" width="100" height="80"/>
      </bpmndi:BPMNShape>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""


# ── find_task_by_name ─────────────────────────────────────────────────────────


class TestFindTaskByName:
    @pytest.fixture
    def tree(self):
        return ET.ElementTree(ET.fromstring(_BPMN_XML))

    def test_finds_plain_task(self, tree):
        el = find_task_by_name(tree, "My Task")
        assert el is not None and el.get("id") == "task_1"

    def test_finds_user_task(self, tree):
        el = find_task_by_name(tree, "User Task")
        assert el is not None and el.get("id") == "task_2"

    def test_returns_none_when_not_found(self, tree):
        assert find_task_by_name(tree, "Nonexistent") is None

    def test_returns_none_when_no_process(self):
        xml = f'<bpmn:definitions xmlns:bpmn="{_BPMN_NS}"/>'
        tree = ET.ElementTree(ET.fromstring(xml))
        assert find_task_by_name(tree, "Any") is None


# ── list_activities ───────────────────────────────────────────────────────────


class TestListActivities:
    def _write_bpmn(self, tmp_path, names: list[str]):
        bpmn = f"""\
<?xml version="1.0"?>
<bpmn:definitions xmlns:bpmn="{_BPMN_NS}">
  <bpmn:process>
    {"".join(f'<bpmn:task id="t{i}" name="{n}"/>' for i, n in enumerate(names))}
  </bpmn:process>
</bpmn:definitions>"""
        path = tmp_path / "model.bpmn"
        path.write_text(bpmn)
        return path

    def test_returns_task_names(self, tmp_path):
        path = self._write_bpmn(tmp_path, ["Fix Bug", "Review"])
        assert list_activities(path) == ["Fix Bug", "Review"]

    def test_task_names_ordered(self, tmp_path):
        path = self._write_bpmn(tmp_path, ["Fix Bug", "Review"])
        assert list_activities(path) != ["Review", "Fix Bug"]

    def test_deduplicates_names(self, tmp_path):
        path = self._write_bpmn(tmp_path, ["Fix Bug", "Fix Bug"])
        assert list_activities(path) == ["Fix Bug"]

    def test_excludes_nameless_tasks(self, tmp_path):
        bpmn = f"""\
<?xml version="1.0"?>
<bpmn:definitions xmlns:bpmn="{_BPMN_NS}">
  <bpmn:process>
    <bpmn:task id="t0"/>
    <bpmn:task id="t1" name="Real Task"/>
  </bpmn:process>
</bpmn:definitions>"""
        path = tmp_path / "model.bpmn"
        path.write_text(bpmn)
        assert list_activities(path) == ["Real Task"]

    def test_empty_process_returns_empty_list(self, tmp_path):
        path = self._write_bpmn(tmp_path, [])
        assert list_activities(path) == []


# ── get_plane ─────────────────────────────────────────────────────────────────


class TestGetPlane:
    def test_finds_plane_when_present(self):
        root = ET.fromstring(_BPMN_DI_XML)
        plane = get_plane(root)
        assert plane is not None
        assert plane.get("bpmnElement") == "proc_1"

    def test_returns_none_when_no_diagram(self):
        root = ET.fromstring(_BPMN_XML)
        assert get_plane(root) is None


# ── diagram_extents ───────────────────────────────────────────────────────────


class TestDiagramExtents:
    def test_returns_bounding_box_of_all_shapes(self):
        # task_a: x=100, y=80, w=100, h=80 → right=200, bottom=160
        # task_b: x=300, y=80, w=100, h=80 → right=400, bottom=160
        root = ET.fromstring(_BPMN_DI_XML)
        assert diagram_extents(root) == (100.0, 80.0, 400.0, 160.0)

    def test_returns_defaults_when_no_shapes(self):
        xml = f"""\
<?xml version="1.0"?>
<bpmn:definitions xmlns:bpmn="{_BPMN_NS}" xmlns:bpmndi="{_BPMNDI_NS}">
  <bpmndi:BPMNDiagram>
    <bpmndi:BPMNPlane/>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>"""
        root = ET.fromstring(xml)
        assert diagram_extents(root) == (0.0, 0.0, 400.0, 200.0)

    def test_returns_defaults_when_no_plane(self):
        root = ET.fromstring(_BPMN_XML)
        assert diagram_extents(root) == (0.0, 0.0, 400.0, 200.0)


# ── find_process ──────────────────────────────────────────────────────────────


class TestFindProcess:
    def test_finds_process_element(self):
        root = ET.fromstring(_BPMN_DI_XML)
        process = find_process(root)
        assert process is not None
        assert process.get("id") == "proc_1"

    def test_returns_none_when_no_process(self):
        xml = f'<bpmn:definitions xmlns:bpmn="{_BPMN_NS}"/>'
        root = ET.fromstring(xml)
        assert find_process(root) is None


# ── find_task_in_process ──────────────────────────────────────────────────────


class TestFindTaskInProcess:
    @pytest.fixture
    def process(self):
        return find_process(ET.fromstring(_BPMN_DI_XML))

    def test_finds_plain_task_by_name(self, process):
        el = find_task_in_process(process, "Task A")
        assert el is not None and el.get("id") == "task_a"

    def test_finds_user_task_by_name(self, process):
        el = find_task_in_process(process, "Task B")
        assert el is not None and el.get("id") == "task_b"

    def test_returns_none_for_missing_name(self, process):
        assert find_task_in_process(process, "Nonexistent") is None

    def test_does_not_match_sequence_flows(self, process):
        # The sequenceFlow has name="Flow One"; querying by that name must still
        # miss, since only the tag whitelist (child.tag in _TASK_TAG_SET) — not a
        # name mismatch — can produce None here. This discriminates: dropping the
        # whitelist would match the same-named non-task flow and return it.
        assert find_task_in_process(process, "Flow One") is None


# ── flows_targeting ───────────────────────────────────────────────────────────


class TestFlowsTargeting:
    @pytest.fixture
    def process(self):
        return find_process(ET.fromstring(_BPMN_DI_XML))

    def test_returns_incoming_flows(self, process):
        flows = flows_targeting(process, "task_b")
        assert len(flows) == 1
        assert flows[0].get("id") == "flow_1"

    def test_returns_empty_when_no_incoming_flows(self, process):
        assert flows_targeting(process, "task_a") == []

    def test_returns_empty_for_unknown_target(self, process):
        assert flows_targeting(process, "nonexistent") == []


# ── flows_from ────────────────────────────────────────────────────────────────


class TestFlowsFrom:
    @pytest.fixture
    def process(self):
        return find_process(ET.fromstring(_BPMN_DI_XML))

    def test_returns_outgoing_flows(self, process):
        flows = flows_from(process, "task_a")
        assert len(flows) == 1
        assert flows[0].get("id") == "flow_1"

    def test_returns_empty_when_no_outgoing_flows(self, process):
        assert flows_from(process, "task_b") == []

    def test_returns_empty_for_unknown_source(self, process):
        assert flows_from(process, "nonexistent") == []
