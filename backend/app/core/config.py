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
