"""Keyless web search via DuckDuckGo (`ddgs`).

Two modes, both driven by sources.yaml:
  * review_sites  -> one `query site:domain` search per trusted domain
  * general web   -> a plain query across forums/the open web

No API key required. This is great for personal use but is unofficial and
rate-limited; the README documents the drop-in upgrade to a Brave/Bing key for
volume/reliability. Failures degrade to an empty list rather than crashing.
"""

import logging
from dataclasses import dataclass
from typing import List

log = logging.getLogger("web_source")


@dataclass
class WebHit:
    title: str
    url: str
    snippet: str
    site: str        # the trusted domain it matched, or "web" for general


def _normalize(row: dict) -> dict:
    """ddgs has used both {'href','body'} and {'url','description'} over time."""
    return {
        "title": row.get("title", "") or "",
        "url": row.get("href") or row.get("url") or "",
        "snippet": row.get("body") or row.get("description") or "",
    }


def _search(ddgs, query: str, max_results: int) -> List[dict]:
    try:
        return list(ddgs.text(query, max_results=max_results))
    except TypeError:
        # Older/newer signatures: keywords= positional.
        return list(ddgs.text(keywords=query, max_results=max_results))


def search_web(query: str, review_sites: List[str], enable_general: bool,
               results_per_site: int = 3, general_results: int = 6) -> List[WebHit]:
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # legacy package name
        except ImportError:
            log.warning("ddgs not installed; skipping web search. `pip install ddgs`")
            return []

    hits: List[WebHit] = []
    try:
        with DDGS() as ddgs:
            for site in review_sites:
                try:
                    for row in _search(ddgs, f"{query} site:{site}", results_per_site):
                        r = _normalize(row)
                        if r["url"]:
                            hits.append(WebHit(r["title"], r["url"], r["snippet"], site))
                except Exception as e:  # noqa: BLE001
                    log.warning("site search failed for %s: %s", site, e)
            if enable_general:
                try:
                    for row in _search(ddgs, query, general_results):
                        r = _normalize(row)
                        if r["url"]:
                            hits.append(WebHit(r["title"], r["url"], r["snippet"], "web"))
                except Exception as e:  # noqa: BLE001
                    log.warning("general web search failed: %s", e)
    except Exception as e:  # noqa: BLE001
        log.warning("DuckDuckGo unavailable: %s", e)
    return hits
