"""Helpers for reading back the PDFs the reports write. Every name and
number in the test data is invented."""

import base64
import re
import zlib

from records import LabelRecord

LONG_DESC = ("BRICK 1X2 W/ BOW 1/2 AND CROSS AXLE HOLE, TRANSPARENT FLUORESCENT REDDISH ORANGE, "
             "WITH PRINTED STRIPES ON BOTH SIDES 012")


def sample_labels() -> list[LabelRecord]:
    """Invented orders in label order (heaviest part first)."""
    rows = [
        # person, element, description, LEGO color, BL color, qty, sheet weight (g/pc)
        ("Ann Example", "6097276", "BASE PLATE 32X32", "Bright Green", "Green", "4", None),
        ("Bob Sample", "6097276", "BASE PLATE 32X32", "Bright Green", "Green", "10", None),
        ("Ann Example", "4211388", "BRICK 1X2", "Medium Stone Grey", "Light Bluish Gray", "25", None),
        ("Cy Tester", "4211388", "BRICK 1X2", "Medium Stone Grey", "Light Bluish Gray", "50", None),
        ("Bob Sample", "6514224", "FLAT TILE 1X2", "Transparent Light Blue", "Trans-Light Blue", "75", None),
        ("Cy Tester", "6584302", "FROG", "Black", "Black", "5", 2.5),
        ("Ann Example", "6999001", "ROUND 1X1", "Bright Green", "Green", "200", None),
    ]
    out = []
    for person, eid, desc, lego, bl, qty, weight in rows:
        out.append(LabelRecord(person, eid, desc, lego, bl, qty, "http://invalid.example/" + eid,
                               weight))
    seen: dict[str, list] = {}
    for r in out:
        seen.setdefault(r.element_id, []).append(r)
    for group in seen.values():
        for i, r in enumerate(group, start=1):
            r.part_seq, r.part_total = i, len(group)
    return out


def streams(path) -> list[bytes]:
    """The decompressed streams of a reportlab PDF."""
    data = open(path, "rb").read()
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        raw = m.group(1).strip()
        if raw.endswith(b"~>"):  # reportlab's default: ASCII85, then Flate
            raw = base64.a85decode(raw[:-2])
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        out.append(raw)
    return out


def pdf_text(path) -> str:
    """Everything the PDF draws with Tj, in order."""
    out = []
    for raw in streams(path):
        for s in re.findall(rb"\(((?:[^()\\]|\\.)*)\)\s*Tj", raw):
            out.append(re.sub(rb"\\(.)", rb"\1", s).decode("latin-1"))
    return "".join(out)


def pdf_layout(path) -> list[str]:
    """The lines that place text and draw boxes, for comparing layouts."""
    lines = []
    for raw in streams(path):
        lines += [ln for ln in raw.decode("latin-1").splitlines()
                  if ln.endswith("Tj T* ET") or ln.endswith(" re S") or ln.endswith(" cm")
                  or ln.endswith(" re f*")]
    return lines


def pages(path) -> list[tuple[float, float]]:
    """Each page's (width, height) in points."""
    data = open(path, "rb").read().decode("latin-1")
    return [(float(a), float(b)) for a, b in
            re.findall(r"/MediaBox \[ 0 0 ([\d.]+) ([\d.]+) \]", data)]


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s)
