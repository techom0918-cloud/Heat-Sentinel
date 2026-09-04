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
| 4 | Human vulnerability engine | ⬜ Not started |
| 5 | Health risk engine | ⬜ Not started |
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

**Note:** this endpoint uses `latitude`/`longitude`, while the Phase 2 weather
endpoints use `lat`/`lon`. See the API consistency note below.

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
