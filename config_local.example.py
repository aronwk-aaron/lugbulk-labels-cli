"""Local, event-specific config — copy this file to config_local.py and fill
in real values. config_local.py is gitignored and never committed.
"""

# From the sheet's URL: https://docs.google.com/spreadsheets/d/<THIS_PART>/edit
SHEET_ID = ""

# Manual color corrections, keyed by Element ID, applied on top of the sheet's
# own "BL Color" lookup. Use for entries the sheet reports as "unknown"/blank.
COLOR_OVERRIDES = {
    # "6584805": "Warm Pink",
}

# Output PDF filename for this event. Optional — falls back to a generic
# name in config.py if omitted.
# OUTPUT_PDF = "ArkLUG-2026-LUGBulk-labels.pdf"
