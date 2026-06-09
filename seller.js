// Seller filter — "Show all from this seller" CTA in the info drawer,
// plus an active-seller chip in the brand bar (tap to clear).
//
// Loads via <script src="/seller.js"></script> injected by the backend's
// serve_frontend route. Relies on window-exposed helpers from the inline
// app (state, apiGet, openDrawer, renderBrandBar, renderError, renderFeed).
//
// Use case: Andy wins items from a Goodwill chapter and wants to see what
// else they have, either to bundle pickups or to check what they'd ship.

(function () {
  const PAGE_SIZE = 40;

  const styleEl = document.createElement('style');
  styleEl.textContent = `
    .seller-cta {
      width: 100%;
      margin-top: 16px;
      padding: 14px;
      border-radius: 12px;
      border: 1px solid var(--olive-deep);
      background: var(--olive);
      color: #fff;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      font-family: inherit;
      letter-spacing: -0.2px;
    }
    .seller-cta:active { transform: scale(0.98); }
    .seller-cta:disabled {
      background: var(--paper-3);
      color: var(--ink-soft);
      border-color: var(--hairline);
      cursor: not-allowed;
    }
    .chip.seller {
      background: var(--olive);
      color: #fff;
      border: 1px solid var(--olive-deep);
      display: inline-flex;
      align-items: center;
      gap: 6px;
      max-width: 220px;
    }
    .chip.seller .seller-name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      max-width: 160px;
    }
    .chip.seller .seller-x {
      font-weight: 700;
      opacity: 0.8;
      font-size: 12px;
      padding-left: 2px;
    }
    .chip.seller:active { opacity: 0.85; }
  `;
  document.head.appendChild(styleEl);

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function appendSellerCTA(item) {
    if (!item || !item.seller_id) return;
    const drawerContent = document.getElementById('drawerContent');
    if (!drawerContent) return;
    if (drawerContent.querySelector('.seller-cta')) return;
    const sellerName = item.seller_name || item.location || 'this seller';
    const btn = document.createElement('button');
    btn.className = 'seller-cta';
    btn.textContent = `🏪 Show all from ${sellerName}`;
    btn.onclick = (e) => {
      e.stopPropagation();
      selectSeller(item.seller_id, sellerName);
    };
    drawerContent.appendChild(btn);
  }

  async function selectSeller(sellerId, sellerName) {
    const s = window.state;
    if (!s || !sellerId) return;
    if (typeof window.closeDrawer === 'function') window.closeDrawer();
    s.mode = 'feed';
    s.activeBrand = null;
    s.activeSellerId = String(sellerId);
    s.activeSellerName = sellerName || '';
    s.page = 1;
    s.items = [];
    s.exhausted = false;
    if (typeof window.renderBrandBar === 'function') window.renderBrandBar();
    document.getElementById('feed').innerHTML = `
      <div class="card">
        <div class="center-msg">
          <div>
            <h3>${escapeHtml(sellerName || 'Seller')}</h3>
            <p>Loading everything they have listed right now.</p>
            <div class="dots"><span></span><span></span><span></span></div>
          </div>
        </div>
      </div>`;
    await window.loadMore();
  }

  function clearSeller() {
    const s = window.state;
    if (!s) return;
    s.activeSellerId = '';
    s.activeSellerName = '';
    if (typeof window.renderBrandBar === 'function') window.renderBrandBar();
    document.getElementById('feed').innerHTML = `
      <div class="card">
        <div class="center-msg">
          <div>
            <h3>Pick a brand</h3>
            <p>Tap a chip up top, or hit ⚙ to search anything across ShopGoodwill.</p>
          </div>
        </div>
      </div>`;
  }

  function appendSellerChip() {
    const bar = document.getElementById('brandBar');
    if (!bar) return;
    bar.querySelectorAll('.chip.seller').forEach(e => e.remove());
    const s = window.state;
    if (!s || !s.activeSellerId) return;
    const chip = document.createElement('button');
    chip.className = 'chip seller';
    const label = s.activeSellerName || `Seller ${s.activeSellerId}`;
    chip.innerHTML = '🏪 <span class="seller-name">' + escapeHtml(label) +
                     '</span><span class="seller-x">×</span>';
    chip.setAttribute('aria-label', 'Clear seller filter');
    chip.title = 'Tap to clear seller filter';
    chip.onclick = clearSeller;
    bar.appendChild(chip);
  }

  async function sellerLoadMore() {
    const s = window.state;
    if (s.loading || s.exhausted) return;
    s.loading = true;
    try {
      const params = new URLSearchParams();
      params.set('seller_id', String(s.activeSellerId));
      params.set('page', String(s.page));
      params.set('page_size', String(PAGE_SIZE));
      const items = await window.apiGet('/api/feed?' + params.toString());
      const got = Array.isArray(items) ? items : [];
      if (!got.length) {
        s.exhausted = true;
      } else {
        s.items.push(...got);
        s.page += 1;
      }
      window.renderFeed();
    } catch (e) {
      window.renderError(e);
    } finally {
      s.loading = false;
    }
  }

  let installed = false;
  function install() {
    if (installed) return;
    if (typeof window.openDrawer !== 'function') return;
    if (typeof window.loadMore !== 'function') return;
    if (typeof window.renderBrandBar !== 'function') return;
    if (!window.state) return;
    installed = true;

    const _openDrawer = window.openDrawer;
    window.openDrawer = function (item) {
      _openDrawer(item);
      try { appendSellerCTA(item); } catch (e) { console.warn('seller cta failed', e); }
    };

    const _renderBrandBar = window.renderBrandBar;
    window.renderBrandBar = function () {
      _renderBrandBar();
      appendSellerChip();
    };

    const _loadMore = window.loadMore;
    window.loadMore = async function () {
      const s = window.state;
      if (s && s.activeSellerId) return sellerLoadMore();
      return _loadMore();
    };

    // Expose for /info drawer's inline onclick wiring if anything needs it later.
    window.selectSeller = selectSeller;
    window.clearSeller = clearSeller;
  }

  let attempts = 0;
  const timer = setInterval(() => {
    attempts += 1;
    install();
    if (installed || attempts > 80) clearInterval(timer);
  }, 50);
})();
