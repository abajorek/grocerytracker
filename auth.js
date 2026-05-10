// In-app ShopGoodwill sign-in. Adds a "🔐 sign in" chip to the brand
// bar (becomes "✓ name" when logged in, tap to log out) and a small
// login modal. Posts credentials to /api/login on the backend, which
// forwards them to ShopGoodwill once and stores the returned JWT.
//
// Loads via <script src="/auth.js"></script> injected by the backend's
// serve_frontend route. Relies on window-exposed helpers from the
// inline app (apiGet, apiSend, renderBrandBar).

(function () {
  let auth = { authenticated: false, username: '', source: 'none' };

  // --- CSS ---
  const styleEl = document.createElement('style');
  styleEl.textContent = `
    .chip.auth {
      background: transparent;
      color: var(--ink-soft);
      border: 1px dashed rgba(28,28,26,0.25);
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-weight: 600;
    }
    .chip.auth.signed-in {
      background: var(--olive);
      color: #fff;
      border-color: var(--olive-deep);
      border-style: solid;
    }
    .chip.auth .auth-name {
      max-width: 110px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .auth-form-row { margin-bottom: 12px; }
    .auth-form-row label {
      display: block;
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: var(--ink-soft);
      margin-bottom: 6px;
    }
    .auth-form-row input {
      margin-bottom: 0 !important;
    }
    .auth-warning {
      font-size: 11px;
      color: var(--ink-soft);
      line-height: 1.4;
      margin-top: 4px;
      padding: 8px 10px;
      background: var(--paper-2);
      border-radius: 8px;
      border: 1px solid var(--hairline);
    }
  `;
  document.head.appendChild(styleEl);

  // --- modal markup ---
  const modalBg = document.createElement('div');
  modalBg.className = 'modal-bg';
  modalBg.id = 'authModalBg';
  modalBg.innerHTML = `
    <div class="modal">
      <h3>Sign in to ShopGoodwill</h3>
      <div class="modal-sub">Bids and snipes will run on this account until you sign out.</div>
      <div class="auth-form-row">
        <label for="authUsername">Email</label>
        <input id="authUsername" type="email" inputmode="email" autocomplete="username"
               autocapitalize="off" autocorrect="off" spellcheck="false" placeholder="">
      </div>
      <div class="auth-form-row">
        <label for="authPassword">Password</label>
        <input id="authPassword" type="password" autocomplete="current-password" placeholder="">
      </div>
      <div class="bid-notice" id="authNotice"></div>
      <div class="auth-warning">
        Your password is sent once over HTTPS to your Render server, then to
        ShopGoodwill. Only the resulting session token is stored — never the password.
      </div>
      <div class="modal-actions" style="margin-top:14px;">
        <button class="btn-secondary" id="authCancel">Cancel</button>
        <button class="btn-primary" id="authSubmit">Sign in</button>
      </div>
    </div>
  `;
  document.body.appendChild(modalBg);

  modalBg.addEventListener('click', (e) => {
    if (e.target.id === 'authModalBg') closeAuthModal();
  });
  document.getElementById('authCancel').onclick = closeAuthModal;
  document.getElementById('authSubmit').onclick = doLogin;
  // Submit on Enter in the password field
  document.getElementById('authPassword').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') doLogin();
  });

  function setAuthNotice(text, kind) {
    const el = document.getElementById('authNotice');
    el.textContent = text || '';
    el.classList.remove('show', 'success');
    if (text) {
      el.classList.add('show');
      if (kind === 'success') el.classList.add('success');
    }
  }

  function openAuthModal() {
    if (auth.authenticated) {
      const who = auth.username || 'this account';
      if (confirm(`Sign out of ${who}? Bids and snipes will fail until you sign back in.`)) {
        doLogout();
      }
      return;
    }
    document.getElementById('authUsername').value = '';
    document.getElementById('authPassword').value = '';
    setAuthNotice('');
    modalBg.classList.add('open');
    setTimeout(() => document.getElementById('authUsername').focus(), 60);
  }

  function closeAuthModal() {
    modalBg.classList.remove('open');
    document.getElementById('authPassword').value = '';
  }

  async function doLogin() {
    const username = document.getElementById('authUsername').value.trim();
    const password = document.getElementById('authPassword').value;
    if (!username || !password) {
      setAuthNotice('Email and password required.');
      return;
    }
    const submit = document.getElementById('authSubmit');
    submit.disabled = true;
    submit.textContent = 'Signing in…';
    setAuthNotice('');
    try {
      const r = await window.apiSend('/api/login', 'POST', {
        username, password, remember: true,
      });
      auth = {
        authenticated: true,
        username: r.username || username,
        source: 'session',
      };
      submit.textContent = 'Signed in ✓';
      setAuthNotice('Signed in successfully.', 'success');
      if (typeof window.renderBrandBar === 'function') window.renderBrandBar();
      setTimeout(() => {
        closeAuthModal();
        submit.disabled = false;
        submit.textContent = 'Sign in';
      }, 900);
    } catch (e) {
      submit.disabled = false;
      submit.textContent = 'Sign in';
      const msg = (e && e.message) ? e.message : String(e);
      setAuthNotice('Failed: ' + msg);
    }
  }

  async function doLogout() {
    try { await window.apiSend('/api/logout', 'POST', {}); } catch {}
    auth = { authenticated: false, username: '', source: 'none' };
    if (typeof window.renderBrandBar === 'function') window.renderBrandBar();
  }

  async function refreshAuthStatus() {
    try {
      const r = await window.apiGet('/api/auth/status');
      auth = {
        authenticated: !!r.authenticated,
        username: r.username || '',
        source: r.source || 'none',
      };
    } catch {
      auth = { authenticated: false, username: '', source: 'none' };
    }
    if (typeof window.renderBrandBar === 'function') window.renderBrandBar();
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function appendAuthChip() {
    const bar = document.getElementById('brandBar');
    if (!bar) return;
    if (bar.querySelector('.chip.auth')) return;
    const chip = document.createElement('button');
    if (auth.authenticated) {
      chip.className = 'chip auth signed-in';
      const label = auth.username || 'session';
      chip.innerHTML = '✓ <span class="auth-name">' + escapeHtml(label) + '</span>';
      chip.setAttribute('aria-label', 'Sign out');
      chip.title = 'Tap to sign out';
    } else {
      chip.className = 'chip auth';
      chip.innerHTML = '🔐 sign in';
      chip.setAttribute('aria-label', 'Sign in to ShopGoodwill');
      chip.title = 'Tap to sign in to ShopGoodwill';
    }
    chip.onclick = openAuthModal;
    bar.appendChild(chip);
  }

  let installed = false;
  function install() {
    if (installed) return;
    if (typeof window.renderBrandBar !== 'function') return;
    if (typeof window.apiGet !== 'function' || typeof window.apiSend !== 'function') return;
    installed = true;

    const _renderBrandBar = window.renderBrandBar;
    window.renderBrandBar = function () {
      _renderBrandBar();
      appendAuthChip();
    };

    refreshAuthStatus();
  }

  let attempts = 0;
  const timer = setInterval(() => {
    attempts += 1;
    install();
    if (installed || attempts > 80) clearInterval(timer);
  }, 50);
})();
