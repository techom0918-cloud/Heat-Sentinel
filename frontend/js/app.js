/* Shell: navigation, header controls, hash router, backend status.
 * Pages register themselves on window.HS_PAGES and receive an AbortSignal
 * so a navigation cancels whatever the previous page had in flight. */
(function () {
  const UI = window.HS_UI, API = window.HS_API, CFG = window.HS_CONFIG;

  const NAV = [
    ['dashboard',     'Dashboard',        'M3 10.5 12 3l9 7.5V21H3z'],
    ['map',           'Hyperlocal GIS',    'm9 4 6 2 6-2v14l-6 2-6-2-6 2V6z'],
    ['risk',          'Heat Risk',        'M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'],
    ['thermal',       'Thermal Stress',   'M14 14.8V4a2 2 0 0 0-4 0v10.8a4 4 0 1 0 4 0z'],
    ['vulnerability', 'Vulnerability',    'M19 14c1.5-1.5 3-3.3 3-5.5A5.5 5.5 0 0 0 12 5a5.5 5.5 0 0 0-10 3.5C2 10.7 3.5 12.5 5 14l7 7z'],
    ['ml',            'ML Prediction',    'M12 2v4m0 12v4M2 12h4m12 0h4M6 6l3 3m6 6 3 3m0-12-3 3m-6 6-3 3'],
    ['explain',       'Explainable AI',   'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01'],
    ['forecast',      'Forecast & Trends','m3 17 6-6 4 4 8-8M17 7h4v4'],
    ['simulator',     'Action Simulator', 'M12 2 2 7l10 5 10-5zM2 17l10 5 10-5M2 12l10 5 10-5'],
    ['optimizer',     'Action Optimizer', 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zm0-6a4 4 0 1 0 0-8 4 4 0 0 0 0 8z'],
    ['alerts',        'Alerts & Warnings','M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a2 2 0 0 0 3.4 0'],
    ['health',        'Health & Mortality','M19 14c1.5-1.5 3-3.3 3-5.5A5.5 5.5 0 0 0 12 5a5.5 5.5 0 0 0-10 3.5C2 10.7 3.5 12.5 5 14l7 7z'],
    ['data',          'Data & Sources',   'M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6'],
    ['system',        'System Status',    'M22 12h-4l-3 9L9 3l-3 9H2']
  ];

  const FLOW = ['Predict','Explain','Forecast','Map','Simulate','Optimize','Alert','Validate'];

  const state = {
    lat: CFG.DEFAULT_COORDS.lat,
    lon: CFG.DEFAULT_COORDS.lon,
    days: 5,
    controller: null
  };

  const icon = (d) =>
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;

  function shell() {
    document.body.innerHTML = `
      <div class="shell">
        <aside class="rail" id="rail">
          <div class="rail-brand">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="4"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2m0-14-2 2M7 17l-2 2"/></svg>
            <b>HeatSentinal</b>
          </div>
          <nav class="rail-nav" id="nav">${NAV.map(([id, label, d]) =>
            `<a href="#/${id}" data-page="${id}">${icon(d)}<span>${label}</span></a>`).join('')}</nav>
          <div class="rail-foot"><b>SIH 2026</b><span>PS ID 26083 · MoES / NCMRWF</span></div>
        </aside>

        <div style="min-width:0">
          <header class="topbar">
            <button class="rail-toggle" id="railToggle" aria-label="Open navigation">
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
            </button>
            <div class="title"><b>HeatSentinal</b>
              <span>AI-Powered Human Heat-Health Early Warning System</span></div>
            <div class="flow">${FLOW.map((f, i) =>
              `${i ? '<i>›</i>' : ''}<b>${f}</b>`).join('')}</div>
            <div class="org"><b id="beStatus">Checking backend…</b>
              <span>Ministry of Earth Sciences · NCMRWF</span></div>
          </header>

          <div class="controls">
            <div class="ctl"><label for="loc">Location</label>
              <select class="field" id="loc">
                <option value="28.6139,77.2090">Delhi (demo zones)</option>
                <option value="19.0760,72.8777">Mumbai</option>
                <option value="23.0225,72.5714">Ahmedabad</option>
                <option value="26.9124,75.7873">Jaipur</option>
                <option value="22.5726,88.3639">Kolkata</option>
              </select></div>
            <div class="ctl"><label>Forecast horizon</label>
              <div class="seg" id="horizon">
                <button data-days="3" aria-pressed="false">3 days</button>
                <button data-days="5" aria-pressed="true">5 days</button>
              </div></div>
            <button class="emergency" id="emergency">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/></svg>
              Emergency View</button>
          </div>

          <main id="view"></main>
        </div>
      </div>`;
  }

  async function backendStatus() {
    const el = document.getElementById('beStatus');
    try {
      const [h, m] = await Promise.allSettled([API.healthDetails(), API.modelStatus()]);
      const up = h.status === 'fulfilled';
      const model = m.status === 'fulfilled' && m.value && m.value.available;
      el.textContent = up
        ? `Backend online · ML model ${model ? 'loaded' : 'not loaded'}`
        : 'Backend unreachable';
      el.style.color = up ? (model ? '#10B981' : '#F59E0B') : '#B91C1C';
    } catch {
      el.textContent = 'Backend unreachable';
      el.style.color = '#B91C1C';
    }
  }

  function setActive(page) {
    document.querySelectorAll('#nav a').forEach(a =>
      a.classList.toggle('active', a.dataset.page === page));
  }

  async function route() {
    const page = (location.hash.replace(/^#\/?/, '') || 'dashboard').split('?')[0];
    setActive(page);
    document.getElementById('rail').classList.remove('open');

    // Cancel anything the previous page still had running.
    if (state.controller) state.controller.abort();
    state.controller = new AbortController();

    const view = document.getElementById('view');
    window.HS_MAP.destroy();

    const mod = window.HS_PAGES[page];
    if (!mod) {
      view.innerHTML = `<section class="panel"><div class="panel-head"><div>
        <h2>${UI.esc(page.replace(/\b\w/g, c => c.toUpperCase()))}</h2>
        <p>This module is not built yet</p></div></div>
        <div class="panel-body">${UI.empty('The backend endpoint for this view exists; the interface is still to come.')}</div></section>`;
      return;
    }
    try {
      await mod.render(view, { ...state, signal: state.controller.signal });
    } catch (err) {
      if (state.controller.signal.aborted) return;
      // A page throwing must not take the shell down with it.
      view.innerHTML = `<section class="panel"><div class="panel-body">
        ${UI.failed('this view', err && err.message, 'route')}</div></section>`;
    }
  }

  function wire() {
    document.getElementById('loc').addEventListener('change', (e) => {
      const [la, lo] = e.target.value.split(',').map(Number);
      state.lat = la; state.lon = lo;
      CFG.MAP_CENTER = [la, lo];
      CFG.DEFAULT_COORDS.label = e.target.selectedOptions[0].text.replace(/\s*\(.*\)$/, '');
      route();
    });
    document.getElementById('horizon').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-days]');
      if (!b) return;
      state.days = Number(b.dataset.days);
      document.querySelectorAll('#horizon button').forEach(x =>
        x.setAttribute('aria-pressed', String(x === b)));
      route();
    });
    document.getElementById('emergency').addEventListener('click', () => {
      location.hash = '#/alerts';
    });
    document.getElementById('railToggle').addEventListener('click', () =>
      document.getElementById('rail').classList.toggle('open'));
    document.body.addEventListener('click', (e) => {
      if (e.target.closest('[data-retry]')) route();
    });
    window.addEventListener('hashchange', route);
  }

  document.addEventListener('DOMContentLoaded', () => {
    shell(); wire(); backendStatus(); route();
  });
})();
