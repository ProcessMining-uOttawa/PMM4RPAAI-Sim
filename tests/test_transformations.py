"""Regression tests for XORSplitAutomation — no external tools required."""
from __future__ import annotations
import json
import xml.etree.ElementTree as ET
import pytest

from core.transformations import (
    _make_ids,
    BOT_CALENDAR_ID, BOT_PROFILE_ID,
    KEY_RESOURCE_CALENDARS, KEY_GATEWAY_BRANCHING_PROBS,
)
from core.transformations import AutomationScenario
from core.bpmn.utils import resource_pool_size
from core.bpmn import BPMN_NS
from core.constants import KEY_RESOURCE_PROFILES, KEY_TASK_RESOURCE_DISTRIBUTION


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
        task_ids = {t.get("id") for t in tree.findall(f".//{{{BPMN_NS}}}task")}
        assert ids.bot_id in task_ids

    def test_four_gateways_added(self, applied):
        bpmn_out, ids = applied
        tree = ET.parse(str(bpmn_out))
        gw_ids = {gw.get("id") for gw in tree.findall(f".//{{{BPMN_NS}}}exclusiveGateway")}
        assert {ids.automation_gate, ids.bot_result_gate,
                ids.fallback_merge, ids.final_join_gate} <= gw_ids

    def test_seven_internal_flows_added(self, applied):
        bpmn_out, ids = applied
        tree = ET.parse(str(bpmn_out))
        flow_ids = {f.get("id") for f in tree.findall(f".//{{{BPMN_NS}}}sequenceFlow")}
        internal = {ids.automation_branch, ids.manual_branch, ids.bot_output,
                    ids.bot_success, ids.bot_failure, ids.to_human, ids.exit_flow}
        assert internal <= flow_ids

    def test_incoming_flow_redirected_to_automation_gate(self, applied):
        bpmn_out, ids = applied
        tree = ET.parse(str(bpmn_out))
        flow = next(f for f in tree.findall(f".//{{{BPMN_NS}}}sequenceFlow")
                    if f.get("id") == "flow_in")
        assert flow.get("targetRef") == ids.automation_gate

    def test_outgoing_flow_redirected_to_final_join(self, applied):
        bpmn_out, ids = applied
        tree = ET.parse(str(bpmn_out))
        flow = next(f for f in tree.findall(f".//{{{BPMN_NS}}}sequenceFlow")
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
    num_cases=100,
    selected_resource_id="res_human_1",
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
        amount = resource_pool_size(data, ids.bot_resource_id)
        assert amount == 2

    def test_manual_resource_amount_set(self, result):
        data, ids, _ = result
        amount = resource_pool_size(data, "res_human_1")
        assert amount == 3

    def test_base_json_not_mutated(self, result):
        _, _, base_json = result
        assert len(base_json[KEY_GATEWAY_BRANCHING_PROBS]) == 0

    def test_selected_resource_none_skips_pool_resize(self, pattern, params_file, applied, tmp_path):
        _, ids = applied
        base_json = pattern.build_base_json(params_file, ids)
        scenario = AutomationScenario(
            automation_rate=0.5, bot_failure_rate=0.1,
            bot_execution_time=60.0, manual_execution_time=1800.0,
            num_bots=1, num_manual_resources=3, num_cases=100,
            selected_resource_id=None,
        )
        json_out = tmp_path / "scenario_none" / "params.json"
        pattern.apply_params(base_json, ids, scenario, json_out)
        data = json.loads(json_out.read_text())
        # amount was 1 in the fixture; should be unchanged since selected_resource_id is None
        assert resource_pool_size(data, "res_human_1") == 1


# ── AutomationScenario validation ────────────────────────────────────────────

class TestAutomationScenarioValidation:
    _base = dict(
        automation_rate=0.5, bot_failure_rate=0.1,
        bot_execution_time=60.0, manual_execution_time=1800.0,
        num_bots=1, num_manual_resources=1, num_cases=100,
    )

    def _make(self, **overrides):
        return AutomationScenario(**{**self._base, **overrides})

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

    def test_num_cases_zero_raises(self):
        with pytest.raises(ValueError, match="num_cases"):
            self._make(num_cases=0)

    def test_num_cases_negative_raises(self):
        with pytest.raises(ValueError, match="num_cases"):
            self._make(num_cases=-1)


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
