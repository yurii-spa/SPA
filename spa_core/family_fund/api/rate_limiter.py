"""In-memory TokenBucket rate limiter (без Redis).

Thread-safe через threading.Lock (CPU-only, без I/O — не блокирует event loop).
Per-key (IP) tracking. Сброс при рестарте процесса — приемлемо для одного
экземпляра на Mac Mini.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class TokenBucket:
    """capacity — burst; refill_rate токенов за refill_interval секунд."""

    capacity: int
    refill_rate: int
    refill_interval: float
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        self._tokens = float(self.capacity)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed >= self.refill_interval:
            cycles = int(elapsed // self.refill_interval)
            self._tokens = min(
                float(self.capacity), self._tokens + cycles * self.refill_rate
            )
            self._last_refill += cycles * self.refill_interval

    def allow(self, cost: int = 1) -> bool:
        with self._lock:
            self._refill()
            if self._tokens >= cost:
                self._tokens -= cost
                return True
            return False

    @property
    def remaining(self) -> int:
        with self._lock:
            self._refill()
            return int(self._tokens)

    @property
    def reset_after(self) -> float:
        """Секунд до следующего цикла пополнения."""
        with self._lock:
            return max(
                0.0, self._last_refill + self.refill_interval - time.monotonic()
            )


class RateLimiterStore:
    """Хранит per-key бакеты с одинаковыми параметрами."""

    def __init__(
        self, capacity: int, refill_rate: int, refill_interval: float = 1.0
    ) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.refill_interval = refill_interval
        self._buckets: dict[str, TokenBucket] = {}
        self._store_lock = threading.Lock()

    def get_bucket(self, key: str) -> TokenBucket:
        with self._store_lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(
                    capacity=self.capacity,
                    refill_rate=self.refill_rate,
                    refill_interval=self.refill_interval,
                )
                self._buckets[key] = bucket
            return bucket

    def allow(self, key: str, cost: int = 1) -> bool:
        return self.get_bucket(key).allow(cost)

    def cleanup(self) -> None:
        """Удаляет бакеты с полным запасом токенов (idle clients)."""
        with self._store_lock:
            full = [
                k for k, b in self._buckets.items() if b.remaining >= self.capacity
            ]
            for k in full:
                del self._buckets[k]

    def reset(self) -> None:
        """Полный сброс (для тестов)."""
        with self._store_lock:
            self._buckets.clear()
