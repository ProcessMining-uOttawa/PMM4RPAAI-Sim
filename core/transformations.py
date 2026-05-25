"""Pluggable BPMN+JSON mutations — pattern definitions and their contracts."""
from __future__ import annotations
import copy, json
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from pathlib import Path

from .parameters import Parameter
from .constants import (
    BOT_PROFILE_ID, BOT_PROFILE_NAME,
    BOT_CALENDAR_ID, BOT_CALENDAR_NAME,
    BOT_CALENDAR_FROM, BOT_CALENDAR_TO, BOT_CALENDAR_BEGIN, BOT_CALENDAR_END,
    BOT_COST_PER_HOUR, BOT_AMOUNT,
    BOT_DISTRIBUTION_NAME, BOT_DISTRIBUTION_VALUE,
    GW1_NAME, GW2_NAME, GW3_NAME, GW4_NAME,
    F_BOT_BRANCH_LABEL, F_HUMAN_BRANCH_LABEL,
    F_BOT_SUCCESS_LABEL, F_BOT_FAILURE_LABEL,
)
from .bpmn_edit import (
    find_process, find_task_in_process,
    flows_targeting, flows_from,
    add_task_el, add_xor_el, add_flow_el, update_flow_target,
)


# ── Public dataclasses ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TransformIds:
    """All generated element IDs for one pattern application."""
    task_id:           str
    bot_id:            str
    automation_gate:   str   # XOR split: bot vs human
    bot_result_gate:   str   # XOR split: bot success vs failure
    fallback_merge:    str   # XOR merge: human_branch + bot_failure → human task
    final_join_gate:   str   # XOR merge: bot_success + human task → exit
    automation_branch: str   # flow: automation_gate → bot task
    manual_branch:     str   # flow: automation_gate → fallback_merge (always-human)
    bot_output:        str   # flow: bot task → bot_result_gate
    bot_success:       str   # flow: bot_result_gate → final_join_gate
    bot_failure:       str   # flow: bot_result_gate → fallback_merge
    to_human:          str   # flow: fallback_merge → human task
    exit_flow:         str   # flow: final_join_gate → next element


@dataclass
class BpmnTransformResult:
    """Returned by apply_bpmn(). Shared across all scenarios in one experiment."""
    bpmn_path: Path
    base_json: dict   # template — deep-copied and extended per scenario
    ids: TransformIds


class Transformation(ABC):
    id: str
    label: str

    @abstractmethod
    def parameters(self, target_activity: str,
                   current_duration_s: float | None = None) -> list[Parameter]:
        """Declare factors. `current_duration_s` (Simod mean) prepopulates levels."""

    @abstractmethod
    def apply_bpmn(self, bpmn_in: Path, json_in: Path, target_activity: str,
                   out_dir: Path) -> BpmnTransformResult:
        """Structural transform: add pattern elements + rewire flows. Called once per experiment."""

    @abstractmethod
    def apply_params(self, base_json: dict, ids: TransformIds,
                     scenario: Any, json_out: Path) -> Path:
        """Parameter injection: set probabilities + durations. Called once per scenario.
        The concrete type of `scenario` is pattern-specific."""


# ── ID helper ─────────────────────────────────────────────────────────────────

def _make_ids(task_id: str) -> TransformIds:
    p = f"{task_id}_auto"
    return TransformIds(
        task_id=task_id,              bot_id=f"{task_id}_bot",
        automation_gate=f"{p}_gw1",  bot_result_gate=f"{p}_gw2",
        fallback_merge=f"{p}_gw3",   final_join_gate=f"{p}_gw4",
        automation_branch=f"{p}_bot_branch", manual_branch=f"{p}_human_branch",
        bot_output=f"{p}_bot_to_gw2",        bot_success=f"{p}_bot_success",
        bot_failure=f"{p}_bot_failure",       to_human=f"{p}_to_human",
        exit_flow=f"{p}_exit",
    )


# ============================================================================
# XOR substitution: 4 gateways + 1 bot task (mirrors automation-bypass pattern)
#
#  prev ──(in_flow)──► automation_gate ──automation_branch──► Bot_Task ──bot_output──► bot_result_gate ──bot_success──► final_join_gate ──(exit_flow)──► next
#                            │                                                               └──bot_failure──► fallback_merge
#                            └──manual_branch─────────────────────────────────────────────────────────────► fallback_merge
#                                                                                                                  └──to_human──► Task ──(out_flow)──► final_join_gate
# ============================================================================

@dataclass(frozen=True)
class AutomationScenario:
    """Human-readable inputs for one automation simulation run.

    Primary fields are set directly. Complements are computed properties so
    the caller never has to manage them explicitly.
    """
    automation_rate:       float  # [0, 1] fraction of cases routed to the bot
    bot_failure_rate:      float  # [0, 1] fraction of bot attempts that fail
    bot_execution_time:    float  # mean bot task duration (seconds)
    manual_execution_time: float  # mean human task duration (seconds)
    num_bots:              int    # bot resource pool size
    num_manual_resources:  int    # human resource pool size

    def __post_init__(self) -> None:
        for name, val in (("automation_rate",  self.automation_rate),
                          ("bot_failure_rate", self.bot_failure_rate)):
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {val}")

    @property
    def manual_branch_rate(self) -> float:
        return round(1.0 - self.automation_rate, 10)

    @property
    def bot_success_rate(self) -> float:
        return round(1.0 - self.bot_failure_rate, 10)

    @classmethod
    def from_taguchi_values(cls, values: dict) -> "AutomationScenario":
        """Bridge: construct from a Taguchi-generated values dict."""
        def _v(suffix: str, default: float) -> float:
            for k, v in values.items():
                if k.endswith("." + suffix):
                    return float(v)
            return default

        return cls(
            automation_rate=_v("pct_auto", 50.0) / 100.0,
            bot_failure_rate=1.0 - _v("pct_ok", 90.0) / 100.0,
            bot_execution_time=_v("t_auto", 60.0),
            manual_execution_time=_v("t_manual", 1800.0),
            num_bots=1,
            num_manual_resources=1,
        )


class XORSplitAutomation(Transformation):
    id = "xor_split_automation"
    label = "XOR split: automated / manual with OK-fallback"

    # --- parameters ----------------------------------------------------------
    def parameters(self, target_activity: str,
                   current_duration_s: float | None = None) -> list[Parameter]:
        t = float(current_duration_s) if current_duration_s else 1800.0
        a = target_activity
        return [
            Parameter(f"{a}.pct_auto", f"{a}: % automated (Auto)",
                      levels=[25, 50, 75], kind="percentage"),
            Parameter(f"{a}.pct_ok",   f"{a}: % auto-success (OK)",
                      levels=[80, 90, 95], kind="percentage"),
            Parameter(f"{a}.t_auto",   f"{a}: Auto-Time mean (s)",
                      levels=[round(t/20, 1), round(t/10, 1), round(t/5, 1)],
                      kind="duration_s"),
            Parameter(f"{a}.t_manual", f"{a}: Non-auto-Time mean (s) [from Simod]",
                      levels=[round(t*0.8, 1), round(t, 1), round(t*1.2, 1)],
                      kind="duration_s"),
        ]

    # --- apply_bpmn ----------------------------------------------------------
    def apply_bpmn(self, bpmn_in: Path, json_in: Path, target_activity: str,
                   out_dir: Path) -> BpmnTransformResult:
        """Add pattern elements to the BPMN and build the base JSON template.
        Called once per experiment; result is shared across all scenarios."""
        out_dir.mkdir(parents=True, exist_ok=True)
        bpmn_out = out_dir / "model.bpmn"

        tree    = ET.parse(str(bpmn_in))
        root    = tree.getroot()
        process = find_process(root)
        if process is None:
            raise ValueError(f"No <bpmn:process> found in {bpmn_in}")

        task = find_task_in_process(process, target_activity)
        if task is None:
            raise ValueError(f"Activity {target_activity!r} not found in {bpmn_in}")

        T_id   = task.get("id")
        T_name = task.get("name")

        incoming = flows_targeting(process, T_id)
        outgoing = flows_from(process, T_id)
        if len(incoming) != 1 or len(outgoing) != 1:
            raise NotImplementedError(
                f"{target_activity}: expected 1 incoming + 1 outgoing flow, "
                f"got {len(incoming)} + {len(outgoing)}. "
                "Pattern doesn't yet handle tasks fed by gateways directly."
            )

        ids = _make_ids(T_id)
        in_flow_id       = incoming[0].get("id")
        out_flow_id      = outgoing[0].get("id")
        original_next_id = outgoing[0].get("targetRef")

        # 1. Add all new elements so DI bounds exist before wiring
        add_task_el(root, process, ids.bot_id,          f"Auto {T_name}",       after_id=T_id)
        add_xor_el (root, process, ids.automation_gate, GW1_NAME,               after_id=T_id)
        add_xor_el (root, process, ids.bot_result_gate, GW2_NAME,               after_id=ids.bot_id)
        add_xor_el (root, process, ids.fallback_merge,  GW3_NAME,               after_id=ids.bot_result_gate)
        add_xor_el (root, process, ids.final_join_gate, GW4_NAME,               after_id=ids.fallback_merge)

        # 2. Redirect boundary flows
        update_flow_target(root, process, in_flow_id,  ids.automation_gate)
        update_flow_target(root, process, out_flow_id, ids.final_join_gate)

        # 3. Wire the seven internal flows
        add_flow_el(root, process, ids.automation_branch, ids.automation_gate, ids.bot_id,          name=F_BOT_BRANCH_LABEL)
        add_flow_el(root, process, ids.manual_branch,     ids.automation_gate, ids.fallback_merge,  name=F_HUMAN_BRANCH_LABEL)
        add_flow_el(root, process, ids.bot_output,        ids.bot_id,          ids.bot_result_gate)
        add_flow_el(root, process, ids.bot_success,       ids.bot_result_gate, ids.final_join_gate, name=F_BOT_SUCCESS_LABEL)
        add_flow_el(root, process, ids.bot_failure,       ids.bot_result_gate, ids.fallback_merge,  name=F_BOT_FAILURE_LABEL)
        add_flow_el(root, process, ids.to_human,          ids.fallback_merge,  T_id)
        add_flow_el(root, process, ids.exit_flow,         ids.final_join_gate, original_next_id)

        tree.write(str(bpmn_out), xml_declaration=True, encoding="utf-8")

        # Build base JSON: load original, add bot resource infra + task entry.
        # Durations and gateway probs are scenario-specific — added in apply_params.
        data = json.loads(Path(json_in).read_text())
        if not any(e.get("task_id") == T_id
                   for e in data.get("task_resource_distribution", [])):
            raise RuntimeError(
                f"No task_resource_distribution entry for {T_id} in {json_in}"
            )

        bot_resource_id   = f"{ids.bot_id}_resource"
        bot_resource_name = f"{T_name} bot"

        # 1. Add 24/7 bot calendar if absent.
        calendars = data.setdefault("resource_calendars", [])
        if not any(c.get("id") == BOT_CALENDAR_ID for c in calendars):
            calendars.append({
                "id":   BOT_CALENDAR_ID,
                "name": BOT_CALENDAR_NAME,
                "time_periods": [{
                    "from": BOT_CALENDAR_FROM, "to": BOT_CALENDAR_TO,
                    "beginTime": BOT_CALENDAR_BEGIN, "endTime": BOT_CALENDAR_END,
                }],
            })

        # 2. Add bot resource profile if absent; always append this task's resource.
        profiles = data.setdefault("resource_profiles", [])
        bot_profile = next((p for p in profiles if p.get("id") == BOT_PROFILE_ID), None)
        if bot_profile is None:
            bot_profile = {"id": BOT_PROFILE_ID, "name": BOT_PROFILE_NAME,
                           "resource_list": []}
            profiles.append(bot_profile)
        bot_profile.setdefault("resource_list", []).append({
            "id":            bot_resource_id,
            "name":          bot_resource_name,
            "cost_per_hour": BOT_COST_PER_HOUR,
            "amount":        BOT_AMOUNT,
            "calendar":      BOT_CALENDAR_ID,
            "assignedTasks": [ids.bot_id],
        })

        # 3. Add bot task distribution entry (duration set per-scenario in apply_params).
        data["task_resource_distribution"].append({
            "task_id":   ids.bot_id,
            "resources": [{
                "resource_id":         bot_resource_id,
                "distribution_name":   BOT_DISTRIBUTION_NAME,
                "distribution_params": [{"value": BOT_DISTRIBUTION_VALUE}],
            }],
        })

        return BpmnTransformResult(bpmn_path=bpmn_out, base_json=data, ids=ids)

    # --- apply_params --------------------------------------------------------
    def apply_params(self, base_json: dict, ids: TransformIds,
                     scenario: AutomationScenario, json_out: Path) -> Path:
        """Inject scenario-specific values into a deep copy of base_json.
        Called once per scenario; never mutates base_json."""
        data = copy.deepcopy(base_json)

        def _set_uniform(entry: dict, mean_s: float, jitter: float = 0.05) -> None:
            lo = max(0.0, mean_s * (1 - jitter))
            hi = mean_s * (1 + jitter)
            for r in entry["resources"]:
                r["distribution_name"]   = "uniform"
                r["distribution_params"] = [{"value": lo}, {"value": hi}]

        manual_entry = next(
            (e for e in data["task_resource_distribution"] if e["task_id"] == ids.task_id), None
        )
        bot_entry = next(
            (e for e in data["task_resource_distribution"] if e["task_id"] == ids.bot_id), None
        )
        if manual_entry:
            _set_uniform(manual_entry, scenario.manual_execution_time)
        if bot_entry:
            _set_uniform(bot_entry, scenario.bot_execution_time)

        gbp = data.setdefault("gateway_branching_probabilities", [])
        gbp.append({"gateway_id": ids.automation_gate, "probabilities": [
            {"path_id": ids.automation_branch, "value": round(scenario.automation_rate, 6)},
            {"path_id": ids.manual_branch,     "value": round(scenario.manual_branch_rate, 6)},
        ]})
        gbp.append({"gateway_id": ids.bot_result_gate, "probabilities": [
            {"path_id": ids.bot_success, "value": round(scenario.bot_success_rate, 6)},
            {"path_id": ids.bot_failure, "value": round(scenario.bot_failure_rate, 6)},
        ]})
        gbp.append({"gateway_id": ids.fallback_merge, "probabilities": [
            {"path_id": ids.to_human, "value": 1.0},
        ]})
        gbp.append({"gateway_id": ids.final_join_gate, "probabilities": [
            {"path_id": ids.exit_flow, "value": 1.0},
        ]})

        bot_resource_id = f"{ids.bot_id}_resource"
        for profile in data.get("resource_profiles", []):
            for resource in profile.get("resource_list", []):
                if resource.get("id") == bot_resource_id:
                    resource["amount"] = scenario.num_bots

        if manual_entry and manual_entry.get("resources"):
            manual_resource_id = manual_entry["resources"][0].get("resource_id")
            for profile in data.get("resource_profiles", []):
                for resource in profile.get("resource_list", []):
                    if resource.get("id") == manual_resource_id:
                        resource["amount"] = scenario.num_manual_resources

        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(data, indent=2))
        return json_out


REGISTRY: dict[str, Transformation] = {
    XORSplitAutomation.id: XORSplitAutomation(),
}
