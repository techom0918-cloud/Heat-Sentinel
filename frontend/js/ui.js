/* Shared rendering helpers.
 * The rule that governs this file: a value the backend did not return is
 * rendered as "Unavailable", never as a placeholder number. */
(function () {
  const R = window.HS_RISK;

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /** Renders a number, or the unavailable state when the backend sent null. */
  function num(v, unit, digits) {
    if (v === null || v === undefined || Number.isNaN(v)) return null;
    const d = digits === undefined ? 1 : digits;
    return Number(v).toFixed(d) + (unit || '');
  }

  function riskMeta(level) {
    return R[level] || R.NOT_CLASSIFIED;
  }

  function riskPill(level) {
    const m = riskMeta(level);
    return `<span class="pill" style="background:${m.color}">${esc(m.label)}</span>`;
  }

  function humanDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return esc(iso);
    return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  }

  /* --- async view states ------------------------------------------------ */
  const loading = (what) =>
    `<div class="state"><div class="spin"></div>Loading ${esc(what)}…</div>`;

  const failed = (what, msg, retryId) =>
    `<div class="state"><b>Unable to retrieve ${esc(what)}</b>${esc(msg || '')}` +
    (retryId ? `<br><button data-retry="${esc(retryId)}">Try again</button>` : '') +
    `</div>`;

  const empty = (msg) => `<div class="state"><b>Nothing to show</b>${esc(msg)}</div>`;

  const unavailable = () => `<span class="na">Unavailable</span>`;

  /* --- KPI ---------------------------------------------------------------
   * value === null renders the unavailable state. Callers must pass null
   * rather than substituting a number when an endpoint fails. */
  function kpi(icon, label, value, sub) {
    const v = value === null || value === undefined
      ? `<div class="val na">Unavailable</div>`
      : `<div class="val">${esc(value)}</div>`;
    return `<div class="kpi">
      <div class="ic">${icon}</div>
      <div><div class="lbl">${esc(label)}</div>${v}
      ${sub ? `<div class="sub">${esc(sub)}</div>` : ''}</div>
    </div>`;
  }

  const ICON = {
    risk: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
    zones:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 4 6 2 6-2v14l-6 2-6-2-6 2V6z"/><path d="M9 4v14M15 6v14"/></svg>',
    heat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 14.76V4a2 2 0 0 0-4 0v10.76a4 4 0 1 0 4 0z"/></svg>',
    bell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a2 2 0 0 0 3.4 0"/></svg>',
    peak: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m3 17 6-6 4 4 8-8"/><path d="M17 7h4v4"/></svg>',
    vuln: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 14c1.5-1.5 3-3.3 3-5.5A5.5 5.5 0 0 0 12 5a5.5 5.5 0 0 0-10 3.5C2 10.7 3.5 12.5 5 14l7 7z"/></svg>'
  };

  window.HS_UI = { esc, num, riskMeta, riskPill, humanDate,
                   loading, failed, empty, unavailable, kpi, ICON };
})();

/* Additional helpers used by the module pages. */
(function () {
  const U = window.HS_UI;

  /** Panel wrapper so pages don't repeat markup. */
  U.panel = (title, sub, body, id) =>
    `<section class="panel"${id ? ` id="${id}"` : ''}>
       <div class="panel-head"><div><h2>${U.esc(title)}</h2>
       ${sub ? `<p>${U.esc(sub)}</p>` : ''}</div></div>
       <div class="panel-body">${body}</div></section>`;

  /** Label/value rows for read-only detail blocks. */
  U.kv = (rows) => `<table class="dt">` + rows.map(([k, v]) =>
    `<tr><th style="width:46%">${U.esc(k)}</th><td>${
      v === null || v === undefined ? '<i style="color:#6F6A66">Unavailable</i>' : v}</td></tr>`).join('') + `</table>`;

  /** Number input bound to a named field. */
  U.input = (name, label, value, step, hint) =>
    `<label class="fld"><span>${U.esc(label)}</span>
      <input class="field" type="number" name="${U.esc(name)}" value="${value}"
        step="${step || 'any'}" inputmode="decimal">
      ${hint ? `<em>${U.esc(hint)}</em>` : ''}</label>`;


  /* The band names read as alarm levels ("HIGH") when they are really heat
   * index ranges taken from the NWS thresholds. Showing the range next to the
   * label stops a routine 34 C September day looking like an emergency.
   * Edges come from the model artifact via model_info.heat_index_edges, so
   * this stays correct if they are ever retuned in config. */
  U.bandRange = (level, edges) => {
    const e = edges && edges.length === 4 ? edges : [27, 32, 41, 54];
    const map = {
      LOW:       `below ${e[0]} \u00B0C`,
      MODERATE:  `${e[0]}\u2013${e[1]} \u00B0C`,
      HIGH:      `${e[1]}\u2013${e[2]} \u00B0C`,
      VERY_HIGH: `${e[2]}\u2013${e[3]} \u00B0C`,
      EXTREME:   `above ${e[3]} \u00B0C`
    };
    return map[level] || null;
  };

  /* NWS wording for the same thresholds, useful as a plain-language gloss. */
  U.bandGloss = {
    LOW: 'no heat caution',
    MODERATE: 'caution',
    HIGH: 'extreme caution',
    VERY_HIGH: 'danger',
    EXTREME: 'extreme danger'
  };

  /** Diverging bar for SHAP: negative left, positive right. */
  U.shapRow = (f, max) => {
    const up = f.direction === 'increases_risk';
    const w = Math.max(2, (f.impact / max) * 48);
    return `<div class="shap">
      <span class="lbl" title="${U.esc(f.feature)}">${U.esc(f.feature_label || f.feature)}</span>
      <span class="track">
        <span class="neg">${!up ? `<i style="width:${w}%"></i>` : ''}</span>
        <span class="axis"></span>
        <span class="pos">${up ? `<i style="width:${w}%"></i>` : ''}</span>
      </span>
      <b>${f.shap_value > 0 ? '+' : ''}${f.shap_value.toFixed(3)}</b></div>`;
  };

  /** Reads every named input inside a container into a plain object. */
  U.readForm = (root) => {
    const out = {};
    root.querySelectorAll('[name]').forEach(el => {
      if (el.type === 'checkbox') { if (el.checked) out[el.name] = true; return; }
      const v = el.value;
      out[el.name] = el.type === 'number' ? (v === '' ? null : Number(v)) : v;
    });
    return out;
  };

  /** Prominent disclaimer block. Used wherever the backend sends one. */
  U.disclaimer = (text) => text
    ? `<div class="note">${U.esc(text)}</div>` : '';

  U.listNote = (title, items) => (items && items.length)
    ? `<div class="note"><b>${U.esc(title)}</b><ul style="margin:5px 0 0 16px;padding:0">${
        items.map(i => `<li>${U.esc(i)}</li>`).join('')}</ul></div>` : '';
})();
