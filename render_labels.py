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
from dataclasses import dataclass
from functools import partial

from reportlab.graphics import shapes
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import String
from reportlab.lib.colors import Color
from reportlab.pdfbase.pdfmetrics import stringWidth
import labels

import colors
from config import LABEL_SPECS, ACTIVE_LABEL_SPEC, IMAGE_CACHE_DIR
from records import LabelRecord, is_valid_element_id

IMAGE_FETCH_WORKERS = 8
MAX_IMAGE_BYTES = 2 * 1024 * 1024
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
            data = resp.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError("image too large")  # a part photo is ~5 KB
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


_image_choice: dict[tuple[str, bool], str | None] = {}  # (element_id, backdrop) -> image


def _label_image(record: LabelRecord, backdrop: bool = True) -> str | None:
    key = (record.element_id, backdrop)
    if key in _image_choice:
        return _image_choice[key]
    path = _cached_image_path(record.element_id, record.image_url)
    if path and backdrop:
        try:
            path = _backdrop_image(path, colors.is_transparent(record.lego_color, record.bl_color),
                                   colors.is_light(record.lego_color, record.bl_color))
        except Exception:
            pass  # unreadable image: draw_label skips it
    _image_choice[key] = path
    return path


def _prefetch_images(records: list[LabelRecord], opts: "LabelOptions") -> None:
    """Warm the image cache for all unique parts in parallel, so draw_label's
    per-label lookups are just cache hits."""
    if not opts.show("photo"):
        return
    unique = {r.element_id: r for r in records}
    backdrop = opts.show("backdrop")
    with ThreadPoolExecutor(max_workers=IMAGE_FETCH_WORKERS) as pool:
        list(pool.map(lambda r: _label_image(r, backdrop), unique.values()))


# Helvetica's cap height and descender, as fractions of the font size, and
# the baseline-to-baseline distance of wrapped lines.
CAP_HEIGHT = 0.72
DESCENDER = 0.22
LEADING = 1.1


def _wrap_lines(text: str, max_width: float, width) -> list[str]:
    """Break text into lines no wider than max_width as width(line) measures
    them, at spaces; a word wider than a whole line is split between
    characters as a last resort. Nothing is dropped but the spaces lines
    break at. Always at least one line. As lugbulk-labels-web's
    pdf_text::wrap_lines."""
    lines: list[str] = []
    line = ""
    for word in text.split(" "):
        candidate = f"{line} {word}" if line else word
        if width(candidate) <= max_width:
            line = candidate
            continue
        if line:
            lines.append(line)
            line = ""
            if width(word) <= max_width:
                line = word
                continue
        while word:  # split by characters, at least one a line
            n = 1
            while n < len(word) and width(word[:n + 1]) <= max_width:
                n += 1
            if n == len(word):
                break
            lines.append(word[:n])
            word = word[n:]
        line = word
    if line or not lines:
        lines.append(line)
    return lines


def _fit_text(text: str, font: str, max_size: float, min_size: float, max_width: float,
              max_height: float) -> tuple[list[str], float, float]:
    """Fit text into a field max_width wide: one line, shrunk from max_size
    down to min_size in half-point steps, when that fits (drawn exactly as
    before). Otherwise it wraps onto more lines and shrinks further until
    the lines fit max_height (cap height of the first line to the
    descenders of the last). Nothing is ever cut off. Returns the lines,
    the font size and the distance between baselines. As
    lugbulk-labels-web's labels_pdf::fit_text."""
    size = max_size
    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 0.5
    if stringWidth(text, font, size) <= max_width:
        return [text], size, size * LEADING

    size = min_size
    while True:
        lines = _wrap_lines(text, max_width, lambda t: stringWidth(t, font, size))
        height = size * (CAP_HEIGHT + DESCENDER) + (len(lines) - 1) * size * LEADING
        if height <= max_height or size <= 0.1:
            return lines, size, size * LEADING
        size = max(0.1, size - 0.25 if size > 2 else size * 0.9)


# Parts of a label that can be switched on and off (--hide / the web
# preview's switches). All on by default except the QR code.
LABEL_PARTS = ("photo", "element_id", "qty", "lego_color", "bl_color", "description",
               "name", "count", "backdrop", "swatch", "qr")
DEFAULT_HIDDEN = frozenset({"qr"})


@dataclass(frozen=True)
class LabelOptions:
    hidden: frozenset = DEFAULT_HIDDEN

    def show(self, part: str) -> bool:
        return part not in self.hidden

    @classmethod
    def parse(cls, hide: str | None, show: str | None = None) -> "LabelOptions":
        """From comma lists of parts to hide / show (on top of the defaults).
        Raises ValueError naming an unknown part."""
        hidden = set(DEFAULT_HIDDEN)
        for items, add in ((hide, True), (show, False)):
            for part in filter(None, (p.strip() for p in (items or "").split(","))):
                if part not in LABEL_PARTS:
                    raise ValueError(f"unknown label part '{part}' (choose from "
                                     f"{', '.join(LABEL_PARTS)})")
                (hidden.add if add else hidden.discard)(part)
        return cls(frozenset(hidden))


def bricklink_url(element_id: str) -> str:
    """Where a label's QR code points: BrickLink's search, which resolves
    LEGO element IDs to the right part and color."""
    return f"https://www.bricklink.com/v2/search.page?q={element_id}"


def _layout(width: float, height: float, opts: LabelOptions, n_lines: int) -> dict:
    """Positions and font sizes (points) scaled to the label's height, so
    every label size gets the same proportions. Parts that are switched off
    free their space: lines stack up, and without a photo the text uses the
    full width. Mirrored in lugbulk-labels-web's labels_pdf.cpp."""
    pad = min(height * 0.07, 9)
    inner = height - 2 * pad
    id_size = min(inner * 0.20, 26)
    small = min(inner * 0.12, 15)
    name_size = min(inner * 0.22, 30)
    top_row = opts.show("element_id") or opts.show("qty")
    name_row = opts.show("name") or opts.show("count")

    y_id = height - pad - id_size * 0.8
    first = (y_id - id_size * 0.2 - small * 1.25) if top_row else (height - pad - small * 0.85)
    lines = [first - i * small * 1.2 for i in range(n_lines)]
    last_text = lines[-1] if lines else (y_id if top_row else height - pad)

    # On taller labels, lift the name toward the text block rather than
    # leaving it stranded at the bottom edge.
    y_name = pad + name_size * 0.22
    lift = 0.0
    if name_row:
        slack = (last_text - small * 0.3) - (y_name + name_size * 0.75)
        lift = max(0.0, slack) * 0.45
        y_name += lift
    art_height = inner - (name_size * 1.3 + lift if name_row else 0)
    img = min(art_height, width * 0.32) if opts.show("photo") else 0.0
    qr = min(art_height * 0.85, width * 0.17) if opts.show("qr") else 0.0
    return dict(
        pad=pad, img=img, qr=qr, text_x=pad + img + pad * 0.8 if img else pad,
        text_right=width - pad - (qr + pad * 0.8 if qr else 0),
        id_size=id_size, small=small, name_size=name_size,
        y_id=y_id, lines=lines, y_name=y_name,
    )


def _qr(label, x: float, y: float, size: float, data: str) -> None:
    widget = QrCodeWidget(data, barLevel="M", barBorder=0)
    x0, y0, x1, y1 = widget.getBounds()
    sx, sy = size / (x1 - x0), size / (y1 - y0)
    group = widget.draw()
    group.transform = (sx, 0, 0, sy, x - x0 * sx, y - y0 * sy)
    label.add(group)


def draw_label(label, width, height, record: LabelRecord, opts: LabelOptions = LabelOptions()):
    # NOTE: width/height (from pylabels) are in points, like every
    # coordinate here — never mix in raw mm values.
    color_lines = []
    if opts.show("lego_color") and record.lego_color:
        color_lines.append(f"LEGO: {record.lego_color}")
    if opts.show("bl_color") and record.bl_color:
        color_lines.append(f"BL: {record.bl_color}")
    texts = color_lines + ([record.description]
                           if opts.show("description") and record.description else [])
    L = _layout(width, height, opts, len(texts))
    pad, small = L["pad"], L["small"]

    img_path = _label_image(record, opts.show("backdrop")) if L["img"] else None
    if img_path:
        try:
            with Image.open(img_path) as im:
                im.verify()  # skip a corrupt image rather than fail the whole PDF
            label.add(shapes.Image(pad, height - pad - L["img"], L["img"], L["img"], img_path))
        except Exception:
            pass
    if L["qr"]:
        _qr(label, width - pad - L["qr"], height - pad - L["qr"], L["qr"],
            bricklink_url(record.element_id))

    text_x, right = L["text_x"], L["text_right"]
    text_max = right - text_x

    # Element ID and qty share the top row. Shrink both together until they
    # fit — the ID must never be cut short.
    id_text = record.element_id if opts.show("element_id") else ""
    qty_text = f"Qty: {record.qty}" if opts.show("qty") else ""
    scale = 1.0

    def row_width(k: float) -> float:
        return (stringWidth(id_text, "Helvetica-Bold", L["id_size"] * k)
                + stringWidth(qty_text, "Helvetica-Bold", L["id_size"] * 0.85 * k)
                + (pad if id_text and qty_text else 0))

    while scale > 0.4 and row_width(scale) > text_max:
        scale -= 0.05
    while scale > 0.01 and row_width(scale) > text_max:  # past that, shrink rather than overlap
        scale *= 0.9
    if qty_text:
        qty_size = L["id_size"] * 0.85 * scale
        label.add(String(right - stringWidth(qty_text, "Helvetica-Bold", qty_size), L["y_id"],
                          qty_text, fontName="Helvetica-Bold", fontSize=qty_size))
    if id_text:
        label.add(String(text_x, L["y_id"], id_text, fontName="Helvetica-Bold",
                          fontSize=L["id_size"] * scale))

    # Swatch: a square of the part's color beside the color name lines.
    swatch_w = 0.0
    rgb = colors.swatch_rgb(record.lego_color, record.bl_color) if opts.show("swatch") else None
    if rgb and color_lines:
        lines_span = small * 1.2 * (len(color_lines) - 1)
        side = lines_span + small * 0.95
        bottom = L["lines"][len(color_lines) - 1] - small * 0.22
        label.add(shapes.Rect(text_x, bottom, side, side, strokeColor=Color(0.35, 0.35, 0.35),
                              strokeWidth=0.5, fillColor=Color(*rgb)))
        if colors.is_transparent(record.lego_color, record.bl_color):
            # Mark see-through colors with a diagonal, like a pane of glass.
            label.add(shapes.Line(text_x, bottom, text_x + side, bottom + side,
                                  strokeColor=Color(0.35, 0.35, 0.35), strokeWidth=0.5))
        swatch_w = side + pad * 0.5

    name_row = opts.show("name") or opts.show("count")
    for i, (y, text) in enumerate(zip(L["lines"], texts)):
        x = text_x + (swatch_w if i < len(color_lines) else 0)
        # The field's space: its own line, from cap height down to where the
        # next line's capitals start; the last line gets everything down to
        # the name row (or the bottom padding).
        top = y + small * CAP_HEIGHT
        bottom = y - small * (1.2 - CAP_HEIGHT)
        if i == len(texts) - 1:
            bottom = min(bottom, L["y_name"] + L["name_size"] * 0.75 + small * 0.15
                         if name_row else pad)
        lines, size, leading = _fit_text(text, "Helvetica", small, small * 0.7, right - x,
                                         top - bottom)
        base = y if len(lines) == 1 else top - size * CAP_HEIGHT
        for line in lines:
            label.add(String(x, base, line, fontName="Helvetica", fontSize=size))
            base -= leading

    counter_w = 0.0
    if opts.show("count") and record.part_total:
        counter = f"{record.part_seq} of {record.part_total}"
        counter_w = stringWidth(counter, "Helvetica-Bold", small)
        label.add(String(width - pad - counter_w, L["y_name"], counter,
                          fontName="Helvetica-Bold", fontSize=small))

    if opts.show("name"):
        # Centered on the label; kept clear of the counter on both sides so
        # it stays visually centered.
        name_max = width - 2 * pad - 2 * (counter_w + pad)
        # Too long for one line: wraps within the name row, from its usual cap
        # height down to half the bottom padding.
        top = L["y_name"] + L["name_size"] * CAP_HEIGHT
        lines, size, leading = _fit_text(record.person, "Helvetica-Bold", L["name_size"],
                                         L["name_size"] * 0.55, name_max, top - pad * 0.5)
        base = L["y_name"] if len(lines) == 1 else top - size * CAP_HEIGHT
        for line in lines:
            name_x = (width - stringWidth(line, "Helvetica-Bold", size)) / 2
            label.add(String(name_x, base, line, fontName="Helvetica-Bold", fontSize=size))
            base -= leading


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


def _save_sheet(records: list[LabelRecord], output_path: str, spec_name: str,
                opts: LabelOptions) -> int:
    sheet = labels.Sheet(_specification(spec_name), partial(draw_label, opts=opts), border=False)
    for record in records:
        sheet.add_label(record)
    sheet.save(output_path)
    return sheet.label_count


def build_pdf(records: list[LabelRecord], output_path: str, spec_name: str = ACTIVE_LABEL_SPEC,
              opts: LabelOptions = LabelOptions()):
    _prefetch_images(records, opts)
    return _save_sheet(records, output_path, spec_name, opts)


_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w\-. ]+")


def build_per_person_pdfs(
    records: list[LabelRecord], output_dir: str, spec_name: str = ACTIVE_LABEL_SPEC,
    opts: LabelOptions = LabelOptions(),
) -> dict[str, int]:
    """Split records by person and write one label PDF per person into
    output_dir. Returns {person: label_count}."""
    by_person: dict[str, list[LabelRecord]] = defaultdict(list)
    for r in records:
        by_person[r.person].append(r)

    _prefetch_images(records, opts)

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
                                     spec_name, opts)

    return counts


def build_test_page(output_path: str, spec_name: str) -> None:
    """One page with every label position outlined and labelled with its
    size, to print on plain paper and hold up against the label stock
    before printing the real thing."""
    spec = LABEL_SPECS[spec_name]

    def draw(label, width, height, index):
        label.add(shapes.Rect(0.5, 0.5, width - 1, height - 1, rx=4, ry=4, fillColor=None,
                              strokeColor=Color(0, 0, 0), strokeWidth=0.75))
        mid_x, mid_y = width / 2, height / 2
        for x1, y1, x2, y2 in ((mid_x - 6, mid_y, mid_x + 6, mid_y),
                               (mid_x, mid_y - 6, mid_x, mid_y + 6)):
            label.add(shapes.Line(x1, y1, x2, y2, strokeColor=Color(0, 0, 0), strokeWidth=0.5))
        size = min(height * 0.12, 10)
        text = (f"{spec['brand']} {spec['part']} #{index}  "
                f"{spec['label_height_mm'] / 25.4:.2f}\" x {spec['label_width_mm'] / 25.4:.2f}\"")
        label.add(String(width / 2, mid_y - size * 2.2, text, fontName="Helvetica",
                          fontSize=size, textAnchor="middle"))

    sheet = labels.Sheet(_specification(spec_name), draw, border=False)
    for i in range(spec["columns"] * spec["rows"]):
        sheet.add_label(i + 1)
    sheet.save(output_path)
