"""
SPA API Client — MP-1528 (v11.44).

Used by dashboard and Telegram bot to fetch data from the REST API.
Falls back to direct file reads if API is unavailable, so the system
works identically whether uvicorn is running or not.

Usage:
    from spa_core.api.client import SPAApiClient
    c = SPAApiClient()
    status = c.get_status()        # dict: done_count, sprint, …
    golive = c.get_golive()        # dict: pass_count, ready, blockers, …
    adapters = c.get_adapters()    # list[dict]: name, tier, apy, …
    evidence = c.get_evidence()    # list[dict]: paper trading history

IMPORTANT: READ-ONLY. No write operations.
"""

from __future__ import annotations

import json
import logging
import sys
import urllib.request
from pathlib import Path
from typing import Any

log = logging.getLogger("spa.api.client")

# ── defaults ──────────────────────────────────────────────────────────────────
_DEFAULT_URL = "http://localhost:8765"
_DEFAULT_TIMEOUT = 2  # seconds — fast fail, fall back to file immediately
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class SPAApiClient:
    """
    Client for the SPA REST API with transparent file fallback.

    All public methods:
      - First attempt an HTTP GET to the running uvicorn server.
      - On any connection error / timeout → silently fall back to reading
        the corresponding JSON file from base_dir/data/.
      - Never raise; always return a safe dict or list.

    Parameters
    ----------
    base_url : str
        Base URL of the running API server (default: http://localhost:8765).
    base_dir : str | Path
        Project root directory used for file fallback (default: auto-detected).
    timeout : int
        HTTP request timeout in seconds (default: 2).
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_URL,
        base_dir: str | Path | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.base_dir = Path(base_dir) if base_dir else _PROJECT_ROOT
        self.timeout = timeout
        self._data_dir = self.base_dir / "data"

    # ── public API ────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """
        Sprint / KANBAN summary.
        HTTP → /api/v1/status  |  fallback → KANBAN.json
        """
        try:
            return self._http_get("/api/v1/status")
        except Exception as e:
            log.debug(f"get_status HTTP failed ({e}); using file fallback")
            return self._fallback_status()

    def get_golive(self) -> dict:
        """
        GoLive readiness report (26 criteria).
        HTTP → /api/v1/golive  |  fallback → data/golive_status.json
        """
        try:
            return self._http_get("/api/v1/golive")
        except Exception as e:
            log.debug(f"get_golive HTTP failed ({e}); using file fallback")
            return self._fallback_golive()

    def get_adapters(self) -> list[dict]:
        """
        Adapter registry with live APY.
        HTTP → /api/v1/adapters  |  fallback → ADAPTER_REGISTRY introspection
        """
        try:
            result = self._http_get("/api/v1/adapters")
            return result.get("adapters", [])
        except Exception as e:
            log.debug(f"get_adapters HTTP failed ({e}); using file fallback")
            return self._fallback_adapters()

    def get_evidence(self) -> list[dict]:
        """
        Paper trading evidence history.
        HTTP → /api/v1/evidence  |  fallback → data/paper_evidence_history.json
        """
        try:
            result = self._http_get("/api/v1/evidence")
            return result.get("data", [])
        except Exception as e:
            log.debug(f"get_evidence HTTP failed ({e}); using file fallback")
            return self._fallback_evidence()

    def is_api_available(self) -> bool:
        """
        Quick liveness check — returns True if /health responds with 200.
        Useful for dashboards to decide which data-fetch mode to use.
        """
        try:
            resp = self._http_get("/health")
            return resp.get("status") == "ok"
        except Exception:
            return False

    # ── HTTP transport ────────────────────────────────────────────────────────

    def _http_get(self, path: str) -> dict:
        """
        Make a GET request; decode JSON; raise on any error.
        Uses only stdlib urllib — no third-party dependencies.
        """
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read()
            return json.loads(raw)

    # ── file fallbacks ────────────────────────────────────────────────────────

    def _read_json(self, filename: str, default: Any = None) -> Any:
        """Read a JSON file from data_dir; return default on any error."""
        path = self._data_dir / filename
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default if default is not None else {}

    def _fallback_status(self) -> dict:
        """File fallback for get_status() — reads KANBAN.json."""
        try:
            kanban_path = self.base_dir / "KANBAN.json"
            k = json.loads(kanban_path.read_text(encoding="utf-8"))
            return {
                "done_count": k.get("done_count", 0),
                "sprint": k.get("sprint_completed", "unknown"),
                "version": k.get("version", "unknown"),
                "source": "file",
            }
        except Exception as e:
            log.warning(f"_fallback_status failed: {e}")
            return {"done_count": 0, "sprint": "unknown", "source": "error"}

    def _fallback_golive(self) -> dict:
        """File fallback for get_golive() — reads data/golive_status.json."""
        data = self._read_json("golive_status.json", None)
        if data is not None:
            data["source"] = "file"
            return data

        # Last resort: run GoLiveReadinessReport inline
        try:
            if str(self.base_dir) not in sys.path:
                sys.path.insert(0, str(self.base_dir))
            from spa_core.analytics.golive_readiness_report import GoLiveReadinessReport
            report = GoLiveReadinessReport(base_dir=str(self.base_dir))
            result = report.generate_report()
            result["source"] = "inline"
            return result
        except Exception as e:
            log.warning(f"_fallback_golive inline failed: {e}")
            return {"pass_count": 0, "total": 26, "ready": False, "source": "error"}

    def _fallback_adapters(self) -> list[dict]:
        """
        File fallback for get_adapters().
        Tries ADAPTER_REGISTRY introspection; falls back to adapter_status.json.
        """
        try:
            if str(self.base_dir) not in sys.path:
                sys.path.insert(0, str(self.base_dir))
            from spa_core.adapters.adapter_registry import REGISTRY
            result = []
            for name, cls in REGISTRY.items():
                row: dict = {"name": name}
                try:
                    inst = cls()
                    row["tier"] = getattr(inst, "TIER", getattr(cls, "TIER", "?"))
                    row["apy"] = inst.safe_apy() if hasattr(inst, "safe_apy") else None
                    row["research_only"] = getattr(inst, "RESEARCH_ONLY", False)
                except Exception:
                    row["tier"] = getattr(cls, "TIER", "?")
                    row["apy"] = None
                result.append(row)
            return result
        except Exception as e:
            log.warning(f"_fallback_adapters registry failed: {e}")

        # Last resort: adapter_status.json
        data = self._read_json("adapter_status.json", None)
        if isinstance(data, list):
            return data
        return []

    def _fallback_evidence(self) -> list[dict]:
        """File fallback for get_evidence() — reads paper_evidence_history.json."""
        data = self._read_json("paper_evidence_history.json", None)
        if isinstance(data, list):
            return data
        # Try equity curve as secondary fallback
        equity = self._read_json("equity_curve_daily.json", None)
        if isinstance(equity, list):
            return equity
        return []
