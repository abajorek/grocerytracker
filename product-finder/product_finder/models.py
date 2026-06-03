"""Shared data structures.

`SourceSnippet` mirrors the dataclass-per-record pattern used by
grocerytracker's `PriceRecord`, but instead of a price it carries a chunk of
real human opinion (a Reddit comment, a review excerpt, a forum post) plus
enough provenance to cite it.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any


# What kind of source a snippet came from. Used for weighting / display only.
REDDIT = "reddit"
REVIEW = "review"   # one of the user's trusted review-site domains
WEB = "web"         # general open-web / forum result


@dataclass
class SourceSnippet:
    """One piece of evidence Claude is allowed to read and cite."""
    source_type: str          # REDDIT | REVIEW | WEB
    title: str
    url: str
    text: str                 # the opinion/excerpt itself (already length-capped)
    score: int = 0            # upvotes for Reddit, 0 otherwise
    origin: str = ""          # e.g. "r/Tools" or "rtings.com"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Quote:
    text: str
    url: str


@dataclass
class Tier:
    """A single good / better / best pick."""
    tier: str                 # "good" | "better" | "best"
    product: str
    why: str
    consensus: str            # e.g. "strong — 5 independent sources agree"
    quotes: List[Quote] = field(default_factory=list)
    approx_price: str = ""
    image_url: str = ""       # optional real product photo (else card shows line-art)


@dataclass
class Recommendation:
    """The synthesized answer rendered on the dashboard."""
    query: str
    summary: str
    tiers: List[Tier] = field(default_factory=list)
    caveats: str = ""
    sources_searched: List[str] = field(default_factory=list)
    snippets: List[SourceSnippet] = field(default_factory=list)  # raw evidence
    mock: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "summary": self.summary,
            "tiers": [asdict(t) for t in self.tiers],
            "caveats": self.caveats,
            "sources_searched": self.sources_searched,
            "snippets": [s.to_dict() for s in self.snippets],
            "mock": self.mock,
        }
