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
| 6–15 | XAI, forecast, zones, simulator, optimizer, alerts, ML, tests, docs | ⬜ Not started |

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
