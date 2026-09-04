"""Health risk endpoints.

Thin by design. All scoring lives in risk_service.py, which is the seam a
trained XGBoost model will later replace behind the same contract.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.models.common import ErrorResponse
from app.models.hazard import (
    HazardForecastResponse,
    ModelInfo,
    ModelStatusResponse,
)
from app.models.risk import RiskPredictionRequest, RiskPredictionResponse
from app.core.config import settings
from app.services import ml_service, risk_service, weather_service

router = APIRouter(prefix="/risk", tags=["Health Risk"])

_DESCRIPTION = """
Estimates heat-health risk for a population by combining thermal stress with
vulnerability.

> **This prototype health-risk score is not a medically validated
> prediction model.**

**Inputs** come from the earlier engines — thermal indices from
`POST /api/v1/thermal/calculate`, `vulnerability_score` from
`POST /api/v1/vulnerability/calculate`. This endpoint **never recalculates**
Heat Index, WBGT or UTCI; index calculation stays in the thermal engine.

**Method**

```
thermal_stress = Σ (sub-weight × normalised index)
risk           = 0.65 × thermal_stress + 0.35 × vulnerability
```

**Normalisation anchors**

| Index | Range | Source |
|---|---|---|
| Heat Index | 27–54 °C | Phase 3 category edges (prototype bands) |
| WBGT | 22–35 °C | **Prototype anchors, uncalibrated** |
| UTCI | 26–46 °C | Published UTCI stress scale (Brode et al. 2012) |

WBGT anchors are placeholders on purpose. Phase 3 returns `NOT_CLASSIFIED`
for WBGT because ISO 7243 and ACGIH limits are defined on *outdoor* WBGT,
not the shade approximation computed here — so those limits are deliberately
not reused as anchors. UTCI is the one index with a documented scale.

**Prototype weights** (configurable) — thermal 0.65, vulnerability 0.35;
within thermal: Heat Index 0.30, WBGT 0.35, UTCI 0.35.

**UTCI is optional.** The thermal engine returns no UTCI above 50 °C air
temperature, which occurs in India. When `utci` is null its weight is
redistributed proportionally, so risk is not understated during the most
severe events.

**Thresholds** — <0.25 LOW, <0.50 MODERATE, <0.75 HIGH, else EXTREME.
Configurable prototype edges.

**`risk_probability`** is `risk_score` echoed. It is *not* a calibrated
probability. **`confidence`** is always `null` — a confidence value derived
from hand-chosen weights would be meaningless. **`contributors`** are
arithmetic shares that sum to `risk_score`; they are **not SHAP values**.
Real SHAP explanations arrive with the XGBoost model in a later phase.

Describes a population, never an individual.
"""


@router.post(
    "/predict",
    response_model=RiskPredictionResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Invalid input."},
        500: {"model": ErrorResponse, "description": "Misconfigured weights."},
    },
    summary="Predict prototype heat-health risk",
    description=_DESCRIPTION,
)
async def predict_risk(
    payload: RiskPredictionRequest,
) -> RiskPredictionResponse:
    return risk_service.predict_risk(
        temperature_c=payload.temperature_c,
        relative_humidity=payload.relative_humidity,
        wind_speed=payload.wind_speed,
        solar_radiation=payload.solar_radiation,
        heat_index=payload.heat_index,
        wbgt=payload.wbgt,
        utci=payload.utci,
        vulnerability_score=payload.vulnerability_score,
    )


# ---------------------------------------------------------------------------
# Trained-model hazard forecast
# ---------------------------------------------------------------------------

LatitudeQuery = Annotated[
    float,
    Query(ge=-90.0, le=90.0, description="Latitude.", examples=[28.6139]),
]
LongitudeQuery = Annotated[
    float,
    Query(ge=-180.0, le=180.0, description="Longitude.", examples=[77.2090]),
]

_FORECAST_DESCRIPTION = """
Three-day-ahead **heat hazard** forecast from the trained model in
`ml/heat_pipeline.py`.

> **This predicts a heat hazard band, not a health outcome.** The model was
> trained on meteorological variables only — no mortality, demographic or
> health data. Combining hazard with vulnerability is what
> `POST /api/v1/risk/predict` does.

**How it works** — fetches ~35 days of hourly history through the weather
service, builds the model's 84 features using the pipeline's *own*
`engineer_features` (imported, not reimplemented, so served features cannot
drift from trained features), and predicts the Heat Index category at
`based_on + horizon_days`.

**Honest performance.** Held-out test, event = "HIGH or above":

| | POD | FAR | CSI | misses |
|---|---|---|---|---|
| Persistence baseline | 0.894 | 0.106 | 0.808 | 120 |
| Model | 0.918 | 0.105 | 0.829 | 93 |

A 22% reduction in missed heat events at an equivalent false-alarm rate.
The improvement is **modest** — on validation, persistence actually scored
slightly higher than every model tried.

**The EXTREME band is unreachable.** Zero EXTREME days occurred in the
training, validation or test splits, so the model cannot predict it and its
skill there is unmeasured. Trained on Delhi, Bengaluru and Kochi only.

`current_category` is the persistence baseline — compare it against
`predicted_category` to see what the model is actually adding.

Returns **503** when no trained artifact is present.
"""


@router.get(
    "/forecast",
    response_model=HazardForecastResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Invalid input or insufficient history."},
        502: {"model": ErrorResponse, "description": "Weather provider failure."},
        503: {"model": ErrorResponse, "description": "No trained model available."},
    },
    summary="Three-day heat hazard forecast (trained model)",
    description=_FORECAST_DESCRIPTION,
)
async def hazard_forecast(
    latitude: LatitudeQuery,
    longitude: LongitudeQuery,
) -> HazardForecastResponse:
    # Fails fast with 503 before spending a provider call.
    info = ml_service.model_info()

    history = await weather_service.get_hourly_history(
        latitude, longitude, settings.ML_HISTORY_DAYS
    )
    prediction = ml_service.forecast_from_history(history)

    return HazardForecastResponse(
        location=history["location"].model_dump(),
        model_info=ModelInfo(**info),
        limitations=ml_service.MODEL_LIMITATIONS,
        disclaimer=ml_service.MODEL_DISCLAIMER,
        **prediction,
    )


@router.get(
    "/model",
    response_model=ModelStatusResponse,
    summary="Trained model status and test metrics",
    description=(
        "Reports whether a trained artifact is loaded, and its held-out test "
        "metrics. Useful for a dashboard badge and for confirming a retrained "
        "model was picked up after restart."
    ),
)
async def model_status() -> ModelStatusResponse:
    if not ml_service.model_is_available():
        return ModelStatusResponse(
            available=False,
            detail=(
                "No trained model artifact is loaded. Run ml/heat_pipeline.py "
                "to train one, then restart the API. The heuristic endpoint "
                "POST /api/v1/risk/predict is unaffected."
            ),
        )
    return ModelStatusResponse(
        available=True,
        detail="Trained model loaded.",
        model_info=ModelInfo(**ml_service.model_info()),
    )
