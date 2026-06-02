# Product Finder

Search the **boards of opinion you trust** — Reddit, forums, and independent
review sites (RTINGS, OutdoorGearLab, Wirecutter, Consumer Reports) — and get a
**good / better / best** answer with real quotes and source links, *without* the
SEO/affiliate listicle hoopla.

Ask: *"what's a good heavy-duty extension cord?"* → get three ranked picks,
why each, how many sources agree, and where each claim came from.

```
search box (browser)
   → retrieve   (Reddit API  +  keyless web search + page fetch)
   → synthesize (Claude reads the evidence → tiered, cited answer)
   → dashboard  (Good / Better / Best cards with quotes + links)
```

## Why it works this way

- **Reddit is not off-limits.** It has an official API. You register a free
  "script" app under your own login, get a client id + secret, and the tool
  queries in *read-only* mode. No scraping, no password, nothing that
  circumvents Reddit. Reliable and within their terms.
- **Review sites** are searched with a keyless DuckDuckGo backend using
  `site:` filters, then the public page text is extracted (respecting
  `robots.txt`). Paywalled pages fall back to their public snippet.
- **Claude does the judging** — its prompt is built to ignore marketing fluff
  and affiliate roundups and surface what real users / independent testers
  actually conclude, with citations.

## Setup

You need **Python 3.10+**.

```bash
cd product-finder
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in the keys below
```

### 1. Reddit API key (free, ~2 minutes)

1. Log in to Reddit, go to <https://www.reddit.com/prefs/apps>.
2. Click **"create another app…"** at the bottom.
3. Choose type **script**. Name it anything (e.g. `product-finder`).
   Set redirect uri to `http://localhost:8080` (required but unused).
4. Click create. The string under the app name is your **client id**;
   **secret** is shown next to "secret".
5. Put both in `.env` as `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`, and set
   `REDDIT_USER_AGENT` to something like `product-finder/0.1 by u/your_username`.

### 2. Claude API key

Get one at <https://console.anthropic.com/> → **API Keys**, and put it in
`.env` as `ANTHROPIC_API_KEY`. Synthesis defaults to `claude-sonnet-4-6`
(fast + inexpensive); a typical search costs well under a cent.

### 3. Choose your sources

Edit **`sources.yaml`** — add/remove subreddits and review-site domains, toggle
general web search, and pick the model. No code changes required.

## Run

```bash
# Web dashboard:
flask --app product_finder.app run
# open http://localhost:5000

# Or the CLI:
python -m product_finder.cli "best heavy-duty extension cord"
```

### Try it with no keys

To check the layout/pipeline before wiring up keys, use the bundled sample data:

```bash
python -m product_finder.cli "best extension cord" --mock
```
…or click **"Try demo"** in the web UI.

## Costs

- Reddit API: free for this volume.
- DuckDuckGo search: free, no key (unofficial + rate-limited — fine for
  personal use).
- Claude: pay-as-you-go; a search sends ~40 short snippets, typically a
  fraction of a cent on Sonnet.

## Good-citizen notes

- `robots.txt` is honored before fetching any full page; if it can't be read,
  the tool uses only the search snippet.
- This reads a handful of public pages a user explicitly asked about — it is
  not a crawler/scraper farm. Respect each site's terms.

## Roadmap

- Drop-in **Brave/Bing Search API** key for more reliable, higher-volume search
  (swap the backend in `retrieval/web_source.py`).
- Persist past searches; compare picks over time.
- Per-source trust weighting in synthesis.

## Layout

```
product-finder/
  sources.yaml            # your trusted sources + settings (edit this)
  .env                    # your keys (gitignored)
  requirements.txt
  product_finder/
    config.py             # loads sources.yaml + .env
    models.py             # SourceSnippet / Tier / Recommendation dataclasses
    pipeline.py           # retrieve -> synthesize orchestration
    synthesis.py          # Claude call (structured output + prompt caching) + mock
    cli.py                # command-line entry point
    app.py                # Flask dashboard
    retrieval/
      reddit_source.py    # PRAW, read-only
      web_source.py       # keyless DuckDuckGo (site: filters + general)
      fetch.py            # robots-respecting page text extraction
    templates/ static/    # dashboard UI
    fixtures/             # sample data for --mock / demo
```
