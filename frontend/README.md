# HeatSentinal — frontend

Plain HTML/CSS/JS. No build step, no `npm install`, no bundler.

## Run

Backend, from `backend/`:

    .\.venv\Scripts\Activate.ps1
    uvicorn app.main:app --reload --port 8000

Frontend, from this folder (any static server):

    python -m http.server 5500

Then open <http://127.0.0.1:5500>.

`file://` will not work — the browser blocks `fetch` from that origin. Serve it.

## Pointing at a different API

Edit the `window.HEAT_SENTINEL_CONFIG` block at the top of `index.html`.
No keys or secrets belong there; the backend needs none.

## CORS

The backend must allow the frontend origin. In `backend/.env`:

    CORS_ORIGINS=http://localhost:5500,http://127.0.0.1:5500

Comma-separated string, not JSON — pydantic-settings JSON-decodes list-typed
fields and fails otherwise.

## The ML model

`/forecast/risk`, `/risk/forecast` and the trajectory panel return **503** when
`heat_model.joblib` is absent. That is deliberate: the backend fails loudly
rather than inventing predictions. Put the artifact where `ML_MODEL_PATH`
points before demoing.

## Files

    index.html              shell, script tags, runtime config
    css/heatsentinal.css    design tokens and layout
    vendor/                 Leaflet 1.9.4, vendored so a bad network can't
                            break the demo
    js/config.js            API base URL, map defaults, risk colours
    js/api.js               one method per real backend endpoint
    js/ui.js                shared render helpers and async states
    js/map.js               Leaflet, driven by /zones/risk GeoJSON
    js/app.js               nav, header, hash router, request cancellation
    js/pages/dashboard.js   Command Centre
    js/pages/analysis.js    Thermal Stress, Vulnerability, Heat Risk
    js/pages/intelligence.js  ML Prediction, Explainable AI, Forecast, GIS
    js/pages/decisions.js   Action Simulator, Optimizer, Alerts
    js/pages/transparency.js  Health & Mortality, Data & Sources, System Status

## Rule this codebase follows

A value the backend did not return is rendered as "Unavailable". Nothing is
substituted to make a panel look complete. `HS_UI.kpi()` takes `null` and
renders the unavailable state; callers pass `null` rather than a placeholder.

## Endpoint coverage

All 18 backend endpoints are called by at least one page:

| Page | Endpoints |
|---|---|
| Dashboard | zones/risk, thermal/current, forecast/risk, alerts/evaluate |
| Hyperlocal GIS | zones/risk |
| Heat Risk | thermal/current, risk/predict |
| Thermal Stress | thermal/current, thermal/calculate |
| Vulnerability | vulnerability/calculate, zones/risk |
| ML Prediction | risk/forecast, risk/model |
| Explainable AI | risk/forecast?explain=true |
| Forecast & Trends | forecast/risk |
| Action Simulator | interventions/types, interventions/simulate, zones/risk |
| Action Optimizer | interventions/optimize, zones/risk |
| Alerts & Warnings | zones/risk, alerts/evaluate |
| Health & Mortality | health-data, health-data/validation |
| Data & Sources | zones/risk, risk/model, thermal/current |
| System Status | health/details, weather/current, thermal/current, risk/predict, risk/model, forecast/risk, zones/risk, interventions/types, health-data |

## Language discipline

The simulator and optimizer report **modelled risk reduction under stated
assumptions**. No page claims lives saved, mortality reduction, or any causal
health outcome, and the Health & Mortality page says so explicitly. The
backend's own `assumptions` and `disclaimer` fields are rendered verbatim
wherever they are returned rather than paraphrased.
