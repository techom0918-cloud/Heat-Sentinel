"""Health / mortality data integration & validation (Phase 12).

Brings historical, government-reported heat-wave mortality observations
into HeatSentinal so model outputs can eventually be compared against
observed outcomes.

THIS IS DATA INTEGRATION + VALIDATION, NOT A NEW PREDICTION MODEL
Nothing here trains, retrains, or touches ml/heat_model.joblib. Nothing
here claims correlation proves causation, or that any intervention reduced
mortality -- see `VALIDATION_DISCLAIMER`.

DATA
The bundled CSV (`settings.HEALTH_DATA_CSV_PATH`) is REAL government data:
year/state-wise heat-wave death counts from a Rajya Sabha parliamentary
answer (see each row's own `source` column, preserved verbatim, never
overwritten). It is NOT synthetic and is NOT marked DEMO_SAMPLE. Any future
dataset that IS invented or illustrative must be marked DEMO_SAMPLE and
never silently mixed with GOVERNMENT_REPORTED rows in the same load.

VALIDATION, HONESTLY SCOPED
"Validate predicted heat risk against observed outcome" only means
something when a *matched, per-year-and-region* model prediction series
exists to compare against. This repository's ML model forecasts current
conditions 3 days ahead; it has never scored the 2018-2022 historical
window this dataset covers, and no such historical prediction file is
bundled here. Rather than inventing one, `summarise()` (served by
`GET /health-data/validation`) reports only what the observed data alone
supports -- yearly totals, regional ranking, and an observed high-risk
count -- and says explicitly that predictive skill metrics (confusion
matrix, probability of detection, precision, correlation) require a
matched prediction series this deployment does not have.
`compare_predictions_to_observations` below implements that comparison in
full, so it is one call away the day a real matched series exists; it is
exercised by tests with clearly-synthetic inputs, never with fabricated
"predictions" presented as real.
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.exceptions import HeatSentinalError

logger = logging.getLogger(__name__)

VALIDATION_DISCLAIMER = (
    "OBSERVED DATA SUMMARY, NOT A CAUSAL OR PREDICTIVE VALIDATION. "
    "Correlation between heat exposure and reported deaths is not evidence "
    "of causation. Reporting methodology may differ across years and "
    "states/UTs. Figures describe reported heat-wave deaths only, not total "
    "heat-attributable mortality, which is widely known to be undercounted."
)

REQUIRED_COLUMNS = {"year", "state", "heat_wave_deaths", "source"}


class HealthDataError(HeatSentinalError):
    """The health dataset is missing or structurally malformed."""

    status_code = 503
    error_type = "health_data_unavailable"


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (Path(__file__).resolve().parents[2] / path).resolve()


@lru_cache(maxsize=1)
def load_health_dataset() -> dict[str, Any]:
    """Load and validate the bundled CSV once.

    Returns clean observations plus data-quality counters. Never raises for
    a single bad row -- a malformed or duplicate row is dropped and
    counted, not fatal to the whole load. Only a missing file or a header
    that does not match the required schema raises `HealthDataError`.
    """
    path = _resolve(settings.HEALTH_DATA_CSV_PATH)
    if not path.exists():
        raise HealthDataError(
            "The health/mortality dataset was not found.",
            details={"expected_path": str(path)},
        )

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        found = {name.strip() for name in (reader.fieldnames or [])}
        if not REQUIRED_COLUMNS.issubset(found):
            raise HealthDataError(
                "The health/mortality dataset does not match the required "
                "schema (year, state, heat_wave_deaths, source).",
                details={
                    "found_columns": reader.fieldnames,
                    "required": sorted(REQUIRED_COLUMNS),
                },
            )
        rows = list(reader)

    observations: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    rejected = 0
    missing_values = 0

    for index, row in enumerate(rows):
        state = (row.get("state") or "").strip()
        source = (row.get("source") or "").strip()
        year_raw = (row.get("year") or "").strip()
        deaths_raw = (row.get("heat_wave_deaths") or "").strip()
        category = (row.get("category") or "").strip() or None

        if not state or not source or not year_raw:
            rejected += 1
            logger.warning("Rejected malformed health data row %d", index)
            continue

        try:
            year = int(float(year_raw))
        except ValueError:
            rejected += 1
            logger.warning(
                "Rejected health data row %d: non-numeric year %r",
                index,
                year_raw,
            )
            continue

        key = (year, state)
        if key in seen:
            rejected += 1
            logger.warning(
                "Rejected duplicate health data row %d: %s %s",
                index,
                year,
                state,
            )
            continue

        if deaths_raw == "" or deaths_raw.upper() == "NA":
            # Genuinely not reported. Excluded from `observations` (which
            # requires a known death count) but counted separately -- never
            # silently coerced to zero, which would fabricate a value.
            missing_values += 1
            seen.add(key)
            continue

        try:
            deaths = int(float(deaths_raw))
        except ValueError:
            rejected += 1
            logger.warning(
                "Rejected health data row %d: non-numeric deaths %r",
                index,
                deaths_raw,
            )
            continue

        if deaths < 0:
            rejected += 1
            logger.warning(
                "Rejected health data row %d: negative deaths %r",
                index,
                deaths_raw,
            )
            continue

        seen.add(key)
        observations.append(
            {
                "year": year,
                "state": state,
                "category": category,
                "heat_wave_deaths": deaths,
                "source": source,
                "data_status": "GOVERNMENT_REPORTED",
                "population": None,
                "exposure_period": None,
            }
        )

    return {
        "observations": observations,
        "source_file": str(path),
        "records_loaded_total": len(observations),
        "rejected_rows": rejected,
        "missing_value_rows": missing_values,
    }


def reset_caches() -> None:
    load_health_dataset.cache_clear()


def list_observations(
    year: int | None = None, state: str | None = None
) -> list[dict[str, Any]]:
    """Filtered, read-only view. Never mutates the cached dataset."""
    observations = load_health_dataset()["observations"]
    if year is not None:
        observations = [o for o in observations if o["year"] == year]
    if state is not None:
        needle = state.strip().lower()
        observations = [o for o in observations if o["state"].lower() == needle]
    return list(observations)


# ---------------------------------------------------------------------------
# Descriptive validation (observed data only)
# ---------------------------------------------------------------------------


def summarise(
    observations: list[dict[str, Any]] | None = None,
    high_risk_threshold: int | None = None,
) -> dict[str, Any]:
    """Yearly totals, regional ranking, and an observed high-risk count.

    Uses only the observed dataset. Computes nothing that requires a
    prediction series -- see the module docstring.
    """
    data = (
        observations
        if observations is not None
        else load_health_dataset()["observations"]
    )
    threshold = (
        high_risk_threshold
        if high_risk_threshold is not None
        else settings.HEALTH_HIGH_RISK_DEATH_THRESHOLD
    )

    notes = [
        "Computed from observed, government-reported data only. No "
        "model-predicted risk series for this historical period exists in "
        "this repository, so no confusion matrix, probability of "
        "detection, precision/recall, or correlation against predictions "
        "is computed here -- doing so would require fabricating a "
        "prediction series.",
        VALIDATION_DISCLAIMER,
    ]

    if not data:
        return {
            "period": "n/a",
            "regions_evaluated": 0,
            "observations": 0,
            "high_risk_threshold": threshold,
            "high_risk_events": 0,
            "yearly_totals": [],
            "top_regions": [],
            "notes": ["No observations matched the requested filters."] + notes,
        }

    years = sorted({row["year"] for row in data})
    states = sorted({row["state"] for row in data})

    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_state: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in data:
        by_year[row["year"]].append(row)
        by_state[row["state"]].append(row)

    yearly_totals = [
        {
            "year": year,
            "total_deaths": sum(r["heat_wave_deaths"] for r in rows),
            "states_reporting": len(rows),
        }
        for year, rows in sorted(by_year.items())
    ]

    region_totals = [
        {
            "state": state,
            "total_deaths": sum(r["heat_wave_deaths"] for r in rows),
            "years_reporting": len(rows),
            "high_risk_years": sum(
                1 for r in rows if r["heat_wave_deaths"] >= threshold
            ),
        }
        for state, rows in by_state.items()
    ]
    region_totals.sort(key=lambda r: r["total_deaths"], reverse=True)

    high_risk_events = sum(
        1 for row in data if row["heat_wave_deaths"] >= threshold
    )

    period = f"{years[0]}-{years[-1]}" if years else "n/a"

    return {
        "period": period,
        "regions_evaluated": len(states),
        "observations": len(data),
        "high_risk_threshold": threshold,
        "high_risk_events": high_risk_events,
        "yearly_totals": yearly_totals,
        "top_regions": region_totals[:10],
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Predictive validation -- ready for a matched prediction series
# ---------------------------------------------------------------------------


def compare_predictions_to_observations(
    predictions: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    high_risk_threshold: int | None = None,
) -> dict[str, Any]:
    """Confusion-matrix-style skill metrics, ONLY given real matched inputs.

    `predictions` must be
    `[{"year": int, "state": str, "high_risk": bool}, ...]` -- a prior
    prediction of whether that year/state would be a high-risk heat event,
    matched to `observations` by (year, state). This function never invents
    predictions; it only scores ones the caller supplies. It is not wired
    to the default `/health-data/validation` endpoint because this
    repository has no such historical series bundled -- see the module
    docstring.
    """
    threshold = (
        high_risk_threshold
        if high_risk_threshold is not None
        else settings.HEALTH_HIGH_RISK_DEATH_THRESHOLD
    )

    observed_by_key = {
        (row["year"], row["state"]): row["heat_wave_deaths"] >= threshold
        for row in observations
    }

    matched = 0
    true_positive = false_positive = false_negative = true_negative = 0

    for prediction in predictions:
        key = (prediction["year"], prediction["state"])
        if key not in observed_by_key:
            continue
        matched += 1
        observed_high_risk = observed_by_key[key]
        predicted_high_risk = bool(prediction["high_risk"])
        if predicted_high_risk and observed_high_risk:
            true_positive += 1
        elif predicted_high_risk and not observed_high_risk:
            false_positive += 1
        elif not predicted_high_risk and observed_high_risk:
            false_negative += 1
        else:
            true_negative += 1

    high_risk_events = true_positive + false_negative
    confusion_matrix = {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
    }

    if matched == 0 or high_risk_events == 0:
        return {
            "matched_observations": matched,
            "high_risk_events": high_risk_events,
            "confusion_matrix": confusion_matrix,
            "probability_of_detection": None,
            "precision": None,
            "notes": [
                "Insufficient matched data to compute probability of "
                "detection or precision: either no predictions matched an "
                "observation by (year, state), or no observed high-risk "
                "events fall within the matched set.",
            ],
        }

    pod = true_positive / high_risk_events
    precision = (
        true_positive / (true_positive + false_positive)
        if (true_positive + false_positive) > 0
        else None
    )

    return {
        "matched_observations": matched,
        "high_risk_events": high_risk_events,
        "confusion_matrix": confusion_matrix,
        "probability_of_detection": round(pod, 4),
        "precision": round(precision, 4) if precision is not None else None,
        "notes": [
            "Probability of detection = true_positive / high_risk_events. "
            "Precision = true_positive / (true_positive + false_positive).",
            VALIDATION_DISCLAIMER,
        ],
    }
