# HeatSentinal — Backend

**AI-Powered Human Heat-Health Early Warning & Decision Intelligence System**

Smart India Hackathon 2026

---

## Status

| Phase | Scope | State |
|-------|-------|-------|
| 1 | FastAPI foundation, config, health, CORS, error handling, Swagger | ✅ Complete |
| 2 | Weather service (Open-Meteo) | ⬜ Not started |
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
| http://127.0.0.1:8000/docs | Swagger UI |
| http://127.0.0.1:8000/redoc | ReDoc |
| http://127.0.0.1:8000/openapi.json | OpenAPI schema |

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
| `WEATHER_API_URL` | Open-Meteo forecast endpoint | Phase 2 |
| `REQUEST_TIMEOUT_SECONDS` | `10` | Phase 2 |
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
