# HeatSentinal — Backend

**AI-Powered Human Heat-Health Early Warning & Decision Intelligence System**

Smart India Hackathon 2026

---

## Status

| Phase | Scope | State |
|-------|-------|-------|
| 1 | FastAPI foundation, config, health, CORS, error handling, Swagger | ✅ Complete |
| 2 | Weather service (Open-Meteo) | ✅ Complete |
| 3 | Thermal stress engine (Heat Index, WBGT, UTCI) | ⬜ Not started |
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
