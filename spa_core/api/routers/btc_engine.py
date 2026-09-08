"""BTC Signal Engine read-API (/api/btc-engine/*) — owner decision 2026-09-08 (earn-defi D-52).

The BTC Signal Engine is a SEPARATE repository (~/Documents/earn-defi, paper track since 2026-09-02).
Its daily job writes a small set of JSON files (track / commitments / runway / shadow); this router
serves them so the static pages under earn-defi.com/btc-engine/ can render live numbers without a
daily site push. Contract, same as the rest of the live API: read-only, pass-through, never raise,
never fabricate — a missing or corrupt file degrades to an honest ``status`` field, not a number.
The origin label ("paper" / "shadow" / "backtest") comes from the data and is passed through
untouched (P6 of the engine's spec: types are never mixed in one series).

Source directory: env ``SPA_BTC_ENGINE_SITE_DIR`` (default ~/Documents/earn-defi/site). Only the
fixed file names below are served — no path parameters reach the filesystem.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time as _time
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from spa_core.api._shared import NO_CACHE_HEADERS, aio_exists, aio_read_json

log = logging.getLogger("spa.api")

router = APIRouter(tags=["btc-engine"])

#: Fixed catalogue: route name → file name. Anything else is 404 by FastAPI routing, never a read.
FILES = {
    "track": "track.json",
    "commitments": "commitments.json",
    "runway": "runway.json",
    "shadow": "shadow.json",
}
MAX_BYTES = 2_000_000  # a track of many years is well under this; refuse to ship anything larger


def site_dir() -> Path:
    return Path(os.environ.get("SPA_BTC_ENGINE_SITE_DIR") or (Path.home() / "Documents" / "earn-defi" / "site"))


def _unavailable(name: str, reason: str, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        {"status": "no_data", "file": name, "reason": reason, "ts": _time.time()},
        status_code=status_code, headers=NO_CACHE_HEADERS,
    )


async def _serve(name: str) -> JSONResponse:
    path = site_dir() / FILES[name]
    if not await aio_exists(path):
        return _unavailable(name, "file_missing")
    try:
        if path.stat().st_size > MAX_BYTES:
            return _unavailable(name, "file_too_large", 503)
        data = await aio_read_json(path)
    except asyncio.TimeoutError:
        return _unavailable(name, "read_timeout", 503)
    except Exception as exc:  # noqa: BLE001 — corrupt file must not become a 500
        log.warning("btc-engine %s unreadable: %s", name, exc)
        return _unavailable(name, "unreadable", 503)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    if isinstance(data, dict):
        data = dict(data)
        data.setdefault("_fetched_at", _time.time())
        data["_file_mtime"] = mtime
        return JSONResponse(data, headers=NO_CACHE_HEADERS)
    return JSONResponse({"data": data, "_fetched_at": _time.time(), "_file_mtime": mtime}, headers=NO_CACHE_HEADERS)


@router.get("/api/btc-engine")
async def btc_engine_index():
    """Catalogue + freshness of every file (no content) — the health line for the /btc-engine/ pages."""
    out = {}
    for name, fname in FILES.items():
        p = site_dir() / fname
        try:
            out[name] = {"present": p.exists(), "mtime": p.stat().st_mtime if p.exists() else None, "bytes": p.stat().st_size if p.exists() else 0}
        except OSError as exc:
            out[name] = {"present": False, "error": str(exc)}
    return JSONResponse({"files": out, "ts": _time.time(), "source": "earn-defi paper contour (separate repo)"}, headers=NO_CACHE_HEADERS)


@router.get("/api/btc-engine/track.json")
async def btc_engine_track():
    return await _serve("track")


@router.get("/api/btc-engine/commitments.json")
async def btc_engine_commitments():
    return await _serve("commitments")


@router.get("/api/btc-engine/runway.json")
async def btc_engine_runway():
    return await _serve("runway")


@router.get("/api/btc-engine/shadow.json")
async def btc_engine_shadow():
    return await _serve("shadow")
