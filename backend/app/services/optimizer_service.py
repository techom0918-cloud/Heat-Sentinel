"""AI Action Optimizer.

Phase 9 answers "what happens if we choose these interventions?". This
module answers the next question: "given a budget and available resources,
which interventions should we choose?"

REUSE, NOT REIMPLEMENTATION
Every candidate plan is scored by calling the EXISTING Phase 9
`intervention_service.simulate`, so the optimizer inherits exactly the same
effect-size assumptions, channel logic (VULNERABILITY vs EXPOSURE) and
disclaimers. Nothing in this module recomputes an intervention's effect on
risk -- it only decides HOW MUCH of each intervention is worth buying.

WHAT'S NEW HERE
Phase 9 takes a coverage fraction (0-1) per intervention directly. Real
resources are counted in units (cooling centres, water tankers, field
workers), not fractions of coverage, so this module adds one thing Phase 9
does not have: PROTOTYPE unit economics (`settings.optimizer_unit_economics`)
translating "N units of resource X" into a coverage fraction, and a cost.

METHOD -- documented, deterministic greedy search
    while budget and resources remain:
        for every intervention still allowed, affordable, resourced, and
        below 100% coverage:
            price a candidate plan with one more unit of that intervention,
            via intervention_service.simulate
        add whichever candidate yields the largest risk reduction per unit
        of budget spent
        stop when no affordable, resourced candidate improves risk

This is a hill-climbing heuristic, not a guaranteed global optimum -- true
combinatorial search over unit counts is exponential in the number of
resource units available. It is transparent (every step is one simulator
call), deterministic (ties break on intervention type name), and bounded
(`OPTIMIZER_MAX_ITERATIONS`).

SAFETY
This is a decision-support prototype. It never claims deaths prevented,
mortality reduction, or causal effectiveness, and it never executes an
intervention in the real world -- it only recommends a modelled plan for a
human to review. See `OPTIMIZER_DISCLAIMER`.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.services import intervention_service, risk_service

logger = logging.getLogger(__name__)

_EPSILON = 1e-9

OPTIMIZER_DISCLAIMER = (
    "MODELLED RECOMMENDATION. Selects a feasible intervention plan under "
    "budget and resource constraints by maximising HeatSentinal's own "
    "modelled risk reduction, via the Phase 9 intervention simulator. It "
    "does NOT estimate deaths prevented, mortality reduction, or any "
    "medical outcome, is NOT empirically validated effectiveness, and does "
    "NOT execute any real-world action -- it only recommends a plan for a "
    "human to review."
)

METHOD_DESCRIPTION = (
    "Deterministic greedy search: at each step, add one resource unit of "
    "whichever allowed intervention yields the largest modelled risk "
    "reduction per unit of budget spent, among interventions that are "
    "still affordable, still have resource units available, and have not "
    "yet reached 100% modelled coverage. Stops when no affordable, "
    "resourced unit improves risk, or after "
    f"{settings.OPTIMIZER_MAX_ITERATIONS} steps. A hill-climbing "
    "heuristic, not a guaranteed global optimum -- exhaustive search over "
    "unit counts is exponential."
)


def _validate(
    budget: float,
    available_resources: dict[str, int],
    allowed_interventions: list[str],
) -> None:
    """Domain validation, independent of FastAPI/pydantic."""
    if budget < 0:
        raise ValidationError(
            "Budget must not be negative.",
            details={"field": "budget", "received": budget},
        )

    for name, quantity in available_resources.items():
        if quantity < 0:
            raise ValidationError(
                "Resource counts must not be negative.",
                details={"field": name, "received": quantity},
            )

    if not allowed_interventions:
        raise ValidationError(
            "At least one intervention must be allowed.",
            details={"supported": intervention_service.supported_types()},
        )

    supported = set(intervention_service.supported_types())
    unknown = sorted(set(allowed_interventions) - supported)
    if unknown:
        raise ValidationError(
            f"Unknown intervention type(s): {unknown}.",
            details={
                "unknown": unknown,
                "supported": sorted(supported),
            },
        )

    if len(set(allowed_interventions)) != len(allowed_interventions):
        raise ValidationError(
            "allowed_interventions must not contain duplicates.",
            details={"received": allowed_interventions},
        )


def _plan_to_interventions(quantities: dict[str, int]) -> list[dict[str, Any]]:
    """Positive-quantity entries, converted to Phase 9's coverage input."""
    economics = settings.optimizer_unit_economics
    interventions = []
    for kind, quantity in quantities.items():
        if quantity <= 0:
            continue
        coverage_per_unit = economics[kind]["coverage_per_unit"]
        coverage = min(1.0, quantity * float(coverage_per_unit))
        interventions.append({"type": kind, "coverage": coverage})
    return interventions


def _score(
    quantities: dict[str, int], weather_kwargs: dict[str, Any], zone_id: str | None
) -> float:
    """Simulated risk score for a plan, via the Phase 9 simulator.

    An all-zero plan has no interventions to simulate, so its score is the
    plain Phase 5 baseline -- the same value Phase 9 itself uses as
    "baseline" internally.
    """
    interventions = _plan_to_interventions(quantities)
    if not interventions:
        return risk_service.predict_risk(**weather_kwargs).risk_score
    return intervention_service.simulate(
        **weather_kwargs, interventions=interventions, zone_id=zone_id
    )["simulation"]["risk_score"]


def optimize(
    *,
    zone_id: str,
    budget: float,
    available_resources: dict[str, int],
    temperature_c: float,
    relative_humidity: float,
    heat_index: float,
    wbgt: float,
    vulnerability_score: float,
    allowed_interventions: list[str] | None = None,
    utci: float | None = None,
    wind_speed: float = 0.0,
    solar_radiation: float | None = None,
) -> dict[str, Any]:
    """Choose the best feasible intervention plan for one zone.

    Inputs are never mutated. Deterministic: identical inputs always yield
    an identical plan, because selection uses no randomness and ties break
    on intervention type name.
    """
    allowed = list(
        allowed_interventions
        if allowed_interventions is not None
        else intervention_service.supported_types()
    )
    resources = dict(available_resources)  # local copy; caller's dict is not touched
    _validate(budget, resources, allowed)

    weather_kwargs = dict(
        temperature_c=temperature_c,
        relative_humidity=relative_humidity,
        heat_index=heat_index,
        wbgt=wbgt,
        vulnerability_score=vulnerability_score,
        utci=utci,
        wind_speed=wind_speed,
        solar_radiation=solar_radiation,
    )

    economics = settings.optimizer_unit_economics
    catalogue = intervention_service.INTERVENTION_CATALOGUE

    baseline_score = risk_service.predict_risk(**weather_kwargs)

    quantities: dict[str, int] = {kind: 0 for kind in sorted(allowed)}
    resources_remaining = {
        name: int(count) for name, count in resources.items()
    }
    budget_remaining = float(budget)
    current_risk = baseline_score.risk_score

    for _ in range(settings.OPTIMIZER_MAX_ITERATIONS):
        best_kind: str | None = None
        best_marginal = 0.0
        best_risk_after: float | None = None
        best_value = -1.0

        for kind in sorted(allowed):  # sorted -> deterministic tie-break
            unit_cost = float(economics[kind]["unit_cost"])
            coverage_per_unit = float(economics[kind]["coverage_per_unit"])
            resource_name = str(economics[kind]["resource"])

            current_coverage = min(
                1.0, quantities[kind] * coverage_per_unit
            )
            if current_coverage >= 1.0 - _EPSILON:
                continue  # already at full modelled coverage
            if unit_cost > budget_remaining + _EPSILON:
                continue  # cannot afford one more unit
            if resources_remaining.get(resource_name, 0) < 1:
                continue  # no resource units left

            trial = dict(quantities)
            trial[kind] += 1
            risk_after = _score(trial, weather_kwargs, zone_id)
            marginal = current_risk - risk_after
            if marginal <= _EPSILON:
                continue  # no further modelled improvement

            value = marginal / unit_cost  # risk reduction per unit budget
            if value > best_value + _EPSILON:
                best_kind = kind
                best_marginal = marginal
                best_risk_after = risk_after
                best_value = value

        if best_kind is None:
            break

        unit_cost = float(economics[best_kind]["unit_cost"])
        resource_name = str(economics[best_kind]["resource"])
        quantities[best_kind] += 1
        resources_remaining[resource_name] -= 1
        budget_remaining -= unit_cost
        current_risk = best_risk_after
        logger.debug(
            "optimizer: +1 %s (marginal=%.4f, risk=%.4f)",
            best_kind,
            best_marginal,
            current_risk,
        )

    optimized_score = (
        intervention_service.simulate(
            **weather_kwargs,
            interventions=_plan_to_interventions(quantities),
            zone_id=zone_id,
        )
        if any(q > 0 for q in quantities.values())
        else None
    )
    optimized_risk = (
        optimized_score["simulation"]["risk_score"]
        if optimized_score is not None
        else baseline_score.risk_score
    )
    optimized_risk_level = (
        optimized_score["simulation"]["risk_level"]
        if optimized_score is not None
        else baseline_score.risk_level
    )

    recommended_actions = []
    total_used = {name: 0 for name in resources_remaining}
    budget_used_total = 0.0
    assumptions: list[str] = []

    for kind in sorted(allowed):
        quantity = quantities[kind]
        if quantity <= 0:
            continue
        entry = catalogue[kind]
        econ = economics[kind]
        coverage = min(1.0, quantity * float(econ["coverage_per_unit"]))
        cost = quantity * float(econ["unit_cost"])
        resource_name = str(econ["resource"])
        total_used[resource_name] = total_used.get(resource_name, 0) + quantity
        budget_used_total += cost

        recommended_actions.append(
            {
                "type": kind,
                "quantity": quantity,
                "resource_type": resource_name,
                "coverage": round(coverage, 4),
                "unit_cost": float(econ["unit_cost"]),
                "cost": round(cost, 2),
                "channel": entry["channel"],
                "assumption": entry["assumption"],
            }
        )
        assumptions.append(
            f"{entry['label']}: {quantity} unit(s) of '{resource_name}' at "
            f"{econ['coverage_per_unit']:.0%} coverage each "
            f"(configured, uncalibrated) -> {coverage:.0%} modelled coverage."
        )

    reduction = baseline_score.risk_score - optimized_risk
    percent = (
        (reduction / baseline_score.risk_score * 100.0)
        if baseline_score.risk_score > 0
        else 0.0
    )

    resources_used = {
        name: total_used.get(name, 0) for name in resources
    }
    resources_remaining_out = {
        name: resources[name] - resources_used.get(name, 0) for name in resources
    }

    assumptions.append(METHOD_DESCRIPTION)
    assumptions.append(
        "Unit costs and coverage-per-unit are configured prototype "
        "assumptions, not procurement or reach data. Intervention "
        "effectiveness itself is unchanged from the Phase 9 simulator."
    )

    return {
        "zone_id": zone_id,
        "baseline_risk": round(baseline_score.risk_score, 4),
        "baseline_risk_level": baseline_score.risk_level,
        "optimized_risk": round(optimized_risk, 4),
        "optimized_risk_level": optimized_risk_level,
        "estimated_risk_reduction": round(max(0.0, reduction), 4),
        "estimated_risk_reduction_percent": round(max(0.0, percent), 2),
        "risk_level_changed": baseline_score.risk_level != optimized_risk_level,
        "recommended_actions": recommended_actions,
        "resources_used": resources_used,
        "resources_remaining": resources_remaining_out,
        "budget": round(float(budget), 2),
        "budget_used": round(budget_used_total, 2),
        "budget_remaining": round(float(budget) - budget_used_total, 2),
        "method": METHOD_DESCRIPTION,
        "assumptions": assumptions,
        "disclaimer": OPTIMIZER_DISCLAIMER,
    }
