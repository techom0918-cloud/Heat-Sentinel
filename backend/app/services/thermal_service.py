"""Human thermal stress engine.

Pure, deterministic calculations. This module makes no network calls and
imports no HTTP client -- the weather service is solely responsible for
retrieving data. Every function here is reusable by the future
risk_service.py and by the offline ML pipeline.

METHODOLOGY -- matched deliberately to the existing heat_pipeline.py so the
API and the trained model never disagree about what "WBGT" means.

1. HEAT INDEX -- recognised calculation
   US National Weather Service algorithm, computed in Fahrenheit.
   Below ~80 F apparent temperature it uses the simple Steadman-derived
   average; above that it uses the Rothfusz regression with the published
   low-RH and high-RH corrections. Result converted back to Celsius.

2. WBGT -- approximation, NOT full outdoor WBGT
   Wet-bulb temperature estimated with Stull (2011), then the shade form
   WBGT = 0.7 * Tw + 0.3 * Ta.
   True outdoor WBGT is 0.7*Tnw + 0.2*Tg + 0.1*Ta and requires a black-globe
   temperature Tg from a physical instrument. Solar radiation is deliberately
   NOT used to synthesise a globe temperature: doing so would require an
   unvalidated radiation model and would let a number that looks like
   occupational WBGT be read as if it were one.

3. UTCI -- reference implementation
   pythermalcomfort, which implements the ISB Commission 6 polynomial.
   Mean radiant temperature is assumed equal to air temperature (shade
   assumption), matching heat_pipeline.py. Wind is clamped to the model's
   applicability range.

None of these values is a medical assessment.
"""

from __future__ import annotations

import logging
import math

from app.core.config import settings
from app.core.exceptions import HeatSentinalError, ValidationError
from app.models.thermal import ThermalMethod, ThermalStressResult

logger = logging.getLogger(__name__)

# --- Optional dependency -------------------------------------------------
# UTCI is never faked. If the library is absent the index is reported as
# NOT_AVAILABLE rather than substituted with an invented formula.
try:  # pragma: no cover - exercised by the import-failure test
    from pythermalcomfort.models import utci as _utci_model

    UTCI_AVAILABLE = True
except ImportError:  # pragma: no cover
    _utci_model = None
    UTCI_AVAILABLE = False
    logger.warning(
        "pythermalcomfort is not installed; UTCI will report NOT_AVAILABLE."
    )

NOT_CLASSIFIED = "NOT_CLASSIFIED"
NOT_AVAILABLE = "NOT_AVAILABLE"

# Top of the published NWS heat index chart: 137 F.
_HEAT_INDEX_CHART_MAX_C = 58.3


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------


def celsius_to_fahrenheit(celsius: float) -> float:
    return celsius * 9.0 / 5.0 + 32.0


def fahrenheit_to_celsius(fahrenheit: float) -> float:
    return (fahrenheit - 32.0) * 5.0 / 9.0


# ---------------------------------------------------------------------------
# 1. Heat Index -- NWS algorithm
# ---------------------------------------------------------------------------


def heat_index_celsius(temperature_c: float, relative_humidity: float) -> float:
    """NWS Heat Index in degrees Celsius.

    Implements the published NWS procedure in Fahrenheit:

      1. Simple form:
         HI = 0.5 * (T + 61.0 + (T - 68.0) * 1.2 + RH * 0.094)

      2. If the mean of that result and T is below 80 F, the simple form is
         the answer. This is why the Rothfusz regression is not applied at
         all temperatures -- it is not valid in cool conditions.

      3. Otherwise the Rothfusz regression applies, plus:
         - low-RH correction   (RH < 13%, 80 F <= T <= 112 F)
         - high-RH correction  (RH > 85%, 80 F <= T <= 87 F)

    Source: NWS Technical Attachment SR 90-23 (Rothfusz, 1990) and the
    NWS Weather Prediction Center heat index documentation.

    Limitation: the regression was fitted for shaded conditions with light
    wind. Outside roughly 80-112 F it is an extrapolation.
    """
    temperature_f = celsius_to_fahrenheit(temperature_c)
    return fahrenheit_to_celsius(
        _heat_index_fahrenheit(temperature_f, relative_humidity)
    )


def _heat_index_fahrenheit(
    temperature_f: float, relative_humidity: float
) -> float:
    """Heat Index in Fahrenheit. Kept separate so it can be unit-tested
    against the NWS reference table directly."""
    simple = 0.5 * (
        temperature_f
        + 61.0
        + ((temperature_f - 68.0) * 1.2)
        + (relative_humidity * 0.094)
    )

    # NWS: use the simple form when its average with T is below 80 F.
    if (simple + temperature_f) / 2.0 < 80.0:
        return simple

    heat_index = (
        -42.379
        + 2.04901523 * temperature_f
        + 10.14333127 * relative_humidity
        - 0.22475541 * temperature_f * relative_humidity
        - 0.00683783 * temperature_f * temperature_f
        - 0.05481717 * relative_humidity * relative_humidity
        + 0.00122874 * temperature_f * temperature_f * relative_humidity
        + 0.00085282 * temperature_f * relative_humidity * relative_humidity
        - 0.00000199
        * temperature_f
        * temperature_f
        * relative_humidity
        * relative_humidity
    )

    # Low humidity correction.
    if relative_humidity < 13.0 and 80.0 <= temperature_f <= 112.0:
        heat_index -= ((13.0 - relative_humidity) / 4.0) * math.sqrt(
            (17.0 - abs(temperature_f - 95.0)) / 17.0
        )

    # High humidity correction.
    if relative_humidity > 85.0 and 80.0 <= temperature_f <= 87.0:
        heat_index += ((relative_humidity - 85.0) / 10.0) * (
            (87.0 - temperature_f) / 5.0
        )

    return heat_index


# ---------------------------------------------------------------------------
# 2. Wet-bulb (Stull) and shade WBGT
# ---------------------------------------------------------------------------


def wet_bulb_stull_celsius(
    temperature_c: float, relative_humidity: float
) -> float:
    """Wet-bulb temperature estimated by the Stull (2011) approximation.

    Source: Stull, R. (2011), "Wet-Bulb Temperature from Relative Humidity
    and Air Temperature", Journal of Applied Meteorology and Climatology,
    50(11), 2267-2269.

    Stated validity: roughly -20 C to +50 C, RH 5% to 99%, at standard
    sea-level pressure. Accuracy degrades outside that envelope, and the
    approximation carries no pressure term, so it is less reliable at
    altitude.
    """
    rh = relative_humidity
    return (
        temperature_c * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(temperature_c + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * (rh**1.5) * math.atan(0.023101 * rh)
        - 4.686035
    )


def wbgt_shade_celsius(
    temperature_c: float, relative_humidity: float
) -> float:
    """Shade WBGT approximation: 0.7 * Tw + 0.3 * Ta.

    This is the indoor / shade form of WBGT. It is NOT the outdoor
    occupational WBGT, which is 0.7*Tnw + 0.2*Tg + 0.1*Ta and needs a
    black-globe temperature from a physical instrument.

    Solar radiation is intentionally not used here. Converting irradiance
    into a globe temperature requires an unvalidated radiation model, and a
    number produced that way would be read as occupational WBGT while
    carrying none of its measurement basis.
    """
    wet_bulb = wet_bulb_stull_celsius(temperature_c, relative_humidity)
    return 0.7 * wet_bulb + 0.3 * temperature_c


# ---------------------------------------------------------------------------
# 3. UTCI
# ---------------------------------------------------------------------------


def utci_celsius(
    temperature_c: float,
    relative_humidity: float,
    wind_speed_ms: float,
) -> tuple[float | None, str, list[str]]:
    """UTCI via pythermalcomfort. Returns (value, category, notes).

    Mean radiant temperature is set equal to air temperature -- the shade
    assumption used by heat_pipeline.py. Under strong sunlight the true mean
    radiant temperature is well above air temperature, so this understates
    outdoor heat load.

    Wind is clamped to the model's applicability range rather than passed
    through, because out-of-range input makes the library return NaN.
    """
    notes: list[str] = []

    if not UTCI_AVAILABLE:
        return (
            None,
            NOT_AVAILABLE,
            ["pythermalcomfort is not installed; UTCI was not computed."],
        )

    if not (
        settings.UTCI_TEMP_MIN_C <= temperature_c <= settings.UTCI_TEMP_MAX_C
    ):
        return (
            None,
            NOT_AVAILABLE,
            [
                f"Air temperature {temperature_c} C is outside the UTCI "
                f"applicability range "
                f"({settings.UTCI_TEMP_MIN_C} to {settings.UTCI_TEMP_MAX_C} C). "
                "UTCI was not computed rather than extrapolated."
            ],
        )

    wind = wind_speed_ms
    if wind < settings.UTCI_WIND_MIN_MS:
        notes.append(
            f"Wind speed {wind_speed_ms} m/s raised to the UTCI minimum of "
            f"{settings.UTCI_WIND_MIN_MS} m/s."
        )
        wind = settings.UTCI_WIND_MIN_MS
    elif wind > settings.UTCI_WIND_MAX_MS:
        notes.append(
            f"Wind speed {wind_speed_ms} m/s capped at the UTCI maximum of "
            f"{settings.UTCI_WIND_MAX_MS} m/s."
        )
        wind = settings.UTCI_WIND_MAX_MS

    try:
        result = _utci_model(
            tdb=temperature_c,
            tr=temperature_c,  # shade assumption: MRT = air temperature
            v=wind,
            rh=relative_humidity,
        )
        value = float(result.utci)
        category = str(result.stress_category)
    except Exception as exc:  # noqa: BLE001 - library may raise anything
        logger.warning("UTCI computation failed: %s", exc)
        return None, NOT_AVAILABLE, ["UTCI computation failed for these inputs."]

    if math.isnan(value):
        return (
            None,
            NOT_AVAILABLE,
            ["UTCI returned no value for these inputs (outside model limits)."],
        )

    return round(value, 1), _normalise_utci_category(category), notes


def _normalise_utci_category(raw: str) -> str:
    """'extreme heat stress' -> 'EXTREME_HEAT_STRESS'."""
    if not raw or raw.lower() == "nan":
        return NOT_AVAILABLE
    return raw.strip().upper().replace(" ", "_")


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def heat_index_category(heat_index_c: float) -> str:
    """Band the Heat Index using configurable Celsius edges.

    Defaults are 27 / 32 / 41 / 54 C, the boundaries already used by
    heat_pipeline.py.

    PROTOTYPE INTERPRETATION. These are the prototype pipeline's bands, not
    a universal medical risk classification. They are configurable precisely
    so they can be recalibrated against Indian heat-mortality data later.
    """
    edges = settings.heat_index_bounds_list
    labels = settings.heat_index_categories_list

    for index, edge in enumerate(edges):
        if heat_index_c < edge:
            return labels[index]
    return labels[-1]


# ---------------------------------------------------------------------------
# Method provenance
# ---------------------------------------------------------------------------


def _methods() -> list[ThermalMethod]:
    return [
        ThermalMethod(
            index="heat_index",
            method=(
                "US NWS algorithm: simple Steadman form below ~80 F, "
                "Rothfusz (1990) regression above, with published low-RH "
                "and high-RH corrections."
            ),
            classification="RECOGNISED_CALCULATION",
            assumptions=[
                "Shaded conditions with light wind.",
                "Computed in Fahrenheit, reported in Celsius.",
            ],
            limitations=[
                "Fitted for roughly 80-112 F; outside that it extrapolates.",
                "Does not account for wind, solar radiation, or clothing.",
                "Not a medical assessment.",
            ],
        ),
        ThermalMethod(
            index="wbgt",
            method=(
                "Shade WBGT approximation: 0.7 * Tw + 0.3 * Ta, with Tw "
                "estimated by the Stull (2011) approximation."
            ),
            classification="APPROXIMATION",
            assumptions=[
                "Shade conditions; no black-globe temperature available.",
                "Standard sea-level pressure (the Stull form has no "
                "pressure term).",
            ],
            limitations=[
                "NOT the full outdoor WBGT (0.7*Tnw + 0.2*Tg + 0.1*Ta), "
                "which requires an instrument-measured globe temperature.",
                "Solar radiation is deliberately unused: synthesising a "
                "globe temperature from irradiance would require an "
                "unvalidated model.",
                "Must not be compared against ISO 7243 or ACGIH "
                "occupational limits, which are defined on outdoor WBGT.",
                "Stull validity is roughly -20 to 50 C and RH 5-99%.",
            ],
        ),
        ThermalMethod(
            index="utci",
            method=(
                "pythermalcomfort implementation of the UTCI polynomial "
                "(ISB Commission 6; Brode et al. 2012)."
                if UTCI_AVAILABLE
                else "Unavailable: pythermalcomfort is not installed."
            ),
            classification="REFERENCE_IMPLEMENTATION",
            assumptions=[
                "Mean radiant temperature assumed equal to air temperature "
                "(shade assumption, matching heat_pipeline.py).",
                f"Wind clamped to {settings.UTCI_WIND_MIN_MS}-"
                f"{settings.UTCI_WIND_MAX_MS} m/s, the model's valid range.",
            ],
            limitations=[
                "The MRT = air temperature assumption understates heat load "
                "in direct sunlight, where true MRT is much higher.",
                f"Air temperature outside {settings.UTCI_TEMP_MIN_C} to "
                f"{settings.UTCI_TEMP_MAX_C} C returns no value. Indian "
                "extremes can exceed 50 C.",
                "Assumes a reference walking person; not individualised.",
            ],
        ),
    ]


def _assumptions(notes: list[str]) -> list[str]:
    base = [
        "Heat Index: NWS algorithm, shade conditions, temperature and "
        "humidity only.",
        "WBGT: SHADE APPROXIMATION using Stull (2011) wet-bulb. Not the "
        "complete outdoor occupational WBGT.",
        "WBGT: solar radiation is accepted but not used in the calculation.",
        "UTCI: mean radiant temperature assumed equal to air temperature "
        "(shade assumption).",
        "All three indices are environmental heat-stress indicators, not "
        "medical assessments of any individual.",
    ]
    return base + notes


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def calculate_thermal_stress(
    temperature: float,
    relative_humidity: float,
    wind_speed: float = 0.0,
    solar_radiation: float | None = None,
) -> ThermalStressResult:
    """Compute all three indices for one set of conditions.

    Deterministic and side-effect free, so risk_service.py and the offline
    ML pipeline can call it and get identical numbers.
    """
    _validate(temperature, relative_humidity, wind_speed, solar_radiation)

    notes: list[str] = []

    try:
        heat_index = round(
            heat_index_celsius(temperature, relative_humidity), 1
        )
        wet_bulb = round(
            wet_bulb_stull_celsius(temperature, relative_humidity), 1
        )
        wbgt = round(wbgt_shade_celsius(temperature, relative_humidity), 1)
    except (ValueError, OverflowError, ZeroDivisionError) as exc:
        logger.exception("Thermal calculation failed")
        raise HeatSentinalError(
            "Thermal stress calculation failed for these inputs.",
            status_code=422,
            details={
                "temperature": temperature,
                "relative_humidity": relative_humidity,
            },
        ) from exc

    if not -20.0 <= temperature <= 50.0:
        notes.append(
            f"Air temperature {temperature} C is outside the Stull (2011) "
            "validity range (-20 to 50 C); the wet-bulb estimate and "
            "therefore the WBGT approximation are less reliable."
        )
    if relative_humidity < 5.0:
        notes.append(
            f"Relative humidity {relative_humidity}% is below the Stull "
            "(2011) validity floor of 5%; the wet-bulb estimate is less "
            "reliable."
        )

    # The published NWS heat index chart stops at 137 F (58.3 C). Beyond
    # that the Rothfusz regression is being extrapolated far outside the
    # domain it was fitted on, and the number stops being physically
    # meaningful even though the arithmetic still works.
    if heat_index > _HEAT_INDEX_CHART_MAX_C:
        notes.append(
            f"Heat Index {heat_index} C is above the top of the published "
            f"NWS chart ({_HEAT_INDEX_CHART_MAX_C} C). The Rothfusz "
            "regression is extrapolating well beyond its fitted domain; "
            "treat the magnitude as indicative of extreme conditions rather "
            "than as a calibrated apparent temperature."
        )

    utci_value, utci_cat, utci_notes = utci_celsius(
        temperature, relative_humidity, wind_speed
    )
    notes.extend(utci_notes)

    return ThermalStressResult(
        temperature=temperature,
        relative_humidity=relative_humidity,
        wind_speed=wind_speed,
        solar_radiation=solar_radiation,
        heat_index=heat_index,
        heat_index_category=heat_index_category(heat_index),
        wet_bulb_temperature=wet_bulb,
        wbgt=wbgt,
        wbgt_category=NOT_CLASSIFIED,
        utci=utci_value,
        utci_category=utci_cat,
        assumptions=_assumptions(notes),
        methods=_methods(),
        notes=notes,
    )


def _validate(
    temperature: float,
    relative_humidity: float,
    wind_speed: float,
    solar_radiation: float | None,
) -> None:
    """Domain validation, independent of FastAPI.

    Phase 5 will call this service directly with no HTTP layer to guard it.
    """
    if not -90.0 <= temperature <= 60.0:
        raise ValidationError(
            "Temperature must be between -90 and 60 degrees Celsius.",
            details={"field": "temperature", "received": temperature},
        )
    if not 0.0 <= relative_humidity <= 100.0:
        raise ValidationError(
            "Relative humidity must be between 0 and 100 percent.",
            details={"field": "relative_humidity", "received": relative_humidity},
        )
    if wind_speed < 0.0:
        raise ValidationError(
            "Wind speed must not be negative.",
            details={"field": "wind_speed", "received": wind_speed},
        )
    if solar_radiation is not None and solar_radiation < 0.0:
        raise ValidationError(
            "Solar radiation must not be negative.",
            details={"field": "solar_radiation", "received": solar_radiation},
        )
