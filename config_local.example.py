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
