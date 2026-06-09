// Deals mode — Claude-scored value scan. Adds a "💎 deals" chip to the
// brand bar; tap triggers /api/deals which returns items ranked by the
// gap between Claude's estimated retail and the current bid. Each card
// in deals mode gets a corner badge showing "+$Δ est. $value".
//
// Tap-on-active behavior: tap the chip to enter deals mode and scan;
// tap the (now active) chip again to open the tune modal — max price,
// min price, hours-left filter, sort mode, search term, clothing on/off.
// Tune values persist via localStorage between sessions.
//
// Loads via <script src="/deals.js"></script> injected by the backend's
// serve_frontend route.

(function () {
  const DEALS_FILTER_KEY = 'gh_deals_filters_v1';

  const dealsFilters = {
    query: '',
    max_price: 100,
    min_price: 5,
    hours_left_max: 0,
    exclude_clothing: true,
    sort: 'delta',
    limit: 30,
  };

  try {
    const raw = localStorage.getItem(DEALS_FILTER_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object') Object.assign(dealsFilters, parsed);
    }
  } catch {}

  function persistDealsFilters() {
    try { localStorage.setItem(DEALS_FILTER_KEY, JSON.stringify(dealsFilters)); } catch {}
  }

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
    .deals-form-row { margin-bottom: 14px; }
    .deals-form-row > .label {
      display: block;
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: var(--ink-soft);
      margin-bottom: 6px;
    }
    .deals-form-row input[type=text],
    .deals-form-row input[type=number],
    .deals-form-row select {
      width: 100%;
      padding: 11px 12px;
      border-radius: 9px;
      border: 1px solid var(--hairline);
      background: var(--paper);
      color: var(--ink);
      font-size: 15px;
      font-family: inherit;
    }
    .deals-form-row input:focus,
    .deals-form-row select:focus {
      outline: 1.5px solid var(--olive);
      border-color: transparent;
    }
    .deals-form-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }
    .deals-form-toggle {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px 14px;
      background: var(--paper-2);
      border-radius: 10px;
      margin-bottom: 14px;
      font-size: 14px;
      color: var(--ink);
      cursor: pointer;
      font-family: inherit;
    }
    .deals-form-toggle input[type=checkbox] {
      width: 18px; height: 18px;
      accent-color: var(--olive);
      flex-shrink: 0;
      margin: 0;
    }
    .deals-form-hint {
      font-size: 11px;
      color: var(--ink-soft);
      margin-top: -8px;
      margin-bottom: 14px;
      line-height: 1.4;
    }
    .deals-results-bar {
      position: fixed;
      top: 0; left: 0; right: 0;
      z-index: 11;
      pointer-events: none;
    }
    .deals-results-bar .pill {
      pointer-events: auto;
      display: inline-block;
      margin: max(env(safe-area-inset-top, 8px) + 56px, 64px) auto 0 50%;
      transform: translateX(-50%);
      background: rgba(28,28,26,0.85);
      color: #fff;
      padding: 7px 14px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.3px;
      cursor: pointer;
      backdrop-filter: blur(10px);
      -webkit-backdrop-filter: blur(10px);
    }
    .deals-results-bar .pill:active { transform: translateX(-50%) scale(0.96); }
  `;
  document.head.appendChild(styleEl);

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // ----- tune modal -----

  let modalBuilt = false;
  function buildTuneModal() {
    if (modalBuilt) return;
    modalBuilt = true;
    const bg = document.createElement('div');
    bg.className = 'modal-bg';
    bg.id = 'dealsTuneModalBg';
    bg.innerHTML = `
      <div class="modal">
        <h3>💎 Tune deal scan</h3>
        <div class="modal-sub">Adjust what to scan and how to rank. Saved between visits.</div>

        <div class="deals-form-row">
          <span class="label">Search (optional)</span>
          <input id="dealsTuneQuery" type="text" placeholder="e.g. Coach, vintage, watch — blank scans everything" autocomplete="off">
        </div>

        <div class="deals-form-grid">
          <div class="deals-form-row">
            <span class="label">Min price</span>
            <input id="dealsTuneMinPrice" type="number" min="0" max="1000" inputmode="decimal">
          </div>
          <div class="deals-form-row">
            <span class="label">Max price</span>
            <input id="dealsTuneMaxPrice" type="number" min="1" max="1000" inputmode="decimal">
          </div>
        </div>

        <div class="deals-form-row">
          <span class="label">Hours left max (0 = no limit)</span>
          <input id="dealsTuneHoursLeft" type="number" min="0" max="168" inputmode="numeric">
        </div>

        <div class="deals-form-row">
          <span class="label">Sort by</span>
          <select id="dealsTuneSort">
            <option value="delta">Largest dollar delta first</option>
            <option value="weighted">Best deal ending soon (delta × urgency)</option>
            <option value="ending_soon">Ending soonest (delta tiebreaker)</option>
          </select>
        </div>

        <label class="deals-form-toggle">
          <input id="dealsTuneExcludeClothing" type="checkbox">
          <span>Exclude clothing & shoes</span>
        </label>

        <div class="deals-form-hint">
          Cold scan with these settings hits Claude once per candidate (~$0.001 each). Results cache for 24h, so repeat scans are essentially free.
        </div>

        <div class="modal-actions">
          <button class="btn-secondary" id="dealsTuneCancel">Cancel</button>
          <button class="btn-primary" id="dealsTuneApply">Scan</button>
        </div>
      </div>`;
    document.body.appendChild(bg);
    bg.addEventListener('click', (e) => {
      if (e.target.id === 'dealsTuneModalBg') closeTuneModal();
    });
    document.getElementById('dealsTuneCancel').onclick = closeTuneModal;
    document.getElementById('dealsTuneApply').onclick = applyTuneAndScan;
  }

  function openTuneModal() {
    buildTuneModal();
    document.getElementById('dealsTuneQuery').value = dealsFilters.query || '';
    document.getElementById('dealsTuneMinPrice').value = dealsFilters.min_price;
    document.getElementById('dealsTuneMaxPrice').value = dealsFilters.max_price;
    document.getElementById('dealsTuneHoursLeft').value = dealsFilters.hours_left_max;
    document.getElementById('dealsTuneSort').value = dealsFilters.sort;
    document.getElementById('dealsTuneExcludeClothing').checked = !!dealsFilters.exclude_clothing;
    document.getElementById('dealsTuneModalBg').classList.add('open');
    setTimeout(() => document.getElementById('dealsTuneQuery').focus(), 60);
  }

  function closeTuneModal() {
    const bg = document.getElementById('dealsTuneModalBg');
    if (bg) bg.classList.remove('open');
  }

  async function applyTuneAndScan() {
    dealsFilters.query = document.getElementById('dealsTuneQuery').value.trim();
    const minP = parseFloat(document.getElementById('dealsTuneMinPrice').value);
    const maxP = parseFloat(document.getElementById('dealsTuneMaxPrice').value);
    const hrs = parseInt(document.getElementById('dealsTuneHoursLeft').value, 10);
    dealsFilters.min_price = Number.isFinite(minP) ? Math.max(0, Math.min(1000, minP)) : 5;
    dealsFilters.max_price = Number.isFinite(maxP) ? Math.max(1, Math.min(1000, maxP)) : 100;
    if (dealsFilters.max_price <= dealsFilters.min_price) {
      dealsFilters.max_price = dealsFilters.min_price + 1;
    }
    dealsFilters.hours_left_max = Number.isFinite(hrs) ? Math.max(0, Math.min(168, hrs)) : 0;
    dealsFilters.sort = document.getElementById('dealsTuneSort').value || 'delta';
    dealsFilters.exclude_clothing = document.getElementById('dealsTuneExcludeClothing').checked;
    persistDealsFilters();
    closeTuneModal();
    await enterDealsMode();
  }

  // ----- chip + mode entry -----

  function appendDealsChip() {
    const bar = document.getElementById('brandBar');
    if (!bar) return;
    if (bar.querySelector('.chip.deals')) return;
    const s = window.state;
    const chip = document.createElement('button');
    const isActive = s && s.mode === 'deals';
    chip.className = 'chip deals' + (isActive ? ' active' : '');
    chip.innerHTML = '💎 deals';
    chip.setAttribute('aria-label', isActive ? 'Tune deal scan' : 'Find value deals');
    chip.title = isActive
      ? 'Tap to tune scan settings'
      : "Find items where Claude’s retail estimate beats the current bid";
    chip.onclick = () => {
      const cur = window.state;
      if (cur && cur.mode === 'deals') {
        openTuneModal();
      } else {
        enterDealsMode();
      }
    };
    bar.appendChild(chip);
  }

  function summaryString() {
    const f = dealsFilters;
    const parts = [];
    if (f.query) parts.push('"' + f.query + '"');
    parts.push('≤$' + f.max_price);
    if (f.hours_left_max > 0) parts.push('≤' + f.hours_left_max + 'h');
    if (!f.exclude_clothing) parts.push('+clothes');
    const sortLabel = f.sort === 'weighted' ? 'urgent×Δ' :
                      f.sort === 'ending_soon' ? 'soon' : 'Δ';
    parts.push(sortLabel);
    return parts.join(' · ');
  }

  function injectResultsBar() {
    if (!window.state || window.state.mode !== 'deals') return;
    document.querySelectorAll('.deals-results-bar').forEach(e => e.remove());
    if (!window.state.items || window.state.items.length === 0) return;
    const bar = document.createElement('div');
    bar.className = 'deals-results-bar';
    bar.innerHTML = '<button class="pill">⚙ ' + escapeHtml(summaryString()) +
                    ' · ' + window.state.items.length + ' deals</button>';
    bar.querySelector('.pill').onclick = openTuneModal;
    document.body.appendChild(bar);
  }

  function clearResultsBar() {
    document.querySelectorAll('.deals-results-bar').forEach(e => e.remove());
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
    s.exhausted = true;
    clearResultsBar();
    window.renderBrandBar();
    document.getElementById('feed').innerHTML = `
      <div class="card">
        <div class="center-msg">
          <div>
            <h3>💎 Scanning for deals…</h3>
            <p>Settings: ${escapeHtml(summaryString())}. Cold scan ~10 sec; cached results are instant.</p>
            <div class="dots"><span></span><span></span><span></span></div>
          </div>
        </div>
      </div>`;
    try {
      const params = new URLSearchParams();
      if (dealsFilters.query) params.set('query', dealsFilters.query);
      params.set('max_price', String(dealsFilters.max_price));
      params.set('min_price', String(dealsFilters.min_price));
      if (dealsFilters.hours_left_max > 0) {
        params.set('hours_left_max', String(dealsFilters.hours_left_max));
      }
      params.set('exclude_clothing', dealsFilters.exclude_clothing ? 'true' : 'false');
      params.set('sort', dealsFilters.sort);
      params.set('limit', String(dealsFilters.limit));
      const items = await window.apiGet('/api/deals?' + params.toString());
      const got = Array.isArray(items) ? items : [];
      if (got.length === 0) {
        document.getElementById('feed').innerHTML = `
          <div class="card">
            <div class="center-msg">
              <div>
                <h3>No deals matched</h3>
                <p>With settings ${escapeHtml(summaryString())}, Claude didn't find anything where the estimated retail beats the current bid. Try widening max price, removing the time filter, or including clothing.</p>
                <button class="ghint" onclick="window.openDealsTune()">⚙ Tune scan</button>
              </div>
            </div>
          </div>`;
        return;
      }
      s.items = got;
      window.renderFeed();
      requestAnimationFrame(() => {
        injectDealBadges();
        injectResultsBar();
      });
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
      if (window.state && window.state.mode === 'deals') {
        requestAnimationFrame(() => {
          injectDealBadges();
          injectResultsBar();
        });
      } else {
        clearResultsBar();
      }
    };

    window.enterDealsMode = enterDealsMode;
    window.openDealsTune = openTuneModal;
  }

  let attempts = 0;
  const timer = setInterval(() => {
    attempts += 1;
    install();
    if (installed || attempts > 80) clearInterval(timer);
  }, 50);
})();
