"""Health risk endpoints.

Thin by design. All scoring lives in risk_service.py, which is the seam a
trained XGBoost model will later replace behind the same contract.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.models.common import ErrorResponse
from app.models.hazard import (
    Explanation,
    HazardForecastResponse,
    ModelInfo,
    ModelStatusResponse,
)
from app.models.risk import RiskPredictionRequest, RiskPredictionResponse
from app.core.config import settings
from app.services import (
    explainability_service,
    ml_service,
    risk_service,
    weather_service,
)

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

**Honest performance.** Held-out test, event = "HIGH or above". Model is
XGBoost, selected on validation CSI against persistence and climatology
baselines:

| | macro-F1 | POD | FAR | CSI | misses |
|---|---|---|---|---|---|
| Climatology | 0.496 | 0.860 | 0.238 | 0.679 | — |
| Persistence | 0.710 | 0.916 | 0.084 | 0.845 | 217 |
| **XGBoost** | **0.726** | **0.945** | 0.086 | **0.868** | **143** |

A **34% reduction in missed heat events** (217 → 143) for 12 additional
false alarms. The model also beats persistence on macro-F1, so it is better
at ranking severity, not only at detecting events.

**The EXTREME band is unreachable.** Across six cities, 578,592 hourly
records and eleven years, no day reached a Heat Index above 54 °C — so zero
EXTREME days appear in any split. The model cannot predict that band and its
skill there is unmeasured. VERY_HIGH recall is 0.57, with errors skewing
toward under-warning.

Trained on Delhi, Bengaluru, Kochi, Ahmedabad, Nagpur and Kolkata only.

`current_category` is the persistence baseline — compare it against
`predicted_category` to see what the model is actually adding.

**`explain=true`** adds a SHAP explanation of *this* prediction: the
features that pushed the model toward the forecast category, ranked by
absolute contribution. It is opt-in because SHAP is the expensive part of
the request. SHAP describes how the fitted model weighted its inputs — it is
**not a causal claim** and not a medical assessment.

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
    explain: Annotated[
        bool,
        Query(
            description=(
                "Include a SHAP explanation of the prediction. Opt-in "
                "because SHAP is the expensive part of the request."
            )
        ),
    ] = False,
    top_factors: Annotated[
        int,
        Query(
            ge=1,
            le=100,
            description=(
                "How many ranked factors to return when explaining. The "
                "model has 84 features, so 84 returns the complete "
                "attribution."
            ),
        ),
    ] = 10,
) -> HazardForecastResponse:
    # Fails fast with 503 before spending a provider call.
    info = ml_service.model_info()

    history = await weather_service.get_hourly_history(
        latitude, longitude, settings.ML_HISTORY_DAYS
    )
    prediction = ml_service.forecast_from_history(history)

    # The design matrix is internal plumbing, not part of the response.
    design = prediction.pop("_design")

    explanation = None
    if explain:
        # Explains the prediction already made above. It is never recomputed
        # or overridden here -- the model remains the source of truth.
        explanation = Explanation(
            **explainability_service.explain_prediction(
                design=design,
                class_index=prediction["predicted_class_index"],
                predicted_category=prediction["predicted_category"],
                top_n=top_factors,
            )
        )

    return HazardForecastResponse(
        location=history["location"].model_dump(),
        model_info=ModelInfo(**info),
        explanation=explanation,
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
    explainer = explainability_service.explainer_is_available()
    return ModelStatusResponse(
        available=True,
        detail=(
            "Trained model loaded. SHAP explanations available."
            if explainer
            else "Trained model loaded. SHAP explanations unavailable."
        ),
        explainer_available=explainer,
        model_info=ModelInfo(**ml_service.model_info()),
    )
