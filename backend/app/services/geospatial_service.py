"""Hyperlocal zone risk.

Turns city-level hazard into zone-level decision intelligence by holding
hazard constant across zones and letting VULNERABILITY vary.

WHY HAZARD IS CITY-LEVEL, HONESTLY
Open-Meteo's global model resolves to roughly 11 km. The demo zones are a
few kilometres across, so every zone in this set falls inside the same
provider grid cell. Fetching weather per zone would return the same numbers
with more API calls and a false impression of spatial resolution. Hazard is
therefore fetched once and applied to every zone, and the response says so.

Genuine hyperlocal hazard needs downscaling -- land surface temperature,
urban heat island modelling, built-form data -- which this repository does
not contain and which is not fabricated here.

WHAT VARIES IS VULNERABILITY, AND THAT IS THE POINT
Two zones under identical weather carry different risk because their
populations differ. That is the whole argument for a heat-health system over
a weather app, and it is what these zones demonstrate.

REUSE, NOT REIMPLEMENTATION
Vulnerability comes from Phase 4's `vulnerability_service`. Combined human
risk comes from Phase 5's `risk_service`, with its existing configured
weights. No new scoring weights are introduced here. The only new
configuration is the priority matrix, which is documented below.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.exceptions import HeatSentinalError, ResourceNotFoundError
from app.services import risk_service, thermal_service, vulnerability_service

logger = logging.getLogger(__name__)

SYNTHETIC_WARNING = (
    "SYNTHETIC DEMO ZONES - NOT FOR REAL-WORLD DECISION MAKING. Polygons are "
    "arbitrary cells, not real administrative boundaries, and the attached "
    "demographics are invented."
)

# Priority combines combined risk with vulnerability, so that a moderately
# hot but highly vulnerable zone is not out-ranked by a hot but resilient
# one. PROTOTYPE MATRIX, not a published prioritisation standard.
_PRIORITY_MATRIX = {
    ("EXTREME", "EXTREME"): "CRITICAL",
    ("EXTREME", "HIGH"): "CRITICAL",
    ("EXTREME", "MODERATE"): "HIGH",
    ("EXTREME", "LOW"): "HIGH",
    ("HIGH", "EXTREME"): "CRITICAL",
    ("HIGH", "HIGH"): "HIGH",
    ("HIGH", "MODERATE"): "HIGH",
    ("HIGH", "LOW"): "MODERATE",
    ("MODERATE", "EXTREME"): "HIGH",
    ("MODERATE", "HIGH"): "HIGH",
    ("MODERATE", "MODERATE"): "MODERATE",
    ("MODERATE", "LOW"): "LOW",
    ("LOW", "EXTREME"): "MODERATE",
    ("LOW", "HIGH"): "MODERATE",
    ("LOW", "MODERATE"): "LOW",
    ("LOW", "LOW"): "LOW",
}


class ZoneDataError(HeatSentinalError):
    """The zone dataset is missing or malformed."""

    status_code = 503
    error_type = "zone_data_unavailable"


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (Path(__file__).resolve().parents[2] / path).resolve()


@lru_cache(maxsize=1)
def load_zones() -> dict[str, Any]:
    """Load the zone FeatureCollection once."""
    path = _resolve(settings.ZONES_GEOJSON_PATH)
    if not path.exists():
        raise ZoneDataError(
            "The zone dataset was not found.",
            details={"expected_path": str(path)},
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ZoneDataError(
            "The zone dataset is not valid JSON.",
            details={"path": str(path)},
        ) from exc

    if document.get("type") != "FeatureCollection":
        raise ZoneDataError(
            "The zone dataset is not a GeoJSON FeatureCollection.",
            details={"type": document.get("type")},
        )
    if not document.get("features"):
        raise ZoneDataError("The zone dataset contains no features.")
    return document


def reset_caches() -> None:
    load_zones.cache_clear()


def list_zone_ids() -> list[str]:
    return [
        feature["properties"]["zone_id"]
        for feature in load_zones()["features"]
        if "zone_id" in feature.get("properties", {})
    ]


def get_zone(zone_id: str) -> dict[str, Any]:
    """Return one zone feature, or raise a clean 404."""
    for feature in load_zones()["features"]:
        if feature.get("properties", {}).get("zone_id") == zone_id:
            return feature
    raise ResourceNotFoundError(
        f"Zone '{zone_id}' does not exist.",
        details={"available_zones": list_zone_ids()},
    )


def zone_vulnerability(feature: dict[str, Any]) -> Any:
    """Phase 4 vulnerability for one zone. Reused, not reimplemented."""
    demographics = feature.get("properties", {}).get("demographics")
    if not isinstance(demographics, dict):
        raise ZoneDataError(
            "A zone is missing its demographics block.",
            details={"zone_id": feature.get("properties", {}).get("zone_id")},
        )
    try:
        return vulnerability_service.calculate_vulnerability(**demographics)
    except TypeError as exc:
        raise ZoneDataError(
            "A zone's demographics do not match the vulnerability inputs.",
            details={
                "zone_id": feature.get("properties", {}).get("zone_id"),
                "error": str(exc),
            },
        ) from exc


def priority_for(risk_level: str, vulnerability_level: str) -> str:
    """Prototype priority matrix. Not a published prioritisation standard."""
    return _PRIORITY_MATRIX.get((risk_level, vulnerability_level), "LOW")


def combine(
    thermal: Any, vulnerability_score: float, weather: Any
) -> Any:
    """Combined human risk via Phase 5. No new weights introduced."""
    return risk_service.predict_risk(
        temperature_c=weather["temperature"],
        relative_humidity=weather["humidity"],
        wind_speed=weather["wind_speed"],
        solar_radiation=weather.get("solar_radiation"),
        heat_index=thermal.heat_index,
        wbgt=thermal.wbgt,
        utci=thermal.utci,
        vulnerability_score=vulnerability_score,
    )


def build_zone_features(thermal: Any, weather: dict[str, Any]) -> list[dict]:
    """Score every zone against one shared hazard reading."""
    features: list[dict[str, Any]] = []

    for feature in load_zones()["features"]:
        properties = feature.get("properties", {})
        zone_id = properties.get("zone_id")
        if not zone_id:
            continue

        vulnerability = zone_vulnerability(feature)
        risk = combine(thermal, vulnerability.vulnerability_score, weather)

        features.append(
            {
                "type": "Feature",
                "geometry": feature.get("geometry"),
                "properties": {
                    "zone_id": zone_id,
                    "name": properties.get("name"),
                    "data_status": properties.get(
                        "data_status", "SYNTHETIC_DEMO"
                    ),
                    # 1. hazard -- identical across zones, and labelled so
                    "heat_hazard": risk.components.thermal_stress,
                    "heat_index": thermal.heat_index,
                    "wbgt": thermal.wbgt,
                    "utci": thermal.utci,
                    # 2. vulnerability -- what actually differs
                    "vulnerability": vulnerability.vulnerability_score,
                    "vulnerability_level": vulnerability.vulnerability_level,
                    # 3. combined human risk
                    "human_risk": risk.risk_score,
                    "risk_level": risk.risk_level,
                    # 4. intervention priority
                    "priority": priority_for(
                        risk.risk_level, vulnerability.vulnerability_level
                    ),
                    "vulnerability_contributions": vulnerability.contributions,
                },
            }
        )

    features.sort(
        key=lambda item: item["properties"]["human_risk"], reverse=True
    )
    return features


async def get_zone_risk(
    latitude: float | None = None, longitude: float | None = None
) -> dict[str, Any]:
    """Fetch hazard once, score every zone, return a GeoJSON collection."""
    from app.services import weather_service

    document = load_zones()
    if latitude is None or longitude is None:
        first = document["features"][0]["properties"].get("centroid")
        longitude, latitude = (
            (first[0], first[1]) if first else (77.2090, 28.6139)
        )

    current = await weather_service.get_current_weather(latitude, longitude)
    observation = current.current

    if observation.relative_humidity is None:
        raise HeatSentinalError(
            "The weather provider supplied no humidity, so zone hazard "
            "cannot be computed.",
            status_code=502,
        )

    thermal = thermal_service.calculate_thermal_stress(
        temperature=observation.temperature_c,
        relative_humidity=observation.relative_humidity,
        wind_speed=observation.wind_speed_ms or 0.0,
        solar_radiation=observation.solar_radiation_wm2,
    )
    weather = {
        "temperature": observation.temperature_c,
        "humidity": observation.relative_humidity,
        "wind_speed": observation.wind_speed_ms or 0.0,
        "solar_radiation": observation.solar_radiation_wm2,
    }

    features = build_zone_features(thermal, weather)

    return {
        "type": "FeatureCollection",
        "data_status": document.get("data_status", "SYNTHETIC_DEMO"),
        "warning": document.get("warning", SYNTHETIC_WARNING),
        "hazard_source": {
            "latitude": current.location.latitude,
            "longitude": current.location.longitude,
            "observed_at": observation.observed_at.isoformat(),
            "provider": current.provider,
            "note": (
                "Hazard is fetched once and applied to every zone. The "
                "provider's global model resolves to roughly 11 km, so all "
                "zones in this set fall within one grid cell. Zone-to-zone "
                "differences here come from VULNERABILITY, not from "
                "differing weather. True hyperlocal hazard would require "
                "downscaling that this repository does not contain."
            ),
        },
        "features": features,
    }
