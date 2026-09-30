"""Pull part/qty data from the 'Order Here' sheet and render printable labels."""

import argparse
import sys
from collections import Counter

from config import (
    SHEET_ID, OUTPUT_PDF, MANIFEST_PATH, LOT_COUNTS_PATH, LOT_COUNTS_PDF_PATH, PER_PERSON_DIR,
    PARTS_PATH, PARTS_PDF_PATH, CHECKLIST_PDF_PATH, TEST_PAGE_PATH, LABEL_SPECS, ACTIVE_LABEL_SPEC, WEIGHT_OVERRIDES, find_label_spec,
    BRICKLINK_CREDENTIALS,
)
import bricklink
from version import __version__
import colors
from render_labels import (
    LABEL_PARTS, LabelOptions, build_pdf, build_per_person_pdfs, build_test_page,
)
from ordering import PART_ORDERS, order_records, summarize_parts
from manifest import (
    build_summary, write_manifest_csv, write_lot_counts_csv, write_lot_counts_pdf,
    write_checklist_pdf, write_parts_csv, write_parts_pdf, person_sort_key, SORT_CHOICES,
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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
        "--parts", action="store_true",
        help=f"Write a parts list ({PARTS_PATH} and {PARTS_PDF_PATH}): each part's "
             "total pieces and how many people ordered it, in label order. No label "
             "images needed; can be combined with --lot-counts.",
    )
    parser.add_argument(
        "--part-order", choices=PART_ORDERS, default="heaviest",
        help="How to order parts on the labels and parts list (default: heaviest "
             "first). Within a part, labels always go smallest qty first.",
    )
    parser.add_argument(
        "--no-bricklink", action="store_true",
        help="Don't look parts up on BrickLink (weights for part order, and colors "
             "the sheet is missing), even if BRICKLINK credentials are configured.",
    )
    parser.add_argument(
        "--label-spec", default=ACTIVE_LABEL_SPEC, metavar="STOCK",
        help=f"Label stock to print on, by part number — e.g. avery5162, 8162, "
             f"avery5160, dymo30857 (default: {ACTIVE_LABEL_SPEC}). Any equivalent "
             f"part number works; see --list-labels.",
    )
    parser.add_argument(
        "--hide", metavar="PARTS", default="",
        help=f"Comma-separated label parts to leave off: {', '.join(LABEL_PARTS)}. "
             f"Everything but qr is on by default.",
    )
    parser.add_argument(
        "--show", metavar="PARTS", default="",
        help="Comma-separated label parts to turn on, e.g. --show qr for a QR code "
             "linking to the part on BrickLink.",
    )
    parser.add_argument(
        "--sample", action="store_true",
        help="Use built-in sample orders instead of a sheet — for trying out a "
             "label design (--hide/--show/--label-spec) before a real run.",
    )
    parser.add_argument(
        "--checklist", action="store_true",
        help=f"Also write {CHECKLIST_PDF_PATH}: one page per person listing their parts "
             "with tick boxes, for packing.",
    )
    parser.add_argument(
        "--test-page", action="store_true",
        help=f"Write {TEST_PAGE_PATH} — the label outlines for --label-spec, to print "
             "on plain paper and check printer alignment — and exit.",
    )
    parser.add_argument(
        "--list-labels", action="store_true",
        help="List every supported Avery and Dymo label stock and exit.",
    )
    parser.add_argument(
        "--sort-by", choices=SORT_CHOICES, default="last",
        help="Sort people by first or last name in reports (default: last).",
    )
    parser.add_argument(
        "--source-file", metavar="PATH",
        help="Read order data from a local .xlsx file instead of the Google "
             "Sheet (e.g. a downloaded export). Columns are matched by "
             "header name, so the file's exact layout doesn't need to match "
             "the live sheet's.",
    )
    parser.add_argument(
        "--sheet-id", metavar="ID",
        help="Google Sheet to read for this run, overriding SHEET_ID in config_local.py "
             "(the long ID in the sheet's URL, between /d/ and /edit).",
    )
    parser.add_argument(
        "--output", metavar="PATH",
        help=f"Output PDF filename for this run, overriding OUTPUT_PDF "
             f"(default: {OUTPUT_PDF}). Only affects the combined label PDF "
             f"— --manifest/--lot-counts filenames are unchanged.",
    )
    args = parser.parse_args()
    try:
        args.label_options = LabelOptions.parse(args.hide, args.show)
    except ValueError as e:
        parser.error(str(e))
    if not args.list_labels:
        spec = find_label_spec(args.label_spec)
        if spec is None:
            parser.error(f"unknown label stock '{args.label_spec}' — see --list-labels")
        args.label_spec = spec
    return args


def list_labels() -> None:
    """Print the label inventory, grouped by brand and page size."""
    group = None
    for sid, s in LABEL_SPECS.items():
        if (s["brand"], s["page"]) != group:
            group = (s["brand"], s["page"])
            print(f"\n{s['brand']} — {'LabelWriter rolls' if s['page'] == 'roll' else s['page']}")
        w, h = s["label_width_mm"] / 25.4, s["label_height_mm"] / 25.4
        per = "roll" if s["page"] == "roll" else f"{s['columns'] * s['rows']}/sheet"
        also = f"  (also {', '.join(s['equivalents'])})" if s["equivalents"] else ""
        print(f"  {sid:14} {h:.2f}\" x {w:.2f}\"  {per:9} {s['description']}{also}")


def apply_bricklink(records, issues) -> dict[str, float]:
    """Look every part up on BrickLink (cached): returns element ID -> catalog
    weight, and fills in BrickLink/LEGO color names the sheet left blank."""
    creds = bricklink.Credentials(**BRICKLINK_CREDENTIALS)
    found, error = bricklink.lookup({r.element_id for r in records}, creds)
    if error:
        print(f"BrickLink: {error} — using cached/estimated weights for the rest.")

    filled = set()
    for r in records:
        info = found.get(r.element_id)
        if info and info.color and not r.bl_color:
            r.bl_color = info.color
            r.lego_color = r.lego_color or colors.resolve("", info.color)[0]
            filled.add(r.element_id)
    # A color BrickLink supplied is no longer missing.
    issues[:] = [i for i in issues if not (i.kind == "missing_color" and i.element_id in filled)]
    return {e: info.weight for e, info in found.items() if info.weight is not None}


def main():
    # Sheet text can hold characters a Windows console can't show; print a
    # placeholder rather than crash.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = parse_args()
    if args.list_labels:
        list_labels()
        return

    if args.test_page:
        build_test_page(TEST_PAGE_PATH, args.label_spec)
        print(f"Wrote {TEST_PAGE_PATH} — print it at 100% scale on plain paper and hold it "
              f"against a sheet of {args.label_spec} labels")
        return

    # Imported here so --help works without the Google/openpyxl deps.
    if args.sample:
        from samples import sample_records
        records, issues = sample_records(), []
    elif args.source_file:
        from xlsx_source import validate_source as validate_xlsx
        records, issues = validate_xlsx(args.source_file)
        if not records:
            sys.exit(f"No label records found in '{args.source_file}' — check the tab layout.")
    else:
        sheet_id = args.sheet_id or SHEET_ID
        if not sheet_id:
            sys.exit("Set SHEET_ID in config_local.py first (see config_local.example.py), "
                     "or pass --sheet-id or --source-file.")
        from sheets_source import validate_sheet
        records, issues = validate_sheet(sheet_id)
        if not records:
            sys.exit("No label records found — check SOURCE_TAB and sheet sharing permissions.")

    bl_weights = {}
    if BRICKLINK_CREDENTIALS and not args.no_bricklink and not args.sample:
        bl_weights = apply_bricklink(records, issues)

    records = order_records(records, WEIGHT_OVERRIDES, args.part_order,
                            person_key=lambda p: person_sort_key(p, args.sort_by),
                            bricklink=bl_weights)
    parts = summarize_parts(records, WEIGHT_OVERRIDES, args.part_order, bl_weights)

    if args.validate:
        print(build_summary(records, issues, args.label_spec, parts, sort_by=args.sort_by))
        return

    if args.parts:
        write_parts_csv(parts, PARTS_PATH)
        write_parts_pdf(parts, PARTS_PDF_PATH)
        print(f"Wrote {PARTS_PATH} and {PARTS_PDF_PATH}")
        if not args.lot_counts:
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

    output_pdf = args.output or OUTPUT_PDF
    count = build_pdf(records, output_pdf, spec_name=args.label_spec,
                      opts=args.label_options)
    print(f"Wrote {count} labels to {output_pdf}")

    if args.per_person:
        counts = build_per_person_pdfs(records, PER_PERSON_DIR, spec_name=args.label_spec,
                                       opts=args.label_options)
        print(f"Wrote {len(counts)} per-person PDFs to {PER_PERSON_DIR}/")

    if args.checklist:
        write_checklist_pdf(records, CHECKLIST_PDF_PATH, sort_by=args.sort_by)
        print(f"Wrote {CHECKLIST_PDF_PATH}")

    if args.manifest:
        summary_path = MANIFEST_PATH.rsplit(".", 1)[0] + ".txt"
        with open(summary_path, "w") as f:
            f.write(build_summary(records, issues, args.label_spec, parts, sort_by=args.sort_by))
        write_manifest_csv(records, MANIFEST_PATH, sort_by=args.sort_by)
        print(f"Wrote {summary_path} and {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
