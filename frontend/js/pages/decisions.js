/* Action Simulator, Action Optimizer, Alerts & Warnings.
 *
 * Language discipline: the backend models risk reduction under stated
 * assumptions. It does not estimate lives saved, and neither does this UI.
 * Every figure here is labelled "modelled" and carries the backend's own
 * assumptions and disclaimer text verbatim. */
(function () {
  const API = window.HS_API, UI = window.HS_UI;
  const P = (window.HS_PAGES = window.HS_PAGES || {});

  async function zoneOptions(ctx) {
    try {
      const z = await API.zones(ctx.lat, ctx.lon, { signal: ctx.signal });
      return z.features.map(f => ({
        id: f.properties.zone_id,
        label: f.properties.name || f.properties.zone_id
      }));
    } catch { return []; }
  }

  const snapshot = (s, label) => `
    <div><div style="font-size:11.5px;color:#6F6A66">${UI.esc(label)}</div>
      <div class="big" style="font-size:27px">${s.risk_score.toFixed(3)}</div>
      <div style="margin-top:4px">${UI.riskPill(s.risk_level)}</div>
      <div style="font-size:11px;color:#6F6A66;margin-top:5px">
        thermal ${s.thermal_stress.toFixed(3)} · vulnerability ${s.vulnerability.toFixed(3)}</div></div>`;

  /* ---------------- Action Simulator ---------------- */
  P.simulator = { title: 'Action Simulator', render: async (root, ctx) => {
    root.innerHTML = `<div class="two">
      ${UI.panel('Choose Interventions', 'Only the measures the backend supports', `<div id="sform">${UI.loading('the intervention catalogue')}</div>`)}
      ${UI.panel('Modelled Outcome', 'Risk reduction under stated assumptions', `<div id="sout">${UI.empty('Pick at least one intervention and run the simulation.')}</div>`)}
    </div>`;

    const [cat, zones] = await Promise.all([
      API.interventionTypes({ signal: ctx.signal }).catch(e => ({ error: e })),
      zoneOptions(ctx)
    ]);
    if (ctx.signal.aborted) return;

    if (cat.error) {
      document.getElementById('sform').innerHTML = UI.failed('the intervention catalogue', cat.error.message);
      return;
    }

    document.getElementById('sform').innerHTML = `
      <label class="fld" style="margin-bottom:11px"><span>Zone</span>
        <select class="field" id="szone">${zones.map(z =>
          `<option value="${UI.esc(z.id)}">${UI.esc(z.label)}</option>`).join('')}</select></label>
      <div id="slist">${cat.interventions.map(i => `
        <div style="border:1px solid var(--rule);border-radius:8px;padding:10px;margin-bottom:8px">
          <label style="display:flex;gap:8px;align-items:flex-start;font-size:13px">
            <input type="checkbox" data-type="${UI.esc(i.type)}" style="margin-top:3px">
            <span><b>${UI.esc(i.label)}</b>
              <span class="tag" style="margin-left:6px">${UI.esc(i.channel)}</span>
              <br><em style="font-size:11px;color:#6F6A66;font-style:normal">${UI.esc(i.assumption)}</em></span>
          </label>
          <div style="display:flex;gap:9px;align-items:center;margin-top:8px">
            <span style="font-size:11px;color:#6F6A66">Coverage</span>
            <input type="range" min="0" max="1" step="0.05" value="0.5"
              data-cov="${UI.esc(i.type)}" style="flex:1">
            <b style="font-size:11.5px;min-width:38px;text-align:right" data-covlbl="${UI.esc(i.type)}">50%</b>
          </div></div>`).join('')}</div>
      <button class="btn" id="srun">Run simulation</button>
      ${UI.disclaimer(cat.disclaimer)}`;

    document.getElementById('slist').addEventListener('input', (e) => {
      const r = e.target.closest('[data-cov]'); if (!r) return;
      document.querySelector(`[data-covlbl="${r.dataset.cov}"]`).textContent =
        Math.round(r.value * 100) + '%';
    });

    document.getElementById('srun').addEventListener('click', async () => {
      const out = document.getElementById('sout');
      const picked = [...document.querySelectorAll('[data-type]:checked')].map(cb => ({
        type: cb.dataset.type,
        coverage: Number(document.querySelector(`[data-cov="${cb.dataset.type}"]`).value)
      }));
      if (!picked.length) { out.innerHTML = UI.empty('Select at least one intervention.'); return; }
      out.innerHTML = UI.loading('the simulation');
      try {
        const r = await API.simulate({
          zone_id: document.getElementById('szone').value, interventions: picked });
        out.innerHTML = `
          <div class="two" style="margin-bottom:14px">
            ${snapshot(r.baseline, 'Baseline risk')}
            ${snapshot(r.simulation, 'Modelled risk after intervention')}</div>
          ${UI.kv([
            ['Modelled risk reduction', r.estimated_risk_reduction.toFixed(4)],
            ['As a percentage', r.estimated_risk_reduction_percent.toFixed(1) + '%'],
            ['Risk band changed', r.risk_level_changed ? 'Yes' : 'No']
          ])}
          <h3 style="font-size:13px;margin:14px 0 7px">Applied measures</h3>
          <div class="scroll-x"><table class="dt">
            <tr><th>Measure</th><th>Channel</th><th>Coverage</th><th>Max effect</th><th>Applied</th></tr>
            ${r.applied_interventions.map(a => `<tr><td>${UI.esc(a.label)}</td>
              <td>${UI.esc(a.channel)}</td><td>${(a.coverage * 100).toFixed(0)}%</td>
              <td>${a.max_effect.toFixed(3)}</td><td>${a.applied_effect.toFixed(4)}</td></tr>`).join('')}
          </table></div>
          ${UI.listNote('Assumptions', r.assumptions)}
          ${UI.disclaimer(r.disclaimer)}`;
      } catch (e) { out.innerHTML = UI.failed('the simulation', e.message); }
    });
  }};

  /* ---------------- Action Optimizer ---------------- */
  P.optimizer = { title: 'Action Optimizer', render: async (root, ctx) => {
    const zones = await zoneOptions(ctx);
    if (ctx.signal.aborted) return;
    root.innerHTML = `<div class="two">
      ${UI.panel('Constraints', 'Budget and resources available to the planner', `
        <div id="oform">
          <label class="fld" style="margin-bottom:11px"><span>Zone</span>
            <select class="field" name="zone_id">${zones.map(z =>
              `<option value="${UI.esc(z.id)}">${UI.esc(z.label)}</option>`).join('')}</select></label>
          <div class="form-grid">
            ${UI.input('budget', 'Budget (₹)', 500000, '1000')}
            ${UI.input('cooling_centers', 'Cooling centres', 5, '1')}
            ${UI.input('water_tankers', 'Water tankers', 10, '1')}
            ${UI.input('field_workers', 'Field workers', 20, '1')}
          </div></div>
        <button class="btn" id="orun">Optimise plan</button>`)}
      ${UI.panel('Recommended Plan', 'Chosen by the backend optimiser', `<div id="oout">${UI.empty('Set constraints and optimise to see a plan.')}</div>`)}
    </div>`;

    document.getElementById('orun').addEventListener('click', async () => {
      const out = document.getElementById('oout');
      out.innerHTML = UI.loading('the optimiser');
      try {
        const f = UI.readForm(document.getElementById('oform'));
        const r = await API.optimize({
          zone_id: f.zone_id, budget: f.budget,
          available_resources: {
            cooling_centers: f.cooling_centers,
            water_tankers: f.water_tankers,
            field_workers: f.field_workers
          }
        });
        out.innerHTML = `
          <div class="two" style="margin-bottom:14px">
            <div><div style="font-size:11.5px;color:#6F6A66">Baseline</div>
              <div class="big" style="font-size:27px">${r.baseline_risk.toFixed(3)}</div>
              <div style="margin-top:4px">${UI.riskPill(r.baseline_risk_level)}</div></div>
            <div><div style="font-size:11.5px;color:#6F6A66">Optimised</div>
              <div class="big" style="font-size:27px">${r.optimized_risk.toFixed(3)}</div>
              <div style="margin-top:4px">${UI.riskPill(r.optimized_risk_level)}</div></div></div>
          ${UI.kv([
            ['Modelled risk reduction', r.estimated_risk_reduction.toFixed(4) +
              ` (${r.estimated_risk_reduction_percent.toFixed(1)}%)`],
            ['Risk band changed', r.risk_level_changed ? 'Yes' : 'No'],
            ['Budget used', `₹${r.budget_used.toLocaleString('en-IN')} of ₹${r.budget.toLocaleString('en-IN')}`],
            ['Budget remaining', `₹${r.budget_remaining.toLocaleString('en-IN')}`],
            ['Method', UI.esc(r.method)]
          ])}
          <h3 style="font-size:13px;margin:14px 0 7px">Recommended actions</h3>
          ${r.recommended_actions.length ? `<div class="scroll-x"><table class="dt">
            <tr><th>Action</th><th>Qty</th><th>Coverage</th><th>Unit cost</th><th>Cost</th></tr>
            ${r.recommended_actions.map(a => `<tr><td>${UI.esc(a.type)}</td>
              <td>${a.quantity}</td><td>${(a.coverage * 100).toFixed(0)}%</td>
              <td>₹${a.unit_cost.toLocaleString('en-IN')}</td>
              <td>₹${a.cost.toLocaleString('en-IN')}</td></tr>`).join('')}
          </table></div>` : UI.empty('The optimiser selected no actions within these constraints.')}
          ${UI.listNote('Assumptions', r.assumptions)}
          ${UI.disclaimer(r.disclaimer)}`;
      } catch (e) { out.innerHTML = UI.failed('the optimiser', e.message); }
    });
  }};

  /* ---------------- Alerts & Warnings ---------------- */
  P.alerts = { title: 'Alerts & Warnings', render: async (root, ctx) => {
    root.innerHTML = UI.panel('Zone Alerts',
      'Each zone evaluated against its forecast peak',
      `<div id="al">${UI.loading('alerts')}</div>`);

    let zones;
    try { zones = await API.zones(ctx.lat, ctx.lon, { signal: ctx.signal }); }
    catch (e) {
      if (ctx.signal.aborted) return;
      document.getElementById('al').innerHTML = UI.failed('alerts', e.message);
      return;
    }
    if (ctx.signal.aborted) return;

    const settled = await Promise.allSettled(zones.features.map(f =>
      API.evaluateAlert(f.properties.zone_id, ctx.days, { signal: ctx.signal })
        .then(a => ({ a, name: f.properties.name || f.properties.zone_id }))));
    if (ctx.signal.aborted) return;

    const ok = settled.filter(s => s.status === 'fulfilled').map(s => s.value);
    if (!ok.length) {
      document.getElementById('al').innerHTML = UI.failed('alerts', 'No zone could be evaluated.');
      return;
    }
    const PRI = window.HS_PRIORITY;
    const sorted = ok.sort((x, y) => Number(y.a.alert_required) - Number(x.a.alert_required));

    document.getElementById('al').innerHTML = sorted.map(({ a, name }) => `
      <div style="border:1px solid var(--rule);border-left:4px solid ${
        a.alert_required ? (PRI[a.priority] || '#6B7280') : '#E3DCD0'};
        border-radius:8px;padding:12px;margin-bottom:10px">
        <div class="row" style="justify-content:space-between">
          <div><b style="font-size:14px">${UI.esc(name)}</b>
            <span class="tag" style="margin-left:7px">${UI.esc(a.priority)}</span></div>
          <div>${a.alert_required
            ? UI.riskPill(a.alert_level)
            : '<span class="pill" style="background:#6B7280">No alert</span>'}</div></div>
        <p style="font-size:12.5px;margin:8px 0">${UI.esc(a.reason)}</p>
        ${UI.kv([
          ['Current risk', UI.riskPill(a.current_risk)],
          ['Forecast peak', UI.riskPill(a.forecast_peak) + ' on ' + UI.esc(a.peak_date)],
          ['Trend', UI.esc(a.trend)],
          ['Vulnerability', UI.riskPill(a.vulnerability_level)],
          ['Escalation', a.escalation ? UI.esc(a.escalation_label || 'Yes') : 'No']
        ])}
        ${a.recommended_actions && a.recommended_actions.length ? `
          <h3 style="font-size:12.5px;margin:11px 0 6px">Recommended actions</h3>
          <ul style="margin:0 0 0 16px;padding:0;font-size:12.5px">
            ${a.recommended_actions.map(x => `<li>${UI.esc(x)}</li>`).join('')}</ul>` : ''}
        ${UI.listNote('Assumptions', a.assumptions)}
        ${UI.disclaimer(a.disclaimer)}
      </div>`).join('');
  }};
})();
