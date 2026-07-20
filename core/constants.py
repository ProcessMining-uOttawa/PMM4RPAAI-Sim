"""Shared constants: analysis column names and Prosimos JSON keys used across modules."""

# ── Analysis column names ────────────────────────────────────────────────────
# per-replication per-case means
COL_MEAN_CYCLE_H = (
    "mean_cycle_h"  # mean cycle time per case in hours, for one replication
)
COL_MEAN_COST = "mean_cost"  # mean cost per case, for one replication
# Optional per-case cycle-time indicators (median / min / max over the case
# durations of one replication). Each is scoring-only: a goal may weight it as
# an indicator, but none feeds a total — the total_cycle_s = mean_cycle_h × n ×
# 3600 identity is carried by the mean alone.
COL_MEDIAN_CYCLE_H = "median_cycle_h"
COL_MIN_CYCLE_H = "min_cycle_h"
COL_MAX_CYCLE_H = "max_cycle_h"
# Mean per-case rework count (excess repeated-activity occurrences per case) — an
# optional scoring indicator for the rework metric; equals total_rework_count /
# n_cases, stored at source like every per-case mean.
COL_MEAN_REWORK_COUNT = "mean_rework_count"

# mean of per-case metrics across replications (aggregate() output; feeds the
# ranked results table)
COL_MEAN_CYCLE_H_MEAN = "mean_cycle_h_mean"
COL_MEAN_COST_MEAN = "mean_cost_mean"
COL_MEDIAN_CYCLE_H_MEAN = "median_cycle_h_mean"
COL_MIN_CYCLE_H_MEAN = "min_cycle_h_mean"
COL_MAX_CYCLE_H_MEAN = "max_cycle_h_mean"
COL_MEAN_REWORK_COUNT_MEAN = "mean_rework_count_mean"

# per-replication run totals (accumulated across all cases in one Prosimos run)
COL_TOTAL_CYCLE_S = "total_cycle_s"
COL_TOTAL_COST = "total_cost"

# mean of run totals across replications (aggregate() output; feeds the
# Baseline tab)
COL_TOTAL_CYCLE_S_MEAN = "total_cycle_s_mean"
COL_TOTAL_COST_MEAN = "total_cost_mean"

# per-replication rework metrics (repeated-activity rework only)
COL_TOTAL_REWORK_COUNT = (
    "total_rework_count"  # total extra activity occurrences across all cases
)
COL_REWORK_RATE = "rework_rate"  # percentage of cases with any rework (0–100)

# per-replication bot-failure metric: cases where the bot ran and a human redid
# the work — its own output metric, deliberately NOT counted as rework
COL_TOTAL_BOT_FAILURE_COUNT = "total_bot_failure_count"

# means across replications (used in aggregate() and compare_to_baseline())
COL_TOTAL_REWORK_COUNT_MEAN = "total_rework_count_mean"
COL_REWORK_RATE_MEAN = "rework_rate_mean"
COL_TOTAL_BOT_FAILURE_COUNT_MEAN = "total_bot_failure_count_mean"

# ── Prosimos JSON schema: top-level section keys ──────────────────────────────
KEY_RESOURCE_PROFILES = "resource_profiles"
KEY_TASK_RESOURCE_DISTRIBUTION = "task_resource_distribution"
# Consumed by both prosimos/editor.py (writes calendars) and prosimos/calendars.py
# (reads them to derive working time) — the two-module rule puts it here.
KEY_RESOURCE_CALENDARS = "resource_calendars"

# ── Taguchi factor IDs (bare column names used in Scenario.values dicts) ──────
F_PCT_AUTO = "pct_auto"
F_PCT_OK = "pct_ok"
F_T_AUTO = "t_auto"
F_T_MANUAL = "t_manual"
F_NUM_BOTS = "num_bots"
F_NUM_MANUAL_RESOURCES = "num_manual_resources"
