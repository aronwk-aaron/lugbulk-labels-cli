"""Pull part/qty data from the 'Order Here' sheet and render printable labels."""

import sys

from config import SHEET_ID, OUTPUT_PDF
from sheets_source import get_label_records
from render_labels import build_pdf


def main():
    if not SHEET_ID:
        sys.exit("Set SHEET_ID in config.py first.")

    records = get_label_records()
    if not records:
        sys.exit("No label records found — check SOURCE_TAB and sheet sharing permissions.")

    count = build_pdf(records, OUTPUT_PDF)
    print(f"Wrote {count} labels to {OUTPUT_PDF}")


if __name__ == "__main__":
    main()
