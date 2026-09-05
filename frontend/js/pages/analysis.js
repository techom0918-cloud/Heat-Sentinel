/* Thermal Stress, Vulnerability, Heat Risk.
 * Each is a live call against the real calculation endpoint. The frontend
 * computes nothing: it collects inputs, posts them, and renders the reply. */
(function () {
  const API = window.HS_API, UI = window.HS_UI;
  const P = (window.HS_PAGES = window.HS_PAGES || {});

  /* ---------------- Thermal Stress ---------------- */
  P.thermal = { title: 'Thermal Stress', render: async (root, ctx) => {
    root.innerHTML = `<div class="two">
      ${UI.panel('Current Conditions', 'Live from the weather provider', `<div id="cur">${UI.loading('thermal indicators')}</div>`)}
      ${UI.panel('Calculate', 'Post your own values to the thermal engine', `
        <div class="form-grid" id="tform">
          ${UI.input('temperature', 'Temperature (°C)', 42)}
          ${UI.input('relative_humidity', 'Relative humidity (%)', 60)}
          ${UI.input('wind_speed', 'Wind speed (km/h)', 2)}
          ${UI.input('solar_radiation', 'Solar radiation (W/m²)', 500, 'any', 'Accepted but unused in WBGT')}
        </div>
        <button class="btn" id="tcalc">Calculate</button>
        <div id="tout" style="margin-top:12px"></div>`)}
    </div>`;

    const indices = (t) => {
      const cell = (l, v, u, d) => {
        const s = UI.num(v, u, d);
        return `<div class="m"><span>${UI.esc(l)}</span>${s ? `<b>${UI.esc(s)}</b>` : `<b class="na">Unavailable</b>`}</div>`;
      };
      return `<div class="mini">
          ${cell('Heat Index', t.heat_index, ' °C')}
          ${cell('WBGT', t.wbgt, ' °C')}
          ${cell('UTCI', t.utci, ' °C')}
          ${cell('Temperature', t.temperature, ' °C')}
          ${cell('Humidity', t.relative_humidity, '%', 0)}
          ${cell('Wet bulb', t.wet_bulb_temperature, ' °C')}
        </div>
        ${UI.kv([
          ['Heat Index category', UI.riskPill(t.heat_index_category)],
          ['WBGT category', UI.esc(t.wbgt_category)],
          ['UTCI category', UI.esc(t.utci_category)]
        ])}
        ${UI.listNote('Assumptions', t.assumptions)}
        ${UI.listNote('Notes', t.notes)}
        ${(t.methods || []).length ? `<div class="scroll-x" style="margin-top:10px"><table class="dt">
          <tr><th>Index</th><th>Method</th><th>Reference</th></tr>
          ${t.methods.map(m => `<tr><td>${UI.esc(m.index)}</td><td>${UI.esc(m.method)}</td><td>${UI.esc(m.reference)}</td></tr>`).join('')}
        </table></div>` : ''}`;
    };

    try {
      const r = await API.thermalCurrent(ctx.lat, ctx.lon, { signal: ctx.signal });
      document.getElementById('cur').innerHTML =
        `<p style="font-size:11.5px;color:#6F6A66;margin:0 0 9px">Observed ${
          new Date(r.observed_at).toLocaleString('en-IN')} · ${UI.esc(r.provider || '')}</p>` + indices(r.thermal);
    } catch (e) {
      if (!ctx.signal.aborted) document.getElementById('cur').innerHTML = UI.failed('thermal indicators', e.message);
    }

    document.getElementById('tcalc').addEventListener('click', async () => {
      const out = document.getElementById('tout');
      out.innerHTML = UI.loading('the calculation');
      try {
        const body = UI.readForm(document.getElementById('tform'));
        out.innerHTML = indices(await API.thermalCalculate(body));
      } catch (e) { out.innerHTML = UI.failed('the calculation', e.message); }
    });
  }};

  /* ---------------- Vulnerability ---------------- */
  P.vulnerability = { title: 'Vulnerability', render: async (root, ctx) => {
    root.innerHTML = `<div class="two">
      ${UI.panel('Vulnerability Inputs', 'Six weighted factors, scored by the backend', `
        <div class="form-grid" id="vform">
          ${UI.input('elderly_population_pct', 'Elderly population (%)', 12.5)}
          ${UI.input('outdoor_worker_pct', 'Outdoor workers (%)', 28)}
          ${UI.input('population_density', 'Population density (/km²)', 8500)}
          ${UI.input('healthcare_accessibility', 'Healthcare access (0–1)', 0.62)}
          ${UI.input('historical_heat_exposure', 'Past heat exposure (0–1)', 0.70)}
          ${UI.input('historical_heat_mortality', 'Past heat deaths (0–1)', 0.35)}
        </div>
        <button class="btn" id="vcalc">Score vulnerability</button>`)}
      ${UI.panel('Result', 'Weights and thresholds are prototype values', `<div id="vout">${UI.empty('Enter values and score to see the breakdown.')}</div>`)}
    </div>
    ${UI.panel('Zone Comparison', 'Vulnerability of each demo zone', `<div id="vzones">${UI.loading('zones')}</div>`)}`;

    document.getElementById('vcalc').addEventListener('click', async () => {
      const out = document.getElementById('vout');
      out.innerHTML = UI.loading('the vulnerability score');
      try {
        const r = await API.vulnerability(UI.readForm(document.getElementById('vform')));
        const max = Math.max(...Object.values(r.contributions).map(Number)) || 1;
        out.innerHTML = `<div class="big">${r.vulnerability_score.toFixed(3)}</div>
          <div style="margin:6px 0 12px">${UI.riskPill(r.vulnerability_level)}</div>
          <h3 style="font-size:13px;margin-bottom:7px">Contribution by factor</h3>
          <div class="bars">${Object.entries(r.contributions).map(([k, v]) => `
            <div class="bar-row"><span>${UI.esc(k.replace(/_/g, ' '))}</span>
              <div class="bar-track"><div class="bar-fill" style="width:${Math.max(3, (v / max) * 100)}%;background:#8B004A"></div></div>
              <b>${Number(v).toFixed(3)}</b></div>`).join('')}</div>
          ${UI.listNote('Limitations', r.limitations)}
          ${UI.disclaimer(r.disclaimer)}`;
      } catch (e) { out.innerHTML = UI.failed('the vulnerability score', e.message); }
    });

    try {
      const z = await API.zones(ctx.lat, ctx.lon, { signal: ctx.signal });
      const rows = z.features.map(f => f.properties);
      document.getElementById('vzones').innerHTML = `<div class="scroll-x"><table class="dt">
        <tr><th>Zone</th><th>Vulnerability</th><th>Level</th><th>Human risk</th><th>Risk level</th><th>Priority</th></tr>
        ${rows.map(p => `<tr><td>${UI.esc(p.name || p.zone_id)}</td>
          <td>${p.vulnerability.toFixed(3)}</td><td>${UI.riskPill(p.vulnerability_level)}</td>
          <td>${p.human_risk.toFixed(3)}</td><td>${UI.riskPill(p.risk_level)}</td>
          <td>${UI.esc(p.priority)}</td></tr>`).join('')}</table></div>`;
    } catch (e) {
      if (!ctx.signal.aborted) document.getElementById('vzones').innerHTML = UI.failed('zone vulnerability', e.message);
    }
  }};

  /* ---------------- Heat Risk ---------------- */
  P.risk = { title: 'Heat Risk', render: async (root, ctx) => {
    root.innerHTML = `<div class="two">
      ${UI.panel('Risk Inputs', 'Prefilled from live conditions where available', `
        <div class="form-grid" id="rform">${UI.loading('current conditions')}</div>
        <button class="btn" id="rcalc" disabled>Assess risk</button>`)}
      ${UI.panel('Assessment', 'Decision support, not a medical diagnosis', `<div id="rout">${UI.empty('Run an assessment to see the breakdown.')}</div>`)}
    </div>`;

    // Prefill from the live thermal endpoint so the form reflects reality
    // rather than arbitrary defaults.
    let t = null;
    try { t = (await API.thermalCurrent(ctx.lat, ctx.lon, { signal: ctx.signal })).thermal; }
    catch { /* fall through to plain defaults */ }
    if (ctx.signal.aborted) return;

    document.getElementById('rform').innerHTML = `
      ${UI.input('temperature_c', 'Temperature (°C)', t ? t.temperature : 42)}
      ${UI.input('relative_humidity', 'Relative humidity (%)', t ? t.relative_humidity : 65)}
      ${UI.input('wind_speed', 'Wind speed (km/h)', t ? t.wind_speed : 2.5)}
      ${UI.input('heat_index', 'Heat Index (°C)', t && t.heat_index !== null ? t.heat_index : 49.2)}
      ${UI.input('wbgt', 'WBGT (°C)', t && t.wbgt !== null ? t.wbgt : 31.5)}
      ${UI.input('utci', 'UTCI (°C)', t && t.utci !== null ? t.utci : 43.1)}
      ${UI.input('vulnerability_score', 'Vulnerability (0–1)', 0.78)}`;
    document.getElementById('rcalc').disabled = false;

    document.getElementById('rcalc').addEventListener('click', async () => {
      const out = document.getElementById('rout');
      out.innerHTML = UI.loading('the risk assessment');
      try {
        const r = await API.riskPredict(UI.readForm(document.getElementById('rform')));
        out.innerHTML = `<div class="big">${r.risk_score.toFixed(3)}</div>
          <div style="margin:6px 0 12px">${UI.riskPill(r.risk_level)}</div>
          ${UI.kv([
            ['Risk score', r.risk_score.toFixed(3)],
            ['Score echoed as probability', r.risk_probability.toFixed(3) + ' <i style="color:#6F6A66">— not calibrated</i>'],
            ['Confidence', r.confidence === null ? null : r.confidence],
            ['Method', UI.esc(r.method)]
          ])}
          <h3 style="font-size:13px;margin:14px 0 7px">Contributors</h3>
          <div class="bars">${(r.contributors || []).map(c => `
            <div class="bar-row"><span>${UI.esc(c.name)}</span>
              <div class="bar-track"><div class="bar-fill" style="width:${Math.max(3, c.share * 100)}%;background:#8B004A"></div></div>
              <b>${(c.share * 100).toFixed(1)}%</b></div>`).join('')}</div>
          <div class="note">These are arithmetic shares of the combined score, not SHAP
            values. Real SHAP attribution lives on the Explainable AI page.</div>
          ${UI.listNote('Limitations', r.limitations)}
          ${UI.disclaimer(r.disclaimer)}`;
      } catch (e) { out.innerHTML = UI.failed('the risk assessment', e.message); }
    });
  }};
})();
