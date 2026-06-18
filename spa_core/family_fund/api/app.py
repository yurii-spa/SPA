"""FastAPI app factory для Family Fund Investor Cabinet.

Запуск:
    python -m uvicorn spa_core.family_fund.api.app:app --port 8766
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .middleware import rate_limit_middleware, request_id_middleware
from .routes import auth, health, portfolio, yield_history

logger = logging.getLogger("family_fund.api")

ALLOWED_ORIGINS = [
    "https://earn-defi.com",
    "http://localhost:5173",
]


def _setup_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        request_id = getattr(request.state, "request_id", None)
        log_fn = logger.error if exc.status_code >= 500 else logger.warning
        log_fn(
            "HTTP %s on %s %s | request_id=%s",
            exc.status_code,
            request.method,
            request.url.path,  # без query params (могут содержать токены)
            request_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {"code": "http_error", "message": str(exc.detail)},
                "request_id": request_id,
            },
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        errors = []
        for err in exc.errors():
            field = ".".join(
                str(loc) for loc in err["loc"] if loc not in ("body", "query")
            )
            errors.append(
                {"code": "validation_error", "message": err["msg"], "field": field}
            )
        return JSONResponse(
            status_code=422,
            content={
                "error": {"code": "validation_error", "message": "Validation failed"},
                "errors": errors,
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.exception(
            "Unhandled exception on %s %s",
            request.method,
            request.url.path,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {"code": "internal_error", "message": "Internal server error"},
                "request_id": getattr(request.state, "request_id", None),
            },
        )


def create_app() -> FastAPI:
    is_prod = os.getenv("ENV") == "production"
    app = FastAPI(
        title="Family Fund API",
        version="1.0.0",
        docs_url=None if is_prod else "/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )

    # Порядок важен: rate-limit добавлен первым → выполняется ВНУТРИ request-id,
    # т.е. у 429-ответа уже есть request_id в state.
    app.middleware("http")(rate_limit_middleware)
    app.middleware("http")(request_id_middleware)

    _setup_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(portfolio.router)
    app.include_router(yield_history.router)

    return app


app = create_app()
