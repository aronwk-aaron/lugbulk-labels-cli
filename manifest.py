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
from ordering import PartSummary
from records import LabelRecord, SheetIssue


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
    parts: list[PartSummary], sort_by: str = "last",
) -> str:
    """Plain-text report: totals, capacity, and any issues found. `parts`
    is ordering.summarize_parts output, listed in label order."""
    per_person_qty = Counter()
    per_person_lots = Counter()
    for r in records:
        per_person_qty[r.person] += float(r.qty)
        per_person_lots[r.person] += 1  # one lot = one label = one (person, part) line

    per_sheet = LABEL_SPECS[spec_name]["columns"] * LABEL_SPECS[spec_name]["rows"]
    sheets = _sheets_needed(len(records), spec_name)

    lines = []
    lines.append("=== Label run summary ===")
    lines.append(f"{len(records)} labels, {len(per_person_qty)} people, {len(parts)} distinct parts")
    lines.append(f"Label format: {spec_name} ({per_sheet}/sheet) -> {sheets} sheet(s) needed")
    lines.append("")

    lines.append(f"--- Per person, by {sort_by} name (lot count / total pieces) ---")
    for person, total in sorted(
        per_person_qty.items(), key=lambda kv: person_sort_key(kv[0], sort_by)
    ):
        lines.append(f"  {person}: {per_person_lots[person]} lots, {total:g} pieces")
    lines.append("")

    lines.append("--- Per part, in label order (pieces / people ordering / weight) ---")
    for p in parts:
        lines.append(f"  {p.element_id}  {p.description}: {p.pieces:g} pieces, "
                     f"{p.lots} people, {_weight_text(p)}")
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
        writer.writerow(["person", "element_id", "description", "lego_color", "bl_color",
                         "qty", "label"])
        for r in sorted(
            records, key=lambda r: (person_sort_key(r.person, sort_by), r.element_id)
        ):
            writer.writerow([_csv_safe(v) for v in (
                r.person, r.element_id, r.description, r.lego_color, r.bl_color, r.qty,
                f"{r.part_seq} of {r.part_total}",
            )])


def write_lot_counts_csv(records: list[LabelRecord], path: str, sort_by: str = "last") -> None:
    """One row per person: how many lots (label lines) and total pieces they have.
    A 'lot' here is one (person, part) line item — one printed label."""
    lots = Counter()
    pieces = Counter()
    for r in records:
        lots[r.person] += 1
        pieces[r.person] += float(r.qty)

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["person", "lot_count", "total_pieces"])
        for person in sorted(lots, key=lambda p: person_sort_key(p, sort_by)):
            writer.writerow([_csv_safe(person), lots[person], f"{pieces[person]:g}"])


def write_lot_counts_pdf(records: list[LabelRecord], path: str, sort_by: str = "last") -> None:
    """One-page-per-however-many-fit table: person / lot count / total pieces,
    for handing someone a printable list instead of a spreadsheet."""
    lots = Counter()
    pieces = Counter()
    for r in records:
        lots[r.person] += 1
        pieces[r.person] += float(r.qty)

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
    table.setStyle(_TABLE_STYLE)
    story.append(table)
    _build_doc(path, story)


def _weight_text(p: PartSummary) -> str:
    if p.weight is None:
        return "size unknown"
    grams = f"{p.weight:.0f}" if p.weight >= 10 else f"{p.weight:.2g}"
    return f"{'~' if p.weight_source == 'estimate' else ''}{grams} g/pc"


def write_parts_csv(parts: list[PartSummary], path: str) -> None:
    """One row per part, in label order: how many pieces in total and how
    many people ordered it (= how many labels / bags to split it into)."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["order", "element_id", "description", "lego_color", "bl_color",
                         "total_pieces", "people", "grams_per_piece", "weight_source"])
        for i, p in enumerate(parts, start=1):
            writer.writerow([i] + [_csv_safe(v) for v in (
                p.element_id, p.description, p.lego_color, p.bl_color)] + [
                f"{p.pieces:g}", p.lots, "" if p.weight is None else f"{p.weight:.3g}",
                p.weight_source])


def write_parts_pdf(parts: list[PartSummary], path: str) -> None:
    """Printable parts list: one row per part, in label order."""
    styles = getSampleStyleSheet()
    cell = styles["BodyText"].clone("cell", fontSize=8, leading=9.5)
    total_pieces = sum(p.pieces for p in parts)
    story = [
        Paragraph("Parts list", styles["Title"]),
        Paragraph(
            f"{len(parts)} parts, {total_pieces:g} pieces, {sum(p.lots for p in parts)} labels "
            "&mdash; in label order", styles["Normal"]),
        Spacer(1, 6 * mm),
    ]
    data = [["#", "Element", "Description", "LEGO / BrickLink color", "Pieces", "People",
             "Weight"]]
    for i, p in enumerate(parts, start=1):
        data.append([
            str(i), p.element_id, Paragraph(_xml_escape(p.description), cell),
            Paragraph(_xml_escape(" / ".join(c for c in (p.lego_color, p.bl_color) if c)), cell),
            f"{p.pieces:g}", str(p.lots), _weight_text(p),
        ])
    table = Table(data, colWidths=[8 * mm, 18 * mm, 52 * mm, 48 * mm, 16 * mm, 14 * mm, 24 * mm],
                  repeatRows=1)
    table.setStyle(_TABLE_STYLE)
    story.append(table)
    _build_doc(path, story)


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _csv_safe(value) -> str:
    """Neutralize spreadsheet formula injection (CWE-1236): names and
    descriptions come from a shared sheet anyone with edit access can
    change, and a cell like "=HYPERLINK(...)" would run when the CSV is
    opened in Excel/Sheets."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _build_doc(path: str, story: list) -> None:
    doc = SimpleDocTemplate(
        path, pagesize=letter,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
    )
    doc.build(story)


_TABLE_STYLE = TableStyle([
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ("FONTSIZE", (0, 0), (-1, -1), 9),
    ("ALIGN", (1, 0), (-1, -1), "CENTER"),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.whitesmoke]),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
])
