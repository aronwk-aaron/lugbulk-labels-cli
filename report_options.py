"""Settings for the packing checklist, parts list and lot counts PDFs (and
which rows the lot-counts/parts CSVs list). A port of the web app's
static/js/report_options.js: same option names, defaults and limits, so a
design saved on the site can be loaded with --report-options FILE.

The options are a dict of sections ("checklist", "parts", "lots", plus a
"zip" section the CLI ignores), each a flat dict of settings.
normalize_options() keeps only known keys, clamps every value to what it
allows and fills in the defaults; the defaults give today's reports.
"""

import copy
import json
import re

from reportlab.lib.pagesizes import A4, landscape, letter

MAX_TITLE = 80
MAX_SUBTITLE = 120
MAX_MIN_LOTS = 9999
MAX_OPTIONS_BYTES = 4096

PAPERS = ("letter", "a4")
ORIENTATIONS = ("portrait", "landscape")
PERSON_SORTS = ("last", "first")
# "labels" = the order of the labels (including --keep-parts optimize).
CHECKLIST_ORDERS = ("labels", "heaviest", "lightest", "sheet")
PARTS_ORDERS = ("labels", "heaviest", "lightest", "sheet", "element")
# The web calls one page per person "page"; the flag calls it "per-person".
CHECKLIST_LAYOUTS = ("page", "continuous")
LAYOUT_FLAG_CHOICES = ("per-person", "continuous")

_PAGE = {"title": "", "subtitle": "", "paper": "letter", "orientation": "portrait"}

DEFAULTS = {
    "checklist": {**_PAGE, "sort": "last", "order": "labels", "layout": "page",
                  "color": True, "weight": False, "photo": False, "checkbox": True,
                  "packed_by": False},
    "parts": {**_PAGE, "order": "labels", "photo": False, "lego_color": True,
              "bl_color": True, "pieces": True, "people": True, "weight": True,
              "total_weight": False, "group_by_color": False},
    "lots": {**_PAGE, "sort": "last", "lots": True, "pieces": True,
             "total_weight": False, "totals": False, "min_lots": 0},
    "zip": {"labels": True, "checklist_pdf": True, "parts_pdf": True, "parts_csv": True,
            "lots_pdf": True, "lots_csv": True, "check_txt": True},
}

REPORTS = ("checklist", "parts", "lots")

_CHOICES = {"paper": PAPERS, "orientation": ORIENTATIONS, "sort": PERSON_SORTS,
            "layout": CHECKLIST_LAYOUTS}

_CONTROL = re.compile("[\u0000-\u001f\u007f-\u009f  ]")


def clean_text(v, max_len: int) -> str:
    """A title or subtitle: control characters turned into spaces, runs of
    spaces collapsed, trimmed and cut to `max_len` characters."""
    if not isinstance(v, str):
        return ""
    s = re.sub(" {2,}", " ", _CONTROL.sub(" ", v)).strip()
    return s[:max_len].strip()


def clamp_int(v, lo: int, hi: int, fallback: int) -> int:
    """A whole number in [lo, hi]; anything else (NaN, text that isn't a
    number, booleans, objects) gives `fallback`."""
    if isinstance(v, bool):
        return fallback
    if isinstance(v, str):
        if not v.strip():
            return fallback
        try:
            v = float(v)
        except ValueError:
            return fallback
    if not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        return fallback
    return min(hi, max(lo, int(v)))


def _normalize_section(name: str, raw) -> dict:
    src = raw if isinstance(raw, dict) else {}
    out = {}
    for key, default in DEFAULTS[name].items():
        v = src.get(key)
        if isinstance(default, bool):
            out[key] = v if isinstance(v, bool) else default
        elif key == "title":
            out[key] = clean_text(v, MAX_TITLE)
        elif key == "subtitle":
            out[key] = clean_text(v, MAX_SUBTITLE)
        elif key == "min_lots":
            out[key] = clamp_int(v, 0, MAX_MIN_LOTS, default)
        elif key == "order":
            allowed = PARTS_ORDERS if name == "parts" else CHECKLIST_ORDERS
            out[key] = v if isinstance(v, str) and v in allowed else default
        else:
            out[key] = v if isinstance(v, str) and v in _CHOICES[key] else default
    return out


def normalize_options(raw) -> dict:
    """A complete, valid options dict from anything (parsed JSON, a partial
    dict, None...). Never raises."""
    src = raw if isinstance(raw, dict) else {}
    return {name: _normalize_section(name, src.get(name)) for name in DEFAULTS}


def default_options() -> dict:
    return copy.deepcopy(normalize_options(None))


def parse_options(text) -> dict:
    """normalize_options() of a JSON string; bad JSON gives the defaults."""
    if not isinstance(text, str) or len(text) > MAX_OPTIONS_BYTES * 4:
        return normalize_options(None)
    try:
        return normalize_options(json.loads(text))
    except ValueError:
        return normalize_options(None)


def page_size(section: dict) -> tuple[float, float]:
    """Page size in points for a section's paper and orientation."""
    size = A4 if section["paper"] == "a4" else letter
    return landscape(size) if section["orientation"] == "landscape" else size


# ---- command-line flags -----------------------------------------------------------

# Toggle names (as written in --checklist-show etc.) -> option key. Hyphens
# and underscores are interchangeable.
TOGGLES = {
    "checklist": ("checkbox", "color", "weight", "photo", "packed_by"),
    "parts": ("photo", "lego_color", "bl_color", "pieces", "people", "weight",
              "total_weight", "group_by_color"),
    "lots": ("lots", "pieces", "total_weight", "totals"),
}


def _flag_names(name: str) -> str:
    return ", ".join(k.replace("_", "-") for k in TOGGLES[name])


def add_arguments(parser) -> None:
    """Add the report flags. Every default is None: a flag the user didn't
    give leaves the value from --report-options (or the built-in default)."""
    g = parser.add_argument_group(
        "report options",
        "Change the packing checklist (--checklist), parts list (--parts) and lot "
        "counts (--lot-counts) PDFs, as the web app's report settings do. Without "
        "these the reports come out as before.")
    g.add_argument("--report-options", metavar="FILE",
                   help="JSON file in the web app's report_options format (a saved design's "
                        "reports); the flags below override it.")
    g.add_argument("--report-title", metavar="TEXT",
                   help=f"Title for every report PDF (up to {MAX_TITLE} characters).")
    g.add_argument("--report-subtitle", metavar="TEXT",
                   help=f"Subtitle for every report PDF (up to {MAX_SUBTITLE} characters).")
    g.add_argument("--paper", choices=PAPERS, help="Paper size of every report PDF "
                   "(default: letter).")
    g.add_argument("--orientation", choices=ORIENTATIONS,
                   help="Page orientation of every report PDF (default: portrait).")
    g.add_argument("--checklist-layout", choices=LAYOUT_FLAG_CHOICES,
                   help="per-person: a new page for each person (default); continuous: "
                        "people run on one after another.")
    g.add_argument("--checklist-order", choices=CHECKLIST_ORDERS,
                   help="Order of parts on the checklist (default: labels = same as the labels).")
    g.add_argument("--checklist-show", metavar="COLUMNS", default="",
                   help=f"Comma-separated checklist columns/items to turn on: "
                        f"{_flag_names('checklist')}. On by default: checkbox, color.")
    g.add_argument("--checklist-hide", metavar="COLUMNS", default="",
                   help="Comma-separated checklist columns/items to turn off.")
    g.add_argument("--parts-order", choices=PARTS_ORDERS,
                   help="Order of the parts list (default: labels = same as the labels).")
    g.add_argument("--parts-show", metavar="COLUMNS", default="",
                   help=f"Comma-separated parts list columns/options to turn on: "
                        f"{_flag_names('parts')}. On by default: lego-color, bl-color, "
                        f"pieces, people, weight.")
    g.add_argument("--parts-hide", metavar="COLUMNS", default="",
                   help="Comma-separated parts list columns/options to turn off.")
    g.add_argument("--lots-show", metavar="COLUMNS", default="",
                   help=f"Comma-separated lot counts columns/options to turn on: "
                        f"{_flag_names('lots')}. On by default: lots, pieces.")
    g.add_argument("--lots-hide", metavar="COLUMNS", default="",
                   help="Comma-separated lot counts columns/options to turn off.")
    g.add_argument("--lots-min-lots", metavar="N", type=_min_lots,
                   help=f"Leave people with fewer than N lots out of the lot counts "
                        f"(0-{MAX_MIN_LOTS}, default 0; larger numbers are capped).")


def _min_lots(text: str) -> int:
    try:
        return clamp_int(float(text), 0, MAX_MIN_LOTS, 0)
    except ValueError:
        import argparse
        raise argparse.ArgumentTypeError(f"'{text}' is not a whole number")


def _toggle(section: dict, name: str, show: str, hide: str) -> None:
    valid = TOGGLES[name]
    seen: dict[str, bool] = {}
    for items, value in ((hide, False), (show, True)):
        for raw in filter(None, (p.strip() for p in (items or "").split(","))):
            key = raw.lower().replace("-", "_")
            if key not in valid:
                raise ValueError(f"unknown {name} option '{raw}' (choose from "
                                 f"{_flag_names(name)})")
            if seen.get(key, value) != value:
                raise ValueError(f"'{raw}' is in both --{name}-show and --{name}-hide")
            seen[key] = value
    section.update(seen)


def options_from_args(args) -> dict:
    """The report options for a run: defaults, then --report-options FILE,
    then the flags. Raises ValueError (with a message fit for the user) on
    a bad file or flag value."""
    base = None
    if args.report_options:
        try:
            with open(args.report_options, encoding="utf-8") as f:
                text = f.read(MAX_OPTIONS_BYTES * 4 + 1)
        except OSError as e:
            raise ValueError(f"can't read --report-options file: {e.strerror or e}")
        if len(text) > MAX_OPTIONS_BYTES * 4:
            raise ValueError("--report-options file is too large")
        try:
            base = json.loads(text)
        except ValueError:
            raise ValueError(f"--report-options file '{args.report_options}' is not valid JSON")
    opts = normalize_options(base)

    page = {"title": args.report_title, "subtitle": args.report_subtitle,
            "paper": args.paper, "orientation": args.orientation}
    for name in REPORTS:
        for key, value in page.items():
            if value is not None:
                opts[name][key] = value
    if args.checklist_layout is not None:
        opts["checklist"]["layout"] = "page" if args.checklist_layout == "per-person" else args.checklist_layout
    if args.checklist_order is not None:
        opts["checklist"]["order"] = args.checklist_order
    if args.parts_order is not None:
        opts["parts"]["order"] = args.parts_order
    if args.lots_min_lots is not None:
        opts["lots"]["min_lots"] = args.lots_min_lots
    if args.sort_by_given:
        opts["checklist"]["sort"] = opts["lots"]["sort"] = args.sort_by_given
    for name in REPORTS:
        _toggle(opts[name], name, getattr(args, f"{name}_show"), getattr(args, f"{name}_hide"))
    return normalize_options(opts)
