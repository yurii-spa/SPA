"""
MP-791: DeFiSentimentTracker
Tracks market sentiment signals from on-chain proxy data.

CLI:
    python3 -m spa_core.analytics.defi_sentiment_tracker --check
    python3 -m spa_core.analytics.defi_sentiment_tracker --run
"""

from __future__ import annotations

import json
import os
import time

from spa_core.utils.atomic import atomic_save
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_PATH_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "defi_sentiment_log.json"
)
LOG_CAP = 100

# Signal classification thresholds
TVL_BULLISH_THRESHOLD = 5.0          # % change
TVL_BEARISH_THRESHOLD = -5.0

NEW_WALLET_BULLISH_RATIO = 1.20      # vs 4-week avg
NEW_WALLET_BEARISH_RATIO = 0.80

WD_RATIO_BULLISH = 0.8               # withdraw/deposit — low = more deposits
WD_RATIO_BEARISH = 1.2

LARGE_EXIT_BULLISH_MAX = 3           # count of >$100K exits
LARGE_EXIT_BEARISH_MIN = 10

# Composite score thresholds
VERY_BULLISH_THRESHOLD = 4
BULLISH_THRESHOLD = 1
BEARISH_THRESHOLD = -1
VERY_BEARISH_THRESHOLD = -4


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SignalLabel(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SentimentLabel(str, Enum):
    VERY_BULLISH = "VERY_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    VERY_BEARISH = "VERY_BEARISH"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SignalBreakdown:
    tvl_change_7d_pct: float
    tvl_signal: str                    # bullish / bearish / neutral

    new_wallet_count_7d: Optional[float]
    new_wallet_4w_avg: Optional[float]
    new_wallet_signal: str

    withdraw_to_deposit_ratio: float
    wd_ratio_signal: str

    large_exit_count_7d: int
    large_exit_signal: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SentimentResult:
    timestamp: float
    protocol: str
    composite_sentiment_score: int     # range: -8 to +8
    sentiment: str                     # VERY_BULLISH .. VERY_BEARISH
    bullish_count: int
    bearish_count: int
    neutral_count: int
    signal_breakdown: dict

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Core tracker
# ---------------------------------------------------------------------------

class DeFiSentimentTracker:
    """
    Classifies per-signal sentiment from on-chain proxy data and produces
    a composite sentiment score.

    Scoring:
        bullish_count * 2 - bearish_count * 2 + neutral_count * 0
        Range: -8 (4 bearish) to +8 (4 bullish)
    """

    def __init__(self, log_path: str = LOG_PATH_DEFAULT):
        self._log_path = log_path
        self._last_result: Optional[SentimentResult] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def track(self, market_data: dict) -> SentimentResult:
        """
        market_data keys:
            protocol: str
            signals:
                tvl_change_7d_pct: float
                new_wallet_count_7d: float          (actual count this week)
                new_wallet_4w_avg: float            (4-week average; optional)
                withdraw_to_deposit_ratio: float
                large_exit_count_7d: int            (exits > $100K)
        """
        protocol: str = str(market_data.get("protocol", "unknown"))
        signals: dict = market_data.get("signals", {})

        tvl_change = float(signals.get("tvl_change_7d_pct", 0.0))
        new_wallets = signals.get("new_wallet_count_7d")
        nw_avg = signals.get("new_wallet_4w_avg")
        wd_ratio = float(signals.get("withdraw_to_deposit_ratio", 1.0))
        large_exits = int(signals.get("large_exit_count_7d", 0))

        # Classify each signal
        tvl_signal = self._classify_tvl(tvl_change)
        nw_signal = self._classify_new_wallets(new_wallets, nw_avg)
        wd_signal = self._classify_wd_ratio(wd_ratio)
        exit_signal = self._classify_large_exits(large_exits)

        all_signals = [tvl_signal, nw_signal, wd_signal, exit_signal]
        bullish_count = sum(1 for s in all_signals if s == SignalLabel.BULLISH)
        bearish_count = sum(1 for s in all_signals if s == SignalLabel.BEARISH)
        neutral_count = sum(1 for s in all_signals if s == SignalLabel.NEUTRAL)

        composite = bullish_count * 2 - bearish_count * 2
        sentiment = self._classify_composite(composite)

        breakdown = SignalBreakdown(
            tvl_change_7d_pct=tvl_change,
            tvl_signal=tvl_signal.value,
            new_wallet_count_7d=float(new_wallets) if new_wallets is not None else None,
            new_wallet_4w_avg=float(nw_avg) if nw_avg is not None else None,
            new_wallet_signal=nw_signal.value,
            withdraw_to_deposit_ratio=wd_ratio,
            wd_ratio_signal=wd_signal.value,
            large_exit_count_7d=large_exits,
            large_exit_signal=exit_signal.value,
        )

        result = SentimentResult(
            timestamp=time.time(),
            protocol=protocol,
            composite_sentiment_score=composite,
            sentiment=sentiment.value,
            bullish_count=bullish_count,
            bearish_count=bearish_count,
            neutral_count=neutral_count,
            signal_breakdown=breakdown.to_dict(),
        )
        self._last_result = result
        return result

    def get_sentiment(self) -> Optional[str]:
        """Return sentiment label from most recent call, or None."""
        if self._last_result is None:
            return None
        return self._last_result.sentiment

    def get_signal_breakdown(self) -> Optional[dict]:
        """Return signal breakdown dict from most recent call, or None."""
        if self._last_result is None:
            return None
        return self._last_result.signal_breakdown

    # ------------------------------------------------------------------
    # Log persistence
    # ------------------------------------------------------------------

    def append_log(self, result: SentimentResult, log_path: Optional[str] = None) -> None:
        """Atomically append result to ring-buffer log (max LOG_CAP entries)."""
        path = log_path or self._log_path
        self._ensure_dir(path)
        entries = self._read_log(path)
        entries.append(result.to_dict())
        if len(entries) > LOG_CAP:
            entries = entries[-LOG_CAP:]
        self._write_log(path, entries)

    # ------------------------------------------------------------------
    # Signal classifiers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_tvl(tvl_change_pct: float) -> SignalLabel:
        if tvl_change_pct > TVL_BULLISH_THRESHOLD:
            return SignalLabel.BULLISH
        elif tvl_change_pct < TVL_BEARISH_THRESHOLD:
            return SignalLabel.BEARISH
        return SignalLabel.NEUTRAL

    @staticmethod
    def _classify_new_wallets(
        count: Optional[float],
        avg_4w: Optional[float],
    ) -> SignalLabel:
        if count is None or avg_4w is None or avg_4w == 0:
            return SignalLabel.NEUTRAL
        ratio = count / avg_4w
        if ratio > NEW_WALLET_BULLISH_RATIO:
            return SignalLabel.BULLISH
        elif ratio < NEW_WALLET_BEARISH_RATIO:
            return SignalLabel.BEARISH
        return SignalLabel.NEUTRAL

    @staticmethod
    def _classify_wd_ratio(wd_ratio: float) -> SignalLabel:
        if wd_ratio < WD_RATIO_BULLISH:
            return SignalLabel.BULLISH
        elif wd_ratio > WD_RATIO_BEARISH:
            return SignalLabel.BEARISH
        return SignalLabel.NEUTRAL

    @staticmethod
    def _classify_large_exits(count: int) -> SignalLabel:
        if count <= LARGE_EXIT_BULLISH_MAX:
            return SignalLabel.BULLISH
        elif count >= LARGE_EXIT_BEARISH_MIN:
            return SignalLabel.BEARISH
        return SignalLabel.NEUTRAL

    @staticmethod
    def _classify_composite(score: int) -> SentimentLabel:
        if score > VERY_BULLISH_THRESHOLD:
            return SentimentLabel.VERY_BULLISH
        elif score > BULLISH_THRESHOLD:
            return SentimentLabel.BULLISH
        elif score >= BEARISH_THRESHOLD:
            return SentimentLabel.NEUTRAL
        elif score > VERY_BEARISH_THRESHOLD:
            return SentimentLabel.BEARISH
        else:
            return SentimentLabel.VERY_BEARISH

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_log(path: str) -> list:
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return []

    @staticmethod
    def _write_log(path: str, entries: list) -> None:
        dir_ = os.path.dirname(path) or "."
        os.makedirs(dir_, exist_ok=True)
        atomic_save(entries, str(path))

    @staticmethod
    def _ensure_dir(path: str) -> None:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _make_demo_data() -> dict:
    return {
        "protocol": "Aave V3",
        "signals": {
            "tvl_change_7d_pct": 7.2,
            "new_wallet_count_7d": 1500,
            "new_wallet_4w_avg": 1100,
            "withdraw_to_deposit_ratio": 0.65,
            "large_exit_count_7d": 2,
        },
    }


def main(args=None):
    import argparse
    parser = argparse.ArgumentParser(description="MP-791 DeFiSentimentTracker")
    parser.add_argument("--check", action="store_true", help="Compute and print, no write")
    parser.add_argument("--run", action="store_true", help="Compute and write log")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    parsed = parser.parse_args(args)

    log_path = LOG_PATH_DEFAULT
    if parsed.data_dir:
        log_path = os.path.join(parsed.data_dir, "defi_sentiment_log.json")

    tracker = DeFiSentimentTracker(log_path=log_path)
    demo = _make_demo_data()
    result = tracker.track(demo)

    print("=== DeFiSentimentTracker (MP-791) ===")
    print(f"  protocol                  : {result.protocol}")
    print(f"  composite_sentiment_score : {result.composite_sentiment_score}")
    print(f"  sentiment                 : {result.sentiment}")
    print(f"  bullish_count             : {result.bullish_count}")
    print(f"  bearish_count             : {result.bearish_count}")
    print(f"  neutral_count             : {result.neutral_count}")
    print("  signal_breakdown:")
    for k, v in result.signal_breakdown.items():
        print(f"    {k}: {v}")

    if parsed.run:
        tracker.append_log(result, log_path)
        print(f"\n✅ Appended to {log_path}")
    else:
        print("\n(dry-run — use --run to persist)")


if __name__ == "__main__":
    main()
