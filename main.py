"""Pull part/qty data from the 'Order Here' sheet and render printable labels."""

import argparse
import sys
from collections import Counter

from config import (
    SHEET_ID, OUTPUT_PDF, MANIFEST_PATH, LOT_COUNTS_PATH, LOT_COUNTS_PDF_PATH, PER_PERSON_DIR,
    LABEL_SPECS, ACTIVE_LABEL_SPEC,
)
from sheets_source import validate_sheet
from render_labels import build_pdf, build_per_person_pdfs
from manifest import (
    build_summary, write_manifest_csv, write_lot_counts_csv, write_lot_counts_pdf,
    person_sort_key, SORT_CHOICES,
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate", action="store_true",
        help="Check the sheet for data problems and print a report. Does not "
             "download images or write a PDF.",
    )
    parser.add_argument(
        "--manifest", action="store_true",
        help=f"Also write a summary report ({MANIFEST_PATH.replace('.csv', '.txt')}) "
             f"and a flat CSV ({MANIFEST_PATH}).",
    )
    parser.add_argument(
        "--per-person", action="store_true",
        help=f"Also write one label PDF per person into {PER_PERSON_DIR}/.",
    )
    parser.add_argument(
        "--lot-counts", action="store_true",
        help=f"Print (and write to {LOT_COUNTS_PATH} and {LOT_COUNTS_PDF_PATH}) each "
             "person's lot count (number of labels) and total pieces. No label "
             "images needed.",
    )
    parser.add_argument(
        "--label-spec", choices=sorted(LABEL_SPECS), default=ACTIVE_LABEL_SPEC,
        help=f"Label sheet format to use (default: {ACTIVE_LABEL_SPEC}).",
    )
    parser.add_argument(
        "--sort-by", choices=SORT_CHOICES, default="last",
        help="Sort people by first or last name in reports (default: last).",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not SHEET_ID:
        sys.exit("Set SHEET_ID in config_local.py first (see config_local.example.py).")

    records, issues = validate_sheet()
    if not records:
        sys.exit("No label records found — check SOURCE_TAB and sheet sharing permissions.")

    if args.validate:
        print(build_summary(records, issues, args.label_spec, sort_by=args.sort_by))
        return

    if args.lot_counts:
        write_lot_counts_csv(records, LOT_COUNTS_PATH, sort_by=args.sort_by)
        write_lot_counts_pdf(records, LOT_COUNTS_PDF_PATH, sort_by=args.sort_by)
        lots = Counter(r.person for r in records)
        for person, count in sorted(
            lots.items(), key=lambda kv: person_sort_key(kv[0], args.sort_by)
        ):
            print(f"{person}: {count}")
        print(f"\nWrote {LOT_COUNTS_PATH} and {LOT_COUNTS_PDF_PATH}")
        return

    if issues:
        print(f"Note: {len(issues)} issue(s) found on the sheet — run with --validate for details.")

    count = build_pdf(records, OUTPUT_PDF, spec_name=args.label_spec)
    print(f"Wrote {count} labels to {OUTPUT_PDF}")

    if args.per_person:
        counts = build_per_person_pdfs(records, PER_PERSON_DIR, spec_name=args.label_spec)
        print(f"Wrote {len(counts)} per-person PDFs to {PER_PERSON_DIR}/")

    if args.manifest:
        summary_path = MANIFEST_PATH.rsplit(".", 1)[0] + ".txt"
        with open(summary_path, "w") as f:
            f.write(build_summary(records, issues, args.label_spec, sort_by=args.sort_by))
        write_manifest_csv(records, MANIFEST_PATH, sort_by=args.sort_by)
        print(f"Wrote {summary_path} and {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
