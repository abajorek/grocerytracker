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

A TikTok-style vertical swipe feed for ShopGoodwill auctions, filtered to
the brands you pin. Cream / sage / dusty-rose aesthetic, full-bleed photos,
flick-up to scroll, double-tap to save, swipe right for details.

### Get it on Sarah's phone (no command line)

#### 1. Make a free Supabase project (saves favorites + pinned brands)

1. Sign in at <https://supabase.com> and create a new project. Pick any
   name. Save the auto-generated database password somewhere safe.
2. While the project finishes provisioning (≈ 1 minute), open
   **Project Settings → API** and copy two values:
   - **Project URL** — looks like `https://xxxxxxxx.supabase.co`
   - **`service_role` key** (under Project API keys) — starts with `eyJ…`

3. Open **SQL Editor**, paste in this snippet and click **Run**:

   ```sql
   create table if not exists thrift_settings (
     key   text primary key,
     value jsonb
   );

   create table if not exists thrift_favorites (
     item_id     bigint primary key,
     title       text,
     image_url   text,
     listing_url text,
     brand       text default '',
     saved_at    timestamptz default now()
   );
   ```

#### 2. Deploy to Render (free)

Click this link and sign in with GitHub:

[**Deploy on Render →**](https://render.com/deploy?repo=https://github.com/abajorek/grocerytracker&branch=claude/research-shopgoodwill-scripts-hKck6)

Render reads `render.yaml` and offers to create the service. Before
clicking **Apply**, fill in the two empty env vars:

| Key | Value |
| --- | --- |
| `SUPABASE_URL` | the Project URL from step 1 |
| `SUPABASE_KEY` | the `service_role` key from step 1 |

Leave `SHOPGOODWILL_TOKEN` blank for now — only needed if anonymous
search starts failing.

After ≈ 2 minutes Render hands you a public URL like
`https://sarah-thrift-feed.onrender.com`.

#### 3. Add it to Sarah's home screen

Open the Render URL in a phone browser, then:

- **iPhone (Safari)**: tap the **Share** icon → **Add to Home Screen**.
  The app launches fullscreen with the cream-and-rose icon.
- **Android (Chrome)**: menu → **Install app** (or **Add to Home Screen**).

That's it. No CLI, no app store.

### Heads-up on Render's free tier

The service sleeps after ≈ 15 minutes of inactivity. The first tap after
a nap takes ≈ 30 seconds while it wakes — the UI shows a friendly
"warming up" card during that wait. Once awake it stays snappy.

### Using the feed

- Tap a brand chip up top to swap feeds. Tap **+ pin** to add brands;
  tap a chip in the manager to remove it.
- Flick up for the next listing.
- Double-tap a card to save it; the heart-burst confirms.
- Swipe right (or tap **i**) to open the detail drawer.
- Tap **↗** to jump to the live ShopGoodwill listing to bid.
- The **♥ saved** chip at the end of the brand bar shows everything
  you've kept.

### Run locally instead

```bash
pip install -r requirements.txt
python shopgoodwill_api.py
```

Then open <http://127.0.0.1:8765>. Without `SUPABASE_URL`/`SUPABASE_KEY`
set, favorites and brands persist to JSON files in `./data/`.

### If ShopGoodwill rejects anonymous traffic

Grab a JWT from a logged-in browser session (Network tab → any
`buyerapi.shopgoodwill.com` request → `Authorization: Bearer …`). Add it
to Render under **Environment → Add Environment Variable**:

| Key | Value |
| --- | --- |
| `SHOPGOODWILL_TOKEN` | the JWT (without the `Bearer ` prefix) |

Render redeploys automatically.
