"""Loads user config (sources.yaml) and secrets (.env)."""

import os
from pathlib import Path
from typing import Any, Dict

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # tool still works if python-dotenv isn't installed
    def load_dotenv(*_a, **_k):  # type: ignore
        return False

# Project root = the product-finder/ directory (parent of this package).
ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "sources.yaml"

DEFAULT_CONFIG: Dict[str, Any] = {
    "subreddits": ["BuyItForLife", "Tools", "HomeImprovement"],
    "review_sites": [
        "rtings.com",
        "outdoorgearlab.com",
        "nytimes.com/wirecutter",
        "consumerreports.org",
    ],
    "enable_general_web": True,
    "synthesis": {
        # Default to a fast, capable, cost-effective model. Swap to
        # "claude-opus-4-8" in sources.yaml for the deepest synthesis.
        "model": "claude-sonnet-4-6",
        "max_snippets": 40,        # hard cap on evidence sent to Claude
    },
    "retrieval": {
        "reddit_posts_per_sub": 4,
        "reddit_comments_per_post": 6,
        "web_results_per_site": 3,
        "general_web_results": 6,
        "fetch_full_text": True,   # try to pull article body (robots permitting)
        "max_chars_per_snippet": 1500,
        "request_timeout": 10,
        "user_agent": "product-finder/0.1 (personal research; +https://github.com/abajorek)",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> Dict[str, Any]:
    """Read sources.yaml (if present) merged over defaults, and load .env."""
    load_dotenv(ROOT / ".env")
    cfg = dict(DEFAULT_CONFIG)
    if SOURCES_FILE.exists():
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, user_cfg)
    return cfg


def reddit_credentials() -> Dict[str, str]:
    return {
        "client_id": os.getenv("REDDIT_CLIENT_ID", ""),
        "client_secret": os.getenv("REDDIT_CLIENT_SECRET", ""),
        "user_agent": os.getenv("REDDIT_USER_AGENT", "product-finder/0.1 by u/your_username"),
    }


def reddit_available() -> bool:
    c = reddit_credentials()
    return bool(c["client_id"] and c["client_secret"])


def claude_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))
