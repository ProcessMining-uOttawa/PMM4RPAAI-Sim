"""Pluggable BPMN+JSON mutations — pattern definitions, contracts, and scenario inputs."""
from __future__ import annotations
import copy
import json
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from pathlib import Path

from .parameters import Parameter
from .constants import KEY_TASK_RESOURCE_DISTRIBUTION
from .simulation.prosimos_edit import (
    set_uniform, set_fixed, set_resource_amount,
    ensure_calendar, upsert_resource_in_profile,
    append_task_distribution, add_gateway_probs,
)
from .bpmn.edit import (
    find_process, find_task_in_process,
    flows_targeting, flows_from,
    add_task_el, add_xor_el, add_flow_el, update_flow_target,
    diagram_extents, TASK_W, TASK_H, GW_W, GW_H,
)

# ── Bot resource profile ──────────────────────────────────────────────────────
BOT_PROFILE_ID   = "BOT_PROFILE"
BOT_PROFILE_NAME = "Bot Resources"

# ── Bot resource defaults ─────────────────────────────────────────────────────
BOT_COST_PER_HOUR = "0"
BOT_AMOUNT        = 1

# ── Bot calendar ──────────────────────────────────────────────────────────────
BOT_CALENDAR_ID    = "BOT_CALENDAR"
BOT_CALENDAR_NAME  = "Bot 24/7 Schedule"
BOT_CALENDAR_FROM  = "MONDAY"
BOT_CALENDAR_TO    = "SUNDAY"
BOT_CALENDAR_BEGIN = "00:00:00.000"
BOT_CALENDAR_END   = "23:59:59.999"

# ── Bot task distribution defaults ────────────────────────────────────────────
BOT_DISTRIBUTION_NAME  = "fix"
BOT_DISTRIBUTION_VALUE = 0.0

# ── Gateway display names ─────────────────────────────────────────────────────
GW1_NAME = "Bot or Human?"
GW2_NAME = "Bot succeeded?"
GW3_NAME = "Human needed"
GW4_NAME = "Exit"

# ── Sequence flow display labels ──────────────────────────────────────────────
F_BOT_BRANCH_LABEL   = "bot"
F_HUMAN_BRANCH_LABEL = "human"
F_BOT_SUCCESS_LABEL  = "success"
F_BOT_FAILURE_LABEL  = "failure"

# ── XOR split automation: Taguchi parameter defaults ──────────────────────────
DEFAULT_MANUAL_DURATION_S = 1800.0
PCT_AUTO_LEVELS    = [25, 50, 75]
PCT_OK_LEVELS      = [80, 90, 95]
T_AUTO_FRACTIONS   = [0.05, 0.10, 0.20]
T_MANUAL_FACTORS   = [0.80, 1.00, 1.20]
NUM_BOTS_LEVELS    = [1, 2, 3]
NUM_MANUAL_LEVELS  = [1, 2, 3]
NUM_CASES_LEVELS   = [100, 500, 1000]


# ── XORSplitAutomation: scenario input type ───────────────────────────────────

@dataclass(frozen=True)
class AutomationScenario:
    """Concrete inputs for one XORSplitAutomation simulation run.

    Primary fields are set directly. Complements are computed properties so
    the caller never has to manage them explicitly.
    """
    automation_rate:       float       # [0, 1] fraction of cases routed to the bot
    bot_failure_rate:      float       # [0, 1] fraction of bot attempts that fail
    bot_execution_time:    float       # mean bot task duration (seconds)
    manual_execution_time: float       # mean human task duration (seconds)
    num_bots:              int         # bot resource pool size
    num_manual_resources:  int         # human resource pool size
    num_cases:             int         # cases per replication
    selected_resource_id:  str | None = None  # resource to resize; None = skip pool resize

    def __post_init__(self) -> None:
        for name, val in (("automation_rate",  self.automation_rate),
                          ("bot_failure_rate", self.bot_failure_rate)):
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {val}")
        for name, val in (("num_bots", self.num_bots),
                          ("num_manual_resources", self.num_manual_resources),
                          ("num_cases", self.num_cases)):
            if val < 1:
                raise ValueError(f"{name} must be ≥ 1, got {val}")

    @property
    def manual_branch_rate(self) -> float:
        return 1.0 - self.automation_rate

    @property
    def bot_success_rate(self) -> float:
        return 1.0 - self.bot_failure_rate

    @classmethod
    def from_taguchi_values(cls, values: dict,
                            selected_resource_id: str | None = None) -> "AutomationScenario":
        """Bridge: construct AutomationScenario from a Taguchi-generated values dict."""
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
            num_bots=int(_v("num_bots", 1.0)),
            num_manual_resources=int(_v("num_manual_resources", 1.0)),
            num_cases=int(_v("num_cases", 100.0)),
            selected_resource_id=selected_resource_id,
        )


# ── Public dataclasses ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TransformIds:
    """All generated element IDs for one pattern application."""
    task_id:           str
    task_name:         str   # display name of the original task
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

    @property
    def bot_resource_id(self) -> str:
        return f"{self.bot_id}_resource"

    @property
    def bot_resource_name(self) -> str:
        return f"{self.task_name} bot"


@dataclass
class BpmnTransformResult:
    """Returned by prepare_experiment(). Shared across all scenarios in one experiment."""
    bpmn_path:         Path
    scenario_template: dict   # deep-copied and extended per scenario by apply_params
    ids:               TransformIds


class Transformation(ABC):
    id: str
    label: str

    @abstractmethod
    def parameters(self, target_activity: str,
                   current_duration_s: float | None = None,
                   selected_resource_id: str | None = None,
                   frozen_pool_size: int | None = None) -> list[Parameter]:
        """Declare factors. `current_duration_s` prepopulates duration levels.
        `selected_resource_id` identifies which resource pool to vary.
        `frozen_pool_size` freezes the manual pool factor at that value when set."""

    def prepare_experiment(self, bpmn_in: Path, json_in: Path, target_activity: str,
                           out_dir: Path) -> BpmnTransformResult:
        """Coordinate the two-step experiment setup. Called once per experiment."""
        bpmn_out, ids      = self.apply_pattern(bpmn_in, target_activity, out_dir)
        scenario_template  = self.build_scenario_template(json_in, ids)
        return BpmnTransformResult(bpmn_path=bpmn_out, scenario_template=scenario_template, ids=ids)

    @abstractmethod
    def apply_pattern(self, bpmn_in: Path, target_activity: str,
                      out_dir: Path) -> tuple[Path, TransformIds]:
        """Add pattern elements to the BPMN and write to out_dir."""

    @abstractmethod
    def build_scenario_template(self, json_in: Path, ids: TransformIds) -> dict:
        """Load the Prosimos JSON and inject pattern-specific shared infrastructure."""

    @abstractmethod
    def apply_params(self, scenario_template: dict, ids: TransformIds,
                     scenario: Any, json_out: Path) -> Path:
        """Deep-copy scenario_template and inject scenario-specific values. Called once per scenario.
        The concrete type of `scenario` is pattern-specific."""


# ── ID helper ─────────────────────────────────────────────────────────────────

def _make_ids(task_id: str, task_name: str) -> TransformIds:
    p = f"{task_id}_auto"
    return TransformIds(
        task_id=task_id,              task_name=task_name,          bot_id=f"{task_id}_bot",
        automation_gate=f"{p}_gw1",  bot_result_gate=f"{p}_gw2",
        fallback_merge=f"{p}_gw3",   final_join_gate=f"{p}_gw4",
        automation_branch=f"{p}_bot_branch", manual_branch=f"{p}_human_branch",
        bot_output=f"{p}_bot_to_gw2",        bot_success=f"{p}_bot_success",
        bot_failure=f"{p}_bot_failure",       to_human=f"{p}_to_human",
        exit_flow=f"{p}_exit",
    )


# ── Pattern layout ────────────────────────────────────────────────────────────

def _xor_bypass_layout(root: ET.Element,
                       ids: TransformIds) -> dict[str, tuple[int, int]]:
    """Return {element_id: (x, y)} top-left corners for the XOR bypass subgraph.

    Places the pattern block in free space below the existing diagram so it
    never overlaps existing elements.  Layout:

        col0          col1           col2              col3
      [auto_gw] ─── [bot_task] ─── [bot_result_gw] ─── [final_join_gw]  ← top lane
                                        │
                                   [fallback_merge]                        ← bottom lane
                                        │
                                   (to_human → original task, above)
    """
    _COL_STEP  = 160   # horizontal distance between column centres
    _V_GAP     = 150   # vertical distance between lane centres
    _Y_MARGIN  = 80    # clear space below existing diagram

    x_min, _, _, y_max = diagram_extents(root)

    cy_top = int(y_max) + _Y_MARGIN + GW_H // 2
    cy_bot = cy_top + _V_GAP
    cols   = [int(x_min) + GW_W // 2 + i * _COL_STEP for i in range(4)]

    def gw_tl(cx: int, cy: int)   -> tuple[int, int]: return (cx - GW_W   // 2, cy - GW_H   // 2)
    def task_tl(cx: int, cy: int) -> tuple[int, int]: return (cx - TASK_W // 2, cy - TASK_H // 2)

    return {
        ids.automation_gate: gw_tl(  cols[0], cy_top),
        ids.bot_id:          task_tl(cols[1], cy_top),
        ids.bot_result_gate: gw_tl(  cols[2], cy_top),
        ids.fallback_merge:  gw_tl(  cols[2], cy_bot),
        ids.final_join_gate: gw_tl(  cols[3], cy_top),
    }


# ============================================================================
# XOR substitution: 4 gateways + 1 bot task (mirrors automation-bypass pattern)
#
#  prev ──(in_flow)──► automation_gate ──automation_branch──► Bot_Task ──bot_output──► bot_result_gate ──bot_success──► final_join_gate ──(exit_flow)──► next
#                            │                                                               └──bot_failure──► fallback_merge
#                            └──manual_branch─────────────────────────────────────────────────────────────► fallback_merge
#                                                                                                                  └──to_human──► Task ──(out_flow)──► final_join_gate
# ============================================================================

class XORSplitAutomation(Transformation):
    id = "xor_split_automation"
    label = "XOR split: automated / manual with OK-fallback"

    # --- parameters ----------------------------------------------------------
    def parameters(self, target_activity: str,
                   current_duration_s: float | None = None,
                   selected_resource_id: str | None = None,
                   frozen_pool_size: int | None = None) -> list[Parameter]:
        t = float(current_duration_s) if current_duration_s else DEFAULT_MANUAL_DURATION_S
        a = target_activity
        pool_frozen = frozen_pool_size is not None
        pool_levels = [frozen_pool_size] * 3 if pool_frozen else list(NUM_MANUAL_LEVELS)
        return [
            Parameter(f"{a}.pct_auto", f"{a}: % automated (Auto)",
                      levels=list(PCT_AUTO_LEVELS), kind="percentage"),
            Parameter(f"{a}.pct_ok",   f"{a}: % auto-success (OK)",
                      levels=list(PCT_OK_LEVELS), kind="percentage"),
            Parameter(f"{a}.t_auto",   f"{a}: Auto-Time mean (s)",
                      levels=[round(t * f, 1) for f in T_AUTO_FRACTIONS],
                      kind="duration_s"),
            Parameter(f"{a}.t_manual", f"{a}: Non-auto-Time mean (s) [from Simod]",
                      levels=[round(t * f, 1) for f in T_MANUAL_FACTORS],
                      kind="duration_s"),
            Parameter(f"{a}.num_bots", "Bot pool size",
                      levels=list(NUM_BOTS_LEVELS), kind="categorical"),
            Parameter(f"{a}.num_manual_resources", "Human pool size",
                      levels=pool_levels, kind="categorical", frozen=pool_frozen),
            Parameter(f"{a}.num_cases", "Cases per replication",
                      levels=list(NUM_CASES_LEVELS), kind="categorical"),
        ]

    # --- apply_pattern -------------------------------------------------------
    def apply_pattern(self, bpmn_in: Path, target_activity: str,
                      out_dir: Path) -> tuple[Path, TransformIds]:
        """Add the XOR bypass pattern to the BPMN and write to out_dir."""
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

        T_id   = task.get("id", "")
        T_name = task.get("name", "")

        incoming = flows_targeting(process, T_id)
        outgoing = flows_from(process, T_id)
        if len(incoming) != 1 or len(outgoing) != 1:
            raise NotImplementedError(
                f"{target_activity}: expected 1 incoming + 1 outgoing flow, "
                f"got {len(incoming)} + {len(outgoing)}. "
                "Pattern doesn't yet handle tasks fed by gateways directly."
            )

        ids = _make_ids(T_id, T_name)
        in_flow_id       = incoming[0].get("id", "")
        out_flow_id      = outgoing[0].get("id", "")
        original_next_id = outgoing[0].get("targetRef", "")

        # 1. Add all new elements in free space below the existing diagram.
        lo = _xor_bypass_layout(root, ids)
        add_task_el(root, process, ids.bot_id,          f"Auto {T_name}", *lo[ids.bot_id])
        add_xor_el (root, process, ids.automation_gate, GW1_NAME,         *lo[ids.automation_gate])
        add_xor_el (root, process, ids.bot_result_gate, GW2_NAME,         *lo[ids.bot_result_gate])
        add_xor_el (root, process, ids.fallback_merge,  GW3_NAME,         *lo[ids.fallback_merge])
        add_xor_el (root, process, ids.final_join_gate, GW4_NAME,         *lo[ids.final_join_gate])

        # 2. Redirect boundary flows.
        # out_flow already originates from the original task, so we reuse it as
        # the human-exit arc (task → final_join_gate) rather than adding a new flow.
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
        return bpmn_out, ids

    # --- build_scenario_template ---------------------------------------------
    def build_scenario_template(self, json_in: Path, ids: TransformIds) -> dict:
        """Load the Prosimos JSON and inject bot resource infrastructure.
        Durations and gateway probabilities are scenario-specific — added in apply_params."""
        data = json.loads(Path(json_in).read_text())
        if not any(e.get("task_id") == ids.task_id
                   for e in data.get(KEY_TASK_RESOURCE_DISTRIBUTION, [])):
            raise RuntimeError(
                f"No task_resource_distribution entry for {ids.task_id} in {json_in}"
            )

        # 1. Add 24/7 bot calendar if absent.
        ensure_calendar(data, {
            "id":   BOT_CALENDAR_ID,
            "name": BOT_CALENDAR_NAME,
            "time_periods": [{
                "from": BOT_CALENDAR_FROM, "to": BOT_CALENDAR_TO,
                "beginTime": BOT_CALENDAR_BEGIN, "endTime": BOT_CALENDAR_END,
            }],
        })

        # 2. Add bot resource profile if absent; always append this task's resource.
        upsert_resource_in_profile(data, BOT_PROFILE_ID, BOT_PROFILE_NAME, {
            "id":            ids.bot_resource_id,
            "name":          ids.bot_resource_name,
            "cost_per_hour": BOT_COST_PER_HOUR,
            "amount":        BOT_AMOUNT,
            "calendar":      BOT_CALENDAR_ID,
            "assignedTasks": [ids.bot_id],
        })

        # 3. Add bot task distribution entry (duration set per-scenario in apply_params).
        append_task_distribution(data, {
            "task_id":   ids.bot_id,
            "resources": [{
                "resource_id":         ids.bot_resource_id,
                "distribution_name":   BOT_DISTRIBUTION_NAME,
                "distribution_params": [{"value": BOT_DISTRIBUTION_VALUE}],
            }],
        })

        return data

    # --- apply_params --------------------------------------------------------
    def apply_params(self, scenario_template: dict, ids: TransformIds,
                     scenario: AutomationScenario, json_out: Path) -> Path:
        """Inject scenario-specific values into a deep copy of scenario_template.
        Called once per scenario; never mutates scenario_template."""
        data = copy.deepcopy(scenario_template)

        manual_entry = next(
            (e for e in data[KEY_TASK_RESOURCE_DISTRIBUTION] if e["task_id"] == ids.task_id), None
        )
        bot_entry = next(
            (e for e in data[KEY_TASK_RESOURCE_DISTRIBUTION] if e["task_id"] == ids.bot_id), None
        )
        if manual_entry:
            set_uniform(manual_entry, scenario.manual_execution_time)
        if bot_entry:
            set_fixed(bot_entry, scenario.bot_execution_time)

        add_gateway_probs(data, ids.automation_gate, {
            ids.automation_branch: round(scenario.automation_rate, 6),
            ids.manual_branch:     round(scenario.manual_branch_rate, 6),
        })
        add_gateway_probs(data, ids.bot_result_gate, {
            ids.bot_success: round(scenario.bot_success_rate, 6),
            ids.bot_failure: round(scenario.bot_failure_rate, 6),
        })
        add_gateway_probs(data, ids.fallback_merge,  {ids.to_human:  1.0})
        add_gateway_probs(data, ids.final_join_gate, {ids.exit_flow: 1.0})

        set_resource_amount(data, ids.bot_resource_id, scenario.num_bots)
        if manual_entry and manual_entry.get("resources") and scenario.selected_resource_id is not None:
            set_resource_amount(data, scenario.selected_resource_id, scenario.num_manual_resources)

        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(data, indent=2))
        return json_out


REGISTRY: dict[str, Transformation] = {
    XORSplitAutomation.id: XORSplitAutomation(),
}
