"""Reddit retrieval via the official API (PRAW), read-only.

This uses Reddit's *supported* API path: a registered "script" app gives you a
client id + secret, and we query in read-only mode. No scraping, no password,
nothing that circumvents Reddit's protections. See the README for the 2-minute
app registration steps.
"""

import logging
from typing import List

from ..models import SourceSnippet, REDDIT

log = logging.getLogger("reddit_source")


def search_reddit(query: str, subreddits: List[str], creds: dict,
                  posts_per_sub: int = 4, comments_per_post: int = 6,
                  max_chars: int = 1500) -> List[SourceSnippet]:
    """Search each configured subreddit and return posts + top comments.

    Returns an empty list (and logs) on any failure so the rest of the
    pipeline keeps working even if Reddit is unavailable.
    """
    try:
        import praw  # imported lazily so the app runs without the dep for mock mode
    except ImportError:
        log.warning("praw not installed; skipping Reddit. `pip install praw`")
        return []

    if not (creds.get("client_id") and creds.get("client_secret")):
        log.info("No Reddit credentials; skipping Reddit search.")
        return []

    try:
        reddit = praw.Reddit(
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
            user_agent=creds.get("user_agent", "product-finder/0.1"),
        )
        reddit.read_only = True
    except Exception as e:  # noqa: BLE001 - surface but don't crash pipeline
        log.warning("Reddit init failed: %s", e)
        return []

    snippets: List[SourceSnippet] = []
    for sub in subreddits:
        try:
            for post in reddit.subreddit(sub).search(query, sort="relevance",
                                                      limit=posts_per_sub):
                body = (post.selftext or "").strip()
                snippets.append(SourceSnippet(
                    source_type=REDDIT,
                    title=post.title,
                    url=f"https://www.reddit.com{post.permalink}",
                    text=body[:max_chars] if body else post.title,
                    score=int(getattr(post, "score", 0)),
                    origin=f"r/{sub}",
                ))
                # Pull the most-upvoted top-level comments (the real signal).
                try:
                    post.comments.replace_more(limit=0)
                    top = sorted(post.comments[:25],
                                 key=lambda c: getattr(c, "score", 0),
                                 reverse=True)[:comments_per_post]
                    for c in top:
                        text = (getattr(c, "body", "") or "").strip()
                        if len(text) < 25:
                            continue
                        snippets.append(SourceSnippet(
                            source_type=REDDIT,
                            title=f"comment on: {post.title}",
                            url=f"https://www.reddit.com{post.permalink}",
                            text=text[:max_chars],
                            score=int(getattr(c, "score", 0)),
                            origin=f"r/{sub}",
                        ))
                except Exception as e:  # noqa: BLE001
                    log.debug("comment fetch failed for %s: %s", post.id, e)
        except Exception as e:  # noqa: BLE001
            log.warning("search failed for r/%s: %s", sub, e)
    return snippets
