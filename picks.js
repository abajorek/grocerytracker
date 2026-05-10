// Andy's Picks — extends the inline app to add a "★ Andy's" mode chip
// that fans out all of Andy's saved searches via /api/picks/feed.
//
// Loads via a <script src="/picks.js"></script> tag injected by the
// backend's serve_frontend route. The inline app exposes `state` on
// window via a tiny shim at the bottom of its <script>; this file then
// monkey-patches renderBrandBar / loadMore.

(function () {
  const css = `
    .chip.picks {
      background: transparent;
      color: var(--ink-soft);
      border: 1px dashed rgba(28,28,26,0.25);
      display: inline-flex; align-items: center; gap: 6px;
      padding: 8px 14px;
    }
    .chip.picks.active {
      background: var(--olive);
      color: #fff;
      border-color: var(--olive-deep);
      border-style: solid;
    }
  `;
  const styleEl = document.createElement('style');
  styleEl.textContent = css;
  document.head.appendChild(styleEl);

  function appendPicksChip() {
    const bar = document.getElementById('brandBar');
    if (!bar) return;
    if (bar.querySelector('.chip.picks')) return;
    const s = window.state;
    const picks = document.createElement('button');
    picks.className = 'chip picks' + (s && s.mode === 'picks' ? ' active' : '');
    picks.innerHTML = "★ Andy's";
    picks.setAttribute('aria-label', "Andy's Picks");
    picks.onclick = window.showPicks;
    bar.appendChild(picks);
  }

  let installed = false;
  function install() {
    if (installed) return;
    if (typeof window.renderBrandBar !== 'function') return;
    if (typeof window.loadMore !== 'function') return;
    if (!window.state) return;
    installed = true;

    const _renderBrandBar = window.renderBrandBar;
    window.renderBrandBar = function () {
      _renderBrandBar();
      appendPicksChip();
    };

    const _loadMore = window.loadMore;
    window.loadMore = async function () {
      const s = window.state;
      if (s && s.mode === 'picks') return picksLoadMore();
      return _loadMore();
    };

    // Wrap renderFeed so the empty-state in picks mode says something useful.
    const _renderFeed = window.renderFeed;
    if (typeof _renderFeed === 'function') {
      window.renderFeed = function () {
        const s = window.state;
        if (s && s.mode === 'picks' && (!s.items || s.items.length === 0) && s.exhausted) {
          document.getElementById('feed').innerHTML = `
            <div class="card">
              <div class="center-msg">
                <div><h3>No picks today</h3>
                <p>None of Andy's saved searches turned up anything on ShopGoodwill that matches the size hints.</p></div>
              </div>
            </div>`;
          return;
        }
        return _renderFeed();
      };
    }

    // Re-render so the chip appears immediately.
    window.renderBrandBar();
  }

  async function picksLoadMore() {
    const s = window.state;
    if (s.loading || s.exhausted) return;
    s.loading = true;
    try {
      const items = await window.apiGet(
        `/api/picks/feed?page=${s.page}&picks_per_page=12`
      );
      if (!items.length) s.exhausted = true;
      s.items.push(...items);
      s.page += 1;
      window.renderFeed();
    } catch (e) {
      window.renderError(e);
    } finally {
      s.loading = false;
    }
  }

  window.showPicks = async function showPicks() {
    const s = window.state;
    if (!s) return;
    s.mode = 'picks';
    s.activeBrand = null;
    s.page = 1;
    s.items = [];
    s.exhausted = false;
    window.renderBrandBar();
    document.getElementById('feed').innerHTML = `
      <div class="card">
        <div class="center-msg">
          <div>
            <h3>Andy's Picks</h3>
            <p>Running 50+ saved searches across ShopGoodwill in parallel. First batch is loading — flick up for more as they come in.</p>
            <div class="dots"><span></span><span></span><span></span></div>
          </div>
        </div>
      </div>`;
    await window.loadMore();
  };

  // The inline app declares state with `const`, so it isn't on window.
  // Poll briefly until the inline app exposes it (we ship a tiny shim
  // alongside this file via the backend that does `window.state = state`),
  // then install our patches.
  let attempts = 0;
  const timer = setInterval(() => {
    attempts += 1;
    install();
    if (installed || attempts > 80) clearInterval(timer);
  }, 50);
})();
