"""Phase 8 + 11: the current-condition Heat Index classifier.

A separate router from `risk.py` on purpose -- `/risk/predict` is the
existing rule-based weighted-formula engine (Phase 5), unchanged here.
This exposes the trained ML classifier from `backend/models/heat_index_model.joblib`.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import HeatSentinalError
from app.models.common import ErrorResponse
from app.models.heat_index import (
    HeatIndexExplanationResponse,
    HeatIndexModelInfo,
    HeatIndexModelStatusResponse,
    HeatIndexPredictionRequest,
    HeatIndexPredictionResponse,
)
from app.services import heat_index_service

router = APIRouter(prefix="/heat-index", tags=["Heat Index Classifier"])

_DISCLAIMER = (
    "Classifies the Heat Index category for the given instantaneous "
    "conditions. Not a temporal forecast, not a health outcome prediction, "
    "and not evidence that environmental features cause heat risk -- the "
    "target is a formula of temperature and humidity."
)


@router.get(
    "/model",
    response_model=HeatIndexModelStatusResponse,
    summary="Heat Index model status and metadata",
)
async def model_status() -> HeatIndexModelStatusResponse:
    if not heat_index_service.bundle_is_available():
        return HeatIndexModelStatusResponse(
            available=False,
            detail="No trained heat_index model artifact is present.",
        )
    explainer_ok = True
    try:
        heat_index_service.get_explainer()
    except HeatSentinalError:
        explainer_ok = False
    return HeatIndexModelStatusResponse(
        available=True,
        detail="Model loaded.",
        explainer_available=explainer_ok,
        model_info=HeatIndexModelInfo(**heat_index_service.model_info()),
    )


@router.post(
    "/predict",
    response_model=HeatIndexPredictionResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Invalid feature payload."},
        503: {"model": ErrorResponse, "description": "Model unavailable."},
    },
    summary="Classify Heat Index category from given conditions",
)
async def predict(payload: HeatIndexPredictionRequest) -> HeatIndexPredictionResponse:
    result = heat_index_service.predict_one(payload.features)
    result.pop("design_row", None)
    return HeatIndexPredictionResponse(
        **result,
        weather_resolution=heat_index_service.WEATHER_RESOLUTION_NOTE,
        disclaimer=_DISCLAIMER,
    )


@router.post(
    "/explain",
    response_model=HeatIndexExplanationResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Invalid feature payload."},
        503: {"model": ErrorResponse, "description": "Model or SHAP unavailable."},
    },
    summary="SHAP explanation for a single Heat Index classification",
)
async def explain(payload: HeatIndexPredictionRequest) -> HeatIndexExplanationResponse:
    return HeatIndexExplanationResponse(
        **heat_index_service.explain_prediction(payload.features)
    )
