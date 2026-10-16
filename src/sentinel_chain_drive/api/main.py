"""FastAPI application factory and lifecycle management."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sentinel_chain_drive.api.endpoints import health
from sentinel_chain_drive.api.v1.api import api_v1_router
from sentinel_chain_drive.core.config import Settings, get_settings
from sentinel_chain_drive.core.errors import register_exception_handlers
from sentinel_chain_drive.core.logging import setup_logging
from sentinel_chain_drive.core.middleware import (
    CorrelationIdMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from sentinel_chain_drive.db.session import close_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifecycle hooks for structured startup and graceful shutdown."""
    settings: Settings = app.state.settings
    setup_logging(log_level=settings.LOG_LEVEL, log_format=settings.LOG_FORMAT)
    logger.info(
        "Starting %s v%s in %s mode",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.ENVIRONMENT,
    )
    yield
    logger.info("Shutting down %s...", settings.APP_NAME)
    await close_db()
    logger.info("Shutdown completed successfully.")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Instantiate and configure the FastAPI application."""
    active_settings = settings or get_settings()

    app = FastAPI(
        title=active_settings.APP_NAME,
        version=active_settings.APP_VERSION,
        description=(
            "AI-Agent Authorization and Cross-Bank Fraud Intelligence Platform - Phase 1 Foundation"
        ),
        docs_url="/docs" if active_settings.ENVIRONMENT != "production" else None,
        redoc_url="/redoc" if active_settings.ENVIRONMENT != "production" else None,
        openapi_url="/openapi.json" if active_settings.ENVIRONMENT != "production" else None,
        lifespan=lifespan,
    )

    app.state.settings = active_settings

    # 1. Defensive HTTP Security Headers
    app.add_middleware(SecurityHeadersMiddleware)

    # 2. Enforce request size boundaries (DoS protection)
    app.add_middleware(
        RequestSizeLimitMiddleware,
        max_size_bytes=active_settings.MAX_REQUEST_SIZE_BYTES,
    )

    # 3. Request Correlation ID tracking
    app.add_middleware(CorrelationIdMiddleware)

    # 4. Conservative CORS (strict origin whitelist, no wildcards)
    if active_settings.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=active_settings.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "X-Correlation-ID", "Accept"],
            max_age=600,
        )

    # 5. Global Exception Handlers
    register_exception_handlers(app)

    # 6. Route Registration
    app.include_router(health.router)
    app.include_router(api_v1_router)

    return app


# Default ASGI application instance for production ASGI servers (uvicorn, gunicorn)
app = create_app()
