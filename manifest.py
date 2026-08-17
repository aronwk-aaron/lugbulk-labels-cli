"""Build a human-readable summary of a label run: per-person totals, per-part
totals, label-sheet capacity, and any data issues noticed on the sheet.

Written as plain text (for reading before you print) and CSV (for dropping
into a spreadsheet) — both derived from the same LabelRecords/SheetIssues
that produced (or would produce) the label PDF.
"""

import csv
from collections import Counter

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from config import LABEL_SPECS
from sheets_source import LabelRecord, SheetIssue


def _sheets_needed(label_count: int, spec_name: str) -> int:
    per_sheet = LABEL_SPECS[spec_name]["columns"] * LABEL_SPECS[spec_name]["rows"]
    return -(-label_count // per_sheet) if label_count else 0  # ceil division


SORT_CHOICES = ("last", "first")


def person_sort_key(person: str, sort_by: str = "last"):
    """Sort key for a "First Last" name. sort_by="last" sorts by the last
    whitespace-separated token (falls back to the full name for anything
    that isn't First-Last, e.g. a single-word entry); sort_by="first" sorts
    by the name as written. Either way, ties break on the full name."""
    parts = person.split()
    primary = (parts[-1].lower() if parts and sort_by == "last" else person.lower())
    return (primary, person.lower())


def build_summary(
    records: list[LabelRecord], issues: list[SheetIssue], spec_name: str,
    sort_by: str = "last",
) -> str:
    """Plain-text report: totals, capacity, and any issues found."""
    per_person_qty = Counter()
    per_person_lots = Counter()
    per_part = Counter()
    for r in records:
        qty = float(r.qty.replace(",", ""))  # sheet may format large qtys as "2,000"
        per_person_qty[r.person] += qty
        per_person_lots[r.person] += 1  # one lot = one label = one (person, part) line
        per_part[(r.element_id, r.description)] += qty

    per_sheet = LABEL_SPECS[spec_name]["columns"] * LABEL_SPECS[spec_name]["rows"]
    sheets = _sheets_needed(len(records), spec_name)

    lines = []
    lines.append("=== Label run summary ===")
    lines.append(f"{len(records)} labels, {len(per_person_qty)} people, {len(per_part)} distinct parts")
    lines.append(f"Label format: {spec_name} ({per_sheet}/sheet) -> {sheets} sheet(s) needed")
    lines.append("")

    lines.append(f"--- Per person, by {sort_by} name (lot count / total pieces) ---")
    for person, total in sorted(
        per_person_qty.items(), key=lambda kv: person_sort_key(kv[0], sort_by)
    ):
        lines.append(f"  {person}: {per_person_lots[person]} lots, {total:g} pieces")
    lines.append("")

    lines.append("--- Per part (total pieces across all people) ---")
    for (element_id, desc), total in sorted(per_part.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {element_id}  {desc}: {total:g}")
    lines.append("")

    if issues:
        lines.append(f"--- {len(issues)} issue(s) found on the sheet ---")
        for issue in issues:
            lines.append(f"  [row {issue.row}] {issue.kind}: {issue.detail}")
    else:
        lines.append("--- No issues found ---")

    return "\n".join(lines) + "\n"


def write_manifest_csv(records: list[LabelRecord], path: str, sort_by: str = "last") -> None:
    """One row per label record — the flat data behind the summary, for
    spot-checking in a spreadsheet."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["person", "element_id", "description", "color", "qty"])
        for r in sorted(
            records, key=lambda r: (person_sort_key(r.person, sort_by), r.element_id)
        ):
            writer.writerow([r.person, r.element_id, r.description, r.color, r.qty])


def write_lot_counts_csv(records: list[LabelRecord], path: str, sort_by: str = "last") -> None:
    """One row per person: how many lots (label lines) and total pieces they have.
    A 'lot' here is one (person, part) line item — one printed label."""
    lots = Counter()
    pieces = Counter()
    for r in records:
        lots[r.person] += 1
        pieces[r.person] += float(r.qty.replace(",", ""))

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["person", "lot_count", "total_pieces"])
        for person in sorted(lots, key=lambda p: person_sort_key(p, sort_by)):
            writer.writerow([person, lots[person], f"{pieces[person]:g}"])


def write_lot_counts_pdf(records: list[LabelRecord], path: str, sort_by: str = "last") -> None:
    """One-page-per-however-many-fit table: person / lot count / total pieces,
    for handing someone a printable list instead of a spreadsheet."""
    lots = Counter()
    pieces = Counter()
    for r in records:
        lots[r.person] += 1
        pieces[r.person] += float(r.qty.replace(",", ""))

    people = sorted(lots, key=lambda p: person_sort_key(p, sort_by))

    styles = getSampleStyleSheet()
    story = [
        Paragraph("Lot counts by person", styles["Title"]),
        Paragraph(
            f"{len(people)} people, {sum(lots.values())} lots total &mdash; sorted by {sort_by} name",
            styles["Normal"],
        ),
        Spacer(1, 6 * mm),
    ]

    data = [["Person", "Lots", "Total pieces"]]
    for person in people:
        data.append([person, str(lots[person]), f"{pieces[person]:g}"])

    table = Table(data, colWidths=[100 * mm, 30 * mm, 40 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.whitesmoke]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)

    doc = SimpleDocTemplate(
        path, pagesize=letter,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
    )
    doc.build(story)
