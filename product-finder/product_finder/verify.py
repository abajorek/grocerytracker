"""Evidence checks that run in code, after Claude answers.

The synthesis prompt asks Claude to quote verbatim, discount affiliate spam and
report consensus honestly. Asking is not enough, so this module checks:

* source_tier()      - trusted reviewer / community / unknown / blocked, by domain
* filter_blocked()   - drops known affiliate/SEO-spam pages before synthesis
* verify_quotes()    - every quote must appear in the evidence; others are dropped
* verify_rating()    - a star rating is kept only if its number is in its source
* grade_evidence()   - counts independent domains that mention a pick and grades
                       the evidence High / Medium / Low (replaces "trust me")
* coverage()         - what each source type actually returned, including zeros
"""

import re
from collections import Counter
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from .models import SourceSnippet, Recommendation, Tier, REDDIT, REVIEW, WEB

TRUSTED = "trusted"
COMMUNITY = "community"
UNKNOWN = "unknown"
BLOCKED = "blocked"

_STOPWORDS = {
    "the", "and", "with", "for", "pro", "plus", "max", "new", "inch", "in",
    "ft", "pack", "set", "of", "by", "a", "an",
}


# ---- Domains ---------------------------------------------------------------

def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _matches(host: str, entry: str) -> bool:
    d = entry.lower().split("/")[0]
    if d.startswith("*."):
        return host.endswith(d[1:])
    return host == d or host.endswith("." + d)


def source_tier(url: str, trust: dict) -> str:
    host = domain_of(url)
    if not host:
        return UNKNOWN
    if any(_matches(host, d) for d in trust.get("blocked_domains", [])):
        return BLOCKED
    if any(_matches(host, d) for d in trust.get("trusted_reviewers", [])):
        return TRUSTED
    if any(_matches(host, d) for d in trust.get("community", [])):
        return COMMUNITY
    return UNKNOWN


def filter_blocked(snippets: List[SourceSnippet],
                   trust: dict) -> Tuple[List[SourceSnippet], List[str]]:
    kept, blocked = [], []
    for s in snippets:
        if source_tier(s.url, trust) == BLOCKED:
            blocked.append(domain_of(s.url))
        else:
            kept.append(s)
    return kept, blocked


# ---- Text matching ---------------------------------------------------------

def _norm(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[‘’“”\"'`]", "", text)
    text = re.sub(r"[^a-z0-9.%$/]+", " ", text)
    return " ".join(text.split())


def _strip_ellipses(quote: str) -> List[str]:
    """A quote with '...' is checked piece by piece."""
    parts = re.split(r"\.\.\.|…", quote)
    return [p for p in (_norm(x) for x in parts) if len(p) >= 12]


def quote_found(quote: str, snippets: Iterable[SourceSnippet],
                url: Optional[str] = None) -> bool:
    pieces = _strip_ellipses(quote)
    if not pieces:
        return False
    pool = list(snippets)
    if url:
        same = [s for s in pool if s.url == url]
        pool = same or pool
    for s in pool:
        body = _norm(s.text + " " + s.title)
        if all(p in body for p in pieces):
            return True
    return False


def product_tokens(product: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+", product.lower())
    return [w for w in words if w not in _STOPWORDS and (len(w) >= 3 or any(c.isdigit() for c in w))]


def mentions(product: str, snippet: SourceSnippet) -> bool:
    toks = product_tokens(product)
    if not toks:
        return False
    body = " " + _norm(snippet.text + " " + snippet.title) + " "
    hits = sum(1 for t in toks if f" {t} " in body or f" {t}" in body)
    need = 1 if len(toks) == 1 else 2
    # The brand (first token) must appear; one more token must too.
    return f" {toks[0]}" in body and hits >= need


# ---- Checks on Claude's answer ---------------------------------------------

def verify_quotes(rec: Recommendation) -> int:
    """Drop quotes that are not in the evidence. Returns how many were dropped."""
    dropped = 0
    for t in rec.tiers:
        kept = []
        for q in t.quotes:
            if quote_found(q.text, rec.snippets, q.url):
                kept.append(q)
            else:
                dropped += 1
        t.quotes = kept
        t.verified = bool(kept)
    return dropped


def verify_rating(t: Tier, snippets: List[SourceSnippet]) -> None:
    """Keep a star rating only if its number appears in the cited source."""
    r = t.rating or {}
    stars = r.get("stars")
    src = r.get("source_url", "")
    if stars in (None, ""):
        t.rating = {}
        return
    try:
        value = float(stars)
    except (TypeError, ValueError):
        t.rating = {}
        return
    pool = [s for s in snippets if s.url == src] or []
    needle = f"{value:g}"
    if not any(needle in s.text for s in pool):
        t.rating = {}
        return
    r["stars"] = value
    t.rating = r


def grade_evidence(t: Tier, snippets: List[SourceSnippet], trust: dict) -> None:
    """Count independent domains that mention this pick, then grade it."""
    domains: Dict[str, str] = {}
    for s in snippets:
        if mentions(t.product, s):
            d = domain_of(s.url)
            if d:
                domains[d] = source_tier(s.url, trust)
    counts = Counter(domains.values())
    t.source_count = len(domains)
    t.trusted_count = counts.get(TRUSTED, 0)
    t.community_count = counts.get(COMMUNITY, 0)
    t.source_domains = sorted(domains)
    if (t.trusted_count >= 1 and t.source_count >= 2) or t.source_count >= 3:
        t.evidence_grade = "High"
    elif t.source_count == 2 or t.trusted_count >= 1:
        t.evidence_grade = "Medium"
    else:
        t.evidence_grade = "Low"
    t.consensus = (
        f"{t.evidence_grade}: mentioned by {t.source_count} independent "
        f"site{'s' if t.source_count != 1 else ''}"
        f" ({t.trusted_count} trusted reviewer, {t.community_count} community)"
    )
    if t.rating:
        floor = float(trust.get("min_rating", 4.0))
        if t.rating.get("stars", 5) < floor:
            t.warning = (f"Rated {t.rating['stars']:g} stars, below the "
                         f"{floor:g} minimum. Not recommended.")


def coverage(snippets: List[SourceSnippet], blocked: List[str],
             trust: dict) -> Dict[str, int]:
    out = {"reddit": 0, "trusted_reviewers": 0, "other_web": 0,
           "blocked_spam": len(blocked)}
    for s in snippets:
        tier = source_tier(s.url, trust)
        if s.source_type == REDDIT or "reddit.com" in domain_of(s.url):
            out["reddit"] += 1
        elif tier == TRUSTED:
            out["trusted_reviewers"] += 1
        else:
            out["other_web"] += 1
    return out


def apply_all(rec: Recommendation, blocked: List[str], trust: dict) -> Recommendation:
    rec.dropped_quotes = verify_quotes(rec)
    for t in rec.tiers:
        verify_rating(t, rec.snippets)
        grade_evidence(t, rec.snippets, trust)
    rec.coverage = coverage(rec.snippets, blocked, trust)
    rec.blocked_sources = sorted(set(blocked))
    return rec
