"""Shared constants: XML namespaces, Prosimos JSON keys, and pattern defaults."""

# ── Bot resource profile ──────────────────────────────────────────────────────
BOT_PROFILE_ID = "BOT_PROFILE"
BOT_PROFILE_NAME = "Bot Resources"

# ── Bot resource defaults ─────────────────────────────────────────────────────
BOT_COST_PER_HOUR = "0"
BOT_AMOUNT = 1

# ── Bot calendar ──────────────────────────────────────────────────────────────
BOT_CALENDAR_ID = "BOT_CALENDAR"
BOT_CALENDAR_NAME = "Bot 24/7 Schedule"
BOT_CALENDAR_FROM = "MONDAY"
BOT_CALENDAR_TO = "SUNDAY"
BOT_CALENDAR_BEGIN = "00:00:00.000"
BOT_CALENDAR_END = "23:59:59.999"

# ── Bot task distribution defaults ────────────────────────────────────────────
BOT_DISTRIBUTION_NAME = "fix"
BOT_DISTRIBUTION_VALUE = 0.0

# ── Gateway display names ─────────────────────────────────────────────────────
GW1_NAME = "Bot or Human?"
GW2_NAME = "Bot succeeded?"
GW3_NAME = "Human needed"
GW4_NAME = "Exit"

# ── Sequence flow display labels ──────────────────────────────────────────────
F_BOT_BRANCH_LABEL = "bot"
F_HUMAN_BRANCH_LABEL = "human"
F_BOT_SUCCESS_LABEL = "success"
F_BOT_FAILURE_LABEL = "failure"

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

# ── Prosimos stats CSV: section header names ──────────────────────────────────
PROSIMOS_SECTION_TASK_STATS = "Individual Task Statistics"
PROSIMOS_SECTION_OVERALL    = "Overall Scenario Statistics"

# ── Prosimos stats CSV: column and row-key lookup strings ─────────────────────
PROSIMOS_COL_TOTAL_COST  = "Total Cost"        # column in SECTION_TASK_STATS
PROSIMOS_COL_ACCUMULATED = "Accumulated Value"  # column in SECTION_OVERALL
PROSIMOS_KPI_CYCLE_TIME  = "cycle_time"         # KPI row key in SECTION_OVERALL

# ── Prosimos JSON schema: top-level section keys ──────────────────────────────
KEY_RESOURCE_CALENDARS = "resource_calendars"
KEY_RESOURCE_PROFILES = "resource_profiles"
KEY_TASK_RESOURCE_DISTRIBUTION = "task_resource_distribution"
KEY_GATEWAY_BRANCHING_PROBS = "gateway_branching_probabilities"

# ── BPMN XML namespaces ───────────────────────────────────────────────────────
BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"

# ── BPMN task element tag names (without namespace prefix) ────────────────────
BPMN_TASK_TAGS = (
    "task",
    "userTask",
    "serviceTask",
    "manualTask",
    "businessRuleTask",
    "scriptTask",
    "sendTask",
    "receiveTask",
)

# ── XOR split automation: Taguchi parameter defaults ──────────────────────────
DEFAULT_MANUAL_DURATION_S = 1800.0  # fallback when Simod mean is unavailable
PCT_AUTO_LEVELS = [25, 50, 75]  # XOR1 branch % to bot
PCT_OK_LEVELS = [80, 90, 95]  # XOR2 success %
T_AUTO_FRACTIONS = [0.05, 0.10, 0.20]  # bot duration as fraction of manual mean
T_MANUAL_FACTORS = [0.80, 1.00, 1.20]  # manual duration as factor of Simod mean
NUM_BOTS_LEVELS = [1, 2, 3]  # bot resource pool size
NUM_MANUAL_LEVELS = [1, 2, 3]  # human resource pool size
