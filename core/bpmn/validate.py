"""Independent structural + topology verifier for the XORSplitAutomation fragment.

Maintainer-facing *trust* sub-tool: given a **transformed** BPMN and the target
activity name, confirm the XORSplitAutomation fragment (4 exclusive gateways + a
bot task + the branch wiring) is actually present and correctly wired at the
executable (sequenceFlow sourceRef/targetRef) level — not merely
connected-*looking* in the diagram. Run it, don't wire it into the app:

    python -m core.bpmn.validate <transformed.bpmn> --target "Fix Bug"
    python -m core.bpmn.validate <transformed.bpmn> --target "Fix Bug" \\
        --behavioral --params <transformed_params.json>

Structural mode is pure-stdlib and needs no venv. `--behavioral` runs a small
Prosimos simulation and checks that observed routing proportions match the
configured branch probabilities; it imports pandas + the Prosimos runner lazily.

INDEPENDENCE CONTRACT (load-bearing — this is a *verifier*):
    This module MUST NOT import core.bpmn.query's flow helpers
    (flows_from / flows_targeting) or anything from core.transformations. A
    verifier that reuses the code-under-test's traversal or its name constants
    proves nothing — a rename or a traversal bug there would silently update
    the oracle's expectations in lockstep. Expected element names, topology,
    and BPMN format constants are RE-ENCODED here as an independent oracle
    (the sentinel-literal precedent, one level up). The verifier builds its own
    adjacency from raw sourceRef/targetRef and anchors on the caller-supplied
    target name, walking the fragment outward by element type + edge degree.

Severity tiers:
    ERROR  = executability (what Prosimos routes on): no dangling refs + the
             exact expected sequenceFlow topology.
    WARNING = representation drift Prosimos ignores: <incoming>/<outgoing> child
              lists that contradict the edges (the transform never maintains
              these — see the §8 known-bug note), and diagram-edge consistency.
"""

from __future__ import annotations

import argparse
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# ── Re-declared BPMN format facts (see INDEPENDENCE CONTRACT) ──────────────────
# These are format invariants, not transform decisions; re-declared locally so
# structural mode is provably hermetic (pure stdlib, no core imports).
_BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
_BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
_TASK_LOCALNAMES = frozenset(
    {
        "task",
        "userTask",
        "serviceTask",
        "manualTask",
        "businessRuleTask",
        "scriptTask",
        "sendTask",
        "receiveTask",
    }
)
_GATEWAY_LOCALNAME = "exclusiveGateway"
_SEQFLOW_LOCALNAME = "sequenceFlow"

# ── Re-encoded pattern fact (see INDEPENDENCE CONTRACT) ───────────────────────
# The bot task is named "Auto " + <target>. Re-encoded, NOT imported from
# transformations.py — a rename there must surface as a loud Layer-2 failure.
_BOT_NAME_PREFIX = "Auto "


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Violation:
    """One structural problem. `code` is a stable machine key; tests assert on it
    (never on `message`, whose wording may change)."""

    code: str
    severity: Severity
    message: str
    element_id: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    target_activity: str
    violations: tuple[Violation, ...]

    @property
    def errors(self) -> tuple[Violation, ...]:
        return tuple(
            violation
            for violation in self.violations
            if violation.severity is Severity.ERROR
        )

    @property
    def warnings(self) -> tuple[Violation, ...]:
        return tuple(
            violation
            for violation in self.violations
            if violation.severity is Severity.WARNING
        )

    @property
    def ok(self) -> bool:
        """True when no ERROR-severity violation was found (warnings allowed)."""
        return not self.errors


# ── Adjacency (built from raw refs — independent of query.py) ─────────────────


@dataclass(frozen=True)
class _Edge:
    flow_id: str
    src: str
    tgt: str


class _Graph:
    """Own adjacency over a <process>'s sequenceFlows and its addressable nodes.

    Deliberately re-implements what query.flows_from/flows_targeting do — the
    oracle must not share the transform's traversal (INDEPENDENCE CONTRACT).
    """

    def __init__(self, process: ET.Element) -> None:
        self.node_by_id: dict[str, ET.Element] = {}
        self.edges: list[_Edge] = []
        self._out: dict[str, list[_Edge]] = {}
        self._in: dict[str, list[_Edge]] = {}
        for el in process:
            if _localname(el.tag) == _SEQFLOW_LOCALNAME:
                edge = _Edge(
                    el.get("id", ""), el.get("sourceRef", ""), el.get("targetRef", "")
                )
                self.edges.append(edge)
                self._out.setdefault(edge.src, []).append(edge)
                self._in.setdefault(edge.tgt, []).append(edge)
            else:
                node_id = el.get("id")
                if node_id is not None:
                    self.node_by_id[node_id] = el

    def out_edges(self, node_id: str) -> list[_Edge]:
        return self._out.get(node_id, [])

    def in_edges(self, node_id: str) -> list[_Edge]:
        return self._in.get(node_id, [])

    def is_gateway(self, node_id: str) -> bool:
        el = self.node_by_id.get(node_id)
        return el is not None and _localname(el.tag) == _GATEWAY_LOCALNAME

    def is_task(self, node_id: str) -> bool:
        el = self.node_by_id.get(node_id)
        return el is not None and _localname(el.tag) in _TASK_LOCALNAMES


@dataclass(frozen=True)
class _Fragment:
    """The gateway/flow ids behavioral mode needs to read the configured branch
    probabilities and match the bot task in the event log. Only what is consumed
    is kept — the resolver validates the whole fragment but records just these."""

    gw_split_auto: str  # XOR1 — bot-vs-human split (pct_auto lives here)
    gw_split_result: str  # XOR2 — bot success-vs-failure split (pct_ok lives here)
    bot_branch_flow: str  # XOR1 -> bot  (the path_id scored by pct_auto)
    bot_success_flow: str  # XOR2 -> XOR4 (the path_id scored by pct_ok)
    bot_name: str  # "Auto <target>" — the activity name to match in the log


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_task_by_name(graph: _Graph, name: str) -> str | None:
    for node_id, el in graph.node_by_id.items():
        if graph.is_task(node_id) and el.get("name") == name:
            return node_id
    return None


# ── Structural checks ─────────────────────────────────────────────────────────


def _check_dangling(graph: _Graph) -> list[Violation]:
    """ERROR: every flow endpoint must resolve to a real node (executability)."""
    violations: list[Violation] = []
    for edge in graph.edges:
        if edge.src not in graph.node_by_id:
            violations.append(
                Violation(
                    "DANGLING_SOURCE_REF",
                    Severity.ERROR,
                    f"sequenceFlow '{edge.flow_id}' sourceRef '{edge.src}' resolves to no element.",
                    edge.flow_id,
                )
            )
        if edge.tgt not in graph.node_by_id:
            violations.append(
                Violation(
                    "DANGLING_TARGET_REF",
                    Severity.ERROR,
                    f"sequenceFlow '{edge.flow_id}' targetRef '{edge.tgt}' resolves to no element.",
                    edge.flow_id,
                )
            )
    return violations


def _resolve_fragment(
    graph: _Graph, target_name: str
) -> tuple[_Fragment | None, list[Violation]]:
    """Anchor on the target task and walk the fragment outward by type + degree.

    Returns (fragment, violations). A fatal structural break stops the walk and
    returns (None, [...]); a non-fatal one (a mis-named-but-topologically-sound
    bot task) still resolves the fragment while recording the ERROR.
    """
    violations: list[Violation] = []

    def err(code: str, message: str, element_id: str | None = None) -> None:
        violations.append(Violation(code, Severity.ERROR, message, element_id))

    target_id = _find_task_by_name(graph, target_name)
    if target_id is None:
        err("TARGET_NOT_FOUND", f"No task named {target_name!r} in the process.")
        return None, violations

    target_in, target_out = graph.in_edges(target_id), graph.out_edges(target_id)
    if len(target_in) != 1 or len(target_out) != 1:
        err(
            "TARGET_DEGREE",
            f"Target {target_name!r} must have exactly 1 incoming and 1 outgoing "
            f"flow; found {len(target_in)} in / {len(target_out)} out.",
            target_id,
        )
        return None, violations

    fallback_merge, exit_merge = (
        target_in[0].src,
        target_out[0].tgt,
    )  # fallback-merge (feeds T), exit-merge
    if not graph.is_gateway(fallback_merge):
        err(
            "MISSING_GATEWAY",
            f"Expected an exclusive gateway feeding {target_name!r}; "
            f"'{fallback_merge}' is missing or not a gateway.",
            fallback_merge,
        )
        return None, violations
    if not graph.is_gateway(exit_merge):
        err(
            "MISSING_GATEWAY",
            f"Expected an exclusive gateway after {target_name!r}; "
            f"'{exit_merge}' is missing or not a gateway.",
            exit_merge,
        )
        return None, violations

    # XOR4 (exit merge): 2 in / 1 out; one in-source is the target, the other XOR2.
    exit_merge_in, exit_merge_out = (
        graph.in_edges(exit_merge),
        graph.out_edges(exit_merge),
    )
    if len(exit_merge_in) != 2 or len(exit_merge_out) != 1:
        err(
            "GATEWAY_DEGREE",
            f"Exit merge gateway '{exit_merge}' must have 2 incoming / 1 outgoing; "
            f"found {len(exit_merge_in)} / {len(exit_merge_out)}.",
            exit_merge,
        )
        return None, violations
    others = [edge.src for edge in exit_merge_in if edge.src != target_id]
    if len(others) != 1:
        err(
            "WIRING_MISMATCH",
            f"Exit merge '{exit_merge}' must be fed by the target and one other gateway.",
            exit_merge,
        )
        return None, violations
    result_split = others[0]
    if not graph.is_gateway(result_split):
        err(
            "MISSING_GATEWAY",
            f"Expected the bot-result gateway feeding the exit merge; "
            f"'{result_split}' is missing or not a gateway.",
            result_split,
        )
        return None, violations

    # XOR2 (bot-result split): 1 in / 2 out to exactly {exit-merge, fallback-merge}.
    result_split_in, result_split_out = (
        graph.in_edges(result_split),
        graph.out_edges(result_split),
    )
    if len(result_split_in) != 1 or len(result_split_out) != 2:
        err(
            "GATEWAY_DEGREE",
            f"Bot-result gateway '{result_split}' must have 1 incoming / 2 outgoing; "
            f"found {len(result_split_in)} / {len(result_split_out)}.",
            result_split,
        )
        return None, violations
    if {e.tgt for e in result_split_out} != {exit_merge, fallback_merge}:
        err(
            "WIRING_MISMATCH",
            f"Bot-result gateway '{result_split}' must branch to the exit merge and the "
            f"fallback merge.",
            result_split,
        )
        return None, violations
    bot_success_flow = next(e.flow_id for e in result_split_out if e.tgt == exit_merge)

    # Bot task: feeds XOR2, named "Auto " + target.
    bot = result_split_in[0].src
    if not graph.is_task(bot):
        err(
            "MISSING_BOT_TASK",
            f"Expected a bot task feeding the bot-result gateway; "
            f"'{bot}' is missing or not a task.",
            bot,
        )
        return None, violations
    bot_name = graph.node_by_id[bot].get("name", "")
    if bot_name != _BOT_NAME_PREFIX + target_name:
        # Non-fatal: topology is intact, only the label is wrong. Record and go on.
        err(
            "BOT_TASK_NAME",
            f"Bot task should be named {_BOT_NAME_PREFIX + target_name!r}; "
            f"found {bot_name!r}.",
            bot,
        )
    bot_in, bot_out = graph.in_edges(bot), graph.out_edges(bot)
    if len(bot_in) != 1 or len(bot_out) != 1:
        err(
            "BOT_TASK_DEGREE",
            f"Bot task '{bot}' must have 1 incoming / 1 outgoing; "
            f"found {len(bot_in)} / {len(bot_out)}.",
            bot,
        )
        return None, violations

    # XOR1 (automation split): 1 in / 2 out to exactly {bot, fallback-merge}.
    auto_split = bot_in[0].src
    if not graph.is_gateway(auto_split):
        err(
            "MISSING_GATEWAY",
            f"Expected the automation split gateway feeding the bot task; "
            f"'{auto_split}' is missing or not a gateway.",
            auto_split,
        )
        return None, violations
    auto_split_in, auto_split_out = (
        graph.in_edges(auto_split),
        graph.out_edges(auto_split),
    )
    if len(auto_split_in) != 1 or len(auto_split_out) != 2:
        err(
            "GATEWAY_DEGREE",
            f"Automation split gateway '{auto_split}' must have 1 incoming / 2 outgoing; "
            f"found {len(auto_split_in)} / {len(auto_split_out)}.",
            auto_split,
        )
        return None, violations
    if {e.tgt for e in auto_split_out} != {bot, fallback_merge}:
        err(
            "WIRING_MISMATCH",
            f"Automation split '{auto_split}' must branch to the bot task and the "
            f"fallback merge.",
            auto_split,
        )
        return None, violations
    bot_branch_flow = next(e.flow_id for e in auto_split_out if e.tgt == bot)

    # XOR3 (fallback merge): 2 in from exactly {XOR1, XOR2}, 1 out to the target.
    fallback_merge_in, fallback_merge_out = (
        graph.in_edges(fallback_merge),
        graph.out_edges(fallback_merge),
    )
    if len(fallback_merge_in) != 2 or len(fallback_merge_out) != 1:
        err(
            "GATEWAY_DEGREE",
            f"Fallback merge gateway '{fallback_merge}' must have 2 incoming / 1 outgoing; "
            f"found {len(fallback_merge_in)} / {len(fallback_merge_out)}.",
            fallback_merge,
        )
        return None, violations
    if fallback_merge_out[0].tgt != target_id:
        err(
            "WIRING_MISMATCH",
            f"Fallback merge '{fallback_merge}' must lead to the target task {target_name!r}.",
            fallback_merge,
        )
        return None, violations
    if {e.src for e in fallback_merge_in} != {auto_split, result_split}:
        err(
            "WIRING_MISMATCH",
            f"Fallback merge '{fallback_merge}' must be fed by the automation split and the "
            f"bot-result gateway.",
            fallback_merge,
        )
        return None, violations

    fragment = _Fragment(
        gw_split_auto=auto_split,
        gw_split_result=result_split,
        bot_branch_flow=bot_branch_flow,
        bot_success_flow=bot_success_flow,
        bot_name=bot_name,
    )
    return fragment, violations


def _check_io_lists(graph: _Graph) -> list[Violation]:
    """WARNING: a *declared* <incoming>/<outgoing> child must not contradict the
    edges. Missing entries are NOT flagged — the transform legitimately omits
    them (see the §8 known-bug note); only lies are surfaced."""
    violations: list[Violation] = []
    edge_by_flow = {e.flow_id: e for e in graph.edges}
    for node_id, el in graph.node_by_id.items():
        for child in el:
            local_name = _localname(child.tag)
            if local_name not in ("incoming", "outgoing"):
                continue
            flow_id = (child.text or "").strip()
            edge = edge_by_flow.get(flow_id)
            if edge is None:
                violations.append(
                    Violation(
                        "IO_LIST_DRIFT",
                        Severity.WARNING,
                        f"Element '{node_id}' lists {local_name} flow '{flow_id}' that "
                        f"does not exist.",
                        node_id,
                    )
                )
            elif local_name == "incoming" and edge.tgt != node_id:
                violations.append(
                    Violation(
                        "IO_LIST_DRIFT",
                        Severity.WARNING,
                        f"Element '{node_id}' lists incoming flow '{flow_id}', but "
                        f"that flow targets '{edge.tgt}'.",
                        node_id,
                    )
                )
            elif local_name == "outgoing" and edge.src != node_id:
                violations.append(
                    Violation(
                        "IO_LIST_DRIFT",
                        Severity.WARNING,
                        f"Element '{node_id}' lists outgoing flow '{flow_id}', but "
                        f"that flow originates from '{edge.src}'.",
                        node_id,
                    )
                )
    return violations


def _check_di(root: ET.Element, graph: _Graph) -> list[Violation]:
    """WARNING: diagram edges vs sequence flows — the literal 'looks connected in
    the preview but isn't wired' surface. A flow with no BPMNEdge won't render; a
    BPMNEdge for a non-flow is stale."""
    violations: list[Violation] = []
    plane = root.find(f".//{{{_BPMNDI_NS}}}BPMNPlane")
    flow_ids = {e.flow_id for e in graph.edges}
    di_flow_ids: set[str] = set()
    if plane is not None:
        for edge in plane.findall(f"{{{_BPMNDI_NS}}}BPMNEdge"):
            bpmn_element = edge.get("bpmnElement", "")
            di_flow_ids.add(bpmn_element)
            if bpmn_element not in flow_ids:
                violations.append(
                    Violation(
                        "DI_EDGE_DANGLING",
                        Severity.WARNING,
                        f"BPMNEdge references bpmnElement '{bpmn_element}' that is not "
                        f"a sequenceFlow.",
                        bpmn_element,
                    )
                )
    for flow_id in flow_ids:
        if flow_id not in di_flow_ids:
            violations.append(
                Violation(
                    "DI_EDGE_MISSING",
                    Severity.WARNING,
                    f"sequenceFlow '{flow_id}' has no BPMNEdge in the diagram.",
                    flow_id,
                )
            )
    return violations


def verify_fragment(bpmn_path: Path | str, target_activity: str) -> VerificationResult:
    """Verify the XORSplitAutomation fragment for `target_activity` in a BPMN.

    Runs all four checks in one pass, so a maintainer sees every dangling ref,
    list-drift, and diagram issue at once. The fragment-topology walk is the one
    exception: it anchors on the target and stops at the first fatal structural
    break (it cannot meaningfully continue past a broken anchor), reporting that
    break plus any non-fatal naming issue found before it. See the module
    docstring for the ERROR/WARNING tiering.
    """
    try:
        root = ET.parse(str(bpmn_path)).getroot()
    except (ET.ParseError, OSError) as exc:
        return VerificationResult(
            target_activity,
            (Violation("PARSE_ERROR", Severity.ERROR, f"Could not read BPMN: {exc}"),),
        )
    process = root.find(f".//{{{_BPMN_NS}}}process")
    if process is None:
        return VerificationResult(
            target_activity,
            (Violation("NO_PROCESS", Severity.ERROR, "No <process> element found."),),
        )

    graph = _Graph(process)
    violations: list[Violation] = []
    violations += _check_dangling(graph)
    _fragment, fragment_violations = _resolve_fragment(graph, target_activity)
    violations += fragment_violations
    violations += _check_io_lists(graph)
    violations += _check_di(root, graph)
    return VerificationResult(target_activity, tuple(violations))


# ── Behavioral mode (opt-in; needs the Prosimos venv) ─────────────────────────


@dataclass(frozen=True)
class BehavioralCheck:
    label: str
    expected: float
    observed: float
    # conditional cases the observation is drawn from (see behavioral_report)
    n_eff: int
    tolerance_floor: float = 0.05
    sigma: float = 4.0

    @property
    def tolerance(self) -> float:
        """Sample-size-aware band: max(floor, sigma·SE), SE = sqrt(p(1-p)/n_eff).

        Stays ~floor when the split is well-sampled and widens when the
        conditional population is small (a rare fragment / minority branch), so a
        real miswire (tens of pp off) fails while sampling noise passes. n_eff==0
        means the split was never exercised — nothing to test, so accept.
        """
        if self.n_eff <= 0:
            return 1.0
        std_error = (self.expected * (1.0 - self.expected) / self.n_eff) ** 0.5
        return max(self.tolerance_floor, self.sigma * std_error)

    @property
    def ok(self) -> bool:
        return abs(self.expected - self.observed) <= self.tolerance


@dataclass(frozen=True)
class BehavioralResult:
    n_cases: int
    checks: tuple[BehavioralCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


def _configured_probability(
    params: dict, gateway_id: str, path_flow: str
) -> float | None:
    """Read one path's branching probability out of a Prosimos params JSON.

    Independent of the transform: gateway_id / path_flow come from the fragment
    the oracle resolved off the BPMN, then are looked up in the JSON — so a
    BPMN<->JSON id mismatch surfaces as a missing probability (a real finding).
    """
    for entry in params.get("gateway_branching_probabilities", []):
        if entry.get("gateway_id") == gateway_id:
            for prob in entry.get("probabilities", []):
                if prob.get("path_id") == path_flow:
                    try:
                        value = float(prob.get("value"))
                    except (TypeError, ValueError):
                        # A null/garbage value is itself a JSON<->BPMN mismatch;
                        # surface it as "missing" so the caller raises cleanly.
                        return None
                    # A non-finite or out-of-[0,1] probability is malformed too;
                    # treat it as missing so it never reaches the SE/tolerance math.
                    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                        return None
                    return value
    return None


def _observed_proportions(
    bot_cases: set, human_cases: set
) -> tuple[float, float, int, int]:
    """Conditional routing proportions from the event-log case-id sets.

    A gateway's branch probability is conditional on REACHING it, so the
    denominators are conditional, NOT the whole simulated population:
      - pct_auto = bot / (bot ∪ human)   -- of cases that entered the fragment
      - pct_ok   = 1 - (bot ∩ human) / bot -- of cases that took the bot branch
    (bot = cases with the "Auto X" task; human = cases with the original "X" —
    a case that reached the fragment shows one or both; bot∩human = bot failed
    then a human redid it.) Returns (pct_auto, pct_ok, n_reached, n_bot) so the
    caller can size each check's tolerance to its real conditional sample.
    """
    reached = bot_cases | human_cases
    failures = bot_cases & human_cases
    pct_auto = len(bot_cases) / len(reached) if reached else 0.0
    pct_ok = 1.0 - (len(failures) / len(bot_cases)) if bot_cases else 0.0
    return pct_auto, pct_ok, len(reached), len(bot_cases)


def behavioral_report(
    bpmn_path: Path | str,
    params_path: Path | str,
    target_activity: str,
    n_cases: int = 2000,
    tolerance_floor: float = 0.05,
    sigma: float = 4.0,
) -> BehavioralResult:
    """Simulate the transformed (BPMN, JSON) pair and check routing proportions.

    Expected proportions come from the params JSON's configured branch
    probabilities; observed ones from the Prosimos event log. Both are
    CONDITIONAL on reaching the fragment — the target activity may sit on a
    conditional path, so not every simulated case enters the automation split
    (see _observed_proportions). Each check's tolerance is sample-size-aware
    (see BehavioralCheck.tolerance): tight when the fragment is common, wider
    when it is rare, so real miswires fail while sampling noise passes.

    Caveat: pct_ok assumes each case traverses the fragment at most once. A
    surrounding loop that re-enters the fragment could place one case on both
    the bot and human paths across iterations, inflating the apparent failure
    count — safe for the near-linear processes this pattern targets.

    Raises ValueError if the fragment is not resolvable (run the structural
    check first) or a configured probability is absent from the JSON.
    """
    import json
    import tempfile

    import pandas as pd

    from ..simulation.runner import simulate

    root = ET.parse(str(bpmn_path)).getroot()
    process = root.find(f".//{{{_BPMN_NS}}}process")
    if process is None:
        raise ValueError("No <process> element found in the BPMN.")
    fragment, violations = _resolve_fragment(_Graph(process), target_activity)
    if fragment is None:
        raise ValueError(
            "Fragment is not structurally valid; run the structural check first. "
            f"First violation: {violations[0].message if violations else 'unknown'}"
        )

    params = json.loads(Path(params_path).read_text())
    expected_pct_auto = _configured_probability(
        params, fragment.gw_split_auto, fragment.bot_branch_flow
    )
    expected_pct_ok = _configured_probability(
        params, fragment.gw_split_result, fragment.bot_success_flow
    )
    if expected_pct_auto is None or expected_pct_ok is None:
        raise ValueError(
            "Configured branch probability missing from the params JSON — the "
            "BPMN gateway/flow ids do not match the JSON (a real miswire)."
        )

    with tempfile.TemporaryDirectory() as tmp:
        out_log = Path(tmp) / "behavioral_log.csv"
        simulate(Path(bpmn_path), Path(params_path), n_cases, out_log)
        log = pd.read_csv(out_log)

    total_cases = log["case_id"].nunique()
    bot_cases = set(log.loc[log["activity"] == fragment.bot_name, "case_id"])
    human_cases = set(log.loc[log["activity"] == target_activity, "case_id"])
    observed_pct_auto, observed_pct_ok, n_reached, n_bot = _observed_proportions(
        bot_cases, human_cases
    )

    return BehavioralResult(
        n_cases=total_cases,
        checks=(
            BehavioralCheck(
                "pct_auto (automation split)",
                expected_pct_auto,
                observed_pct_auto,
                n_eff=n_reached,
                tolerance_floor=tolerance_floor,
                sigma=sigma,
            ),
            BehavioralCheck(
                "pct_ok (bot-result split)",
                expected_pct_ok,
                observed_pct_ok,
                n_eff=n_bot,
                tolerance_floor=tolerance_floor,
                sigma=sigma,
            ),
        ),
    )


# ── CLI (thin shell over the pure functions above) ────────────────────────────


def _print_result(result: VerificationResult) -> None:
    print(f"Structural check - target {result.target_activity!r}")
    if not result.violations:
        print("  OK - fragment present and correctly wired.")
        return
    for violation in result.violations:
        marker = "ERROR" if violation.severity is Severity.ERROR else "warn "
        print(f"  [{marker}] {violation.code}: {violation.message}")
    print(f"  {len(result.errors)} error(s), {len(result.warnings)} warning(s).")


def _print_behavioral(result: BehavioralResult) -> None:
    print(f"\nBehavioral check - {result.n_cases} simulated cases")
    for check in result.checks:
        verdict = "OK" if check.ok else "FAIL"
        print(
            f"  [{verdict}] {check.label}: expected {check.expected:.3f}, "
            f"observed {check.observed:.3f} "
            f"(n={check.n_eff}, tol +/-{check.tolerance:.3f})"
        )


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m core.bpmn.validate",
        description="Verify a transformed BPMN has the XORSplitAutomation fragment.",
    )
    parser.add_argument("bpmn_path", type=Path, help="Path to the transformed BPMN.")
    parser.add_argument(
        "--target", required=True, help="Name of the target (automated) activity."
    )
    parser.add_argument(
        "--behavioral",
        action="store_true",
        help="Also run a Prosimos routing check (needs --params and the venv).",
    )
    parser.add_argument("--params", type=Path, help="Transformed Prosimos params JSON.")
    parser.add_argument("--cases", type=int, default=2000, help="Cases to simulate.")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.05,
        help="Proportion-match tolerance FLOOR (widened by sample size).",
    )
    args = parser.parse_args(argv)

    result = verify_fragment(args.bpmn_path, args.target)
    _print_result(result)
    exit_code = 0 if result.ok else 1

    if args.behavioral:
        if args.params is None:
            parser.error("--behavioral requires --params")
        if not result.ok:
            print("\nSkipping behavioral check: the structural check must pass first.")
        else:
            try:
                behavioral = behavioral_report(
                    args.bpmn_path, args.params, args.target, args.cases, args.tolerance
                )
            except ValueError as exc:
                parser.error(str(exc))
            _print_behavioral(behavioral)
            if not behavioral.ok:
                exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(_cli())
