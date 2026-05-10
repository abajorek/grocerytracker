// Andy's saved searches as individual brand-bar chips.
//
// Loads via <script src="/picks.js"></script> (injected by the backend's
// serve_frontend route). Fetches /api/picks once on install, then renders
// one chip per saved search after the user-pinned brands. Tapping a chip
// loads that single saved search via /api/feed with the pick's query +
// price_max + no_pickup, and applies size-hint + brand-prefix filtering
// client-side (mirrors the backend's _pick_query_matches_title and
// _match_size_hints used by /api/picks/feed).
//
// Filter logic is duplicated here on purpose — the round-trip cost of a
// dedicated /api/picks/{i}/feed endpoint isn't worth the extra deploy.

(function () {
  const PICK_PAGE_SIZE = 40;

  const styleEl = document.createElement('style');
  styleEl.textContent = `
    .picks-divider {
      flex-shrink: 0;
      align-self: stretch;
      width: 1px;
      background: var(--hairline);
      margin: 6px 4px;
    }
    .picks-label {
      flex-shrink: 0;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 1.2px;
      text-transform: uppercase;
      color: var(--olive-deep);
      align-self: center;
      padding: 0 4px;
      white-space: nowrap;
    }
    .chip.pick {
      background: transparent;
      color: var(--olive-deep);
      border: 1px solid rgba(108, 117, 89, 0.40);
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .chip.pick.active {
      background: var(--olive);
      color: #fff;
      border-color: var(--olive-deep);
    }
    .chip.pick .pick-meta {
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 0.4px;
      opacity: 0.75;
    }
  `;
  document.head.appendChild(styleEl);

  // -------- filter logic (mirrors backend) --------

  const STOPWORDS = new Set([
    'the','and','for','men','mens','women','womens','with',
    'size','sized','small','medium','large',
    'jacket','coat','shirt','pants','trousers','sweater',
    'henley','down','vest','shorts','bag','gloves','boots','shoes',
    'company','vc','co',
  ]);

  function stripDiacritics(s) {
    return (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '');
  }

  function pickQueryMatchesTitle(query, title) {
    if (!query) return true;
    const titleNorm = stripDiacritics(title || '').toLowerCase();
    const queryNorm = stripDiacritics(query).toLowerCase();
    const tokens = titleNorm.match(/[a-z]{2,}/g) || [];
    const tokenSet = new Set(tokens);
    const qWords = (queryNorm.match(/[a-z]{2,}/g) || []).filter(w => w.length >= 3);
    if (!qWords.length) return true;
    if (!qWords.every(w => tokenSet.has(w))) return false;
    const brandWord = qWords.find(w => !STOPWORDS.has(w)) || qWords[0];
    return tokens.slice(0, 6).includes(brandWord);
  }

  function matchSizeHints(title, hints) {
    if (!hints || !hints.length) return true;
    const titleLower = stripDiacritics(title || '').toLowerCase();
    if (!titleLower) return false;
    const tokens = new Set(titleLower.match(/[a-z0-9][a-z0-9\-/]*/g) || []);
    return hints.some(h => {
      const hl = stripDiacritics(String(h || '')).toLowerCase().trim();
      return hl && tokens.has(hl);
    });
  }

  // -------- helpers --------

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function pickLabel(p) {
    return p.name || p.query || 'Pick';
  }

  // -------- chip rendering --------

  let cachedPicks = [];

  function appendPickChips() {
    const bar = document.getElementById('brandBar');
    if (!bar) return;
    // Wipe stale picks UI (we re-add on every renderBrandBar).
    bar.querySelectorAll('.chip.pick, .picks-divider, .picks-label').forEach(e => e.remove());
    if (!cachedPicks.length) return;

    const divider = document.createElement('div');
    divider.className = 'picks-divider';
    bar.appendChild(divider);

    const label = document.createElement('span');
    label.className = 'picks-label';
    label.textContent = "Andy's";
    bar.appendChild(label);

    const s = window.state;
    cachedPicks.forEach((p, idx) => {
      const c = document.createElement('button');
      const isActive = s && s.mode === 'pick' && s.activePickIndex === idx;
      c.className = 'chip pick' + (isActive ? ' active' : '');
      const meta = p.price_max ? ` <span class="pick-meta">≤$${Math.round(p.price_max)}</span>` : '';
      c.innerHTML = escapeHtml(pickLabel(p)) + meta;
      c.onclick = () => selectPick(idx);
      bar.appendChild(c);
    });
  }

  // -------- pick mode handlers --------

  async function selectPick(index) {
    const s = window.state;
    if (!s) return;
    const pick = cachedPicks[index];
    if (!pick) return;
    s.mode = 'pick';
    s.activePickIndex = index;
    s.activePickData = pick;
    s.activeBrand = null;
    s.page = 1;
    s.items = [];
    s.exhausted = false;
    window.renderBrandBar();

    const sizesNote = (pick.size_hints && pick.size_hints.length)
      ? ` · sizes: ${pick.size_hints.slice(0, 4).join(', ')}`
      : '';
    const priceNote = pick.price_max ? ` · ≤$${Math.round(pick.price_max)}` : '';
    document.getElementById('feed').innerHTML = `
      <div class="card">
        <div class="center-msg">
          <div>
            <h3>${escapeHtml(pickLabel(pick))}</h3>
            <p>${escapeHtml(pick.query)}${escapeHtml(priceNote)}${escapeHtml(sizesNote)}</p>
            <div class="dots"><span></span><span></span><span></span></div>
          </div>
        </div>
      </div>`;
    await window.loadMore();
  }

  async function pickLoadMore() {
    const s = window.state;
    if (s.loading || s.exhausted) return;
    if (s.activePickIndex == null) return;
    const pick = cachedPicks[s.activePickIndex];
    if (!pick) return;
    s.loading = true;
    try {
      const params = new URLSearchParams();
      params.set('q', pick.query);
      params.set('page', String(s.page));
      params.set('page_size', String(PICK_PAGE_SIZE));
      params.set('no_pickup', 'true');
      if (pick.price_max) params.set('price_max', String(pick.price_max));
      const raw = await window.apiGet('/api/feed?' + params.toString());
      s.page += 1;
      const got = Array.isArray(raw) ? raw : [];
      if (got.length === 0) {
        s.exhausted = true;
      } else {
        // Backend already keyword-matched on title; we apply the strict
        // brand-prefix + size-hint filters that distinguish a pick from a
        // generic /api/feed search.
        const label = pickLabel(pick);
        const filtered = got
          .filter(it => pickQueryMatchesTitle(pick.query, it.title))
          .filter(it => matchSizeHints(it.title, pick.size_hints || []))
          .map(it => Object.assign({}, it, { brand: label }));
        if (filtered.length === 0 && got.length < PICK_PAGE_SIZE) {
          // Last page from the upstream + nothing matched our extra filters.
          s.exhausted = true;
        }
        if (filtered.length > 0) {
          s.items.push(...filtered);
        }
      }
      window.renderFeed();
    } catch (e) {
      window.renderError(e);
    } finally {
      s.loading = false;
    }
  }

  // -------- install / wiring --------

  let installed = false;
  function install() {
    if (installed) return;
    if (typeof window.renderBrandBar !== 'function') return;
    if (typeof window.loadMore !== 'function') return;
    if (typeof window.renderFeed !== 'function') return;
    if (!window.state) return;
    installed = true;

    const _renderBrandBar = window.renderBrandBar;
    window.renderBrandBar = function () {
      _renderBrandBar();
      appendPickChips();
    };

    const _loadMore = window.loadMore;
    window.loadMore = async function () {
      const s = window.state;
      if (s && s.mode === 'pick') return pickLoadMore();
      return _loadMore();
    };

    const _renderFeed = window.renderFeed;
    window.renderFeed = function () {
      const s = window.state;
      if (s && s.mode === 'pick' && (!s.items || s.items.length === 0) && s.exhausted) {
        const pick = s.activePickData || {};
        document.getElementById('feed').innerHTML = `
          <div class="card">
            <div class="center-msg">
              <div><h3>Nothing for ${escapeHtml(pickLabel(pick))}</h3>
              <p>No ShopGoodwill listings match this saved search right now (after price + size filters). Try another pick chip.</p></div>
            </div>
          </div>`;
        return;
      }
      return _renderFeed();
    };

    // Pull the picks list once, then re-render the brand bar to show chips.
    window.apiGet('/api/picks').then(picks => {
      cachedPicks = Array.isArray(picks) ? picks : [];
      window.renderBrandBar();
    }).catch(() => { /* swallow — picks chips just won't show */ });
  }

  let attempts = 0;
  const timer = setInterval(() => {
    attempts += 1;
    install();
    if (installed || attempts > 80) clearInterval(timer);
  }, 50);
})();
