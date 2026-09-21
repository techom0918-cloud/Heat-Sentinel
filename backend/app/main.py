"""HeatSentinal API application factory and entrypoint.

Run locally with:
    uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.models.common import RootResponse

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks.

    Later phases will warm the weather client and load the trained model here.
    """
    logger.info(
        "%s v%s starting (debug=%s)",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.DEBUG,
    )
    logger.info("Allowed CORS origins: %s", settings.cors_origins_list)
    yield
    logger.info("%s shutting down", settings.APP_NAME)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    application = FastAPI(
        title=settings.APP_TITLE,
        description=settings.APP_DESCRIPTION,
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(application)

    # Versioned business endpoints live under /api/v1.
    application.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @application.get(
        "/",
        response_model=RootResponse,
        tags=["Root"],
        summary="Service identity",
    )
    async def root() -> RootResponse:
        return RootResponse(
            name=settings.APP_NAME,
            status="running",
            message=settings.APP_MESSAGE,
        )

    return application


app = create_app()
