# HeatSentinal — Backend

**AI-Powered Human Heat-Health Early Warning & Decision Intelligence System**

Smart India Hackathon 2026

---

## Status

| Phase | Scope | State |
|-------|-------|-------|
| 1 | FastAPI foundation, config, health, CORS, error handling, Swagger | ✅ Complete |
| 2 | Weather service (Open-Meteo) | ✅ Complete |
| 3 | Thermal stress engine (Heat Index, WBGT, UTCI) | ✅ Complete |
| 4 | Human vulnerability engine | ✅ Complete |
| 5 | Health risk engine | ✅ Complete |
| 6 | Explainable AI (SHAP) | ✅ Complete |
| 7 | Risk trajectory & forecast | ✅ Complete |
| 8 | Hyperlocal GIS risk zones | ✅ Complete |
| 9 | Heat Action Simulator | ✅ Complete |
| 10–15 | Action optimizer, alerts, mortality interface, docs | ⬜ Not started |

---

## Architecture

Four layers, one direction of dependency:

```
routes/     HTTP only. Parse, validate, delegate, return.
services/   Business logic. No FastAPI imports.
utils/      Pure functions. No I/O, no framework.
models/     Pydantic schemas shared by routes and services.
```

`core/config.py` is the single source of configuration. `core/exceptions.py`
is the single source of error formatting. Nothing else reads `os.environ`
and no route builds an error response by hand.

---

## Installation (Windows 11 / PowerShell)

```powershell
cd HeatSentinal\backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

If PowerShell blocks the activation script:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

---

## Running

```powershell
uvicorn app.main:app --reload
```

| URL | Purpose |
|-----|---------|
| http://127.0.0.1:8000/ | Service identity |
| http://127.0.0.1:8000/api/v1/health | Liveness check |
| http://127.0.0.1:8000/api/v1/health/details | Runtime metadata |
| http://127.0.0.1:8000/api/v1/weather/current | Current weather |
| http://127.0.0.1:8000/api/v1/weather/forecast | 1-5 day forecast |
| http://127.0.0.1:8000/api/v1/thermal/calculate | Thermal stress (POST) |
| http://127.0.0.1:8000/api/v1/thermal/current | Weather + thermal stress |
| http://127.0.0.1:8000/api/v1/vulnerability/calculate | Vulnerability score (POST) |
| http://127.0.0.1:8000/api/v1/risk/predict | Health risk score (POST) |
| http://127.0.0.1:8000/docs | Swagger UI |
| http://127.0.0.1:8000/redoc | ReDoc |
| http://127.0.0.1:8000/openapi.json | OpenAPI schema |

---

## Weather API (Phase 2)

### How the weather service works

```
route (weather.py)   ->  service (weather_service.py)  ->  Open-Meteo
   validates lat/lon        builds params, calls provider,
   and days                 translates payload into
                            HeatSentinal schemas
```

`app/services/weather_service.py` is the **only** module that knows Open-Meteo
exists. Routes import the service, never an HTTP client. Swapping to IMD or
NCMRWF later means rewriting that one file.

**Fixed unit convention** (set here once for the whole system):

| Quantity | Unit |
|---|---|
| Temperature | °C |
| Relative humidity | % (0–100) |
| Wind speed | **m/s** |
| Precipitation | mm |
| Solar radiation (instant) | W/m² |
| Solar radiation (daily total) | MJ/m² |

Wind is requested as `wind_speed_unit=ms` because WBGT and UTCI are defined on
m/s. Passing km/h would produce wrong-but-plausible index values.

**Two provider gaps handled in the service:**

1. Solar radiation is not an Open-Meteo *current* variable. It is read from
   the hourly series at the hour matching the observation time.
2. Open-Meteo publishes no daily humidity aggregate. `relative_humidity_mean`
   and `relative_humidity_at_max_temp` are computed from the hourly series.
   The second pairs humidity with each day's hottest hour, because heat stress
   peaks with temperature — using a daily mean would understate afternoon risk.

**Missing values are never invented.** Any variable the provider omits is
returned as `null`. The single exception is temperature: if it is absent the
request fails with 502, since every later phase depends on it.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/weather/current` | Current conditions for a coordinate |
| GET | `/api/v1/weather/forecast` | 1–5 day daily forecast |

### `GET /api/v1/weather/current`

| Parameter | Type | Range | Required |
|---|---|---|---|
| `lat` | float | −90 to 90 | yes |
| `lon` | float | −180 to 180 | yes |

```
curl "http://127.0.0.1:8000/api/v1/weather/current?lat=28.6139&lon=77.2090"
```

```json
{
  "location": {
    "latitude": 28.625,
    "longitude": 77.25,
    "elevation_m": 216.0,
    "timezone": "Asia/Kolkata"
  },
  "current": {
    "observed_at": "2026-09-04T14:30:00",
    "temperature_c": 34.2,
    "relative_humidity": 62.0,
    "apparent_temperature_c": 41.8,
    "wind_speed_ms": 2.8,
    "wind_direction_deg": 118.0,
    "precipitation_mm": 0.0,
    "cloud_cover_pct": 75.0,
    "surface_pressure_hpa": 991.2,
    "solar_radiation_wm2": 612.0,
    "is_day": true
  },
  "provider": "open-meteo",
  "retrieved_at": "2026-09-04T09:00:11.482Z"
}
```

### `GET /api/v1/weather/forecast`

| Parameter | Type | Range | Required |
|---|---|---|---|
| `lat` | float | −90 to 90 | yes |
| `lon` | float | −180 to 180 | yes |
| `days` | int | 1 to 5 | no (default 5) |

```
curl "http://127.0.0.1:8000/api/v1/weather/forecast?lat=28.6139&lon=77.2090&days=3"
```

```json
{
  "location": {
    "latitude": 28.625,
    "longitude": 77.25,
    "elevation_m": 216.0,
    "timezone": "Asia/Kolkata"
  },
  "days": 3,
  "forecast": [
    {
      "date": "2026-09-04",
      "temperature_max_c": 40.0,
      "temperature_min_c": 27.0,
      "apparent_temperature_max_c": 46.0,
      "relative_humidity_mean": 71.5,
      "relative_humidity_at_max_temp": 56.0,
      "wind_speed_max_ms": 3.4,
      "precipitation_sum_mm": 0.0,
      "solar_radiation_max_wm2": 1800.0,
      "solar_radiation_sum_mj": 21.5
    }
  ],
  "provider": "open-meteo",
  "retrieved_at": "2026-09-04T09:00:11.482Z"
}
```

### Error responses

| Condition | Status | `error.type` |
|---|---|---|
| `lat` outside −90..90 | 422 | `request_validation_error` |
| `lon` outside −180..180 | 422 | `request_validation_error` |
| `days` outside 1..5 | 422 | `request_validation_error` |
| Service called directly with bad input | 422 | `validation_error` |
| Provider timeout | 502 | `external_service_error` |
| Provider unreachable | 502 | `external_service_error` |
| Provider returned 4xx/5xx | 502 | `external_service_error` |
| Malformed or empty provider payload | 502 | `external_service_error` |

```json
{
  "error": {
    "type": "external_service_error",
    "message": "The weather provider did not respond in time.",
    "details": { "provider": "open-meteo", "timeout_s": 10.0 }
  }
}
```

### Data source

[Open-Meteo](https://open-meteo.com/) — free for non-commercial use, no API
key. Attribution required in any public deployment. Global model resolution is
roughly 11 km, so `location` in the response is the **resolved grid cell**, not
the exact coordinate requested. Phase 8's 330 m hyperlocal zones will need
downscaling on top of this, not raw provider output.

---

## Thermal Stress Engine (Phase 3)

### Architecture

```
weather route  -> weather_service -> Open-Meteo
thermal route  -> weather_service -> thermal_service -> response
```

`thermal_service.py` is **pure**: no network calls, no HTTP client import,
deterministic output. That is enforced by a test, and it is what lets the
future `risk_service.py` and the offline `heat_pipeline.py` call the same
functions and get identical numbers.

### Methodology

Calculations are matched deliberately to the existing `heat_pipeline.py`, so
the API and the trained model never disagree about what "WBGT" means.

| Index | Method | Classification |
|---|---|---|
| Heat Index | NWS algorithm — simple Steadman form below ~80 °F, Rothfusz (1990) regression above, plus published low-RH and high-RH corrections | **Recognised calculation** |
| WBGT | Shade form `0.7·Tw + 0.3·Ta`, with Tw from Stull (2011) | **Approximation** |
| UTCI | `pythermalcomfort` implementation of the ISB Commission 6 polynomial | **Reference implementation** |

### Assumptions and limitations

**Heat Index.** Shaded conditions, light wind. Fitted for roughly 80–112 °F;
outside that it extrapolates. Ignores wind, radiation, and clothing. When the
result exceeds 58.3 °C (137 °F, the top of the published NWS chart) the
response carries an explicit extrapolation note.

**WBGT — this is a shade approximation, not outdoor WBGT.** True outdoor WBGT
is `0.7·Tnw + 0.2·Tg + 0.1·Ta` and requires an instrument-measured black-globe
temperature. **Solar radiation is accepted and echoed but deliberately unused**:
deriving a globe temperature from irradiance would need an unvalidated
radiation model, and the output would read as occupational WBGT while carrying
none of its measurement basis. For the same reason `wbgt_category` is always
`NOT_CLASSIFIED` — ISO 7243 and ACGIH limits are defined on outdoor WBGT and
depend on metabolic rate and acclimatisation. The Stull form has no pressure
term, so it is less reliable at altitude, and its stated validity is about
−20 to 50 °C with RH 5–99%.

**UTCI.** Mean radiant temperature is assumed equal to air temperature (shade
assumption, matching `heat_pipeline.py`), which understates heat load in direct
sun. Wind is clamped to 0.5–17 m/s. **Air temperature above 50 °C returns
`null`** rather than an extrapolated value — Indian extremes do exceed this.
`utci_category` uses the official UTCI stress scale (Brode et al. 2012).

**Heat Index categories are prototype bands**, not a medical classification.
Edges default to 27/32/41/54 °C (matching `heat_pipeline.py`) and are
configurable via `HEAT_INDEX_BOUNDS_C` so they can be recalibrated against
Indian heat-mortality data later.

None of these values is a medical assessment of any individual.

### `POST /api/v1/thermal/calculate`

```
curl -X POST "http://127.0.0.1:8000/api/v1/thermal/calculate" ^
  -H "Content-Type: application/json" ^
  -d "{\"temperature\":42.0,\"relative_humidity\":60.0,\"wind_speed\":2.0,\"solar_radiation\":500.0}"
```

| Field | Unit | Range |
|---|---|---|
| `temperature` | °C | −90 to 60 |
| `relative_humidity` | % | 0 to 100 |
| `wind_speed` | m/s | ≥ 0 (default 0) |
| `solar_radiation` | W/m² | ≥ 0, optional, **unused** |

```json
{
  "temperature": 42.0,
  "relative_humidity": 60.0,
  "wind_speed": 2.0,
  "solar_radiation": 500.0,
  "heat_index": 71.2,
  "heat_index_category": "EXTREME",
  "wet_bulb_temperature": 34.8,
  "wbgt": 36.9,
  "wbgt_category": "NOT_CLASSIFIED",
  "utci": 51.9,
  "utci_category": "EXTREME_HEAT_STRESS",
  "assumptions": ["..."],
  "methods": [{"index": "...", "classification": "...", "limitations": ["..."]}],
  "notes": ["..."]
}
```

### `GET /api/v1/thermal/current`

| Parameter | Type | Range |
|---|---|---|
| `latitude` | float | −90 to 90 |
| `longitude` | float | −180 to 180 |

```
curl "http://127.0.0.1:8000/api/v1/thermal/current?latitude=28.6139&longitude=77.2090"
```

Returns `location`, `observed_at`, `weather`, `thermal`, `provider`. If the
provider supplies no relative humidity the request fails with 502 rather than
guessing a value.

**Coordinate parameter names differ by endpoint.** This is deliberate and
documented rather than accidental:

| Endpoint | Parameters |
|---|---|
| `/api/v1/weather/current` | `lat`, `lon` |
| `/api/v1/weather/forecast` | `lat`, `lon` |
| `/api/v1/thermal/current` | `latitude`, `longitude` |

Frontend clients must use the right form per endpoint; the wrong one returns
422. Swagger at `/docs` shows the correct names for each.

---

## Human Vulnerability Engine (Phase 4)

> **This is a prototype vulnerability scoring framework and is not a
> medically validated risk score.**

### Purpose

Estimates how susceptible a *population* — never an individual — is to
extreme heat, by combining six demographic and infrastructural factors into
one 0–1 score with per-factor contributions a dashboard can explain.

### Input variables

| Variable | Unit | Range |
|---|---|---|
| `elderly_population_pct` | % aged 65+ | 0–100 |
| `outdoor_worker_pct` | % of workforce outdoors | 0–100 |
| `population_density` | people/km² | ≥ 0 |
| `healthcare_accessibility` | index (**protective**) | 0–1 |
| `historical_heat_exposure` | index | 0–1 |
| `historical_heat_mortality` | index | 0–1 |

### Normalisation

| Factor | Method |
|---|---|
| Elderly population | percentage ÷ 100 |
| Outdoor workers | percentage ÷ 100 |
| Population density | log₁₀ between configurable floor and ceiling |
| Healthcare accessibility | **`1 − access`** (inverted) |
| Historical heat exposure | already 0–1, clamped |
| Historical heat mortality | already 0–1, clamped |

**Direction convention:** every normalised factor points the same way —
1.0 means *more* vulnerable. Healthcare accessibility is protective, so it
is inverted. An input of 0.62 appears as 0.38 in `factors`.

**Why log for density.** District density spans roughly four orders of
magnitude. Under linear normalisation against a 20,000/km² ceiling, a
district at 2,000/km² scores 0.10 and one at 200/km² scores 0.01 — almost
every district collapses into the bottom of the range and the factor stops
discriminating. Log scaling spreads them out and encodes the assumption
that the marginal effect of extra density diminishes at the top.

**Explicitly uncalibrated:** the floor (10/km²) and ceiling (20,000/km²) are
prototype anchors, *not* surveyed extremes. Set them from real census data
before using this for anything real. `POPULATION_DENSITY_NORMALISATION` can
be switched to `linear`.

### Weights and scoring

`score = Σ (weight × normalised factor)`

| Factor | Weight |
|---|---|
| Elderly population | 0.20 |
| Outdoor workers | 0.20 |
| Population density | 0.15 |
| Healthcare accessibility | 0.15 |
| Historical heat exposure | 0.15 |
| Historical heat mortality | 0.15 |

Weights live only in `app/core/config.py`, are environment-overridable, and
**must sum to 1.0** — a set that does not raises a 500 rather than silently
rescaling every score.

### Thresholds

| Score | Level |
|---|---|
| 0.00–0.24 | LOW |
| 0.25–0.49 | MODERATE |
| 0.50–0.74 | HIGH |
| 0.75–1.00 | EXTREME |

Configurable prototype edges, not clinical cut-offs.

### Limitations

- Weights are uncalibrated prototype values, not derived from Indian
  heat-mortality data.
- Thresholds are prototype edges, not epidemiological cut-offs.
- The model is linear and additive — it cannot represent interactions such
  as elderly residents who are *also* outdoor workers.
- Density floor/ceiling are prototype anchors, not surveyed extremes.
- Healthcare accessibility, historical exposure and historical mortality
  arrive as pre-computed 0–1 indices; this engine does not define how they
  are derived. Phase 12 will supply them from NCRB, IMD and census sources.
- Vulnerability describes a population, never an individual.

**No Indian demographic or mortality data is fabricated anywhere in this
engine.** It computes only from values supplied in the request.

### `POST /api/v1/vulnerability/calculate`

```powershell
$body = @{
    elderly_population_pct    = 12.5
    outdoor_worker_pct        = 28.0
    population_density        = 8500
    healthcare_accessibility  = 0.62
    historical_heat_exposure  = 0.70
    historical_heat_mortality = 0.35
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/vulnerability/calculate" `
    -Method Post -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 6
```

```json
{
  "vulnerability_score": 0.4286,
  "vulnerability_level": "MODERATE",
  "factors": {
    "elderly_population": 0.125,
    "outdoor_workers": 0.28,
    "population_density": 0.8874,
    "healthcare_accessibility": 0.38,
    "historical_heat_exposure": 0.7,
    "historical_heat_mortality": 0.35
  },
  "contributions": {
    "elderly_population": 0.025,
    "outdoor_workers": 0.056,
    "population_density": 0.133114,
    "healthcare_accessibility": 0.057,
    "historical_heat_exposure": 0.105,
    "historical_heat_mortality": 0.0525
  },
  "weights": { "elderly_population": 0.2, "...": "..." },
  "normalisation": { "healthcare_accessibility": "1 - accessibility (INVERTED: protective factor)" },
  "thresholds": { "LOW": 0.25, "MODERATE": 0.5, "HIGH": 0.75, "EXTREME": 1.0 },
  "limitations": ["..."],
  "disclaimer": "PROTOTYPE VULNERABILITY FRAMEWORK - NOT A MEDICALLY VALIDATED RISK SCORE..."
}
```

`contributions` sums to `vulnerability_score`, so the frontend can show
exactly why an area scored as it did.

---

## Health Risk Engine (Phase 5)

> **This prototype health-risk score is not a medically validated
> prediction model.**

### Purpose

Combines thermal stress with population vulnerability into one 0–1 risk
score with per-factor contributions. This layer **consumes** thermal
indices; it never recalculates them. Index calculation belongs to Phase 3,
and a test asserts `risk_service.py` does not import `thermal_service`.

### Inputs

| Field | Unit | Range | Source |
|---|---|---|---|
| `temperature_c` | °C | −90…60 | weather engine (context only) |
| `relative_humidity` | % | 0…100 | weather engine (context only) |
| `wind_speed` | m/s | ≥ 0 | weather engine (context only) |
| `solar_radiation` | W/m² | ≥ 0, optional | weather engine (context only) |
| `heat_index` | °C | −100…150 | **thermal engine** |
| `wbgt` | °C | −50…100 | **thermal engine** |
| `utci` | °C | −100…100, **optional** | **thermal engine** |
| `vulnerability_score` | index | 0…1 | **vulnerability engine** |

### Scoring methodology

```
thermal_stress = Σ (sub-weight × normalised index)
risk           = 0.65 × thermal_stress + 0.35 × vulnerability
```

**Normalisation anchors** — each index scaled linearly and clamped:

| Index | Range | Source |
|---|---|---|
| Heat Index | 27–54 °C | Phase 3 category edges (prototype bands) |
| WBGT | 22–35 °C | **Prototype anchors, uncalibrated** |
| UTCI | 26–46 °C | Published UTCI stress scale (Brode et al. 2012) |

The WBGT anchors are placeholders deliberately. Phase 3 returns
`NOT_CLASSIFIED` for WBGT because ISO 7243 and ACGIH limits are defined on
*outdoor* WBGT, not the shade approximation computed here — reusing those
limits as anchors would contradict that and dress an uncalibrated number in
borrowed authority. **UTCI is the only index with a documented scale.**

**Prototype weights** (configurable, each group sums to 1.0):

| | Weight |
|---|---|
| Thermal stress | 0.65 |
| Vulnerability | 0.35 |
| — Heat Index | 0.30 |
| — WBGT | 0.35 |
| — UTCI | 0.35 |

**UTCI is optional.** The thermal engine returns no UTCI above 50 °C air
temperature, which occurs in India. When `utci` is null its weight is
redistributed proportionally across the remaining indices — dropping it
instead would shrink `thermal_stress` and understate risk during exactly the
events this system exists for.

### Thresholds

| Score | Level |
|---|---|
| 0.00–0.24 | LOW |
| 0.25–0.49 | MODERATE |
| 0.50–0.74 | HIGH |
| 0.75–1.00 | EXTREME |

Configurable prototype edges, not clinical cut-offs.

### Limitations

- Not a validated prediction model — nothing has been fitted to
  heat-mortality outcomes.
- Weights are uncalibrated prototype values chosen for plausibility.
- WBGT normalisation anchors are placeholders pending calibration.
- Heat Index and WBGT are strongly correlated, so the weighted mean
  double-counts temperature and humidity to some degree.
- Linear and additive — cannot represent interactions such as extreme heat
  arriving in an already vulnerable district.
- `risk_probability` is the score echoed, **not** a calibrated probability.
- `confidence` is always `null` and stays null until a model is trained.
- `contributors` are arithmetic shares, **not SHAP values**.
- Describes a population, never an individual.

### Future ML compatibility

`risk_service.predict_risk()` is the seam. XGBoost replaces its body behind
the same signature and response model; `confidence` then returns a real
value and `contributors` are swapped for SHAP. Callers do not change.

### `POST /api/v1/risk/predict`

```powershell
$body = @{
    temperature_c       = 42.0
    relative_humidity   = 65.0
    wind_speed          = 2.5
    solar_radiation     = 700.0
    heat_index          = 49.2
    wbgt                = 31.5
    utci                = 43.1
    vulnerability_score = 0.78
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/risk/predict" `
    -Method Post -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 6
```

```json
{
  "risk_score": 0.7941,
  "risk_probability": 0.7941,
  "risk_level": "EXTREME",
  "confidence": null,
  "components": { "thermal_stress": 0.8017, "vulnerability": 0.78 },
  "contributors": [
    { "factor": "vulnerability", "impact": 0.273, "direction": "increases", "normalised_value": 0.78, "weight": 0.35 },
    { "factor": "UTCI", "impact": 0.194513, "direction": "increases", "normalised_value": 0.855, "weight": 0.2275 },
    { "factor": "WBGT", "impact": 0.166269, "direction": "increases", "normalised_value": 0.7308, "weight": 0.2275 },
    { "factor": "Heat Index", "impact": 0.160333, "direction": "increases", "normalised_value": 0.8222, "weight": 0.195 }
  ],
  "normalised_indices": { "heat_index": 0.8222, "wbgt": 0.7308, "utci": 0.855 },
  "thresholds": { "LOW": 0.25, "MODERATE": 0.5, "HIGH": 0.75, "EXTREME": 1.0 },
  "limitations": ["..."],
  "disclaimer": "PROTOTYPE HEALTH-RISK SCORE - NOT A MEDICALLY VALIDATED PREDICTION MODEL..."
}
```

`contributors` sum to `risk_score`, so a dashboard can show exactly why a
location scored as it did.

---

## Phase 6 — Explainable AI (SHAP)

### PREDICT → EXPLAIN

```
PREDICT   ml_service        84 features -> 3-day heat hazard category
EXPLAIN   explainability_service   SHAP -> which features drove THAT class
```

The model stays the source of truth. SHAP never re-predicts, never rescores,
and never alters a forecast — a test asserts `explainability_service` calls
neither `predict` nor `predict_proba`.

### Usage

Opt-in, because SHAP is the expensive part of the request:

```
GET /api/v1/risk/forecast?latitude=28.6139&longitude=77.2090&explain=true
```

`top_factors` (1–100, default 10) controls how many ranked factors come
back. The model has 84 features, so `top_factors=84` returns the complete
attribution.

### Example

**Prediction:** `EXTREME` (confidence 0.99)

**Main drivers:**

| # | Feature | Value | SHAP | Direction |
|---|---|---|---|---|
| 1 | mean heat index | 70.6 | +0.708 | increases_risk |
| 2 | peak WBGT 2 days earlier | 41.9 | +0.672 | increases_risk |
| 3 | 7-day average peak UTCI | 66.4 | +0.664 | increases_risk |
| 4 | peak heat index | 93.8 | +0.626 | increases_risk |
| 5 | 3-day average peak heat index | 93.7 | +0.465 | increases_risk |
| 6 | consecutive hot days | 35.0 | −0.428 | decreases_risk |

**Generated summary:**

> The model's EXTREME forecast is driven mainly by heat index, wet-bulb globe
> temperature, UTCI thermal stress and temperature. Moderating the forecast:
> recent heat persistence and humidity.

Summaries are built deterministically from the ranked themes — no LLM, no
randomness. The same factors always produce the same sentence.

### Multiclass handling

The model has five classes, and SHAP's output shape varies by library and
estimator version. `_normalise_shap_output` handles:

- `Explanation` objects (unwrapped, then recursed)
- lists of per-class arrays (older SHAP)
- 3D arrays as `(samples, features, classes)` **or** `(classes, samples, features)`
- 2D arrays (binary/single output)

Contributions are attributed to the **predicted class only**. Class
contributions are never summed together. Where an axis mapping is ambiguous
the service raises rather than guessing — a wrong axis would produce a
plausible-looking explanation of the wrong class.

### Performance

The `TreeExplainer` is built once and cached (`lru_cache`), reusing the
estimator `ml_service` already loaded. The artifact is never re-read per
request, and SHAP runs only when `explain=true`.

### What SHAP is and is not

A SHAP value here is a signed contribution, in the model's output space, of
one feature toward the predicted class for one input, relative to the
explainer's base value.

**These are not causal claims.** SHAP describes how this fitted model
weighted its inputs. It does not establish that a feature causes heat, harm
or any health outcome. The model was trained on meteorological variables
only — no mortality, demographic or health data. Every explanation carries
this caveat in its `caveat` field.

---

## Phases 7–9 — Forecast, Map, Simulate

### The decision flow

```
PREDICT    ml_service            84 features  -> heat hazard category (t+3)
EXPLAIN    explainability_service SHAP        -> why that category
FORECAST   forecast_service      trajectory   -> how it changes over 5 days
MAP        geospatial_service    GeoJSON      -> which zones, and who is exposed
SIMULATE   intervention_service  scenarios    -> what changes if we act
```

Four kinds of number appear in these responses, and they are kept apart on
purpose:

| Kind | Where it comes from | Example |
|---|---|---|
| **Observed** | measured weather | today's Heat Index |
| **Model prediction** | the trained artifact | the t+3 category, with confidence |
| **Vulnerability estimate** | Phase 4, uncalibrated weights | a zone's 0–1 score |
| **Simulated effect** | Phase 9 assumptions | risk change under an intervention |

Conflating these is how a heat dashboard misleads. Every response labels
which it is giving you.

---

## Phase 7 — Risk Trajectory & Forecast

`GET /api/v1/forecast/risk?latitude=28.6139&longitude=77.2090&days=5`

**The honest constraint.** The trained artifact stores `horizon_days: 3`. It
was fitted on exactly one target — the heat category three days after the
feature date. It does not predict day 1, 2, 4 or 5, and this endpoint does
not pretend otherwise. Every day is labelled with the method that produced
it:

| `method` | Meaning | Confidence |
|---|---|---|
| `OBSERVED` | Category from observed weather | — |
| `NWP_DERIVED` | Category computed from the provider's numerical weather forecast, using the same Heat Index bands the model was trained against. A forecast, but not an ML one. | — |
| `ML_MODEL` | The trained model at its supported horizon | model class probability |

At the model's horizon both values exist, and **both are reported** —
`model_risk_level` plus the NWP-derived value in `method_note`. Where they
disagree, that disagreement is information.

`trend` is deterministic: mean category level of the later half of the
trajectory minus the earlier half, against a configurable threshold →
`WORSENING`, `STABLE`, or `IMPROVING`.

---

## Phase 8 — Hyperlocal Risk Zones

`GET /api/v1/zones/risk`

Returns a GeoJSON `FeatureCollection` ready for any mapping library.

> **The bundled dataset is SYNTHETIC.** `data/demo_zones.geojson` contains
> arbitrary rectangular cells over Delhi — **not** real administrative, ward
> or census boundaries — with invented demographics. Replace with a real
> boundary file and real census, occupational, healthcare-access and
> NCRB/IMD mortality data before any operational use. Both the collection
> and every feature carry `data_status: SYNTHETIC_DEMO`.

Each feature separates four things:

1. `heat_hazard` — how hot it is
2. `vulnerability` — how badly this population copes (**Phase 4, reused**)
3. `human_risk` — the two combined (**Phase 5, existing weights**)
4. `priority` — what to act on first

**Hazard is city-level, and the response says so.** Open-Meteo's global model
resolves to roughly 11 km; every demo zone falls inside one grid cell.
Fetching weather per zone would return identical numbers while implying a
spatial resolution that does not exist. What varies between zones is
**vulnerability** — which is precisely the argument for a heat-health system
over a weather app. True hyperlocal hazard needs downscaling (land surface
temperature, urban heat island modelling) that this repository does not
contain and does not fake.

`priority` uses a prototype matrix combining risk level with vulnerability
level, so a moderately hot but highly vulnerable zone is not out-ranked by a
hot but resilient one. It is not a published prioritisation standard.

---

## Phase 9 — Heat Action Simulator

`POST /api/v1/interventions/simulate`
`GET /api/v1/interventions/types`

> **MODELLED SCENARIO.** Reports an estimated change in HeatSentinal's own
> risk score under explicit assumptions. It does **not** estimate deaths
> prevented, mortality reduction, or any medical outcome. Effect sizes are
> uncalibrated prototype assumptions — this repository contains no
> intervention evaluation data.

Each intervention acts on one channel:

| Type | Channel | Max effect |
|---|---|---|
| `COOLING_CENTER` | VULNERABILITY | 0.25 |
| `WATER_DISTRIBUTION` | VULNERABILITY | 0.12 |
| `WORK_HOUR_SHIFT` | EXPOSURE | 0.20 |
| `SHADE_REST_AREA` | EXPOSURE | 0.10 |
| `PUBLIC_ALERT` | EXPOSURE | 0.05 |

All five are configurable via environment variables.

`effect = max_effect × coverage`. Interventions on the same channel combine
**multiplicatively** — `∏(1 − effect)` — so stacking yields diminishing
returns and can never exceed a total reduction. An additive model would let
four measures sum past 100%, which is not a defensible assumption.

Baseline and simulated scores both come from the same Phase 5 risk engine,
so they are directly comparable. The simulator never retrains or touches the
ML model; a test asserts it does not import `ml_service`.

```json
{
  "zone_id": "ZONE_01",
  "baseline":   { "risk_score": 0.79, "risk_level": "EXTREME" },
  "simulation": { "risk_score": 0.74, "risk_level": "HIGH" },
  "estimated_risk_reduction": 0.052,
  "estimated_risk_reduction_percent": 6.56,
  "risk_level_changed": true,
  "channel_reductions": { "vulnerability": 0.191, "exposure": 0.0 },
  "assumptions": ["Cooling centres: assumed to reduce modelled vulnerability ..."],
  "disclaimer": "MODELLED SCENARIO. ... does NOT estimate deaths prevented ..."
}
```

---

## Testing

```powershell
pytest
```

---

## Environment variables

| Variable | Default | Used from |
|----------|---------|-----------|
| `DEBUG` | `True` | Phase 1 |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Phase 1 |
| `WEATHER_PROVIDER` | `open-meteo` | Phase 2 |
| `WEATHER_API_URL` | Open-Meteo forecast endpoint | Phase 2 |
| `REQUEST_TIMEOUT_SECONDS` | `10` | Phase 2 |
| `WEATHER_TIMEZONE` | `auto` | Phase 2 |
| `WEATHER_FORECAST_MAX_DAYS` | `5` | Phase 2 |
| `HEAT_INDEX_BOUNDS_C` | `27,32,41,54` | Phase 3 |
| `HEAT_INDEX_CATEGORIES` | `LOW,MODERATE,HIGH,VERY_HIGH,EXTREME` | Phase 3 |
| `UTCI_WIND_MIN_MS` / `UTCI_WIND_MAX_MS` | `0.5` / `17.0` | Phase 3 |
| `UTCI_TEMP_MIN_C` / `UTCI_TEMP_MAX_C` | `-50.0` / `50.0` | Phase 3 |
| `FORECAST_MAX_DAYS` | `5` | Phase 7 |
| `FORECAST_TREND_THRESHOLD` | `0.5` | Phase 7 |
| `ZONES_GEOJSON_PATH` | `data/demo_zones.geojson` | Phase 8 |
| `INTERVENTION_*_EFFECT` | 0.25 / 0.12 / 0.20 / 0.05 / 0.10 | Phase 9 |
| `MODEL_PATH` | `ml/models` | Phase 13 |
| `DATABASE_URL` | *(empty)* | Later |

`CORS_ORIGINS` is a comma-separated string, not JSON. It is parsed into a
list by `Settings.cors_origins_list`.

Never commit `.env`. Never hardcode keys.

---

## Error contract

Every error — domain, validation, HTTP, or unhandled — returns the same shape:

```json
{
  "error": {
    "type": "validation_error",
    "message": "One or more request parameters are invalid.",
    "details": {}
  }
}
```

The frontend only ever parses one error format.

---

## Scientific integrity rules

These constrain every later phase and are stated here so they are not lost:

- No invented formulas. Every thermal index cites its published method.
- Every metric is labelled as **recognised calculation**, **approximation**,
  or **prototype estimation**.
- Risk thresholds are **configurable prototype thresholds**, never described
  as medically validated.
- Intervention results are **estimated relative reductions in modeled risk**,
  never mortality reductions.
- Mortality data is never fabricated. Mock data is labelled
  `MOCK DATA — NOT FOR REAL-WORLD DECISION MAKING`.
