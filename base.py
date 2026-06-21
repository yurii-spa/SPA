"""
spa_core/base.py

Base classes for all SPA analytics and adapter modules.
Eliminates copy-pasted save()/load() across 80+ files.

Usage:
    from spa_core.base import BaseAnalytics, BaseAdapter

    class MyAnalytics(BaseAnalytics):
        OUTPUT_PATH = "data/my_output.json"

        def compute(self) -> dict:
            result = {"value": 42}
            self.save(result)
            return result

        def to_dict(self) -> dict:
            return self.load()
"""
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Optional

from spa_core.utils.atomic import atomic_load, atomic_save

logger = logging.getLogger(__name__)


class BaseAnalytics(ABC):
    """
    Base class for all analytics modules.
    Provides: save(), load(), _path(), _ensure_dir().
    Requires subclasses to implement: to_dict()
    """

    OUTPUT_PATH: str = ""  # Override in subclass

    def __init__(self, base_dir: str = "."):
        self.base_dir = base_dir

    def _path(self, relative: str) -> str:
        return os.path.join(self.base_dir, relative)

    def _ensure_dir(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def save(self, data: Any = None, path: str = None) -> str:
        """Atomic save. Uses OUTPUT_PATH if path not specified."""
        target = path or self._path(self.OUTPUT_PATH)
        if data is None:
            data = self.to_dict()
        atomic_save(data, target)
        return target

    def load(self, path: str = None) -> Any:
        """Loads from OUTPUT_PATH or given path."""
        target = path or self._path(self.OUTPUT_PATH)
        return atomic_load(target)

    @abstractmethod
    def to_dict(self) -> dict:
        """Returns current state as JSON-serializable dict."""
        ...


class BaseAdapter(ABC):
    """
    Base class for all DeFi protocol adapters.
    Ensures RESEARCH_ONLY flag and standard interface.
    """

    RESEARCH_ONLY: bool = True
    SOURCE_ID: str = ""
    FALLBACK_APY: float = 5.0
    CACHE_TTL: int = 300  # seconds

    def __init__(self):
        self._cache: Optional[dict] = None
        self._cache_time: float = 0.0

    def _cache_expired(self) -> bool:
        import time

        return (time.time() - self._cache_time) > self.CACHE_TTL

    @abstractmethod
    def current_apy(self) -> float:
        """Returns current APY. Uses FALLBACK_APY on error."""
        ...

    @abstractmethod
    def source_metadata(self) -> dict:
        """Returns source state info."""
        ...

    def is_research_only(self) -> bool:
        return self.RESEARCH_ONLY

    def safe_apy(self) -> float:
        """Returns current_apy() or FALLBACK_APY on any exception."""
        try:
            return self.current_apy()
        except Exception as e:
            logger.warning(f"{self.SOURCE_ID}: safe_apy fallback ({e})")
            return self.FALLBACK_APY


class BaseReport(BaseAnalytics):
    """
    Base class for reports (markdown + JSON output).
    """

    @abstractmethod
    def to_markdown(self) -> str:
        """Renders report as Markdown string."""
        ...

    def save_markdown(self, path: str = None) -> str:
        """Saves markdown to .md file atomically (tmp+os.replace)."""
        import os
        md = self.to_markdown()
        target = path or (self._path(self.OUTPUT_PATH).replace(".json", ".md"))
        self._ensure_dir(target)
        tmp = target + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(md)
            os.replace(tmp, target)
        finally:
            try:
                os.remove(tmp)
            except FileNotFoundError:
                pass
        return target
