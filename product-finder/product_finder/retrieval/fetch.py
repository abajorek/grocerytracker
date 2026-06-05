"""Fetch and extract the main text of a public page, respecting robots.txt.

If robots disallows the path (or anything goes wrong), we return None and the
caller falls back to the search-result snippet. This is deliberately polite:
the tool reads a handful of public pages a user explicitly asked about; it is
not a crawler.
"""

import logging
from functools import lru_cache
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from typing import Optional

log = logging.getLogger("fetch")


@lru_cache(maxsize=128)
def _robots_for(scheme: str, netloc: str, user_agent: str) -> Optional[RobotFileParser]:
    try:
        rp = RobotFileParser()
        rp.set_url(f"{scheme}://{netloc}/robots.txt")
        rp.read()
        return rp
    except Exception as e:  # noqa: BLE001
        log.debug("robots.txt unreadable for %s: %s", netloc, e)
        return None


def can_fetch(url: str, user_agent: str) -> bool:
    parts = urlparse(url)
    if not parts.scheme.startswith("http"):
        return False
    rp = _robots_for(parts.scheme, parts.netloc, user_agent)
    if rp is None:
        # Couldn't read robots -> be conservative, don't fetch full text.
        return False
    try:
        return rp.can_fetch(user_agent, url)
    except Exception:  # noqa: BLE001
        return False


def fetch_main_text(url: str, user_agent: str, timeout: int = 10,
                    max_chars: int = 1500) -> Optional[str]:
    """Return cleaned article text, or None to signal 'use the snippet instead'."""
    if not can_fetch(url, user_agent):
        return None
    try:
        import trafilatura
    except ImportError:
        log.warning("trafilatura not installed; using snippets only.")
        return None
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        text = trafilatura.extract(downloaded, include_comments=False,
                                   include_tables=False)
        if not text:
            return None
        return text.strip()[:max_chars]
    except Exception as e:  # noqa: BLE001
        log.debug("fetch failed for %s: %s", url, e)
        return None
