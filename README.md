# lugbulk-label

> **AI disclaimer:** This project was written with assistance from Claude
> (Anthropic). Review the code before relying on it, especially the Sheets
> parsing logic and label layout math.

Reads rows from a Google Sheet (read-only) — or a downloaded `.xlsx` of
it — and renders them onto label PDFs, ready to print. Built for pivoting
a "one column per person" order sheet into individual part-request labels
(part thumbnail, Element ID, LEGO and BrickLink color, description,
quantity, person name, and "3 of 10" within the part).

## Download

Every [release](https://github.com/aronwk-aaron/lugbulk-labels-cli/releases)
has standalone programs for Windows, macOS (Apple Silicon) and Linux — no
Python needed. The **canary** pre-release is always the latest code on
`master`; `v*` releases are the stable ones. Put the program in a folder
and run it from a terminal there (`lugbulk-label --help`); it reads
`config_local.py`, `service_account.json` and writes its outputs in that
folder. `--source-file` runs need no setup at all.

To run from source instead, follow Setup below.

## Releases

`.github/workflows/build.yml` runs the tests and builds and smoke-tests
the three binaries on every pull request and push, then publishes:

| Event | GitHub release |
|---|---|
| Push to `master` | Rolling **canary** pre-release — always the head of `master` — with fresh binaries and the changes since the last release |
| Push a `vX.Y.Z` tag | Release `vX.Y.Z` with generated notes and binaries |
| Push a `vX.Y.Z-rc.N` tag | Pre-release |

`--version` shows which build you have (`1.2.0`, `canary-<sha>`, or `dev`
from a checkout). To cut a release: `git tag v1.2.0 && git push origin v1.2.0`.

## Setup

### 1. Install dependencies

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Create a Google Cloud service account

The script authenticates as a service account, not as you — no OAuth
consent screen, no browser login.

1. Go to [console.cloud.google.com](https://console.cloud.google.com).
2. Create a new project (or reuse one) via the project dropdown, top-left.
3. Enable the API: search bar → "Google Sheets API" → **Enable**.
4. Create the service account: left sidebar → **IAM & Admin** →
   **Service Accounts** → **Create Service Account**.
   - Any name works (e.g. `sheet-labels-reader`).
   - Skip granting it project roles — it only needs Sheets access, not GCP
     access — click through to **Done**.
5. Create a key: click the new service account → **Keys** tab → **Add Key**
   → **Create new key** → **JSON** → **Create**. This downloads a JSON file.
6. Move it into the project root and rename it:
   ```
   mv ~/Downloads/<downloaded-file>.json service_account.json
   ```
   This file is gitignored — never commit it.

### 3. Give the service account read access to your sheet

- If the sheet has **"Anyone with the link can view"** turned on (Share →
  General access), no further action is needed — the service account can
  already read it.
- Otherwise, open the JSON key file, copy the `client_email` value
  (looks like `sheet-labels-reader@your-project.iam.gserviceaccount.com`),
  and share the sheet with that email as a **Viewer**.

### 4. Configure the event-specific values

```
cp config_local.example.py config_local.py
```

Edit `config_local.py`:
- `SHEET_ID` — the long ID in the sheet's URL, between `/d/` and `/edit`.
- `COLOR_OVERRIDES` / `LEGO_COLOR_OVERRIDES` — optional manual fixes for
  the BrickLink / LEGO color name, keyed by Element ID.
- `WEIGHT_OVERRIDES` — optional grams-per-piece for parts whose size can't
  be estimated from the description (see [Label order](#label-order)).
- `OUTPUT_PDF` — optional. Set this to name the output PDF after the
  actual event (e.g. `"ArkLUG-2026-LUGBulk-labels.pdf"`) instead of the
  generic `labels.pdf` default.

`config_local.py` is gitignored — it holds the sheet ID and any per-event
overrides, kept out of the public repo.

### 5. Check the sheet's layout is recognized

The source tab (`SOURCE_TAB`, default `"Order Here"`) is read by
`pivot.py`, which finds its columns by **header text** rather than fixed
positions:

- Element ID: `"Element ID"` or `"Part Number"`
- Description: `"Description"`
- Colors: `"LEGO Color"` and/or `"BL Color"` (either or both — whichever
  is missing is looked up, see [Colors](#colors))
- Weight (optional): `"Weight"` — grams per piece, used for part ordering

The header row can be anywhere in the first 10 rows (exports sometimes
have a totals row above it). Two ways of laying out the people are
recognized:

- **qty markers** (the ArkLUG sheet): names on the header row, and the row
  below marks each person's quantity column `qty` (next to a `$$` column).
- **name/cost pairs** (2026's master sheet): each person is a header cell
  with their name followed by one with their running cost total.

Run `--validate` against a new sheet to confirm the people and parts it
finds look right. If your headers use different words, add them to the
`*_HEADERS` tuples in `config.py`.

## Run

```
.venv/bin/python main.py
```

Without `--source-file`, `SHEET_ID` must be set in `config_local.py` (see
step 4). Produces `labels.pdf` (or the name set by `OUTPUT_PDF` in
`config_local.py` — see below), sized for Avery 5162 (1-1/3" x 4", 2
across x 7 down, 14/sheet, US Letter) by default — see
[Label sizes](#label-sizes). When printing, use "Actual size" / 100% scale
in the print dialog — not "Fit to page" — or the die-cut alignment will be
off.

Part thumbnails are downloaded from LEGO's CDN by Element ID and cached
in `image_cache/` so re-runs don't re-fetch images already seen (unique
images are prefetched in parallel before rendering). A failed download is
cached as a miss and retried after 24 hours, rather than staying blank
forever. Rows with a blank or zero quantity for a given person are
skipped — one label is only generated per (person, part) pair with
qty > 0. Quantities may use thousands separators ("2,000") — they're
parsed the same as "2000".

Label text auto-shrinks to fit the label width, truncating with an
ellipsis as a last resort for unusually long values. Trans, white, and
otherwise very pale parts nearly vanish in LEGO's white-background photos,
so their thumbnails are set on a light gray rounded tile instead: trans
parts read like glass in front of it, white parts are cut out and stay
white (cached as `image_cache/<id>.backdrop1.png`).

### Label order

Labels are grouped by part, and numbered within it ("3 of 10") so whoever
is splitting a bulk bag knows when that part is done:

- **Parts** go heaviest first by default (`--part-order lightest` or
  `sheet` to change). Weight is, in priority order: `WEIGHT_OVERRIDES` in
  `config_local.py`, the sheet's `Weight` column, the BrickLink catalog
  (see [BrickLink weights](#bricklink-weights)), or an estimate from the
  description's stud dimensions (`PLATE 4X8`, `BRICK 1X2X5`,
  `BRICK 1X1X1 2/3`, DUPLO counted double-size). Parts with none of those
  (plants, animals, minifig parts…) go last in sheet order, marked "size
  unknown" in `--validate`/`--parts` output.
- **Within a part**, smallest quantity first (ties by last name).

### Colors

Labels show both the LEGO and the BrickLink color name. Sheets usually
fill in only one — LEGO's abbreviated names (`MED. ST-GREY`,
`BR.YEL-GREEN`, `TR.L.BLUE`) or BrickLink's (`Light Bluish Gray`) — and
the other is looked up in `colors.py`. A color it doesn't know shows as an
`unmapped_color` issue in `--validate`; add the pair to `COLORS` in
`colors.py` (or a per-element override in `config_local.py`).

### CLI options

```
.venv/bin/python main.py [options]
```

| Flag | Effect |
|---|---|
| `--validate` | Check the sheet for data problems (duplicate person+part entries, non-numeric qty, bad element IDs, missing/unmapped colors, missing description) and print a report, including the part order. Doesn't download images or write a PDF — fast pre-flight check before a real run. |
| `--manifest` | Also write `manifest.txt` (per-person and per-part totals, sheet-capacity estimate, any issues found) and `manifest.csv` (one row per label, for spot-checking in a spreadsheet). |
| `--lot-counts` | Print, and write to `lot_counts.csv` and `lot_counts.pdf`, each person's lot count (number of labels/line items) and total pieces. No images needed. |
| `--parts` | Write `parts.csv` and `parts.pdf`: one row per part, in label order, with total pieces, how many people ordered it, and its weight. No images needed; combine with `--lot-counts` for both. |
| `--part-order {heaviest,lightest,sheet}` | Order of parts on the labels and parts list (default: `heaviest`). |
| `--per-person` | Also write one label PDF per person into `labels_by_person/`, alongside the combined `labels.pdf`. |
| `--no-bricklink` | Skip BrickLink lookups even if credentials are configured. |
| `--label-spec STOCK` | Label stock by part number, e.g. `avery5162`, `8162`, `dymo30857` (default: `avery5162`) — see [Label sizes](#label-sizes). |
| `--list-labels` | List every supported Avery and Dymo stock. |
| `--sort-by {last,first}` | Sort people by first or last name in `--validate`/`--manifest`/`--lot-counts` output (default: `last`). |
| `--source-file PATH` | Read order data from a local `.xlsx` file instead of the Google Sheet — see [Using a local .xlsx file instead of the Sheet](#using-a-local-xlsx-file-instead-of-the-sheet). |
| `--sheet-id ID` | Read a different Google Sheet for this run, overriding `SHEET_ID` — handy when several groups' sheets are shared with the service account. |
| `--output PATH` | Output PDF filename for this run, overriding `OUTPUT_PDF` (default: the generic `labels.pdf`, or the name set in `config_local.py`). Only affects the combined label PDF — `--manifest`/`--lot-counts` filenames are unchanged. |

Run `--validate` first on a new or freshly-edited sheet — it catches
data-entry mistakes (like a quantity typed as `"2,ooo"` instead of
`"2000"`) before you've spent time downloading images and printing.

## Using a local .xlsx file instead of the Sheet

Every command works against a downloaded/exported `.xlsx` copy of the
order sheet instead of the live Google Sheet — pass `--source-file`:

```
.venv/bin/python main.py --source-file LUGbulk2026_master.xlsx --validate
.venv/bin/python main.py --source-file LUGbulk2026_master.xlsx --manifest
.venv/bin/python main.py --source-file LUGbulk2026_master.xlsx --output Briggs-LUGBulk-labels.pdf
```

This needs no `config_local.py`/`SHEET_ID`/service account — those are
only required for the default (no `--source-file`) Google Sheets path.
Both ways of running coexist; pick whichever fits a given run. Since
`.xlsx` runs don't go through `config_local.py`, use `--output` (see the
CLI options table above) to name the label PDF instead of `OUTPUT_PDF` —
otherwise it falls back to the generic `labels.pdf`/configured default.
`--manifest` and `--lot-counts` always use their fixed filenames
(`manifest.csv`/`.txt`, `lot_counts.csv`/`.pdf`) regardless of source;
rename them afterward if you're running both sources side by side and
want to keep both sets.

The `.xlsx` path uses the same header-based reader as the live sheet (see
step 5 above), plus tolerance for a renamed tab (`"OrderHere"` vs
`"Order Here"`), so everything downstream behaves the same either way.

## Fixing missing/wrong colors

If a part's color is blank, wrong, or `unmapped_color` in `--validate`,
add an entry to `COLOR_OVERRIDES` (BrickLink name) or
`LEGO_COLOR_OVERRIDES` (LEGO name) in `config_local.py`, keyed by
Element ID:

```python
COLOR_OVERRIDES = {
    "6584805": "Warm Pink",
}
```

This only affects the rendered label — it never writes back to the sheet.

## BrickLink weights

With BrickLink API credentials configured, every part is looked up on
BrickLink: its catalog weight orders the labels, and its BrickLink color
fills in any color the sheet left blank (or wrote as `unknown`). Lookups
are cached in `bricklink_cache.json` (a part costs two API calls, once;
parts BrickLink doesn't know are retried after a week), so later runs are
instant and offline-safe. Without credentials — or with `--no-bricklink` —
weights fall back to estimates.

To get credentials:

1. Log in to BrickLink and open
   [API registration](https://www.bricklink.com/v2/api/register_consumer.page)
   (BrickLink may require your account to have a store — a closed one is
   fine).
2. Register a consumer to get a **consumer key** and **consumer secret**.
3. Create an **access token** for the IP address you'll run from (your
   public IP — BrickLink rejects calls from any other with
   `TOKEN_IP_MISMATCHED`); note its **token** and **token secret**.
4. Put all four in `config_local.py`:

   ```python
   BRICKLINK = {
       "consumer_key": "...", "consumer_secret": "...",
       "token": "...", "token_secret": "...",
   }
   ```

   or export `BRICKLINK_CONSUMER_KEY`, `BRICKLINK_CONSUMER_SECRET`,
   `BRICKLINK_TOKEN`, `BRICKLINK_TOKEN_SECRET`.

If BrickLink rejects the credentials, the run prints why and carries on
with cached/estimated weights.

## Label sizes

Any common Avery or Dymo stock works — 51 stocks (Avery US-Letter and A4,
Dymo LabelWriter rolls), plus 112 equivalent part numbers. Pass the part
number printed on the box to `--label-spec`: `avery5162`, `8162`,
`Avery 5160`, `L7163`, `dymo30857` all work. The default is Avery 5162
(1-1/3" x 4", 14/sheet). See them all with:

```
.venv/bin/python main.py --list-labels
```

The label layout scales with the label, so any size gets the same design
and inner margin. Dymo roll labels are one label per page — print with the
Dymo driver's matching paper size. Tiny stock (return-address, file-folder
tabs) is left out as too small for the design, as are portrait-only sheets.

The inventory lives in `label_specs.json`, generated from the
[gLabels](https://github.com/jimevins/glabels-qt) template database (MIT
licensed) plus a few Dymo rolls it lacks:

```
.venv/bin/python tools/update_label_specs.py
cp label_specs.json ../lugbulk-labels-web/data/   # keep the web app in step
```

## Tests

```
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

## Project files

| File | Purpose |
|---|---|
| `main.py` | Entry point and CLI — parses flags, pulls records, dispatches to the right output(s) |
| `sheets_source.py` | Reads the Google Sheet (read-only) |
| `xlsx_source.py` | Reads a local `.xlsx` file instead (`--source-file`) |
| `pivot.py` | Turns either source's rows into per-label records, flagging data issues |
| `records.py` | The record/issue types, element ID validation, color override handling |
| `colors.py` | LEGO <-> BrickLink color name table |
| `ordering.py` | Part weight estimates, label order, "N of M" numbering, per-part summaries |
| `bricklink.py` | BrickLink API client (OAuth 1.0) and lookup cache — weights and colors |
| `render_labels.py` | Draws each label (thumbnail, text, layout), lays out the PDF, prefetches and outlines images |
| `manifest.py` | Builds the summary/manifest report, lot-count and parts-list CSV/PDF |
| `config.py` | Shared/non-sensitive config (header names, label stock lookup, output paths) |
| `label_specs.json` | Avery/Dymo label stock inventory (generated) |
| `tools/update_label_specs.py` | Regenerates `label_specs.json` from gLabels |
| `config_local.py` | Your sheet ID, overrides, and output filename — gitignored |
| `tests/` | pytest suite (`tests/fixtures/sample_order.xlsx` is a made-up order sheet) |
| `version.py` | Build version, rewritten by CI |
| `.github/workflows/build.yml` | CI: tests, standalone binaries, canary and versioned releases |
| `config_local.example.py` | Template for `config_local.py` |
