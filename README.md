# grocerytracker

Little tools for tracking prices on things we buy.

## Grocery price comparison

Multi-store scraper that compares prices across Walmart, Safeway, Sprouts,
Sam's Club, and City Market.

```bash
pip install -r requirements.txt
python grocery_scraper.py
```

Open `price_dashboard.html` in a browser for the standalone dashboard UI.

## Sarah's Thrift Feed (ShopGoodwill)

A TikTok-style vertical swipe feed for ShopGoodwill auctions, filtered to the
brands you pin. Built for Sarah.

```bash
pip install -r requirements.txt
python shopgoodwill_api.py
```

Then open <http://127.0.0.1:8765> on your phone or in a browser.

- Tap a brand chip up top to swap feeds. Tap **+ pin** to add brands; tap a
  pinned brand in the manager to remove it.
- Flick up for the next listing.
- Double-tap a card to save it; the heart-burst confirms.
- Swipe right (or tap the **i** button) to open the detail drawer.
- Tap the **↗** button to jump to the live ShopGoodwill listing to bid.
- The **♥ saved** chip at the end of the brand bar shows everything you've kept.

### If you need authenticated search

ShopGoodwill's `Search/ItemListing` endpoint usually works anonymously. If it
starts rejecting requests, grab a JWT from a logged-in browser session and
export it before launching:

```bash
export SHOPGOODWILL_TOKEN=eyJhbGciOi...
python shopgoodwill_api.py
```

Favorites and pinned brands are stored in `./data/`.
