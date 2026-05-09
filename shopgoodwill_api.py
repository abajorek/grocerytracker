#!/usr/bin/env python3
"""
Goodwill Hunting - ShopGoodwill TikTok-style backend

Wraps ShopGoodwill's public ItemListing search and stores pinned brands +
saved listings. Storage gracefully degrades:

  * If SUPABASE_URL + SUPABASE_KEY are set, persists via Supabase's REST
    API (PostgREST). No Postgres driver required.
  * Otherwise falls back to local JSON files in ./data/ (dev mode).

Local:
    pip install -r requirements.txt
    python shopgoodwill_api.py

Production (Render / Railway / Fly):
    uvicorn shopgoodwill_api:app --host 0.0.0.0 --port $PORT

If anonymous ShopGoodwill search starts returning 401, set
SHOPGOODWILL_TOKEN to a JWT lifted from a logged-in browser session.
The same token is required for /api/bid (placing real bids).
"""

import html as html_module
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from zoneinfo import ZoneInfo
    _PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover
    _PACIFIC = timezone.utc

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel


SHOPGOODWILL_BASE = "https://buyerapi.shopgoodwill.com/api"
FALLBACK_IMAGE_BASE = "https://shopgoodwillimages.azureedge.net/production/"

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
FAVORITES_FILE = DATA_DIR / "favorites.json"
BRANDS_FILE = DATA_DIR / "brands.json"
FRONTEND_FILE = ROOT / "shopgoodwill_feed.html"
MANIFEST_FILE = ROOT / "manifest.webmanifest"
ICON_FILE = ROOT / "icon.svg"

DEFAULT_BRANDS = [
    "Coach",
    "Madewell",
    "Free People",
    "Anthropologie",
    "Patagonia",
    "J.Crew",
    "Eileen Fisher",
    "Lululemon",
]

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or ""


class FeedItem(BaseModel):
    id: int
    title: str
    image_url: str
    images: List[str] = []
    current_price: float
    minimum_bid: float
    bid_count: int
    end_time: str
    seconds_left: int
    listing_url: str
    brand: str
    location: Optional[str] = None


class Favorite(BaseModel):
    item_id: int
    title: str
    image_url: str
    listing_url: str
    saved_at: str
    brand: Optional[str] = ""


class BidRequest(BaseModel):
    item_id: int
    amount: float
    quantity: int = 1


app = FastAPI(title="Goodwill Hunting")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- helpers ----------

def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2))


def _build_image_url(image_server: str, image_path: str) -> str:
    if not image_path:
        return ""
    image_path = image_path.replace("\\", "/").strip()
    if image_path.startswith("http://") or image_path.startswith("https://"):
        return image_path
    base = (image_server or FALLBACK_IMAGE_BASE).rstrip("/")
    return f"{base}/{image_path.lstrip('/')}"


def _seconds_until(end_time_str: str) -> int:
    if not end_time_str:
        return 0
    try:
        s = end_time_str.replace("Z", "+00:00")
        end = datetime.fromisoformat(s)
    except Exception:
        return 0
    if end.tzinfo is None:
        end = end.replace(tzinfo=_PACIFIC)
    delta = (end - datetime.now(timezone.utc)).total_seconds()
    return max(0, int(delta))


def _normalize_item(raw: dict, brand_query: str) -> Optional[FeedItem]:
    item_id = raw.get("itemId") or raw.get("id") or 0
    if not item_id:
        return None
    image_path = (
        raw.get("imageURL")
        or raw.get("imageUrlString")
        or raw.get("image")
        or ""
    )
    if isinstance(image_path, str) and ";" in image_path:
        image_path = image_path.split(";", 1)[0]
    image_url = _build_image_url(raw.get("imageServer", "") or "", image_path)
    if not image_url:
        return None
    end_time = raw.get("endTime") or raw.get("endDate") or ""
    return FeedItem(
        id=int(item_id),
        title=str(raw.get("title", "") or "").strip(),
        image_url=image_url,
        images=[image_url],
        current_price=float(raw.get("currentPrice", 0) or 0),
        minimum_bid=float(raw.get("minimumBid", 0) or 0),
        bid_count=int(raw.get("bidCount", 0) or 0),
        end_time=end_time,
        seconds_left=_seconds_until(end_time),
        listing_url=f"https://shopgoodwill.com/item/{item_id}",
        brand=brand_query,
        location=raw.get("sellerName") or raw.get("location"),
    )


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://shopgoodwill.com",
    "Referer": "https://shopgoodwill.com/",
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not.A/Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def _shopgoodwill_payload(query: str, page: int, page_size: int) -> dict:
    return {
        "isSize": False,
        "isWeddingCatagory": "false",
        "isMultipleCategoryIds": False,
        "isFromHeaderMenuTab": False,
        "layout": "",
        "searchText": query.replace('"', ""),
        "selectedGroup": "",
        "selectedCategoryIds": "",
        "selectedSellerIds": "",
        "lowPrice": "0",
        "highPrice": "999999",
        "searchBuyNowOnly": "",
        "searchPickupOnly": "false",
        "searchNoPickupOnly": "false",
        "searchOneCentShippingOnly": "false",
        "searchDescriptions": "false",
        "searchClosedAuctions": "false",
        "closedAuctionEndingDate": "1/1/0001",
        "closedAuctionDaysBack": "7",
        "searchCanadaShipping": "false",
        "searchInternationalShippingOnly": "false",
        "sortColumn": "1",
        "sortDescending": "false",
        "savedSearchId": 0,
        "useBuyerPrefs": "true",
        "searchUSOnlyShipping": "false",
        "categoryLevelNo": "1",
        "categoryLevel": 1,
        "categoryId": 0,
        "partNumber": "",
        "catIds": "",
        "page": int(page),
        "pageSize": int(page_size),
    }


def _shopgoodwill_request(query: str, page: int, page_size: int) -> requests.Response:
    headers = dict(DEFAULT_HEADERS)
    token = os.environ.get("SHOPGOODWILL_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.post(
        f"{SHOPGOODWILL_BASE}/Search/ItemListing",
        json=_shopgoodwill_payload(query, page, page_size),
        headers=headers,
        timeout=20,
    )


def _search_shopgoodwill(query: str, page: int = 1, page_size: int = 40) -> List[dict]:
    try:
        resp = _shopgoodwill_request(query, page, page_size)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"ShopGoodwill network error: {exc}")

    if not resp.ok:
        body = (resp.text or "")[:240].replace("\n", " ")
        raise HTTPException(
            status_code=502,
            detail=f"ShopGoodwill returned {resp.status_code}: {body}",
        )

    try:
        data = resp.json()
    except ValueError:
        snippet = (resp.text or "")[:240].replace("\n", " ")
        raise HTTPException(
            status_code=502,
            detail=f"ShopGoodwill returned non-JSON ({resp.status_code}): {snippet}",
        )

    if isinstance(data, dict):
        if "searchResults" in data and isinstance(data["searchResults"], dict):
            return data["searchResults"].get("items", []) or []
        return data.get("items", []) or []
    return []


def _place_bid(item_id: int, amount: float, quantity: int = 1) -> dict:
    token = os.environ.get("SHOPGOODWILL_TOKEN")
    if not token:
        raise HTTPException(
            status_code=401,
            detail=(
                "SHOPGOODWILL_TOKEN is not set on the server. Add your ShopGoodwill "
                "JWT in Render → Environment to enable bidding."
            ),
        )
    headers = dict(DEFAULT_HEADERS)
    headers["Authorization"] = f"Bearer {token}"
    payload = {
        "itemId": int(item_id),
        "bidAmount": f"{float(amount):.2f}",
        "quantity": int(quantity),
    }
    try:
        resp = requests.post(
            f"{SHOPGOODWILL_BASE}/ItemBid/PlaceBid",
            json=payload, headers=headers, timeout=20,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"ShopGoodwill network error: {exc}")

    if resp.status_code in (401, 403):
        raise HTTPException(
            status_code=401,
            detail=(
                "ShopGoodwill rejected the token (it may be expired). Log in again "
                "and update SHOPGOODWILL_TOKEN in Render → Environment."
            ),
        )
    if not resp.ok:
        body = (resp.text or "")[:300].replace("\n", " ")
        raise HTTPException(
            status_code=502,
            detail=f"ShopGoodwill returned {resp.status_code}: {body}",
        )

    try:
        return resp.json()
    except ValueError:
        return {"raw": (resp.text or "")[:300]}


_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_IMAGE_LIST_KEYS = (
    "imageUrlString", "imageURLString",
    "imageURLs", "imageUrls",
    "images", "itemImages", "additionalImages", "imageList", "galleryImages",
    "itemImageUrls", "itemImageURLs",
)
_IMAGE_SCALAR_KEYS = (
    "imageURL", "imageUrl", "imageName", "image",
    "largeImageURL", "largeImageUrl", "primaryImage",
)


def _looks_like_image_path(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    lower = value.lower().split("?", 1)[0]
    return lower.endswith(_IMAGE_SUFFIXES)


def _split_image_string(value: str) -> List[str]:
    if not value:
        return []
    pieces = value.replace(",", ";").split(";")
    return [p for p in (s.strip() for s in pieces) if p]


def _extract_gallery(detail: Any, image_server_default: str = "") -> List[str]:
    if not isinstance(detail, dict):
        return []
    image_server = (
        detail.get("imageServer")
        or detail.get("imageServerLocation")
        or image_server_default
        or FALLBACK_IMAGE_BASE
    )
    seen: set = set()
    out: List[str] = []

    def push(raw: Any):
        if not isinstance(raw, str):
            return
        url = raw.strip()
        if not url:
            return
        if not url.startswith("http"):
            if not _looks_like_image_path(url):
                return
            url = _build_image_url(image_server, url)
        else:
            url = url.replace("\\", "/")
        if url in seen:
            return
        seen.add(url)
        out.append(url)

    for key in _IMAGE_SCALAR_KEYS:
        if key in detail:
            push(detail.get(key))

    for key in _IMAGE_LIST_KEYS:
        items = detail.get(key)
        if isinstance(items, str):
            for piece in _split_image_string(items):
                push(piece)
        elif isinstance(items, list):
            for it in items:
                if isinstance(it, str):
                    push(it)
                elif isinstance(it, dict):
                    for k in ("imageURL", "imageUrl", "url", "fileName", "name", "src"):
                        if k in it:
                            push(it[k])
                            break

    return out


# ---------- description / notes extraction ----------

_BLOCK_TAGS_RE = re.compile(
    r'<\s*(br|/p|/li|/div|/h[1-6]|/tr|/table)\s*/?\s*>',
    re.IGNORECASE,
)
_TAGS_RE = re.compile(r'<[^>]+>')

_NOTE_BLOCKLIST = re.compile(
    r'(\breturns?\b|\brefunds?\b|\bshipping\b|\bpolic(y|ies)\b|paypal|'
    r'\binsurance\b|\brestocking\b|\bs&h\b|please\s+(note|see|contact)|'
    r'thank you|good luck|happy bidding|customer service|tickets?|'
    r'business days|\bverified\b|\bdistortion\b|gemologist|\bcertified\b|'
    r'goodwill 2 ?go|goodwill\s+industries|donation|claim|address|'
    r'authoriz|combined\s+shipping|warranty|disabilities|barriers'
    r'|presents:|patronage|tampered|forfeit|signature required|'
    r'\bAs Is\b|\bnot return\b|please\s+follow|please\s+be\s+advised|'
    r'msrp|appraisal|appraised|professional|magnetic content|'
    r'pickup\s+(instructions|policy)|combined|\.com\b|http)',
    re.IGNORECASE,
)

_NOTE_LINE_RE = re.compile(r'^([^:]{2,30}?)\s*:\s*(.+)$')


def _strip_html(value: str) -> str:
    if not value:
        return ""
    text = _BLOCK_TAGS_RE.sub("\n", value)
    text = _TAGS_RE.sub(" ", text)
    text = html_module.unescape(text)
    text = text.replace(" ", " ").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text


def _extract_notes(html_description: str) -> List[str]:
    """Pull "Label: value" item-spec lines from the HTML description, dropping
    boilerplate (return policy, shipping, marketing)."""
    text = _strip_html(html_description)
    out: List[str] = []
    seen = set()
    for raw_line in re.split(r'[\n\r]+', text):
        line = raw_line.strip(" \t-•* ")
        if not line or len(line) > 140:
            continue
        m = _NOTE_LINE_RE.match(line)
        if not m:
            continue
        label, value = m.group(1).strip(), m.group(2).strip()
        if not value or len(value) > 100:
            continue
        if _NOTE_BLOCKLIST.search(line):
            continue
        norm = (label.lower(), value.lower())
        if norm in seen:
            continue
        seen.add(norm)
        out.append(f"{label}: {value}")
        if len(out) >= 8:
            break
    return out


def _fetch_item_detail(item_id: int) -> dict:
    headers = dict(DEFAULT_HEADERS)
    token = os.environ.get("SHOPGOODWILL_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.get(
            f"{SHOPGOODWILL_BASE}/itemDetail/GetItemDetailModelByItemId/{int(item_id)}",
            headers=headers, timeout=15,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"ShopGoodwill network error: {exc}")
    if not resp.ok:
        body = (resp.text or "")[:240].replace("\n", " ")
        raise HTTPException(
            status_code=502,
            detail=f"ShopGoodwill returned {resp.status_code}: {body}",
        )
    try:
        return resp.json()
    except ValueError:
        snippet = (resp.text or "")[:240].replace("\n", " ")
        raise HTTPException(
            status_code=502, detail=f"non-JSON ({resp.status_code}): {snippet}"
        )


# ---------- eBay sold-listing comps ----------

_TITLE_NOISE = re.compile(
    r'\b(BEST\s+PRICE|NWT|NWOT|EUC|GUC|VTG|VINTAGE|RARE|SEALED|LOT\s+OF|'
    r'NIB|MIB|VG\+?|NEW\s+WITH\s+TAGS|PREOWNED|PRE-OWNED|AS\s+IS)\b',
    re.IGNORECASE,
)


def _clean_title_for_comps(title: str) -> str:
    if not title:
        return ""
    cleaned = _TITLE_NOISE.sub(" ", title)
    cleaned = re.sub(r"[\(\)\[\]\{\}]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:90]


def _shorten_title(title: str) -> str:
    """Take the first 5-6 significant words for a fallback narrower search."""
    words = [w for w in title.split() if len(w) >= 2]
    if len(words) <= 5:
        return title
    return " ".join(words[:6])


def _ebay_search_sold(query: str) -> Optional[dict]:
    if len(query) < 4:
        return None
    try:
        resp = requests.get(
            "https://www.ebay.com/sch/i.html",
            params={
                "_nkw": query,
                "LH_Sold": "1",
                "LH_Complete": "1",
                "_sop": "13",  # sort: ended recently
                "_ipg": "60",  # 60 per page
            },
            headers=BROWSER_HEADERS,
            timeout=12,
        )
    except requests.RequestException:
        return None
    if not resp.ok:
        return None

    body = resp.text or ""
    # Pull the price spans. eBay's class is "s-item__price"; the very first
    # "Shop on eBay" promo card has its own price block we want to skip.
    raw_prices: List[float] = []
    for m in re.finditer(r's-item__price[^>]*>([^<]+)<', body):
        snippet = m.group(1)
        for v in re.findall(r'\$\s*([0-9,]+(?:\.\d{2})?)', snippet):
            try:
                raw_prices.append(float(v.replace(",", "")))
            except ValueError:
                continue
    # eBay tends to repeat the promo card price; drop the first if we got many.
    if len(raw_prices) >= 6:
        raw_prices = raw_prices[1:]

    # Need at least a handful of data points for a meaningful number.
    if len(raw_prices) < 3:
        return None

    raw_prices.sort()
    n = len(raw_prices)
    median = raw_prices[n // 2] if n % 2 else (raw_prices[n // 2 - 1] + raw_prices[n // 2]) / 2

    # Trim wild outliers (>3x or <0.2x median) before reporting low/high.
    filtered = [p for p in raw_prices if 0.2 * median <= p <= 3 * median]
    if len(filtered) < 3:
        filtered = raw_prices

    return {
        "query": query,
        "count": len(filtered),
        "median": round(median, 2),
        "low": round(filtered[0], 2),
        "high": round(filtered[-1], 2),
    }


_COMPS_CACHE: Dict[str, Dict[str, Any]] = {}
_COMPS_TTL = 600  # 10 minutes


def _ebay_comps(title: str) -> Optional[dict]:
    cleaned = _clean_title_for_comps(title)
    if not cleaned:
        return None

    cache = _COMPS_CACHE.get(cleaned)
    if cache and (time.time() - cache["t"] < _COMPS_TTL):
        return cache["v"]

    result = _ebay_search_sold(cleaned)
    if not result or result.get("count", 0) < 3:
        short = _shorten_title(cleaned)
        if short and short != cleaned:
            fallback = _ebay_search_sold(short)
            if fallback and fallback.get("count", 0) >= 3:
                result = fallback

    _COMPS_CACHE[cleaned] = {"v": result, "t": time.time()}
    if len(_COMPS_CACHE) > 200:
        for k in list(_COMPS_CACHE.keys())[:50]:
            _COMPS_CACHE.pop(k, None)
    return result


# ---------- storage (Supabase REST or local file) ----------

def _supabase_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def _supabase(method: str, path: str, *, body=None, params=None, prefer: Optional[str] = None):
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    try:
        resp = requests.request(
            method,
            f"{SUPABASE_URL}/rest/v1/{path}",
            headers=headers, params=params, json=body, timeout=15,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Supabase network error: {exc}")
    if not resp.ok:
        raise HTTPException(status_code=502, detail=f"Supabase {resp.status_code}: {resp.text[:240]}")
    if not resp.text:
        return []
    try:
        return resp.json()
    except ValueError:
        return []


def store_get_brands() -> List[str]:
    if _supabase_enabled():
        rows = _supabase(
            "GET", "thrift_settings",
            params={"key": "eq.brands", "select": "value"},
        )
        if rows and rows[0].get("value"):
            value = rows[0]["value"]
            if isinstance(value, list):
                return value
        return list(DEFAULT_BRANDS)
    return _read_json(BRANDS_FILE, list(DEFAULT_BRANDS))


def store_set_brands(brands: List[str]) -> List[str]:
    cleaned = [b.strip() for b in brands if b and b.strip()]
    if _supabase_enabled():
        _supabase(
            "POST", "thrift_settings",
            body={"key": "brands", "value": cleaned},
            prefer="return=minimal,resolution=merge-duplicates",
        )
        return cleaned
    _write_json(BRANDS_FILE, cleaned)
    return cleaned


def store_list_favorites() -> list:
    if _supabase_enabled():
        return _supabase(
            "GET", "thrift_favorites",
            params={"select": "*", "order": "saved_at.desc"},
        )
    return _read_json(FAVORITES_FILE, [])


def store_add_favorite(fav: Favorite) -> list:
    payload = {
        "item_id": fav.item_id,
        "title": fav.title,
        "image_url": fav.image_url,
        "listing_url": fav.listing_url,
        "brand": fav.brand or "",
        "saved_at": fav.saved_at,
    }
    if _supabase_enabled():
        _supabase(
            "POST", "thrift_favorites",
            body=payload,
            prefer="return=minimal,resolution=merge-duplicates",
        )
        return store_list_favorites()
    favs = _read_json(FAVORITES_FILE, [])
    if not any(f.get("item_id") == fav.item_id for f in favs):
        favs.append(payload)
        _write_json(FAVORITES_FILE, favs)
    return favs


def store_remove_favorite(item_id: int) -> list:
    if _supabase_enabled():
        _supabase(
            "DELETE", "thrift_favorites",
            params={"item_id": f"eq.{item_id}"},
        )
        return store_list_favorites()
    favs = _read_json(FAVORITES_FILE, [])
    remaining = [f for f in favs if f.get("item_id") != item_id]
    _write_json(FAVORITES_FILE, remaining)
    return remaining


# ---------- routes ----------

@app.get("/api/feed", response_model=List[FeedItem])
def get_feed(
    brand: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=100),
):
    raw_items = _search_shopgoodwill(brand, page=page, page_size=page_size)
    items: List[FeedItem] = []
    for raw in raw_items:
        try:
            normalized = _normalize_item(raw, brand)
        except Exception:
            continue
        if normalized is not None:
            items.append(normalized)
    return items


@app.get("/api/item/{item_id}")
def get_item(item_id: int):
    detail = _fetch_item_detail(item_id)
    if not isinstance(detail, dict):
        return {"id": item_id, "images": [], "notes": []}
    images = _extract_gallery(detail)
    title = (detail.get("title") or detail.get("itemTitle") or "").strip()
    notes = _extract_notes(detail.get("description") or "")
    city = (detail.get("pickupCity") or "").strip()
    state = (detail.get("pickupState") or "").strip()
    location = ", ".join(p for p in [city, state] if p)
    seller = (detail.get("sellerCompanyName") or "").strip()
    buy_now = float(detail.get("buyNowPrice") or 0) or None
    shipping = float(detail.get("shippingPrice") or detail.get("defaultShippingPrice") or 0) or None
    handling = float(detail.get("handlingPrice") or 0) or None
    return {
        "id": item_id,
        "title": title,
        "images": images,
        "notes": notes,
        "location": location,
        "seller": seller,
        "buy_now_price": buy_now,
        "shipping_price": shipping,
        "handling_price": handling,
    }


@app.get("/api/item/{item_id}/raw")
def get_item_raw(item_id: int):
    """Diagnostic: return the upstream item detail payload as-is."""
    return _fetch_item_detail(item_id)


@app.get("/api/comps")
def api_comps(title: str = Query(..., min_length=3)):
    """Recent eBay sold-listing comps for the given item title.

    Best-effort scrape of public sold-listing search results. eBay can rate-
    limit or change their HTML at any time; callers should treat a missing
    response as "no estimate available" rather than an error.
    """
    comps = _ebay_comps(title)
    if not comps:
        return {"ok": False, "reason": "no comps found", "query": _clean_title_for_comps(title)}
    return {"ok": True, **comps}


@app.post("/api/bid")
def api_place_bid(req: BidRequest):
    return {"ok": True, "result": _place_bid(req.item_id, req.amount, req.quantity)}


@app.get("/api/debug/upstream")
def debug_upstream(brand: str = "Coach", page: int = 1, page_size: int = 5):
    """Diagnostic: hit ShopGoodwill directly and return raw status + body snippet."""
    try:
        resp = _shopgoodwill_request(brand, page, page_size)
    except requests.RequestException as exc:
        return {"network_error": str(exc)}
    snippet = (resp.text or "")[:600]
    return {
        "status": resp.status_code,
        "content_type": resp.headers.get("Content-Type", ""),
        "body_snippet": snippet,
        "has_token": bool(os.environ.get("SHOPGOODWILL_TOKEN")),
    }


@app.get("/api/brands")
def get_brands():
    return store_get_brands()


@app.post("/api/brands")
def set_brands(brands: List[str]):
    return store_set_brands(brands)


@app.get("/api/favorites")
def list_favorites():
    return store_list_favorites()


@app.post("/api/favorites")
def add_favorite(fav: Favorite):
    return store_add_favorite(fav)


@app.delete("/api/favorites/{item_id}")
def remove_favorite(item_id: int):
    return store_remove_favorite(item_id)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "storage": "supabase" if _supabase_enabled() else "file",
        "bidding": bool(os.environ.get("SHOPGOODWILL_TOKEN")),
    }


@app.get("/")
def serve_frontend():
    if FRONTEND_FILE.exists():
        return FileResponse(str(FRONTEND_FILE), media_type="text/html")
    raise HTTPException(status_code=404, detail="shopgoodwill_feed.html not found")


@app.get("/manifest.webmanifest")
def serve_manifest():
    if MANIFEST_FILE.exists():
        return FileResponse(str(MANIFEST_FILE), media_type="application/manifest+json")
    raise HTTPException(status_code=404)


@app.get("/icon.svg")
def serve_icon():
    if ICON_FILE.exists():
        return FileResponse(str(ICON_FILE), media_type="image/svg+xml")
    raise HTTPException(status_code=404)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8765"))
    uvicorn.run(app, host="0.0.0.0", port=port)
