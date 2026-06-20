# DEPRECATED — orphaned module. Canonical: spa_core.scheduler.adapter_watchdog
# No active imports point here. TODO: remove in next cleanup.
# This file is kept for git history only.
raise ImportError(
    "DEPRECATED: use spa_core.scheduler.adapter_watchdog instead"
)

"""
adapter_watchdog.py — MP-596 AdapterWatchdog.

Мониторинг здоровья адаптеров: сравнивает текущий snapshot с предыдущим,
создаёт AlertDispatcher алерты при деградации APY / peg / risk_score.

Интегрируется с AlertDispatcher (если доступен), иначе только лог.

Атомарные записи: tmp-file + os.replace. Только stdlib.
Никогда не поднимает исключений наружу (fail-safe).

NOT imported from: risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).
"""
# from __future__ import annotations  # MP-1233: neutralized — unreachable below DEPRECATED raise, broke py_compile

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.monitoring.adapter_watchdog")

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_ADAPTER_STATUS_FILENAME = "adapter_status.json"
_WATCHDOG_HISTORY_FILENAME = "watchdog_history.json"

# Ring-buffer: 48 snapshots = 2 дня при hourly запуске
RING_BUFFER_MAX = 48

# Tier → default risk_score
_TIER_DEFAULT_RISK: Dict[str, float] = {
    "T1": 0.20,
    "T2": 0.35,
    "T3": 0.55,
    "T3-SPEC": 0.65,
    "T2-conditional": 0.40,
}


# ===========================================================================
# Dataclasses
# ===========================================================================

@dataclass
class AdapterHealth:
    """Агрегированное состояние одного адаптера за один snapshot."""
    adapter_id: str
    chain: str
    tier: str
    apy_pct: float
    risk_score: float
    peg_price: float         # usdc_price или 1.0 fallback
    is_healthy: bool         # apy > 0 AND peg within tolerance
    apy_change_pct: float    # diff vs предыдущий snapshot (0.0 если нет истории)
    alert_level: str         # "OK" / "WARNING" / "CRITICAL"

    def to_dict(self) -> dict:
        return {
            "adapter_id": self.adapter_id,
            "chain": self.chain,
            "tier": self.tier,
            "apy_pct": self.apy_pct,
            "risk_score": self.risk_score,
            "peg_price": self.peg_price,
            "is_healthy": self.is_healthy,
            "apy_change_pct": self.apy_change_pct,
            "alert_level": self.alert_level,
        }


@dataclass
class WatchdogReport:
    """Сводный отчёт одного прохода watchdog."""
    generated_at: str
    total_adapters: int
    healthy: int
    warning: int
    critical: int
    alerts_created: int
    adapter_statuses: List[AdapterHealth] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "total_adapters": self.total_adapters,
            "healthy": self.healthy,
            "warning": self.warning,
            "critical": self.critical,
            "alerts_created": self.alerts_created,
            "summary": self.summary,
            "adapter_statuses": [s.to_dict() for s in self.adapter_statuses],
        }


# ===========================================================================
# Atomic write helper
# ===========================================================================

def _atomic_write_json(path: Path, payload: object) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(payload, str(path))
class AdapterWatchdog:
    """
    Watchdog мониторинга здоровья адаптеров.

    Читает ``data/adapter_status.json``, сравнивает с предыдущим snapshot'ом
    из ``data/watchdog_history.json``, классифицирует каждый адаптер
    (OK / WARNING / CRITICAL) и создаёт Alert'ы через AlertDispatcher.

    Параметры
    ----------
    data_path : str | None
        Путь к директории с adapter_status.json. По умолчанию — data/.
    use_alert_dispatcher : bool
        Если True — пытается импортировать AlertDispatcher для создания Alert'ов.
        При недоступности автоматически откатывается в log-only режим.
    """

    # Пороги алертов
    APY_DROP_WARNING_PCT = 1.0    # APY снизился на ≥1% vs предыдущий snapshot → WARNING
    APY_DROP_CRITICAL_PCT = 2.0   # APY снизился на ≥2% → CRITICAL
    APY_FLOOR_PCT = 0.5           # APY ниже 0.5% → CRITICAL
    PEG_TOLERANCE = 0.005         # |usdc_price - 1.0| > 0.5% → WARNING
    PEG_CRITICAL = 0.02           # |usdc_price - 1.0| > 2% → CRITICAL
    RISK_SCORE_CEILING = 0.9      # risk_score > 0.9 → WARNING

    def __init__(
        self,
        data_path: Optional[str] = None,
        use_alert_dispatcher: bool = True,
    ) -> None:
        if data_path is None:
            self._data_dir = _DEFAULT_DATA_DIR
        else:
            self._data_dir = Path(data_path)
        self._adapter_status_path = self._data_dir / _ADAPTER_STATUS_FILENAME
        self._history_path = self._data_dir / _WATCHDOG_HISTORY_FILENAME
        self._use_alert_dispatcher = use_alert_dispatcher
        self._dispatcher = None  # lazily resolved

    # ------------------------------------------------------------------
    # AlertDispatcher lazy-init
    # ------------------------------------------------------------------

    def _get_dispatcher(self):
        """Возвращает AlertDispatcher или None (если недоступен / отключён)."""
        if not self._use_alert_dispatcher:
            return None
        if self._dispatcher is not None:
            return self._dispatcher
        try:
            from spa_core.alerts.alert_dispatcher import AlertDispatcher
            self._dispatcher = AlertDispatcher()
        except Exception as exc:  # noqa: BLE001
            log.debug("AlertDispatcher unavailable, log-only mode: %s", exc)
            self._dispatcher = None
        return self._dispatcher

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_current_status(self) -> dict:
        """
        Читает adapter_status.json.

        Возвращает {} при любой ошибке (fail-safe).
        """
        try:
            with open(self._adapter_status_path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception as exc:  # noqa: BLE001
            log.debug("load_current_status error: %s", exc)
            return {}

    def load_previous_snapshot(self) -> dict:
        """
        Читает последний snapshot из watchdog_history.json.

        Возвращает {} если файла нет или при любой ошибке (fail-safe).
        Формат истории: {"snapshots": [...], "latest": {...}}
        """
        try:
            if not self._history_path.exists():
                return {}
            with open(self._history_path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return {}
            latest = data.get("latest")
            if isinstance(latest, dict):
                return latest
            # Fallback: last entry of snapshots ring-buffer
            snapshots = data.get("snapshots", [])
            if isinstance(snapshots, list) and snapshots:
                last = snapshots[-1]
                return last if isinstance(last, dict) else {}
            return {}
        except Exception as exc:  # noqa: BLE001
            log.debug("load_previous_snapshot error: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Internal APY/peg extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_apy(entry: dict) -> float:
        """APY из entry: apy_pct → apy → mock_apy (USDC, первый chain) → 0.0."""
        for key in ("apy_pct", "apy"):
            val = entry.get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
                return float(val)
        # Fallback: mock_apy
        mock = entry.get("mock_apy")
        if isinstance(mock, dict):
            # Попробуем ethereum → первый chain
            for chain_key in ("ethereum", *mock.keys()):
                chain_data = mock.get(chain_key)
                if isinstance(chain_data, dict):
                    usdc = chain_data.get("USDC")
                    if isinstance(usdc, (int, float)) and not isinstance(usdc, bool) and usdc > 0:
                        return float(usdc)
        return 0.0

    @staticmethod
    def _extract_risk_score(entry: dict) -> float:
        """risk_score из entry; fallback по tier."""
        rs = entry.get("risk_score")
        if isinstance(rs, (int, float)) and not isinstance(rs, bool):
            return float(rs)
        tier = str(entry.get("tier", ""))
        return _TIER_DEFAULT_RISK.get(tier, 0.30)

    @staticmethod
    def _extract_peg_price(entry: dict) -> float:
        """usdc_price из entry; fallback 1.0."""
        price = entry.get("usdc_price")
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            return float(price)
        return 1.0

    @staticmethod
    def _extract_chain(entry: dict) -> str:
        """Первый chain из chains[] или поле chain/network; fallback 'ethereum'."""
        chains = entry.get("chains")
        if isinstance(chains, list) and chains:
            return str(chains[0])
        for key in ("chain", "network"):
            val = entry.get(key)
            if isinstance(val, str) and val:
                return val
        return "ethereum"

    # ------------------------------------------------------------------
    # Build index of previous adapter APY for diff
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prev_apy_index(previous: dict) -> Dict[str, float]:
        """
        Строит {adapter_id: apy_pct} из предыдущего snapshot.

        Формат previous: {"adapter_statuses": [...], ...}
        """
        index: Dict[str, float] = {}
        statuses = previous.get("adapter_statuses", [])
        if not isinstance(statuses, list):
            return index
        for entry in statuses:
            if not isinstance(entry, dict):
                continue
            aid = entry.get("adapter_id")
            apy = entry.get("apy_pct")
            if aid and isinstance(apy, (int, float)) and not isinstance(apy, bool):
                index[str(aid)] = float(apy)
        return index

    # ------------------------------------------------------------------
    # Classify
    # ------------------------------------------------------------------

    def classify_adapter(
        self,
        adapter_id: str,
        current: dict,
        previous: dict,
    ) -> AdapterHealth:
        """
        Извлекает текущие данные адаптера из ``current`` adapter_status.json,
        вычисляет apy_change_pct vs предыдущий snapshot, определяет alert_level.

        Параметры
        ----------
        adapter_id : str
            Ключ адаптера (protocol_key).
        current : dict
            Полный dict из adapter_status.json.
        previous : dict
            Предыдущий snapshot (WatchdogReport.to_dict()) или {}.
        """
        # Найти entry адаптера в current
        entry = self._find_adapter_entry(adapter_id, current)

        tier = str(entry.get("tier", "T2"))
        chain = self._extract_chain(entry)
        apy_pct = self._extract_apy(entry)
        risk_score = self._extract_risk_score(entry)
        peg_price = self._extract_peg_price(entry)

        # Peg deviation
        peg_dev = abs(peg_price - 1.0)
        # is_healthy: apy > 0 AND peg within PEG_TOLERANCE
        is_healthy = (apy_pct > 0) and (peg_dev <= self.PEG_TOLERANCE)

        # APY change vs previous
        prev_apy_index = self._build_prev_apy_index(previous)
        prev_apy = prev_apy_index.get(adapter_id)
        if prev_apy is not None:
            apy_change_pct = apy_pct - prev_apy
        else:
            apy_change_pct = 0.0

        # Classify alert_level (CRITICAL > WARNING > OK)
        alert_level = self._classify_level(
            apy_pct, apy_change_pct, peg_dev, risk_score
        )

        return AdapterHealth(
            adapter_id=adapter_id,
            chain=chain,
            tier=tier,
            apy_pct=apy_pct,
            risk_score=risk_score,
            peg_price=peg_price,
            is_healthy=is_healthy,
            apy_change_pct=round(apy_change_pct, 4),
            alert_level=alert_level,
        )

    def _classify_level(
        self,
        apy_pct: float,
        apy_change_pct: float,
        peg_dev: float,
        risk_score: float,
    ) -> str:
        """Возвращает 'CRITICAL', 'WARNING' или 'OK'."""
        # CRITICAL conditions (любое из)
        if apy_pct < self.APY_FLOOR_PCT and apy_pct >= 0:
            return "CRITICAL"
        if apy_change_pct <= -self.APY_DROP_CRITICAL_PCT:
            return "CRITICAL"
        if peg_dev > self.PEG_CRITICAL:
            return "CRITICAL"
        # WARNING conditions (любое из)
        if apy_change_pct <= -self.APY_DROP_WARNING_PCT:
            return "WARNING"
        if peg_dev > self.PEG_TOLERANCE:
            return "WARNING"
        if risk_score > self.RISK_SCORE_CEILING:
            return "WARNING"
        return "OK"

    @staticmethod
    def _find_adapter_entry(adapter_id: str, current: dict) -> dict:
        """
        Ищет entry адаптера в current adapter_status.json.

        Приоритет 1 — список ``adapters[]`` по protocol_key.
        Приоритет 2 — верхнеуровневый ключ adapter_id.
        Fallback — пустой dict.
        """
        adapters_list = current.get("adapters", [])
        if isinstance(adapters_list, list):
            for entry in adapters_list:
                if not isinstance(entry, dict):
                    continue
                if entry.get("protocol_key") == adapter_id:
                    return entry
        # Top-level dict key fallback
        val = current.get(adapter_id)
        if isinstance(val, dict):
            return val
        return {}

    # ------------------------------------------------------------------
    # Extract all adapter IDs from current status
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_adapter_ids(current: dict) -> List[str]:
        """Возвращает список adapter_id из adapter_status.json."""
        adapters_list = current.get("adapters", [])
        ids: List[str] = []
        if isinstance(adapters_list, list):
            for entry in adapters_list:
                if isinstance(entry, dict):
                    pk = entry.get("protocol_key")
                    if pk and isinstance(pk, str):
                        ids.append(pk)
        return ids

    # ------------------------------------------------------------------
    # Alert creation
    # ------------------------------------------------------------------

    def create_alerts(self, statuses: List[AdapterHealth]) -> int:
        """
        Для каждого WARNING/CRITICAL создаёт Alert через AlertDispatcher.
        При недоступности диспетчера — пишет в лог.

        Возвращает количество созданных алертов.
        """
        count = 0
        dispatcher = self._get_dispatcher()

        for status in statuses:
            if status.alert_level == "OK":
                continue

            title, message = self._build_alert_text(status)

            if dispatcher is not None:
                try:
                    from spa_core.alerts.alert_dispatcher import AlertLevel
                    level = (
                        AlertLevel.CRITICAL
                        if status.alert_level == "CRITICAL"
                        else AlertLevel.WARNING
                    )
                    alert = dispatcher.create_alert(
                        level=level,
                        title=title,
                        message=message,
                        adapter_id=status.adapter_id,
                    )
                    dispatcher.dispatch(alert)
                    count += 1
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "AlertDispatcher error for %s: %s — falling back to log",
                        status.adapter_id, exc,
                    )
                    log.warning("[%s] %s | %s", status.alert_level, title, message)
                    count += 1
            else:
                log.warning("[%s] %s | %s", status.alert_level, title, message)
                count += 1

        return count

    @staticmethod
    def _build_alert_text(status: AdapterHealth):
        """Формирует (title, message) для Alert."""
        title = f"Adapter {status.adapter_id} [{status.alert_level}]"
        parts = [
            f"Adapter: {status.adapter_id} (tier={status.tier}, chain={status.chain})",
            f"APY: {status.apy_pct:.2f}% (Δ{status.apy_change_pct:+.2f}%)",
            f"Peg: {status.peg_price:.4f}",
            f"RiskScore: {status.risk_score:.3f}",
            f"Healthy: {status.is_healthy}",
        ]
        return title, " | ".join(parts)

    # ------------------------------------------------------------------
    # Snapshot persistence
    # ------------------------------------------------------------------

    def _save_snapshot(self, report: WatchdogReport) -> None:
        """
        Сохраняет snapshot в watchdog_history.json (ring-buffer 48 записей).
        Atomic: tmp + os.replace.
        """
        try:
            # Загрузить существующую историю
            existing_snapshots: List[dict] = []
            if self._history_path.exists():
                try:
                    with open(self._history_path, encoding="utf-8") as fh:
                        hist = json.load(fh)
                    if isinstance(hist, dict):
                        existing_snapshots = hist.get("snapshots", [])
                        if not isinstance(existing_snapshots, list):
                            existing_snapshots = []
                except Exception:
                    existing_snapshots = []

            new_entry = report.to_dict()
            combined = existing_snapshots + [new_entry]
            if len(combined) > RING_BUFFER_MAX:
                combined = combined[-RING_BUFFER_MAX:]

            payload = {
                "schema_version": 1,
                "source": "adapter_watchdog",
                "ring_buffer_max": RING_BUFFER_MAX,
                "snapshot_count": len(combined),
                "updated_at": report.generated_at,
                "latest": new_entry,
                "snapshots": combined,
            }
            _atomic_write_json(self._history_path, payload)
        except Exception as exc:  # noqa: BLE001
            log.error("_save_snapshot error: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_check(self) -> WatchdogReport:
        """
        Основной метод: загружает current → классифицирует → создаёт алерты
        → сохраняет snapshot в watchdog_history.json.

        Всегда возвращает WatchdogReport (fail-safe).
        """
        generated_at = datetime.now(timezone.utc).isoformat()
        try:
            current = self.load_current_status()
            previous = self.load_previous_snapshot()

            adapter_ids = self._extract_adapter_ids(current)
            statuses = [
                self.classify_adapter(aid, current, previous)
                for aid in adapter_ids
            ]

            healthy = sum(1 for s in statuses if s.alert_level == "OK")
            warning = sum(1 for s in statuses if s.alert_level == "WARNING")
            critical = sum(1 for s in statuses if s.alert_level == "CRITICAL")

            alerts_created = self.create_alerts(statuses)

            report = WatchdogReport(
                generated_at=generated_at,
                total_adapters=len(statuses),
                healthy=healthy,
                warning=warning,
                critical=critical,
                alerts_created=alerts_created,
                adapter_statuses=statuses,
                summary="",
            )
            report.summary = self._make_summary(report)

            self._save_snapshot(report)
            return report

        except Exception as exc:  # noqa: BLE001
            log.error("run_check unexpected error: %s", exc)
            return WatchdogReport(
                generated_at=generated_at,
                total_adapters=0,
                healthy=0,
                warning=0,
                critical=0,
                alerts_created=0,
                adapter_statuses=[],
                summary=f"ERROR: {exc}",
            )

    def get_report(self) -> WatchdogReport:
        """
        Только читает и классифицирует — без создания алертов
        и без записи snapshot (side-effect-free).
        """
        generated_at = datetime.now(timezone.utc).isoformat()
        try:
            current = self.load_current_status()
            previous = self.load_previous_snapshot()

            adapter_ids = self._extract_adapter_ids(current)
            statuses = [
                self.classify_adapter(aid, current, previous)
                for aid in adapter_ids
            ]

            healthy = sum(1 for s in statuses if s.alert_level == "OK")
            warning = sum(1 for s in statuses if s.alert_level == "WARNING")
            critical = sum(1 for s in statuses if s.alert_level == "CRITICAL")

            report = WatchdogReport(
                generated_at=generated_at,
                total_adapters=len(statuses),
                healthy=healthy,
                warning=warning,
                critical=critical,
                alerts_created=0,
                adapter_statuses=statuses,
                summary="",
            )
            report.summary = self._make_summary(report)
            return report

        except Exception as exc:  # noqa: BLE001
            log.error("get_report unexpected error: %s", exc)
            return WatchdogReport(
                generated_at=generated_at,
                total_adapters=0,
                healthy=0,
                warning=0,
                critical=0,
                alerts_created=0,
                adapter_statuses=[],
                summary=f"ERROR: {exc}",
            )

    def to_dict(self) -> dict:
        """Возвращает текущий отчёт (без алертов) как JSON-сериализуемый dict."""
        return self.get_report().to_dict()

    def format_summary(self) -> str:
        """Краткий текстовый отчёт ≤500 символов."""
        return self.get_report().summary

    # ------------------------------------------------------------------
    # Summary builder
    # ------------------------------------------------------------------

    @staticmethod
    def _make_summary(report: WatchdogReport) -> str:
        """Строит краткий отчёт ≤500 символов."""
        parts = [
            f"AdapterWatchdog @ {report.generated_at[:19]}Z",
            (
                f"Adapters: {report.total_adapters} total | "
                f"{report.healthy} OK | "
                f"{report.warning} WARNING | "
                f"{report.critical} CRITICAL"
            ),
            f"Alerts created: {report.alerts_created}",
        ]
        # Добавим критичных адаптеров (не более 3)
        critical_adapters = [
            s for s in report.adapter_statuses if s.alert_level == "CRITICAL"
        ][:3]
        if critical_adapters:
            names = ", ".join(s.adapter_id for s in critical_adapters)
            parts.append(f"CRITICAL: {names}")
        # Предупреждений (не более 3)
        warning_adapters = [
            s for s in report.adapter_statuses if s.alert_level == "WARNING"
        ][:3]
        if warning_adapters:
            names = ", ".join(s.adapter_id for s in warning_adapters)
            parts.append(f"WARNING: {names}")
        summary = " | ".join(parts)
        return summary[:500]


# ===========================================================================
# CLI
# ===========================================================================

def _main(argv=None) -> int:
    """
    CLI:
        python3 -m spa_core.monitoring.adapter_watchdog --check   # читает, без записи (default)
        python3 -m spa_core.monitoring.adapter_watchdog --run     # + запись snapshot + алерты
    """
    import sys
    args = sys.argv[1:] if argv is None else list(argv)
    run_mode = "--run" in args
    data_path = None
    for i, arg in enumerate(args):
        if arg == "--data-dir" and i + 1 < len(args):
            data_path = args[i + 1]

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    watchdog = AdapterWatchdog(data_path=data_path, use_alert_dispatcher=run_mode)

    if run_mode:
        report = watchdog.run_check()
        print(report.summary)
        print(f"Alerts created: {report.alerts_created}")
    else:
        report = watchdog.get_report()
        print(report.summary)

    print(
        f"\nAdapters: {report.total_adapters} total | "
        f"{report.healthy} OK | {report.warning} WARN | {report.critical} CRIT"
    )
    for s in report.adapter_statuses:
        if s.alert_level != "OK":
            print(
                f"  [{s.alert_level}] {s.adapter_id} "
                f"apy={s.apy_pct:.2f}% Δ{s.apy_change_pct:+.2f}% "
                f"peg={s.peg_price:.4f}"
            )
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
