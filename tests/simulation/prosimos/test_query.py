"""Tests for core/simulation/prosimos/query.py — no external tools required."""

from __future__ import annotations

import pytest

from core.simulation.prosimos.query import (
    resource_selector_config,
    resource_pool_size,
    shared_resource_ids,
    task_mean_duration_s,
    task_resources,
)

_PROSIMOS_JSON = {
    "resource_profiles": [
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
    "task_resource_distribution": [
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


def _selector_json(task_id: str, resources: list[dict]) -> dict:
    """Build a minimal Prosimos JSON dict for resource_selector_config tests."""
    profile_resources = [
        {
            "id": resource["id"],
            "name": resource["name"],
            "amount": resource.get("amount", 1),
        }
        for resource in resources
    ]
    task_dist = [
        {
            "task_id": task_id,
            "resources": [{"resource_id": resource["id"]} for resource in resources],
        }
    ]
    return {
        "resource_profiles": [{"id": "profile_1", "resource_list": profile_resources}],
        "task_resource_distribution": task_dist,
    }


def _distribution_json(distribution_name: str, values: list[float]) -> dict:
    """One task (t1) with one resource (r1) using the given duration distribution."""
    return {
        "resource_profiles": [],
        "task_resource_distribution": [
            {
                "task_id": "t1",
                "resources": [
                    {
                        "resource_id": "r1",
                        "distribution_name": distribution_name,
                        "distribution_params": [{"value": value} for value in values],
                    }
                ],
            }
        ],
    }


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

    @pytest.mark.parametrize(
        "distribution_name, values, expected",
        # Param layouts mirror Prosimos/pix_framework exactly (params[0] = mean):
        #   fix [mean] · expon [mean, min, max] · norm [mean, std, min, max] ·
        #   lognorm / gamma [mean, var, min, max]. Short forms exercise the aliases.
        [
            ("fix", [450.0], 450.0),
            ("expon", [120.0, 0.0, 600.0], 120.0),
            ("exponential", [60.0], 60.0),  # alias
            ("norm", [300.0, 30.0, 0.0, 600.0], 300.0),
            ("normal", [180.0, 20.0], 180.0),  # alias
            ("lognorm", [240.0, 10000.0, 0.0, 1200.0], 240.0),
            ("gamma", [500.0, 250000.0, 0.0, 3000.0], 500.0),
        ],
    )
    def test_first_param_is_mean(self, distribution_name, values, expected):
        data = _distribution_json(distribution_name, values)
        assert task_mean_duration_s(data, "t1") == pytest.approx(expected)

    def test_unrecognised_distribution_returns_none(self):
        # Simod emits uniform/fix/expon/norm/lognorm/gamma; "triang" is in pix's enum
        # but the fitter never emits it, so we deliberately don't handle it → None
        # (the caller then falls back to its default duration).
        data = _distribution_json("triang", [1.0, 2.0, 3.0])
        assert task_mean_duration_s(data, "t1") is None

    def test_mixed_known_and_unknown_distributions(self):
        # One resource uses an unhandled distribution (triang → None), the other a
        # known fix [450]. The unknown mean is SKIPPED, not averaged in, so the
        # result is the known mean (450) — not None, and not (450 + …) / 2.
        data = {
            "resource_profiles": [],
            "task_resource_distribution": [
                {
                    "task_id": "t1",
                    "resources": [
                        {
                            "resource_id": "r1",
                            "distribution_name": "triang",
                            "distribution_params": [
                                {"value": 1.0},
                                {"value": 2.0},
                                {"value": 3.0},
                            ],
                        },
                        {
                            "resource_id": "r2",
                            "distribution_name": "fix",
                            "distribution_params": [{"value": 450.0}],
                        },
                    ],
                }
            ],
        }
        assert task_mean_duration_s(data, "t1") == pytest.approx(450.0)


# ── resource_selector_config ──────────────────────────────────────────────────


class TestResourceSelectorConfig:
    def test_no_resources_returns_empty(self):
        data = _selector_json("task_1", [])
        config = resource_selector_config(data, "task_1")
        assert config.selectable == []
        assert config.frozen == []
        assert config.fallback_pool_size is None

    def test_single_resource_auto_selectable(self):
        data = _selector_json("task_1", [{"id": "r1", "name": "Alice"}])
        config = resource_selector_config(data, "task_1")
        assert len(config.selectable) == 1
        assert config.selectable[0]["id"] == "r1"
        assert config.frozen == []
        assert config.fallback_pool_size is None

    def test_single_shared_resource_frozen(self):
        """A task's only resource, shared with another task, is frozen + pinned —
        not selectable. Regression for the len<=1 early return that skipped the
        shared check (20b)."""
        data = {
            "resource_profiles": [
                {
                    "id": "profile_1",
                    "resource_list": [{"id": "r1", "name": "Alice", "amount": 4}],
                }
            ],
            "task_resource_distribution": [
                {"task_id": "task_1", "resources": [{"resource_id": "r1"}]},
                {"task_id": "task_2", "resources": [{"resource_id": "r1"}]},
            ],
        }
        config = resource_selector_config(data, "task_1")
        assert config.selectable == []
        assert [r["id"] for r in config.frozen] == ["r1"]
        assert config.fallback_pool_size == 4

    def test_multiple_resources_none_shared(self):
        data = _selector_json(
            "task_1",
            [
                {"id": "r1", "name": "Alice"},
                {"id": "r2", "name": "Bob"},
            ],
        )
        config = resource_selector_config(data, "task_1")
        assert {r["id"] for r in config.selectable} == {"r1", "r2"}
        assert config.frozen == []
        assert config.fallback_pool_size is None

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
        config = resource_selector_config(data, "task_1")
        assert [r["id"] for r in config.selectable] == ["r2"]
        assert [r["id"] for r in config.frozen] == ["r1"]
        assert config.fallback_pool_size is None

    def test_all_resources_shared_returns_fallback_pool_size(self):
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
        config = resource_selector_config(data, "task_1")
        assert config.selectable == []
        assert len(config.frozen) == 2
        assert config.fallback_pool_size == 3  # pool size of the first resource

    def test_all_resources_shared_pool_unknown_when_not_in_profile(self):
        """fallback_pool_size is None when no resource appears in any profile."""
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
        config = resource_selector_config(data, "task_1")
        assert config.selectable == []
        assert config.fallback_pool_size is None

    def test_unknown_task_returns_empty(self):
        data = _selector_json("task_1", [{"id": "r1", "name": "Alice"}])
        config = resource_selector_config(data, "nonexistent_task")
        assert config.selectable == []
        assert config.frozen == []
        assert config.fallback_pool_size is None
