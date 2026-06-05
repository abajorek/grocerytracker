"""Orchestrates: retrieve evidence -> synthesize -> Recommendation.

`run_search(query, mock=...)` is the single entry point used by both the CLI
and the Flask app.
"""

import json
import logging
from pathlib import Path
from typing import List

from . import config as cfg
from .models import SourceSnippet, Recommendation, REDDIT, REVIEW, WEB
from .retrieval import reddit_source, web_source, fetch, image_source
from . import synthesis

log = logging.getLogger("pipeline")

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_snippets.json"


def _load_fixture() -> List[SourceSnippet]:
    with open(FIXTURE, "r", encoding="utf-8") as f:
        rows = json.load(f)
    return [SourceSnippet(**r) for r in rows]


def gather_evidence(query: str, conf: dict) -> List[SourceSnippet]:
    """Run all configured retrieval sources and return combined snippets."""
    ret = conf["retrieval"]
    snippets: List[SourceSnippet] = []

    # 1) Reddit (official API)
    snippets += reddit_source.search_reddit(
        query, conf["subreddits"], cfg.reddit_credentials(),
        posts_per_sub=ret["reddit_posts_per_sub"],
        comments_per_post=ret["reddit_comments_per_post"],
        max_chars=ret["max_chars_per_snippet"],
    )

    # 2) Review sites + general web (keyless DuckDuckGo)
    hits = web_source.search_web(
        query, conf["review_sites"], conf["enable_general_web"],
        results_per_site=ret["web_results_per_site"],
        general_results=ret["general_web_results"],
    )
    for h in hits:
        text = h.snippet
        if ret["fetch_full_text"]:
            full = fetch.fetch_main_text(
                h.url, ret["user_agent"],
                timeout=ret["request_timeout"],
                max_chars=ret["max_chars_per_snippet"],
            )
            if full:
                text = full
        if "reddit.com" in h.site:
            stype = REDDIT
        elif h.site != "web":
            stype = REVIEW
        else:
            stype = WEB
        snippets.append(SourceSnippet(
            source_type=stype,
            title=h.title,
            url=h.url,
            text=(text or h.snippet)[:ret["max_chars_per_snippet"]],
            score=0,
            origin=h.site,
        ))

    return snippets[: conf["synthesis"]["max_snippets"]]


def _sources_label(conf: dict) -> List[str]:
    out = [f"r/{s}" for s in conf["subreddits"]]
    out += conf["review_sites"]
    if conf["enable_general_web"]:
        out.append("general web")
    return out


def run_search(query: str, mock: bool = False) -> Recommendation:
    conf = cfg.load_config()

    if mock:
        snippets = _load_fixture()
        rec = synthesis.synthesize_mock(query, snippets)
        rec.sources_searched = ["(mock fixtures)"]
        return rec

    snippets = gather_evidence(query, conf)
    if not snippets:
        rec = Recommendation(
            query=query,
            summary="No evidence found. Check your Reddit credentials / network, "
                    "or widen the sources in sources.yaml.",
            sources_searched=_sources_label(conf),
        )
        return rec

    if not cfg.claude_available():
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to .env, or run in --mock mode "
            "to verify the pipeline without calling Claude."
        )

    rec = synthesis.synthesize(query, snippets, conf["synthesis"]["model"])
    rec.sources_searched = _sources_label(conf)

    # Enrich each pick with a real product photo (best-effort, keyless).
    # Cards fall back to line-art when no image is found.
    if conf["retrieval"].get("fetch_images", True):
        for t in rec.tiers:
            if not t.image_url and t.product:
                t.image_url = image_source.find_image(f"{t.product} product")

    return rec
