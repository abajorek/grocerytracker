// Snipe extension — adds a "Snipe at end" button to the bid sheet
// alongside Place bid. Schedules a backend snipe via POST /api/snipes
// that fires LEAD_SECONDS before the auction's end_time.
//
// Loads via <script src="/snipe.js"></script> injected by the backend's
// serve_frontend route. Relies on window-exposed helpers from the inline
// app (apiSend, setBidNotice, openBidSheet). Reads the current bid
// amount from the modal's DOM (selected preset or custom input) so it
// stays in sync with the Place-bid flow without poking at internal state.

(function () {
  const LEAD_SECONDS = 8;
  // Don't show the snipe button if the auction ends sooner than this —
  // there's no realistic time to schedule + fire.
  const MIN_REMAINING_FOR_SNIPE = LEAD_SECONDS + 10;

  const styleEl = document.createElement('style');
  styleEl.textContent = `
    .btn-snipe {
      padding: 12px 16px;
      border-radius: 10px;
      border: 1px solid var(--olive-deep);
      background: var(--olive);
      color: #fff;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      font-family: inherit;
      transition: background 0.15s ease, transform 0.1s ease;
    }
    .btn-snipe:active { transform: scale(0.97); }
    .btn-snipe:disabled {
      background: var(--paper-3);
      color: var(--ink-soft);
      border-color: var(--hairline);
      cursor: not-allowed;
    }
    .snipe-hint {
      grid-column: 1 / -1;
      font-size: 11px;
      color: var(--ink-soft);
      letter-spacing: 0.3px;
      margin-top: 8px;
      text-align: right;
    }
  `;
  document.head.appendChild(styleEl);

  function readCurrentBidAmount() {
    const customRaw = document.getElementById('bidCustom');
    const customVal = customRaw ? parseFloat(customRaw.value) : NaN;
    if (Number.isFinite(customVal) && customVal > 0) return customVal;
    const sel = document.querySelector('.bid-preset.selected');
    if (sel) {
      const v = parseFloat(sel.dataset.amount);
      if (Number.isFinite(v) && v > 0) return v;
    }
    return null;
  }

  function fmtClockOffset(secondsFromNow) {
    const target = new Date(Date.now() + secondsFromNow * 1000);
    return target.toLocaleTimeString([], {
      hour: 'numeric', minute: '2-digit', second: '2-digit',
    });
  }

  function injectSnipeButton(item) {
    const modal = document.querySelector('#bidModalBg .modal');
    if (!modal) return;
    const actions = modal.querySelector('.modal-actions');
    if (!actions) return;
    actions.querySelectorAll('.btn-snipe, .snipe-hint').forEach(e => e.remove());

    if (!item || !item.end_time || item.is_closed) return;
    if (!Number.isFinite(item.seconds_left) || item.seconds_left < MIN_REMAINING_FOR_SNIPE) return;

    const btn = document.createElement('button');
    btn.className = 'btn-snipe';
    btn.type = 'button';
    btn.textContent = 'Snipe at end';
    btn.title = `Schedule a bid to fire ${LEAD_SECONDS}s before this auction closes`;
    const primary = actions.querySelector('.btn-primary');
    if (primary) {
      actions.insertBefore(btn, primary);
    } else {
      actions.appendChild(btn);
    }

    const hint = document.createElement('div');
    hint.className = 'snipe-hint';
    hint.textContent = `Snipe fires ${LEAD_SECONDS}s before close · about ${fmtClockOffset(item.seconds_left - LEAD_SECONDS)}`;
    actions.appendChild(hint);

    btn.onclick = () => scheduleSnipe(item, btn, hint);
  }

  async function scheduleSnipe(item, btn, hint) {
    const amount = readCurrentBidAmount();
    if (!amount) {
      if (typeof window.setBidNotice === 'function') {
        window.setBidNotice('Pick an amount first (preset or custom).');
      }
      return;
    }
    btn.disabled = true;
    btn.textContent = 'Scheduling…';
    try {
      const snipe = await window.apiSend('/api/snipes', 'POST', {
        item_id: item.id,
        amount: amount,
        end_time: item.end_time,
        lead_seconds: LEAD_SECONDS,
        title: item.title,
        image_url: item.image_url,
      });
      btn.textContent = 'Scheduled ✓';
      const fmtPrice = window.fmtPrice || (n => `$${(Number(n) || 0).toFixed(2)}`);
      const fireLocal = snipe && snipe.fire_at
        ? new Date(snipe.fire_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })
        : '';
      const noteFn = window.setBidNotice;
      if (typeof noteFn === 'function') {
        noteFn(
          `Snipe of ${fmtPrice(amount)} scheduled${fireLocal ? ` · fires ${fireLocal}` : ''}.`,
          'success',
        );
      }
      if (hint) hint.remove();
      setTimeout(() => {
        const modalBg = document.getElementById('bidModalBg');
        if (modalBg) modalBg.classList.remove('open');
      }, 1500);
    } catch (e) {
      btn.disabled = false;
      btn.textContent = 'Snipe at end';
      const msg = (e && e.message) ? e.message : String(e);
      if (typeof window.setBidNotice === 'function') {
        window.setBidNotice('Snipe failed: ' + msg);
      }
    }
  }

  let installed = false;
  function install() {
    if (installed) return;
    if (typeof window.openBidSheet !== 'function') return;
    if (typeof window.apiSend !== 'function') return;
    installed = true;

    const _open = window.openBidSheet;
    window.openBidSheet = function (item) {
      _open(item);
      try { injectSnipeButton(item); } catch (e) { console.warn('snipe inject failed', e); }
    };
  }

  let attempts = 0;
  const timer = setInterval(() => {
    attempts += 1;
    install();
    if (installed || attempts > 80) clearInterval(timer);
  }, 50);
})();
