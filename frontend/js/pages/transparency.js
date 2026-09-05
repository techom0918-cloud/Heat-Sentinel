/* Health & Mortality validation, Data & Sources, System Status.
 * These three exist for scrutiny: they state what the data is, where it came
 * from, and what the system cannot do. */
(function () {
  const API = window.HS_API, UI = window.HS_UI, CFG = window.HS_CONFIG;
  const P = (window.HS_PAGES = window.HS_PAGES || {});

  /* ---------------- Health & Mortality ---------------- */
  P.health = { title: 'Health & Mortality', render: async (root, ctx) => {
    root.innerHTML = `
      ${UI.panel('Observed Mortality', 'Government-reported heat-wave deaths', `<div id="hobs">${UI.loading('the mortality dataset')}</div>`)}
      <div class="two">
        ${UI.panel('Yearly Totals', 'As reported, not modelled', `<div id="hyear">${UI.loading('yearly totals')}</div>`)}
        ${UI.panel('Most Affected States', 'By reported deaths', `<div id="htop">${UI.loading('regional totals')}</div>`)}
      </div>`;

    const [d, v] = await Promise.allSettled([
      API.healthData({ signal: ctx.signal }),
      API.healthValidation({ signal: ctx.signal })
    ]);
    if (ctx.signal.aborted) return;

    const ho = document.getElementById('hobs');
    if (d.status === 'fulfilled') {
      const r = d.value;
      ho.innerHTML = UI.kv([
        ['Data status', `<span class="tag">${UI.esc(r.data_status)}</span>`],
        ['Source file', UI.esc(r.source_file)],
        ['Records loaded', r.records_loaded_total],
        ['Records returned', r.records_returned],
        ['Rows rejected', r.rejected_rows],
        ['Rows with missing values', r.missing_value_rows]
      ]) + `<div class="scroll-x" style="margin-top:12px"><table class="dt">
        <tr><th>Year</th><th>State</th><th>Reported deaths</th><th>Source</th></tr>
        ${(r.observations || []).slice(0, 25).map(o => `<tr>
          <td>${o.year}</td><td>${UI.esc(o.state)}</td>
          <td>${o.heat_wave_deaths.toLocaleString('en-IN')}</td>
          <td style="font-size:11px">${UI.esc(o.source)}</td></tr>`).join('')}
      </table></div>
      ${UI.listNote('Notes', r.notes)}
      <div class="note"><b>What this page is and is not</b><br>
        These are observed, reported counts. The system does not predict deaths,
        and no figure anywhere in HeatSentinal should be read as lives saved or
        as a causal effect of an intervention.</div>`;
    } else {
      ho.innerHTML = UI.failed('the mortality dataset', d.reason && d.reason.message);
    }

    const hy = document.getElementById('hyear'), ht = document.getElementById('htop');
    if (v.status === 'fulfilled') {
      const r = v.value;
      const maxY = Math.max(...(r.yearly_totals || []).map(y => y.total_deaths), 1);
      hy.innerHTML = UI.kv([
        ['Period', UI.esc(r.period)],
        ['Regions evaluated', r.regions_evaluated],
        ['Observations', r.observations],
        ['High-risk threshold', r.high_risk_threshold + ' deaths'],
        ['High-risk events', r.high_risk_events]
      ]) + `<div class="bars" style="margin-top:12px">${(r.yearly_totals || []).map(y => `
        <div class="bar-row"><span>${y.year}</span>
          <div class="bar-track"><div class="bar-fill" style="width:${Math.max(3, (y.total_deaths / maxY) * 100)}%;background:#8B004A"></div></div>
          <b>${y.total_deaths.toLocaleString('en-IN')}</b></div>`).join('')}</div>
        ${UI.listNote('Notes', r.notes)}`;

      const maxR = Math.max(...(r.top_regions || []).map(x => x.total_deaths), 1);
      ht.innerHTML = `<div class="bars">${(r.top_regions || []).map(x => `
        <div class="bar-row"><span title="${UI.esc(x.state)}">${UI.esc(x.state)}</span>
          <div class="bar-track"><div class="bar-fill" style="width:${Math.max(3, (x.total_deaths / maxR) * 100)}%;background:#8B004A"></div></div>
          <b>${x.total_deaths.toLocaleString('en-IN')}</b></div>`).join('')}</div>
        <div class="note">Reported totals only. Reporting completeness varies by
          state and year, so these are not comparable as rates.</div>`;
    } else {
      const m = v.reason && v.reason.message;
      hy.innerHTML = UI.failed('yearly totals', m);
      ht.innerHTML = UI.failed('regional totals', m);
    }
  }};

  /* ---------------- Data & Sources ---------------- */
  P.data = { title: 'Data & Sources', render: async (root, ctx) => {
    root.innerHTML = `
      ${UI.panel('What this system runs on', 'Sources, resolution and known limits', `<div id="dsrc">${UI.loading('source information')}</div>`)}
      ${UI.panel('Model', 'Algorithm, features and measured performance', `<div id="dmodel">${UI.loading('model information')}</div>`)}`;

    const [z, m, t] = await Promise.allSettled([
      API.zones(ctx.lat, ctx.lon, { signal: ctx.signal }),
      API.modelStatus({ signal: ctx.signal }),
      API.thermalCurrent(ctx.lat, ctx.lon, { signal: ctx.signal })
    ]);
    if (ctx.signal.aborted) return;

    const zc = z.status === 'fulfilled' ? z.value : null;
    const tc = t.status === 'fulfilled' ? t.value : null;

    document.getElementById('dsrc').innerHTML = UI.kv([
      ['Weather provider', tc ? UI.esc(tc.provider) : null],
      ['Observed at', tc ? new Date(tc.observed_at).toLocaleString('en-IN') : null],
      ['Zone geometry status', zc ? `<span class="tag">${UI.esc(zc.data_status)}</span>` : null],
      ['Zones returned', zc ? zc.features.length : null],
      ['Mortality data', 'Government-reported heat-wave deaths, 2018–2022']
    ]) + (zc && zc.warning ? `<div class="note synthetic"><b>Zone geometry</b><br>${UI.esc(zc.warning)}</div>` : '')
      + `<div class="note"><b>Spatial resolution</b><br>
        The weather grid resolves to roughly 11 km, so all zones in a city share
        one hazard cell. Variation between zones comes from vulnerability, not
        from hazard. Zone-level hazard downscaling is not implemented.</div>
      <div class="note"><b>Index caveats</b><br>
        WBGT is a shade approximation, so ISO 7243 and ACGIH exposure limits are
        deliberately not applied. UTCI is reported as unavailable above its valid
        range rather than extrapolated. Solar radiation is accepted as an input
        but is not used to derive a globe temperature.</div>
      <div class="note"><b>Thresholds</b><br>
        Every weight, threshold and intervention effect size is a prototype value
        held in configuration. None has been clinically or epidemiologically
        validated.</div>`;

    const me = document.getElementById('dmodel');
    if (m.status === 'fulfilled' && m.value.model_info) {
      const i = m.value.model_info, perf = i.test_metrics || {};
      me.innerHTML = UI.kv([
        ['Algorithm', UI.esc(i.type)],
        ['Features', i.feature_count],
        ['Forecast horizon', i.horizon_days + ' days'],
        ['Risk bands', (i.risk_levels || []).join(', ')],
        ['Trained on', UI.esc(i.trained_on)]
      ]) + (Object.keys(perf).length ? `<h3 style="font-size:13px;margin:14px 0 7px">Held-out performance</h3>` +
        UI.kv(Object.entries(perf).map(([k, v]) =>
          [k.toUpperCase(), typeof v === 'number' ? v.toFixed(3) : UI.esc(String(v))])) : '')
        + `<div class="note">The model was selected on Critical Success Index rather
          than accuracy. Accuracy is misleading for rare events: predicting "never
          hot" scores above 90% while catching nothing.</div>`;
    } else {
      me.innerHTML = m.status === 'fulfilled'
        ? UI.empty('No model is loaded on the server, so no model details are available.')
        : UI.failed('model information', m.reason && m.reason.message);
    }
  }};

  /* ---------------- System Status ---------------- */
  P.system = { title: 'System Status', render: async (root, ctx) => {
    root.innerHTML = UI.panel('Service Status', 'Probed live, not declared',
      `<div id="sys">${UI.loading('service status')}</div>`);

    // Each row is an actual request. Nothing here is hardcoded to "Operational".
    const probes = [
      ['Backend API',        () => API.healthDetails()],
      ['Weather service',    () => API.weatherCurrent(ctx.lat, ctx.lon)],
      ['Thermal engine',     () => API.thermalCurrent(ctx.lat, ctx.lon)],
      ['Risk engine',        () => API.riskPredict({ temperature_c: 40, relative_humidity: 50,
                                heat_index: 45, wbgt: 30, vulnerability_score: 0.5 })],
      ['ML model',           () => API.modelStatus()],
      ['Forecast trajectory',() => API.trajectory(ctx.lat, ctx.lon, 3)],
      ['GIS zones',          () => API.zones(ctx.lat, ctx.lon)],
      ['Intervention catalogue', () => API.interventionTypes()],
      ['Health data',        () => API.healthData()]
    ];

    const results = await Promise.allSettled(probes.map(([, fn]) => fn()));
    if (ctx.signal.aborted) return;

    const detail = results[0].status === 'fulfilled' ? results[0].value : null;
    const row = (label, res) => {
      let colour = '#10B981', text = 'Operational';
      if (res.status === 'rejected') {
        const s = res.reason && res.reason.status;
        colour = s === 503 ? '#F59E0B' : '#B91C1C';
        text = s === 503 ? 'Dependency unavailable' : (res.reason.message || 'Failed');
      }
      return `<tr><td><i class="dot" style="background:${colour}"></i> ${UI.esc(label)}</td>
        <td style="color:${colour};font-weight:600">${UI.esc(text)}</td></tr>`;
    };

    document.getElementById('sys').innerHTML = `<div class="scroll-x"><table class="dt">
        <tr><th>Service</th><th>Status</th></tr>
        ${probes.map(([l], i) => row(l, results[i])).join('')}
      </table></div>
      ${detail ? '<h3 style="font-size:13px;margin:16px 0 7px">Build</h3>' + UI.kv([
        ['Service', UI.esc(detail.service)],
        ['Version', UI.esc(detail.version)],
        ['API version', UI.esc(detail.api_version)],
        ['Debug mode', detail.debug ? '<span style="color:#F59E0B;font-weight:600">On — not a production setting</span>' : 'Off'],
        ['Uptime', Math.round(detail.uptime_seconds) + ' s']
      ]) : ''}
      <div class="note">Every row above is a live request made just now. A service
        that reports "Dependency unavailable" is failing loudly by design rather
        than returning fabricated values.</div>
      ${UI.kv([['Frontend API base', UI.esc(CFG.API_BASE_URL)]])}`;
  }};
})();
