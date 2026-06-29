"""Tests for core/simulation/prosimos/editor.py — no external tools required.

Prosimos schema keys are hardcoded as sentinels: a typo in editor.py's KEY_*
constants (or the inline strings) must fail a test loudly, so these tests
deliberately do not import those constants.
"""

from __future__ import annotations

import pytest

from core.simulation.prosimos.editor import (
    add_gateway_probs,
    append_task_distribution,
    ensure_calendar,
    set_fixed,
    set_resource_amount,
    set_uniform,
    upsert_resource_in_profile,
)


def _entry(*resource_ids: str) -> dict:
    """A task_resource_distribution entry holding the given resource ids."""
    return {
        "task_id": "t1",
        "resources": [{"resource_id": resource_id} for resource_id in resource_ids],
    }


# ── set_uniform / set_fixed ───────────────────────────────────────────────────


class TestSetUniform:
    def test_writes_uniform_to_all_resources(self):
        entry = _entry("r1", "r2")
        set_uniform(entry, 100.0)
        assert all(r["distribution_name"] == "uniform" for r in entry["resources"])

    def test_bounds_are_mean_plus_minus_jitter(self):
        entry = _entry("r1")
        set_uniform(entry, 100.0, jitter=0.1)
        params = entry["resources"][0]["distribution_params"]
        assert params[0]["value"] == pytest.approx(90.0)
        assert params[1]["value"] == pytest.approx(110.0)

    def test_lower_bound_clamped_at_zero(self):
        entry = _entry("r1")
        set_uniform(entry, 1.0, jitter=2.0)  # mean*(1-2) = -1 → clamped to 0
        params = entry["resources"][0]["distribution_params"]
        assert params[0]["value"] == 0.0


class TestSetFixed:
    def test_writes_fix_with_single_value(self):
        entry = _entry("r1")
        set_fixed(entry, 250.0)
        resource = entry["resources"][0]
        assert resource["distribution_name"] == "fix"
        assert resource["distribution_params"] == [{"value": 250.0}]

    def test_applies_to_all_resources(self):
        entry = _entry("r1", "r2")
        set_fixed(entry, 300.0)
        assert all(r["distribution_name"] == "fix" for r in entry["resources"])


# ── set_resource_amount ───────────────────────────────────────────────────────


class TestSetResourceAmount:
    def _sim(self) -> dict:
        return {
            "resource_profiles": [
                {
                    "id": "p1",
                    "resource_list": [
                        {"id": "r1", "amount": 1},
                        {"id": "r2", "amount": 1},
                    ],
                }
            ]
        }

    def test_sets_amount_on_matching_resource(self):
        sim = self._sim()
        set_resource_amount(sim, "r2", 5)
        resource_list = sim["resource_profiles"][0]["resource_list"]
        assert {r["id"]: r["amount"] for r in resource_list} == {"r1": 1, "r2": 5}

    def test_not_found_is_noop(self):
        sim = self._sim()
        set_resource_amount(sim, "nonexistent", 9)  # exercises the not-found branch
        resource_list = sim["resource_profiles"][0]["resource_list"]
        assert [r["amount"] for r in resource_list] == [1, 1]

    def test_finds_resource_across_profiles(self):
        sim = {
            "resource_profiles": [
                {"id": "p1", "resource_list": [{"id": "r1", "amount": 1}]},
                {"id": "p2", "resource_list": [{"id": "r2", "amount": 1}]},
            ]
        }
        set_resource_amount(sim, "r2", 7)
        assert sim["resource_profiles"][1]["resource_list"][0]["amount"] == 7


# ── ensure_calendar ───────────────────────────────────────────────────────────


class TestEnsureCalendar:
    def test_adds_calendar_when_key_absent(self):
        sim: dict = {}
        ensure_calendar(sim, {"id": "cal_1"})
        assert sim["resource_calendars"] == [{"id": "cal_1"}]

    def test_adds_calendar_when_id_new(self):
        sim = {"resource_calendars": [{"id": "cal_1"}]}
        ensure_calendar(sim, {"id": "cal_2"})
        assert [c["id"] for c in sim["resource_calendars"]] == ["cal_1", "cal_2"]

    def test_idempotent_when_id_exists(self):
        sim = {"resource_calendars": [{"id": "cal_1", "name": "first"}]}
        ensure_calendar(sim, {"id": "cal_1", "name": "second"})  # same id → skip
        assert sim["resource_calendars"] == [{"id": "cal_1", "name": "first"}]


# ── upsert_resource_in_profile ────────────────────────────────────────────────


class TestUpsertResourceInProfile:
    def test_creates_profile_when_absent(self):
        sim: dict = {}
        upsert_resource_in_profile(sim, "p1", "Pool", {"id": "r1"})
        profile = sim["resource_profiles"][0]
        assert profile["id"] == "p1"
        assert profile["name"] == "Pool"
        assert profile["resource_list"] == [{"id": "r1"}]

    def test_appends_to_existing_profile(self):
        sim = {
            "resource_profiles": [
                {"id": "p1", "name": "Pool", "resource_list": [{"id": "r1"}]}
            ]
        }
        upsert_resource_in_profile(sim, "p1", "Pool", {"id": "r2"})  # profile exists
        profiles = sim["resource_profiles"]
        assert len(profiles) == 1  # not recreated
        assert [r["id"] for r in profiles[0]["resource_list"]] == ["r1", "r2"]


# ── append_task_distribution ──────────────────────────────────────────────────


class TestAppendTaskDistribution:
    def test_appends_entry(self):
        sim = {"task_resource_distribution": [{"task_id": "t0"}]}
        append_task_distribution(sim, {"task_id": "t1"})
        assert [e["task_id"] for e in sim["task_resource_distribution"]] == ["t0", "t1"]


# ── add_gateway_probs ─────────────────────────────────────────────────────────


class TestAddGatewayProbs:
    def test_builds_entry_structure(self):
        sim: dict = {}
        add_gateway_probs(sim, "gw1", {"flow_a": 0.7, "flow_b": 0.3})
        entries = sim["gateway_branching_probabilities"]
        assert len(entries) == 1
        assert entries[0]["gateway_id"] == "gw1"
        probs = {p["path_id"]: p["value"] for p in entries[0]["probabilities"]}
        assert probs == {"flow_a": 0.7, "flow_b": 0.3}

    def test_appends_to_existing_list(self):
        sim = {"gateway_branching_probabilities": [{"gateway_id": "gw0"}]}
        add_gateway_probs(sim, "gw1", {"flow_a": 1.0})
        ids = [e["gateway_id"] for e in sim["gateway_branching_probabilities"]]
        assert ids == ["gw0", "gw1"]
