#!/usr/bin/env python3
"""
Goodwill Hunting - ShopGoodwill TikTok-style backend.

Highlights:
  * /api/login + /api/logout + /api/auth/status: in-app ShopGoodwill
    login that stores the returned JWT in Supabase. Replaces the
    SHOPGOODWILL_TOKEN env-var dance for the common case; the env var
    is still honored as a fallback when no session token is stored.
  * /api/snipes (schedule) + /api/snipe/tick (cron-driven worker).
  * /api/retail (Claude vision retail-price lookup).
  * /api/picks (saved-search seed; UI is paused).

Deploy notes:
  * Render free tier sleeps after 15 min idle. Set up cron-job.org
    pinging /api/snipe/tick?key=$SNIPE_TICK_SECRET every 60s.
  * For first-time setup either add SHOPGOODWILL_TOKEN env var, or
    just hit the Sign-in chip in the app and provide username/password.
"""

import html as html_module
import json
import os
import re
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from zoneinfo import ZoneInfo
    _PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover
    _PACIFIC = timezone.utc

import requests
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel


SHOPGOODWILL_BASE = "https://buyerapi.shopgoodwill.com/api"
FALLBACK_IMAGE_BASE = "https://shopgoodwillimages.azureedge.net/production/"

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
FAVORITES_FILE = DATA_DIR / "favorites.json"
BRANDS_FILE = DATA_DIR / "brands.json"
PICKS_FILE = DATA_DIR / "picks.json"
SNIPES_FILE = DATA_DIR / "snipes.json"
AUTH_FILE = DATA_DIR / "auth.json"
FRONTEND_FILE = ROOT / "shopgoodwill_feed.html"
PICKS_JS_FILE = ROOT / "picks.js"
SNIPE_JS_FILE = ROOT / "snipe.js"
AUTH_JS_FILE = ROOT / "auth.js"
MANIFEST_FILE = ROOT / "manifest.webmanifest"
ICON_FILE = ROOT / "icon.svg"

DEFAULT_BRANDS = [
    "Coach", "Madewell", "Free People", "Anthropologie",
    "Patagonia", "J.Crew", "Eileen Fisher", "Lululemon",
]

DEFAULT_PICKS: List[Dict[str, Any]] = [
    {"name": "Merz Navy Henley", "query": "merz henley", "price_max": 70, "size_hints": ["XL", "X-Large"]},
    {"name": "Brycelands", "query": "brycelands", "size_hints": ["36", "38"]},
    {"name": "No Ordinary Joe", "query": "no ordinary joe", "size_hints": ["XL", "X-Large", "44", "45", "46"]},
    {"name": "Private White VC", "query": "private white", "size_hints": ["XL", "X-Large", "36", "37", "38"]},
    {"name": "Páramo", "query": "paramo", "size_hints": ["XL", "X-Large"]},
    {"name": "Mackintosh", "query": "mackintosh", "price_max": 200, "size_hints": ["L", "XL", "Large", "X-Large"]},
    {"name": "John Smedley", "query": "john smedley", "price_max": 100, "size_hints": ["L", "XL", "Large", "X-Large"]},
    {"name": "Montane Minimus", "query": "montane minimus", "price_max": 100, "size_hints": ["XL", "X-Large"]},
    {"name": "Arc'teryx Squamish", "query": "arcteryx squamish", "price_max": 100, "size_hints": ["XL", "X-Large"]},
    {"name": "Rab Demand", "query": "rab demand", "price_max": 100, "size_hints": ["XL", "X-Large"]},
    {"name": "Roeckl Gloves", "query": "roeckl", "price_max": 100, "size_hints": ["XL", "X-Large"]},
    {"name": "Devold Expedition", "query": "devold expedition", "price_max": 100, "size_hints": ["XL", "X-Large"]},
    {"name": "Rab Microlight", "query": "rab microlight", "price_max": 100, "size_hints": ["XL", "X-Large"]},
    {"name": "Rab Neutrino", "query": "rab neutrino", "price_max": 100, "size_hints": ["XL", "X-Large"]},
    {"name": "Montbell Down", "query": "montbell down", "price_max": 100, "size_hints": ["XL", "X-Large"]},
    {"name": "Montbell Mirage", "query": "montbell mirage", "price_max": 100, "size_hints": ["XL", "X-Large"]},
    {"name": "Nanga Aurora", "query": "nanga aurora"},
    {"name": "Outlier", "query": "outlier", "size_hints": ["12"]},
    {"name": "Western Rise", "query": "western rise", "size_hints": ["12"]},
    {"name": "Dale of Norway", "query": "dale of norway", "size_hints": ["12"]},
    {"name": "Devold", "query": "devold", "size_hints": ["12"]},
    {"name": "Amundsen", "query": "amundsen", "size_hints": ["12"]},
    {"name": "Meindl", "query": "meindl", "size_hints": ["12"]},
    {"name": "Hanwag", "query": "hanwag", "size_hints": ["12"]},
    {"name": "Berghaus", "query": "berghaus", "size_hints": ["L", "XL", "Large", "X-Large", "36", "37", "38"]},
    {"name": "Rab", "query": "rab", "size_hints": ["L", "XL", "Large", "X-Large", "36", "37", "38"]},
    {"name": "Montane", "query": "montane", "size_hints": ["L", "XL", "Large", "X-Large", "36", "37", "38"]},
    {"name": "Veilance", "query": "veilance", "price_max": 100, "size_hints": ["L", "XL", "Large", "X-Large", "36", "37", "38"]},
    {"name": "66° North", "query": "66 degrees north", "price_max": 50, "size_hints": ["L", "XL", "Large", "X-Large"]},
    {"name": "C.P. Company", "query": "cp company", "price_max": 50, "size_hints": ["L", "XL", "Large", "X-Large", "36", "37", "38"]},
    {"name": "Fjällräven Vidda Pro", "query": "fjallraven vidda", "price_max": 70, "size_hints": ["36", "38"]},
    {"name": "Fjällräven Keb Trousers", "query": "fjallraven keb", "price_max": 80, "size_hints": ["36", "37", "38"]},
    {"name": "Icebreaker Waypoint", "query": "icebreaker waypoint", "size_hints": ["L", "XL", "Large", "X-Large"]},
    {"name": "Orvis Moleskin", "query": "orvis moleskin", "price_max": 1000, "size_hints": ["L", "XL", "Large", "X-Large", "36", "37", "38"]},
    {"name": "Orvis Chamois", "query": "orvis chamois", "price_max": 1000, "size_hints": ["L", "XL", "Large", "X-Large", "36", "37", "38"]},
    {"name": "SealSkinz", "query": "sealskinz"},
    {"name": "Prana Stretch Zion Zip", "query": "stretch zion zip", "size_hints": ["L", "Large", "36", "37"]},
    {"name": "Prana Stretch Zion Convertible", "query": "stretch zion convertible", "size_hints": ["36", "37"]},
    {"name": "Patagonia Quandary", "query": "patagonia quandary", "size_hints": ["36", "38"]},
    {"name": "Lundhags", "query": "lundhags", "size_hints": ["L", "XL", "Large", "X-Large", "36", "37", "38"]},
    {"name": "Faherty Legend", "query": "faherty legend", "price_max": 50, "size_hints": ["XL", "X-Large"]},
    {"name": "Klättermusen", "query": "klattermusen", "price_max": 50, "size_hints": ["L", "XL", "Large", "X-Large", "36", "37", "38"]},
    {"name": "Fjällräven", "query": "fjallraven", "size_hints": ["54", "55", "56", "57"]},
    {"name": "Melanzana", "query": "melanzana", "price_max": 50, "size_hints": ["L", "XL", "Large", "X-Large"]},
    {"name": "Himali", "query": "himali", "price_max": 50, "size_hints": ["L", "XL", "Large", "X-Large", "12"]},
    {"name": "Barbour Jacket", "query": "barbour", "price_max": 50, "size_hints": ["XL", "X-Large"]},
    {"name": "Ted Baker", "query": "ted baker", "size_hints": ["46"]},
    {"name": "Profumo", "query": "profumo", "price_max": 50, "size_hints": ["L", "XL", "Large", "X-Large", "36", "37"]},
    {"name": "Fat Face", "query": "fat face", "price_max": 50, "size_hints": ["XL", "X-Large"]},
    {"name": "Hoka Anacapa 2 Low GTX", "query": "hoka anacapa", "price_max": 50, "size_hints": ["12"]},
    {"name": "Fjällräven Övik", "query": "fjallraven ovik", "price_max": 50, "size_hints": ["XL", "X-Large"]},
    {"name": "Norrøna", "query": "norrona", "price_max": 50, "size_hints": ["36", "37", "38", "12"]},
    {"name": "Samsøe", "query": "samsoe", "price_max": 50, "size_hints": ["36", "37", "38", "12"]},
]

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or ""

ANTHROPIC_API_KEY = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001").strip()

SNIPE_TICK_SECRET = (os.environ.get("SNIPE_TICK_SECRET") or "").strip()

SORT_OPTIONS: Dict[str, tuple] = {
    "ending_soon":  ("1", "false"),
    "newly_listed": ("4", "true"),
    "price_low":    ("3", "false"),
    "price_high":   ("3", "true"),
    "most_bids":    ("2", "true"),
}

_PICKS_CACHE: Dict[str, Dict[str, Any]] = {}
_PICKS_TTL = 300

_FRAME_INJECTION = (
    "<script>(function(){try{"
    "window.state=state;"
    "window.apiGet=apiGet;"
    "window.apiSend=apiSend;"
    "window.renderError=renderError;"
    "window.setBidNotice=setBidNotice;"
    "window.openBidSheet=openBidSheet;"
    "window.fmtPrice=fmtPrice;"
    "window.renderBrandBar=renderBrandBar;"
    "}catch(e){}})()</script>"
    "<script src=\"/picks.js?v=4\"></script>"
    "<script src=\"/snipe.js?v=1\"></script>"
    "<script src=\"/auth.js?v=1\"></script>"
)


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
    is_closed: bool = False


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


class SnipeRequest(BaseModel):
    item_id: int
    amount: float
    end_time: str
    lead_seconds: int = 8
    title: Optional[str] = ""
    image_url: Optional[str] = ""


class LoginRequest(BaseModel):
    username: str
    password: str
    remember: bool = True


app = FastAPI(title="Goodwill Hunting")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
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


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _normalize_item(raw: dict, brand_query: str) -> Optional[FeedItem]:
    item_id = raw.get("itemId") or raw.get("id") or 0
    if not item_id:
        return None
    image_path = (
        raw.get("imageURL") or raw.get("imageUrlString") or raw.get("image") or ""
    )
    if isinstance(image_path, str) and ";" in image_path:
        image_path = image_path.split(";", 1)[0]
    image_url = _build_image_url(raw.get("imageServer", "") or "", image_path)
    if not image_url:
        return None
    end_time = raw.get("endTime") or raw.get("endDate") or ""
    seconds = _seconds_until(end_time)
    final_price = raw.get("finalPrice") or raw.get("closingPrice")
    is_closed = bool(
        raw.get("isClosed") or raw.get("closed") or final_price is not None
        or (end_time and seconds == 0)
    )
    current = raw.get("currentPrice")
    if current is None and final_price is not None:
        current = final_price
    return FeedItem(
        id=int(item_id),
        title=str(raw.get("title", "") or "").strip(),
        image_url=image_url,
        images=[image_url],
        current_price=float(current or 0),
        minimum_bid=float(raw.get("minimumBid", 0) or 0),
        bid_count=int(raw.get("bidCount", 0) or 0),
        end_time=end_time,
        seconds_left=seconds,
        listing_url=f"https://shopgoodwill.com/item/{item_id}",
        brand=brand_query,
        location=raw.get("sellerName") or raw.get("location"),
        is_closed=is_closed,
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


# ---------- auth (ShopGoodwill JWT, stored in Supabase) ----------

_AUTH_LOCK = threading.Lock()


def _supabase_enabled():
    return bool(SUPABASE_URL and SUPABASE_KEY)


def _supabase(method, path, *, body=None, params=None, prefer=None):
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    try:
        resp = requests.request(method, f"{SUPABASE_URL}/rest/v1/{path}",
                                headers=headers, params=params, json=body, timeout=15)
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


def _read_session_auth() -> Optional[dict]:
    """Stored session credentials (token + username) from Supabase or local
    JSON fallback. Returns dict like {token, username, saved_at} or None."""
    if _supabase_enabled():
        try:
            rows = _supabase("GET", "thrift_settings",
                             params={"key": "eq.shopgoodwill_auth", "select": "value"})
        except HTTPException:
            return None
        if rows and rows[0].get("value"):
            value = rows[0]["value"]
            if isinstance(value, dict) and value.get("token"):
                return value
        return None
    cached = _read_json(AUTH_FILE, None)
    if isinstance(cached, dict) and cached.get("token"):
        return cached
    return None


def _save_session_auth(token: str, username: str) -> dict:
    payload = {
        "token": token,
        "username": username,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    with _AUTH_LOCK:
        if _supabase_enabled():
            _supabase("POST", "thrift_settings",
                      body={"key": "shopgoodwill_auth", "value": payload},
                      prefer="return=minimal,resolution=merge-duplicates")
        else:
            _write_json(AUTH_FILE, payload)
    return payload


def _clear_session_auth():
    with _AUTH_LOCK:
        if _supabase_enabled():
            try:
                _supabase("DELETE", "thrift_settings",
                          params={"key": "eq.shopgoodwill_auth"})
            except HTTPException:
                pass
        elif AUTH_FILE.exists():
            try:
                AUTH_FILE.unlink()
            except Exception:
                pass


def _get_active_token() -> str:
    """Active ShopGoodwill JWT — Supabase session first, env-var fallback."""
    sess = _read_session_auth()
    if sess and sess.get("token"):
        return str(sess["token"]).strip()
    return (os.environ.get("SHOPGOODWILL_TOKEN") or "").strip()


def _shopgoodwill_login(username: str, password: str, remember: bool = True) -> dict:
    """Call ShopGoodwill's auth endpoint and return the parsed response."""
    payload = {
        "username": username,
        "password": password,
        "remember": bool(remember),
        "clientIpAddress": "0.0.0.0",
        "browser": DEFAULT_HEADERS["User-Agent"],
        "appVersion": "Goodwill-Hunting/1.0",
    }
    headers = dict(DEFAULT_HEADERS)
    try:
        resp = requests.post(f"{SHOPGOODWILL_BASE}/SignIn/Login",
                             json=payload, headers=headers, timeout=15)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502,
                            detail=f"ShopGoodwill network error: {exc}")
    if resp.status_code in (400, 401, 403):
        try:
            data = resp.json()
            msg = (data.get("message") or data.get("error")
                   or data.get("title") or "").strip()
        except ValueError:
            msg = ""
        if not msg:
            msg = (
                "ShopGoodwill rejected the login. Double-check the email and "
                "password — note that ShopGoodwill is case-sensitive on email."
            )
        raise HTTPException(status_code=401, detail=msg)
    if not resp.ok:
        body = (resp.text or "")[:300].replace("\n", " ")
        raise HTTPException(status_code=502,
                            detail=f"ShopGoodwill returned {resp.status_code}: {body}")
    try:
        return resp.json()
    except ValueError:
        raise HTTPException(status_code=502,
                            detail="Login response was not JSON.")


def _extract_token_from_login(data: dict) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    for key in ("accessToken", "access_token", "token", "authToken", "jwt"):
        v = data.get(key)
        if isinstance(v, str) and v.startswith("eyJ"):
            return v
    inner = data.get("data")
    if isinstance(inner, dict):
        return _extract_token_from_login(inner)
    return None


# ---------- shopgoodwill core ----------

def _build_search_payload(*, query, page, page_size, sort="ending_soon",
                          price_min=0, price_max=0, buy_now_only=False,
                          no_pickup=False, include_closed=False, closed_days_back=7):
    sort_col, sort_desc = SORT_OPTIONS.get(sort, SORT_OPTIONS["ending_soon"])
    high = price_max if price_max and price_max > 0 else 999999
    low = price_min if price_min and price_min >= 0 else 0
    return {
        "isSize": False, "isWeddingCatagory": "false",
        "isMultipleCategoryIds": False, "isFromHeaderMenuTab": False,
        "layout": "", "searchText": (query or "").replace('"', ""),
        "selectedGroup": "", "selectedCategoryIds": "", "selectedSellerIds": "",
        "lowPrice": str(low), "highPrice": str(high),
        "searchBuyNowOnly": "true" if buy_now_only else "",
        "searchPickupOnly": "false",
        "searchNoPickupOnly": "true" if no_pickup else "false",
        "searchOneCentShippingOnly": "false", "searchDescriptions": "false",
        "searchClosedAuctions": "true" if include_closed else "false",
        "closedAuctionEndingDate": "1/1/0001",
        "closedAuctionDaysBack": str(int(closed_days_back) if include_closed else 7),
        "searchCanadaShipping": "false", "searchInternationalShippingOnly": "false",
        "sortColumn": sort_col, "sortDescending": sort_desc,
        "savedSearchId": 0, "useBuyerPrefs": "true",
        "searchUSOnlyShipping": "false",
        "categoryLevelNo": "1", "categoryLevel": 1, "categoryId": 0,
        "partNumber": "", "catIds": "",
        "page": int(page), "pageSize": int(page_size),
    }


def _shopgoodwill_request(*, query, page, page_size, **filters):
    headers = dict(DEFAULT_HEADERS)
    token = _get_active_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = _build_search_payload(query=query, page=page, page_size=page_size, **filters)
    return requests.post(
        f"{SHOPGOODWILL_BASE}/Search/ItemListing",
        json=payload, headers=headers, timeout=20,
    )


def _search_shopgoodwill(query, page=1, page_size=40, **filters):
    try:
        resp = _shopgoodwill_request(query=query, page=page, page_size=page_size, **filters)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"ShopGoodwill network error: {exc}")
    if not resp.ok:
        body = (resp.text or "")[:240].replace("\n", " ")
        raise HTTPException(status_code=502, detail=f"ShopGoodwill returned {resp.status_code}: {body}")
    try:
        data = resp.json()
    except ValueError:
        snippet = (resp.text or "")[:240].replace("\n", " ")
        raise HTTPException(status_code=502, detail=f"ShopGoodwill returned non-JSON ({resp.status_code}): {snippet}")
    if isinstance(data, dict):
        if "searchResults" in data and isinstance(data["searchResults"], dict):
            return data["searchResults"].get("items", []) or []
        return data.get("items", []) or []
    return []


def _place_bid(item_id, amount, quantity=1):
    token = _get_active_token()
    if not token:
        raise HTTPException(status_code=401, detail=(
            "Not signed in to ShopGoodwill. Tap the Sign in chip in the app, "
            "or set SHOPGOODWILL_TOKEN in Render → Environment."
        ))
    headers = dict(DEFAULT_HEADERS)
    headers["Authorization"] = f"Bearer {token}"
    payload = {"itemId": int(item_id), "bidAmount": f"{float(amount):.2f}", "quantity": int(quantity)}
    try:
        resp = requests.post(f"{SHOPGOODWILL_BASE}/ItemBid/PlaceBid",
                             json=payload, headers=headers, timeout=20)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"ShopGoodwill network error: {exc}")
    if resp.status_code in (401, 403):
        # Token is bad — clear the stored session so the user is prompted to re-login.
        _clear_session_auth()
        raise HTTPException(status_code=401, detail=(
            "ShopGoodwill rejected the session (likely expired). Tap Sign in "
            "and re-enter credentials."
        ))
    if not resp.ok:
        body = (resp.text or "")[:300].replace("\n", " ")
        raise HTTPException(status_code=502, detail=f"ShopGoodwill returned {resp.status_code}: {body}")
    try:
        return resp.json()
    except ValueError:
        return {"raw": (resp.text or "")[:300]}


_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_IMAGE_LIST_KEYS = (
    "imageUrlString", "imageURLString", "imageURLs", "imageUrls",
    "images", "itemImages", "additionalImages", "imageList", "galleryImages",
    "itemImageUrls", "itemImageURLs",
)
_IMAGE_SCALAR_KEYS = (
    "imageURL", "imageUrl", "imageName", "image",
    "largeImageURL", "largeImageUrl", "primaryImage",
)


def _looks_like_image_path(value):
    if not isinstance(value, str) or not value:
        return False
    lower = value.lower().split("?", 1)[0]
    return lower.endswith(_IMAGE_SUFFIXES)


def _split_image_string(value):
    if not value:
        return []
    pieces = value.replace(",", ";").split(";")
    return [p for p in (s.strip() for s in pieces) if p]


def _extract_gallery(detail, image_server_default=""):
    if not isinstance(detail, dict):
        return []
    image_server = (
        detail.get("imageServer") or detail.get("imageServerLocation")
        or image_server_default or FALLBACK_IMAGE_BASE
    )
    seen, out = set(), []
    def push(raw):
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


_BLOCK_TAGS_RE = re.compile(r'<\s*(br|/p|/li|/div|/h[1-6]|/tr|/table)\s*/?\s*>', re.IGNORECASE)
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


def _strip_html(value):
    if not value:
        return ""
    text = _BLOCK_TAGS_RE.sub("\n", value)
    text = _TAGS_RE.sub(" ", text)
    text = html_module.unescape(text)
    text = text.replace(" ", " ").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text


def _extract_notes(html_description):
    text = _strip_html(html_description)
    out, seen = [], set()
    for raw_line in re.split(r'[\n\r]+', text):
        line = raw_line.strip(" \t-•* ")
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


_DETAIL_CACHE: Dict[int, Dict[str, Any]] = {}
_DETAIL_TTL = 1800


def _fetch_item_detail(item_id):
    cached = _DETAIL_CACHE.get(item_id)
    if cached and time.time() - cached["t"] < _DETAIL_TTL:
        return cached["v"]
    headers = dict(DEFAULT_HEADERS)
    token = _get_active_token()
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
        raise HTTPException(status_code=502, detail=f"ShopGoodwill returned {resp.status_code}: {body}")
    try:
        data = resp.json()
    except ValueError:
        snippet = (resp.text or "")[:240].replace("\n", " ")
        raise HTTPException(status_code=502, detail=f"non-JSON ({resp.status_code}): {snippet}")
    _DETAIL_CACHE[item_id] = {"v": data, "t": time.time()}
    if len(_DETAIL_CACHE) > 200:
        for k in list(_DETAIL_CACHE.keys())[:50]:
            _DETAIL_CACHE.pop(k, None)
    return data


_RETAIL_CACHE: Dict[int, Dict[str, Any]] = {}
_RETAIL_TTL = 86400
_RETAIL_PROMPT = (
    "You are identifying a thrift-store auction listing. Use BOTH the photo "
    "and the title together to identify the *specific* product (e.g. not "
    "\"Coach handbag\" but \"Coach Signature Canvas Stripe Tote\"). Then "
    "estimate the original RETAIL price someone would pay to buy this same "
    "item NEW from the brand or a similar new retailer today.\n\n"
    "Title: {title}\n"
    "{brand_line}"
    "\n"
    "Reply with JSON only, no other text:\n"
    "{{\n"
    "  \"product\": \"specific product name\",\n"
    "  \"retail_low\": <integer dollars>,\n"
    "  \"retail_high\": <integer dollars>,\n"
    "  \"confidence\": \"high\" | \"medium\" | \"low\",\n"
    "  \"note\": \"one short sentence about how confident and why\"\n"
    "}}\n\n"
    "If you cannot identify the specific item confidently, set confidence to "
    "\"low\" and use a wider price range based on what is visible in the photo."
)


def _parse_retail_json(text):
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    obj = None
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        m = re.search(r"\{[\s\S]+\}", text)
        if m:
            try:
                obj = json.loads(m.group(0))
            except (ValueError, TypeError):
                obj = None
    if not isinstance(obj, dict):
        return None
    out: Dict[str, Any] = {}
    if obj.get("product"):
        out["product"] = str(obj["product"])[:120]
    for k in ("retail_low", "retail_high"):
        v = obj.get(k)
        try:
            out[k] = float(v) if v is not None else None
        except (ValueError, TypeError):
            out[k] = None
    conf = str(obj.get("confidence", "")).lower()
    out["confidence"] = conf if conf in ("high", "medium", "low") else "low"
    if obj.get("note"):
        out["note"] = str(obj["note"])[:240]
    return out


def _retail_estimate(item_id, title, brand, image_url):
    if not ANTHROPIC_API_KEY:
        return {"ok": False, "reason": "ANTHROPIC_API_KEY is not set on the server. Add it in Render → Environment to enable retail-price lookup."}
    cached = _RETAIL_CACHE.get(item_id)
    if cached and time.time() - cached["t"] < _RETAIL_TTL:
        return cached["v"]
    if not image_url or not image_url.startswith("http"):
        return {"ok": False, "reason": "no image URL available for this item"}
    brand_line = f"Brand: {brand}\n" if brand else ""
    prompt = _RETAIL_PROMPT.format(title=(title or "(no title)")[:200], brand_line=brand_line)
    body = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 400,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "url", "url": image_url}},
                {"type": "text", "text": prompt},
            ],
        }],
    }
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body, timeout=25,
        )
    except requests.RequestException as exc:
        return {"ok": False, "reason": f"network: {exc}"}
    if not resp.ok:
        snippet = (resp.text or "")[:240].replace("\n", " ")
        return {"ok": False, "reason": f"Anthropic API {resp.status_code}: {snippet}"}
    try:
        data = resp.json()
    except ValueError:
        return {"ok": False, "reason": "non-JSON response from Anthropic"}
    text_parts = []
    for block in data.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(block.get("text", ""))
    raw_text = "".join(text_parts).strip()
    parsed = _parse_retail_json(raw_text)
    if not parsed:
        return {"ok": False, "reason": "couldn't parse retail JSON from model", "raw": raw_text[:240]}
    result = {"ok": True, "model": ANTHROPIC_MODEL, **parsed}
    _RETAIL_CACHE[item_id] = {"v": result, "t": time.time()}
    if len(_RETAIL_CACHE) > 500:
        for k in list(_RETAIL_CACHE.keys())[:100]:
            _RETAIL_CACHE.pop(k, None)
    return result


def store_get_brands():
    if _supabase_enabled():
        rows = _supabase("GET", "thrift_settings", params={"key": "eq.brands", "select": "value"})
        if rows and rows[0].get("value"):
            value = rows[0]["value"]
            if isinstance(value, list):
                return value
        return list(DEFAULT_BRANDS)
    return _read_json(BRANDS_FILE, list(DEFAULT_BRANDS))


def store_set_brands(brands):
    cleaned = [b.strip() for b in brands if b and b.strip()]
    if _supabase_enabled():
        _supabase("POST", "thrift_settings",
                  body={"key": "brands", "value": cleaned},
                  prefer="return=minimal,resolution=merge-duplicates")
        return cleaned
    _write_json(BRANDS_FILE, cleaned)
    return cleaned


def store_list_favorites():
    if _supabase_enabled():
        return _supabase("GET", "thrift_favorites",
                         params={"select": "*", "order": "saved_at.desc"})
    return _read_json(FAVORITES_FILE, [])


def store_add_favorite(fav):
    payload = {
        "item_id": fav.item_id, "title": fav.title,
        "image_url": fav.image_url, "listing_url": fav.listing_url,
        "brand": fav.brand or "", "saved_at": fav.saved_at,
    }
    if _supabase_enabled():
        _supabase("POST", "thrift_favorites", body=payload,
                  prefer="return=minimal,resolution=merge-duplicates")
        return store_list_favorites()
    favs = _read_json(FAVORITES_FILE, [])
    if not any(f.get("item_id") == fav.item_id for f in favs):
        favs.append(payload)
        _write_json(FAVORITES_FILE, favs)
    return favs


def store_remove_favorite(item_id):
    if _supabase_enabled():
        _supabase("DELETE", "thrift_favorites", params={"item_id": f"eq.{item_id}"})
        return store_list_favorites()
    favs = _read_json(FAVORITES_FILE, [])
    remaining = [f for f in favs if f.get("item_id") != item_id]
    _write_json(FAVORITES_FILE, remaining)
    return remaining


# ---------- picks ----------

_SIZE_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-/]*")
_WORD_TOKEN_RE = re.compile(r"[a-z]{2,}")
_QUERY_STOPWORDS = {
    "the", "and", "for", "men", "mens", "women", "womens", "with",
    "size", "sized", "small", "medium", "large",
    "jacket", "coat", "shirt", "pants", "trousers", "sweater",
    "henley", "down", "vest", "shorts", "bag", "gloves", "boots", "shoes",
    "company", "vc", "co",
}


def _strip_diacritics(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def _match_size_hints(title, hints):
    if not hints:
        return True
    title_lower = _strip_diacritics(title or "").lower()
    if not title_lower:
        return False
    tokens = set(_SIZE_TOKEN_RE.findall(title_lower))
    for h in hints:
        h_low = _strip_diacritics(str(h or "")).lower().strip()
        if not h_low:
            continue
        if h_low in tokens:
            return True
    return False


def _pick_query_matches_title(query: str, title: str) -> bool:
    if not query:
        return True
    title_norm = _strip_diacritics(title or "").lower()
    query_norm = _strip_diacritics(query).lower()
    title_tokens_all = _WORD_TOKEN_RE.findall(title_norm)
    title_token_set = set(title_tokens_all)
    query_words = [w for w in _WORD_TOKEN_RE.findall(query_norm) if len(w) >= 3]
    if not query_words:
        return True
    if not all(w in title_token_set for w in query_words):
        return False
    brand_word = next((w for w in query_words if w not in _QUERY_STOPWORDS), query_words[0])
    return brand_word in title_tokens_all[:6]


def store_get_picks() -> List[dict]:
    if _supabase_enabled():
        rows = _supabase("GET", "thrift_settings", params={"key": "eq.picks", "select": "value"})
        if rows and rows[0].get("value"):
            value = rows[0]["value"]
            if isinstance(value, list):
                return value
    if PICKS_FILE.exists():
        cached = _read_json(PICKS_FILE, None)
        if isinstance(cached, list):
            return cached
    return list(DEFAULT_PICKS)


def store_set_picks(picks):
    cleaned = []
    for p in picks or []:
        if not isinstance(p, dict):
            continue
        q = (p.get("query") or "").strip()
        if not q:
            continue
        entry = {"name": (p.get("name") or q).strip(), "query": q}
        pm = p.get("price_max")
        try:
            pm = float(pm) if pm is not None else 0
        except (ValueError, TypeError):
            pm = 0
        if pm > 0:
            entry["price_max"] = pm
        hints = p.get("size_hints") or []
        if isinstance(hints, list):
            entry["size_hints"] = [str(h).strip() for h in hints if str(h).strip()]
        cleaned.append(entry)
    if _supabase_enabled():
        _supabase("POST", "thrift_settings",
                  body={"key": "picks", "value": cleaned},
                  prefer="return=minimal,resolution=merge-duplicates")
    else:
        _write_json(PICKS_FILE, cleaned)
    return cleaned


def _search_one_pick(pick):
    cache_key = json.dumps(pick, sort_keys=True)
    cached = _PICKS_CACHE.get(cache_key)
    if cached and time.time() - cached["t"] < _PICKS_TTL:
        return cached["v"]
    label = (pick.get("name") or pick.get("query") or "Pick").strip()
    query = (pick.get("query") or "").strip()
    if not query:
        _PICKS_CACHE[cache_key] = {"v": [], "t": time.time()}
        return []
    try:
        raw_items = _search_shopgoodwill(
            query, page=1, page_size=24,
            price_max=float(pick.get("price_max") or 0),
            no_pickup=True,
        )
    except (HTTPException, Exception):
        return []
    hints = pick.get("size_hints") or []
    items = []
    for raw in raw_items:
        try:
            normalized = _normalize_item(raw, label)
        except Exception:
            continue
        if normalized is None:
            continue
        if not _pick_query_matches_title(query, normalized.title):
            continue
        if hints and not _match_size_hints(normalized.title, hints):
            continue
        items.append(normalized)
    _PICKS_CACHE[cache_key] = {"v": items, "t": time.time()}
    if len(_PICKS_CACHE) > 200:
        for k in list(_PICKS_CACHE.keys())[:50]:
            _PICKS_CACHE.pop(k, None)
    return items


# ---------- snipes ----------

_SNIPE_LOCK = threading.Lock()


def _load_snipes() -> List[dict]:
    if _supabase_enabled():
        rows = _supabase("GET", "thrift_settings", params={"key": "eq.snipes", "select": "value"})
        if rows and rows[0].get("value"):
            value = rows[0]["value"]
            if isinstance(value, list):
                return value
        return []
    return _read_json(SNIPES_FILE, [])


def _save_snipes(snipes: List[dict]):
    if _supabase_enabled():
        _supabase("POST", "thrift_settings",
                  body={"key": "snipes", "value": snipes},
                  prefer="return=minimal,resolution=merge-duplicates")
    else:
        _write_json(SNIPES_FILE, snipes)


def _patch_snipe(snipe_id: str, **fields) -> Optional[dict]:
    with _SNIPE_LOCK:
        snipes = _load_snipes()
        for s in snipes:
            if s.get("id") == snipe_id:
                s.update(fields)
                _save_snipes(snipes)
                return dict(s)
    return None


def _prune_snipes(snipes: List[dict]) -> List[dict]:
    terminal = {"fired", "failed", "cancelled"}
    live, done = [], []
    for s in snipes:
        (done if s.get("status") in terminal else live).append(s)
    done.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return live + done[:50]


def _check_snipe_key(key: str) -> bool:
    if not SNIPE_TICK_SECRET:
        return False
    return (key or "").strip() == SNIPE_TICK_SECRET


def _execute_snipe(snipe_id: str):
    snipes = _load_snipes()
    snipe = next((s for s in snipes if s.get("id") == snipe_id), None)
    if not snipe:
        return
    try:
        fire_at = _parse_iso(snipe["fire_at"])
        delta = (fire_at - datetime.now(timezone.utc)).total_seconds()
        if delta > 0:
            time.sleep(min(delta, 300))
        result = _place_bid(int(snipe["item_id"]), float(snipe["amount"]), 1)
        _patch_snipe(
            snipe_id, status="fired",
            fired_at=datetime.now(timezone.utc).isoformat(),
            result=json.dumps(result)[:400],
        )
    except HTTPException as exc:
        _patch_snipe(
            snipe_id, status="failed",
            fired_at=datetime.now(timezone.utc).isoformat(),
            result=f"{exc.status_code}: {exc.detail}"[:400],
        )
    except Exception as exc:
        _patch_snipe(
            snipe_id, status="failed",
            fired_at=datetime.now(timezone.utc).isoformat(),
            result=f"{type(exc).__name__}: {exc}"[:400],
        )


# ---------- routes ----------

@app.get("/api/feed", response_model=List[FeedItem])
def get_feed(
    brand: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=100),
    q: str = Query(""),
    sort: str = Query("ending_soon"),
    price_min: float = Query(0, ge=0),
    price_max: float = Query(0, ge=0),
    buy_now_only: bool = Query(False),
    no_pickup: bool = Query(False),
    has_bids: bool = Query(False),
    include_closed: bool = Query(False),
    closed_days_back: int = Query(7, ge=1, le=30),
):
    brand = (brand or "").strip()
    q = (q or "").strip()
    parts = [p for p in (brand, q) if p]
    if not parts:
        raise HTTPException(status_code=400, detail="Provide brand or q (search query)")
    search_text = " ".join(parts)
    raw_items = _search_shopgoodwill(
        search_text, page=page, page_size=page_size,
        sort=sort, price_min=price_min, price_max=price_max,
        buy_now_only=buy_now_only, no_pickup=no_pickup,
        include_closed=include_closed, closed_days_back=closed_days_back,
    )
    items = []
    label = brand or q
    for raw in raw_items:
        try:
            normalized = _normalize_item(raw, label)
        except Exception:
            continue
        if normalized is None:
            continue
        if has_bids and normalized.bid_count <= 0:
            continue
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
        "id": item_id, "title": title, "images": images, "notes": notes,
        "location": location, "seller": seller,
        "buy_now_price": buy_now, "shipping_price": shipping, "handling_price": handling,
    }


@app.get("/api/item/{item_id}/raw")
def get_item_raw(item_id: int):
    return _fetch_item_detail(item_id)


@app.get("/api/retail")
def api_retail(item_id: int, brand: str = ""):
    detail = _fetch_item_detail(item_id)
    title = (detail.get("title") or "").strip() if isinstance(detail, dict) else ""
    images = _extract_gallery(detail) if isinstance(detail, dict) else []
    image_url = images[0] if images else ""
    return _retail_estimate(item_id, title, brand or "", image_url)


@app.post("/api/bid")
def api_place_bid(req: BidRequest):
    return {"ok": True, "result": _place_bid(req.item_id, req.amount, req.quantity)}


# ----- auth -----

@app.get("/api/auth/status")
def auth_status():
    sess = _read_session_auth()
    if sess and sess.get("token"):
        return {
            "authenticated": True,
            "username": sess.get("username") or "",
            "source": "session",
            "saved_at": sess.get("saved_at", ""),
        }
    if (os.environ.get("SHOPGOODWILL_TOKEN") or "").strip():
        return {
            "authenticated": True,
            "username": "(env-var token)",
            "source": "env",
            "saved_at": "",
        }
    return {"authenticated": False, "username": "", "source": "none", "saved_at": ""}


@app.post("/api/login")
def api_login(req: LoginRequest):
    username = (req.username or "").strip()
    if not username or not req.password:
        raise HTTPException(status_code=400, detail="username and password required")
    data = _shopgoodwill_login(username, req.password, remember=req.remember)
    token = _extract_token_from_login(data)
    if not token:
        # Best-effort error message: surface the response keys so we can debug
        # without ever logging the password.
        keys = ", ".join(list(data.keys())[:8]) if isinstance(data, dict) else "<non-dict>"
        raise HTTPException(
            status_code=502,
            detail=f"Login succeeded but no JWT in response (keys: {keys}).",
        )
    display_name = ""
    if isinstance(data, dict):
        display_name = (
            data.get("username") or data.get("userName")
            or data.get("name") or data.get("displayName") or ""
        )
        inner = data.get("data")
        if not display_name and isinstance(inner, dict):
            display_name = (
                inner.get("username") or inner.get("userName")
                or inner.get("name") or inner.get("displayName") or ""
            )
    saved = _save_session_auth(token, str(display_name or username))
    return {"ok": True, "username": saved["username"], "source": "session"}


@app.post("/api/logout")
def api_logout():
    _clear_session_auth()
    return {"ok": True}


# ----- snipes -----

@app.post("/api/snipes")
def schedule_snipe(req: SnipeRequest):
    if req.amount <= 0:
        raise HTTPException(400, "amount must be positive")
    try:
        end_dt = _parse_iso(req.end_time)
    except Exception:
        raise HTTPException(400, f"invalid end_time: {req.end_time!r}")
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=_PACIFIC)
    end_utc = end_dt.astimezone(timezone.utc)
    lead = max(2, min(60, int(req.lead_seconds)))
    fire_at = end_utc - timedelta(seconds=lead)
    now_utc = datetime.now(timezone.utc)
    if fire_at <= now_utc + timedelta(seconds=2):
        raise HTTPException(400, "auction is too close to its end to schedule a snipe")
    snipe = {
        "id": "snipe_" + uuid.uuid4().hex[:12],
        "item_id": int(req.item_id),
        "amount": round(float(req.amount), 2),
        "fire_at": fire_at.isoformat(),
        "end_time": end_utc.isoformat(),
        "lead_seconds": lead,
        "title": (req.title or "")[:200],
        "image_url": (req.image_url or "")[:400],
        "status": "scheduled",
        "result": "",
        "created_at": now_utc.isoformat(),
        "fired_at": None,
    }
    with _SNIPE_LOCK:
        snipes = _load_snipes()
        snipes.append(snipe)
        snipes = _prune_snipes(snipes)
        _save_snipes(snipes)
    return snipe


@app.get("/api/snipes")
def list_snipes(status: str = Query("")):
    snipes = _load_snipes()
    if status:
        snipes = [s for s in snipes if s.get("status") == status]
    snipes.sort(key=lambda s: s.get("fire_at", ""), reverse=True)
    return snipes


@app.delete("/api/snipes/{snipe_id}")
def cancel_snipe(snipe_id: str):
    with _SNIPE_LOCK:
        snipes = _load_snipes()
        for s in snipes:
            if s.get("id") == snipe_id:
                cur = s.get("status")
                if cur != "scheduled":
                    raise HTTPException(409, f"cannot cancel snipe in status {cur!r}")
                s["status"] = "cancelled"
                s["result"] = "cancelled by user"
                s["fired_at"] = datetime.now(timezone.utc).isoformat()
                _save_snipes(snipes)
                return s
    raise HTTPException(404, "snipe not found")


@app.api_route("/api/snipe/tick", methods=["GET", "POST"])
def snipe_tick(request: Request, key: str = Query(default="")):
    header_key = (request.headers.get("x-snipe-key") or "").strip()
    if not _check_snipe_key(key or header_key):
        raise HTTPException(403, "invalid or missing snipe key")
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(seconds=90)
    backstop = now - timedelta(seconds=30)
    spawned = []
    with _SNIPE_LOCK:
        snipes = _load_snipes()
        for s in snipes:
            if s.get("status") != "scheduled":
                continue
            try:
                fire_at = _parse_iso(s["fire_at"])
            except Exception:
                continue
            if fire_at <= horizon and fire_at >= backstop:
                s["status"] = "in_flight"
                spawned.append(s["id"])
        if spawned:
            _save_snipes(snipes)
    for sid in spawned:
        threading.Thread(target=_execute_snipe, args=(sid,), daemon=True).start()
    pending = sum(1 for s in snipes if s.get("status") == "scheduled")
    return {
        "ok": True, "now": now.isoformat(), "horizon": horizon.isoformat(),
        "spawned": spawned, "pending": pending, "total": len(snipes),
    }


@app.get("/api/debug/upstream")
def debug_upstream(brand: str = "Coach", page: int = 1, page_size: int = 5):
    try:
        resp = _shopgoodwill_request(query=brand, page=page, page_size=page_size)
    except requests.RequestException as exc:
        return {"network_error": str(exc)}
    return {
        "status": resp.status_code,
        "content_type": resp.headers.get("Content-Type", ""),
        "body_snippet": (resp.text or "")[:600],
        "has_token": bool(_get_active_token()),
    }


@app.get("/api/brands")
def get_brands():
    return store_get_brands()


@app.post("/api/brands")
def set_brands(brands: List[str]):
    return store_set_brands(brands)


@app.get("/api/picks")
def list_picks():
    return store_get_picks()


@app.post("/api/picks")
def save_picks(picks: List[Dict[str, Any]]):
    return store_set_picks(picks)


@app.get("/api/picks/feed", response_model=List[FeedItem])
def picks_feed(page: int = Query(1, ge=1), picks_per_page: int = Query(12, ge=1, le=24)):
    picks = store_get_picks()
    if not picks:
        return []
    start = (page - 1) * picks_per_page
    end = start + picks_per_page
    chunk = picks[start:end]
    if not chunk:
        return []
    all_items = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for batch in pool.map(_search_one_pick, chunk):
            all_items.extend(batch)
    seen, deduped = set(), []
    for it in sorted(
        all_items,
        key=lambda x: (1 if x.is_closed else 0,
                       x.seconds_left if x.seconds_left > 0 else 10**9),
    ):
        if it.id in seen:
            continue
        seen.add(it.id)
        deduped.append(it)
    return deduped


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
    sess = _read_session_auth()
    snipes = _load_snipes() if (_supabase_enabled() or SNIPES_FILE.exists()) else []
    return {
        "ok": True,
        "storage": "supabase" if _supabase_enabled() else "file",
        "bidding": bool(_get_active_token()),
        "auth_source": "session" if (sess and sess.get("token")) else (
            "env" if (os.environ.get("SHOPGOODWILL_TOKEN") or "").strip() else "none"
        ),
        "auth_username": (sess or {}).get("username", "") if sess else "",
        "retail_lookup": bool(ANTHROPIC_API_KEY),
        "retail_model": ANTHROPIC_MODEL if ANTHROPIC_API_KEY else None,
        "picks": len(store_get_picks()),
        "snipe_tick_configured": bool(SNIPE_TICK_SECRET),
        "snipes_pending": sum(1 for s in snipes if s.get("status") == "scheduled"),
        "snipes_total": len(snipes),
    }


@app.get("/picks.js")
def serve_picks_js():
    if PICKS_JS_FILE.exists():
        return FileResponse(str(PICKS_JS_FILE), media_type="application/javascript")
    raise HTTPException(status_code=404)


@app.get("/snipe.js")
def serve_snipe_js():
    if SNIPE_JS_FILE.exists():
        return FileResponse(str(SNIPE_JS_FILE), media_type="application/javascript")
    raise HTTPException(status_code=404)


@app.get("/auth.js")
def serve_auth_js():
    if AUTH_JS_FILE.exists():
        return FileResponse(str(AUTH_JS_FILE), media_type="application/javascript")
    raise HTTPException(status_code=404)


@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    if not FRONTEND_FILE.exists():
        raise HTTPException(status_code=404, detail="shopgoodwill_feed.html not found")
    html = FRONTEND_FILE.read_text()
    if "/picks.js" not in html:
        html = html.replace("</body>", _FRAME_INJECTION + "</body>", 1)
    return HTMLResponse(html, media_type="text/html")


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
