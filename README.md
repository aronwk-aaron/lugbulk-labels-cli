# lugbulk-label

> **AI disclaimer:** This project was written with assistance from Claude
> (Anthropic). Review the code before relying on it, especially the Sheets
> parsing logic and label layout math.

Reads rows from a Google Sheet (read-only) and renders them onto an
Avery 5160-style label sheet PDF, ready to print. Built for pivoting a
"one column per person" order sheet into individual part-request labels
(part thumbnail, Element ID, color, description, quantity, person name).

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
- `COLOR_OVERRIDES` — optional manual fixes for elements where the sheet's
  own color lookup is blank/`"unknown"`, keyed by Element ID.
- `OUTPUT_PDF` — optional. Set this to name the output PDF after the
  actual event (e.g. `"ArkLUG-2026-LUGBulk-labels.pdf"`) instead of the
  generic `labels.pdf` default.

`config_local.py` is gitignored — it holds the sheet ID and any per-event
overrides, kept out of the public repo.

### 5. Check the sheet's column layout matches

`config.py` assumes the source tab (`SOURCE_TAB`, default `"Order Here"`)
is shaped like:

```
# | Element ID | Photo | Description | BL Color | Cost Each | ... | <Person 1> (qty, $) | <Person 2> (qty, $) | ...
```

with person names in row 1 (`HEADER_ROW`) and part data starting row 3
(`DATA_START_ROW`). If your sheet's tab name or column indices differ,
adjust `SOURCE_TAB`, `COL_ELEMENT_ID`, `COL_DESCRIPTION`, `COL_COLOR`,
`FIRST_PERSON_COL`, `LAST_PERSON_COL` in `config.py` accordingly.

## Run

```
.venv/bin/python main.py
```

If `config_local.py` is missing, this exits with a message telling you to
create it (see step 4). Produces `labels.pdf` (or the name set by
`OUTPUT_PDF` in `config_local.py` — see below), sized for Avery 5160
(1" x 2-5/8", 3 across x 10 down, 30/sheet, US Letter). When printing, use
"Actual size" / 100% scale in the print dialog — not "Fit to page" — or
the die-cut alignment will be off.

Part thumbnails are downloaded from LEGO's CDN by Element ID and cached
in `image_cache/` so re-runs don't re-fetch images already seen (unique
images are prefetched in parallel before rendering). A failed download is
cached as a miss and retried after 24 hours, rather than staying blank
forever. Rows with a blank or zero quantity for a given person are
skipped — one label is only generated per (person, part) pair with
qty > 0. Quantities may use thousands separators ("2,000") — they're
parsed the same as "2000".

Label text (color, description, person name) auto-shrinks to fit the
label width, truncating with an ellipsis as a last resort for unusually
long values.

### CLI options

```
.venv/bin/python main.py [options]
```

| Flag | Effect |
|---|---|
| `--validate` | Check the sheet for data problems (duplicate person+part entries, non-numeric qty, missing color/description) and print a report. Doesn't download images or write a PDF — fast pre-flight check before a real run. |
| `--manifest` | Also write `manifest.txt` (per-person and per-part totals, sheet-capacity estimate, any issues found) and `manifest.csv` (one row per label, for spot-checking in a spreadsheet). |
| `--lot-counts` | Print, and write to `lot_counts.csv` and `lot_counts.pdf`, each person's lot count (number of labels/line items) and total pieces. No images needed. |
| `--per-person` | Also write one label PDF per person into `labels_by_person/`, alongside the combined `labels.pdf`. |
| `--label-spec {avery5160,avery5163}` | Label sheet format to use (default: `avery5160`, 30/sheet). `avery5163` is 2"x4", 10/sheet — more room per label, fewer sheets to buy/feed. |
| `--sort-by {last,first}` | Sort people by first or last name in `--validate`/`--manifest`/`--lot-counts` output (default: `last`). |

Run `--validate` first on a new or freshly-edited sheet — it catches
data-entry mistakes (like a quantity typed as `"2,ooo"` instead of
`"2000"`) before you've spent time downloading images and printing.

## Fixing missing/wrong colors

If the sheet's own color lookup is blank or `"unknown"` for a part, add
an entry to `COLOR_OVERRIDES` in `config_local.py`, keyed by Element ID:

```python
COLOR_OVERRIDES = {
    "6584805": "Warm Pink",
}
```

This only affects the rendered label — it never writes back to the sheet.

## Customizing the label size

Two Avery formats ship built in: `avery5160` (1"x2-5/8", 30/sheet,
default) and `avery5163` (2"x4", 10/sheet). Switch between them with
`--label-spec` on the command line — no code changes needed. Other
sizes can be added to `LABEL_SPECS` in `config.py`; set
`ACTIVE_LABEL_SPEC` to change the default, or just pass `--label-spec`
per run.

## Project files

| File | Purpose |
|---|---|
| `main.py` | Entry point and CLI — parses flags, pulls records, dispatches to the right output(s) |
| `sheets_source.py` | Reads the sheet (read-only), pivots it into per-label records, and flags data issues |
| `render_labels.py` | Draws each label (thumbnail, text, layout), lays out the PDF, and prefetches images |
| `manifest.py` | Builds the summary/manifest report and lot-count CSV/PDF |
| `config.py` | Shared/non-sensitive config (tab layout, label specs, output paths) |
| `config_local.py` | Your sheet ID, color overrides, and output filename — gitignored |
| `config_local.example.py` | Template for `config_local.py` |
