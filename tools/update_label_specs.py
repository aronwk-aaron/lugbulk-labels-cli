"""Regenerate label_specs.json: the Avery and Dymo label stock the CLI and
lugbulk-labels-web can print on.

Source: the gLabels template database (MIT-licensed — notice reproduced
in the output), which has sheet geometry for Avery US-Letter and A4
(Zweckform) stock and Dymo LabelWriter rolls, plus a few Dymo rolls it
lacks (SUPPLEMENT below). Only adhesive labels (gLabels category
"label") that are rectangular and big enough for the label design are kept (see MIN_*), and portrait sheet labels are skipped
since the design is landscape. Roll labels are stored landscape — print
them with the Dymo driver's matching paper size and it rotates as needed.

    python tools/update_label_specs.py            # writes label_specs.json
    cp label_specs.json ../lugbulk-labels-web/data/
"""

import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://raw.githubusercontent.com/jimevins/glabels-qt/master/templates/"
FILES = ["avery-us-templates.xml", "avery-iso-templates.xml", "dymo-other-templates.xml"]
PAGES = {"US-Letter": (215.9, 279.4), "A4": (210.0, 297.0)}

# Smallest label the design is still legible on (landscape, mm). Avery
# 5160 (66.7 x 25.4) is the smallest in practical use.
MIN_WIDTH, MIN_HEIGHT = 44.0, 22.0

# Dymo LabelWriter rolls missing from gLabels: (part, description,
# width, height mm as fed, equivalent parts).
SUPPLEMENT = [
    ("30857", "Name badge labels", 57, 102, []),
    ("30321", "Large address labels", 36, 89, []),
    ("30320", "Address labels", 28, 89, []),
    ("30323", "Shipping labels", 54, 101, []),
    ("30336", "Multipurpose labels", 25, 54, []),
    ("1744907", "4XL shipping labels", 102, 159, []),
]

LICENSE_NOTICE = (
    "Label geometry derived from the gLabels template database, "
    "Copyright (C) 2001-2026 Jaye Evins, used under the MIT license: "
    "https://github.com/jimevins/glabels-qt/blob/master/templates/LICENSE"
)


def mm(value: str) -> float:
    m = re.fullmatch(r"\s*([-\d.]+)\s*(in|mm|cm|pt)?\s*", value or "0")
    number, unit = float(m.group(1)), m.group(2) or "pt"
    return number * {"in": 25.4, "mm": 1.0, "cm": 10.0, "pt": 25.4 / 72}[unit]


def spec_id(brand: str, part: str) -> str:
    return re.sub(r"[^a-z0-9]", "", f"{brand}{part}".lower())


def parse(xml_text: str) -> tuple[list[dict], dict[str, list[str]]]:
    root = ET.fromstring(xml_text)
    specs, equivs = [], {}
    for t in root.findall("Template"):
        brand, part = t.get("brand"), t.get("part")
        if t.get("equiv"):
            equivs.setdefault(spec_id(brand, t.get("equiv")), []).append(part)
            continue
        if "label" not in {m.get("category") for m in t.findall("Meta")}:
            continue  # business/index/post cards, tent cards, CD inserts...
        labels = [c for c in t if c.tag.startswith("Label-")]
        if len(labels) != 1 or labels[0].tag != "Label-rectangle":
            continue
        label = labels[0]
        layouts = label.findall("Layout")
        if len(layouts) != 1:
            continue
        lay = layouts[0]
        w, h = mm(label.get("width")), mm(label.get("height"))
        size = t.get("size")
        spec = dict(id=spec_id(brand, part), brand=brand, part=part,
                    description=t.get("_description", ""), equivalents=[])
        if size in PAGES:
            if h > w:
                continue  # portrait sheet label: the design is landscape
            page_w, page_h = PAGES[size]
            spec.update(
                page=size, sheet_width_mm=page_w, sheet_height_mm=page_h,
                columns=int(lay.get("nx")), rows=int(lay.get("ny")),
                label_width_mm=w, label_height_mm=h,
                left_margin_mm=mm(lay.get("x0")), top_margin_mm=mm(lay.get("y0")),
                column_gap_mm=max(0.0, mm(lay.get("dx")) - w) if int(lay.get("nx")) > 1 else 0.0,
                row_gap_mm=max(0.0, mm(lay.get("dy")) - h) if int(lay.get("ny")) > 1 else 0.0,
            )
        elif size in ("roll", "other"):
            spec.update(roll_spec(max(w, h), min(w, h)))
        else:
            continue
        specs.append(spec)
    return specs, equivs


def roll_spec(width: float, height: float) -> dict:
    return dict(page="roll", sheet_width_mm=width, sheet_height_mm=height, columns=1, rows=1,
                label_width_mm=width, label_height_mm=height, left_margin_mm=0.0,
                top_margin_mm=0.0, column_gap_mm=0.0, row_gap_mm=0.0)


def main() -> None:
    specs, equivs = [], {}
    for name in FILES:
        with urllib.request.urlopen(BASE + name, timeout=30) as resp:
            s, e = parse(resp.read().decode())
        specs += s
        for k, v in e.items():
            equivs.setdefault(k, []).extend(v)
    known = {s["id"] for s in specs}
    for part, desc, w, h, eq in SUPPLEMENT:
        if spec_id("Dymo", part) not in known:
            specs.append(dict(id=spec_id("Dymo", part), brand="Dymo", part=part, description=desc,
                              equivalents=eq, **roll_spec(max(w, h), min(w, h))))

    for s in specs:
        s["equivalents"] = sorted(set(s["equivalents"] + equivs.get(s["id"], [])),
                                  key=lambda p: (len(p), p))
        for k, v in s.items():
            if isinstance(v, float):
                s[k] = round(v, 3)
    usable = [s for s in specs
              if s["label_width_mm"] >= MIN_WIDTH and s["label_height_mm"] >= MIN_HEIGHT]
    usable.sort(key=lambda s: (s["brand"], s["page"] != "US-Letter", s["page"],
                               int(re.sub(r"\D", "", s["part"]) or 0), s["part"]))
    with open("label_specs.json", "w") as f:
        json.dump({"source": LICENSE_NOTICE, "specs": usable}, f, indent=1)
        f.write("\n")
    print(f"Wrote {len(usable)} label specs "
          f"({sum(len(s['equivalents']) for s in usable)} equivalent part numbers) "
          f"to label_specs.json", file=sys.stderr)


if __name__ == "__main__":
    main()
