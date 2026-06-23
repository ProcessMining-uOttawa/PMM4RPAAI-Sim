"""Tests for core/bpmn/query.py — no external tools required."""

from __future__ import annotations
import xml.etree.ElementTree as ET

import pytest

from core.bpmn.query import (
    find_task_by_name,
    list_activities,
    resource_selector_config,
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

    def test_expon_distribution_uses_first_param_as_mean(self):
        data = {
            KEY_RESOURCE_PROFILES: [],
            KEY_TASK_RESOURCE_DISTRIBUTION: [
                {
                    "task_id": "t1",
                    "resources": [
                        {
                            "resource_id": "r1",
                            "distribution_name": "expon",
                            "distribution_params": [{"value": 120.0}],
                        }
                    ],
                }
            ],
        }
        assert task_mean_duration_s(data, "t1") == pytest.approx(120.0)

    def test_exponential_alias_also_accepted(self):
        data = {
            KEY_RESOURCE_PROFILES: [],
            KEY_TASK_RESOURCE_DISTRIBUTION: [
                {
                    "task_id": "t1",
                    "resources": [
                        {
                            "resource_id": "r1",
                            "distribution_name": "exponential",
                            "distribution_params": [{"value": 60.0}],
                        }
                    ],
                }
            ],
        }
        assert task_mean_duration_s(data, "t1") == pytest.approx(60.0)

    def test_norm_distribution_uses_first_param_as_mean(self):
        data = {
            KEY_RESOURCE_PROFILES: [],
            KEY_TASK_RESOURCE_DISTRIBUTION: [
                {
                    "task_id": "t1",
                    "resources": [
                        {
                            "resource_id": "r1",
                            "distribution_name": "norm",
                            "distribution_params": [{"value": 300.0}, {"value": 30.0}],
                        }
                    ],
                }
            ],
        }
        assert task_mean_duration_s(data, "t1") == pytest.approx(300.0)

    def test_normal_alias_also_accepted(self):
        data = {
            KEY_RESOURCE_PROFILES: [],
            KEY_TASK_RESOURCE_DISTRIBUTION: [
                {
                    "task_id": "t1",
                    "resources": [
                        {
                            "resource_id": "r1",
                            "distribution_name": "normal",
                            "distribution_params": [{"value": 180.0}, {"value": 20.0}],
                        }
                    ],
                }
            ],
        }
        assert task_mean_duration_s(data, "t1") == pytest.approx(180.0)


# ── list_activities ───────────────────────────────────────────────────────────


class TestListActivities:
    def _write_bpmn(self, tmp_path, names: list[str]):
        bpmn = f"""\
<?xml version="1.0"?>
<bpmn:definitions xmlns:bpmn="{BPMN_NS}">
  <bpmn:process>
    {"".join(f'<bpmn:task id="t{i}" name="{n}"/>' for i, n in enumerate(names))}
  </bpmn:process>
</bpmn:definitions>"""
        path = tmp_path / "model.bpmn"
        path.write_text(bpmn)
        return path

    def test_returns_task_names(self, tmp_path):
        path = self._write_bpmn(tmp_path, ["Fix Bug", "Review"])
        assert list_activities(path) == ["Fix Bug", "Review"]

    def test_deduplicates_names(self, tmp_path):
        path = self._write_bpmn(tmp_path, ["Fix Bug", "Fix Bug"])
        assert list_activities(path) == ["Fix Bug"]

    def test_excludes_nameless_tasks(self, tmp_path):
        bpmn = f"""\
<?xml version="1.0"?>
<bpmn:definitions xmlns:bpmn="{BPMN_NS}">
  <bpmn:process>
    <bpmn:task id="t0"/>
    <bpmn:task id="t1" name="Real Task"/>
  </bpmn:process>
</bpmn:definitions>"""
        path = tmp_path / "model.bpmn"
        path.write_text(bpmn)
        assert list_activities(path) == ["Real Task"]

    def test_empty_process_returns_empty_list(self, tmp_path):
        path = self._write_bpmn(tmp_path, [])
        assert list_activities(path) == []


# ── resource_selector_config ──────────────────────────────────────────────────


def _prosimos_sel(task_id: str, resources: list[dict]) -> dict:
    """Build a minimal Prosimos JSON dict for resource_selector_config tests."""
    profile_resources = [
        {"id": r["id"], "name": r["name"], "amount": r.get("amount", 1)}
        for r in resources
    ]
    task_dist = [
        {
            "task_id": task_id,
            "resources": [{"resource_id": r["id"]} for r in resources],
        }
    ]
    return {
        "resource_profiles": [{"id": "profile_1", "resource_list": profile_resources}],
        "task_resource_distribution": task_dist,
    }


class TestResourceSelectorConfig:
    def test_no_resources_returns_empty(self):
        data = _prosimos_sel("task_1", [])
        cfg = resource_selector_config(data, "task_1")
        assert cfg.selectable == []
        assert cfg.frozen == []
        assert cfg.frozen_pool_size is None

    def test_single_resource_auto_selectable(self):
        data = _prosimos_sel("task_1", [{"id": "r1", "name": "Alice"}])
        cfg = resource_selector_config(data, "task_1")
        assert len(cfg.selectable) == 1
        assert cfg.selectable[0]["id"] == "r1"
        assert cfg.frozen == []
        assert cfg.frozen_pool_size is None

    def test_multiple_resources_none_shared(self):
        data = _prosimos_sel(
            "task_1",
            [
                {"id": "r1", "name": "Alice"},
                {"id": "r2", "name": "Bob"},
            ],
        )
        cfg = resource_selector_config(data, "task_1")
        assert {r["id"] for r in cfg.selectable} == {"r1", "r2"}
        assert cfg.frozen == []
        assert cfg.frozen_pool_size is None

    def test_multiple_resources_partial_shared(self):
        """One resource shared with another task → frozen; other is selectable."""
        data = {
            "resource_profiles": [
                {
                    "id": "profile_1",
                    "resource_list": [
                        {"id": "r1", "name": "Alice", "amount": 2},
                        {"id": "r2", "name": "Bob", "amount": 1},
                    ],
                }
            ],
            "task_resource_distribution": [
                {
                    "task_id": "task_1",
                    "resources": [
                        {"resource_id": "r1"},
                        {"resource_id": "r2"},
                    ],
                },
                {"task_id": "task_2", "resources": [{"resource_id": "r1"}]},
            ],
        }
        cfg = resource_selector_config(data, "task_1")
        assert [r["id"] for r in cfg.selectable] == ["r2"]
        assert [r["id"] for r in cfg.frozen] == ["r1"]
        assert cfg.frozen_pool_size is None

    def test_all_resources_shared_returns_frozen_pool_size(self):
        """Both resources on task_1 are also on another task → all frozen."""
        data = {
            "resource_profiles": [
                {
                    "id": "profile_1",
                    "resource_list": [
                        {"id": "r1", "name": "Alice", "amount": 3},
                        {"id": "r2", "name": "Bob", "amount": 2},
                    ],
                }
            ],
            "task_resource_distribution": [
                {
                    "task_id": "task_1",
                    "resources": [
                        {"resource_id": "r1"},
                        {"resource_id": "r2"},
                    ],
                },
                {
                    "task_id": "task_2",
                    "resources": [
                        {"resource_id": "r1"},
                        {"resource_id": "r2"},
                    ],
                },
            ],
        }
        cfg = resource_selector_config(data, "task_1")
        assert cfg.selectable == []
        assert len(cfg.frozen) == 2
        assert cfg.frozen_pool_size == 3  # pool size of the first resource

    def test_all_resources_shared_pool_unknown_when_not_in_profile(self):
        """frozen_pool_size is None when no resource appears in any profile."""
        data = {
            "resource_profiles": [],
            "task_resource_distribution": [
                {
                    "task_id": "task_1",
                    "resources": [
                        {"resource_id": "r1"},
                        {"resource_id": "r2"},
                    ],
                },
                {
                    "task_id": "task_2",
                    "resources": [
                        {"resource_id": "r1"},
                        {"resource_id": "r2"},
                    ],
                },
            ],
        }
        cfg = resource_selector_config(data, "task_1")
        assert cfg.selectable == []
        assert cfg.frozen_pool_size is None

    def test_unknown_task_returns_empty(self):
        data = _prosimos_sel("task_1", [{"id": "r1", "name": "Alice"}])
        cfg = resource_selector_config(data, "nonexistent_task")
        assert cfg.selectable == []
        assert cfg.frozen == []
        assert cfg.frozen_pool_size is None
