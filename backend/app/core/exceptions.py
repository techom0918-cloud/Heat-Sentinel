"""Application exceptions and centralized error handling.

Every error leaving the API uses the same JSON envelope:

    {
        "error": {
            "type": "...",
            "message": "...",
            "details": {...}
        }
    }

so the React dashboard only ever has to parse one error shape.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)


class HeatSentinalError(Exception):
    """Base class for all expected, domain-level failures.

    Raise this (or a subclass) from services so routes never have to build
    error responses by hand.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_type: str = "heatsentinal_error"

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code


class ValidationError(HeatSentinalError):
    """Input failed a domain rule (e.g. latitude outside -90..90)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_type = "validation_error"


class ExternalServiceError(HeatSentinalError):
    """An upstream provider failed, timed out, or returned garbage."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_type = "external_service_error"


class AuthenticationError(HeatSentinalError):
    """Login credentials were wrong, or a session/reset token is invalid,
    missing, or expired (Phase 16)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    error_type = "authentication_error"


class ResourceNotFoundError(HeatSentinalError):
    """A requested record, zone, or dataset does not exist."""

    status_code = status.HTTP_404_NOT_FOUND
    error_type = "not_found"


def _error_response(
    status_code: int,
    error_type: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build the standard error envelope."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "type": error_type,
                "message": message,
                "details": details or {},
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all exception handlers to the FastAPI application."""

    @app.exception_handler(HeatSentinalError)
    async def handle_domain_error(
        request: Request, exc: HeatSentinalError
    ) -> JSONResponse:
        logger.warning("Domain error on %s: %s", request.url.path, exc.message)
        return _error_response(
            exc.status_code, exc.error_type, exc.message, exc.details
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "request_validation_error",
            "One or more request parameters are invalid.",
            {"errors": _serialize_validation_errors(exc)},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return _error_response(
            exc.status_code,
            "http_error",
            str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # Full traceback goes to the server log, never to the client.
        logger.exception("Unhandled error on %s", request.url.path)
        message = (
            f"{type(exc).__name__}: {exc}"
            if settings.DEBUG
            else "An unexpected internal error occurred."
        )
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_server_error",
            message,
        )


def _serialize_validation_errors(
    exc: RequestValidationError,
) -> list[dict[str, Any]]:
    """Flatten FastAPI validation errors into JSON-safe dictionaries."""
    serialized: list[dict[str, Any]] = []
    for error in exc.errors():
        serialized.append(
            {
                "field": ".".join(str(part) for part in error.get("loc", [])),
                "message": error.get("msg", ""),
                "type": error.get("type", ""),
            }
        )
    return serialized
