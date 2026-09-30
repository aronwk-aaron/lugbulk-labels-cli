"""Local, event-specific config — copy this file to config_local.py and fill
in real values. config_local.py is gitignored and never committed.

Only needed for the Google Sheets path; --source-file runs work without it.
"""

# From the sheet's URL: https://docs.google.com/spreadsheets/d/<THIS_PART>/edit
SHEET_ID = ""

# Manual color corrections, keyed by Element ID. COLOR_OVERRIDES replaces
# the BrickLink name, LEGO_COLOR_OVERRIDES the LEGO name. Use for entries
# the sheet has blank/"unknown", or that --validate reports as unmapped.
COLOR_OVERRIDES = {
    # "6584805": "Warm Pink",
}
LEGO_COLOR_OVERRIDES = {
    # "6584805": "Warm Pink",
}

# Grams per piece, keyed by Element ID, for ordering parts heaviest-first
# where the description has no stud dimensions to estimate from (plants,
# animals, minifig parts...). --validate / --parts list those as "size unknown".
WEIGHT_OVERRIDES = {
    # "6584302": 0.6,  # frog
}

# Optional: where BrickLink's catalog download files live (default
# "bricklink" next to the program) — see README.md "BrickLink weights".
# BRICKLINK_DIR = "bricklink"

# Output PDF filename for this event. Optional — falls back to a generic
# name in config.py if omitted.
# OUTPUT_PDF = "ArkLUG-2026-LUGBulk-labels.pdf"
