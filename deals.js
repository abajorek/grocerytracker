// Deals mode — Claude-scored value scan. Adds a "💎 deals" chip to the
// brand bar; tap triggers /api/deals which returns items ranked by the
// gap between Claude's estimated retail and the current bid. Each card
// in deals mode gets a corner badge showing "+$Δ est. $value".
//
// Loads via <script src="/deals.js"></script> injected by the backend's
// serve_frontend route.
//
// Use case from Andy: see underpriced items ending soon, prioritized
// by largest value gap. Default scan excludes clothing/shoes/apparel
// per his ask; bags, watches, electronics, collectibles all stay in.

(function () {
  const DEFAULT_MAX_PRICE = 100;
  const DEFAULT_SORT = 'delta';
  const DEFAULT_LIMIT = 30;

  const styleEl = document.createElement('style');
  styleEl.textContent = `
    .chip.deals {
      background: transparent;
      color: var(--olive-deep);
      border: 1px dashed rgba(108, 117, 89, 0.45);
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-weight: 600;
    }
    .chip.deals.active {
      background: var(--olive);
      color: #fff;
      border-color: var(--olive-deep);
      border-style: solid;
    }
    .deal-badge {
      position: absolute;
      top: calc(env(safe-area-inset-top, 0px) + 80px);
      right: 14px;
      z-index: 4;
      background: var(--olive);
      color: #fff;
      padding: 12px 16px;
      border-radius: 14px;
      text-align: center;
      box-shadow: 0 6px 18px rgba(28, 28, 26, 0.22);
      min-width: 90px;
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
    }
    .deal-badge.high { background: var(--success-text); }
    .deal-badge.medium { background: var(--olive); }
    .deal-badge.low {
      background: var(--coral-deep);
      color: #fff;
    }
    .deal-badge .delta {
      font-family: var(--display);
      font-variation-settings: 'opsz' 60;
      font-size: 26px;
      font-weight: 700;
      letter-spacing: -0.6px;
      line-height: 1;
    }
    .deal-badge .retail {
      font-size: 11px;
      opacity: 0.85;
      letter-spacing: 0.4px;
      margin-top: 4px;
      text-transform: uppercase;
      font-weight: 600;
    }
    .deal-badge .conf-dot {
      display: inline-block;
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: rgba(255,255,255,0.85);
      margin-right: 4px;
      vertical-align: middle;
    }
  `;
  document.head.appendChild(styleEl);

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function appendDealsChip() {
    const bar = document.getElementById('brandBar');
    if (!bar) return;
    if (bar.querySelector('.chip.deals')) return;
    const s = window.state;
    const chip = document.createElement('button');
    chip.className = 'chip deals' + (s && s.mode === 'deals' ? ' active' : '');
    chip.innerHTML = '💎 deals';
    chip.setAttribute('aria-label', 'Find value deals');
    chip.title = 'Find items where Claude’s retail estimate beats the current bid';
    chip.onclick = enterDealsMode;
    bar.appendChild(chip);
  }

  async function enterDealsMode() {
    const s = window.state;
    if (!s) return;
    s.mode = 'deals';
    s.activeBrand = null;
    s.activeSellerId = '';
    s.activeSellerName = '';
    s.page = 1;
    s.items = [];
    s.exhausted = true;  // /api/deals returns the full ranked list at once
    window.renderBrandBar();
    document.getElementById('feed').innerHTML = `
      <div class="card">
        <div class="center-msg">
          <div>
            <h3>💎 Scanning for deals…</h3>
            <p>Pulling ~40 ending-soon listings, asking Claude what each one's actually worth, then ranking by the value gap. Takes ~10 sec cold, near-instant if cached.</p>
            <div class="dots"><span></span><span></span><span></span></div>
          </div>
        </div>
      </div>`;
    try {
      const params = new URLSearchParams({
        max_price: String(DEFAULT_MAX_PRICE),
        sort: DEFAULT_SORT,
        limit: String(DEFAULT_LIMIT),
        exclude_clothing: 'true',
      });
      const items = await window.apiGet('/api/deals?' + params.toString());
      const got = Array.isArray(items) ? items : [];
      if (got.length === 0) {
        document.getElementById('feed').innerHTML = `
          <div class="card">
            <div class="center-msg">
              <div>
                <h3>No deals right now</h3>
                <p>Claude didn't find anything where the estimated retail beats the current bid. Try again in a bit, or refresh once new listings land.</p>
              </div>
            </div>
          </div>`;
        return;
      }
      s.items = got;
      window.renderFeed();
      // Badges go on AFTER the existing renderFeed runs.
      requestAnimationFrame(injectDealBadges);
    } catch (e) {
      window.renderError(e);
    }
  }

  function injectDealBadges() {
    if (!window.state || window.state.mode !== 'deals') return;
    document.querySelectorAll('.card[data-id]').forEach(card => {
      if (card.querySelector('.deal-badge')) return;
      const id = parseInt(card.dataset.id, 10);
      const item = (window.state.items || []).find(x => x.id === id);
      if (!item || !item.retail_mid || item.retail_mid <= item.current_price) return;
      const delta = Math.round(item.retail_mid - item.current_price);
      const conf = String(item.confidence || 'medium').toLowerCase();
      const retailDisp = Math.round(item.retail_mid);
      const badge = document.createElement('div');
      badge.className = 'deal-badge ' + conf;
      badge.title = (item.product || 'Estimated value') +
                    (item.deal_note ? ' — ' + item.deal_note : '');
      badge.innerHTML =
        '<div class="delta">+$' + delta + '</div>' +
        '<div class="retail"><span class="conf-dot"></span>est. $' + retailDisp + '</div>';
      card.appendChild(badge);
    });
  }

  let installed = false;
  function install() {
    if (installed) return;
    if (typeof window.renderBrandBar !== 'function') return;
    if (typeof window.renderFeed !== 'function') return;
    if (typeof window.apiGet !== 'function') return;
    if (!window.state) return;
    installed = true;

    const _renderBrandBar = window.renderBrandBar;
    window.renderBrandBar = function () {
      _renderBrandBar();
      appendDealsChip();
    };

    const _renderFeed = window.renderFeed;
    window.renderFeed = function () {
      _renderFeed();
      // After each re-render in deals mode, re-apply badges.
      if (window.state && window.state.mode === 'deals') {
        requestAnimationFrame(injectDealBadges);
      }
    };

    window.enterDealsMode = enterDealsMode;
  }

  let attempts = 0;
  const timer = setInterval(() => {
    attempts += 1;
    install();
    if (installed || attempts > 80) clearInterval(timer);
  }, 50);
})();
