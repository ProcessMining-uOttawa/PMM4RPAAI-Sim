"""Pluggable BPMN+JSON mutations."""
from __future__ import annotations
import copy, json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from lxml import etree

from .bpmn_utils import (BPMN_NS, NS, _tag, new_id,
                         find_task_by_name, find_flows, task_mean_duration_s)
from .parameters import Parameter


@dataclass
class TransformResult:
    bpmn_path: Path
    json_path: Path


class Transformation(ABC):
    id: str
    label: str

    @abstractmethod
    def parameters(self, target_activity: str,
                   current_duration_s: float | None = None) -> list[Parameter]:
        """Declare factors. `current_duration_s` (Simod mean) prepopulates levels."""

    @abstractmethod
    def apply(self, bpmn_in: Path, json_in: Path, target_activity: str,
              values: dict[str, object], out_dir: Path) -> TransformResult:
        """Produce mutated BPMN + Prosimos JSON for one scenario."""


# ============================================================================
# XOR substitution: 4 gateways + 2 activities.
#
#   ─►(XOR1)─%Auto─►[Auto Act]─►(XOR2)──%OK───────────────────►(XOR4)─►
#         │                         │
#       100-Auto                  100-OK
#         │                         │
#         └────────►(XOR3)◄─────────┘
#                     │
#                     ▼
#                  [Act] (original) ───────────────────────────►(XOR4)
# ============================================================================
class XORSplitAutomation(Transformation):
    id = "xor_split_automation"
    label = "XOR split: automated / manual with OK-fallback"

    # --- parameters ----------------------------------------------------------
    def parameters(self, target_activity: str,
                   current_duration_s: float | None = None) -> list[Parameter]:
        t = float(current_duration_s) if current_duration_s else 1800.0  # 30 min default
        a = target_activity
        return [
            Parameter(f"{a}.pct_auto", f"{a}: % automated (Auto)",
                      levels=[25, 50, 75], kind="percentage"),
            Parameter(f"{a}.pct_ok", f"{a}: % auto-success (OK)",
                      levels=[80, 90, 95], kind="percentage"),
            Parameter(f"{a}.t_auto", f"{a}: Auto-Time mean (s)",
                      levels=[round(t/20, 1), round(t/10, 1), round(t/5, 1)],
                      kind="duration_s"),
            Parameter(f"{a}.t_manual", f"{a}: Non-auto-Time mean (s) [from Simod]",
                      levels=[round(t*0.8, 1), round(t, 1), round(t*1.2, 1)],
                      kind="duration_s"),
        ]

    # --- apply ---------------------------------------------------------------
    def apply(self, bpmn_in: Path, json_in: Path, target_activity: str,
              values: dict, out_dir: Path) -> TransformResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        bpmn_out = out_dir / "model.bpmn"
        json_out = out_dir / "params.json"

        # Look up parameter values irrespective of activity-prefixed keys.
        def _v(suffix: str, default=None):
            for k, v in values.items():
                if k.endswith("." + suffix):
                    return v
            return default
        pct_auto = float(_v("pct_auto", 50)) / 100.0
        pct_ok   = float(_v("pct_ok", 90))   / 100.0
        t_auto   = float(_v("t_auto", 60.0))
        t_man    = float(_v("t_manual", 1800.0))

        # ----- BPMN edit -----------------------------------------------------
        tree = etree.parse(str(bpmn_in))
        task = find_task_by_name(tree, target_activity)
        if task is None:
            raise ValueError(f"Activity {target_activity!r} not found in {bpmn_in}")
        T_id = task.get("id")
        T_name = task.get("name")
        proc = task.getparent()

        incoming, outgoing = find_flows(tree, T_id)
        if len(incoming) != 1 or len(outgoing) != 1:
            raise NotImplementedError(
                f"{target_activity}: expected 1 incoming + 1 outgoing flow, "
                f"got {len(incoming)} + {len(outgoing)}. "
                "Pattern doesn't yet handle tasks fed by gateways directly."
            )
        in_flow, out_flow = incoming[0], outgoing[0]

        # IDs for the new sub-graph
        xor1_id, xor2_id, xor3_id, xor4_id = (new_id() for _ in range(4))
        auto_id = new_id()
        # New sequence flows
        f_xor1_auto  = new_id("flow"); f_xor1_xor3 = new_id("flow")
        f_auto_xor2  = new_id("flow")
        f_xor2_xor4  = new_id("flow"); f_xor2_xor3 = new_id("flow")
        f_xor3_T     = new_id("flow"); f_T_xor4    = new_id("flow")

        # Rewire existing flows
        in_flow.set("targetRef", xor1_id)
        out_flow.set("sourceRef", xor4_id)

        # Build new elements
        def mk(tag, **attrs):
            el = etree.SubElement(proc, _tag(tag), nsmap=None)
            for k, v in attrs.items():
                el.set(k, v)
            return el

        def gateway(gid, direction, in_flows, out_flows):
            gw = mk("exclusiveGateway", id=gid, gatewayDirection=direction, name="")
            for fid in in_flows:
                etree.SubElement(gw, _tag("incoming")).text = fid
            for fid in out_flows:
                etree.SubElement(gw, _tag("outgoing")).text = fid
            return gw

        gateway(xor1_id, "Diverging",
                in_flows=[in_flow.get("id")],
                out_flows=[f_xor1_auto, f_xor1_xor3])
        gateway(xor2_id, "Diverging",
                in_flows=[f_auto_xor2],
                out_flows=[f_xor2_xor4, f_xor2_xor3])
        gateway(xor3_id, "Converging",
                in_flows=[f_xor1_xor3, f_xor2_xor3],
                out_flows=[f_xor3_T])
        gateway(xor4_id, "Converging",
                in_flows=[f_xor2_xor4, f_T_xor4],
                out_flows=[out_flow.get("id")])

        # New automated task (same shape as Simod's tasks)
        auto_task = mk("task", completionQuantity="1", id=auto_id,
                       isForCompensation="false",
                       name=f"Auto {T_name}", startQuantity="1")

        # New sequenceFlows
        def flow(fid, src, tgt):
            mk("sequenceFlow", id=fid, name="", sourceRef=src, targetRef=tgt)
        flow(f_xor1_auto, xor1_id, auto_id)
        flow(f_xor1_xor3, xor1_id, xor3_id)
        flow(f_auto_xor2, auto_id, xor2_id)
        flow(f_xor2_xor4, xor2_id, xor4_id)
        flow(f_xor2_xor3, xor2_id, xor3_id)
        flow(f_xor3_T,    xor3_id, T_id)
        flow(f_T_xor4,    T_id,    xor4_id)

        tree.write(str(bpmn_out), xml_declaration=True, encoding="UTF-8",
                   standalone=False)

        # ----- JSON edit -----------------------------------------------------
        data = json.loads(Path(json_in).read_text())

        # Find the original task entry and clone it for the Auto task.
        manual_entry = None
        for e in data["task_resource_distribution"]:
            if e["task_id"] == T_id:
                manual_entry = e
                break
        if manual_entry is None:
            raise RuntimeError(
                f"No task_resource_distribution entry for {T_id} in {json_in}")

        def set_uniform_around(entry: dict, mean_s: float, jitter: float = 0.05):
            lo = max(0.0, mean_s * (1 - jitter))
            hi = mean_s * (1 + jitter)
            for r in entry["resources"]:
                r["distribution_name"] = "uniform"
                r["distribution_params"] = [{"value": lo}, {"value": hi}]

        # Manual entry: keep id, override duration
        set_uniform_around(manual_entry, t_man)

        # Auto entry: clone resources list, give new task_id, override duration
        auto_entry = copy.deepcopy(manual_entry)
        auto_entry["task_id"] = auto_id
        set_uniform_around(auto_entry, t_auto)
        data["task_resource_distribution"].append(auto_entry)

        # Gateway branching probabilities
        gbp = data.setdefault("gateway_branching_probabilities", [])
        gbp.append({
            "gateway_id": xor1_id,
            "probabilities": [
                {"path_id": f_xor1_auto, "value": pct_auto},
                {"path_id": f_xor1_xor3, "value": round(1 - pct_auto, 6)},
            ],
        })
        gbp.append({
            "gateway_id": xor2_id,
            "probabilities": [
                {"path_id": f_xor2_xor4, "value": pct_ok},
                {"path_id": f_xor2_xor3, "value": round(1 - pct_ok, 6)},
            ],
        })

        Path(json_out).write_text(json.dumps(data, indent=2))
        return TransformResult(bpmn_path=bpmn_out, json_path=json_out)


REGISTRY: dict[str, Transformation] = {
    XORSplitAutomation.id: XORSplitAutomation(),
}
