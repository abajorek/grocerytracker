# Research protocol

These rules apply to every product recommendation, whether the app makes it
or Claude answers in chat. They come from an audit of earlier answers that
recommended 2.9-star products, claimed "Reddit consensus" no search had found,
stated wrong specs from memory, and cited affiliate listicles as evidence.

## 1. Search every time

No recommendation from memory alone. If an answer could not be researched,
label it **"from memory, not verified"**.

## 2. What every pick needs

| Requirement | Rule |
|---|---|
| Exact model | Name the model number. Product lines mix specs across models (the Quickie Bulldozer 599 is polypropylene; the 633 is natural tampico). |
| Star rating | Stars **and** review count **and** where they came from (Amazon, Chewy, Home Depot...). If none was found, say "no rating found". |
| Rating floor | **4.0 stars or better with 100+ reviews.** Anything below is flagged "not recommended", even if it is the only option. |
| Sources | **2+ independent sources** that are not affiliate pages, at least one of them a hands-on tester or a real-owner community. |
| Specs | Materials, sizes and fittings come from a manufacturer or retailer spec page, never from memory. |
| Price | Only from a listing retrieved that day, with the date. Otherwise "check current price". (Instacart prices are not visible to Claude.) |

## 3. What counts as a source

- **Trusted testers:** sites that run their own tests (RTINGS, OutdoorGearLab,
  Wirecutter, Consumer Reports, America's Test Kitchen, King Arthur...).
- **Community:** real-owner threads (Reddit, trade forums).
- **Retail listings:** count for ratings and specs only, not for "best".
- **Do not count:** affiliate "N Best X (Month Year)" pages, AI-written review
  farms, sites on free hosting (`*.pages.dev`, `*.netlify.app`, `*.github.io`).
  The blocklist in `product_finder/config.py` holds the ones seen so far.

## 4. Attribution

- Name a site or community only if a page from it was actually retrieved. No
  "Reddit loves X" without a retrieved thread; no "Wirecutter's pick" without
  Wirecutter's page.
- Quotes are copied exactly from the retrieved text.

## 5. Show the strength of the evidence

Each pick gets a grade, computed the same way as `verify.grade_evidence()`:

- **High:** 3+ independent sites, or a trusted tester plus one more.
- **Medium:** 2 sites, or one trusted tester alone.
- **Low:** 1 site or none.

Also say what was searched and not found (for example "no Reddit threads found").

## 6. Process

- If a request is ambiguous ("no ultrasonic"), ask one short question rather
  than guess.
- If a pick does not survive one pushback, re-run the research instead of
  swapping in the next name that comes to mind.
