/* ML Prediction, Explainable AI, Forecast & Trends, Hyperlocal GIS. */
(function () {
  const API = window.HS_API, UI = window.HS_UI;
  const P = (window.HS_PAGES = window.HS_PAGES || {});

  /* ---------------- ML Prediction ---------------- */
  P.ml = { title: 'ML Prediction', render: async (root, ctx) => {
    root.innerHTML = `<div class="two">
      ${UI.panel('Hazard Forecast', 'Single-horizon prediction from the trained model', `<div id="pred">${UI.loading('the model prediction')}</div>`)}
      ${UI.panel('Model', 'What is actually loaded on the server', `<div id="minfo">${UI.loading('model status')}</div>`)}
    </div>`;

    const [f, m] = await Promise.allSettled([
      API.riskForecast(ctx.lat, ctx.lon, false, { signal: ctx.signal }),
      API.modelStatus({ signal: ctx.signal })
    ]);
    if (ctx.signal.aborted) return;

    const pe = document.getElementById('pred');
    if (f.status === 'fulfilled') {
      const d = f.value;
      const probs = d.class_probabilities || {};
      const maxP = Math.max(...Object.values(probs).map(Number), 0.0001);
      const edges = (d.model_info || {}).heat_index_edges;
      const range = UI.bandRange(d.predicted_category, edges);
      pe.innerHTML = `<div class="big">${UI.esc(UI.riskMeta(d.predicted_category).label)}</div>
        <div style="margin:6px 0 4px">${UI.riskPill(d.predicted_category)}</div>
        ${range ? `<div style="font-size:12.5px;color:#6F6A66;margin-bottom:12px">
          Daily peak heat index ${UI.esc(range)} \u00B7 ${UI.esc(UI.bandGloss[d.predicted_category] || '')}</div>` : ''}
        ${UI.kv([
          ['Issued for', UI.esc(d.issued_for)],
          ['Horizon', d.horizon_days + ' days'],
          ['Predicted band', UI.esc(range || d.predicted_category)],
          ['Confidence', d.confidence === null ? null : (d.confidence * 100).toFixed(1) + '%'],
          ['Current category', UI.riskPill(d.current_category) +
            (UI.bandRange(d.current_category, edges) ? ` <span style="color:#6F6A66">(${UI.esc(UI.bandRange(d.current_category, edges))})</span>` : '')],
          ['Today\u2019s peak heat index', UI.num(d.current_heat_index_max, ' \u00B0C')],
          ['Days of history used', d.days_of_history_used]
        ])}
        <div class="note">These bands are heat index ranges, not heatwave
          declarations. ${UI.esc(UI.riskMeta(d.predicted_category).label)} means the
          day\u2019s peak heat index is expected ${UI.esc(range || 'in this band')}.
          Mid-range bands are ordinary warm days across much of India rather than
          emergencies. Compare with the current category above: if the two match,
          the model is predicting persistence, not escalation.</div>
        ${Object.keys(probs).length ? `<h3 style="font-size:13px;margin:14px 0 7px">Class probabilities</h3>
          <div class="bars">${Object.entries(probs).map(([k, v]) => `
            <div class="bar-row"><span>${UI.esc(k)}</span>
              <div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, (v / maxP) * 100)}%;background:${UI.riskMeta(k).color}"></div></div>
              <b>${(Number(v) * 100).toFixed(1)}%</b></div>`).join('')}</div>` : ''}
        ${UI.listNote('Limitations', d.limitations)}
        ${UI.disclaimer(d.disclaimer)}`;
    } else {
      const r = f.reason || {};
      pe.innerHTML = r.status === 503
        ? UI.empty('The trained model is not loaded on the server, so no prediction is available.')
        : UI.failed('the model prediction', r.message);
    }

    const me = document.getElementById('minfo');
    if (m.status === 'fulfilled') {
      const s = m.value, i = s.model_info || {};
      const perf = i.test_metrics || {};
      me.innerHTML = UI.kv([
        ['Status', s.available ? '<span class="pill" style="background:#10B981">Loaded</span>' : '<span class="pill" style="background:#B91C1C">Not loaded</span>'],
        ['SHAP explainer', s.explainer_available ? 'Available' : 'Unavailable'],
        ['Algorithm', UI.esc(i.type)],
        ['Features', i.feature_count],
        ['Horizon', i.horizon_days ? i.horizon_days + ' days' : null],
        ['Risk bands', (i.risk_levels || []).join(', ')],
        ['Trained on', UI.esc(i.trained_on)]
      ]) + (Object.keys(perf).length ? `<h3 style="font-size:13px;margin:14px 0 7px">Held-out performance</h3>` +
        UI.kv(Object.entries(perf).map(([k, v]) =>
          [k.toUpperCase(), typeof v === 'number' ? v.toFixed(3) : UI.esc(String(v))])) : '') +
        `<div class="note">${UI.esc(s.detail || '')}</div>
         <div class="note">The model has a single horizon. In a multi-day trajectory
         exactly one day is an ML prediction; the rest are observed conditions or
         categories derived from the weather forecast.</div>`;
    } else {
      me.innerHTML = UI.failed('model status', m.reason && m.reason.message);
    }
  }};

  /* ---------------- Explainable AI ---------------- */
  P.explain = { title: 'Explainable AI', render: async (root, ctx) => {
    root.innerHTML = UI.panel('Why is the risk what it is?',
      'SHAP attribution over the trained model, for the predicted class',
      `<div id="ex">${UI.loading('the explanation')}</div>`);

    try {
      const d = await API.riskForecast(ctx.lat, ctx.lon, true, { signal: ctx.signal });
      if (ctx.signal.aborted) return;
      const e = d.explanation;
      if (!e) {
        document.getElementById('ex').innerHTML =
          UI.empty('The model is loaded but returned no explanation for this request.');
        return;
      }
      const factors = e.top_factors || [];
      const max = Math.max(...factors.map(f => f.impact), 0.0001);
      const up = factors.filter(f => f.direction === 'increases_risk');
      const down = factors.filter(f => f.direction !== 'increases_risk');

      document.getElementById('ex').innerHTML = `
        <div class="two" style="margin-bottom:14px">
          <div><div class="big">${UI.esc(UI.riskMeta(d.predicted_category).label)}</div>
            <div style="margin-top:6px">${UI.riskPill(d.predicted_category)}</div>
            <p style="font-size:12.5px;color:#6F6A66;margin-top:9px">${UI.esc(e.summary || '')}</p></div>
          <div>${UI.kv([
            ['Explained class', UI.esc(e.explained_class)],
            ['Base value', e.base_value === null ? null : e.base_value.toFixed(4)],
            ['Features considered', e.features_considered],
            ['Confidence', d.confidence === null ? null : (d.confidence * 100).toFixed(1) + '%']
          ])}</div>
        </div>
        <h3 style="font-size:13px;margin:0 0 8px">Factor contributions</h3>
        <div style="display:flex;gap:16px;font-size:11px;color:#6F6A66;margin-bottom:9px">
          <span><i class="dot" style="background:#10B981"></i> lowers risk</span>
          <span><i class="dot" style="background:#B91C1C"></i> raises risk</span></div>
        ${up.map(f => UI.shapRow(f, max)).join('')}
        ${down.map(f => UI.shapRow(f, max)).join('')}
        <div class="note"><b>Method</b><br>${UI.esc(e.method || '')}</div>
        ${e.caveat ? `<div class="note">${UI.esc(e.caveat)}</div>` : ''}`;
    } catch (err) {
      if (ctx.signal.aborted) return;
      document.getElementById('ex').innerHTML = err.status === 503
        ? UI.empty('SHAP needs the trained model, which is not loaded on the server.')
        : UI.failed('the explanation', err.message);
    }
  }};

  /* ---------------- Forecast & Trends ---------------- */
  P.forecast = { title: 'Forecast & Trends', render: async (root, ctx) => {
    root.innerHTML = UI.panel('Risk Trajectory', 'Day-by-day, with the provenance of each day',
      `<div id="tj">${UI.loading('the trajectory')}</div>`);
    try {
      const d = await API.trajectory(ctx.lat, ctx.lon, ctx.days, { signal: ctx.signal });
      if (ctx.signal.aborted) return;
      const badge = (m) => {
        const c = m === 'ML_MODEL' ? '#8B004A' : m === 'OBSERVED' ? '#6B7280' : '#F59E0B';
        return `<span class="pill" style="background:${c}">${UI.esc(m.replace('_', ' '))}</span>`;
      };
      document.getElementById('tj').innerHTML = `
        ${UI.kv([
          ['Peak risk', UI.riskPill(d.peak_risk) + ' on ' + UI.esc(d.peak_date)],
          ['Trend', UI.esc(d.trend)],
          ['Days returned', `${d.days_returned} of ${d.days_requested} requested`],
          ['Model horizon', d.model_horizon_days + ' days']
        ])}
        <div class="scroll-x" style="margin-top:12px"><table class="dt">
          <tr><th>Date</th><th>Ahead</th><th>Band</th><th>Band range</th><th>Peak HI</th><th>Source</th><th>Confidence</th></tr>
          ${(d.forecast || []).map(f => `<tr>
            <td>${UI.esc(f.target_date)}</td><td>+${f.days_ahead}d</td>
            <td>${UI.riskPill(f.risk_level)}</td>
            <td style="color:#6F6A66">${UI.esc(UI.bandRange(f.risk_level) || '—')}</td>
            <td>${UI.num(f.heat_index_max, ' °C') || '—'}</td>
            <td>${badge(f.method)}</td>
            <td>${f.confidence === null ? '<i style="color:#6F6A66">n/a</i>' : (f.confidence * 100).toFixed(1) + '%'}</td>
          </tr>`).join('')}
        </table></div>
        <div class="note">Bands are heat index ranges, not heatwave declarations.
          Peak HI is the number behind the band, so a HIGH day sitting at 34 °C is
          a normal warm day rather than an alert-worthy one.</div>
        <div class="note">Only the ML day carries a confidence value. Days marked
          NWP DERIVED are categories computed from the weather forecast using the
          same thresholds the model was trained against — they are not predictions.</div>
        ${UI.listNote('Limitations', d.limitations)}`;
    } catch (e) {
      if (ctx.signal.aborted) return;
      document.getElementById('tj').innerHTML = e.status === 503
        ? UI.empty('The trained model is not loaded, so no trajectory is available.')
        : UI.failed('the trajectory', e.message);
    }
  }};

  /* ---------------- Hyperlocal GIS ---------------- */
  P.map = { title: 'Hyperlocal GIS', render: async (root, ctx) => {
    root.innerHTML = `
      ${UI.panel('Zone Risk Map', 'Filter and rank the zones the backend returns', `
        <div class="row" style="margin-bottom:10px">
          <span style="font-size:11.5px;color:#6F6A66">Show</span>
          <div class="chips" id="filters">
            ${['ALL', 'EXTREME', 'VERY_HIGH', 'HIGH', 'MODERATE', 'LOW'].map((k, i) =>
              `<button class="chip" data-f="${k}" aria-pressed="${i === 0}">${
                k === 'ALL' ? 'All zones' : UI.riskMeta(k).label}</button>`).join('')}
          </div>
        </div>
        <div class="map-wrap" style="padding:0"><div id="map"></div>
          <div class="legend" id="legend" hidden></div></div>
        <div id="mnote"></div>`)}
      ${UI.panel('Zone Ranking', 'Ordered by human risk score', `<div id="rank">${UI.loading('zones')}</div>`)}`;

    let coll = null;
    try {
      coll = await API.zones(ctx.lat, ctx.lon, { signal: ctx.signal });
    } catch (e) {
      if (ctx.signal.aborted) return;
      document.getElementById('map').outerHTML = UI.failed('the zone map', e.message);
      document.getElementById('rank').innerHTML = UI.failed('zone ranking', e.message);
      return;
    }
    if (ctx.signal.aborted) return;

    const lg = document.getElementById('legend');
    lg.hidden = false;
    lg.innerHTML = '<b>Risk level</b>' + ['EXTREME', 'VERY_HIGH', 'HIGH', 'MODERATE', 'LOW']
      .map(k => `<div><i class="dot" style="background:${UI.riskMeta(k).color}"></i>${UI.riskMeta(k).label}</div>`).join('');

    if (coll.data_status && coll.data_status !== 'REAL') {
      document.getElementById('mnote').innerHTML =
        `<div class="note synthetic"><b>${UI.esc(coll.data_status)}</b> — ${UI.esc(coll.warning || '')}</div>`;
    }

    const draw = (filter) => {
      const feats = filter === 'ALL' ? coll.features
        : coll.features.filter(f => f.properties.risk_level === filter);
      window.HS_MAP.renderZones('map', { ...coll, features: feats });
      const rows = feats.map(f => f.properties).sort((a, b) => b.human_risk - a.human_risk);
      document.getElementById('rank').innerHTML = rows.length ? `<div class="scroll-x"><table class="dt">
          <tr><th>#</th><th>Zone</th><th>Risk</th><th>Score</th><th>Hazard</th><th>Vulnerability</th>
              <th>Heat Index</th><th>WBGT</th><th>UTCI</th><th>Priority</th></tr>
          ${rows.map((p, i) => `<tr>
            <td>${i + 1}</td><td>${UI.esc(p.name || p.zone_id)}</td>
            <td>${UI.riskPill(p.risk_level)}</td><td>${p.human_risk.toFixed(3)}</td>
            <td>${p.heat_hazard.toFixed(3)}</td><td>${p.vulnerability.toFixed(3)}</td>
            <td>${UI.num(p.heat_index, ' °C') || '—'}</td>
            <td>${UI.num(p.wbgt, ' °C') || '—'}</td>
            <td>${UI.num(p.utci, ' °C') || '—'}</td>
            <td>${UI.esc(p.priority)}</td></tr>`).join('')}
        </table></div>
        <div class="note">Hazard is identical across zones: the provider grid is
          about 11 km, so every zone shares one cell. What varies is vulnerability
          — that is the point of the zone layer.</div>`
        : UI.empty('No zones match this filter.');
    };

    draw('ALL');
    document.getElementById('filters').addEventListener('click', (e) => {
      const b = e.target.closest('.chip'); if (!b) return;
      document.querySelectorAll('#filters .chip').forEach(c =>
        c.setAttribute('aria-pressed', String(c === b)));
      draw(b.dataset.f);
    });
  }};
})();
