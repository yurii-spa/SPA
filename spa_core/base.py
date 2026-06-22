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

    def __init__(self, data_dir: str = "data", base_dir: Optional[str] = None):
        # ``base_dir`` is an alias accepted by subclasses that treat the arg as
        # "repo root" rather than "data directory"; it maps 1-to-1 to data_dir.
        # LLM FORBIDDEN — deterministic initialisation.
        resolved = base_dir if base_dir is not None else data_dir
        self._data_dir = Path(resolved)
        self._data_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _default_path(self, filename: Optional[str] = None) -> Path:
        fname = filename or f"{self.MODULE_NAME}.json"
        return self._data_dir / fname

    def _path(self, relative: str) -> str:
        """Resolve a repo-relative path against this instance's base/data dir.

        Subclasses that receive ``base_dir`` (e.g. alert classes) pass it as
        the first positional arg to ``super().__init__()``.  Those subclasses
        set ``self._data_dir = Path(base_dir)`` (their root), so joining a
        relative path like ``"data/foo.json"`` gives the correct absolute path.
        LLM FORBIDDEN — deterministic path resolution only.
        """
        import os
        return os.path.join(str(self._data_dir), relative)

    def save(self, data: Any = None, filename: Optional[str] = None) -> bool:
        """Save data as JSON. Returns True on success.

        Resolution order for the output path:
        1. ``filename`` kwarg (explicit override)
        2. ``self.OUTPUT_PATH`` if defined and contains ``/`` (repo-relative
           path — resolved via ``_path()`` so tests with ``base_dir=tmpdir``
           write to the correct temp location)
        3. ``_default_path()`` using ``MODULE_NAME`` (legacy fallback)

        If ``data`` is omitted, falls back to ``self._data``.
        LLM FORBIDDEN — deterministic persistence only.
        """
        import os
        if data is None:
            data = getattr(self, "_data", {})
        try:
            if filename is not None:
                path = self._default_path(filename)
                path.write_text(json.dumps(data, indent=2, default=str))
            else:
                output_path = getattr(self, "OUTPUT_PATH", None)
                if output_path and "/" in output_path:
                    resolved = self._path(output_path)
                    os.makedirs(os.path.dirname(resolved), exist_ok=True)
                    Path(resolved).write_text(json.dumps(data, indent=2, default=str))
                else:
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

    def analyze(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Run analysis and return a result dict.

        Default no-op implementation. This was historically an
        ``@abstractmethod``, but ~40 analytics subclasses never implemented it
        and were therefore impossible to instantiate (the resulting TypeError
        was swallowed inside ``cycle_runner``'s try/except — i.e. the modules
        were silently dead). Making it a concrete default restores
        instantiability; subclasses SHOULD still override ``analyze()`` with
        real logic. Returns ``{}`` by default (no recursion into ``to_dict``).
        """
        return {}

    def run_and_save(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Convenience: analyze + save result."""
        result = self.analyze(*args, **kwargs)
        self.save(result)
        return result


class BaseReport(ABC):
    """Abstract base for all SPA report generators.

    Subclasses may call ``super().__init__(base_dir)`` to store the repo root.
    LLM FORBIDDEN — deterministic base initialisation only.
    """

    def __init__(self, base_dir: str = ".") -> None:
        # Store repo root so subclasses can resolve data paths.
        # Normalise: empty string → current directory.
        self.base_dir: str = base_dir.rstrip("/") or "."

    def _path(self, relative: str) -> str:
        """Resolve a repo-relative path against ``self.base_dir``.

        Returns an absolute-ish path string suitable for ``open()`` /
        ``Path()``.  When ``base_dir`` is ``.`` (current directory), the
        relative path is returned as-is so existing tests that use cwd-based
        paths keep working.
        LLM FORBIDDEN — deterministic path resolution only.
        """
        import os
        if self.base_dir == ".":
            return relative
        return os.path.join(self.base_dir, relative)

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
