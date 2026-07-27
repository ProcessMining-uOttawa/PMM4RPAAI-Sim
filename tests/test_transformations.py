"""Regression tests for core/transformations.py â€” XORSplitAutomation and the
transform-validation error contract; no external tools required."""

from __future__ import annotations
import json
import xml.etree.ElementTree as ET
import pytest

from core.transformations import (
    _make_ids,
    _manual_pool_levels,
    BOT_CALENDAR_ID,
    BOT_PROFILE_ID,
    AutomationParams,
    BpmnTransformResult,
    TransformValidationError,
    XORSplitAutomation,
)
from core.simulation.prosimos.editor import (
    KEY_RESOURCE_CALENDARS,
    KEY_GATEWAY_BRANCHING_PROBS,
)
from core.simulation.prosimos.query import resource_pool_size
from core.bpmn import BPMN_NS
from core.bpmn.validate import (
    Severity,
    VerificationResult,
    Violation,
    verify_fragment,
)
from core.constants import (
    KEY_RESOURCE_PROFILES,
    KEY_TASK_RESOURCE_DISTRIBUTION,
    F_PCT_AUTO,
    F_PCT_OK,
    F_T_AUTO,
    F_T_MANUAL,
    F_NUM_BOTS,
    F_NUM_MANUAL_RESOURCES,
)


# â”€â”€ Shared fixtures â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#
# These live here, not in a root conftest.py, because this module is their only
# consumer.
#
# MINIMAL_PARAMS hardcodes the Prosimos JSON schema keys as string literals
# rather than importing the KEY_* constants from production. The fixture mocks an
# *external* system's document format, so it should be an independent oracle of
# that contract: if a KEY_* constant were ever mistyped, production would look
# for the wrong key in this correctly-spelled document and fail â€” exactly the
# regression a constant-mirrored fixture would silently hide. (Assertions below
# navigate production's *own* output and legitimately use the KEY_* constants.)
#
#  start_1 â”€â”€flow_inâ”€â”€â–º task_1 ("Test Task") â”€â”€flow_outâ”€â”€â–º end_1

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
    "resource_calendars": [
        {
            "id": "cal_human",
            "name": "9-5 Weekdays",
            "time_periods": [
                {
                    "from": "MONDAY",
                    "to": "FRIDAY",
                    "beginTime": "09:00:00.000",
                    "endTime": "17:00:00.000",
                }
            ],
        }
    ],
    "resource_profiles": [
        {
            "id": "profile_human",
            "name": "Human Workers",
            "resource_list": [
                {
                    "id": "res_human_1",
                    "name": "Worker",
                    "cost_per_hour": "10",
                    "amount": 1,
                    "calendar": "cal_human",
                    "assignedTasks": ["task_1"],
                }
            ],
        }
    ],
    "task_resource_distribution": [
        {
            "task_id": "task_1",
            "resources": [
                {
                    "resource_id": "res_human_1",
                    "distribution_name": "fix",
                    "distribution_params": [{"value": 3600.0}],
                }
            ],
        }
    ],
    "gateway_branching_probabilities": [],
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


# â”€â”€ TestParameters â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestParameters:
    """Factor-level declaration, focused on the human-pool centering."""

    def _levels(self, params, factor_id):
        return next(p.levels for p in params if p.id == factor_id)

    def _param(self, params, factor_id):
        return next(p for p in params if p.id == factor_id)

    def test_manual_pool_centered_on_selected_size(self, pattern):
        params = pattern.parameters("T", selected_pool_size=5)
        assert self._levels(params, F_NUM_MANUAL_RESOURCES) == [4, 5, 6]

    def test_manual_pool_floor_at_one(self, pattern):
        # discovered pool of 1 â†’ shift up to [1, 2, 3], never [0, 1, 2]
        params = pattern.parameters("T", selected_pool_size=1)
        assert self._levels(params, F_NUM_MANUAL_RESOURCES) == [1, 2, 3]

    def test_manual_pool_default_when_size_unknown(self, pattern):
        # no pool info (e.g. demo) â†’ default size 1 hits the floor â†’ [1, 2, 3]
        params = pattern.parameters("T")
        assert self._levels(params, F_NUM_MANUAL_RESOURCES) == [1, 2, 3]

    def test_manual_pool_not_frozen_by_default(self, pattern):
        params = pattern.parameters("T", selected_pool_size=5)
        assert self._param(params, F_NUM_MANUAL_RESOURCES).frozen is False

    def test_frozen_pool_pins_all_three_levels(self, pattern):
        params = pattern.parameters("T", frozen_pool_size=4)
        manual = self._param(params, F_NUM_MANUAL_RESOURCES)
        assert manual.levels == [4, 4, 4]
        assert manual.frozen is True

    def test_frozen_takes_precedence_over_selected(self, pattern):
        params = pattern.parameters("T", selected_pool_size=8, frozen_pool_size=3)
        assert self._levels(params, F_NUM_MANUAL_RESOURCES) == [3, 3, 3]

    def test_bot_pool_levels_unchanged(self, pattern):
        # num_bots is a NEW pool â€” stays 1/2/3 regardless of the discovered human pool
        params = pattern.parameters("T", selected_pool_size=8)
        assert self._levels(params, F_NUM_BOTS) == [1, 2, 3]

    def test_auto_and_manual_time_prepopulated_from_discovered_mean(self, pattern):
        # t_auto = 5/10/20 % of the discovered mean; t_manual = 80/100/120 %.
        params = pattern.parameters("T", current_duration_s=3600.0)
        assert self._levels(params, F_T_AUTO) == [180.0, 360.0, 720.0]
        assert self._levels(params, F_T_MANUAL) == [2880.0, 3600.0, 4320.0]

    @pytest.mark.parametrize("dur", [0.0, None])
    def test_auto_and_manual_time_fall_back_to_default_duration(self, pattern, dur):
        # A zero or None discovered duration falls back to DEFAULT_MANUAL_DURATION_S
        # (1800 s) as the base for both factors (both are falsy in `if current_duration_s`).
        params = pattern.parameters("T", current_duration_s=dur)
        assert self._levels(params, F_T_AUTO) == [90.0, 180.0, 360.0]
        assert self._levels(params, F_T_MANUAL) == [1440.0, 1800.0, 2160.0]


class TestManualPoolLevels:
    """The centering formula in isolation."""

    def test_perturbs_by_one_for_normal_pool(self):
        assert _manual_pool_levels(5) == [4, 5, 6]

    def test_two_gives_one_two_three(self):
        assert _manual_pool_levels(2) == [1, 2, 3]

    def test_one_shifts_up(self):
        assert _manual_pool_levels(1) == [1, 2, 3]

    def test_levels_stay_distinct_and_positive(self):
        for n in range(1, 20):
            levels = _manual_pool_levels(n)
            assert len(set(levels)) == 3
            assert all(v >= 1 for v in levels)


# â”€â”€ Multi-flow BPMN fixtures (no DI section needed â€” error raised before DI work) â”€

MULTI_INCOMING_BPMN = """\
<?xml version="1.0" encoding="utf-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="def_1">
  <bpmn:process id="proc_1" isExecutable="true">
    <bpmn:startEvent id="start_1"/>
    <bpmn:startEvent id="start_2"/>
    <bpmn:task id="task_1" name="Test Task"/>
    <bpmn:endEvent id="end_1"/>
    <bpmn:sequenceFlow id="flow_in1" sourceRef="start_1" targetRef="task_1"/>
    <bpmn:sequenceFlow id="flow_in2" sourceRef="start_2" targetRef="task_1"/>
    <bpmn:sequenceFlow id="flow_out" sourceRef="task_1"  targetRef="end_1"/>
  </bpmn:process>
</bpmn:definitions>
"""

MULTI_OUTGOING_BPMN = """\
<?xml version="1.0" encoding="utf-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="def_1">
  <bpmn:process id="proc_1" isExecutable="true">
    <bpmn:startEvent id="start_1"/>
    <bpmn:task id="task_1" name="Test Task"/>
    <bpmn:endEvent id="end_1"/>
    <bpmn:endEvent id="end_2"/>
    <bpmn:sequenceFlow id="flow_in"   sourceRef="start_1" targetRef="task_1"/>
    <bpmn:sequenceFlow id="flow_out1" sourceRef="task_1"  targetRef="end_1"/>
    <bpmn:sequenceFlow id="flow_out2" sourceRef="task_1"  targetRef="end_2"/>
  </bpmn:process>
</bpmn:definitions>
"""


# Same single-in/single-out shape as MINIMAL_BPMN, but carrying no BPMNDiagram â€”
# schema-legal (DI is minOccurs="0"), and the one input apply_pattern rejects
# outright rather than transforming.
NO_DI_BPMN = """\
<?xml version="1.0" encoding="utf-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="def_1">
  <bpmn:process id="proc_1" isExecutable="true">
    <bpmn:startEvent id="start_1"/>
    <bpmn:task id="task_1" name="Test Task"/>
    <bpmn:endEvent id="end_1"/>
    <bpmn:sequenceFlow id="flow_in"  sourceRef="start_1" targetRef="task_1"/>
    <bpmn:sequenceFlow id="flow_out" sourceRef="task_1"  targetRef="end_1"/>
  </bpmn:process>
</bpmn:definitions>
"""


# Carries a <BPMNDiagram> but no <BPMNPlane> inside it. The plane is what holds
# the shapes, so this is rejected too â€” but the message must name the plane, not
# claim the diagram is missing from a model that has one.
DIAGRAM_WITHOUT_PLANE_BPMN = """\
<?xml version="1.0" encoding="utf-8"?>
<bpmn:definitions
    xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
    id="def_1">
  <bpmn:process id="proc_1" isExecutable="true">
    <bpmn:startEvent id="start_1"/>
    <bpmn:task id="task_1" name="Test Task"/>
    <bpmn:endEvent id="end_1"/>
    <bpmn:sequenceFlow id="flow_in"  sourceRef="start_1" targetRef="task_1"/>
    <bpmn:sequenceFlow id="flow_out" sourceRef="task_1"  targetRef="end_1"/>
  </bpmn:process>
  <bpmndi:BPMNDiagram id="diagram_1"/>
</bpmn:definitions>
"""


# The target's outgoing flow names no targetRef, so the pattern has nowhere to
# re-attach the exit arc. Malformed input (targetRef is required on
# tSequenceFlow) â€” rejected at the boundary rather than wired into a dangling ref.
NO_TARGET_REF_BPMN = """\
<?xml version="1.0" encoding="utf-8"?>
<bpmn:definitions
    xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
    xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
    id="def_1">
  <bpmn:process id="proc_1" isExecutable="true">
    <bpmn:startEvent id="start_1"/>
    <bpmn:task id="task_1" name="Test Task"/>
    <bpmn:sequenceFlow id="flow_in"  sourceRef="start_1" targetRef="task_1"/>
    <bpmn:sequenceFlow id="flow_out" sourceRef="task_1"/>
  </bpmn:process>
  <bpmndi:BPMNDiagram id="diagram_1">
    <bpmndi:BPMNPlane id="plane_1" bpmnElement="proc_1">
      <bpmndi:BPMNShape id="task_1_di" bpmnElement="task_1">
        <dc:Bounds x="100" y="100" width="100" height="80"/>
      </bpmndi:BPMNShape>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""


# â”€â”€ TestMultiFlowNotImplemented â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestMultiFlowNotImplemented:
    def test_multi_incoming_raises(self, pattern, tmp_path):
        bpmn = tmp_path / "multi_in.bpmn"
        bpmn.write_text(MULTI_INCOMING_BPMN, encoding="utf-8")
        with pytest.raises(NotImplementedError, match="expected 1 incoming"):
            pattern.apply_pattern(bpmn, "Test Task", tmp_path / "out")

    def test_multi_outgoing_raises(self, pattern, tmp_path):
        bpmn = tmp_path / "multi_out.bpmn"
        bpmn.write_text(MULTI_OUTGOING_BPMN, encoding="utf-8")
        with pytest.raises(NotImplementedError, match=r"got 1 \+ 2"):
            pattern.apply_pattern(bpmn, "Test Task", tmp_path / "out")


# â”€â”€ TestApplyPattern â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


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
        task_ids = {t.get("id") for t in tree.findall(f".//{{{BPMN_NS}}}task")}
        assert ids.bot_id in task_ids

    def test_four_gateways_added(self, applied):
        bpmn_out, ids = applied
        tree = ET.parse(str(bpmn_out))
        gw_ids = {
            gw.get("id") for gw in tree.findall(f".//{{{BPMN_NS}}}exclusiveGateway")
        }
        assert {
            ids.automation_gate,
            ids.bot_result_gate,
            ids.fallback_merge,
            ids.final_join_gate,
        } <= gw_ids

    def test_seven_internal_flows_added(self, applied):
        bpmn_out, ids = applied
        tree = ET.parse(str(bpmn_out))
        flow_ids = {f.get("id") for f in tree.findall(f".//{{{BPMN_NS}}}sequenceFlow")}
        internal = {
            ids.automation_branch,
            ids.manual_branch,
            ids.bot_output,
            ids.bot_success,
            ids.bot_failure,
            ids.to_human,
            ids.exit_flow,
        }
        assert internal <= flow_ids

    def test_incoming_flow_redirected_to_automation_gate(self, applied):
        bpmn_out, ids = applied
        tree = ET.parse(str(bpmn_out))
        flow = next(
            f
            for f in tree.findall(f".//{{{BPMN_NS}}}sequenceFlow")
            if f.get("id") == "flow_in"
        )
        assert flow.get("targetRef") == ids.automation_gate

    def test_outgoing_flow_redirected_to_final_join(self, applied):
        bpmn_out, ids = applied
        tree = ET.parse(str(bpmn_out))
        flow = next(
            f
            for f in tree.findall(f".//{{{BPMN_NS}}}sequenceFlow")
            if f.get("id") == "flow_out"
        )
        assert flow.get("targetRef") == ids.final_join_gate

    def test_missing_activity_raises(self, pattern, bpmn_file, tmp_path):
        with pytest.raises(ValueError, match="not found"):
            pattern.apply_pattern(bpmn_file, "Nonexistent Activity", tmp_path / "out")

    def test_di_less_model_raises(self, pattern, tmp_path):
        # A DI-less model is schema-legal and Prosimos-executable, but the BPMN
        # ships as an externally-inspected export and the pattern is laid out
        # against the existing diagram â€” so it is rejected, not half-applied.
        bpmn = tmp_path / "no_di.bpmn"
        bpmn.write_text(NO_DI_BPMN, encoding="utf-8")
        with pytest.raises(ValueError, match="No <bpmndi:BPMNPlane> found"):
            pattern.apply_pattern(bpmn, "Test Task", tmp_path / "out")

    def test_diagram_without_a_plane_names_the_plane(self, pattern, tmp_path):
        # The guard resolves the plane, so it must not claim the *diagram* is
        # missing from a model that plainly has one â€” the error would send the
        # reader looking for an element sitting right there in their file.
        bpmn = tmp_path / "no_plane.bpmn"
        bpmn.write_text(DIAGRAM_WITHOUT_PLANE_BPMN, encoding="utf-8")
        with pytest.raises(ValueError, match="No <bpmndi:BPMNPlane> found"):
            pattern.apply_pattern(bpmn, "Test Task", tmp_path / "out")

    def test_outgoing_flow_without_target_ref_raises(self, pattern, tmp_path):
        # Malformed input, not caller error: it must surface as a boundary
        # ValueError, not as add_flow_el's assert tripping on an empty id once
        # the wiring is underway.
        bpmn = tmp_path / "no_target_ref.bpmn"
        bpmn.write_text(NO_TARGET_REF_BPMN, encoding="utf-8")
        with pytest.raises(ValueError, match="has no targetRef"):
            pattern.apply_pattern(bpmn, "Test Task", tmp_path / "out")

    def test_di_less_model_writes_no_output(self, pattern, tmp_path):
        # A rejected DI-less transform must write no output â€” a partial apply
        # would leave real flows pointing at gateways that were never created.
        bpmn = tmp_path / "no_di.bpmn"
        bpmn.write_text(NO_DI_BPMN, encoding="utf-8")
        out_dir = tmp_path / "out"
        with pytest.raises(ValueError):
            pattern.apply_pattern(bpmn, "Test Task", out_dir)
        assert not (out_dir / "model.bpmn").exists()


# â”€â”€ TestBuildBaseJson â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestBuildBaseJson:
    @pytest.fixture
    def scenario_template(self, pattern, params_file, applied):
        _, ids = applied
        return pattern.build_scenario_template(params_file, ids)

    def test_bot_calendar_added(self, scenario_template):
        cal_ids = {c["id"] for c in scenario_template[KEY_RESOURCE_CALENDARS]}
        assert BOT_CALENDAR_ID in cal_ids

    def test_bot_profile_added(self, scenario_template):
        profile_ids = {p["id"] for p in scenario_template[KEY_RESOURCE_PROFILES]}
        assert BOT_PROFILE_ID in profile_ids

    def test_bot_resource_in_profile(self, scenario_template, applied):
        _, ids = applied
        bot_profile = next(
            p
            for p in scenario_template[KEY_RESOURCE_PROFILES]
            if p["id"] == BOT_PROFILE_ID
        )
        resource_ids = {r["id"] for r in bot_profile["resource_list"]}
        assert ids.bot_resource_id in resource_ids

    def test_bot_task_distribution_added(self, scenario_template, applied):
        _, ids = applied
        task_ids = {
            e["task_id"] for e in scenario_template[KEY_TASK_RESOURCE_DISTRIBUTION]
        }
        assert ids.bot_id in task_ids

    def test_original_task_preserved(self, scenario_template):
        task_ids = {
            e["task_id"] for e in scenario_template[KEY_TASK_RESOURCE_DISTRIBUTION]
        }
        assert "task_1" in task_ids

    def test_bot_cost_written_to_profile(self, pattern, params_file, applied):
        _, ids = applied
        template = pattern.build_scenario_template(
            params_file, ids, bot_cost_per_hour=15.0
        )
        bot_profile = next(
            p for p in template[KEY_RESOURCE_PROFILES] if p["id"] == BOT_PROFILE_ID
        )
        bot_resource = next(
            r for r in bot_profile["resource_list"] if r["id"] == ids.bot_resource_id
        )
        assert bot_resource["cost_per_hour"] == "15.0"

    def test_missing_task_in_params_raises(self, pattern, params_file):
        ids = _make_ids("nonexistent_id", "Fake Task")
        with pytest.raises(RuntimeError, match="No task_resource_distribution entry"):
            pattern.build_scenario_template(params_file, ids)

    def test_empty_resources_in_params_raises(self, pattern, applied, tmp_path):
        _, ids = applied
        params_empty = tmp_path / "empty_resources.json"
        params_empty.write_text(
            json.dumps(
                {
                    "resource_calendars": [],
                    "resource_profiles": [],
                    "task_resource_distribution": [
                        {"task_id": ids.task_id, "resources": []}
                    ],
                    "gateway_branching_probabilities": [],
                }
            )
        )
        with pytest.raises(RuntimeError, match="no resources assigned"):
            pattern.build_scenario_template(params_empty, ids)


# â”€â”€ TestApplyParams â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_SCENARIO = AutomationParams(
    automation_rate=0.75,
    bot_failure_rate=0.10,
    bot_execution_time=60.0,
    manual_execution_time=1800.0,
    num_bots=2,
    num_manual_resources=3,
    selected_resource_id="res_human_1",
)


class TestApplyParams:
    @pytest.fixture
    def result(self, pattern, params_file, applied, tmp_path):
        """Returns (output_data, ids, scenario_template) for _SCENARIO."""
        _, ids = applied
        scenario_template = pattern.build_scenario_template(params_file, ids)
        json_out = tmp_path / "scenario" / "params.json"
        pattern.apply_params(scenario_template, ids, _SCENARIO, json_out)
        return json.loads(json_out.read_text()), ids, scenario_template

    def test_output_file_written(self, result, tmp_path):
        _, _, _ = result
        assert (tmp_path / "scenario" / "params.json").exists()

    def test_automation_gate_probabilities(self, result):
        data, ids, _ = result
        probs = _gbp_probs(data, ids.automation_gate)
        assert probs[ids.automation_branch] == pytest.approx(0.75)
        assert probs[ids.manual_branch] == pytest.approx(0.25)
        assert sum(probs.values()) == pytest.approx(1.0)

    def test_bot_result_gate_probabilities(self, result):
        data, ids, _ = result
        probs = _gbp_probs(data, ids.bot_result_gate)
        assert probs[ids.bot_success] == pytest.approx(0.90)
        assert probs[ids.bot_failure] == pytest.approx(0.10)
        assert sum(probs.values()) == pytest.approx(1.0)

    def test_merge_gates_have_probability_one(self, result):
        data, ids, _ = result
        assert _gbp_probs(data, ids.fallback_merge)[ids.to_human] == pytest.approx(1.0)
        assert _gbp_probs(data, ids.final_join_gate)[ids.exit_flow] == pytest.approx(
            1.0
        )

    def test_bot_duration_set_fixed(self, result):
        data, ids, _ = result
        entry = next(
            e
            for e in data[KEY_TASK_RESOURCE_DISTRIBUTION]
            if e["task_id"] == ids.bot_id
        )
        r = entry["resources"][0]
        assert r["distribution_name"] == "fix"
        assert r["distribution_params"] == [{"value": 60.0}]

    def test_manual_duration_set_within_jitter(self, result):
        data, ids, _ = result
        lo, hi = _task_dist_bounds(data, ids.task_id)
        assert lo == pytest.approx(1800.0 * 0.95)
        assert hi == pytest.approx(1800.0 * 1.05)

    def test_bot_resource_amount_set(self, result):
        data, ids, _ = result
        amount = resource_pool_size(data, ids.bot_resource_id)
        assert amount == 2

    def test_manual_resource_amount_set(self, result):
        data, ids, _ = result
        amount = resource_pool_size(data, "res_human_1")
        assert amount == 3

    def test_scenario_template_not_mutated(self, result):
        _, _, scenario_template = result
        assert len(scenario_template[KEY_GATEWAY_BRANCHING_PROBS]) == 0

    def test_selected_resource_none_skips_pool_resize(
        self, pattern, params_file, applied, tmp_path
    ):
        _, ids = applied
        scenario_template = pattern.build_scenario_template(params_file, ids)
        scenario = AutomationParams(
            automation_rate=0.5,
            bot_failure_rate=0.1,
            bot_execution_time=60.0,
            manual_execution_time=1800.0,
            num_bots=1,
            num_manual_resources=3,
            selected_resource_id=None,
        )
        json_out = tmp_path / "scenario_none" / "params.json"
        pattern.apply_params(scenario_template, ids, scenario, json_out)
        data = json.loads(json_out.read_text())
        # amount was 1 in the fixture; should be unchanged since selected_resource_id is None
        assert resource_pool_size(data, "res_human_1") == 1


# â”€â”€ AutomationParams validation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestAutomationParamsValidation:
    _base = dict(
        automation_rate=0.5,
        bot_failure_rate=0.1,
        bot_execution_time=60.0,
        manual_execution_time=1800.0,
        num_bots=1,
        num_manual_resources=1,
    )

    def _make(self, **overrides):
        return AutomationParams(**{**self._base, **overrides})

    def test_valid_scenario_ok(self):
        self._make()  # should not raise

    def test_automation_rate_below_zero_raises(self):
        with pytest.raises(ValueError, match="automation_rate"):
            self._make(automation_rate=-0.1)

    def test_automation_rate_above_one_raises(self):
        with pytest.raises(ValueError, match="automation_rate"):
            self._make(automation_rate=1.1)

    def test_bot_failure_rate_out_of_range_raises(self):
        with pytest.raises(ValueError, match="bot_failure_rate"):
            self._make(bot_failure_rate=1.5)

    def test_num_bots_zero_raises(self):
        with pytest.raises(ValueError, match="num_bots"):
            self._make(num_bots=0)

    def test_num_bots_negative_raises(self):
        with pytest.raises(ValueError, match="num_bots"):
            self._make(num_bots=-1)

    def test_num_manual_resources_zero_raises(self):
        with pytest.raises(ValueError, match="num_manual_resources"):
            self._make(num_manual_resources=0)


# â”€â”€ TestParamsFromValues â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_VALUES = {
    F_PCT_AUTO: 50,
    F_PCT_OK: 90,
    F_T_AUTO: 60.0,
    F_T_MANUAL: 1800.0,
    F_NUM_BOTS: 2,
    F_NUM_MANUAL_RESOURCES: 3,
}


class TestParamsFromValues:
    @pytest.fixture
    def bpmn_result(self, pattern, bpmn_file, params_file, tmp_path):
        bpmn_out, ids = pattern.apply_pattern(bpmn_file, "Test Task", tmp_path / "out")
        template = pattern.build_scenario_template(params_file, ids)
        return BpmnTransformResult(
            bpmn_path=bpmn_out,
            scenario_template=template,
            ids=ids,
            selected_resource_id="res_human_1",
        )

    def test_returns_automation_params(self, pattern, bpmn_result):
        params = pattern.params_from_values(_VALUES, bpmn_result)
        assert isinstance(params, AutomationParams)

    def test_values_mapped_correctly(self, pattern, bpmn_result):
        params = pattern.params_from_values(_VALUES, bpmn_result)
        assert params.automation_rate == pytest.approx(0.50)
        assert params.bot_failure_rate == pytest.approx(0.10)
        assert params.bot_execution_time == pytest.approx(60.0)

    def test_selected_resource_id_propagated(self, pattern, bpmn_result):
        params = pattern.params_from_values(_VALUES, bpmn_result)
        assert params.selected_resource_id == "res_human_1"

    def test_none_selected_resource_propagated(
        self, pattern, bpmn_file, params_file, tmp_path
    ):
        bpmn_out, ids = pattern.apply_pattern(bpmn_file, "Test Task", tmp_path / "out2")
        template = pattern.build_scenario_template(params_file, ids)
        result_none = BpmnTransformResult(
            bpmn_path=bpmn_out,
            scenario_template=template,
            ids=ids,
            selected_resource_id=None,
        )
        params = pattern.params_from_values(_VALUES, result_none)
        assert params.selected_resource_id is None


class TestBaselineParams:
    @pytest.fixture
    def bpmn_result(self, pattern, bpmn_file, params_file, tmp_path):
        bpmn_out, ids = pattern.apply_pattern(bpmn_file, "Test Task", tmp_path / "out")
        template = pattern.build_scenario_template(params_file, ids)
        return BpmnTransformResult(
            bpmn_path=bpmn_out,
            scenario_template=template,
            ids=ids,
            selected_resource_id="res_human_1",
        )

    def test_returns_automation_params(self, pattern, bpmn_result):
        assert isinstance(pattern.baseline_params(bpmn_result), AutomationParams)

    def test_zero_automation(self, pattern, bpmn_result):
        params = pattern.baseline_params(bpmn_result)
        assert params.automation_rate == 0.0
        assert params.manual_branch_rate == 1.0  # 100% human path

    def test_manual_duration_is_discovered_mean(self, pattern, bpmn_result):
        # MINIMAL_PARAMS task_1 is fix 3600.0 â†’ that is the baseline human duration
        params = pattern.baseline_params(bpmn_result)
        assert params.manual_execution_time == pytest.approx(3600.0)

    def test_skips_pool_resize(self, pattern, bpmn_result):
        # selected_resource_id=None leaves the human pool at its discovered size
        assert pattern.baseline_params(bpmn_result).selected_resource_id is None

    def test_bot_factors_inert_but_valid(self, pattern, bpmn_result):
        params = pattern.baseline_params(bpmn_result)
        assert params.bot_failure_rate == 0.0
        assert params.num_bots >= 1

    def test_applied_baseline_routes_all_to_human(self, pattern, bpmn_result, tmp_path):
        out = tmp_path / "baseline.json"
        pattern.apply_params(
            bpmn_result.scenario_template,
            bpmn_result.ids,
            pattern.baseline_params(bpmn_result),
            out,
        )
        probs = _gbp_probs(json.loads(out.read_text()), bpmn_result.ids.automation_gate)
        assert probs[bpmn_result.ids.automation_branch] == 0.0
        assert probs[bpmn_result.ids.manual_branch] == 1.0


# â”€â”€ Helpers used by multiple test classes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _gbp_probs(data: dict, gateway_id: str) -> dict:
    """Return {path_id: value} for a gateway in gateway_branching_probabilities."""
    entry = next(
        g for g in data[KEY_GATEWAY_BRANCHING_PROBS] if g["gateway_id"] == gateway_id
    )
    return {p["path_id"]: p["value"] for p in entry["probabilities"]}


def _task_dist_bounds(data: dict, task_id: str) -> tuple[float, float]:
    """Return (lo, hi) uniform bounds for the first resource of a task."""
    entry = next(
        e for e in data[KEY_TASK_RESOURCE_DISTRIBUTION] if e["task_id"] == task_id
    )
    params = entry["resources"][0]["distribution_params"]
    return params[0]["value"], params[1]["value"]


# â”€â”€ AutomationParams.from_taguchi_values â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestFromTaguchiValues:
    _FULL = {
        "pct_auto": 75.0,
        "pct_ok": 90.0,
        "t_auto": 60.0,
        "t_manual": 1800.0,
        "num_bots": 2,
        "num_manual_resources": 3,
    }

    def test_full_values_mapped_correctly(self):
        s = AutomationParams.from_taguchi_values(self._FULL)
        assert s.automation_rate == pytest.approx(0.75)
        assert s.bot_failure_rate == pytest.approx(0.10)  # 1 - 90/100
        assert s.bot_execution_time == pytest.approx(60.0)
        assert s.manual_execution_time == pytest.approx(1800.0)
        assert s.num_bots == 2
        assert s.num_manual_resources == 3

    def test_empty_dict_uses_defaults(self):
        s = AutomationParams.from_taguchi_values({})
        assert s.automation_rate == pytest.approx(0.50)
        assert s.bot_failure_rate == pytest.approx(0.10)
        assert s.num_bots == 1
        assert s.num_manual_resources == 1

    def test_num_bots_and_num_manual_keys_used(self):
        s = AutomationParams.from_taguchi_values(
            {"num_bots": 3, "num_manual_resources": 5}
        )
        assert s.num_bots == 3
        assert s.num_manual_resources == 5

    def test_selected_resource_id_passed_through(self):
        s = AutomationParams.from_taguchi_values({}, selected_resource_id="res_42")
        assert s.selected_resource_id == "res_42"


# â”€â”€ TransformIds properties â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_bot_task_name():
    ids = _make_ids("task_1", "Test Task")
    assert ids.bot_task_name == "Auto Test Task"


# â”€â”€ prepare_experiment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestPrepareExperiment:
    def test_returns_bpmn_transform_result(
        self, pattern, bpmn_file, params_file, tmp_path
    ):
        result = pattern.prepare_experiment(
            bpmn_file, params_file, "Test Task", tmp_path / "out"
        )
        assert isinstance(result, BpmnTransformResult)

    def test_bpmn_path_exists(self, pattern, bpmn_file, params_file, tmp_path):
        result = pattern.prepare_experiment(
            bpmn_file, params_file, "Test Task", tmp_path / "out"
        )
        assert result.bpmn_path.exists()

    def test_selected_resource_id_propagated(
        self, pattern, bpmn_file, params_file, tmp_path
    ):
        result = pattern.prepare_experiment(
            bpmn_file,
            params_file,
            "Test Task",
            tmp_path / "out",
            selected_resource_id="res_human_1",
        )
        assert result.selected_resource_id == "res_human_1"

    def test_selected_resource_id_defaults_to_none(
        self, pattern, bpmn_file, params_file, tmp_path
    ):
        result = pattern.prepare_experiment(
            bpmn_file, params_file, "Test Task", tmp_path / "out"
        )
        assert result.selected_resource_id is None


# â”€â”€ apply_pattern â€” no-process error â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_no_process_raises(pattern, tmp_path):
    from core.bpmn import BPMN_NS as _NS

    bpmn = f"""\
<?xml version="1.0" encoding="utf-8"?>
<bpmn:definitions xmlns:bpmn="{_NS}" id="def_1">
</bpmn:definitions>
"""
    path = tmp_path / "no_process.bpmn"
    path.write_text(bpmn, encoding="utf-8")
    with pytest.raises(ValueError, match="No <bpmn:process>"):
        pattern.apply_pattern(path, "Test Task", tmp_path / "out")


# â”€â”€ TestVerifyTransformed â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestVerifyTransformed:
    def test_delegates_to_verify_fragment(self, pattern, applied):
        # Thin by design â€” pins the ABC wiring: the pattern's verifier is the
        # XOR structural oracle, its result passed through unchanged.
        bpmn_out, _ = applied
        result = pattern.verify_transformed(bpmn_out, "Test Task")
        assert result == verify_fragment(bpmn_out, "Test Task")


# â”€â”€ TestPrepareExperimentGate â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_ERROR_VIOLATION = Violation(
    "MISSING_GATEWAY", Severity.ERROR, "no split gateway", element_id="gw1"
)
_WARNING_VIOLATION = Violation("IO_LIST_DRIFT", Severity.WARNING, "list drift")


class TestPrepareExperimentGate:
    """The verify â†’ report â†’ raise wiring in prepare_experiment.

    The oracle is canned by patching verify_fragment (its own correctness is
    pinned in tests/bpmn/test_validate.py); the real verify_transformed and the
    real gate branch run.
    """

    def _prepare(self, pattern, bpmn_file, params_file, tmp_path):
        return pattern.prepare_experiment(
            bpmn_file, params_file, "Test Task", tmp_path / "out"
        )

    def _stub_oracle(self, monkeypatch, violations):
        canned = VerificationResult(target_activity="Test Task", violations=violations)
        monkeypatch.setattr("core.transformations.verify_fragment", lambda *_: canned)

    def test_error_raises_and_writes_report(
        self, pattern, bpmn_file, params_file, tmp_path, monkeypatch
    ):
        self._stub_oracle(monkeypatch, (_ERROR_VIOLATION, _WARNING_VIOLATION))
        with pytest.raises(TransformValidationError) as exc:
            self._prepare(pattern, bpmn_file, params_file, tmp_path)
        report = tmp_path / "out" / "validation.log"
        text = report.read_text(encoding="utf-8")
        assert exc.value.report_path == report
        assert exc.value.log_tail == text
        assert "ERROR MISSING_GATEWAY" in text and "WARNING IO_LIST_DRIFT" in text

    def test_error_keeps_model_on_disk(
        self, pattern, bpmn_file, params_file, tmp_path, monkeypatch
    ):
        # Regression guard: the mis-wired model is deliberately kept beside the
        # report so both artifacts are inspectable.
        self._stub_oracle(monkeypatch, (_ERROR_VIOLATION,))
        with pytest.raises(TransformValidationError):
            self._prepare(pattern, bpmn_file, params_file, tmp_path)
        assert (tmp_path / "out" / "model.bpmn").exists()

    def test_warnings_only_log_without_raising(
        self, pattern, bpmn_file, params_file, tmp_path, monkeypatch
    ):
        self._stub_oracle(monkeypatch, (_WARNING_VIOLATION,))
        result = self._prepare(pattern, bpmn_file, params_file, tmp_path)
        assert isinstance(result, BpmnTransformResult)
        report = tmp_path / "out" / "validation.log"
        assert "WARNING IO_LIST_DRIFT" in report.read_text(encoding="utf-8")

    def test_clean_model_writes_no_report(
        self, pattern, bpmn_file, params_file, tmp_path
    ):
        # Real oracle, no patch: the minimal fixture transforms clean, so the
        # gate must neither raise nor leave a validation.log behind.
        self._prepare(pattern, bpmn_file, params_file, tmp_path)
        assert not (tmp_path / "out" / "validation.log").exists()


# â”€â”€ TestTransformValidationError â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestTransformValidationError:
    def test_carries_report_path_and_log_tail(self, tmp_path):
        # log_tail is the run-failure surface's contract (read via getattr) â€”
        # renaming the attribute would silently drop the report expander.
        report = tmp_path / "validation.log"
        err = TransformValidationError(
            "2 structural error(s)", report, log_tail="ERROR X: y"
        )
        assert str(err) == "2 structural error(s)"
        assert err.report_path == report
        assert err.log_tail == "ERROR X: y"
        assert isinstance(err, RuntimeError)
