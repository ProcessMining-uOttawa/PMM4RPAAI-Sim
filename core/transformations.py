"""Pluggable BPMN+JSON mutations — mirrors the automation-bypass pattern."""
from __future__ import annotations
import copy, json
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from .parameters import Parameter

# ── XML namespaces ────────────────────────────────────────────────────────────
_NS = {
    "bpmn":   "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc":     "http://www.omg.org/spec/DD/20100524/DC",
    "di":     "http://www.omg.org/spec/DD/20100524/DI",
}
for _prefix, _uri in _NS.items():
    ET.register_namespace(_prefix, _uri)

_BPMN   = _NS["bpmn"]
_BPMNDI = _NS["bpmndi"]
_DC     = _NS["dc"]
_DI     = _NS["di"]

# ── Shape dimensions ──────────────────────────────────────────────────────────
_TASK_W, _TASK_H = 100, 80
_GW_W,   _GW_H   = 50,  50
_H_GAP           = 50

# ── Task element tags ─────────────────────────────────────────────────────────
_TASK_TAGS = frozenset({
    f"{{{_BPMN}}}task",            f"{{{_BPMN}}}userTask",
    f"{{{_BPMN}}}serviceTask",     f"{{{_BPMN}}}manualTask",
    f"{{{_BPMN}}}businessRuleTask",f"{{{_BPMN}}}scriptTask",
    f"{{{_BPMN}}}sendTask",        f"{{{_BPMN}}}receiveTask",
})


# ── Public dataclasses ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TransformIds:
    """All generated element IDs for one pattern application."""
    task_id:      str
    bot_id:       str
    gw1_id:       str
    gw2_id:       str
    gw3_id:       str
    gw4_id:       str
    f_bot_branch: str
    f_hum_branch: str
    f_bot_to_gw2: str
    f_bot_success: str
    f_bot_failure: str
    f_to_human:   str
    f_exit:       str


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
                     values: dict, json_out: Path) -> Path:
        """Parameter injection: set probabilities + durations. Called once per scenario."""


# ── DI helpers (ported from bpmn_editor/di.py) ───────────────────────────────

def _get_plane(root: ET.Element) -> ET.Element | None:
    return root.find(f".//{{{_BPMNDI}}}BPMNPlane")


def _get_shape_bounds(root: ET.Element, element_id: str) -> dict | None:
    plane = _get_plane(root)
    if plane is None:
        return None
    for shape in plane.findall(f"{{{_BPMNDI}}}BPMNShape"):
        if shape.get("bpmnElement") == element_id:
            b = shape.find(f"{{{_DC}}}Bounds")
            if b is not None:
                return {k: float(b.get(k, 0)) for k in ("x", "y", "width", "height")}
    return None


def _auto_place_after(root: ET.Element, after_id: str, h: int) -> tuple[int, int]:
    src = _get_shape_bounds(root, after_id)
    if src is None:
        return 300, 200
    return (int(src["x"] + src["width"] + _H_GAP),
            int(src["y"] + (src["height"] - h) / 2))


def _auto_place_rightmost(root: ET.Element, h: int) -> tuple[int, int]:
    plane = _get_plane(root)
    if plane is None:
        return 300, 200
    rx, ry, found = 0.0, 0.0, False
    for shape in plane.findall(f"{{{_BPMNDI}}}BPMNShape"):
        b = shape.find(f"{{{_DC}}}Bounds")
        if b is None:
            continue
        sx, sy = float(b.get("x", 0)), float(b.get("y", 0))
        sw, sh = float(b.get("width", 0)), float(b.get("height", 0))
        if not found or sx + sw > rx:
            rx, ry, found = sx + sw, sy + (sh - h) / 2, True
    return (int(rx + _H_GAP), int(ry)) if found else (300, 200)


def _waypoints_between(root: ET.Element, src_id: str, tgt_id: str) -> list[tuple[float, float]]:
    s = _get_shape_bounds(root, src_id)
    t = _get_shape_bounds(root, tgt_id)
    if s and t:
        return [(s["x"] + s["width"], s["y"] + s["height"] / 2),
                (t["x"],              t["y"] + t["height"] / 2)]
    return [(300.0, 120.0), (400.0, 120.0)]


def _add_shape(plane: ET.Element, element_id: str,
               x: int, y: int, w: int, h: int, marker: bool = False) -> None:
    shape = ET.SubElement(plane, f"{{{_BPMNDI}}}BPMNShape")
    shape.set("id", f"{element_id}_di")
    shape.set("bpmnElement", element_id)
    if marker:
        shape.set("isMarkerVisible", "true")
    b = ET.SubElement(shape, f"{{{_DC}}}Bounds")
    b.set("x", str(x)); b.set("y", str(y))
    b.set("width", str(w)); b.set("height", str(h))
    ET.SubElement(shape, f"{{{_BPMNDI}}}BPMNLabel")


def _add_edge(plane: ET.Element, flow_id: str, pts: list[tuple[float, float]]) -> None:
    edge = ET.SubElement(plane, f"{{{_BPMNDI}}}BPMNEdge")
    edge.set("id", f"{flow_id}_di")
    edge.set("bpmnElement", flow_id)
    for wx, wy in pts:
        wp = ET.SubElement(edge, f"{{{_DI}}}waypoint")
        wp.set("x", str(int(wx))); wp.set("y", str(int(wy)))


# ── Process helpers (ported from bpmn_editor/operations.py) ──────────────────

def _find_process(root: ET.Element) -> ET.Element | None:
    return root.find(f".//{{{_BPMN}}}process")


def _find_task_by_name(process: ET.Element, name: str) -> ET.Element | None:
    for el in process:
        if el.tag in _TASK_TAGS and el.get("name") == name:
            return el
    return None


def _flows_targeting(process: ET.Element, target_id: str) -> list[ET.Element]:
    tag = f"{{{_BPMN}}}sequenceFlow"
    return [el for el in process if el.tag == tag and el.get("targetRef") == target_id]


def _flows_from(process: ET.Element, source_id: str) -> list[ET.Element]:
    tag = f"{{{_BPMN}}}sequenceFlow"
    return [el for el in process if el.tag == tag and el.get("sourceRef") == source_id]


def _add_task_el(root: ET.Element, process: ET.Element,
                 task_id: str, name: str, after_id: str | None = None) -> None:
    el = ET.SubElement(process, f"{{{_BPMN}}}task")
    el.set("id", task_id); el.set("name", name)
    plane = _get_plane(root)
    if plane is not None:
        x, y = (_auto_place_after(root, after_id, _TASK_H)
                if after_id else _auto_place_rightmost(root, _TASK_H))
        _add_shape(plane, task_id, x, y, _TASK_W, _TASK_H)


def _add_xor_el(root: ET.Element, process: ET.Element,
                gw_id: str, name: str = "", after_id: str | None = None) -> None:
    el = ET.SubElement(process, f"{{{_BPMN}}}exclusiveGateway")
    el.set("id", gw_id)
    if name:
        el.set("name", name)
    plane = _get_plane(root)
    if plane is not None:
        x, y = (_auto_place_after(root, after_id, _GW_H)
                if after_id else _auto_place_rightmost(root, _GW_H))
        _add_shape(plane, gw_id, x, y, _GW_W, _GW_H, marker=True)


def _add_flow_el(root: ET.Element, process: ET.Element,
                 flow_id: str, src: str, tgt: str, name: str = "") -> None:
    flow = ET.SubElement(process, f"{{{_BPMN}}}sequenceFlow")
    flow.set("id", flow_id); flow.set("sourceRef", src); flow.set("targetRef", tgt)
    if name:
        flow.set("name", name)
    plane = _get_plane(root)
    if plane is not None:
        _add_edge(plane, flow_id, _waypoints_between(root, src, tgt))


def _update_flow_target(root: ET.Element, process: ET.Element,
                        flow_id: str, new_target: str) -> None:
    tag = f"{{{_BPMN}}}sequenceFlow"
    flow = next((el for el in process if el.tag == tag and el.get("id") == flow_id), None)
    if flow is None:
        raise ValueError(f"sequenceFlow '{flow_id}' not found")
    src = flow.get("sourceRef", "")
    flow.set("targetRef", new_target)
    plane = _get_plane(root)
    if plane is not None:
        edge = next((e for e in plane.findall(f"{{{_BPMNDI}}}BPMNEdge")
                     if e.get("bpmnElement") == flow_id), None)
        if edge is not None:
            wp_tag = f"{{{_DI}}}waypoint"
            for wp in edge.findall(wp_tag):
                edge.remove(wp)
            for wx, wy in _waypoints_between(root, src, new_target):
                wp = ET.SubElement(edge, wp_tag)
                wp.set("x", str(int(wx))); wp.set("y", str(int(wy)))


# ── ID helper ─────────────────────────────────────────────────────────────────

def _make_ids(task_id: str) -> TransformIds:
    p = f"{task_id}_auto"
    return TransformIds(
        task_id=task_id,      bot_id=f"{task_id}_bot",
        gw1_id=f"{p}_gw1",   gw2_id=f"{p}_gw2",
        gw3_id=f"{p}_gw3",   gw4_id=f"{p}_gw4",
        f_bot_branch=f"{p}_bot_branch",  f_hum_branch=f"{p}_human_branch",
        f_bot_to_gw2=f"{p}_bot_to_gw2", f_bot_success=f"{p}_bot_success",
        f_bot_failure=f"{p}_bot_failure",f_to_human=f"{p}_to_human",
        f_exit=f"{p}_exit",
    )


# ============================================================================
# XOR substitution: 4 gateways + 1 bot task (mirrors automation-bypass pattern)
#
#  prev ──(in_flow → gw1)──► GW1 ──bot──► Bot_Task ──► GW2 ──success──► GW4 ──(exit)──► next
#                              │                           └──failure──► GW3
#                              └──human────────────────────────────────► GW3
#                                                                         └──to_human──► Task ──(out_flow → gw4)──► GW4
# ============================================================================

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
        process = _find_process(root)
        if process is None:
            raise ValueError(f"No <bpmn:process> found in {bpmn_in}")

        task = _find_task_by_name(process, target_activity)
        if task is None:
            raise ValueError(f"Activity {target_activity!r} not found in {bpmn_in}")

        T_id   = task.get("id")
        T_name = task.get("name")

        incoming = _flows_targeting(process, T_id)
        outgoing = _flows_from(process, T_id)
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
        _add_task_el(root, process, ids.bot_id,  f"Auto {T_name}", after_id=T_id)
        _add_xor_el (root, process, ids.gw1_id, "Bot or Human?",  after_id=T_id)
        _add_xor_el (root, process, ids.gw2_id, "Bot succeeded?", after_id=ids.bot_id)
        _add_xor_el (root, process, ids.gw3_id, "Human needed",   after_id=ids.gw2_id)
        _add_xor_el (root, process, ids.gw4_id, "Exit",           after_id=ids.gw3_id)

        # 2. Redirect boundary flows
        _update_flow_target(root, process, in_flow_id,  ids.gw1_id)
        _update_flow_target(root, process, out_flow_id, ids.gw4_id)

        # 3. Wire the seven internal flows
        _add_flow_el(root, process, ids.f_bot_branch,  ids.gw1_id,  ids.bot_id,        name="bot")
        _add_flow_el(root, process, ids.f_hum_branch,  ids.gw1_id,  ids.gw3_id,        name="human")
        _add_flow_el(root, process, ids.f_bot_to_gw2,  ids.bot_id,  ids.gw2_id)
        _add_flow_el(root, process, ids.f_bot_success, ids.gw2_id,  ids.gw4_id,        name="success")
        _add_flow_el(root, process, ids.f_bot_failure, ids.gw2_id,  ids.gw3_id,        name="failure")
        _add_flow_el(root, process, ids.f_to_human,    ids.gw3_id,  T_id)
        _add_flow_el(root, process, ids.f_exit,        ids.gw4_id,  original_next_id)

        tree.write(str(bpmn_out), xml_declaration=True, encoding="utf-8")

        # Build base JSON: load original and add the bot task entry (structural).
        # Durations and gateway probs are scenario-specific — added in apply_params.
        data = json.loads(Path(json_in).read_text())
        manual_entry = next(
            (e for e in data.get("task_resource_distribution", [])
             if e.get("task_id") == T_id), None
        )
        if manual_entry is None:
            raise RuntimeError(
                f"No task_resource_distribution entry for {T_id} in {json_in}"
            )
        bot_entry = copy.deepcopy(manual_entry)
        bot_entry["task_id"] = ids.bot_id
        data["task_resource_distribution"].append(bot_entry)

        return BpmnTransformResult(bpmn_path=bpmn_out, base_json=data, ids=ids)

    # --- apply_params --------------------------------------------------------
    def apply_params(self, base_json: dict, ids: TransformIds,
                     values: dict, json_out: Path) -> Path:
        """Inject scenario-specific durations and gateway probabilities.
        Called once per scenario; deep-copies base_json so it is never mutated."""
        def _v(suffix, default=None):
            for k, v in values.items():
                if k.endswith("." + suffix):
                    return v
            return default

        pct_auto = float(_v("pct_auto", 50)) / 100.0
        pct_ok   = float(_v("pct_ok",   90)) / 100.0
        t_auto   = float(_v("t_auto",   60.0))
        t_man    = float(_v("t_manual", 1800.0))

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
            _set_uniform(manual_entry, t_man)
        if bot_entry:
            _set_uniform(bot_entry, t_auto)

        gbp = data.setdefault("gateway_branching_probabilities", [])
        gbp.append({"gateway_id": ids.gw1_id, "probabilities": [
            {"path_id": ids.f_bot_branch,  "value": round(pct_auto, 6)},
            {"path_id": ids.f_hum_branch,  "value": round(1.0 - pct_auto, 6)},
        ]})
        gbp.append({"gateway_id": ids.gw2_id, "probabilities": [
            {"path_id": ids.f_bot_success, "value": round(pct_ok, 6)},
            {"path_id": ids.f_bot_failure, "value": round(1.0 - pct_ok, 6)},
        ]})
        gbp.append({"gateway_id": ids.gw3_id, "probabilities": [
            {"path_id": ids.f_to_human, "value": 1.0},
        ]})
        gbp.append({"gateway_id": ids.gw4_id, "probabilities": [
            {"path_id": ids.f_exit, "value": 1.0},
        ]})

        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(data, indent=2))
        return json_out


REGISTRY: dict[str, Transformation] = {
    XORSplitAutomation.id: XORSplitAutomation(),
}
