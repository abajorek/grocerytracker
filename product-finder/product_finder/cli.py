"""Command-line entry point. Mostly for offline verification / scripting.

    python -m product_finder.cli "best extension cord" --mock
    python -m product_finder.cli "best extension cord"        # live (needs keys)
"""

import argparse
import json
import logging
import sys

from .pipeline import run_search


def main(argv=None):
    parser = argparse.ArgumentParser(description="Find good/better/best product picks.")
    parser.add_argument("query", help="e.g. 'best heavy-duty extension cord'")
    parser.add_argument("--mock", action="store_true",
                        help="Use bundled fixtures + mock synthesis (no API keys).")
    parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    try:
        rec = run_search(args.query, mock=args.mock)
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(rec.to_dict(), indent=2))
        return 0

    print(f"\n=== {rec.query} ===\n")
    print(rec.summary, "\n")
    for t in rec.tiers:
        price = f" (~{t.approx_price})" if t.approx_price else ""
        print(f"[{t.tier.upper()}] {t.product}{price}")
        print(f"    why: {t.why}")
        print(f"    consensus: {t.consensus}")
        for q in t.quotes:
            print(f"    “{q.text}”")
            print(f"      -> {q.url}")
        print()
    if rec.caveats:
        print(f"Caveats: {rec.caveats}")
    print(f"\nSources searched: {', '.join(rec.sources_searched)}")
    print(f"Evidence gathered: {len(rec.snippets)} snippets"
          + ("  [MOCK]" if rec.mock else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
