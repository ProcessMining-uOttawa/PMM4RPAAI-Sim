"""Shared constants: analysis column names and Prosimos JSON keys used across modules."""

# ── Analysis column names ────────────────────────────────────────────────────
# per-replication per-case means
COL_MEAN_CYCLE_H = "mean_cycle_h"  # mean cycle time per case in hours, for one replication
COL_MEAN_COST = "mean_cost"        # mean cost per case, for one replication

# mean of per-case metrics across replications (used in aggregate() and Panel 4)
COL_MEAN_CYCLE_H_MEAN = "mean_cycle_h_mean"
COL_MEAN_COST_MEAN    = "mean_cost_mean"

# per-replication run totals (accumulated across all cases in one Prosimos run)
COL_TOTAL_CYCLE_S = "total_cycle_s"
COL_TOTAL_COST = "total_cost"

# mean of run totals across replications (used in aggregate() and Panel 5)
COL_TOTAL_CYCLE_S_MEAN = "total_cycle_s_mean"
COL_TOTAL_COST_MEAN = "total_cost_mean"

# per-replication rework metrics
COL_TOTAL_REWORK_COUNT = "total_rework_count"  # total extra activity occurrences + bot-failure events across all cases
COL_REWORK_RATE        = "rework_rate"          # percentage of cases with any rework (0–100)

# mean of rework metrics across replications (used in aggregate() and compare_to_baseline())
COL_TOTAL_REWORK_COUNT_MEAN = "total_rework_count_mean"
COL_REWORK_RATE_MEAN        = "rework_rate_mean"

# ── Prosimos JSON schema: top-level section keys ──────────────────────────────
KEY_RESOURCE_PROFILES = "resource_profiles"
KEY_TASK_RESOURCE_DISTRIBUTION = "task_resource_distribution"

# ── Taguchi factor IDs (bare column names used in Scenario.values dicts) ──────
F_PCT_AUTO             = "pct_auto"
F_PCT_OK               = "pct_ok"
F_T_AUTO               = "t_auto"
F_T_MANUAL             = "t_manual"
F_NUM_BOTS             = "num_bots"
F_NUM_MANUAL_RESOURCES = "num_manual_resources"
F_NUM_CASES            = "num_cases"
