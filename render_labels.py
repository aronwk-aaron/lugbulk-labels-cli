"""Render LabelRecords onto label-sheet (or label-roll) PDFs.

Layout, scaled to whatever label size is in use:

    +-------------------------------------------+
    | [thumb]  6225242 (bold)         Qty: 150  |
    |          LEGO: Medium Stone Grey          |
    |          BL: Light Bluish Gray            |
    |          BRICK 1X1X1 2/3 W/2 KNOBS        |
    |        Person Name (bold, centered)  3 of 10
    +-------------------------------------------+
"""

import io
import os
import re
import time
import urllib.request
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageChops, ImageDraw, ImageFilter
from reportlab.graphics import shapes
from reportlab.graphics.shapes import String
from reportlab.pdfbase.pdfmetrics import stringWidth
import labels

import colors
from config import LABEL_SPECS, ACTIVE_LABEL_SPEC, IMAGE_CACHE_DIR
from records import LabelRecord, is_valid_element_id

IMAGE_FETCH_WORKERS = 8
# A cached miss (404, timeout, etc.) is retried after this long, so a transient
# CDN outage doesn't permanently blank out a thumbnail.
MISS_RETRY_SECONDS = 24 * 60 * 60

# Light parts (trans, white) nearly vanish on LEGO's white product shots,
# so they're cut out and set on a light gray tile — see _backdrop_image.
BACKDROP_TILE = (218, 220, 224)
BACKDROP_BG_TOLERANCE = 4  # a pixel within this of pure white (every channel) is background
BACKDROP_SCALE = 2  # render the cut-out at 2x for smooth edges at print size
BACKDROP_HOLE_MIN = 0.02  # enclosed white area (fraction of image) treated as background
TRANS_GAIN = 1.6  # max contrast boost for trans parts
FAINT_PART_MIN = 150  # a part whose darkest 5% is at least this light counts as faint
BACKDROP_VERSION = 1  # bump to regenerate cached backdrop images


def _cached_image_path(element_id: str, url: str) -> str | None:
    """Download and cache a part thumbnail by element ID. Returns None on failure
    (missing product photo, network issue, etc.) so rendering can skip gracefully."""
    if not is_valid_element_id(element_id):
        return None  # never let sheet text pick a path outside the cache
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
        Image.open(io.BytesIO(data)).verify()  # don't cache an error page
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)  # atomic: a crash never leaves a half-written image
        return path
    except Exception:
        # Cache the miss as an empty file so we don't re-fetch every run.
        open(path, "wb").close()
        return None


def _background_mask(img: Image.Image) -> Image.Image:
    """255 = background: near-white regions touching the border, plus large
    enclosed near-white regions (the opening of a window frame, say) —
    real part faces are shaded, not pure white."""
    w, h = img.size
    px = img.load()
    bg = Image.new("L", (w, h), 0)
    bg_px = bg.load()
    seen: set[tuple[int, int]] = set()

    def is_white(x: int, y: int) -> bool:
        return 255 - min(px[x, y]) <= BACKDROP_BG_TOLERANCE

    def region(start: tuple[int, int]) -> tuple[list, bool]:
        pixels, touches_border, queue = [], False, deque([start])
        seen.add(start)
        while queue:
            x, y = queue.popleft()
            pixels.append((x, y))
            touches_border |= x in (0, w - 1) or y in (0, h - 1)
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen and is_white(nx, ny):
                    seen.add((nx, ny))
                    queue.append((nx, ny))
        return pixels, touches_border

    for y in range(h):
        for x in range(w):
            if (x, y) in seen or not is_white(x, y):
                continue
            pixels, touches_border = region((x, y))
            if touches_border or len(pixels) >= w * h * BACKDROP_HOLE_MIN:
                for p in pixels:
                    bg_px[p] = 255
    return bg


def _drop_small_components(mask: Image.Image, min_fraction: float = 0.15) -> Image.Image:
    """Clear connected blobs smaller than min_fraction of the largest one —
    JPEG-noise specks, and slivers of a pure-white face the background
    fill cut off from the rest of the part."""
    w, h = mask.size
    px = mask.load()
    seen = set()
    components = []
    for y in range(h):
        for x in range(w):
            if not px[x, y] or (x, y) in seen:
                continue
            blob, queue = [], deque([(x, y)])
            seen.add((x, y))
            while queue:
                cx, cy = queue.popleft()
                blob.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < w and 0 <= ny < h and px[nx, ny] and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        queue.append((nx, ny))
            components.append(blob)
    largest = max((len(c) for c in components), default=0)
    out = mask.copy()
    out_px = out.load()
    for blob in components:
        if len(blob) < largest * min_fraction:
            for bx, by in blob:
                out_px[bx, by] = 0
    return out


def _is_faint(img: Image.Image, part: Image.Image) -> bool:
    """True if even the darkest 5% of the part's pixels are light."""
    hist = img.convert("L").histogram(mask=part)
    target, seen = sum(hist) * 0.05, 0
    for level, count in enumerate(hist):
        seen += count
        if seen >= target:
            return level >= FAINT_PART_MIN
    return False


def _backdrop_image(src_path: str, trans: bool, light_color: bool) -> str:
    """Return the image to print for a part: the product photo as-is, or —
    for trans, white, and otherwise faint parts, which nearly vanish on
    LEGO's white-background shots — the part set on a light gray rounded
    tile. Cached next to the source image.

    The tile is the photo *multiplied* onto gray: white background becomes
    tile gray while the part's shading and edges carry through. That alone
    is how a trans part is shown (it reads like glass in front of the tile,
    with no cut-out edge to halo). A white part is then cut out and put
    back on top at full brightness, so it still looks white."""
    out_path = src_path.removesuffix(".jpg") + f".backdrop{BACKDROP_VERSION}.png"
    plain_marker = src_path.removesuffix(".jpg") + f".plain{BACKDROP_VERSION}"
    for cached in (out_path, plain_marker):
        if os.path.exists(cached) and os.path.getmtime(cached) >= os.path.getmtime(src_path):
            return out_path if cached == out_path else src_path

    img = Image.open(src_path).convert("RGB")
    part = None
    if not trans:
        part = ImageChops.invert(_background_mask(img))
        part = part.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))  # specks
        part = _drop_small_components(part)
        # Close: bridge small gaps where a white edge touches the background.
        for size_filter in [ImageFilter.MaxFilter] * 3 + [ImageFilter.MinFilter] * 3:
            part = part.filter(size_filter(3))
        if not (light_color or _is_faint(img, part)):
            open(plain_marker, "w").close()  # photo is fine as-is; remember that
            return src_path

    size = (img.width * BACKDROP_SCALE, img.height * BACKDROP_SCALE)
    photo = img.resize(size, Image.LANCZOS)
    if trans:
        # Deepen the faint edge lines a little.
        darkest = img.convert("L").getextrema()[0]  # the background is white
        gain = min(TRANS_GAIN, 150 / max(1, 255 - darkest))
        photo = photo.point(lambda c: max(0, int(255 - (255 - c) * gain)))

    tile_mask = Image.new("L", size, 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle(
        [0, 0, size[0] - 1, size[1] - 1], radius=size[0] // 10, fill=255)
    out = Image.new("RGB", size, (255, 255, 255))
    out.paste(ImageChops.multiply(Image.new("RGB", size, BACKDROP_TILE), photo), mask=tile_mask)

    if part is not None:
        # Smooth, anti-aliased silhouette at the output size, pulled in a
        # pixel so the JPEG's off-white fringe stays in the multiplied band.
        mask = part.resize(size, Image.BILINEAR).filter(
            ImageFilter.GaussianBlur(BACKDROP_SCALE * 0.8))
        mask = mask.point(lambda v: 255 if v >= 128 else 0).filter(ImageFilter.MinFilter(5))
        mask = mask.filter(ImageFilter.GaussianBlur(BACKDROP_SCALE * 0.5))
        out.paste(photo, mask=ImageChops.multiply(mask, tile_mask))

    tmp = f"{out_path}.{os.getpid()}.tmp.png"
    out.save(tmp)
    os.replace(tmp, out_path)
    return out_path


_image_choice: dict[str, str | None] = {}  # element_id -> image to draw


def _label_image(record: LabelRecord) -> str | None:
    if record.element_id in _image_choice:
        return _image_choice[record.element_id]
    path = _cached_image_path(record.element_id, record.image_url)
    if path:
        try:
            path = _backdrop_image(path, colors.is_transparent(record.lego_color, record.bl_color),
                                   colors.is_light(record.lego_color, record.bl_color))
        except Exception:
            pass  # unreadable image: draw_label skips it
    _image_choice[record.element_id] = path
    return path


def _prefetch_images(records: list[LabelRecord]) -> None:
    """Warm the image cache for all unique parts in parallel, so draw_label's
    per-label lookups are just cache hits."""
    unique = {r.element_id: r for r in records}
    with ThreadPoolExecutor(max_workers=IMAGE_FETCH_WORKERS) as pool:
        list(pool.map(_label_image, unique.values()))


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


def _layout(width: float, height: float) -> dict:
    """Positions and font sizes (points) scaled to the label's height, so
    every label size gets the same proportions."""
    pad = min(height * 0.07, 9)
    inner = height - 2 * pad
    id_size = min(inner * 0.20, 26)
    small = min(inner * 0.12, 15)
    name_size = min(inner * 0.22, 30)

    y_id = height - pad - id_size * 0.8
    y_lego = y_id - id_size * 0.2 - small * 1.25
    y_bl = y_lego - small * 1.2
    y_desc = y_bl - small * 1.2
    # On taller labels, lift the name toward the text block rather than
    # leaving it stranded at the bottom edge.
    y_name = pad + name_size * 0.22
    slack = (y_desc - small * 0.3) - (y_name + name_size * 0.75)
    lift = max(0.0, slack) * 0.45
    y_name += lift
    img = min(inner - name_size * 1.3 - lift, width * 0.32)
    return dict(
        pad=pad, img=img, text_x=pad + img + pad * 0.8,
        id_size=id_size, small=small, name_size=name_size,
        y_id=y_id, y_lego=y_lego, y_bl=y_bl, y_desc=y_desc, y_name=y_name,
    )


def draw_label(label, width, height, record: LabelRecord):
    # NOTE: width/height (from pylabels) are in points, like every
    # coordinate here — never mix in raw mm values.
    L = _layout(width, height)
    pad, small = L["pad"], L["small"]

    img_path = _label_image(record)
    if img_path:
        try:
            with Image.open(img_path) as im:
                im.verify()  # skip a corrupt image rather than fail the whole PDF
            label.add(shapes.Image(pad, height - pad - L["img"], L["img"], L["img"], img_path))
        except Exception:
            pass

    text_x = L["text_x"]
    text_max = width - pad - text_x

    qty_text = f"Qty: {record.qty}"
    qty_size = L["id_size"] * 0.85
    qty_w = stringWidth(qty_text, "Helvetica-Bold", qty_size)
    label.add(String(width - pad - qty_w, L["y_id"], qty_text,
                      fontName="Helvetica-Bold", fontSize=qty_size))

    id_text, id_size = _fit_string(record.element_id, "Helvetica-Bold", L["id_size"],
                                    L["id_size"] * 0.6, text_max - qty_w - pad)
    label.add(String(text_x, L["y_id"], id_text, fontName="Helvetica-Bold", fontSize=id_size))

    for y, text in ((L["y_lego"], f"LEGO: {record.lego_color}" if record.lego_color else ""),
                    (L["y_bl"], f"BL: {record.bl_color}" if record.bl_color else ""),
                    (L["y_desc"], record.description)):
        if text:
            fitted, size = _fit_string(text, "Helvetica", small, small * 0.7, text_max)
            label.add(String(text_x, y, fitted, fontName="Helvetica", fontSize=size))

    counter_w = 0.0
    if record.part_total:
        counter = f"{record.part_seq} of {record.part_total}"
        counter_w = stringWidth(counter, "Helvetica-Bold", small)
        label.add(String(width - pad - counter_w, L["y_name"], counter,
                          fontName="Helvetica-Bold", fontSize=small))

    # Centered on the label; kept clear of the counter on both sides so it
    # stays visually centered.
    name_max = width - 2 * pad - 2 * (counter_w + pad)
    name_text, name_size = _fit_string(record.person, "Helvetica-Bold", L["name_size"],
                                        L["name_size"] * 0.55, name_max)
    name_x = (width - stringWidth(name_text, "Helvetica-Bold", name_size)) / 2
    label.add(String(name_x, L["y_name"], name_text, fontName="Helvetica-Bold",
                      fontSize=name_size))


def _specification(spec_name: str) -> "labels.Specification":
    spec = LABEL_SPECS[spec_name]
    # A hair under true size: pylabels' float checks reject labels that
    # exactly fill the page (rolls, and edge-to-edge sheets like 5126/5663).
    width, height = spec["label_width_mm"] - 0.01, spec["label_height_mm"] - 0.01
    return labels.Specification(
        spec["sheet_width_mm"], spec["sheet_height_mm"],
        spec["columns"], spec["rows"], width, height,
        corner_radius=2,
        left_margin=spec["left_margin_mm"], top_margin=spec["top_margin_mm"],
        column_gap=spec["column_gap_mm"] if spec["columns"] > 1 else None,
        row_gap=spec["row_gap_mm"] if spec["rows"] > 1 else None,
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
    used_names: set[str] = set()
    for person, person_records in by_person.items():
        safe_name = _UNSAFE_FILENAME_CHARS.sub("_", person).strip(" ._") or "unknown"
        # Two people whose names sanitize alike must not overwrite each other.
        candidate, n = safe_name, 2
        while candidate.lower() in used_names:
            candidate, n = f"{safe_name}_{n}", n + 1
        used_names.add(candidate.lower())
        counts[person] = _save_sheet(person_records, os.path.join(output_dir, f"{candidate}.pdf"),
                                     spec_name)

    return counts
