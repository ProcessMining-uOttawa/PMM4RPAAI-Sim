"""Constants for the automation bypass pattern."""

# ── Bot resource profile ──────────────────────────────────────────────────────
BOT_PROFILE_ID   = "BOT_PROFILE"
BOT_PROFILE_NAME = "Bot Resources"

# ── Bot resource defaults ─────────────────────────────────────────────────────
BOT_COST_PER_HOUR = "0"
BOT_AMOUNT        = 1

# ── Bot calendar ──────────────────────────────────────────────────────────────
BOT_CALENDAR_ID   = "BOT_CALENDAR"
BOT_CALENDAR_NAME = "Bot 24/7 Schedule"
BOT_CALENDAR_FROM  = "MONDAY"
BOT_CALENDAR_TO    = "SUNDAY"
BOT_CALENDAR_BEGIN = "00:00:00.000"
BOT_CALENDAR_END   = "23:59:59.999"

# ── Bot task distribution defaults ────────────────────────────────────────────
BOT_DISTRIBUTION_NAME  = "fix"
BOT_DISTRIBUTION_VALUE = 0.0

# ── Gateway display names ─────────────────────────────────────────────────────
GW1_NAME = "Bot or Human?"
GW2_NAME = "Bot succeeded?"
GW3_NAME = "Human needed"
GW4_NAME = "Exit"

# ── Sequence flow display labels ──────────────────────────────────────────────
F_BOT_BRANCH_LABEL   = "bot"
F_HUMAN_BRANCH_LABEL = "human"
F_BOT_SUCCESS_LABEL  = "success"
F_BOT_FAILURE_LABEL  = "failure"
