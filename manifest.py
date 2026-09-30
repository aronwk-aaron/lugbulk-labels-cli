"""Build a human-readable summary of a label run: per-person totals, per-part
totals, label-sheet capacity, and any data issues noticed on the sheet.

Written as plain text (for reading before you print) and CSV (for dropping
into a spreadsheet) — both derived from the same LabelRecords/SheetIssues
that produced (or would produce) the label PDF.
"""

import csv
from collections import Counter
from dataclasses import dataclass, field

from reportlab.graphics.shapes import Drawing, Rect
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    CondPageBreak, Flowable, Image, PageBreak, SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer,
)
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

from config import LABEL_SPECS
from ordering import PartSummary, summarize_parts
from report_options import DEFAULTS, page_size
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


@dataclass
class ReportContext:
    """What the reports need beyond the label-ordered records they're given:
    the records in sheet order (for "sheet" part order) and the weight
    sources (for "heaviest"/"lightest" and the weight columns). Without it,
    sheet order falls back to label order and only sheet/estimated weights
    are known."""
    sheet_records: list | None = None
    overrides: dict = field(default_factory=dict)
    bricklink: dict = field(default_factory=dict)


_NO_CONTEXT = ReportContext()


def _section(name: str, opts: dict | None) -> dict:
    """A report's options: its section of the report options, with the
    defaults for anything left out."""
    return {**DEFAULTS[name], **(opts or {})}


def _by_weight(parts: list[PartSummary], order: str) -> list[PartSummary]:
    sign = -1 if order == "heaviest" else 1
    # Stable: unknown-weight parts keep their order after the rest.
    return sorted(parts, key=lambda p: (p.weight is None, sign * (p.weight or 0)))


def ordered_parts(parts: list[PartSummary], order: str = "labels",
                  context: ReportContext | None = None) -> list[PartSummary]:
    """`parts` (in label order) in a report's order: "labels" (as given),
    "heaviest", "lightest", "sheet" (first appearance on the sheet) or
    "element" (by element ID, numerically)."""
    ctx = context or _NO_CONTEXT
    if order == "labels":
        return list(parts)
    base = (summarize_parts(ctx.sheet_records, ctx.overrides, "sheet", ctx.bricklink)
            if ctx.sheet_records else list(parts))
    if order == "sheet":
        return base
    if order == "element":
        return sorted(base, key=lambda p: (len(p.element_id), p.element_id))
    return _by_weight(base, order)


def _label_order_parts(records: list[LabelRecord], ctx: ReportContext) -> list[PartSummary]:
    return summarize_parts(records, ctx.overrides, "sheet", ctx.bricklink)


def ordered_records(records: list[LabelRecord], order: str = "labels",
                    context: ReportContext | None = None) -> list[LabelRecord]:
    """`records` (in label order) grouped by part in a report's order. Within
    a part they keep their label order."""
    ctx = context or _NO_CONTEXT
    if order == "labels":
        return list(records)
    rank = {p.element_id: i for i, p in enumerate(
        ordered_parts(_label_order_parts(records, ctx), order, ctx))}
    return sorted(records, key=lambda r: rank[r.element_id])  # stable


def _lot_totals(records: list[LabelRecord], sort_by: str, ctx: ReportContext) -> list[dict]:
    """One dict per person, in name order: lots, pieces and total weight
    (grams of the parts with a known weight; `estimated` if any of those is
    an estimate, `unknown` if some part has no weight)."""
    parts = {p.element_id: p for p in _label_order_parts(records, ctx)}
    totals: dict[str, dict] = {}
    for r in records:
        t = totals.setdefault(r.person, {"person": r.person, "lots": 0, "pieces": 0.0,
                                         "grams": 0.0, "estimated": False, "unknown": False})
        qty = float(r.qty)
        t["lots"] += 1
        t["pieces"] += qty
        p = parts.get(r.element_id)
        if p is not None and p.weight is not None:
            t["grams"] += qty * p.weight
            t["estimated"] = t["estimated"] or p.weight_source == "estimate"
        else:
            t["unknown"] = True
    return sorted(totals.values(), key=lambda t: person_sort_key(t["person"], sort_by))


def _mass_text(grams: float) -> str:
    return f"{grams:.0f} g" if grams < 1000 else f"{grams / 1000:.2f} kg"


def _total_mass_text(t: dict) -> str:
    """"~1.20 kg+": "~" when part of it is estimated, "+" when some parts'
    weights aren't known."""
    if t["grams"] == 0 and t["unknown"]:
        return "?"
    return f"{'~' if t['estimated'] else ''}{_mass_text(t['grams'])}{'+' if t['unknown'] else ''}"


def write_lot_counts_csv(records: list[LabelRecord], path: str, sort_by: str | None = None,
                         opts: dict | None = None) -> None:
    """One row per person: how many lots (label lines) and total pieces they have.
    A 'lot' here is one (person, part) line item — one printed label. With
    a minimum-lots option, people with fewer lots are left out."""
    o = _section("lots", opts)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["person", "lot_count", "total_pieces"])
        for t in _lot_totals(records, sort_by or o["sort"], _NO_CONTEXT):
            if t["lots"] >= o["min_lots"]:
                writer.writerow([_csv_safe(t["person"]), t["lots"], f"{t['pieces']:g}"])


def _fit_columns(widths: list[float], flex: list[bool], available: float) -> list[float]:
    """Column widths (points) for the page: as given when they fit (within
    5 pt over) and don't leave a lot of room (60 pt or more) unused;
    otherwise the flex column takes up the difference, and if that's not
    enough every column shrinks in proportion. (The web app's fitColumns.)"""
    total = sum(widths)
    if available - 60 <= total <= available + 5:
        return list(widths)
    flex_total = sum(w for w, f in zip(widths, flex) if f)
    out = list(widths)
    if flex_total > 0:
        diff = available - total
        out = [max(40.0, w + diff * w / flex_total) if f else w for w, f in zip(widths, flex)]
    now = sum(out)
    if now > available:
        out = [w * available / now for w in out]
    return out


_PADDING = 6  # the table style's left/right cell padding, points
_FIT_MARGIN = 2  # plain text may use the padding, leaving this much at each side


def _txt(text: str, width: float, style, bold: bool = False):
    """A table cell's text: the plain string when it fits its column, else
    a Paragraph that wraps, so nothing is ever cut off."""
    font = "Helvetica-Bold" if bold else "Helvetica"
    if stringWidth(text, font, 9) <= width - 2 * _FIT_MARGIN:
        return text
    return Paragraph(_xml_escape(text), style)


def _styles():
    base = getSampleStyleSheet()
    cell = base["BodyText"].clone("cell", fontSize=9, leading=11)
    bold = cell.clone("boldcell", fontName="Helvetica-Bold")
    return base, cell, bold


def _photo(element_id: str, url: str, width: float):
    """A part's cached photo scaled into a `width`-wide cell, or "" when
    there is none."""
    if not url:
        return ""
    from render_labels import _cached_image_path  # heavy imports, only for photos
    path = _cached_image_path(element_id, url)
    if not path:
        return ""
    try:
        w, h = ImageReader(path).getSize()
    except Exception:
        return ""
    box = width - 2 * _PADDING
    scale = min(box / w, box / h)
    return Image(path, w * scale, h * scale)


class _SignOff(Flowable):
    """A "Packed by: ____  Date: ____" line."""

    def wrap(self, avail_width, avail_height):
        return avail_width, 10 * mm

    def draw(self):
        c = self.canv
        c.setFont("Helvetica", 9)
        c.drawString(3, 8, "Packed by:")
        c.drawString(265, 8, "Date:")
        c.setLineWidth(0.6)
        c.line(52, 6, 250, 6)
        c.line(292, 6, 400, 6)


def _checkbox() -> Drawing:
    box = Drawing(10, 10)
    box.add(Rect(0, 0, 10, 10, fillColor=None, strokeColor=colors.black, strokeWidth=0.8))
    return box


_ORDER_WORDS = {
    "labels": "in label order", "heaviest": "heaviest first", "lightest": "lightest first",
    "sheet": "in sheet order", "element": "by element ID",
}


def write_checklist_pdf(records: list[LabelRecord], path: str, sort_by: str | None = None,
                        opts: dict | None = None, context: ReportContext | None = None) -> None:
    """Packing checklist: one page per person (in name order) listing their
    parts in label order, with a box to tick as each bag goes in. `opts` is
    the report options' "checklist" section (see report_options.py)."""
    o = _section("checklist", opts)
    sort_by = sort_by or o["sort"]
    ctx = context or _NO_CONTEXT
    styles, cell, bold = _styles()

    # (key, header, width in mm, flex) of each column shown.
    cols = []
    if o["checkbox"]:
        cols.append(("check", "", 9, False))
    if o["photo"]:
        cols.append(("photo", "Photo", 12, False))
    cols += [("element", "Element", 20, False), ("description", "Description", 58, True)]
    if o["color"]:
        cols.append(("color", "LEGO / BrickLink color", 52, False))
    if o["weight"]:
        cols.append(("weight", "Weight", 24, False))
    cols += [("qty", "Qty", 16, False), ("label", "Label", 20, False)]

    size = page_size(o)
    widths = _fit_columns([c[2] * mm for c in cols], [c[3] for c in cols], size[0] - 30 * mm)
    width_of = {c[0]: w for c, w in zip(cols, widths)}
    parts = {p.element_id: p for p in _label_order_parts(records, ctx)} if o["weight"] else {}

    by_person: dict[str, list[LabelRecord]] = {}
    for r in ordered_records(records, o["order"], ctx):
        by_person.setdefault(r.person, []).append(r)

    continuous = o["layout"] == "continuous"
    story = []
    for n, person in enumerate(sorted(by_person, key=lambda p: person_sort_key(p, sort_by))):
        items = by_person[person]
        pieces = sum(float(r.qty) for r in items)
        if n:
            story.append(Spacer(1, 6 * mm) if continuous else PageBreak())
        if continuous:
            story.append(CondPageBreak(50 * mm))  # a heading never ends a page alone
        story += [
            Paragraph(_xml_escape(person), styles["Title"]),
            Paragraph(f"{len(items)} lots, {pieces:g} pieces", styles["Normal"]),
            Spacer(1, 5 * mm),
        ]
        data = [[_txt(c[1], width_of[c[0]], bold, True) for c in cols]]
        for r in items:
            row = []
            for key, *_ in cols:
                w = width_of[key]
                if key == "check":
                    row.append(_checkbox())
                elif key == "photo":
                    row.append(_photo(r.element_id, r.image_url, w))
                elif key == "element":
                    row.append(_txt(r.element_id, w, cell))
                elif key == "description":
                    row.append(Paragraph(_xml_escape(r.description), cell))
                elif key == "color":
                    row.append(Paragraph(_xml_escape(
                        " / ".join(c for c in (r.lego_color, r.bl_color) if c)), cell))
                elif key == "weight":
                    p = parts.get(r.element_id)
                    row.append(_txt(_weight_text(p) if p else "size unknown", w, cell))
                elif key == "qty":
                    row.append(_txt(r.qty, w, cell))
                else:
                    row.append(_txt(f"{r.part_seq} of {r.part_total}" if r.part_total else "",
                                    w, cell))
            data.append(row)
        table = Table(data, colWidths=widths, repeatRows=1)
        table.setStyle(_TABLE_STYLE)
        story.append(table)
        if o["packed_by"]:
            story += [CondPageBreak(16 * mm), Spacer(1, 3 * mm), _SignOff()]
    if not story:
        story.append(Paragraph("No orders.", styles["Normal"]))
    header = (o["title"], o["subtitle"]) if o["title"] or o["subtitle"] else None
    _build_doc(path, story, size, title=o["title"], header=header)


def _weight_text(p: PartSummary) -> str:
    if p.weight is None:
        return "size unknown"
    grams = f"{p.weight:.0f}" if p.weight >= 10 else f"{p.weight:.2g}"
    return f"{'~' if p.weight_source == 'estimate' else ''}{grams} g/pc"


def write_parts_csv(parts: list[PartSummary], path: str, opts: dict | None = None,
                    context: ReportContext | None = None) -> None:
    """One row per part, in the parts list's order (label order unless the
    options say otherwise): how many pieces in total and how many people
    ordered it (= how many labels / bags to split it into)."""
    o = _section("parts", opts)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["order", "element_id", "description", "lego_color", "bl_color",
                         "total_pieces", "people", "grams_per_piece", "weight_source"])
        for i, p in enumerate(ordered_parts(parts, o["order"], context), start=1):
            writer.writerow([i] + [_csv_safe(v) for v in (
                p.element_id, p.description, p.lego_color, p.bl_color)] + [
                f"{p.pieces:g}", p.lots, "" if p.weight is None else f"{p.weight:.3g}",
                p.weight_source])


def _joined_colors(p: PartSummary) -> str:
    return " / ".join(c for c in (p.lego_color, p.bl_color) if c)


def write_parts_pdf(parts: list[PartSummary], path: str, opts: dict | None = None,
                    context: ReportContext | None = None) -> None:
    """Printable parts list: one row per part, in label order unless the
    options say otherwise. `parts` is in label order."""
    o = _section("parts", opts)
    parts = ordered_parts(parts, o["order"], context)
    styles = getSampleStyleSheet()
    cell = styles["BodyText"].clone("cell", fontSize=8, leading=9.5)
    bold = cell.clone("boldcell", fontName="Helvetica-Bold", fontSize=9, leading=11)

    def color_cells(p: PartSummary) -> list[str]:
        if o["lego_color"] and o["bl_color"]:
            return [_joined_colors(p)]
        return [p.lego_color] if o["lego_color"] else [p.bl_color] if o["bl_color"] else []

    color_key = lambda p: (color_cells(p) or [_joined_colors(p)])[0]  # noqa: E731
    if o["group_by_color"]:
        # Stable: parts keep their order within a color; no color sorts last.
        parts = sorted(parts, key=lambda p: (not color_key(p), color_key(p).lower()))

    cols = [("n", "#", 8, False)]
    if o["photo"]:
        cols.append(("photo", "Photo", 12, False))
    cols += [("element", "Element", 18, False), ("description", "Description", 52, True)]
    if o["lego_color"] and o["bl_color"]:
        cols.append(("color", "LEGO / BrickLink color", 48, False))
    elif o["lego_color"]:
        cols.append(("color", "LEGO color", 40, False))
    elif o["bl_color"]:
        cols.append(("color", "BrickLink color", 40, False))
    for key, header, w in (("pieces", "Pieces", 16), ("people", "People", 14),
                           ("weight", "Weight", 24), ("total_weight", "Total weight", 24)):
        if o[key]:
            cols.append((key, header, w, False))

    size = page_size(o)
    widths = _fit_columns([c[2] * mm for c in cols], [c[3] for c in cols], size[0] - 30 * mm)
    width_of = {c[0]: w for c, w in zip(cols, widths)}

    total_pieces = sum(p.pieces for p in parts)
    stats = (f"{len(parts)} parts, {total_pieces:g} pieces, {sum(p.lots for p in parts)} labels "
             f"&mdash; {_ORDER_WORDS[o['order']]}")
    if o["group_by_color"]:
        stats += ", grouped by color"
    title = o["title"] or "Parts list"
    story = [Paragraph(_xml_escape(title), styles["Title"])]
    if o["subtitle"]:
        story.append(Paragraph(_xml_escape(o["subtitle"]), styles["Normal"]))
    story += [Paragraph(stats, styles["Normal"]), Spacer(1, 6 * mm)]

    data = [[_txt(c[1], width_of[c[0]], bold, True) for c in cols]]
    style = list(_TABLE_STYLE.getCommands())
    group = None
    for i, p in enumerate(parts, start=1):
        if o["group_by_color"] and (group is None or color_key(p).lower() != group):
            group = color_key(p).lower()
            count = sum(1 for q in parts if color_key(q).lower() == group)
            label = f"{color_key(p) or 'No color'} ({count} part{'' if count == 1 else 's'})"
            r = len(data)
            data.append([_txt(label, sum(widths), bold, True)] + [""] * (len(cols) - 1))
            style += [("SPAN", (0, r), (-1, r)), ("BACKGROUND", (0, r), (-1, r), colors.Color(0.9, 0.9, 0.9)),
                      ("ALIGN", (0, r), (-1, r), "LEFT"), ("FONTNAME", (0, r), (-1, r), "Helvetica-Bold")]
        row = []
        for key, *_ in cols:
            w = width_of[key]
            if key == "n":
                row.append(_txt(str(i), w, cell))
            elif key == "photo":
                row.append(_photo(p.element_id, p.image_url, w))
            elif key == "element":
                row.append(_txt(p.element_id, w, cell))
            elif key == "description":
                row.append(Paragraph(_xml_escape(p.description), cell))
            elif key == "color":
                row.append(Paragraph(_xml_escape(color_cells(p)[0]), cell))
            elif key == "pieces":
                row.append(_txt(f"{p.pieces:g}", w, cell))
            elif key == "people":
                row.append(_txt(str(p.lots), w, cell))
            elif key == "weight":
                row.append(_txt(_weight_text(p), w, cell))
            else:
                row.append(_txt("?" if p.weight is None else
                                f"{'~' if p.weight_source == 'estimate' else ''}"
                                f"{_mass_text(p.weight * p.pieces)}", w, cell))
        data.append(row)
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle(style))
    story.append(table)
    _build_doc(path, story, size, title=o["title"])


def write_lot_counts_pdf(records: list[LabelRecord], path: str, sort_by: str | None = None,
                         opts: dict | None = None, context: ReportContext | None = None) -> None:
    """One-page-per-however-many-fit table: person / lot count / total pieces,
    for handing someone a printable list instead of a spreadsheet."""
    o = _section("lots", opts)
    sort_by = sort_by or o["sort"]
    styles, cell, bold = _styles()
    everyone = _lot_totals(records, sort_by, context or _NO_CONTEXT)
    people = [t for t in everyone if t["lots"] >= o["min_lots"]]

    cols = [("person", "Person", 100, True)]
    for key, header, w in (("lots", "Lots", 30), ("pieces", "Total pieces", 40),
                           ("total_weight", "Total weight", 35)):
        if o[key]:
            cols.append((key, header, w, False))
    size = page_size(o)
    widths = _fit_columns([c[2] * mm for c in cols], [c[3] for c in cols], size[0] - 30 * mm)
    width_of = {c[0]: w for c, w in zip(cols, widths)}

    def cells(label: str, t: dict, style, is_bold: bool) -> list:
        # A Paragraph when needed, so a long name wraps within its column.
        row = [Paragraph(_xml_escape(label), style)]
        for key, *_ in cols[1:]:
            text = (str(t["lots"]) if key == "lots" else f"{t['pieces']:g}" if key == "pieces"
                    else _total_mass_text(t))
            row.append(_txt(text, width_of[key], style, is_bold))
        return row

    total_lots = sum(t["lots"] for t in people)
    stats = f"{len(people)} people, {total_lots} lots total &mdash; sorted by {sort_by} name"
    if o["min_lots"] > 1:
        stats += (f" ({len(everyone) - len(people)} with fewer than {o['min_lots']} "
                  "lots left out)")
    story = [Paragraph(_xml_escape(o["title"] or "Lot counts by person"), styles["Title"])]
    if o["subtitle"]:
        story.append(Paragraph(_xml_escape(o["subtitle"]), styles["Normal"]))
    story += [Paragraph(stats, styles["Normal"]), Spacer(1, 6 * mm)]

    data = [[_txt(c[1], width_of[c[0]], bold, True) for c in cols]]
    data += [cells(t["person"], t, cell, False) for t in people]
    style = list(_TABLE_STYLE.getCommands())
    if o["totals"]:
        total = {"lots": total_lots, "pieces": sum(t["pieces"] for t in people),
                 "grams": sum(t["grams"] for t in people),
                 "estimated": any(t["estimated"] for t in people),
                 "unknown": any(t["unknown"] for t in people)}
        data.append(cells(f"Total ({len(people)} people)", total, bold, True))
        style += [("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                  ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black)]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle(style))
    story.append(table)
    _build_doc(path, story, size, title=o["title"])


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _csv_safe(value) -> str:
    """Neutralize spreadsheet formula injection (CWE-1236): names and
    descriptions come from a shared sheet anyone with edit access can
    change, and a cell like "=HYPERLINK(...)" would run when the CSV is
    opened in Excel/Sheets."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _build_doc(path: str, story: list, size=None, title: str = "",
               header: tuple[str, str] | None = None) -> None:
    """`header` = (title, subtitle): a line at the top of every page (wrapped
    if long), with the margin made room for."""
    size = size or page_size(DEFAULTS["checklist"])
    margin = 15 * mm
    top = margin
    running = None
    if header:
        heading, sub = header
        parts = []
        if heading:
            parts.append(f'<font name="Helvetica-Bold" size="10">{_xml_escape(heading)}</font>')
        if sub:
            parts.append(_xml_escape(sub))
        running = Paragraph(" ".join(parts), ParagraphStyle("running", fontName="Helvetica",
                                                            fontSize=9, leading=12))
        _, h = running.wrap(size[0] - 2 * margin, 1000)
        top = margin + h + 3 * mm

        def draw(canvas, doc):
            running.drawOn(canvas, margin, size[1] - margin - h)
    doc = SimpleDocTemplate(
        path, pagesize=size,
        leftMargin=margin, rightMargin=margin, topMargin=top, bottomMargin=margin,
        **({"title": title} if title else {}),
    )
    if running:
        doc.build(story, onFirstPage=draw, onLaterPages=draw)
    else:
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
