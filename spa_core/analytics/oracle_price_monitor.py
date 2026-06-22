"""
MP-667: OraclePriceMonitor
Monitor oracle price feeds for staleness and manipulation risk.
Advisory/read-only. Pure stdlib. Atomic JSON writes (os.replace).
"""
from dataclasses import dataclass
from typing import List
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/oracle_monitor_log.json")
MAX_ENTRIES = 100

# Staleness thresholds (seconds)
STALENESS_THRESHOLDS = {
    "FRESH":  3600,    # < 1 hour old
    "AGING":  14400,   # 1-4 hours old
    "STALE":  86400,   # 4-24 hours old
    # EXPIRED: >= 24 hours old
}

# Deviation thresholds vs reference price (as fraction)
DEVIATION_THRESHOLDS = {
    "NORMAL":     0.005,  # < 0.5% from reference
    "SUSPICIOUS": 0.02,   # 0.5-2% from reference
    "ALERT":      0.05,   # 2-5% from reference
    # MANIPULATION: >= 5% from reference
}


@dataclass
class OracleFeed:
    feed_id: str
    protocol: str           # e.g. "Chainlink", "Pyth", "Band"
    asset: str              # e.g. "ETH/USD"
    reported_price: float
    reference_price: float  # off-chain/CeFi reference price
    last_update_ts: float   # unix timestamp of last price update
    current_ts: float       # current time (injectable for testing)
    heartbeat_seconds: int  # expected update interval (e.g. 3600 for 1hr)


@dataclass
class OracleHealth:
    feed_id: str
    protocol: str
    asset: str
    reported_price: float
    reference_price: float
    age_seconds: float           # current_ts - last_update_ts
    staleness_status: str        # FRESH / AGING / STALE / EXPIRED
    price_deviation_pct: float   # abs deviation from reference in %
    deviation_status: str        # NORMAL / SUSPICIOUS / ALERT / MANIPULATION
    heartbeat_missed: bool       # age > 2x heartbeat
    overall_status: str          # HEALTHY / DEGRADED / FAILED
    advisory: str


class OraclePriceMonitor:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    def _age(self, feed: OracleFeed) -> float:
        return feed.current_ts - feed.last_update_ts

    def _staleness(self, age: float) -> str:
        if age < STALENESS_THRESHOLDS["FRESH"]:
            return "FRESH"
        if age < STALENESS_THRESHOLDS["AGING"]:
            return "AGING"
        if age < STALENESS_THRESHOLDS["STALE"]:
            return "STALE"
        return "EXPIRED"

    def _deviation_pct(self, reported: float, reference: float) -> float:
        if reference <= 0:
            return 0.0
        return round(abs(reported - reference) / reference * 100, 4)

    def _deviation_status(self, dev_pct: float) -> str:
        pct = dev_pct / 100  # convert back to fraction for threshold comparison
        if pct < DEVIATION_THRESHOLDS["NORMAL"]:
            return "NORMAL"
        if pct < DEVIATION_THRESHOLDS["SUSPICIOUS"]:
            return "SUSPICIOUS"
        if pct < DEVIATION_THRESHOLDS["ALERT"]:
            return "ALERT"
        return "MANIPULATION"

    def _heartbeat_missed(self, age: float, heartbeat: int) -> bool:
        return age > 2 * heartbeat

    def _overall_status(self, staleness: str, deviation: str) -> str:
        if staleness == "EXPIRED" or deviation == "MANIPULATION":
            return "FAILED"
        if staleness in ("STALE", "AGING") or deviation in ("ALERT", "SUSPICIOUS"):
            return "DEGRADED"
        return "HEALTHY"

    def _advisory(self, overall: str, staleness: str, deviation: str) -> str:
        if overall == "FAILED":
            return (
                f"⛔ FAILED oracle — {staleness} feed, {deviation} price."
                " Do not use for trades."
            )
        if overall == "DEGRADED":
            return (
                f"⚠️ DEGRADED oracle — {staleness} data, {deviation} deviation."
                " Cross-check before use."
            )
        return "✅ Oracle healthy — fresh price, normal deviation."

    def assess(self, feed: OracleFeed) -> OracleHealth:
        age = self._age(feed)
        staleness = self._staleness(age)
        dev_pct = self._deviation_pct(feed.reported_price, feed.reference_price)
        dev_status = self._deviation_status(dev_pct)
        overall = self._overall_status(staleness, dev_status)
        return OracleHealth(
            feed_id=feed.feed_id,
            protocol=feed.protocol,
            asset=feed.asset,
            reported_price=round(feed.reported_price, 6),
            reference_price=round(feed.reference_price, 6),
            age_seconds=round(age, 2),
            staleness_status=staleness,
            price_deviation_pct=dev_pct,
            deviation_status=dev_status,
            heartbeat_missed=self._heartbeat_missed(age, feed.heartbeat_seconds),
            overall_status=overall,
            advisory=self._advisory(overall, staleness, dev_status),
        )

    def assess_batch(self, feeds: List[OracleFeed]) -> List[OracleHealth]:
        return [self.assess(f) for f in feeds]

    def failed_oracles(self, results: List[OracleHealth]) -> List[OracleHealth]:
        return [r for r in results if r.overall_status == "FAILED"]

    def save_results(self, results: List[OracleHealth]) -> None:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        for r in results:
            existing.append({
                "timestamp": time.time(),
                "feed_id": r.feed_id,
                "age_seconds": r.age_seconds,
                "staleness_status": r.staleness_status,
                "deviation_status": r.deviation_status,
                "overall_status": r.overall_status,
            })
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []
