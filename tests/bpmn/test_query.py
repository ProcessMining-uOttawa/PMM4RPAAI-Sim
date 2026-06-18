"""Tests for core/bpmn/query.py — no external tools required."""

from __future__ import annotations
import xml.etree.ElementTree as ET

import pytest

from core.bpmn.query import (
    find_task_by_name,
    task_resources,
    shared_resource_ids,
    resource_pool_size,
    task_mean_duration_s,
)
from core.bpmn import BPMN_NS
from core.constants import KEY_RESOURCE_PROFILES, KEY_TASK_RESOURCE_DISTRIBUTION

_BPMN_XML = f"""\
<?xml version="1.0"?>
<bpmn:definitions xmlns:bpmn="{BPMN_NS}">
  <bpmn:process>
    <bpmn:task     id="task_1" name="My Task"/>
    <bpmn:userTask id="task_2" name="User Task"/>
  </bpmn:process>
</bpmn:definitions>
"""

# res_b appears in task_1 and task_2 → shared; res_a only in task_1 → exclusive
_PROSIMOS_JSON = {
    KEY_RESOURCE_PROFILES: [
        {
            "id": "profile_1",
            "name": "Workers",
            "resource_list": [
                {
                    "id": "res_a",
                    "name": "Alice",
                    "amount": 2,
                    "cost_per_hour": "10",
                    "calendar": "cal_1",
                },
                {
                    "id": "res_b",
                    "name": "Bob",
                    "amount": 1,
                    "cost_per_hour": "10",
                    "calendar": "cal_1",
                },
            ],
        }
    ],
    KEY_TASK_RESOURCE_DISTRIBUTION: [
        {
            "task_id": "task_1",
            "resources": [
                {
                    "resource_id": "res_a",
                    "distribution_name": "uniform",
                    "distribution_params": [{"value": 100.0}, {"value": 200.0}],
                },
                {
                    "resource_id": "res_b",
                    "distribution_name": "fix",
                    "distribution_params": [{"value": 300.0}],
                },
            ],
        },
        {
            "task_id": "task_2",
            "resources": [
                {
                    "resource_id": "res_b",
                    "distribution_name": "uniform",
                    "distribution_params": [{"value": 50.0}, {"value": 150.0}],
                },
            ],
        },
    ],
}


# ── find_task_by_name ─────────────────────────────────────────────────────────


class TestFindTaskByName:
    @pytest.fixture
    def tree(self):
        return ET.ElementTree(ET.fromstring(_BPMN_XML))

    def test_finds_plain_task(self, tree):
        el = find_task_by_name(tree, "My Task")
        assert el is not None and el.get("id") == "task_1"

    def test_finds_user_task(self, tree):
        el = find_task_by_name(tree, "User Task")
        assert el is not None and el.get("id") == "task_2"

    def test_returns_none_when_not_found(self, tree):
        assert find_task_by_name(tree, "Nonexistent") is None


# ── task_resources ────────────────────────────────────────────────────────────


class TestTaskResources:
    def test_returns_resources_in_order(self):
        resources = task_resources(_PROSIMOS_JSON, "task_1")
        assert [r["id"] for r in resources] == ["res_a", "res_b"]

    def test_includes_resolved_names(self):
        resources = task_resources(_PROSIMOS_JSON, "task_1")
        assert resources[0]["name"] == "Alice"
        assert resources[1]["name"] == "Bob"

    def test_not_found_returns_empty(self):
        assert task_resources(_PROSIMOS_JSON, "nonexistent") == []


# ── shared_resource_ids ───────────────────────────────────────────────────────


class TestSharedResourceIds:
    def test_shared_resource_detected(self):
        assert "res_b" in shared_resource_ids(_PROSIMOS_JSON)

    def test_exclusive_resource_not_shared(self):
        assert "res_a" not in shared_resource_ids(_PROSIMOS_JSON)


# ── resource_pool_size ────────────────────────────────────────────────────────


class TestResourcePoolSize:
    def test_returns_correct_amount(self):
        assert resource_pool_size(_PROSIMOS_JSON, "res_a") == 2

    def test_returns_none_when_not_found(self):
        assert resource_pool_size(_PROSIMOS_JSON, "unknown") is None


# ── task_mean_duration_s ──────────────────────────────────────────────────────


class TestTaskMeanDurationS:
    def test_averages_across_resources(self):
        # res_a: uniform [100, 200] → mean 150
        # res_b: fix [300]          → mean 300
        # average = (150 + 300) / 2 = 225
        assert task_mean_duration_s(_PROSIMOS_JSON, "task_1") == pytest.approx(225.0)

    def test_uniform_single_resource(self):
        # task_2 / res_b: uniform [50, 150] → mean 100
        assert task_mean_duration_s(_PROSIMOS_JSON, "task_2") == pytest.approx(100.0)

    def test_returns_none_when_task_not_found(self):
        assert task_mean_duration_s(_PROSIMOS_JSON, "nonexistent") is None
