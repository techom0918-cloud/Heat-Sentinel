"""Health risk endpoints.

Thin by design. All scoring lives in risk_service.py, which is the seam a
trained XGBoost model will later replace behind the same contract.
"""

from fastapi import APIRouter

from app.models.common import ErrorResponse
from app.models.risk import RiskPredictionRequest, RiskPredictionResponse
from app.services import risk_service

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
