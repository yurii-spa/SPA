"""
spa_core/base.py
Base abstract classes for SPA analytics, reporting, and adapter modules.
All analytics classes should inherit from BaseAnalytics.
All report classes should inherit from BaseReport.
All protocol adapter classes should inherit from BaseAdapter.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional


class BaseAnalytics(ABC):
    """
    Abstract base for all SPA analytics modules.
    Provides standard save/load helpers and enforces analyze() contract.
    """

    MODULE_NAME: str = "base_analytics"
    VERSION: str = "1.0.0"

    def __init__(self, data_dir: str = "data"):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _default_path(self, filename: Optional[str] = None) -> Path:
        fname = filename or f"{self.MODULE_NAME}.json"
        return self._data_dir / fname

    def save(self, data: Any, filename: Optional[str] = None) -> bool:
        """Save data as JSON. Returns True on success."""
        try:
            path = self._default_path(filename)
            path.write_text(json.dumps(data, indent=2, default=str))
            return True
        except Exception:
            return False

    def load(self, filename: Optional[str] = None, default: Any = None) -> Any:
        """Load JSON data. Returns default on missing/corrupt file."""
        try:
            path = self._default_path(filename)
            if not path.exists():
                return default
            return json.loads(path.read_text())
        except Exception:
            return default

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------

    @abstractmethod
    def analyze(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Run analysis and return a result dict."""

    def run_and_save(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Convenience: analyze + save result."""
        result = self.analyze(*args, **kwargs)
        self.save(result)
        return result


class BaseReport(ABC):
    """Abstract base for all SPA report generators."""

    @abstractmethod
    def generate(self, *args: Any, **kwargs: Any) -> str:
        """Generate and return report as string."""


class BaseAdapter(ABC):
    """
    Abstract base for protocol yield adapters.
    Subclasses must define PROTOCOL and override fetch_apy().
    """

    PROTOCOL: str = "base"
    TIER: int = 3
    RESEARCH_ONLY: bool = True
    FALLBACK_APY: float = 0.04  # 4% conservative fallback

    def safe_apy(self) -> float:
        """Return APY safely — never raises, falls back to FALLBACK_APY."""
        try:
            result = self.fetch_apy()
            if result is None or not isinstance(result, (int, float)):
                return self.FALLBACK_APY
            return float(result)
        except Exception:
            return self.FALLBACK_APY

    def fetch_apy(self) -> Optional[float]:
        """Override to return live APY. May return None or raise on failure."""
        return self.FALLBACK_APY
