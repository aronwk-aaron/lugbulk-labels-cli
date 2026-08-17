# sheet-labels

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

Produces `labels.pdf`, sized for Avery 5160 (1" x 2-5/8", 3 across x 10
down, 30/sheet, US Letter). When printing, use "Actual size" / 100% scale
in the print dialog — not "Fit to page" — or the die-cut alignment will
be off.

Part thumbnails are downloaded from LEGO's CDN by Element ID and cached
in `image_cache/` so re-runs don't re-fetch images already seen.

## Customizing the label size

Other Avery sizes can be added to `LABEL_SPECS` in `config.py`, then
set `ACTIVE_LABEL_SPEC` to the new key.
