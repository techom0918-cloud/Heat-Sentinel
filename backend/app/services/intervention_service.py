"""Heat action simulator.

Answers "what if we act?" by re-running the EXISTING risk calculation with
modelled intervention effects applied, then reporting the change.

WHAT THIS IS NOT
It does not predict deaths prevented, mortality reduction, or any medical
outcome. It reports an estimated change in HeatSentinal's own modelled risk
score under explicit, configurable assumptions. Those assumptions are
plausible starting values, NOT empirically validated effect sizes -- this
repository contains no intervention evaluation data.

HOW EFFECTS ARE APPLIED
Interventions act on one of two channels:

    VULNERABILITY   cooling centres, water distribution -- they change how
                    badly the exposed population copes
    EXPOSURE        work-hour shifts, shade, public alerts -- they change
                    how much heat load people take on

Each has a configured maximum effect, scaled linearly by coverage:

    effect = max_effect x coverage

Multiple interventions on the same channel combine multiplicatively:

    remaining = product of (1 - effect_i)

Multiplicative rather than additive so that stacking interventions can
never exceed 100% reduction, and so each additional measure yields
diminishing returns -- which is the more defensible assumption when the
alternative is a sum that reaches an impossible total.

The simulator never retrains or touches the ML model. It operates on the
downstream risk layer only.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.services import risk_service

logger = logging.getLogger(__name__)

CHANNEL_VULNERABILITY = "VULNERABILITY"
CHANNEL_EXPOSURE = "EXPOSURE"

# Channel and human-readable assumption per intervention. Effect SIZES live
# in configuration; only the channel and wording live here.
INTERVENTION_CATALOGUE: dict[str, dict[str, str]] = {
    "COOLING_CENTER": {
        "channel": CHANNEL_VULNERABILITY,
        "label": "Cooling centres",
        "assumption": (
            "Assumed to reduce modelled vulnerability for the covered share "
            "of the population by providing air-conditioned refuge during "
            "peak hours."
        ),
    },
    "WATER_DISTRIBUTION": {
        "channel": CHANNEL_VULNERABILITY,
        "label": "Water distribution",
        "assumption": (
            "Assumed to reduce modelled vulnerability for the covered share "
            "of the population by improving hydration."
        ),
    },
    "WORK_HOUR_SHIFT": {
        "channel": CHANNEL_EXPOSURE,
        "label": "Outdoor work-hour shift",
        "assumption": (
            "Assumed to reduce modelled heat exposure for the covered share "
            "of outdoor workers by moving labour away from peak hours."
        ),
    },
    "PUBLIC_ALERT": {
        "channel": CHANNEL_EXPOSURE,
        "label": "Public heat alerts",
        "assumption": (
            "Assumed to produce a small reduction in modelled exposure "
            "through voluntary behaviour change. Deliberately the smallest "
            "assumed effect, since compliance is uncertain."
        ),
    },
    "SHADE_REST_AREA": {
        "channel": CHANNEL_EXPOSURE,
        "label": "Shaded rest areas",
        "assumption": (
            "Assumed to reduce modelled exposure for the covered share of "
            "the population by lowering radiant heat load."
        ),
    },
}

SIMULATION_DISCLAIMER = (
    "MODELLED SCENARIO. Reports an estimated change in HeatSentinal's own "
    "risk score under explicit assumptions. It does NOT estimate deaths "
    "prevented, mortality reduction, or any medical outcome. Intervention "
    "effect sizes are uncalibrated prototype assumptions, not empirically "
    "validated effectiveness."
)


def supported_types() -> list[str]:
    return sorted(INTERVENTION_CATALOGUE)


def max_effect(intervention_type: str) -> float:
    """Configured maximum effect for one intervention type."""
    effects = settings.intervention_effects
    if intervention_type not in effects:
        raise ValidationError(
            f"Unknown intervention type '{intervention_type}'.",
            details={"supported": supported_types()},
        )
    return effects[intervention_type]


def validate_interventions(interventions: list[dict[str, Any]]) -> None:
    """Reject unknown types, bad coverage, and duplicates."""
    if not interventions:
        raise ValidationError(
            "At least one intervention is required to simulate.",
            details={"supported": supported_types()},
        )

    seen: set[str] = set()
    for item in interventions:
        kind = item.get("type")
        if kind not in INTERVENTION_CATALOGUE:
            raise ValidationError(
                f"Unknown intervention type '{kind}'.",
                details={"supported": supported_types()},
            )
        if kind in seen:
            raise ValidationError(
                f"Intervention '{kind}' was supplied more than once.",
                details={"duplicate": kind},
            )
        seen.add(kind)

        coverage = item.get("coverage")
        if coverage is None or not 0.0 <= float(coverage) <= 1.0:
            raise ValidationError(
                "Coverage must be between 0 and 1.",
                details={"intervention": kind, "received": coverage},
            )


def compute_channel_reductions(
    interventions: list[dict[str, Any]]
) -> tuple[float, float, list[dict[str, Any]]]:
    """Return (vulnerability reduction, exposure reduction, per-item detail).

    Same-channel effects combine multiplicatively, so stacking can approach
    but never reach a total reduction.
    """
    remaining = {CHANNEL_VULNERABILITY: 1.0, CHANNEL_EXPOSURE: 1.0}
    applied: list[dict[str, Any]] = []

    for item in interventions:
        kind = item["type"]
        coverage = float(item["coverage"])
        entry = INTERVENTION_CATALOGUE[kind]
        effect = max_effect(kind) * coverage

        remaining[entry["channel"]] *= 1.0 - effect
        applied.append(
            {
                "type": kind,
                "label": entry["label"],
                "channel": entry["channel"],
                "coverage": round(coverage, 4),
                "max_effect": round(max_effect(kind), 4),
                "applied_effect": round(effect, 4),
                "assumption": entry["assumption"],
            }
        )

    return (
        1.0 - remaining[CHANNEL_VULNERABILITY],
        1.0 - remaining[CHANNEL_EXPOSURE],
        applied,
    )


def simulate(
    *,
    temperature_c: float,
    relative_humidity: float,
    heat_index: float,
    wbgt: float,
    vulnerability_score: float,
    interventions: list[dict[str, Any]],
    utci: float | None = None,
    wind_speed: float = 0.0,
    solar_radiation: float | None = None,
    zone_id: str | None = None,
) -> dict[str, Any]:
    """Baseline vs simulated risk under the supplied interventions.

    Inputs are never mutated. Both scores come from the same Phase 5
    `risk_service.predict_risk`, so baseline and simulation are directly
    comparable.
    """
    validate_interventions(interventions)

    baseline = risk_service.predict_risk(
        temperature_c=temperature_c,
        relative_humidity=relative_humidity,
        wind_speed=wind_speed,
        solar_radiation=solar_radiation,
        heat_index=heat_index,
        wbgt=wbgt,
        utci=utci,
        vulnerability_score=vulnerability_score,
    )

    vuln_reduction, exposure_reduction, applied = compute_channel_reductions(
        interventions
    )

    # Vulnerability is scaled directly. Exposure is applied to the thermal
    # indices by scaling each toward its normalisation floor, so the effect
    # lands in the same units the risk engine already understands rather
    # than inventing a new one.
    simulated_vulnerability = max(
        0.0, min(1.0, vulnerability_score * (1.0 - vuln_reduction))
    )
    simulated_heat_index = _scale_toward_floor(
        heat_index, settings.RISK_HEAT_INDEX_MIN_C, exposure_reduction
    )
    simulated_wbgt = _scale_toward_floor(
        wbgt, settings.RISK_WBGT_MIN_C, exposure_reduction
    )
    simulated_utci = (
        _scale_toward_floor(
            utci, settings.RISK_UTCI_MIN_C, exposure_reduction
        )
        if utci is not None
        else None
    )

    simulated = risk_service.predict_risk(
        temperature_c=temperature_c,
        relative_humidity=relative_humidity,
        wind_speed=wind_speed,
        solar_radiation=solar_radiation,
        heat_index=simulated_heat_index,
        wbgt=simulated_wbgt,
        utci=simulated_utci,
        vulnerability_score=simulated_vulnerability,
    )

    reduction = baseline.risk_score - simulated.risk_score
    percent = (
        (reduction / baseline.risk_score * 100.0)
        if baseline.risk_score > 0
        else 0.0
    )

    return {
        "zone_id": zone_id,
        "baseline": {
            "risk_score": baseline.risk_score,
            "risk_level": baseline.risk_level,
            "thermal_stress": baseline.components.thermal_stress,
            "vulnerability": baseline.components.vulnerability,
        },
        "simulation": {
            "risk_score": simulated.risk_score,
            "risk_level": simulated.risk_level,
            "thermal_stress": simulated.components.thermal_stress,
            "vulnerability": simulated.components.vulnerability,
        },
        "estimated_risk_reduction": round(max(0.0, reduction), 4),
        "estimated_risk_reduction_percent": round(max(0.0, percent), 2),
        "risk_level_changed": baseline.risk_level != simulated.risk_level,
        "applied_interventions": applied,
        "channel_reductions": {
            "vulnerability": round(vuln_reduction, 4),
            "exposure": round(exposure_reduction, 4),
        },
        "assumptions": [
            f"{item['label']}: {item['assumption']}" for item in applied
        ]
        + [
            "Effects scale linearly with coverage and combine "
            "multiplicatively within a channel, so stacking yields "
            "diminishing returns and can never exceed a total reduction.",
            "Effect sizes are uncalibrated prototype assumptions, not "
            "empirically validated effectiveness.",
        ],
        "disclaimer": SIMULATION_DISCLAIMER,
    }


def _scale_toward_floor(value: float, floor: float, reduction: float) -> float:
    """Move a thermal index toward its normalisation floor by `reduction`.

    Scaling the index itself rather than the normalised score keeps the
    simulation in the units the risk engine already validates, and means an
    index already at or below the floor cannot be reduced further.
    """
    if reduction <= 0 or value <= floor:
        return value
    return floor + (value - floor) * (1.0 - reduction)
