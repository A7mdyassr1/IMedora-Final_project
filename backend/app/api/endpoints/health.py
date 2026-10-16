import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.health import DatabaseHealthResponse, HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
def health() -> HealthResponse:
    """The API process is up. Does not touch the database."""
    return HealthResponse(status="ok")


@router.get(
    "/health/db",
    response_model=DatabaseHealthResponse,
    responses={503: {"model": DatabaseHealthResponse, "description": "PostgreSQL is unreachable"}},
    summary="Database connectivity check",
)
def database_health(db: Session = Depends(get_db)):
    """Verifies the backend can run a query against PostgreSQL."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.error("Database health check failed", exc_info=True)
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": "unreachable"})
    return DatabaseHealthResponse(status="ok", database="up")
