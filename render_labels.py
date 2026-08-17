"""Render LabelRecords onto an Avery-style label sheet PDF.

Layout mirrors the reference photo:
    [thumb]  Element ID: 1234567      Qty: 150
             Color
             PART NAME
                Person Name (bold, larger, centered)
"""

import os
import re
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from reportlab.graphics import shapes
from reportlab.graphics.shapes import String
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
import labels

from config import LABEL_SPECS, ACTIVE_LABEL_SPEC, IMAGE_CACHE_DIR
from sheets_source import LabelRecord

# NOTE: draw_label's width/height args (from pylabels) are already in points,
# same unit as every coordinate below — do not mix in raw mm values.
IMG_SIZE = 16 * mm
TEXT_LEFT = IMG_SIZE + 3 * mm  # text starts right of the thumbnail
MARGIN = 2

IMAGE_FETCH_WORKERS = 8
# A cached miss (404, timeout, etc.) is retried after this long, so a transient
# CDN outage doesn't permanently blank out a thumbnail.
MISS_RETRY_SECONDS = 24 * 60 * 60


def _cached_image_path(element_id: str, url: str) -> str | None:
    """Download and cache a part thumbnail by element ID. Returns None on failure
    (missing product photo, network issue, etc.) so rendering can skip gracefully."""
    os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)
    path = os.path.join(IMAGE_CACHE_DIR, f"{element_id}.jpg")
    if os.path.exists(path):
        if os.path.getsize(path) > 0:
            return path
        # Empty file = cached miss. Retry it once it's stale enough.
        if time.time() - os.path.getmtime(path) < MISS_RETRY_SECONDS:
            return None

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        with open(path, "wb") as f:
            f.write(data)
        return path
    except Exception:
        # Cache the miss as an empty file so we don't re-fetch every run.
        open(path, "wb").close()
        return None


def _prefetch_images(records: list[LabelRecord]) -> None:
    """Warm the image cache for all unique element IDs in parallel, so
    draw_label's per-label lookups below are just cache hits."""
    unique = {r.element_id: r.image_url for r in records}
    with ThreadPoolExecutor(max_workers=IMAGE_FETCH_WORKERS) as pool:
        list(pool.map(lambda kv: _cached_image_path(*kv), unique.items()))


def _fit_string(text: str, font: str, max_size: float, min_size: float, max_width: float):
    """Shrink font size to fit text within max_width; truncate with an ellipsis
    as a last resort if even min_size doesn't fit."""
    size = max_size
    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 0.5
    if stringWidth(text, font, size) <= max_width:
        return text, size

    size = min_size
    truncated = text
    while truncated and stringWidth(truncated + "…", font, size) > max_width:
        truncated = truncated[:-1]
    return (truncated + "…" if truncated else text), size


def draw_label(label, width, height, record: LabelRecord):
    img_path = _cached_image_path(record.element_id, record.image_url)
    if img_path:
        try:
            ImageReader(img_path)  # validates it decodes as an image before we place it
            label.add(
                shapes.Image(MARGIN, height - IMG_SIZE - MARGIN, IMG_SIZE, IMG_SIZE, img_path)
            )
        except Exception:
            pass  # corrupt/unreadable image; skip thumbnail, keep text

    text_x = TEXT_LEFT

    id_font, id_size = "Helvetica", 7
    label.add(String(text_x, height - 10, f"Element ID: {record.element_id}",
                      fontName=id_font, fontSize=id_size))

    qty_text = f"Qty: {record.qty}"
    qty_font, qty_size = "Helvetica-Bold", 11
    qty_x = width - MARGIN - stringWidth(qty_text, qty_font, qty_size)
    label.add(String(max(text_x, qty_x), height - 10, qty_text,
                      fontName=qty_font, fontSize=qty_size))

    text_max_width = width - text_x - MARGIN

    color_text, color_size = _fit_string(record.color, "Helvetica", 7, 5, text_max_width)
    label.add(String(text_x, height - 18, color_text,
                      fontName="Helvetica", fontSize=color_size))

    desc_text, desc_size = _fit_string(record.description, "Helvetica", 7, 5, text_max_width)
    label.add(String(text_x, height - 26, desc_text,
                      fontName="Helvetica", fontSize=desc_size))

    name_font = "Helvetica-Bold"
    name_text, name_size = _fit_string(record.person, name_font, 13, 8, width - 2 * MARGIN)
    name_x = (width - stringWidth(name_text, name_font, name_size)) / 2
    label.add(String(name_x, height - 46, name_text, fontName=name_font, fontSize=name_size))


def _specification(spec_name: str) -> "labels.Specification":
    spec = LABEL_SPECS[spec_name]
    return labels.Specification(
        spec["sheet_width"], spec["sheet_height"],
        spec["columns"], spec["rows"],
        spec["label_width"], spec["label_height"],
        corner_radius=spec["corner_radius"],
        left_margin=spec["left_margin"], right_margin=spec["right_margin"],
        top_margin=spec["top_margin"], bottom_margin=spec["bottom_margin"],
        row_gap=spec["row_gap"], column_gap=spec["column_gap"],
    )


def _save_sheet(records: list[LabelRecord], output_path: str, spec_name: str) -> int:
    sheet = labels.Sheet(_specification(spec_name), draw_label, border=False)
    for record in records:
        sheet.add_label(record)
    sheet.save(output_path)
    return sheet.label_count


def build_pdf(records: list[LabelRecord], output_path: str, spec_name: str = ACTIVE_LABEL_SPEC):
    _prefetch_images(records)
    return _save_sheet(records, output_path, spec_name)


_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w\-. ]+")


def build_per_person_pdfs(
    records: list[LabelRecord], output_dir: str, spec_name: str = ACTIVE_LABEL_SPEC
) -> dict[str, int]:
    """Split records by person and write one label PDF per person into
    output_dir. Returns {person: label_count}."""
    by_person: dict[str, list[LabelRecord]] = defaultdict(list)
    for r in records:
        by_person[r.person].append(r)

    _prefetch_images(records)

    os.makedirs(output_dir, exist_ok=True)
    counts: dict[str, int] = {}
    for person, person_records in by_person.items():
        safe_name = _UNSAFE_FILENAME_CHARS.sub("_", person).strip() or "unknown"
        path = os.path.join(output_dir, f"{safe_name}.pdf")
        counts[person] = _save_sheet(person_records, path, spec_name)

    return counts
