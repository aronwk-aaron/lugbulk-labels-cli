"""Part weights (and BrickLink color names) from the BrickLink API.

For each LEGO element ID: GET /item_mapping/{element_id} gives the
BrickLink part number and color, then GET /items/PART/{no} gives the
catalog weight in grams. Results — including misses — are cached in
bricklink_cache.json, so a part costs two API calls once, ever (BrickLink
allows 5,000 calls a day).

The API needs OAuth 1.0 credentials from
https://www.bricklink.com/v2/api/register_consumer.page — a consumer key
and secret, plus an access token and secret, which BrickLink ties to the
IP address you'll call from. See README.md "BrickLink weights".
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

API_BASE = "https://api.bricklink.com/api/store/v1"
CACHE_PATH = "bricklink_cache.json"
# A part BrickLink didn't know (or had no weight for) is asked about again
# after this long, in case the catalog has caught up with a new element.
MISS_RETRY_SECONDS = 7 * 24 * 60 * 60
WORKERS = 4


class BrickLinkError(Exception):
    """The API refused the request (bad credentials, wrong IP, ...)."""


@dataclass(frozen=True)
class Credentials:
    consumer_key: str
    consumer_secret: str
    token: str
    token_secret: str


@dataclass(frozen=True)
class PartInfo:
    part_no: str | None  # BrickLink item number, e.g. "3004"
    color: str | None  # BrickLink color name
    weight: float | None  # grams per piece


def _pct(value: str) -> str:
    return urllib.parse.quote(str(value), safe="~-._")


def oauth_header(method: str, url: str, creds: Credentials, params: dict | None = None,
                 nonce: str | None = None, timestamp: str | None = None) -> str:
    """OAuth 1.0 HMAC-SHA1 Authorization header (RFC 5849). `params` are
    the request's query/form parameters, which are part of the signature."""
    oauth = {
        "oauth_consumer_key": creds.consumer_key,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_token": creds.token,
        "oauth_version": "1.0",
    }
    pairs = sorted((_pct(k), _pct(v)) for k, v in {**(params or {}), **oauth}.items())
    base = "&".join([method.upper(), _pct(url), _pct("&".join(f"{k}={v}" for k, v in pairs))])
    key = f"{_pct(creds.consumer_secret)}&{_pct(creds.token_secret)}"
    oauth["oauth_signature"] = base64.b64encode(
        hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth.items()))


def _get(path: str, creds: Credentials):
    """GET an API path; returns the response's `data`, or None if BrickLink
    says the item doesn't exist. Raises BrickLinkError for anything that
    means every other request will fail too (auth, IP, quota)."""
    url = API_BASE + path
    req = urllib.request.Request(url, headers={"Authorization": oauth_header("GET", url, creds)})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except ValueError:
            raise BrickLinkError(f"HTTP {e.code} from BrickLink") from e
    meta = body.get("meta", {})
    code = meta.get("code")
    if code == 200:
        return body.get("data")
    if code in (400, 404):  # unknown element / item
        return None
    raise BrickLinkError(f"{meta.get('message', 'error')}: {meta.get('description', '')} "
                         f"(code {code})")


def _weight(raw) -> float | None:
    try:
        weight = float(raw)
    except (TypeError, ValueError):
        return None
    return weight if weight > 0 else None  # the catalog uses 0 for "unknown"


def _fetch(element_id: str, creds: Credentials) -> PartInfo:
    mappings = _get(f"/item_mapping/{element_id}", creds) or []
    mapping = next((m for m in mappings if m.get("item", {}).get("type") == "PART"), None)
    if not mapping:
        return PartInfo(None, None, None)
    part_no = mapping["item"]["no"]
    item = _get(f"/items/PART/{urllib.parse.quote(part_no, safe='')}", creds) or {}
    return PartInfo(part_no, mapping.get("color_name") or None, _weight(item.get("weight")))


def _load_cache(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def _save_cache(path: str, cache: dict) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def lookup(element_ids, creds: Credentials,
           cache_path: str = CACHE_PATH) -> tuple[dict[str, PartInfo], str | None]:
    """PartInfo for each element ID BrickLink knows, from the cache or the
    API, plus an error message if the API rejected the credentials partway
    (whatever was fetched is still returned and cached)."""
    cache = _load_cache(cache_path)
    now = time.time()

    def fresh(entry: dict | None) -> bool:
        if not entry:
            return False
        if entry.get("weight") is not None:
            return True  # catalog weights don't change
        return now - entry.get("fetched", 0) < MISS_RETRY_SECONDS

    todo = sorted({e for e in element_ids if not fresh(cache.get(e))})
    error: BrickLinkError | None = None
    if todo:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {e: pool.submit(_fetch, e, creds) for e in todo}
            for element_id, future in futures.items():
                try:
                    info = future.result()
                except BrickLinkError as e:
                    error = error or e
                    continue
                except OSError:
                    continue  # network blip: leave uncached, try next run
                cache[element_id] = {"part": info.part_no, "color": info.color,
                                     "weight": info.weight, "fetched": now}
        _save_cache(cache_path, cache)

    found = {
        e: PartInfo(cache[e].get("part"), cache[e].get("color"), cache[e].get("weight"))
        for e in element_ids if e in cache
    }
    return found, (str(error) if error else None)
