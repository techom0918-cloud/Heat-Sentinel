"""Application configuration.

All runtime configuration is loaded from environment variables (or a local
.env file) exactly once and cached. Nothing in the codebase should read
os.environ directly -- import `settings` from here instead.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings.

    Values are resolved in this order:
      1. real environment variables
      2. values in backend/.env
      3. the defaults declared below
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Application metadata -------------------------------------------
    APP_NAME: str = "HeatSentinal"
    APP_TITLE: str = "HeatSentinal API"
    APP_DESCRIPTION: str = (
        "AI-powered Human Heat-Health Early Warning and "
        "Decision Intelligence System"
    )
    APP_VERSION: str = "1.0.0"
    APP_MESSAGE: str = "Heat Health Intelligence API"

    # ---- API ------------------------------------------------------------
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = True

    # ---- Weather provider (Phase 2) -------------------------------------
    WEATHER_PROVIDER: str = "open-meteo"
    WEATHER_API_URL: str = "https://api.open-meteo.com/v1/forecast"
    REQUEST_TIMEOUT_SECONDS: float = 10.0

    # "auto" resolves the local timezone from the coordinates, so daily
    # aggregates line up with local calendar days rather than UTC days.
    WEATHER_TIMEZONE: str = "auto"

    # Upper bound accepted by /weather/forecast and /forecast/risk.
    WEATHER_FORECAST_MAX_DAYS: int = 5

    # ---- Thermal stress engine (Phase 3) --------------------------------
    # Heat Index category edges in Celsius, matching heat_pipeline.py.
    # PROTOTYPE bands, not a medical classification -- configurable so they
    # can be recalibrated against Indian heat-mortality data later.
    HEAT_INDEX_BOUNDS_C: str = "27,32,41,54"
    HEAT_INDEX_CATEGORIES: str = "LOW,MODERATE,HIGH,VERY_HIGH,EXTREME"

    # UTCI model applicability limits (pythermalcomfort / ISB Commission 6).
    UTCI_WIND_MIN_MS: float = 0.5
    UTCI_WIND_MAX_MS: float = 17.0
    UTCI_TEMP_MIN_C: float = -50.0
    UTCI_TEMP_MAX_C: float = 50.0

    @property
    def heat_index_bounds_list(self) -> list[float]:
        """Heat Index category edges, ascending."""
        return [
            float(edge.strip())
            for edge in self.HEAT_INDEX_BOUNDS_C.split(",")
            if edge.strip()
        ]

    @property
    def heat_index_categories_list(self) -> list[str]:
        """Heat Index category labels. One more label than there are edges."""
        return [
            label.strip()
            for label in self.HEAT_INDEX_CATEGORIES.split(",")
            if label.strip()
        ]

    # ---- Vulnerability engine (Phase 4) ---------------------------------
    # PROTOTYPE WEIGHTS. Not medically or scientifically validated. They are
    # plausible starting values, kept here (and only here) so they can be
    # recalibrated against real Indian data without touching any code.
    # Must sum to 1.0.
    VULNERABILITY_WEIGHT_ELDERLY: float = 0.20
    VULNERABILITY_WEIGHT_OUTDOOR_WORKERS: float = 0.20
    VULNERABILITY_WEIGHT_POPULATION_DENSITY: float = 0.15
    VULNERABILITY_WEIGHT_HEALTHCARE_ACCESS: float = 0.15
    VULNERABILITY_WEIGHT_HISTORICAL_EXPOSURE: float = 0.15
    VULNERABILITY_WEIGHT_HISTORICAL_MORTALITY: float = 0.15

    # Population density normalisation. "log" or "linear".
    # Log is the default because district density spans four orders of
    # magnitude; linear normalisation pins almost every district near zero.
    POPULATION_DENSITY_NORMALISATION: str = "log"
    POPULATION_DENSITY_FLOOR: float = 10.0
    POPULATION_DENSITY_CEILING: float = 20000.0

    # PROTOTYPE category edges, configurable.
    VULNERABILITY_BOUNDS: str = "0.25,0.50,0.75"
    VULNERABILITY_CATEGORIES: str = "LOW,MODERATE,HIGH,EXTREME"

    @property
    def vulnerability_weights(self) -> dict[str, float]:
        """Factor weights as a dict. Keys match the response `factors` keys."""
        return {
            "elderly_population": self.VULNERABILITY_WEIGHT_ELDERLY,
            "outdoor_workers": self.VULNERABILITY_WEIGHT_OUTDOOR_WORKERS,
            "population_density": self.VULNERABILITY_WEIGHT_POPULATION_DENSITY,
            "healthcare_accessibility": (
                self.VULNERABILITY_WEIGHT_HEALTHCARE_ACCESS
            ),
            "historical_heat_exposure": (
                self.VULNERABILITY_WEIGHT_HISTORICAL_EXPOSURE
            ),
            "historical_heat_mortality": (
                self.VULNERABILITY_WEIGHT_HISTORICAL_MORTALITY
            ),
        }

    @property
    def vulnerability_bounds_list(self) -> list[float]:
        return [
            float(edge.strip())
            for edge in self.VULNERABILITY_BOUNDS.split(",")
            if edge.strip()
        ]

    @property
    def vulnerability_categories_list(self) -> list[str]:
        return [
            label.strip()
            for label in self.VULNERABILITY_CATEGORIES.split(",")
            if label.strip()
        ]

    # ---- Machine learning (used from Phase 13 onwards) ------------------
    MODEL_PATH: str = "ml/models"

    # ---- Database (intentionally unused until PostgreSQL is needed) -----
    DATABASE_URL: str = ""

    # ---- CORS -----------------------------------------------------------
    # Stored as a plain comma-separated string on purpose. pydantic-settings
    # tries to JSON-decode list-typed fields, which makes a normal
    # `CORS_ORIGINS=a,b` line in .env blow up. Parsing happens below instead.
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS_ORIGINS split into a clean list of origins."""
        return [
            origin.strip()
            for origin in self.CORS_ORIGINS.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Return the cached Settings instance.

    Exposed as a function so FastAPI routes/tests can override it later
    via dependency injection.
    """
    return Settings()


settings: Settings = get_settings()
