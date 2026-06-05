"""Keyless product-image lookup via DuckDuckGo image search.

Given a product name, returns a single image URL (or "" if none). Used to
enrich recommendation cards with a real photo; on any failure the card falls
back to its line-art illustration, so this is always best-effort.
"""

import logging

log = logging.getLogger("image_source")


def _images(ddgs, query: str, max_results: int):
    try:
        return list(ddgs.images(query, max_results=max_results))
    except TypeError:
        return list(ddgs.images(keywords=query, max_results=max_results))


def find_image(query: str) -> str:
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # legacy package name
        except ImportError:
            log.warning("ddgs not installed; skipping image lookup.")
            return ""

    try:
        with DDGS() as ddgs:
            for row in _images(ddgs, query, max_results=4):
                # Prefer DDG's proxied thumbnail (hotlink-friendly), then the
                # full image; tolerate key-name drift across ddgs versions.
                url = (row.get("thumbnail") or row.get("image")
                       or row.get("thumbnailUrl") or row.get("url") or "")
                if url.startswith("http"):
                    return url
    except Exception as e:  # noqa: BLE001 - best-effort, never crash the pipeline
        log.debug("image lookup failed for %r: %s", query, e)
    return ""
