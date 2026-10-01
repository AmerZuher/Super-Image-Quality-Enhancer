"""Typed application errors, rendered as RFC 9457 problem+json.

Raise ``AppError`` (or a subclass) with a stable ``code`` and, where possible, a ``fix``
the UI can show as-is. Never return ad-hoc error dicts from endpoints.
"""

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from siqe.core.logging import get_logger

log = get_logger(__name__)

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    """An expected failure with a stable, documented code (for example ``image.too_large``)."""

    status: int = 400

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status: int | None = None,
        title: str | None = None,
        fix: str | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        if status is not None:
            self.status = status
        self.title = title or code.replace(".", " ").replace("_", " ").capitalize()
        self.fix = fix
        self.extra = extra

    def to_problem(self, instance: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": f"urn:siqe:error:{self.code}",
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "code": self.code,
        }
        if self.fix:
            body["fix"] = self.fix
        if instance:
            body["instance"] = instance
        body.update(self.extra)
        return body


class NotFoundError(AppError):
    status = 404


class ServiceUnavailableError(AppError):
    status = 503


def problem_response(error: AppError, request: Request) -> JSONResponse:
    return JSONResponse(error.to_problem(request.url.path), status_code=error.status, media_type=PROBLEM_JSON)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.status >= 500:
            log.warning("request.failed", code=exc.code, detail=exc.detail, path=request.url.path)
        return problem_response(exc, request)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        err = AppError(
            "request.invalid",
            "The request has missing or invalid fields.",
            status=422,
            title="Invalid request",
            errors=[{"loc": list(e.get("loc", ())), "msg": e.get("msg", "")} for e in exc.errors()],
        )
        return problem_response(err, request)

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
        code = "request.not_found" if exc.status_code == 404 else f"http.{exc.status_code}"
        err = AppError(code, str(exc.detail), status=exc.status_code)
        return problem_response(err, request)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("request.crashed", path=request.url.path)
        err = AppError(
            "internal.error",
            "Something went wrong on the server. The error has been logged.",
            status=500,
            title="Internal error",
            fix="Check the api container logs (docker compose logs api) and report it if it repeats.",
        )
        return problem_response(err, request)
