"""
One consistent error format for the whole API:

    {"error": {"code": "not_found", "message": "...", "details": [...]}}

Raw PostgreSQL errors are never sent to clients; technical detail goes to
the log only. Services raise the AppError subclasses below; anything the
database layer throws is translated here to a safe message.
"""
import logging
from typing import Any, List, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def error_body(code: str, message: str, details: Optional[List[Any]] = None) -> dict:
    body: dict = {"code": code, "message": message}
    if details:
        body["details"] = details
    return {"error": body}


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    default_message = "An unexpected error occurred."
    headers: Optional[dict] = None

    def __init__(self, message: Optional[str] = None, *, details: Optional[List[Any]] = None):
        self.message = message or self.default_message
        self.details = details
        super().__init__(self.message)


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"
    default_message = "Invalid request."


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    default_message = "Authentication required."
    headers = {"WWW-Authenticate": "Bearer"}


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    default_message = "You do not have permission to perform this action."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    default_message = "Resource not found."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    default_message = "The request conflicts with existing data."


_HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        return JSONResponse(
            error_body(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException):
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(error_body(code, message), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        # Only location + message: pydantic's "input" echo could contain secrets (passwords).
        details = [
            {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            error_body("validation_error", "Request validation failed.", details), status_code=422
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(request: Request, exc: IntegrityError):
        logger.warning("Database integrity error: %s", exc.orig)
        return JSONResponse(
            error_body("conflict", "The request conflicts with existing data."), status_code=409
        )

    @app.exception_handler(OperationalError)
    async def handle_operational_error(request: Request, exc: OperationalError):
        logger.error("Database operational error", exc_info=exc)
        return JSONResponse(
            error_body("database_unavailable", "The database is currently unavailable."), status_code=503
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_sqlalchemy_error(request: Request, exc: SQLAlchemyError):
        logger.error("Unexpected database error", exc_info=exc)
        return JSONResponse(
            error_body("internal_error", "An unexpected error occurred."), status_code=500
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(
            error_body("internal_error", "An unexpected error occurred."), status_code=500
        )
