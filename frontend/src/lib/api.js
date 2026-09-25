const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";
const TOKEN_KEY = "heatsentinel_session_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request(path, { method = "GET", body, params, auth = false } = {}) {
  const url = new URL(BASE + path);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
    });
  }

  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  let res;
  try {
    res = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(
      "Could not reach the HeatSentinel backend. Is it running on port 8000?",
      0,
      null
    );
  }

  const isJson = res.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await res.json().catch(() => null) : null;

  if (!res.ok) {
    const message = data?.error?.message || data?.detail || `Request failed (${res.status})`;
    throw new ApiError(message, res.status, data);
  }
  return data;
}

export const api = {
  // --- Health -----------------------------------------------------------
  health: () => request("/health"),

  // --- Weather / thermal --------------------------------------------------
  currentThermal: (latitude, longitude) =>
    request("/thermal/current", { params: { latitude, longitude } }),
  weatherForecast: (lat, lon, days = 5) =>
    request("/weather/forecast", { params: { lat, lon, days } }),

  // --- Zones / spatial (Phase 10 -- prototype demo zones) ----------------
  zoneRisk: (latitude, longitude) =>
    request("/zones/risk", { params: { latitude, longitude } }),

  // --- 300m grid (Phase 9 -- deferred; will 503 until it exists) --------
  gridRisk: (bbox) => request("/grid/risk", { params: bbox }),

  // --- 3-day hazard forecast + SHAP (Phase 7/11, existing trained model) -
  hazardForecast: (latitude, longitude, { explain = false, topFactors = 7 } = {}) =>
    request("/risk/forecast", {
      params: { latitude, longitude, explain, top_factors: topFactors },
    }),
  riskTrajectory: (latitude, longitude, days = 3) =>
    request("/forecast/risk", { params: { latitude, longitude, days } }),
  modelStatus: () => request("/risk/model"),

  // --- Heat Index classifier (Phase 8/11 -- new model, single-cell) -----
  heatIndexModel: () => request("/heat-index/model"),
  heatIndexPredict: (features) => request("/heat-index/predict", { method: "POST", body: { features } }),
  heatIndexExplain: (features) => request("/heat-index/explain", { method: "POST", body: { features } }),

  // --- Auth ---------------------------------------------------------------
  securityQuestions: () => request("/auth/security-questions"),
  signup: (email, password, security_answers) =>
    request("/auth/signup", { method: "POST", body: { email, password, security_answers } }),
  login: (email, password) =>
    request("/auth/login", { method: "POST", body: { email, password } }),
  me: () => request("/auth/me", { auth: true }),

  // --- Personalisation (Phase 13 -- auth-aware) ---------------------------
  getProfile: (user_id) => request("/personal/profile", { params: { user_id }, auth: true }),
  putProfile: (payload) => request("/personal/profile", { method: "PUT", body: payload, auth: true }),
  getHealth: (user_id) => request("/personal/health-profile", { params: { user_id }, auth: true }),
  putHealth: (payload) => request("/personal/health-profile", { method: "PUT", body: payload, auth: true }),
  putAssessment: (payload) => request("/personal/assessment", { method: "PUT", body: payload, auth: true }),
  personalRisk: (payload) => request("/personal/risk", { method: "POST", body: payload, auth: true }),

  // --- Alerts / interventions ----------------------------------------------
  evaluateAlert: (zone_id, days = 3) =>
    request("/alerts/evaluate", { method: "POST", body: { zone_id, days } }),
  interventionTypes: () => request("/interventions/types"),
  simulateInterventions: (zone_id, interventions) =>
    request("/interventions/simulate", { method: "POST", body: { zone_id, interventions } }),

  // --- Vulnerability (Human Vulnerability Engine) -------------------------
  calculateVulnerability: (payload) =>
    request("/vulnerability/calculate", { method: "POST", body: payload }),

  // --- Health Risk Engine (thermal + vulnerability -> combined risk) -----
  predictRisk: (payload) => request("/risk/predict", { method: "POST", body: payload }),

  // --- Thermal Stress Engine (user-supplied conditions, no weather fetch) --
  calculateThermal: (payload) => request("/thermal/calculate", { method: "POST", body: payload }),

  // --- Health / Mortality Validation ----------------------------------------
  healthDataValidation: (params) => request("/health-data/validation", { params }),

  // --- AI Action Optimizer -------------------------------------------------
  optimizeInterventions: (payload) =>
    request("/interventions/optimize", { method: "POST", body: payload }),
};

export { ApiError };
