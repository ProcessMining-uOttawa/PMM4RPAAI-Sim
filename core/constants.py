"""Shared constants: analysis column names and Prosimos JSON keys used across modules."""

# ── Analysis column names ────────────────────────────────────────────────────
COL_CYCLE_H = "cycle_h"
COL_COST = "cost"
COL_CYCLE_H_MEAN = "cycle_h_mean"
COL_COST_MEAN = "cost_mean"

# per-replication run totals (accumulated across all cases in one Prosimos run)
COL_TOTAL_CYCLE_S = "total_cycle_s"
COL_TOTAL_COST = "total_cost"

# mean of run totals across replications (used in aggregate() and Panel 5)
COL_TOTAL_CYCLE_S_MEAN = "total_cycle_s_mean"
COL_TOTAL_COST_MEAN = "total_cost_mean"

# per-replication rework metrics (informational, not wired into ranking)
COL_REWORK_COUNT = "rework_count"   # total extra activity occurrences + bot-failure events
COL_REWORK_RATE  = "rework_rate"    # fraction of cases with any rework

# mean of rework metrics across replications (used in aggregate() and compare_to_baseline())
COL_REWORK_COUNT_MEAN = "rework_count_mean"
COL_REWORK_RATE_MEAN  = "rework_rate_mean"

# ── Prosimos JSON schema: top-level section keys ──────────────────────────────
KEY_RESOURCE_PROFILES = "resource_profiles"
KEY_TASK_RESOURCE_DISTRIBUTION = "task_resource_distribution"
