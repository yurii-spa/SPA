"""
APY History Tracker

Appends each run's protocol APY data to a rolling JSON store.
Keeps 90 days of history. Used for trend analysis and go-live confidence.

MP-1406: Migrated to BaseAnalytics (Phase 1 — inheritance + to_dict only).
"""
import json, os, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from spa_core.base import BaseAnalytics

APY_HISTORY_FILE = "data/apy_history.json"
MAX_HISTORY_DAYS = 90

class APYTracker(BaseAnalytics):
    OUTPUT_PATH = "data/apy_history.json"

    def __init__(self, history_file: str = APY_HISTORY_FILE):
        super().__init__()  # sets self.base_dir = "."
        self.history_file = Path(history_file)
        self._data = self._load()

    def to_dict(self) -> dict:
        """Returns current in-memory APY history state."""
        return self._data

    def _load(self) -> dict:
        if self.history_file.exists():
            try:
                return json.loads(self.history_file.read_text())
            except (json.JSONDecodeError, OSError, ValueError):
                # Corrupt or unreadable history → start fresh (don't swallow
                # KeyboardInterrupt/SystemExit via a bare except).
                pass
        return {"protocol_history": {}, "last_updated": None}

    def record_snapshot(self, pools: list[dict], timestamp: str = None) -> None:
        """
        Record current APY for each pool. pools is a list of DeFiLlama pool dicts.
        Each dict must have: project, symbol, apy, tvlUsd.
        """
        ts = timestamp or datetime.now(timezone.utc).isoformat()

        for pool in pools:
            key = f"{pool.get('project', 'unknown')}:{pool.get('symbol', 'unknown')}"
            if key not in self._data["protocol_history"]:
                self._data["protocol_history"][key] = []

            self._data["protocol_history"][key].append({
                "ts": ts,
                "apy": round(pool.get("apy", 0), 4),
                "tvl": round(pool.get("tvlUsd", 0), 0),
            })

        self._data["last_updated"] = ts
        self._prune_old_entries()
        self._save()

    def _prune_old_entries(self) -> None:
        """Remove entries older than MAX_HISTORY_DAYS."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_HISTORY_DAYS)).isoformat()
        for key in self._data["protocol_history"]:
            self._data["protocol_history"][key] = [
                e for e in self._data["protocol_history"][key] if e["ts"] >= cutoff
            ]

    def _save(self) -> None:
        self.history_file.parent.mkdir(exist_ok=True)
        self.history_file.write_text(json.dumps(self._data, indent=2))

    def get_trend(self, protocol_key: str, days: int = 7) -> dict:
        """
        Calculate APY trend for a protocol over the last N days.
        Returns: {avg_apy, min_apy, max_apy, trend: "UP"|"DOWN"|"STABLE", change_7d_bps}
        """
        entries = self._data["protocol_history"].get(protocol_key, [])
        if not entries:
            return {"avg_apy": None, "trend": "UNKNOWN", "data_points": 0}

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        recent = [e for e in entries if e["ts"] >= cutoff]

        if len(recent) < 2:
            last_apy = recent[0]["apy"] if recent else entries[-1]["apy"]
            return {
                "avg_apy": last_apy,
                "latest_apy": last_apy,
                "trend": "UNKNOWN",
                "data_points": len(recent),
            }

        apys = [e["apy"] for e in recent]
        first, last = apys[0], apys[-1]
        change_bps = round((last - first) * 100, 1)  # basis points

        if change_bps > 10:
            trend = "UP"
        elif change_bps < -10:
            trend = "DOWN"
        else:
            trend = "STABLE"

        return {
            "avg_apy": round(sum(apys) / len(apys), 4),
            "min_apy": round(min(apys), 4),
            "max_apy": round(max(apys), 4),
            "latest_apy": last,
            "trend": trend,
            "change_7d_bps": change_bps,
            "data_points": len(recent),
        }

    def all_trends(self, days: int = 7) -> dict:
        """Return trends for all tracked protocols."""
        return {
            key: self.get_trend(key, days)
            for key in self._data["protocol_history"]
        }

    def weighted_portfolio_apy(self, positions: list[dict]) -> float:
        """
        Calculate portfolio's current weighted APY from latest recorded values.
        positions: list of {protocol, symbol, allocation_pct}
        """
        total_weight = 0
        weighted_sum = 0
        for pos in positions:
            key = f"{pos.get('protocol', '')}:{pos.get('symbol', '')}"
            trend = self.get_trend(key, days=1)
            if trend.get("latest_apy") is not None:
                w = pos.get("allocation_pct", 0)
                weighted_sum += trend["latest_apy"] * w
                total_weight += w
        if total_weight == 0:
            return 0.0
        return round(weighted_sum / total_weight, 4)


# ─── Protocol-context entrypoint (линия A1 время-рядов, 2026-08-05) ──────────

def analyze(context=None):
    """Контекст агрегатора → реальный ряд APY → собственный движок
    get_trend() (данные инжектируются в стор инстанса в его формате
    {"ts","apy"}; штатный apy_history.json пуст — трекер никогда не
    накапливал снапшоты). Окно 90 дней: в ряду есть честная дыра
    (historical_apy кончается 2026-06-20, живая точка — сегодня),
    7-дневное окно почти всегда содержало бы <2 точек.

    Fail-closed: <3 точек или trend=UNKNOWN → None.
    Полярность: DOWN → риск выше 50 (масштаб по |change_bps|), UP → ниже.
    Без записей: record_snapshot/_save не зовутся.
    """
    from spa_core.analytics import _protocol_facts as _pf
    from spa_core.analytics import _apy_series as _apy
    if not _pf.is_protocol_context(context):
        return None
    proto = _apy.canonical_protocol(context["protocol"])
    series = _apy.get_series(proto, min_days=3,
                             data_dir=context.get("data_dir"))
    if series is None:
        return None
    tracker = APYTracker()
    tracker._data = {
        "protocol_history": {
            proto: [{"ts": day + "T00:00:00+00:00", "apy": apy}
                    for day, apy in series]
        },
        "last_updated": None,
    }
    trend = tracker.get_trend(proto, days=90)
    if trend.get("trend") in (None, "UNKNOWN") or trend.get("data_points", 0) < 2:
        return None
    change_bps = float(trend.get("change_7d_bps", 0.0) or 0.0)
    direction = trend["trend"]
    if direction == "DOWN":
        risk = 55.0 + min(30.0, abs(change_bps) / 10.0)
    elif direction == "UP":
        risk = 45.0 - min(25.0, abs(change_bps) / 10.0)
    else:
        risk = 40.0
    return {
        "protocol": proto,
        "risk_score": round(max(0.0, min(100.0, risk)), 2),
        "trend": direction,
        "change_bps": change_bps,
        "avg_apy": trend.get("avg_apy"),
        "data_points": trend.get("data_points"),
        "series_last_date": series[-1][0],
        "source": _apy.SERIES_SOURCE,
    }
