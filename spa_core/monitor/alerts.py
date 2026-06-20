"""
SPA Alert Engine — M3
Threshold-based alerts отдельно от Risk Policy.

Risk Policy = блокирует сделки (детерминированный код).
Alerts = информирует о состоянии рынка / аномалиях данных.

Alerts НЕ могут блокировать сделки — они только логируют и сохраняют risk_events.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

log = logging.getLogger(__name__)

# ─── Severity ─────────────────────────────────────────────────────────────────

Severity = Literal["INFO", "WARNING", "CRITICAL"]


@dataclass
class Alert:
    severity: Severity
    event_type: str
    protocol_key: str | None
    message: str
    details: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __str__(self) -> str:
        proto = f"[{self.protocol_key}] " if self.protocol_key else ""
        return f"[{self.severity}] {proto}{self.message}"


# ─── Alert Rules ──────────────────────────────────────────────────────────────

class AlertEngine:
    """
    Проверяет снапшоты APY/TVL и генерирует alerts при аномалиях.
    Отдельно от Risk Policy — не блокирует сделки.
    """

    # Пороги для alert-правил
    APY_DROP_THRESHOLD_PCT   = 20.0   # APY упал на >20% от предыдущего снапшота
    APY_SPIKE_THRESHOLD_PCT  = 50.0   # APY вырос на >50% — возможная аномалия
    TVL_DROP_THRESHOLD_PCT   = 30.0   # TVL упал на >30% — риск ликвидности
    STALE_DATA_HOURS         = 6.0    # данные старше 6 часов — pipeline мог упасть
    MIN_TVL_WARNING_USD      = 10_000_000  # TVL < $10M → предупреждение

    def check_snapshots(self, current: list[dict], previous: list[dict]) -> list[Alert]:
        """
        Сравнить текущие снапшоты с предыдущими.
        Вернуть список alerts.
        """
        alerts: list[Alert] = []

        # Индексируем предыдущие по protocol_key
        prev_index = {s["protocol_key"]: s for s in previous}

        for snap in current:
            key = snap["protocol_key"]
            prev = prev_index.get(key)

            # 1. Проверка свежести данных
            alerts.extend(self._check_staleness(snap))

            # 2. TVL слишком низкий
            alerts.extend(self._check_tvl_level(snap))

            if not prev:
                continue  # нет предыдущего снапшота для сравнения

            # 3. Резкое падение APY
            alerts.extend(self._check_apy_drop(snap, prev))

            # 4. Резкий рост APY (аномалия)
            alerts.extend(self._check_apy_spike(snap, prev))

            # 5. Резкое падение TVL
            alerts.extend(self._check_tvl_drop(snap, prev))

        return alerts

    def check_pipeline_health(self, snapshots: list[dict]) -> list[Alert]:
        """Проверить что данные вообще есть и свежие."""
        alerts: list[Alert] = []
        if not snapshots:
            alerts.append(Alert(
                severity="CRITICAL",
                event_type="NO_DATA",
                protocol_key=None,
                message="No snapshots in database — data pipeline may be down",
                details={"expected_protocols": 7},
            ))
        else:
            protocols_seen = {s["protocol_key"] for s in snapshots}
            expected = {
                "aave-v3-usdc-ethereum", "aave-v3-usdt-ethereum",
                "compound-v3-usdc-ethereum", "morpho-usdc-ethereum",
                "yearn-v3-usdc-ethereum", "maple-usdc-ethereum",
                "euler-v2-usdc-ethereum",
            }
            missing = expected - protocols_seen
            if missing:
                alerts.append(Alert(
                    severity="WARNING",
                    event_type="MISSING_PROTOCOL_DATA",
                    protocol_key=None,
                    message=f"Missing data for {len(missing)} protocol(s): {', '.join(sorted(missing))}",
                    details={"missing": list(missing)},
                ))
        return alerts

    # ── Private checkers ──────────────────────────────────────────────────────

    def _check_staleness(self, snap: dict) -> list[Alert]:
        alerts = []
        ts_str = snap.get("timestamp", "")
        if not ts_str:
            return alerts
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            if age_hours > self.STALE_DATA_HOURS:
                alerts.append(Alert(
                    severity="WARNING",
                    event_type="STALE_DATA",
                    protocol_key=snap["protocol_key"],
                    message=f"Data is {age_hours:.1f}h old (threshold: {self.STALE_DATA_HOURS}h)",
                    details={"age_hours": round(age_hours, 2), "timestamp": ts_str},
                ))
        except (ValueError, TypeError):
            pass
        return alerts

    def _check_tvl_level(self, snap: dict) -> list[Alert]:
        alerts = []
        tvl = snap.get("tvl_usd", 0) or 0
        if 0 < tvl < self.MIN_TVL_WARNING_USD:
            alerts.append(Alert(
                severity="WARNING",
                event_type="LOW_TVL",
                protocol_key=snap["protocol_key"],
                message=f"TVL ${tvl/1e6:.1f}M below warning threshold ${self.MIN_TVL_WARNING_USD/1e6:.0f}M",
                details={"tvl_usd": tvl, "threshold_usd": self.MIN_TVL_WARNING_USD},
            ))
        return alerts

    def _check_apy_drop(self, snap: dict, prev: dict) -> list[Alert]:
        alerts = []
        cur_apy  = snap.get("apy_total") or 0
        prev_apy = prev.get("apy_total") or 0
        if prev_apy <= 0:
            return alerts
        drop_pct = (prev_apy - cur_apy) / prev_apy * 100
        if drop_pct >= self.APY_DROP_THRESHOLD_PCT:
            severity = "CRITICAL" if drop_pct >= 50 else "WARNING"
            alerts.append(Alert(
                severity=severity,
                event_type="APY_DROP",
                protocol_key=snap["protocol_key"],
                message=f"APY dropped {drop_pct:.1f}%: {prev_apy:.2f}% → {cur_apy:.2f}%",
                details={"prev_apy": prev_apy, "cur_apy": cur_apy, "drop_pct": round(drop_pct, 2)},
            ))
        return alerts

    def _check_apy_spike(self, snap: dict, prev: dict) -> list[Alert]:
        alerts = []
        cur_apy  = snap.get("apy_total") or 0
        prev_apy = prev.get("apy_total") or 0
        if prev_apy <= 0:
            return alerts
        spike_pct = (cur_apy - prev_apy) / prev_apy * 100
        if spike_pct >= self.APY_SPIKE_THRESHOLD_PCT:
            alerts.append(Alert(
                severity="WARNING",
                event_type="APY_SPIKE",
                protocol_key=snap["protocol_key"],
                message=f"APY spiked {spike_pct:.1f}%: {prev_apy:.2f}% → {cur_apy:.2f}% (possible anomaly)",
                details={"prev_apy": prev_apy, "cur_apy": cur_apy, "spike_pct": round(spike_pct, 2)},
            ))
        return alerts

    def _check_tvl_drop(self, snap: dict, prev: dict) -> list[Alert]:
        alerts = []
        cur_tvl  = snap.get("tvl_usd") or 0
        prev_tvl = prev.get("tvl_usd") or 0
        if prev_tvl <= 0:
            return alerts
        drop_pct = (prev_tvl - cur_tvl) / prev_tvl * 100
        if drop_pct >= self.TVL_DROP_THRESHOLD_PCT:
            severity = "CRITICAL" if drop_pct >= 60 else "WARNING"
            alerts.append(Alert(
                severity=severity,
                event_type="TVL_DROP",
                protocol_key=snap["protocol_key"],
                message=f"TVL dropped {drop_pct:.1f}%: ${prev_tvl/1e6:.1f}M → ${cur_tvl/1e6:.1f}M",
                details={
                    "prev_tvl": prev_tvl, "cur_tvl": cur_tvl,
                    "drop_pct": round(drop_pct, 2),
                },
            ))
        return alerts
