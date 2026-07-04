"""
spa_core/academy/api/app.py

Academy FastAPI sub-application factory.

The Academy onboarding surface is a SEPARATE FastAPI app with its OWN CORS
policy and credentialed cookie handling, mounted by the main public API via
``app.mount("/academy", create_academy_app())`` (D4-approved). This keeps the
public :8765 API's permissive/no-credential CORS completely isolated from the
Academy's credentialed same-site cookie flow — a rogue origin can never ride the
academy session cookie.

create_academy_app(db_path=None) -> FastAPI
  - db_path overrides the SPA_ACADEMY_DB env var (tests inject a tmp-file DB).
  - The DB must already exist and be migrated: this factory NEVER creates or
    migrates a database — it fails fast with a clear error, so a stray process
    can't silently stand up an empty academy DB in the wrong place.
  - Wiring: CORS (outermost) → AcademyRateLimit → SeedPhraseGuard → routes.

DEV mode (SPA_ACADEMY_DEV=1 or ACADEMY_DEV=1) additionally allows the Astro dev
origin http://localhost:4321 and relaxes cookie Secure (handled in routes).

LLM FORBIDDEN in this module.
Academy stage 3.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from spa_core.academy.db import AcademyDB
from spa_core.academy.api.middleware import AcademyRateLimit, SeedPhraseGuard
from spa_core.academy.api.routes import auth as auth_routes
from spa_core.academy.api.routes import progress as progress_routes
from spa_core.academy.api.routes import notes as notes_routes
from spa_core.academy.api.routes import quiz as quiz_routes
from spa_core.academy.api.routes import wallet as wallet_routes
from spa_core.academy.api.routes import verify as verify_routes

# Production origin (the site). DEV additionally allows the Astro dev server.
_PROD_ORIGIN = "https://earn-defi.com"
_DEV_ORIGIN = "http://localhost:4321"


def _is_dev() -> bool:
    return (
        os.environ.get("SPA_ACADEMY_DEV", "").strip() == "1"
        or os.environ.get("ACADEMY_DEV", "").strip() == "1"
    )


def _allowed_origins() -> list:
    origins = [_PROD_ORIGIN]
    if _is_dev():
        origins.append(_DEV_ORIGIN)
    return origins


def _resolve_db_path(db_path: Optional[str]) -> str:
    resolved = db_path if db_path is not None else os.environ.get("SPA_ACADEMY_DB")
    if not resolved:
        raise RuntimeError(
            "Academy DB path is not configured: pass db_path= or set "
            "SPA_ACADEMY_DB. Refusing to guess a path."
        )
    return resolved


def _verify_db_ready(db_path: str) -> None:
    """Fail fast unless the DB file exists AND its migrations are applied.

    Never creates the file (a bare sqlite3.connect would): we check existence
    on disk first, then confirm at least migration 0001 is recorded.
    """
    if not os.path.exists(db_path):
        raise RuntimeError(
            f"Academy DB not found at {db_path!r}. Create and migrate it first: "
            "`python3 -m spa_core.academy.manage init-db` "
            "(with SPA_ACADEMY_DB set). The API never auto-creates it."
        )
    version = AcademyDB(db_path=db_path).schema_version()
    if version < 1:
        raise RuntimeError(
            f"Academy DB at {db_path!r} has no migrations applied "
            "(schema_version=0). Run `manage.py init-db` before serving."
        )


def create_academy_app(db_path: Optional[str] = None) -> FastAPI:
    """Build and return the Academy FastAPI sub-application."""
    resolved_db = _resolve_db_path(db_path)
    # Fail fast at construction so a broken DB surfaces immediately (and the
    # main server's mount try/except can degrade gracefully in production).
    _verify_db_ready(resolved_db)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Re-verify on serve start (covers a DB deleted between build & boot).
        _verify_db_ready(app.state.db_path)
        yield

    app = FastAPI(
        title="SPA Academy — Real-Money Onboarding",
        description="Invite-gated, non-custodial onboarding academy.",
        lifespan=lifespan,
        docs_url=None if not _is_dev() else "/docs",
        redoc_url=None,
    )
    app.state.db_path = resolved_db

    # ── Middleware (added inner→outer; last added is outermost) ──────────────
    #   outermost → innermost:  CORS → AcademyRateLimit → SeedPhraseGuard → app
    app.add_middleware(SeedPhraseGuard)
    app.add_middleware(AcademyRateLimit)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "service": "academy", "dev": _is_dev()}

    app.include_router(auth_routes.router)
    app.include_router(progress_routes.router)
    app.include_router(notes_routes.router)
    app.include_router(quiz_routes.router)
    app.include_router(wallet_routes.router)
    app.include_router(verify_routes.router)
    return app
