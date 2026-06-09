"""Shared pytest fixtures available to all test modules."""
from __future__ import annotations
import json
import pytest

from core.transformations import XORSplitAutomation
from core.simulation.prosimos_edit import KEY_RESOURCE_CALENDARS, KEY_GATEWAY_BRANCHING_PROBS
from core.constants import KEY_RESOURCE_PROFILES, KEY_TASK_RESOURCE_DISTRIBUTION

# ── Minimal synthetic BPMN ────────────────────────────────────────────────────
#
#  start_1 ──flow_in──► task_1 ("Test Task") ──flow_out──► end_1

MINIMAL_BPMN = """\
<?xml version="1.0" encoding="utf-8"?>
<bpmn:definitions
    xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
    xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
    xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
    id="def_1">
  <bpmn:process id="proc_1" isExecutable="true">
    <bpmn:startEvent id="start_1"/>
    <bpmn:task id="task_1" name="Test Task"/>
    <bpmn:endEvent id="end_1"/>
    <bpmn:sequenceFlow id="flow_in"  sourceRef="start_1" targetRef="task_1"/>
    <bpmn:sequenceFlow id="flow_out" sourceRef="task_1"  targetRef="end_1"/>
  </bpmn:process>
  <bpmndi:BPMNDiagram id="diagram_1">
    <bpmndi:BPMNPlane id="plane_1" bpmnElement="proc_1">
      <bpmndi:BPMNShape id="start_1_di" bpmnElement="start_1">
        <dc:Bounds x="100" y="200" width="36" height="36"/>
        <bpmndi:BPMNLabel/>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="task_1_di" bpmnElement="task_1">
        <dc:Bounds x="200" y="180" width="100" height="80"/>
        <bpmndi:BPMNLabel/>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="end_1_di" bpmnElement="end_1">
        <dc:Bounds x="400" y="200" width="36" height="36"/>
        <bpmndi:BPMNLabel/>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="flow_in_di" bpmnElement="flow_in">
        <di:waypoint x="136" y="218"/>
        <di:waypoint x="200" y="220"/>
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="flow_out_di" bpmnElement="flow_out">
        <di:waypoint x="300" y="220"/>
        <di:waypoint x="400" y="218"/>
      </bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""

MINIMAL_PARAMS = {
    KEY_RESOURCE_CALENDARS: [
        {
            "id": "cal_human",
            "name": "9-5 Weekdays",
            "time_periods": [{
                "from": "MONDAY", "to": "FRIDAY",
                "beginTime": "09:00:00.000", "endTime": "17:00:00.000",
            }],
        }
    ],
    KEY_RESOURCE_PROFILES: [
        {
            "id": "profile_human",
            "name": "Human Workers",
            "resource_list": [{
                "id": "res_human_1",
                "name": "Worker",
                "cost_per_hour": "10",
                "amount": 1,
                "calendar": "cal_human",
                "assignedTasks": ["task_1"],
            }],
        }
    ],
    KEY_TASK_RESOURCE_DISTRIBUTION: [
        {
            "task_id": "task_1",
            "resources": [{
                "resource_id": "res_human_1",
                "distribution_name": "fix",
                "distribution_params": [{"value": 3600.0}],
            }],
        }
    ],
    KEY_GATEWAY_BRANCHING_PROBS: [],
}


@pytest.fixture
def pattern():
    return XORSplitAutomation()


@pytest.fixture
def bpmn_file(tmp_path):
    p = tmp_path / "test.bpmn"
    p.write_text(MINIMAL_BPMN, encoding="utf-8")
    return p


@pytest.fixture
def params_file(tmp_path):
    p = tmp_path / "params.json"
    p.write_text(json.dumps(MINIMAL_PARAMS), encoding="utf-8")
    return p


@pytest.fixture
def applied(pattern, bpmn_file, tmp_path):
    """Runs apply_pattern and returns (bpmn_out_path, ids)."""
    bpmn_out, ids = pattern.apply_pattern(bpmn_file, "Test Task", tmp_path / "out")
    return bpmn_out, ids
