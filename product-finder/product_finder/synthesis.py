"""Turn raw evidence into a good / better / best recommendation using Claude.

We force structured output via a tool schema (so parsing is reliable) and cache
the long system prompt with `cache_control` so repeated searches in a session
are cheaper. The prompt's whole job is to strip marketing fluff and surface
what real users and independent reviewers actually conclude — with citations.
"""

import json
import logging
from typing import List

from .models import SourceSnippet, Recommendation, Tier, Quote

log = logging.getLogger("synthesis")

SYSTEM_PROMPT = """You are a no-nonsense product-recommendation analyst.

You are given EVIDENCE: excerpts from Reddit threads, independent review sites
(e.g. RTINGS, OutdoorGearLab, Wirecutter, Consumer Reports) and forums, each
with a URL. Your job is to answer the user's "what should I buy" question with a
GOOD / BETTER / BEST tiering grounded ONLY in that evidence.

Hard rules:
- Recommend specific products/models, not vague categories.
- Prefer claims that MULTIPLE independent sources agree on. State consensus
  honestly (e.g. "strong — 5 sources agree" vs "single reviewer's opinion").
- IGNORE marketing fluff, affiliate "top 10" listicles, and SEO spam. If a
  source reads like an affiliate roundup with no real testing or user
  experience, discount it.
- Every tier MUST include at least one short verbatim quote with its source URL.
  Quotes must come from the provided evidence — never invent them.
- If the evidence is thin or conflicting, say so plainly in caveats. Do not
  pad. No hype.
- Keep "why" to one or two sentences."""

EMIT_TOOL = {
    "name": "emit_recommendations",
    "description": "Return the structured good/better/best recommendation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "2-3 sentence plain-English bottom line.",
            },
            "tiers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tier": {"type": "string", "enum": ["good", "better", "best"]},
                        "product": {"type": "string"},
                        "why": {"type": "string"},
                        "consensus": {"type": "string"},
                        "approx_price": {"type": "string"},
                        "image_url": {
                            "type": "string",
                            "description": "Optional direct product image URL ONLY if "
                                           "one clearly appears in the evidence; else omit.",
                        },
                        "quotes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "text": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                                "required": ["text", "url"],
                            },
                        },
                    },
                    "required": ["tier", "product", "why", "consensus", "quotes"],
                },
            },
            "caveats": {"type": "string"},
        },
        "required": ["summary", "tiers"],
    },
}


def _format_evidence(snippets: List[SourceSnippet]) -> str:
    lines = []
    for i, s in enumerate(snippets, 1):
        lines.append(
            f"[{i}] ({s.source_type}, {s.origin}, score={s.score}) {s.title}\n"
            f"    URL: {s.url}\n"
            f"    {s.text}"
        )
    return "\n\n".join(lines)


def synthesize(query: str, snippets: List[SourceSnippet], model: str) -> Recommendation:
    """Call Claude and parse the structured tool output into a Recommendation."""
    import anthropic  # lazy import keeps mock mode dependency-free

    client = anthropic.Anthropic()
    user_content = (
        f"Question: {query}\n\n"
        f"EVIDENCE ({len(snippets)} items):\n\n{_format_evidence(snippets)}"
    )

    resp = client.messages.create(
        model=model,
        max_tokens=2000,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        tools=[EMIT_TOOL],
        tool_choice={"type": "tool", "name": "emit_recommendations"},
        messages=[{"role": "user", "content": user_content}],
    )

    data = None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            data = block.input
            break
    if data is None:
        raise RuntimeError("Claude did not return structured recommendations.")

    return _build(query, data, snippets, mock=False)


def _build(query, data, snippets, mock):
    tiers = []
    for t in data.get("tiers", []):
        tiers.append(Tier(
            tier=t.get("tier", ""),
            product=t.get("product", ""),
            why=t.get("why", ""),
            consensus=t.get("consensus", ""),
            approx_price=t.get("approx_price", ""),
            image_url=t.get("image_url", ""),
            quotes=[Quote(q.get("text", ""), q.get("url", ""))
                    for q in t.get("quotes", [])],
        ))
    return Recommendation(
        query=query,
        summary=data.get("summary", ""),
        tiers=tiers,
        caveats=data.get("caveats", ""),
        snippets=snippets,
        mock=mock,
    )


def synthesize_mock(query: str, snippets: List[SourceSnippet]) -> Recommendation:
    """Offline synthesis: no API call. Builds a plausible 3-tier result from the
    highest-scoring snippets so the full pipeline + dashboard can be verified
    without any keys."""
    ranked = sorted(snippets, key=lambda s: s.score, reverse=True)
    picks = ranked[:3] if len(ranked) >= 3 else ranked + ranked[:3 - len(ranked)]
    labels = ["good", "better", "best"]
    tiers = []
    for label, s in zip(labels, picks):
        tiers.append(Tier(
            tier=label,
            product=f"[mock] pick from {s.origin or s.source_type}",
            why="Placeholder reasoning — mock mode does not call Claude.",
            consensus=f"mock — derived from snippet score {s.score}",
            approx_price="n/a",
            quotes=[Quote(text=s.text[:160], url=s.url)],
        ))
    return Recommendation(
        query=query,
        summary="MOCK RESULT — wiring/dashboard check only. Add an "
                "ANTHROPIC_API_KEY and run without --mock for real analysis.",
        tiers=tiers,
        caveats="This is mock output to verify the pipeline end-to-end offline.",
        snippets=snippets,
        mock=True,
    )
