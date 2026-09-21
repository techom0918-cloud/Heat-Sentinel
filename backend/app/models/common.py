"""Pydantic schemas shared across the API.

Domain-specific schemas (weather, thermal, risk, ...) live in their own
modules from Phase 2 onwards.
"""

from pydantic import BaseModel, Field


class RootResponse(BaseModel):
    """Service identity returned by GET /."""

    name: str = Field(..., description="Short service name.")
    status: str = Field(..., description="Process-level status.")
    message: str = Field(..., description="Human-readable service tagline.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "HeatSentinal",
                "status": "running",
                "message": "Heat Health Intelligence API",
            }
        }
    }


class HealthResponse(BaseModel):
    """Minimal liveness payload returned by GET /api/v1/health."""

    status: str = Field(..., description="'healthy' when the API is serving.")

    model_config = {"json_schema_extra": {"example": {"status": "healthy"}}}


class HealthDetailsResponse(BaseModel):
    """Richer health payload for dashboards and deployment checks."""

    status: str
    service: str
    version: str
    api_version: str
    debug: bool
    uptime_seconds: float

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "healthy",
                "service": "HeatSentinal",
                "version": "1.0.0",
                "api_version": "v1",
                "debug": True,
                "uptime_seconds": 12.4,
            }
        }
    }


class ErrorDetail(BaseModel):
    """Body of the standard error envelope."""

    type: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Envelope returned by every error handler."""

    error: ErrorDetail

    model_config = {
        "json_schema_extra": {
            "example": {
                "error": {
                    "type": "validation_error",
                    "message": "One or more request parameters are invalid.",
                    "details": {},
                }
            }
        }
    }
