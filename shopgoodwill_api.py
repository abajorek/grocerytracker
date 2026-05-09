#!/usr/bin/env python3
"""
Sarah's Thrift Feed - ShopGoodwill TikTok-style backend

Wraps ShopGoodwill's public ItemListing search endpoint, normalizes the
response into something the swipe feed can render, and persists pinned
brands + saved listings to a local JSON file. Serves the static frontend
from the same origin so the browser doesn't need CORS gymnastics.

Run:
    pip install -r requirements.txt
    python shopgoodwill_api.py
    open http://127.0.0.1:8765

If the public endpoint rejects anonymous traffic, set SHOPGOODWILL_TOKEN
in the env to a JWT lifted from a logged-in browser session.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

try:
    from zoneinfo import ZoneInfo
    _PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - zoneinfo always available on 3.9+
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


app = FastAPI(title="Sarah's Thrift Feed")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


def _search_shopgoodwill(query: str, page: int = 1, page_size: int = 40) -> List[dict]:
    payload = {
        "isSize": False,
        "isWeddingCatagory": "false",
        "isMultipleCategoryIds": False,
        "isFromHeaderMenuTab": False,
        "layout": "",
        "searchText": query,
        "selectedCategoryIds": "",
        "selectedGroup": "",
        "selectedSellerIds": "",
        "sortColumn": "1",
        "sortDirection": "asc",
        "page": int(page),
        "pageSize": int(page_size),
        "savedSearchId": 0,
        "highBidRange": "",
        "lowBidRange": "",
        "highPrice": "999999",
        "lowPrice": "0",
        "categoryName": "",
        "categoryId": 0,
        "categoryLevel": 0,
        "categoryLevelNo": "1",
        "isMultipleSearch": False,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://shopgoodwill.com",
        "Referer": "https://shopgoodwill.com/",
    }
    token = os.environ.get("SHOPGOODWILL_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = requests.post(
            f"{SHOPGOODWILL_BASE}/Search/ItemListing",
            json=payload,
            headers=headers,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"ShopGoodwill upstream error: {exc}")

    if isinstance(data, dict):
        if "searchResults" in data and isinstance(data["searchResults"], dict):
            return data["searchResults"].get("items", []) or []
        return data.get("items", []) or []
    return []


@app.get("/api/brands")
def get_brands():
    return _read_json(BRANDS_FILE, DEFAULT_BRANDS)


@app.post("/api/brands")
def set_brands(brands: List[str]):
    cleaned = [b.strip() for b in brands if b and b.strip()]
    _write_json(BRANDS_FILE, cleaned)
    return cleaned


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


@app.get("/api/favorites")
def list_favorites():
    return _read_json(FAVORITES_FILE, [])


@app.post("/api/favorites")
def add_favorite(fav: Favorite):
    favs = _read_json(FAVORITES_FILE, [])
    if not any(f.get("item_id") == fav.item_id for f in favs):
        favs.append(fav.model_dump())
        _write_json(FAVORITES_FILE, favs)
    return favs


@app.delete("/api/favorites/{item_id}")
def remove_favorite(item_id: int):
    favs = _read_json(FAVORITES_FILE, [])
    remaining = [f for f in favs if f.get("item_id") != item_id]
    _write_json(FAVORITES_FILE, remaining)
    return remaining


@app.get("/")
def serve_frontend():
    if FRONTEND_FILE.exists():
        return FileResponse(str(FRONTEND_FILE))
    raise HTTPException(status_code=404, detail="shopgoodwill_feed.html not found")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)
