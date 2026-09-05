/* Command Centre.
 *
 * Every figure below comes from a backend response. Where the mockup showed
 * population-at-risk, predicted health cases and state-level breakdowns, the
 * API has no such data, so those panels are replaced with things it does
 * return: per-zone risk, mean vulnerability contributions, and the real
 * five-day trajectory. Nothing is filled in to make the grid look complete.
 */
(function () {
  const API = window.HS_API, UI = window.HS_UI, CFG = window.HS_CONFIG;

  /** Small dependency-free SVG line chart for the risk trajectory. */
  function trendChart(days) {
    if (!days.length) return UI.empty('No forecast days returned.');
    const W = 560, H = 190, PAD = { l: 30, r: 18, t: 20, b: 26 };
    const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
    const x = (i) => PAD.l + (days.length === 1 ? iw / 2 : (i / (days.length - 1)) * iw);
    // risk_level_index is 0..4; clamped so a flat EXTREME line still
    // sits inside the plot instead of on the frame.
    const y = (v) => PAD.t + ih - (Math.min(Math.max(v, 0), 4) / 4) * ih;

    const line = days.map((d, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(d.risk_level_index).toFixed(1)}`).join(' ');
    const grid = [0, 1, 2, 3, 4].map(v =>
      `<line x1="${PAD.l}" x2="${W - PAD.r}" y1="${y(v)}" y2="${y(v)}" stroke="#E3DCD0" stroke-width="1"/>
       <text x="${PAD.l - 6}" y="${y(v) + 3.5}" text-anchor="end" font-size="9" fill="#6F6A66">${v}</text>`).join('');

    const pts = days.map((d, i) => {
      const isML = d.method === 'ML_MODEL';
      const c = UI.riskMeta(d.risk_level).color;
      return `<circle cx="${x(i)}" cy="${y(d.risk_level_index)}" r="${isML ? 6 : 4}"
                fill="${c}" stroke="#fff" stroke-width="${isML ? 2.5 : 1.5}">
              <title>${UI.esc(d.target_date)} — ${UI.esc(d.risk_level)} (${UI.esc(d.method)})</title></circle>`;
    }).join('');

    const labels = days.map((d, i) =>
      `<text x="${x(i)}" y="${H - 8}" text-anchor="middle" font-size="9.5" fill="#6F6A66">${UI.humanDate(d.target_date)}</text>`).join('');

    return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto" role="img"
              aria-label="Risk trajectory by day">${grid}
              <path d="${line}" fill="none" stroke="#8B004A" stroke-width="2.2"/>${pts}${labels}</svg>
      <div style="font-size:11px;color:#6F6A66;margin-top:6px">
        Larger marker = the single day predicted by the ML model. Other days are
        observed conditions or categories derived from the weather forecast.
      </div>`;
  }

  function bars(rows, max) {
    if (!rows.length) return UI.empty('No zones returned.');
    return `<div class="bars">` + rows.map(r => `
      <div class="bar-row">
        <span title="${UI.esc(r.label)}" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${UI.esc(r.label)}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.max(3, (r.value / max) * 100).toFixed(1)}%;background:${r.color}"></div></div>
        <b style="font-size:11.5px">${UI.esc(r.display)}</b>
      </div>`).join('') + `</div>`;
  }

  async function render(root, ctx) {
    const { lat, lon, days } = ctx;
    const signal = ctx.signal;

    root.innerHTML = `
      <div class="kpis" id="kpis">${UI.loading('risk intelligence')}</div>
      <div class="grid-main">
        <section class="panel">
          <div class="panel-head">
            <div><h2>Heat-Health Risk Map</h2>
            <p>Zone risk from weather, vulnerability and the risk engine</p></div>
          </div>
          <div class="map-wrap"><div id="map"></div>
            <div class="legend" id="legend" hidden></div>
          </div>
          <div class="panel-body" id="map-note"></div>
        </section>
        <section class="panel"><div class="panel-head"><div><h2>Risk by Zone</h2>
          <p>Human risk score per zone</p></div></div>
          <div class="panel-body" id="zonebars">${UI.loading('zones')}</div></section>
        <section class="panel"><div class="panel-head"><div><h2>Vulnerability Drivers</h2>
          <p>Mean contribution across zones</p></div></div>
          <div class="panel-body" id="vulnbars">${UI.loading('vulnerability')}</div></section>
      </div>
      <div class="grid-bottom">
        <section class="panel"><div class="panel-head"><div><h2>Risk Trajectory</h2>
          <p id="traj-sub">Forecast horizon</p></div></div>
          <div class="panel-body" id="trend">${UI.loading('forecast')}</div></section>
        <section class="panel"><div class="panel-head"><div><h2>Thermal Indicators</h2>
          <p id="thermal-sub">Current conditions</p></div></div>
          <div class="panel-body" id="thermal">${UI.loading('thermal indicators')}</div></section>
        <section class="panel"><div class="panel-head"><div><h2>Alerts</h2>
          <p>Evaluated per zone against the forecast peak</p></div></div>
          <div class="panel-body" id="alerts">${UI.loading('alerts')}</div></section>
      </div>`;

    // Fire independently: one failing endpoint must not blank the dashboard.
    const results = await Promise.allSettled([
      API.zones(lat, lon, { signal }),
      API.thermalCurrent(lat, lon, { signal }),
      API.trajectory(lat, lon, days, { signal })
    ]);
    if (signal.aborted) return;

    const [zonesR, thermalR, trajR] = results;
    const zones   = zonesR.status   === 'fulfilled' ? zonesR.value   : null;
    const thermal = thermalR.status === 'fulfilled' ? thermalR.value : null;
    const traj    = trajR.status    === 'fulfilled' ? trajR.value    : null;

    /* ---------- map ---------- */
    const mapNote = document.getElementById('map-note');
    if (zones) {
      const n = window.HS_MAP.renderZones('map', zones);
      const lg = document.getElementById('legend');
      lg.hidden = false;
      lg.innerHTML = '<b>Risk level</b>' + ['EXTREME','VERY_HIGH','HIGH','MODERATE','LOW']
        .map(k => `<div><i class="dot" style="background:${UI.riskMeta(k).color}"></i>${UI.riskMeta(k).label}</div>`).join('');
      // The backend labels its own demo geometry. Surface that in the UI, not
      // just in the JSON, so nobody reads the map as operational.
      if (zones.data_status && zones.data_status !== 'REAL') {
        mapNote.innerHTML = `<div class="note synthetic"><b>${UI.esc(zones.data_status)}</b> —
          ${UI.esc(zones.warning || '')}</div>`;
      }
      if (!n) mapNote.innerHTML += UI.empty('Zones returned without geometry.');
    } else {
      document.getElementById('map').outerHTML =
        UI.failed('the risk map', zonesR.reason && zonesR.reason.message, 'dash');
    }

    /* ---------- zone bars ---------- */
    const zb = document.getElementById('zonebars');
    if (zones && zones.features && zones.features.length) {
      const rows = zones.features
        .map(f => ({
          label: f.properties.name || f.properties.zone_id,
          value: f.properties.human_risk,
          display: f.properties.human_risk.toFixed(2),
          color: UI.riskMeta(f.properties.risk_level).color
        }))
        .sort((a, b) => b.value - a.value);
      zb.innerHTML = bars(rows, Math.max(...rows.map(r => r.value)) || 1);
    } else {
      zb.innerHTML = zones ? UI.empty('No zones for this location.')
        : UI.failed('zone risk', zonesR.reason && zonesR.reason.message, 'dash');
    }

    /* ---------- vulnerability drivers ----------
       Averages ZoneProperties.vulnerability_contributions across zones. This
       is a real backend field, unlike the mockup's exposure-group split. */
    const vb = document.getElementById('vulnbars');
    if (zones && zones.features && zones.features.length) {
      const acc = {}, n = zones.features.length;
      zones.features.forEach(f => {
        Object.entries(f.properties.vulnerability_contributions || {})
          .forEach(([k, v]) => { acc[k] = (acc[k] || 0) + Number(v); });
      });
      // Machine field names truncate into ambiguity in a narrow panel --
      // historical_heat_exposure and historical_heat_mortality both render as
      // "Historical Hea...". Name them the way a user reads them instead.
      const NAMES = {
        elderly_population: 'Elderly residents',
        outdoor_workers: 'Outdoor workers',
        population_density: 'Population density',
        healthcare_accessibility: 'Healthcare access',
        historical_heat_exposure: 'Past heat exposure',
        historical_heat_mortality: 'Past heat deaths'
      };
      const rows = Object.entries(acc)
        .map(([k, v]) => ({
          label: NAMES[k] || k.replace(/_/g, ' '),
          value: v / n, display: (v / n).toFixed(3), color: '#8B004A'
        }))
        .sort((a, b) => b.value - a.value);
      vb.innerHTML = rows.length ? bars(rows, Math.max(...rows.map(r => r.value)) || 1)
        : UI.empty('No contribution breakdown returned.');
    } else {
      vb.innerHTML = UI.failed('vulnerability drivers', '', 'dash');
    }

    /* ---------- trajectory ---------- */
    const tr = document.getElementById('trend');
    if (traj) {
      tr.innerHTML = trendChart(traj.forecast || []);
      document.getElementById('traj-sub').textContent =
        `${traj.days_returned} days · model horizon ${traj.model_horizon_days} d · peak ${traj.peak_risk} on ${UI.humanDate(traj.peak_date)}`;
    } else {
      const m = trajR.reason || {};
      tr.innerHTML = m.status === 503
        ? UI.empty('The ML model is not loaded on the server, so no trajectory is available.')
        : UI.failed('the forecast', m.message, 'dash');
    }

    /* ---------- thermal ---------- */
    const th = document.getElementById('thermal');
    if (thermal) {
      const t = thermal.thermal || {};
      const cell = (label, v, unit, digits) => {
        const s = UI.num(v, unit, digits);
        return `<div class="m"><span>${UI.esc(label)}</span>${
          s ? `<b>${UI.esc(s)}</b>` : `<b class="na">Unavailable</b>`}</div>`;
      };
      th.innerHTML = `<div class="mini">
          ${cell('Temperature', t.temperature, ' °C')}
          ${cell('Humidity', t.relative_humidity, '%', 0)}
          ${cell('Wind', t.wind_speed, ' km/h')}
          ${cell('Heat Index', t.heat_index, ' °C')}
          ${cell('WBGT', t.wbgt, ' °C')}
          ${cell('UTCI', t.utci, ' °C')}
        </div>
        ${t.utci === null ? `<div class="note">UTCI is returned as unavailable rather than
          extrapolated: the model is undefined above 50 °C, which Indian extremes exceed.</div>` : ''}
        ${t.wbgt_category === 'NOT_CLASSIFIED' ? `<div class="note">WBGT is a shade
          approximation, so ISO 7243 exposure limits are deliberately not applied.</div>` : ''}`;
      document.getElementById('thermal-sub').textContent =
        `Observed ${new Date(thermal.observed_at).toLocaleString('en-IN')} · ${thermal.provider || ''}`;
    } else {
      th.innerHTML = UI.failed('thermal indicators', thermalR.reason && thermalR.reason.message, 'dash');
    }

    /* ---------- alerts (one call per zone) ---------- */
    const al = document.getElementById('alerts');
    let alerts = [];
    if (zones && zones.features && zones.features.length) {
      const settled = await Promise.allSettled(
        zones.features.slice(0, 8).map(f =>
          API.evaluateAlert(f.properties.zone_id, days, { signal })
            .then(a => ({ a, name: f.properties.name || f.properties.zone_id }))));
      if (signal.aborted) return;
      alerts = settled.filter(s => s.status === 'fulfilled').map(s => s.value);

      const active = alerts.filter(x => x.a.alert_required);
      al.innerHTML = active.length ? `<div class="alist">` + active.map(({ a, name }) => `
          <div class="aitem">
            <i class="dot" style="background:${UI.riskMeta(a.alert_level).color};margin-top:4px"></i>
            <div class="txt"><b>${UI.esc(a.priority)} — ${UI.esc(a.alert_level)}</b>
              <span>${UI.esc(name)} · peak ${UI.esc(a.forecast_peak)} on ${UI.humanDate(a.peak_date)}</span>
              <span style="display:block;margin-top:3px">${UI.esc(a.reason)}</span></div>
          </div>`).join('') + `</div>
          <div class="note">Recommended actions are decision-support text, not medical
          instructions, and are never dispatched automatically.</div>`
        : (alerts.length
            ? UI.empty('No zone currently meets the alert threshold.')
            : UI.failed('alerts', 'The alert service did not respond.', 'dash'));
    } else {
      al.innerHTML = UI.empty('Alerts are evaluated per zone; no zones are available.');
    }

    /* ---------- KPIs (computed only from what actually arrived) ---------- */
    const feats = (zones && zones.features) || [];
    const highBands = ['HIGH', 'VERY_HIGH', 'EXTREME'];
    const worst = feats.length
      ? feats.reduce((a, b) => (b.properties.human_risk > a.properties.human_risk ? b : a))
      : null;

    document.getElementById('kpis').innerHTML = [
      UI.kpi(UI.ICON.risk, 'Highest Zone Risk',
        worst ? UI.riskMeta(worst.properties.risk_level).label : null,
        worst ? `${worst.properties.name || worst.properties.zone_id} · score ${worst.properties.human_risk.toFixed(2)}` : ''),
      UI.kpi(UI.ICON.zones, 'High-Risk Zones',
        feats.length ? `${feats.filter(f => highBands.includes(f.properties.risk_level)).length} of ${feats.length}` : null,
        feats.length ? 'At HIGH or above' : ''),
      UI.kpi(UI.ICON.heat, 'Heat Index (now)',
        thermal && thermal.thermal ? UI.num(thermal.thermal.heat_index, ' °C') : null,
        CFG.DEFAULT_COORDS.label),
      UI.kpi(UI.ICON.peak, 'Forecast Peak Band',
        traj ? UI.riskMeta(traj.peak_risk).label : null,
        traj ? `${UI.bandRange(traj.peak_risk) || ''} · ${UI.humanDate(traj.peak_date)}` : ''),
      UI.kpi(UI.ICON.bell, 'Zones Requiring Alert',
        alerts.length ? String(alerts.filter(x => x.a.alert_required).length) : null,
        alerts.length ? `of ${alerts.length} evaluated` : ''),
      UI.kpi(UI.ICON.vuln, 'Mean Vulnerability',
        feats.length ? (feats.reduce((s, f) => s + f.properties.vulnerability, 0) / feats.length).toFixed(2) : null,
        feats.length ? 'Across zones' : '')
    ].join('');
  }

  window.HS_PAGES = window.HS_PAGES || {};
  window.HS_PAGES.dashboard = { title: 'Command Centre', render };
})();
