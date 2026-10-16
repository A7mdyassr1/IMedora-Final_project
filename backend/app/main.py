"""
IMedora Backend - application entry point.

Run from the backend/ directory:
    uvicorn app.main:app --reload
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.api.endpoints import health
from app.api.router import api_v1_router
from app.core.config import get_settings
from app.core.database import check_database_connection, dispose_engine, safe_database_url
from app.core.exceptions import register_exception_handlers
from app.core.logging_config import setup_logging

logger = logging.getLogger("imedora")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting %s v%s (env=%s)", settings.app_name, settings.app_version, settings.app_env)
    # Deliberately non-fatal: the API still boots so /health/db can report the
    # problem, instead of the process crash-looping while the DB restarts.
    try:
        check_database_connection()
        logger.info("Database connection OK (%s)", safe_database_url())
    except SQLAlchemyError:
        logger.error("Database is unreachable at startup - /health/db will report it", exc_info=True)
    yield
    dispose_engine()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="REST API for IMedora - medical device management for hospitals.",
        lifespan=lifespan,
    )

    origins = settings.cors_origins_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        # Browsers reject credentials combined with a wildcard origin.
        allow_credentials="*" not in origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
