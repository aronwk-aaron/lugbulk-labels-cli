"""Configuration for the Sheets -> label PDF pipeline.

Event-specific values (SHEET_ID, COLOR_OVERRIDES) live in config_local.py,
which is gitignored — copy config_local.example.py to get started.
"""

try:
    from config_local import SHEET_ID, COLOR_OVERRIDES
except ImportError:
    raise SystemExit(
        "config_local.py not found. Run: cp config_local.example.py config_local.py "
        "and fill in SHEET_ID (see README.md)."
    )

# --- Google Sheets (READ-ONLY: never write/update/append to this sheet) ---
SOURCE_TAB = "Order Here"
SERVICE_ACCOUNT_FILE = "service_account.json"  # path to the downloaded key, keep out of git

# --- "Order Here" tab layout (0-indexed columns) ---
COL_ELEMENT_ID = 1
COL_DESCRIPTION = 3
COL_COLOR = 4
FIRST_PERSON_COL = 7    # 'qty' column for the first person
LAST_PERSON_COL = 89    # 'qty' column for the last person (inclusive)
PERSON_COL_STRIDE = 2   # each person occupies (qty, $cost) = 2 columns
HEADER_ROW = 0          # person names live here
DATA_START_ROW = 2      # first row of actual part data

# LEGO element photo CDN — built from Element ID, since the sheet's own
# Photo column is an in-cell =IMAGE() formula the Sheets API can't return.
IMAGE_URL_TEMPLATE = (
    "https://www.lego.com/cdn/product-assets/element.img.lod5photo.192x192/{element_id}.jpg"
)

# --- Label sheet layout (Avery 5160: 1" x 2-5/8", 3 across x 10 down, 30/sheet) ---
LABEL_SPECS = {
    "avery5160": dict(
        sheet_width=215.9, sheet_height=279.4,  # US Letter, mm
        columns=3, rows=10,
        label_width=66.675, label_height=25.4,  # mm
        corner_radius=2,
        left_margin=4.7625, right_margin=4.7625,
        top_margin=12.7, bottom_margin=12.7,
        row_gap=0, column_gap=3.175,
    ),
}
ACTIVE_LABEL_SPEC = "avery5160"

# --- Output ---
OUTPUT_PDF = "labels.pdf"
IMAGE_CACHE_DIR = "image_cache"
