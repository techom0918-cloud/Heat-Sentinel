/* My Heat Profile — personalisation layer.
 *
 * Additive: this page touches no existing view and recomputes nothing. It
 * collects answers, PUTs them to the three separate backend records, then
 * POSTs for a score that the backend calculates.
 *
 * Authentication is being built separately. The user id is a constant here;
 * swapping it for the authenticated id is the only change needed later. */
(function () {
  const API = window.HS_API, UI = window.HS_UI;
  const P = (window.HS_PAGES = window.HS_PAGES || {});

  const USER_ID = 'demo_user_001';   // replace with the authenticated id

  const sel = (name, label, opts, value) =>
    `<label class="fld"><span>${UI.esc(label)}</span>
      <select class="field" name="${name}">${opts.map(([v, t]) =>
        `<option value="${v}"${v === value ? ' selected' : ''}>${UI.esc(t)}</option>`).join('')}
      </select></label>`;

  const check = (name, label, on) =>
    `<label style="display:flex;gap:8px;align-items:center;font-size:12.5px;padding:5px 0">
      <input type="checkbox" name="${name}"${on ? ' checked' : ''}><span>${UI.esc(label)}</span></label>`;

  async function render(root, ctx) {
    root.innerHTML = `
      ${UI.panel('My Heat Profile',
        'Your own risk, combining current conditions with how you respond to heat', `
        <div class="note">This estimates heat risk from what you tell us. It is
          not a medical diagnosis and cannot assess your health. Answers about
          today are stored separately from your stable profile and are not kept
          as part of it.</div>

        <h3 style="font-size:13.5px;margin:16px 0 8px;color:#8B004A">About you</h3>
        <div id="fProfile" class="form-grid">
          ${sel('age_group', 'Age', [
            ['under_18','Under 18'],['18_30','18 – 30'],['31_50','31 – 50'],
            ['51_65','51 – 65'],['over_65','65+']], '31_50')}
          ${UI.input('height_cm', 'Height (cm)', 170)}
          ${UI.input('weight_kg', 'Weight (kg)', 68)}
          <label class="fld"><span>Country of residence</span>
            <input class="field" type="text" name="country_of_residence"
              placeholder="e.g. India" maxlength="80"></label>
          ${sel('usual_climate', 'Climate you are used to', [
            ['cold','Cold'],['mild','Mild'],['warm','Warm'],
            ['hot_humid','Hot / humid']], 'mild')}
          ${sel('time_in_region', 'How long in Delhi-NCR', [
            ['first_3_days','First 3 days'],['days_4_7','4–7 days'],
            ['weeks_1_4','1–4 weeks'],['over_a_month','More than a month']], 'over_a_month')}
          ${sel('experienced_over_40c', 'Been in heat above 40 °C before', [
            ['true','Yes'],['false','No']], 'true')}
          ${sel('heat_comfort', 'How you feel in Delhi heat now', [
            ['very_comfortable','Very comfortable'],
            ['somewhat_comfortable','Somewhat comfortable'],
            ['uncomfortable','Uncomfortable'],
            ['extremely_uncomfortable','Extremely uncomfortable']], 'somewhat_comfortable')}
        </div>

        <div class="note">Your country is stored for context only. It never
          affects your score — where you live does not determine heat tolerance.
          How long you have been in this climate does, so that is what we use.</div>

        <h3 style="font-size:13.5px;margin:18px 0 8px;color:#8B004A">Today</h3>
        <div id="fDaily" class="form-grid">
          ${sel('outdoor_duration', 'Time outdoors today', [
            ['under_30_min','Under 30 minutes'],['min_30_to_2h','30 min – 2 hours'],
            ['h2_to_4','2–4 hours'],['over_4h','More than 4 hours']], 'min_30_to_2h')}
          ${sel('outdoor_window', 'Mainly when', [
            ['morning','Morning (before 11am)'],['midday','11am – 3pm'],
            ['afternoon','3pm – 6pm'],['evening_night','Evening / night']], 'morning')}
          ${sel('activity', 'Doing what', [
            ['sightseeing','Sightseeing / walking'],['sports','Sports / exercise'],
            ['work','Work'],['shopping','Shopping'],['travelling','Travelling'],
            ['mostly_indoors','Mostly indoors']], 'sightseeing')}
          ${UI.input('daily_water_litres', 'Water you usually drink (litres/day)', 2)}
          ${sel('fluids_today', 'Had enough fluids today', [
            ['yes','Yes'],['not_sure','Not sure'],['no','No']], 'yes')}
          ${sel('clothing', 'Wearing outdoors', [
            ['light_loose','Light, loose'],['normal','Normal'],
            ['heavy_dark','Heavy / dark']], 'normal')}
        </div>
        <div class="three" style="margin-top:4px">
          <div>${check('alcohol_today', 'Alcohol today')}
               ${check('caffeine_today', 'A lot of caffeine today')}</div>
          <div>${check('water_access', 'Water available', true)}
               ${check('shade_access', 'Shade or AC available', true)}</div>
          <div>${check('hat_access', 'Hat or umbrella')}
               ${check('sunscreen_access', 'Sunscreen')}</div>
        </div>

        <h3 style="font-size:13.5px;margin:18px 0 8px;color:#8B004A">Health context
          <span style="font-weight:400;font-size:11.5px;color:#6F6A66">— optional</span></h3>
        <div id="fHealth" class="form-grid">
          ${sel('heat_sensitive', 'Any condition or medication that makes you more sensitive to heat', [
            ['prefer_not_to_say','Prefer not to say'],['no','No'],['yes','Yes']], 'prefer_not_to_say')}
          ${sel('pregnancy_status', 'Pregnant', [
            ['prefer_not_to_say','Prefer not to say'],['no','No'],['yes','Yes']], 'prefer_not_to_say')}
          ${sel('status', 'Is it current', [
            ['unknown','Not sure'],['active','Current'],['resolved','Resolved']], 'unknown')}
        </div>
        <label class="fld" style="margin-top:10px"><span>Any specific condition
          you want to note (optional)</span>
          <input class="field" type="text" name="condition_note"
            placeholder="e.g. autoimmune condition, on medication" maxlength="300"></label>
        <div class="note">Nothing here is diagnosed by this system — it is only
          what you choose to tell us, it is editable at any time, and a condition
          marked resolved stops affecting your score.</div>

        <h3 style="font-size:13.5px;margin:18px 0 8px;color:#8B004A">Feeling unwell right now?</h3>
        <div class="chips" id="fSymptoms">
          ${[['unusual_thirst','Unusual thirst'],['headache','Headache'],
             ['dizziness','Dizziness / light-headedness'],
             ['weakness','Weakness or unusual tiredness'],
             ['nausea','Nausea / vomiting'],['muscle_cramps','Muscle cramps'],
             ['heavy_sweating','Heavy sweating'],
             ['confusion','Confusion or unusual behaviour'],
             ['fainting','Fainting'],
             ['difficulty_staying_awake','Difficulty staying awake'],
             ['not_sweating','Stopped sweating']].map(([v,t]) =>
            `<button type="button" class="chip" data-sym="${v}" aria-pressed="false">${t}</button>`).join('')}
        </div>
        <div class="note">These are never scored. Early signs get practical
          advice; signs that can mean heat stroke get urgent guidance instead.</div>

        <div class="row" style="margin-top:16px">
          <button class="btn" id="calc">Calculate my heat risk</button>
          <span id="status" style="font-size:12px;color:#6F6A66"></span>
        </div>`)}
      <div id="result" style="margin-top:12px"></div>`;

    document.getElementById('fSymptoms').addEventListener('click', (e) => {
      const b = e.target.closest('[data-sym]'); if (!b) return;
      b.setAttribute('aria-pressed', b.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
    });

    document.getElementById('calc').addEventListener('click', () => submit(ctx));
  }

  async function submit(ctx) {
    const out = document.getElementById('result');
    const status = document.getElementById('status');
    out.innerHTML = UI.loading('your personalised risk');
    status.textContent = '';

    try {
      const pf = UI.readForm(document.getElementById('fProfile'));
      const df = UI.readForm(document.getElementById('fDaily'));
      const hf = UI.readForm(document.getElementById('fHealth'));
      const symptoms = [...document.querySelectorAll('[data-sym][aria-pressed="true"]')]
        .map(b => b.dataset.sym);

      // Checkboxes only appear in readForm when ticked.
      const bools = ['alcohol_today','caffeine_today','water_access',
                     'shade_access','hat_access','sunscreen_access'];
      bools.forEach(k => { df[k] = df[k] === true; });

      // Three separate records, three separate calls — matching the backend's
      // deliberate split between stable, health and daily data.
      await API.putProfile({
        user_id: USER_ID, age_group: pf.age_group,
        height_cm: pf.height_cm, weight_kg: pf.weight_kg,
        country_of_residence: pf.country_of_residence || null,
        usual_climate: pf.usual_climate, time_in_region: pf.time_in_region,
        experienced_over_40c: pf.experienced_over_40c === 'true',
        heat_comfort: pf.heat_comfort
      });
      await API.putHealth({
        user_id: USER_ID, heat_sensitive: hf.heat_sensitive,
        pregnancy_status: hf.pregnancy_status, status: hf.status,
        condition_note: hf.condition_note || null
      });
      await API.putAssessment({ user_id: USER_ID, ...df, current_symptoms: symptoms });

      const r = await API.personalRisk({
        user_id: USER_ID, latitude: ctx.lat, longitude: ctx.lon
      });
      out.innerHTML = renderResult(r);
      status.textContent = 'Saved and scored.';
      out.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) {
      out.innerHTML = UI.failed('your personalised risk', e.message);
    }
  }

  function renderResult(r) {
    const pct = (v) => Math.round(v * 100);
    const meta = UI.riskMeta(r.risk_level);

    // Red-flag symptoms lead, above everything else on the page.
    const n = r.safety_notice;
    const urgent = n ? `
      <div class="panel" style="border-left:5px solid ${n.urgent ? '#B91C1C' : '#F59E0B'};margin-bottom:12px">
        <div class="panel-body" style="padding-top:14px">
          <h2 style="color:${n.urgent ? '#B91C1C' : '#B45309'};font-size:17px">${
            n.urgent ? 'Get help now' : 'Stop and cool down'}</h2>
          <p style="font-size:13.5px;margin:8px 0">${UI.esc(n.message)}</p>
        </div></div>` : '';

    const cell = (l, v, u, d) => {
      const s = UI.num(v, u, d);
      return `<div class="m"><span>${UI.esc(l)}</span>${
        s ? `<b>${UI.esc(s)}</b>` : `<b class="na">Unavailable</b>`}</div>`;
    };

    return urgent + `
      <div class="two">
        ${UI.panel('Your personalised risk', 'Conditions today combined with your profile', `
          <div class="big" style="color:${meta.color}">${pct(r.personalised_risk_score)} <span style="font-size:17px">/ 100</span></div>
          <div style="margin:6px 0 14px">${UI.riskPill(r.risk_level)}</div>
          <div class="two" style="gap:9px">
            <div class="m" style="border:1px solid var(--rule);border-radius:8px;padding:10px">
              <span style="font-size:11px;color:#6F6A66">Environmental risk</span>
              <b style="font-family:'Source Serif 4',serif;font-size:19px;display:block">${pct(r.environmental_risk_score)} / 100</b>
              <span style="font-size:11px;color:#6F6A66">${UI.esc(r.environmental_risk_level)}</span></div>
            <div class="m" style="border:1px solid var(--rule);border-radius:8px;padding:10px">
              <span style="font-size:11px;color:#6F6A66">Your vulnerability</span>
              <b style="font-family:'Source Serif 4',serif;font-size:19px;display:block">${pct(r.personal_vulnerability_score)} / 100</b>
              <span style="font-size:11px;color:#6F6A66">from your answers</span></div>
          </div>
          <div class="note">${UI.esc(r.method)}</div>`)}

        ${UI.panel('Conditions right now', 'From the existing thermal engine, unchanged', `
          <div class="mini">
            ${cell('Temperature', r.thermal.temperature, ' °C')}
            ${cell('Humidity', r.thermal.relative_humidity, '%', 0)}
            ${cell('Wind', r.thermal.wind_speed, ' km/h')}
            ${cell('Heat Index', r.thermal.heat_index, ' °C')}
            ${cell('WBGT', r.thermal.wbgt, ' °C')}
            ${cell('UTCI', r.thermal.utci, ' °C')}
            ${cell('Wet bulb', r.thermal.wet_bulb, ' °C')}
          </div>
          ${r.thermal.utci === null ? `<div class="note">UTCI is reported as
            unavailable rather than extrapolated beyond its valid range.</div>` : ''}`)}
      </div>

      ${UI.panel('Why is my risk this level?', 'Every factor, with its weight', `
        ${r.top_drivers.length ? `<ul style="margin:0 0 12px 16px;padding:0;font-size:13px">
          ${r.top_drivers.map(d => `<li style="margin-bottom:4px">${UI.esc(d)}</li>`).join('')}</ul>` : ''}
        <div class="bars">${r.factors.map(f => `
          <div class="bar-row"><span title="${UI.esc(f.detail)}">${UI.esc(f.label)}</span>
            <div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, f.score * 100)}%;background:#8B004A"></div></div>
            <b>${(f.contribution * 100).toFixed(1)}</b></div>`).join('')}</div>
        <div class="note">The right-hand number is each factor's contribution to
          your vulnerability score out of 100 — its own level multiplied by its
          weight. Weights are prototype values, not fitted to health outcomes.</div>`)}

      ${UI.panel('What you can do', 'Based on the answers you gave', `
        <ul style="margin:0 0 0 16px;padding:0;font-size:13.5px">
          ${r.recommendations.map(x => `<li style="margin-bottom:6px">${UI.esc(x)}</li>`).join('')}</ul>
        ${UI.listNote('Assumptions', r.assumptions)}
        ${UI.listNote('Limitations', r.limitations)}
        ${UI.disclaimer(r.disclaimer)}`)}`;
  }

  P.personal = { title: 'My Heat Profile', render };
})();
