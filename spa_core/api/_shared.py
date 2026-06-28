"""
spa_core/api/_shared.py — shared state + helpers for the SPA API routers.

P3-7 router split: server.py was a ~2028-LOC monolith of 58 handlers, each
repeating "read data/*.json → graceful fallback → return verbatim". The handlers
now live in spa_core/api/routers/*.py (one APIRouter per tag group), and ALL the
cross-cutting state + helpers they share live HERE so there is exactly one copy.

CRITICAL behavior-preserving contracts (the API is the live public surface):

  • Data-dir indirection. Every handler reads the data dir at CALL time via
    `data_dir()`, which resolves `spa_core.api.server._DATA_DIR`. The whole API
    test suite redirects the data dir with `monkeypatch.setattr(server, "_DATA_DIR",
    tmp_path)`; routing the read through server keeps that hermetic redirection
    working unchanged. server.py still owns the canonical `_DATA_DIR` attribute.

  • read_state(filename, default) is the ONE shared graceful loader (the dedup of
    the repeated boilerplate). It is byte-identical to the old per-handler
    `_load_json`: missing/corrupt file → the default (or {}), never raises. Honesty
    `meta` envelopes are attached by the handlers AFTER the read, exactly as before.

  • The async live-read helpers, the event ring buffer, honesty-meta builders, and
    the no-cache headers are all moved verbatim so /api/live/*, SSE/WS, and the
    backtest-meta-labeled endpoints behave identically.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("spa.api")

_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent

# Canonical default data dir. server.py exposes the live `_DATA_DIR` attribute
# (initialised from this) which `data_dir()` resolves at call time so the test
# monkeypatch on server._DATA_DIR reaches every router handler.
DEFAULT_DATA_DIR = Path(os.environ.get("SPA_DATA_DIR", _PROJECT_ROOT / "data"))


def data_dir() -> Path:
    """Resolve the active data dir AT CALL TIME from server._DATA_DIR.

    The API test suite redirects the data dir via
    ``monkeypatch.setattr(server, "_DATA_DIR", tmp_path)``; resolving through the
    server module here keeps that hermetic redirection working for router handlers.
    Falls back to DEFAULT_DATA_DIR before server has finished importing.
    """
    try:
        from spa_core.api import server as _srv
        return _srv._DATA_DIR
    except Exception:  # noqa: BLE001 — during server import, before _DATA_DIR exists
        return DEFAULT_DATA_DIR


# ─── State loaders ────────────────────────────────────────────────────────────

def read_state(filename: str, default: Any = None) -> Any:
    """Load data/<filename> as JSON; return `default` if missing or corrupt.

    The single shared, graceful, fail-open state reader — byte-identical to the
    former per-handler `_load_json`: a missing file or a JSONDecodeError yields
    the supplied default (or {} when no default given), never an exception. The
    file contents are returned VERBATIM; honesty `meta` envelopes are attached by
    the calling handler afterwards, exactly as before the split.
    """
    path = data_dir() / filename
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.debug(f"Data file not found: {path} — returning default")
        return default if default is not None else {}
    except json.JSONDecodeError as e:
        log.warning(f"JSON decode error in {path}: {e}")
        return default if default is not None else {}


# Backward-compatible alias (server.py re-exports it as `_load_json`).
_load_json = read_state


# ─── JSON-safety guards (fail-CLOSED against NaN/inf in corrupt state) ──────────
#
# json.loads() ACCEPTS the bare tokens NaN/Infinity/-Infinity by default, but the FastAPI/
# Starlette response serializer rejects non-finite floats ("Out of range float values are not
# JSON compliant") → an uncaught 500. A corrupt log line / state file carrying such a token would
# therefore crash any endpoint that echoes the parsed payload. These two helpers keep the public
# proof surface fail-CLOSED: a non-finite number is never emitted, and finite payloads are
# byte-identical (the helpers are a no-op on clean data).

def _has_nonfinite(obj: Any) -> bool:
    """True if any float anywhere in `obj` is NaN/inf (recursive, stdlib-only)."""
    import math
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, float):
            if not math.isfinite(cur):
                return True
        elif isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, (list, tuple)):
            stack.extend(cur)
    return False


def scrub_nonfinite(obj: Any) -> Any:
    """Recursively replace every NaN/inf float with None; finite data passes through unchanged.

    Used where a state payload is echoed VERBATIM into a response (e.g. the decision log rows):
    a non-finite number is honestly nulled rather than crashing the serializer. PURE; a no-op on
    any payload that has no non-finite floats."""
    import math
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: scrub_nonfinite(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_nonfinite(v) for v in obj]
    return obj


def parse_log_line(line: str, corrupt_marker: Any = None) -> Any:
    """Parse one JSONL line, fail-CLOSED. Returns the parsed object, or `corrupt_marker` when the
    line is not valid JSON OR contains a non-finite (NaN/inf) number.

    Treating a NaN/inf-bearing row as CORRUPT is the honest outcome for a tamper-evident chain:
    the row could never have been hashed from finite inputs, so it must fail verification AND must
    never be echoed as a serializer-crashing non-finite. Behaviour-preserving for clean lines."""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return corrupt_marker
    if _has_nonfinite(obj):
        return corrupt_marker
    return obj


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Honesty meta (additive labeling) ─────────────────────────────────────────

_BACKTEST_DISCLAIMER = (
    "Backtest/paper research — advisory, not realized capital, not a track record"
)


def backtest_meta(basis: str, period: str, *, is_realized: bool = False) -> dict:
    """Standard additive meta block for endpoints serving backtest/simulated numbers."""
    return {
        "is_backtest": True,
        "is_realized": bool(is_realized),
        "basis": basis,
        "period": period,
        "disclaimer": _BACKTEST_DISCLAIMER,
    }


_SLEEVE_YIELD_BASIS = {
    "engine_b": "assumed",
    "engine_c": "assumed",
    "rwa_floor": "live_feed",
    "rwa_sleeve": "live_feed",
}
_SLEEVE_YIELD_BASIS_NOTE = {
    "engine_b": "ASSUMED: HY band-median proxy, not realized",
    "engine_c": "ASSUMED: LP fee-only, impermanent loss NOT modeled, not realized",
    "rwa_floor": "live tokenized-T-bill feed",
    "rwa_sleeve": "live tokenized-T-bill feed",
}


def sleeve_yield_basis(sid: str) -> str:
    """assumed | live_feed | realized — default 'realized' for live paper sleeves."""
    return _SLEEVE_YIELD_BASIS.get(sid, "realized")


# ─── PaperTrader (optional — graceful fallback) ───────────────────────────────

def get_live_portfolio() -> dict | None:
    """Try to read live portfolio directly from PaperTrader; None if unavailable."""
    try:
        from paper_trading.engine import PaperTrader
        from database.init_db import get_db_path, init_database
        db_path = get_db_path()
        init_database(db_path)
        trader = PaperTrader(db_path=db_path)
        return trader.get_status()
    except Exception as e:  # noqa: BLE001
        log.debug(f"PaperTrader unavailable: {e}")
        return None


# ─── Live-API async helpers (non-blocking reads) ──────────────────────────────

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}

LIVE_READ_TIMEOUT: float = 3.0  # seconds; 503 is returned if exceeded


def live_read(filename: str) -> Any:
    """Read+parse data/<filename>; raise on missing/corrupt so callers decide."""
    return json.loads((data_dir() / filename).read_text(encoding="utf-8"))


async def aio_read_json(path: Path, timeout: float = LIVE_READ_TIMEOUT) -> Any:
    """Async non-blocking JSON file read with a hard timeout (thread-pool I/O)."""
    text: str = await asyncio.wait_for(
        asyncio.to_thread(path.read_text, encoding="utf-8"),
        timeout=timeout,
    )
    return json.loads(text)


async def aio_exists(path: Path) -> bool:
    """Non-blocking path.exists() — runs in thread pool."""
    return await asyncio.to_thread(path.exists)


# ─── Event Queue (SSE ring buffer) ───────────────────────────────────────────

class EventQueue:
    """In-memory ring buffer (last N events) + async fan-out to SSE subscribers."""

    def __init__(self, maxsize: int = 50) -> None:
        self._history: deque = deque(maxlen=maxsize)
        self._subscribers: list[asyncio.Queue] = []

    async def push(self, event: dict[str, Any]) -> None:
        self._history.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow consumer — drop rather than block

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def history(self) -> list[dict]:
        return list(self._history)

    def clear(self) -> None:
        """Clear history and subscribers (used in tests)."""
        self._history.clear()
        self._subscribers.clear()


# The single shared event queue instance (server.py re-exports it as event_queue).
event_queue = EventQueue(maxsize=50)
