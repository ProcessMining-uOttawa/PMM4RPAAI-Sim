"""Two-layer test of the XORSplitAutomation trust verifier (core.bpmn.validate).

Layer 1 (TestOracleTrust): trust the oracle FIRST. One hand-authored correct
golden is accepted clean; every negative is an in-test mutation of that golden
asserting a specific violation code. If the oracle would accept a broken model,
Layer 2 is worthless.

Layer 2 (TestAppliedPatternVerified): THEN use the trusted oracle to verify the
real apply_pattern output over a corpus (the minimal synthetic input + the real
demo LoanApp model). Both must verify FULLY clean — edit.py keeps the
<incoming>/<outgoing> lists true to the edges it writes, so the transform leaves
no drift to tolerate.

Behavioral mode has no automated test here — it needs the Prosimos venv and is
exercised manually via the CLI (like runner.py's Simod/Prosimos invocation
paths, excluded from the coverage floor).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from core.bpmn.query import list_activities
from core.bpmn.validate import (
    BehavioralCheck,
    BehavioralResult,
    Severity,
    _configured_probability,
    _observed_proportions,
    verify_fragment,
)
from core.demo import DEMO_BPMN
from core.transformations import XORSplitAutomation
from tests.test_transformations import MINIMAL_BPMN

GOLDEN = Path(__file__).parent / "fixtures" / "golden_transformed.bpmn"
TARGET = "Test Task"
_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

# A second, independently-authored golden: a real 26-task Claims Management
# process built by hand in Apromore (NOT apply_pattern-generated) with the pattern
# applied, then denoised of its qbp: simulator-config block. A different author and
# real scale than the minimal golden above — a stronger independence anchor.
CLAIMS_GOLDEN = Path(__file__).parent / "fixtures" / "golden_claims_apromore.bpmn"
CLAIMS_TARGET = "Close Assessment"


# ── helpers ───────────────────────────────────────────────────────────────────


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _process(root: ET.Element) -> ET.Element:
    process = root.find(f".//{{{_NS}}}process")
    assert process is not None
    return process


def _flow(process: ET.Element, flow_id: str) -> ET.Element:
    for el in process:
        if _localname(el.tag) == "sequenceFlow" and el.get("id") == flow_id:
            return el
    raise AssertionError(f"flow {flow_id!r} not in golden")


def _node(process: ET.Element, node_id: str) -> ET.Element:
    for el in process:
        if _localname(el.tag) != "sequenceFlow" and el.get("id") == node_id:
            return el
    raise AssertionError(f"node {node_id!r} not in golden")


def _write(tree: ET.ElementTree, tmp_path: Path) -> Path:
    out = tmp_path / "mutated.bpmn"
    tree.write(str(out), xml_declaration=True, encoding="utf-8")
    return out


def _error_codes(result) -> set[str]:
    return {violation.code for violation in result.errors}


# ── Layer 1: trust the oracle ──────────────────────────────────────────────────


class TestOracleTrust:
    def test_golden_accepted(self):
        result = verify_fragment(GOLDEN, TARGET)
        # A correct golden is fully clean — no errors AND no warnings.
        assert result.violations == (), [
            violation.code for violation in result.violations
        ]
        assert result.ok

    def test_claims_golden_accepted(self):
        # The independently-authored Apromore golden must also be accepted fully
        # clean — a real-scale second anchor for the oracle's accept behaviour.
        result = verify_fragment(CLAIMS_GOLDEN, CLAIMS_TARGET)
        assert result.violations == (), [
            violation.code for violation in result.violations
        ]
        assert result.ok

    def test_target_not_found(self):
        result = verify_fragment(GOLDEN, "No Such Activity")
        assert not result.ok
        assert "TARGET_NOT_FOUND" in _error_codes(result)

    def test_missing_file_reports_parse_error(self, tmp_path):
        # A nonexistent path must return a clean PARSE_ERROR, not a traceback.
        result = verify_fragment(tmp_path / "does_not_exist.bpmn", TARGET)
        assert not result.ok
        assert "PARSE_ERROR" in _error_codes(result)

    def test_dangling_target_ref(self, tmp_path):
        tree = ET.parse(str(GOLDEN))
        _flow(_process(tree.getroot()), "task_1_auto_bot_success").set(
            "targetRef", "does_not_exist"
        )
        result = verify_fragment(_write(tree, tmp_path), TARGET)
        assert not result.ok
        assert "DANGLING_TARGET_REF" in _error_codes(result)

    def test_missing_merge_gateway(self, tmp_path):
        tree = ET.parse(str(GOLDEN))
        process = _process(tree.getroot())
        process.remove(_node(process, "task_1_auto_gw3"))
        result = verify_fragment(_write(tree, tmp_path), TARGET)
        assert not result.ok
        assert "MISSING_GATEWAY" in _error_codes(result)

    def test_bot_task_misnamed(self, tmp_path):
        tree = ET.parse(str(GOLDEN))
        _node(_process(tree.getroot()), "task_1_bot").set("name", "Not The Bot")
        result = verify_fragment(_write(tree, tmp_path), TARGET)
        assert not result.ok
        assert "BOT_TASK_NAME" in _error_codes(result)

    def test_split_wrong_degree(self, tmp_path):
        tree = ET.parse(str(GOLDEN))
        process = _process(tree.getroot())
        # A third outgoing edge from the automation split (to a real node, so the
        # failure is degree — not a dangling ref).
        extra = ET.SubElement(process, f"{{{_NS}}}sequenceFlow")
        extra.set("id", "extra_split_edge")
        extra.set("sourceRef", "task_1_auto_gw1")
        extra.set("targetRef", "end_1")
        result = verify_fragment(_write(tree, tmp_path), TARGET)
        assert not result.ok
        assert "GATEWAY_DEGREE" in _error_codes(result)

    def test_missing_internal_flow(self, tmp_path):
        tree = ET.parse(str(GOLDEN))
        process = _process(tree.getroot())
        # Drop the fallback-merge -> target flow; the target loses its only inflow.
        process.remove(_flow(process, "task_1_auto_to_human"))
        result = verify_fragment(_write(tree, tmp_path), TARGET)
        assert not result.ok
        assert "TARGET_DEGREE" in _error_codes(result)

    def test_io_list_contradiction_is_warning_not_error(self, tmp_path):
        # A declared <incoming> that lies about its edge is drift, not a miswire:
        # a WARNING that leaves the model passing (locks the ERROR/WARNING tiering).
        tree = ET.parse(str(GOLDEN))
        incoming = ET.SubElement(
            _node(_process(tree.getroot()), "end_1"), f"{{{_NS}}}incoming"
        )
        incoming.text = "flow_in"  # flow_in targets gw1, not end_1
        result = verify_fragment(_write(tree, tmp_path), TARGET)
        drift = [
            violation
            for violation in result.violations
            if violation.code == "IO_LIST_DRIFT"
        ]
        assert drift and all(
            violation.severity is Severity.WARNING for violation in drift
        )
        assert result.errors == ()
        assert result.ok


# ── Layer 2: verify apply_pattern via the trusted oracle ───────────────────────


def _first_transformable(pattern, bpmn_path, tmp_path):
    """First activity apply_pattern accepts (1 incoming + 1 outgoing), transformed."""
    for i, name in enumerate(list_activities(bpmn_path)):
        try:
            out_bpmn, _ = pattern.apply_pattern(
                bpmn_path, name, tmp_path / f"probe_{i}"
            )
            return name, out_bpmn
        except NotImplementedError:
            continue
    return None, None


class TestAppliedPatternVerified:
    @pytest.fixture
    def pattern(self):
        return XORSplitAutomation()

    def test_minimal_input_transformed_ok(self, pattern, tmp_path):
        src = tmp_path / "in.bpmn"
        src.write_text(MINIMAL_BPMN, encoding="utf-8")
        out_bpmn, _ = pattern.apply_pattern(src, "Test Task", tmp_path / "out")
        result = verify_fragment(out_bpmn, "Test Task")
        assert result.violations == (), [
            violation.code for violation in result.violations
        ]

    def test_demo_model_transformed_ok(self, pattern, tmp_path):
        name, out_bpmn = _first_transformable(pattern, DEMO_BPMN, tmp_path)
        assert name is not None, "demo model has no 1-in/1-out task to transform"
        result = verify_fragment(out_bpmn, name)
        # Fully clean on a real model: no IO_LIST_DRIFT left to tolerate. This is
        # the regression guard for the edit.py <incoming>/<outgoing> maintenance.
        assert result.violations == (), [
            violation.code for violation in result.violations
        ]


# ── Behavioral helpers (pure, venv-free — the sim itself is exercised via CLI) ──


def _probs(gateway_id: str, path_id: str, value) -> dict:
    return {
        "gateway_branching_probabilities": [
            {
                "gateway_id": gateway_id,
                "probabilities": [{"path_id": path_id, "value": value}],
            }
        ]
    }


class TestConfiguredProbability:
    def test_reads_matching_path(self):
        params = _probs("gw1", "flow_a", 0.75)
        assert _configured_probability(params, "gw1", "flow_a") == 0.75

    def test_missing_gateway_returns_none(self):
        params = _probs("gw1", "flow_a", 0.75)
        assert _configured_probability(params, "gw_other", "flow_a") is None

    def test_missing_path_returns_none(self):
        params = _probs("gw1", "flow_a", 0.75)
        assert _configured_probability(params, "gw1", "flow_other") is None

    def test_null_value_returns_none_not_crash(self):
        # A matching path with a null value is a JSON<->BPMN mismatch, surfaced
        # as "missing" (None) so behavioral_report raises cleanly, not TypeError.
        params = _probs("gw1", "flow_a", None)
        assert _configured_probability(params, "gw1", "flow_a") is None

    def test_out_of_range_value_returns_none(self):
        # A probability outside [0, 1] (or non-finite) is malformed -> missing,
        # so it never reaches the SE/tolerance math in behavioral_report.
        params = _probs("gw1", "flow_a", 1.5)
        assert _configured_probability(params, "gw1", "flow_a") is None


class TestObservedProportions:
    """The conditional-denominator fix: proportions are per fragment-reaching
    case, NOT per whole simulated population."""

    def test_pct_auto_conditions_on_reached_not_total(self):
        # 2 bot cases, 4 human cases (one shared) -> 5 reached the fragment.
        # pct_auto must be 2/5, NOT 2/<some larger population>.
        pct_auto, _, n_reached, _ = _observed_proportions({1, 2}, {2, 3, 4, 5})
        assert n_reached == 5
        assert pct_auto == pytest.approx(2 / 5)

    def test_pct_ok_conditions_on_bot_cases(self):
        # bot={1,2,3,4}; bot-then-human (failures) = {3,4} -> pct_ok = 1 - 2/4.
        _, pct_ok, _, n_bot = _observed_proportions({1, 2, 3, 4}, {3, 4, 9})
        assert n_bot == 4
        assert pct_ok == pytest.approx(0.5)

    def test_empty_sets_do_not_divide_by_zero(self):
        pct_auto, pct_ok, n_reached, n_bot = _observed_proportions(set(), set())
        assert (pct_auto, pct_ok, n_reached, n_bot) == (0.0, 0.0, 0, 0)


class TestBehavioralVerdicts:
    def test_small_sample_widens_tolerance_so_noise_passes(self):
        # The exact smoke-test case: pct_ok 0.75 vs expected 0.80 at n_eff=128
        # is ~1.4 sigma -> noise. Fixed +/-0.05 wrongly FAILed; the widened band
        # (max floor, 4*SE ~= 0.14) passes it.
        check = BehavioralCheck("pct_ok", 0.80, 0.75, n_eff=128)
        assert check.tolerance > 0.05
        assert check.ok

    def test_large_sample_holds_the_floor_so_real_miswire_fails(self):
        # A 7pp deviation at large n_eff exceeds the floor -> a real miswire fails.
        check = BehavioralCheck("pct_auto", 0.25, 0.32, n_eff=100_000)
        assert check.tolerance == pytest.approx(0.05)
        assert not check.ok

    def test_zero_sample_is_untestable_and_accepts(self):
        assert BehavioralCheck("x", 0.5, 0.9, n_eff=0).ok

    def test_result_ok_requires_all_checks(self):
        good = BehavioralCheck("a", 0.5, 0.5, n_eff=1000)
        bad = BehavioralCheck("b", 0.5, 0.9, n_eff=1000)
        assert BehavioralResult(1000, (good,)).ok
        assert not BehavioralResult(1000, (good, bad)).ok
