#!/usr/bin/env python3
"""
Sarah's Thrift Feed - ShopGoodwill TikTok-style backend

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

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

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
FALLBACK_IMAGE_BASE = "https://shopgoodwillimages.azureedge.net/AuctionImages"

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


app = FastAPI(title="Sarah's Thrift Feed")
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
    "imageURLs", "imageUrls", "imageURLString", "imageUrlString",
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


def _extract_gallery(detail: Any, image_server_default: str = "") -> List[str]:
    """Walk a ShopGoodwill item-detail payload and pull out every image URL.

    The shape varies; we treat any field whose name contains "image" or whose
    value looks like an image filename as a candidate. Order is preserved
    (the main hero shot tends to come first) and duplicates are dropped.
    """
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
        if url in seen:
            return
        seen.add(url)
        out.append(url)

    for key in _IMAGE_SCALAR_KEYS:
        if key in detail:
            push(detail.get(key))

    for key in _IMAGE_LIST_KEYS:
        items = detail.get(key)
        if isinstance(items, str) and items:
            for piece in items.split(","):
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
    images = _extract_gallery(detail)
    title = (detail.get("title") or detail.get("itemTitle") or "").strip() if isinstance(detail, dict) else ""
    return {"id": item_id, "title": title, "images": images}


@app.get("/api/item/{item_id}/raw")
def get_item_raw(item_id: int):
    """Diagnostic: return the upstream item detail payload as-is."""
    return _fetch_item_detail(item_id)


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
