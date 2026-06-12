"""Tests for core/bpmn/utils.py — resource_selector_config."""
from __future__ import annotations

from core.bpmn.utils import resource_selector_config


# ── Minimal Prosimos JSON fixture helpers ──────────────────────────────────────

def _prosimos(task_id: str, resources: list[dict], *, shared_with: str | None = None) -> dict:
    """Build a minimal Prosimos JSON dict.

    resources: list of {id, name, amount} for the target task.
    shared_with: if given, each resource also appears in a second task entry,
                 making them shared.
    """
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
    if shared_with:
        task_dist.append(
            {
                "task_id": shared_with,
                "resources": [{"resource_id": r["id"]} for r in resources],
            }
        )
    return {
        "resource_profiles": [{"id": "profile_1", "resource_list": profile_resources}],
        "task_resource_distribution": task_dist,
    }


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestResourceSelectorConfig:

    def test_no_resources_returns_empty(self):
        data = _prosimos("task_1", [])
        cfg = resource_selector_config(data, "task_1")
        assert cfg.selectable == []
        assert cfg.frozen == []
        assert cfg.frozen_pool_size is None

    def test_single_resource_auto_selectable(self):
        data = _prosimos("task_1", [{"id": "r1", "name": "Alice"}])
        cfg = resource_selector_config(data, "task_1")
        assert len(cfg.selectable) == 1
        assert cfg.selectable[0]["id"] == "r1"
        assert cfg.frozen == []
        assert cfg.frozen_pool_size is None

    def test_multiple_resources_none_shared(self):
        data = _prosimos("task_1", [
            {"id": "r1", "name": "Alice"},
            {"id": "r2", "name": "Bob"},
        ])
        cfg = resource_selector_config(data, "task_1")
        assert {r["id"] for r in cfg.selectable} == {"r1", "r2"}
        assert cfg.frozen == []
        assert cfg.frozen_pool_size is None

    def test_multiple_resources_partial_shared(self):
        """One resource shared with another task → frozen; other is selectable."""
        data = {
            "resource_profiles": [
                {"id": "profile_1", "resource_list": [
                    {"id": "r1", "name": "Alice", "amount": 2},
                    {"id": "r2", "name": "Bob",   "amount": 1},
                ]}
            ],
            "task_resource_distribution": [
                {"task_id": "task_1", "resources": [
                    {"resource_id": "r1"},
                    {"resource_id": "r2"},
                ]},
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
                {"id": "profile_1", "resource_list": [
                    {"id": "r1", "name": "Alice", "amount": 3},
                    {"id": "r2", "name": "Bob",   "amount": 2},
                ]}
            ],
            "task_resource_distribution": [
                {"task_id": "task_1", "resources": [
                    {"resource_id": "r1"}, {"resource_id": "r2"},
                ]},
                {"task_id": "task_2", "resources": [
                    {"resource_id": "r1"}, {"resource_id": "r2"},
                ]},
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
                {"task_id": "task_1", "resources": [
                    {"resource_id": "r1"}, {"resource_id": "r2"},
                ]},
                {"task_id": "task_2", "resources": [
                    {"resource_id": "r1"}, {"resource_id": "r2"},
                ]},
            ],
        }
        cfg = resource_selector_config(data, "task_1")
        assert cfg.selectable == []
        assert cfg.frozen_pool_size is None

    def test_unknown_task_returns_empty(self):
        data = _prosimos("task_1", [{"id": "r1", "name": "Alice"}])
        cfg = resource_selector_config(data, "nonexistent_task")
        assert cfg.selectable == []
        assert cfg.frozen == []
        assert cfg.frozen_pool_size is None
