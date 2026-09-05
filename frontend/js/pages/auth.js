/* Accounts: signup / login / forgot-password (Phase 16).
 *
 * The session token is a bearer token from POST /auth/login, kept in
 * localStorage so a reload doesn't sign the person out. Nothing here
 * stores health, demographic, or heat-risk data -- see vulnerability.js /
 * dashboard.js for that. This page only talks to the /auth/* endpoints. */
(function () {
  const KEY_TOKEN = 'hs_session_token';
  const KEY_EMAIL = 'hs_session_email';
  const KEY_EXPIRES = 'hs_session_expires';

  function safeGet(key) {
    try { return localStorage.getItem(key); } catch { return null; }
  }
  function safeSet(key, value) {
    try { localStorage.setItem(key, value); } catch { /* private mode etc. */ }
  }
  function safeRemove(key) {
    try { localStorage.removeItem(key); } catch { /* ignore */ }
  }

  function save(token, email, expiresAt) {
    safeSet(KEY_TOKEN, token);
    safeSet(KEY_EMAIL, email);
    safeSet(KEY_EXPIRES, String(expiresAt));
  }
  function clear() {
    safeRemove(KEY_TOKEN); safeRemove(KEY_EMAIL); safeRemove(KEY_EXPIRES);
  }
  function token() { return safeGet(KEY_TOKEN); }
  function email() { return safeGet(KEY_EMAIL); }
  function isLoggedIn() {
    const t = token();
    const exp = Number(safeGet(KEY_EXPIRES) || 0);
    return !!t && exp * 1000 > Date.now();
  }

  // Read by app.js to paint the header status button; not a page itself.
  window.HS_AUTH = { save, clear, token, email, isLoggedIn };
})();

(function () {
  const API = window.HS_API, UI = window.HS_UI, AUTH = window.HS_AUTH;
  const P = (window.HS_PAGES = window.HS_PAGES || {});

  const QUESTION_COUNT = 2; // mirrors the backend default; the page still
                            // reads the real count from GET /auth/security-questions

  function loginForm() {
    return `
      <label class="fld"><span>Email</span>
        <input class="field" type="email" name="email" autocomplete="email" required></label>
      <label class="fld" style="margin-top:9px"><span>Password</span>
        <input class="field" type="password" name="password" autocomplete="current-password" required></label>
      <button class="btn" id="doLogin" style="margin-top:13px">Log in</button>
      <div style="margin-top:10px;font-size:12px">
        <a href="#" data-switch="forgot">Forgot password?</a></div>`;
  }

  function signupForm(questions) {
    const pick = questions.slice(0, Math.max(QUESTION_COUNT, 2));
    return `
      <label class="fld"><span>Email</span>
        <input class="field" type="email" name="email" autocomplete="email" required></label>
      <label class="fld" style="margin-top:9px"><span>Password</span>
        <input class="field" type="password" name="password" autocomplete="new-password" required></label>
      <em style="font-size:10.5px;color:var(--muted)">At least 8 characters.</em>
      <div style="margin-top:13px;font-size:12px;color:var(--muted)">
        <b>Security questions</b> -- used only to reset a forgotten password.</div>
      ${pick.map((q, i) => `
        <label class="fld" style="margin-top:9px">
          <span>${UI.esc(q)}</span>
          <input class="field" type="text" name="answer_${i}" data-qidx="${questions.indexOf(q)}" required>
        </label>`).join('')}
      <button class="btn" id="doSignup" style="margin-top:13px">Create account</button>`;
  }

  function forgotForm(questions) {
    const pick = questions.slice(0, Math.max(QUESTION_COUNT, 2));
    return `
      <label class="fld"><span>Email</span>
        <input class="field" type="email" name="email" autocomplete="email" required></label>
      <div style="margin-top:13px;font-size:12px;color:var(--muted)">
        Answer your security questions to reset your password.</div>
      ${pick.map((q, i) => `
        <label class="fld" style="margin-top:9px">
          <span>${UI.esc(q)}</span>
          <input class="field" type="text" name="fanswer_${i}" data-qidx="${questions.indexOf(q)}" required>
        </label>`).join('')}
      <button class="btn" id="doVerify" style="margin-top:13px">Verify answers</button>
      <div id="resetBlock" hidden style="margin-top:15px;border-top:1px solid var(--rule);padding-top:13px">
        <label class="fld"><span>New password</span>
          <input class="field" type="password" name="new_password" autocomplete="new-password"></label>
        <button class="btn" id="doReset" style="margin-top:11px">Set new password</button>
      </div>
      <div style="margin-top:10px;font-size:12px"><a href="#" data-switch="login">Back to log in</a></div>`;
  }

  function tabs(active) {
    const items = [['login', 'Log in'], ['signup', 'Sign up']];
    return `<div style="display:flex;gap:8px;margin-bottom:14px">${
      items.map(([id, label]) =>
        `<button class="btn${id === active ? '' : ' ghost'}" data-switch="${id}">${label}</button>`
      ).join('')}</div>`;
  }

  function loggedInView(root) {
    root.innerHTML = UI.panel('Your account', 'Signed in for personalization', `
      ${UI.kv([['Email', UI.esc(AUTH.email())]])}
      <button class="btn ghost" id="doLogout" style="margin-top:13px">Log out</button>`);
    document.getElementById('doLogout').addEventListener('click', () => {
      AUTH.clear();
      if (window.HS_APP && window.HS_APP.refreshAccountStatus) window.HS_APP.refreshAccountStatus();
      render(root, { view: 'login' });
    });
  }

  let questionsCache = null;
  async function getQuestions(signal) {
    if (questionsCache) return questionsCache;
    const r = await API.securityQuestions({ signal });
    questionsCache = r.questions;
    return questionsCache;
  }

  async function render(root, ctx) {
    if (AUTH.isLoggedIn()) { loggedInView(root); return; }

    const view = (ctx && ctx.view) || 'login';
    root.innerHTML = UI.panel(
      'Account', 'Personalize alerts for yourself -- optional, separate from the public dashboard',
      `<div id="authTabs">${view === 'forgot' ? '' : tabs(view)}</div><div id="authBody">${UI.loading('the account form')}</div>`
    );

    const body = document.getElementById('authBody');
    let questions = [];
    try {
      questions = await getQuestions(ctx && ctx.signal);
    } catch (err) {
      body.innerHTML = UI.failed('the security-question list', err && err.message);
      return;
    }
    if (ctx && ctx.signal && ctx.signal.aborted) return;

    if (view === 'signup') body.innerHTML = signupForm(questions);
    else if (view === 'forgot') body.innerHTML = forgotForm(questions);
    else body.innerHTML = loginForm();

    root.querySelectorAll('[data-switch]').forEach(a => a.addEventListener('click', (e) => {
      e.preventDefault();
      render(root, { ...ctx, view: a.dataset.switch });
    }));

    if (view === 'login') wireLogin(root, body);
    else if (view === 'signup') wireSignup(root, body);
    else if (view === 'forgot') wireForgot(root, body);
  }

  function collectAnswers(container, prefix) {
    return [...container.querySelectorAll(`input[data-qidx]`)]
      .filter(el => el.name.startsWith(prefix))
      .map(el => ({ question_index: Number(el.dataset.qidx), answer: el.value }));
  }

  function wireLogin(pageRoot, body) {
    document.getElementById('doLogin').addEventListener('click', async () => {
      const f = UI.readForm(body);
      const btn = document.getElementById('doLogin');
      btn.disabled = true;
      try {
        const r = await API.login({ email: f.email, password: f.password });
        AUTH.save(r.session_token, r.email, r.expires_at);
        if (window.HS_APP && window.HS_APP.refreshAccountStatus) window.HS_APP.refreshAccountStatus();
        render(pageRoot, {});
      } catch (err) {
        btn.disabled = false;
        body.insertAdjacentHTML('beforeend', UI.failed('log in', err && err.message));
      }
    });
  }

  function wireSignup(pageRoot, body) {
    document.getElementById('doSignup').addEventListener('click', async () => {
      const f = UI.readForm(body);
      const btn = document.getElementById('doSignup');
      btn.disabled = true;
      try {
        await API.signup({
          email: f.email,
          password: f.password,
          security_answers: collectAnswers(body, 'answer_')
        });
        const r = await API.login({ email: f.email, password: f.password });
        AUTH.save(r.session_token, r.email, r.expires_at);
        if (window.HS_APP && window.HS_APP.refreshAccountStatus) window.HS_APP.refreshAccountStatus();
        render(pageRoot, {});
      } catch (err) {
        btn.disabled = false;
        body.insertAdjacentHTML('beforeend', UI.failed('create the account', err && err.message));
      }
    });
  }

  let pendingResetToken = null;

  function wireForgot(pageRoot, body) {
    document.getElementById('doVerify').addEventListener('click', async () => {
      const f = UI.readForm(body);
      const btn = document.getElementById('doVerify');
      btn.disabled = true;
      try {
        const r = await API.forgotPasswordVerify({
          email: f.email,
          security_answers: collectAnswers(body, 'fanswer_')
        });
        pendingResetToken = r.reset_token;
        document.getElementById('resetBlock').hidden = false;
      } catch (err) {
        body.insertAdjacentHTML('beforeend', UI.failed('verify those answers', err && err.message));
      } finally {
        btn.disabled = false;
      }
    });

    document.getElementById('doReset').addEventListener('click', async () => {
      const f = UI.readForm(body);
      const btn = document.getElementById('doReset');
      btn.disabled = true;
      try {
        await API.forgotPasswordReset({
          reset_token: pendingResetToken,
          new_password: f.new_password
        });
        render(pageRoot, { view: 'login' });
      } catch (err) {
        btn.disabled = false;
        body.insertAdjacentHTML('beforeend', UI.failed('reset the password', err && err.message));
      }
    });
  }

  P.account = { title: 'Account', render };
})();
