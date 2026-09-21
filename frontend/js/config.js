/* HeatSentinal - runtime configuration.
 * Override in deployment by setting window.HEAT_SENTINEL_CONFIG before
 * this file loads (see index.html). No secrets belong in here: the backend
 * needs no API key, and anything sensitive stays server-side. */
window.HS_CONFIG = Object.assign({
  API_BASE_URL: 'http://127.0.0.1:8000/api/v1',
  TIMEOUT_MS: 30000,
  // Delhi. The shipped demo zones are drawn over this city, so the default
  // view matches the only area the backend has zone polygons for.
  DEFAULT_COORDS: { lat: 28.6139, lon: 77.2090, label: 'Delhi' },
  MAP_CENTER: [28.6139, 77.2090],
  MAP_ZOOM: 11
}, window.HEAT_SENTINEL_CONFIG || {});

/* Risk semantics. Kept identical to the backend's five hazard bands plus the
 * deliberate NOT_CLASSIFIED state used by WBGT. */
window.HS_RISK = {
  LOW:            { color: '#10B981', label: 'Low' },
  MODERATE:       { color: '#F59E0B', label: 'Moderate' },
  HIGH:           { color: '#F97316', label: 'High' },
  VERY_HIGH:      { color: '#EF4444', label: 'Very high' },
  EXTREME:        { color: '#B91C1C', label: 'Extreme' },
  NOT_CLASSIFIED: { color: '#6B7280', label: 'Not classified' }
};

window.HS_PRIORITY = {
  ROUTINE:  '#6B7280',
  ELEVATED: '#F59E0B',
  URGENT:   '#F97316',
  CRITICAL: '#B91C1C'
};
