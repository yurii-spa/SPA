"""
spa_core/utils/metrics.py
Lightweight metrics collector for SPA.
No external dependencies — stores in-memory and periodically flushes to JSON.
Tracks: counters, gauges, timers.
"""
import contextlib
import time
from typing import Dict, List, Optional

from spa_core.utils.atomic import atomic_save
from spa_core.utils import clock


class MetricsCollector:
    """Lightweight in-memory metrics collector (stdlib only)."""

    def __init__(self, base_dir: str = "."):
        self.base_dir = base_dir
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}
        self._timers: Dict[str, List[float]] = {}

    # ── counters ────────────────────────────────────────────────────────────

    def increment(self, name: str, n: int = 1, **tags) -> None:
        """Increments a counter by n (default 1)."""
        key = self._make_key(name, tags)
        self._counters[key] = self._counters.get(key, 0) + n

    def get_counter(self, name: str, **tags) -> int:
        """Returns current counter value (0 if not seen)."""
        return self._counters.get(self._make_key(name, tags), 0)

    # ── gauges ──────────────────────────────────────────────────────────────

    def set_gauge(self, name: str, value: float, **tags) -> None:
        """Sets a gauge to an absolute value."""
        key = self._make_key(name, tags)
        self._gauges[key] = value

    def get_gauge(self, name: str, **tags) -> Optional[float]:
        """Returns current gauge value (None if not seen)."""
        return self._gauges.get(self._make_key(name, tags))

    # ── timers ──────────────────────────────────────────────────────────────

    def record_time(self, name: str, duration_ms: float, **tags) -> None:
        """Records a timing observation in milliseconds."""
        key = self._make_key(name, tags)
        if key not in self._timers:
            self._timers[key] = []
        self._timers[key].append(duration_ms)
        # Ring-buffer: keep last 1000 samples
        if len(self._timers[key]) > 1000:
            self._timers[key] = self._timers[key][-1000:]

    @contextlib.contextmanager
    def timer(self, name: str, **tags):
        """Context manager that auto-records elapsed time in ms."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self.record_time(name, elapsed_ms, **tags)

    def get_timer_stats(self, name: str, **tags) -> Optional[dict]:
        """Returns {count, avg_ms, p95_ms} for a timer key, or None."""
        key = self._make_key(name, tags)
        samples = self._timers.get(key)
        if not samples:
            return None
        sorted_s = sorted(samples)
        p95_idx = int(len(sorted_s) * 0.95)
        return {
            "count": len(sorted_s),
            "avg_ms": sum(sorted_s) / len(sorted_s),
            "p95_ms": sorted_s[min(p95_idx, len(sorted_s) - 1)],
        }

    # ── flush ───────────────────────────────────────────────────────────────

    def flush(self, path: str = None) -> dict:
        """Serialises current metrics to a dict and optionally writes to JSON."""
        timer_summary = {}
        for k, v in self._timers.items():
            if not v:
                continue
            sorted_v = sorted(v)
            p95_idx = int(len(sorted_v) * 0.95)
            timer_summary[k] = {
                "count": len(sorted_v),
                "avg_ms": sum(sorted_v) / len(sorted_v),
                "p95_ms": sorted_v[min(p95_idx, len(sorted_v) - 1)],
            }

        data = {
            "timestamp": clock.utcnow().isoformat(),
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "timers": timer_summary,
        }

        flush_path = path or f"{self.base_dir}/data/metrics.json"
        try:
            atomic_save(data, flush_path)
        except Exception:
            pass  # flush is best-effort; never crash caller

        return data

    def reset(self) -> None:
        """Resets all in-memory metrics (useful for testing)."""
        self._counters.clear()
        self._gauges.clear()
        self._timers.clear()

    # ── internal ────────────────────────────────────────────────────────────

    @staticmethod
    def _make_key(name: str, tags: dict) -> str:
        if not tags:
            return name
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name}{{{tag_str}}}"


# ── module-level singleton ───────────────────────────────────────────────────

_global: Optional[MetricsCollector] = None


def get_metrics(base_dir: str = ".") -> MetricsCollector:
    """Returns the global MetricsCollector singleton (lazy init)."""
    global _global
    if _global is None:
        _global = MetricsCollector(base_dir)
    return _global


def reset_global() -> None:
    """Resets the global singleton (for test isolation)."""
    global _global
    _global = None
