"""Regression tests for XORSplitAutomation — no external tools required."""
from __future__ import annotations
import json
import xml.etree.ElementTree as ET
import pytest
from pathlib import Path

from core.transformations import XORSplitAutomation, _make_ids
from core.parameters import AutomationScenario
from core.constants import (
    BOT_CALENDAR_ID, BOT_PROFILE_ID,
    KEY_RESOURCE_CALENDARS, KEY_RESOURCE_PROFILES,
    KEY_TASK_RESOURCE_DISTRIBUTION, KEY_GATEWAY_BRANCHING_PROBS,
)

_BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

# ── Fixtures: minimal synthetic BPMN + params ─────────────────────────────────
#
#  start_1 ──flow_in──► task_1 ("Test Task") ──flow_out──► end_1

_MINIMAL_BPMN = """\
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

_MINIMAL_PARAMS = {
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


# ── Module-level fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def pattern():
    return XORSplitAutomation()


@pytest.fixture
def bpmn_file(tmp_path):
    p = tmp_path / "test.bpmn"
    p.write_text(_MINIMAL_BPMN, encoding="utf-8")
    return p


@pytest.fixture
def params_file(tmp_path):
    p = tmp_path / "params.json"
    p.write_text(json.dumps(_MINIMAL_PARAMS), encoding="utf-8")
    return p


@pytest.fixture
def applied(pattern, bpmn_file, tmp_path):
    """Runs apply_pattern and returns (bpmn_out_path, ids)."""
    bpmn_out, ids = pattern.apply_pattern(bpmn_file, "Test Task", tmp_path / "out")
    return bpmn_out, ids


# ── TestApplyPattern ──────────────────────────────────────────────────────────

class TestApplyPattern:

    def test_output_file_exists(self, applied):
        bpmn_out, _ = applied
        assert bpmn_out.exists()

    def test_ids_populated(self, applied):
        _, ids = applied
        assert ids.task_id == "task_1"
        assert ids.task_name == "Test Task"
        assert ids.bot_resource_id == f"{ids.bot_id}_resource"
        assert ids.bot_resource_name == "Test Task bot"

    def test_bot_task_added(self, applied):
        bpmn_out, ids = applied
        tree = ET.parse(str(bpmn_out))
        task_ids = {t.get("id") for t in tree.findall(f".//{{{_BPMN_NS}}}task")}
        assert ids.bot_id in task_ids

    def test_four_gateways_added(self, applied):
        bpmn_out, ids = applied
        tree = ET.parse(str(bpmn_out))
        gw_ids = {gw.get("id") for gw in tree.findall(f".//{{{_BPMN_NS}}}exclusiveGateway")}
        assert {ids.automation_gate, ids.bot_result_gate,
                ids.fallback_merge, ids.final_join_gate} <= gw_ids

    def test_seven_internal_flows_added(self, applied):
        bpmn_out, ids = applied
        tree = ET.parse(str(bpmn_out))
        flow_ids = {f.get("id") for f in tree.findall(f".//{{{_BPMN_NS}}}sequenceFlow")}
        internal = {ids.automation_branch, ids.manual_branch, ids.bot_output,
                    ids.bot_success, ids.bot_failure, ids.to_human, ids.exit_flow}
        assert internal <= flow_ids

    def test_incoming_flow_redirected_to_automation_gate(self, applied):
        bpmn_out, ids = applied
        tree = ET.parse(str(bpmn_out))
        flow = next(f for f in tree.findall(f".//{{{_BPMN_NS}}}sequenceFlow")
                    if f.get("id") == "flow_in")
        assert flow.get("targetRef") == ids.automation_gate

    def test_outgoing_flow_redirected_to_final_join(self, applied):
        bpmn_out, ids = applied
        tree = ET.parse(str(bpmn_out))
        flow = next(f for f in tree.findall(f".//{{{_BPMN_NS}}}sequenceFlow")
                    if f.get("id") == "flow_out")
        assert flow.get("targetRef") == ids.final_join_gate

    def test_missing_activity_raises(self, pattern, bpmn_file, tmp_path):
        with pytest.raises(ValueError, match="not found"):
            pattern.apply_pattern(bpmn_file, "Nonexistent Activity", tmp_path / "out")


# ── TestBuildBaseJson ─────────────────────────────────────────────────────────

class TestBuildBaseJson:

    @pytest.fixture
    def base_json(self, pattern, params_file, applied):
        _, ids = applied
        return pattern.build_base_json(params_file, ids)

    def test_bot_calendar_added(self, base_json):
        cal_ids = {c["id"] for c in base_json[KEY_RESOURCE_CALENDARS]}
        assert BOT_CALENDAR_ID in cal_ids

    def test_bot_profile_added(self, base_json):
        profile_ids = {p["id"] for p in base_json[KEY_RESOURCE_PROFILES]}
        assert BOT_PROFILE_ID in profile_ids

    def test_bot_resource_in_profile(self, base_json, applied):
        _, ids = applied
        bot_profile = next(p for p in base_json[KEY_RESOURCE_PROFILES]
                           if p["id"] == BOT_PROFILE_ID)
        resource_ids = {r["id"] for r in bot_profile["resource_list"]}
        assert ids.bot_resource_id in resource_ids

    def test_bot_task_distribution_added(self, base_json, applied):
        _, ids = applied
        task_ids = {e["task_id"] for e in base_json[KEY_TASK_RESOURCE_DISTRIBUTION]}
        assert ids.bot_id in task_ids

    def test_original_task_preserved(self, base_json):
        task_ids = {e["task_id"] for e in base_json[KEY_TASK_RESOURCE_DISTRIBUTION]}
        assert "task_1" in task_ids

    def test_missing_task_in_params_raises(self, pattern, params_file):
        ids = _make_ids("nonexistent_id", "Fake Task")
        with pytest.raises(RuntimeError, match="No task_resource_distribution entry"):
            pattern.build_base_json(params_file, ids)


# ── TestApplyParams ───────────────────────────────────────────────────────────

_SCENARIO = AutomationScenario(
    automation_rate=0.75,
    bot_failure_rate=0.10,
    bot_execution_time=60.0,
    manual_execution_time=1800.0,
    num_bots=2,
    num_manual_resources=3,
)


class TestApplyParams:

    @pytest.fixture
    def result(self, pattern, params_file, applied, tmp_path):
        """Returns (output_data, ids, base_json) for _SCENARIO."""
        _, ids = applied
        base_json = pattern.build_base_json(params_file, ids)
        json_out = tmp_path / "scenario" / "params.json"
        pattern.apply_params(base_json, ids, _SCENARIO, json_out)
        return json.loads(json_out.read_text()), ids, base_json

    def test_output_file_written(self, result, tmp_path):
        _, _, _ = result
        assert (tmp_path / "scenario" / "params.json").exists()

    def test_automation_gate_probabilities(self, result):
        data, ids, _ = result
        probs = _gbp_probs(data, ids.automation_gate)
        assert probs[ids.automation_branch] == pytest.approx(0.75)
        assert probs[ids.manual_branch]     == pytest.approx(0.25)
        assert sum(probs.values())          == pytest.approx(1.0)

    def test_bot_result_gate_probabilities(self, result):
        data, ids, _ = result
        probs = _gbp_probs(data, ids.bot_result_gate)
        assert probs[ids.bot_success] == pytest.approx(0.90)
        assert probs[ids.bot_failure] == pytest.approx(0.10)
        assert sum(probs.values())    == pytest.approx(1.0)

    def test_merge_gates_have_probability_one(self, result):
        data, ids, _ = result
        assert _gbp_probs(data, ids.fallback_merge)[ids.to_human]  == pytest.approx(1.0)
        assert _gbp_probs(data, ids.final_join_gate)[ids.exit_flow] == pytest.approx(1.0)

    def test_bot_duration_set_within_jitter(self, result):
        data, ids, _ = result
        lo, hi = _task_dist_bounds(data, ids.bot_id)
        assert lo == pytest.approx(60.0 * 0.95)
        assert hi == pytest.approx(60.0 * 1.05)

    def test_manual_duration_set_within_jitter(self, result):
        data, ids, _ = result
        lo, hi = _task_dist_bounds(data, ids.task_id)
        assert lo == pytest.approx(1800.0 * 0.95)
        assert hi == pytest.approx(1800.0 * 1.05)

    def test_bot_resource_amount_set(self, result):
        data, ids, _ = result
        amount = _resource_amount(data, ids.bot_resource_id)
        assert amount == 2

    def test_manual_resource_amount_set(self, result):
        data, ids, _ = result
        amount = _resource_amount(data, "res_human_1")
        assert amount == 3

    def test_base_json_not_mutated(self, result):
        _, _, base_json = result
        assert len(base_json[KEY_GATEWAY_BRANCHING_PROBS]) == 0


# ── Helpers used by multiple test classes ─────────────────────────────────────

def _gbp_probs(data: dict, gateway_id: str) -> dict:
    """Return {path_id: value} for a gateway in gateway_branching_probabilities."""
    entry = next(g for g in data[KEY_GATEWAY_BRANCHING_PROBS]
                 if g["gateway_id"] == gateway_id)
    return {p["path_id"]: p["value"] for p in entry["probabilities"]}


def _task_dist_bounds(data: dict, task_id: str) -> tuple[float, float]:
    """Return (lo, hi) uniform bounds for the first resource of a task."""
    entry = next(e for e in data[KEY_TASK_RESOURCE_DISTRIBUTION]
                 if e["task_id"] == task_id)
    params = entry["resources"][0]["distribution_params"]
    return params[0]["value"], params[1]["value"]


def _resource_amount(data: dict, resource_id: str) -> int | None:
    for profile in data[KEY_RESOURCE_PROFILES]:
        for resource in profile["resource_list"]:
            if resource["id"] == resource_id:
                return resource["amount"]
    return None
