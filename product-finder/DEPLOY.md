# Put Product Finder online (free) — phone-friendly guide

Goal: a private web address (like `https://product-finder-xxxx.onrender.com`)
you open from your phone, no terminal needed afterwards. Host: **Render** (free
tier). One-time setup takes ~15 minutes.

You need three things first (all free):
1. A **Reddit API key** (client id + secret)
2. A **Claude API key**
3. A password you make up (to lock the site so only you can use it)

> Getting the two keys is in the main [README](README.md#setup), steps 1 and 2.
> Tip: email yourself the keys so you can paste them on your phone.

---

## Steps

**1. Merge the code to `main` (one tap)**
Open [PR #1](https://github.com/abajorek/grocerytracker/pull/1) in the GitHub
app and tap **Merge**. (Render reads the `render.yaml` blueprint from your repo.)

**2. Create a Render account**
Go to <https://render.com> → **Get Started** → **Sign in with GitHub** and
authorize it to see the `grocerytracker` repo.

**3. Launch the Blueprint**
- Tap **New +** → **Blueprint**.
- Pick the **grocerytracker** repo. Render finds `render.yaml` automatically and
  shows a service called **product-finder**.
- Tap **Apply** / **Create**.

**4. Paste your secrets**
Render will prompt for the values marked secret. Paste:
- `REDDIT_CLIENT_ID` — from your Reddit app
- `REDDIT_CLIENT_SECRET` — from your Reddit app
- `ANTHROPIC_API_KEY` — from console.anthropic.com
- `APP_PASSWORD` — any password you choose (you'll type this to open the site)

**5. Wait for it to build (~3–5 min)**
When it says **Live**, tap the URL at the top (e.g.
`https://product-finder-xxxx.onrender.com`).

**6. Use it**
Your browser asks for a login — leave the username blank (or anything) and enter
your **APP_PASSWORD**. Then search, e.g. *"best heavy-duty extension cord"*.

---

## Good to know

- **Free tier sleeps.** After ~15 minutes idle the app naps; the next visit
  takes ~50 seconds to wake up, then it's quick again.
- **Cost.** Render web service: free. Reddit + image search: free. Claude:
  pay-as-you-go, typically a fraction of a cent per search.
- **A search takes ~15–40s** (it reads many sources, then Claude writes the
  answer). That's normal.
- **Changing trusted sources:** edit `product-finder/sources.yaml` in GitHub
  (you can do this from the GitHub app) and Render auto-redeploys.
- **Rotate a key / change password:** Render dashboard → your service →
  **Environment** → edit the value → save (it redeploys).

## Alternative hosts

The app is a standard Flask + gunicorn service, so Railway, Fly.io, or any
Python host works too. The start command is:

```
gunicorn product_finder.app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 1
```
with `product-finder/` as the root directory and the same environment variables.
