/* HeatSentinal API client.
 *
 * One method per real backend endpoint. Every path and query parameter here
 * was read off the running app's /openapi.json -- nothing is invented.
 *
 * Note the deliberate parameter inconsistency in the backend: /weather/*
 * takes lat/lon, while /thermal, /forecast and /zones take latitude/longitude.
 * That is documented upstream, so it is honoured rather than "corrected".
 */
(function () {
  const CFG = window.HS_CONFIG;

  class ApiError extends Error {
    constructor(message, status, details) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
      this.details = details || null;
    }
  }

  function qs(params) {
    const p = new URLSearchParams();
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') p.append(k, v);
    });
    const s = p.toString();
    return s ? `?${s}` : '';
  }

  async function request(path, { method = 'GET', body, signal, headers } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort('timeout'), CFG.TIMEOUT_MS);
    // Caller-supplied signal composes with the timeout so a page change
    // cancels in-flight requests instead of letting them land on a dead view.
    if (signal) signal.addEventListener('abort', () => controller.abort(), { once: true });

    try {
      const mergedHeaders = { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(headers || {}) };
      const res = await fetch(CFG.API_BASE_URL + path, {
        method,
        signal: controller.signal,
        headers: Object.keys(mergedHeaders).length ? mergedHeaders : undefined,
        body: body ? JSON.stringify(body) : undefined
      });

      const text = await res.text();
      let data = null;
      try { data = text ? JSON.parse(text) : null; } catch { data = null; }

      if (!res.ok) {
        // The backend wraps every failure in one envelope:
        // { error: { type, message, details } }
        const env = data && data.error;
        throw new ApiError(
          (env && env.message) || `Request failed (${res.status})`,
          res.status,
          (env && env.details) || null
        );
      }
      return data;
    } catch (err) {
      if (err.name === 'AbortError') {
        throw new ApiError('The request timed out.', 0, { path });
      }
      if (err instanceof ApiError) throw err;
      throw new ApiError('Cannot reach the backend.', 0, { path });
    } finally {
      clearTimeout(timer);
    }
  }

  const api = {
    ApiError,

    // --- System -----------------------------------------------------------
    health:        (o) => request('/health', o),
    healthDetails: (o) => request('/health/details', o),
    modelStatus:   (o) => request('/risk/model', o),

    // --- Weather (lat/lon) ------------------------------------------------
    weatherCurrent:  (lat, lon, o) => request(`/weather/current${qs({ lat, lon })}`, o),
    weatherForecast: (lat, lon, days, o) =>
      request(`/weather/forecast${qs({ lat, lon, days })}`, o),

    // --- Thermal (latitude/longitude) -------------------------------------
    thermalCurrent: (latitude, longitude, o) =>
      request(`/thermal/current${qs({ latitude, longitude })}`, o),
    thermalCalculate: (payload, o) =>
      request('/thermal/calculate', { ...o, method: 'POST', body: payload }),

    // --- Vulnerability ----------------------------------------------------
    vulnerability: (payload, o) =>
      request('/vulnerability/calculate', { ...o, method: 'POST', body: payload }),

    // --- Risk -------------------------------------------------------------
    riskPredict: (payload, o) =>
      request('/risk/predict', { ...o, method: 'POST', body: payload }),
    /** explain=true adds real SHAP values. Without it, none are returned. */
    riskForecast: (latitude, longitude, explain, o) =>
      request(`/risk/forecast${qs({ latitude, longitude, explain: explain ? 'true' : undefined })}`, o),

    // --- Trajectory -------------------------------------------------------
    trajectory: (latitude, longitude, days, o) =>
      request(`/forecast/risk${qs({ latitude, longitude, days })}`, o),

    // --- Geospatial -------------------------------------------------------
    zones: (latitude, longitude, o) =>
      request(`/zones/risk${qs({ latitude, longitude })}`, o),

    // --- Interventions ----------------------------------------------------
    interventionTypes: (o) => request('/interventions/types', o),
    simulate: (payload, o) =>
      request('/interventions/simulate', { ...o, method: 'POST', body: payload }),
    optimize: (payload, o) =>
      request('/interventions/optimize', { ...o, method: 'POST', body: payload }),

    // --- Alerts -----------------------------------------------------------
    evaluateAlert: (zone_id, days, o) =>
      request('/alerts/evaluate', { ...o, method: 'POST', body: { zone_id, days } }),

    // --- Health / mortality ----------------------------------------------
    healthData:       (o) => request('/health-data', o),
    healthValidation: (o) => request('/health-data/validation', o),

    // --- Accounts (Phase 16) -----------------------------------------------
    securityQuestions: (o) => request('/auth/security-questions', o),
    signup: (payload, o) => request('/auth/signup', { ...o, method: 'POST', body: payload }),
    login:  (payload, o) => request('/auth/login',  { ...o, method: 'POST', body: payload }),
    me:     (token, o) => request('/auth/me', {
      ...o,
      headers: { Authorization: `Bearer ${token}` }
    }),
    forgotPasswordVerify: (payload, o) =>
      request('/auth/forgot-password/verify', { ...o, method: 'POST', body: payload }),
    forgotPasswordReset: (payload, o) =>
      request('/auth/forgot-password/reset', { ...o, method: 'POST', body: payload })
  };

  window.HS_API = api;
})();
