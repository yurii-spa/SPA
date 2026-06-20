"""
peg_monitor.py — MP-601 PegStabilityMonitor.

Мониторит отклонение цены стейблкоинов от 1.00 по всем адаптерам.
Создаёт CRITICAL алерт при депеге любого адаптера.

Атомарные записи: tmp-file + os.replace. Только stdlib.
Никогда не поднимает исключений наружу (fail-safe).

NOT imported from: risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.monitoring.peg_monitor")

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_ADAPTER_STATUS_FILENAME = "adapter_status.json"
_PEG_REPORT_FILENAME = "peg_report.json"
_PEG_HISTORY_FILENAME = "peg_history.json"

# Ring-buffer: 96 snapshots = 4 дня при hourly запуске
RING_BUFFER_MAX = 96

# Meta keys to skip when scanning top-level keys in adapter_status.json
_META_KEYS = frozenset({
    "generated_at", "schema_version", "execution_mode", "live_apy_enabled",
    "mev_protection", "adapters", "base_gas_monitor",
})


# ===========================================================================
# Dataclasses
# ===========================================================================

@dataclass
class PegStatus:
    """Состояние привязки одного адаптера."""
    adapter_id: str
    asset: str            # "USDC", "DAI", "USDT", "FRAX", etc.
    chain: str
    current_price: float  # extracted from adapter_status.json
    deviation_pct: float  # abs(price - 1.0) * 100
    status: str           # "STABLE" / "CAUTION" / "WARNING" / "CRITICAL"
    last_checked: str     # ISO timestamp

    def to_dict(self) -> dict:
        return {
            "adapter_id": self.adapter_id,
            "asset": self.asset,
            "chain": self.chain,
            "current_price": self.current_price,
            "deviation_pct": self.deviation_pct,
            "status": self.status,
            "last_checked": self.last_checked,
        }


@dataclass
class PegReport:
    """Сводный отчёт по состоянию привязки всех адаптеров."""
    generated_at: str
    total_monitored: int
    stable: int
    caution: int           # deviation >= 0.1%
    warning: int           # deviation >= 0.3%
    critical: int          # deviation >= 1.0%
    worst_adapter: str     # adapter_id с наибольшим deviation
    worst_deviation_pct: float
    statuses: List[PegStatus] = field(default_factory=list)
    overall_status: str = "GREEN"  # "GREEN" / "YELLOW" / "RED"

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "total_monitored": self.total_monitored,
            "stable": self.stable,
            "caution": self.caution,
            "warning": self.warning,
            "critical": self.critical,
            "worst_adapter": self.worst_adapter,
            "worst_deviation_pct": self.worst_deviation_pct,
            "overall_status": self.overall_status,
            "statuses": [s.to_dict() for s in self.statuses],
        }


# ===========================================================================
# Atomic write helper
# ===========================================================================

def _atomic_write_json(path: Path, payload: object) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(payload, str(path))
class PegStabilityMonitor:
    """
    Монитор стабильности привязки (peg) стейблкоинов.

    Читает ``data/adapter_status.json``, извлекает цену каждого актива,
    классифицирует отклонение (STABLE/CAUTION/WARNING/CRITICAL)
    и создаёт AlertDispatcher алерты для WARNING/CRITICAL.

    Параметры
    ----------
    data_path : str | None
        Путь к директории с adapter_status.json. По умолчанию — data/.
    use_alert_dispatcher : bool
        Если True — пытается импортировать AlertDispatcher для создания Alert'ов.
        При недоступности автоматически откатывается в log-only режим.
    """

    # Пороги (в % отклонения от 1.00)
    CAUTION_PCT  = 0.10   # 0.1% deviation
    WARNING_PCT  = 0.30   # 0.3% deviation
    CRITICAL_PCT = 1.00   # 1.0% deviation (major depeg)

    # Маппинг: ключевое слово → базовый актив (substring match против adapter_id)
    ASSET_MAP: Dict[str, str] = {
        "aave":     "USDC",
        "morpho":   "USDC",
        "compound": "USDC",
        "sdai":     "DAI",
        "spark":    "USDC/DAI",
        "sfrax":    "FRAX",
        "frax":     "FRAX",
        "susds":    "USDS",
        "sky":      "USDS",
        "wusdm":    "USDM",
        "stusd":    "USD+",
        "scrvusd":  "crvUSD",
    }

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
        self._peg_report_path = self._data_dir / _PEG_REPORT_FILENAME
        self._peg_history_path = self._data_dir / _PEG_HISTORY_FILENAME
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
            # BUG FIX (TELEGRAM_AUDIT 2026-06-18): enable suppress_duplicates
            # with a 1h cooldown (3600 s).  The old default (cooldown_seconds=300,
            # suppress_duplicates=False) combined with launchd restarting this
            # process every 5 min meant the dedup window was reset on every run
            # and CRITICAL peg alerts fired every 5 minutes.
            # Now dedup state is persisted to alert_dispatcher_dedup.json so
            # the 1h window survives process restarts.
            self._dispatcher = AlertDispatcher(
                suppress_duplicates=True,
                cooldown_seconds=3600,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("AlertDispatcher unavailable, log-only mode: %s", exc)
            self._dispatcher = None
        return self._dispatcher

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_adapter_status(self) -> dict:
        """
        Читает adapter_status.json.

        Возвращает {} при любой ошибке (fail-safe).
        """
        try:
            with open(self._adapter_status_path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception as exc:  # noqa: BLE001
            log.debug("load_adapter_status error: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Asset inference
    # ------------------------------------------------------------------

    def infer_asset(self, adapter_id: str) -> str:
        """
        Определяет базовый актив адаптера по ASSET_MAP или ключевым словам в adapter_id.

        Порядок:
          1. Точное совпадение adapter_id.lower() с ключом ASSET_MAP.
          2. Substring: ищет самый длинный ключ ASSET_MAP, являющийся
             подстрокой adapter_id.lower().
          3. Fallback: "USDC".
        """
        lower = adapter_id.lower()

        # 1. Exact match
        if lower in self.ASSET_MAP:
            return self.ASSET_MAP[lower]

        # 2. Longest substring match
        best_key: Optional[str] = None
        best_len: int = 0
        for key in self.ASSET_MAP:
            if key in lower and len(key) > best_len:
                best_key = key
                best_len = len(key)
        if best_key is not None:
            return self.ASSET_MAP[best_key]

        # 3. Fallback
        return "USDC"

    # ------------------------------------------------------------------
    # Price extraction
    # ------------------------------------------------------------------

    def get_peg_price(self, adapter_id: str, data: dict) -> float:
        """
        Ищет цену актива в entry адаптера.

        Проверяет поля в порядке приоритета:
            usdc_price → dai_price → frax_price → peg_price → price → asset_price.
        Fallback: 1.0 (assume stable).
        """
        entry = self._find_entry(adapter_id, data)
        for field_name in (
            "usdc_price", "dai_price", "frax_price",
            "peg_price", "price", "asset_price",
        ):
            val = entry.get(field_name)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                return float(val)
        return 1.0

    @staticmethod
    def _find_entry(adapter_id: str, data: dict) -> dict:
        """
        Ищет entry адаптера в adapter_status.json.

        Приоритет 1 — список ``adapters[]`` по protocol_key.
        Приоритет 2 — верхнеуровневый ключ adapter_id.
        Fallback — пустой dict.
        """
        adapters_list = data.get("adapters", [])
        if isinstance(adapters_list, list):
            for entry in adapters_list:
                if isinstance(entry, dict) and entry.get("protocol_key") == adapter_id:
                    return entry
        # Top-level dict key fallback
        val = data.get(adapter_id)
        if isinstance(val, dict):
            return val
        return {}

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
    # Status classification
    # ------------------------------------------------------------------

    def classify_status(self, deviation_pct: float) -> str:
        """
        Классифицирует отклонение от 1.00 по порогам.

        Returns: "CRITICAL" / "WARNING" / "CAUTION" / "STABLE"
        """
        if deviation_pct >= self.CRITICAL_PCT:
            return "CRITICAL"
        if deviation_pct >= self.WARNING_PCT:
            return "WARNING"
        if deviation_pct >= self.CAUTION_PCT:
            return "CAUTION"
        return "STABLE"

    # ------------------------------------------------------------------
    # Single adapter check
    # ------------------------------------------------------------------

    def check_adapter(self, adapter_id: str, data: dict) -> PegStatus:
        """Создаёт PegStatus для одного адаптера."""
        now = datetime.now(timezone.utc).isoformat()
        entry = self._find_entry(adapter_id, data)

        # Asset: prefer assets[] from entry, else infer from adapter_id
        asset = self.infer_asset(adapter_id)
        assets_field = entry.get("assets")
        if isinstance(assets_field, list) and assets_field:
            asset = str(assets_field[0])

        chain = self._extract_chain(entry)
        current_price = self.get_peg_price(adapter_id, data)
        deviation_pct = round(abs(current_price - 1.0) * 100, 6)
        status = self.classify_status(deviation_pct)

        return PegStatus(
            adapter_id=adapter_id,
            asset=asset,
            chain=chain,
            current_price=current_price,
            deviation_pct=deviation_pct,
            status=status,
            last_checked=now,
        )

    # ------------------------------------------------------------------
    # Extract all adapter IDs
    # ------------------------------------------------------------------

    def _extract_adapter_ids(self, data: dict) -> List[str]:
        """
        Возвращает список adapter_id из adapter_status.json.

        Объединяет: adapters[].protocol_key + верхнеуровневые ключи-адаптеры.
        Дедуплицирует, сохраняет порядок.
        """
        seen: set = set()
        ids: List[str] = []

        # 1. From adapters[] list (protocol_key)
        adapters_list = data.get("adapters", [])
        if isinstance(adapters_list, list):
            for entry in adapters_list:
                if isinstance(entry, dict):
                    pk = entry.get("protocol_key")
                    if pk and isinstance(pk, str) and pk not in seen:
                        seen.add(pk)
                        ids.append(pk)

        # 2. Top-level dict keys (skip meta keys and non-dict values)
        for key, val in data.items():
            if key in _META_KEYS:
                continue
            if not isinstance(val, dict):
                continue
            if key not in seen:
                seen.add(key)
                ids.append(key)

        return ids

    # ------------------------------------------------------------------
    # Overall status
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_overall_status(statuses: List[PegStatus]) -> str:
        """RED if any CRITICAL; YELLOW if any WARNING or CAUTION; GREEN otherwise."""
        if any(s.status == "CRITICAL" for s in statuses):
            return "RED"
        if any(s.status in ("WARNING", "CAUTION") for s in statuses):
            return "YELLOW"
        return "GREEN"

    # ------------------------------------------------------------------
    # Build PegReport from statuses
    # ------------------------------------------------------------------

    @staticmethod
    def _build_report(generated_at: str, statuses: List[PegStatus]) -> PegReport:
        """Строит PegReport из списка PegStatus."""
        stable   = sum(1 for s in statuses if s.status == "STABLE")
        caution  = sum(1 for s in statuses if s.status == "CAUTION")
        warning  = sum(1 for s in statuses if s.status == "WARNING")
        critical = sum(1 for s in statuses if s.status == "CRITICAL")

        if statuses:
            worst = max(statuses, key=lambda s: s.deviation_pct)
            worst_adapter = worst.adapter_id
            worst_deviation_pct = worst.deviation_pct
        else:
            worst_adapter = ""
            worst_deviation_pct = 0.0

        overall = PegStabilityMonitor._compute_overall_status(statuses)

        return PegReport(
            generated_at=generated_at,
            total_monitored=len(statuses),
            stable=stable,
            caution=caution,
            warning=warning,
            critical=critical,
            worst_adapter=worst_adapter,
            worst_deviation_pct=worst_deviation_pct,
            statuses=statuses,
            overall_status=overall,
        )

    # ------------------------------------------------------------------
    # Alert creation
    # ------------------------------------------------------------------

    def _create_alerts(self, statuses: List[PegStatus]) -> int:
        """
        Для каждого WARNING/CRITICAL создаёт Alert через AlertDispatcher.
        STABLE и CAUTION алертов не создаёт.
        При недоступности диспетчера — пишет в лог.

        Возвращает количество созданных алертов.
        """
        count = 0
        dispatcher = self._get_dispatcher()

        for status in statuses:
            if status.status not in ("WARNING", "CRITICAL"):
                continue

            title = f"Peg {status.status}: {status.adapter_id} ({status.asset})"
            message = (
                f"Adapter: {status.adapter_id} | Asset: {status.asset} | "
                f"Chain: {status.chain} | Price: {status.current_price:.6f} | "
                f"Deviation: {status.deviation_pct:.4f}%"
            )

            if dispatcher is not None:
                try:
                    from spa_core.alerts.alert_dispatcher import AlertLevel
                    level = (
                        AlertLevel.CRITICAL
                        if status.status == "CRITICAL"
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
                    log.warning("[%s] %s | %s", status.status, title, message)
                    count += 1
            else:
                log.warning("[%s] %s | %s", status.status, title, message)
                count += 1

        return count

    # ------------------------------------------------------------------
    # History ring-buffer persistence
    # ------------------------------------------------------------------

    def _save_history(self, report: PegReport) -> None:
        """
        Сохраняет snapshot в peg_history.json (ring-buffer 96 записей).
        Atomic: tmp + os.replace.
        """
        try:
            existing: List[dict] = []
            if self._peg_history_path.exists():
                try:
                    with open(self._peg_history_path, encoding="utf-8") as fh:
                        hist = json.load(fh)
                    if isinstance(hist, dict):
                        existing = hist.get("snapshots", [])
                        if not isinstance(existing, list):
                            existing = []
                except Exception:
                    existing = []

            new_entry = report.to_dict()
            combined = existing + [new_entry]
            if len(combined) > RING_BUFFER_MAX:
                combined = combined[-RING_BUFFER_MAX:]

            payload = {
                "schema_version": 1,
                "source": "peg_monitor",
                "ring_buffer_max": RING_BUFFER_MAX,
                "snapshot_count": len(combined),
                "updated_at": report.generated_at,
                "latest": new_entry,
                "snapshots": combined,
            }
            _atomic_write_json(self._peg_history_path, payload)
        except Exception as exc:  # noqa: BLE001
            log.error("_save_history error: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_check(self) -> PegReport:
        """
        Основной метод: загружает адаптеры → проверяет peg → создаёт алерты
        → сохраняет историю в peg_history.json.

        Всегда возвращает PegReport (fail-safe).
        """
        generated_at = datetime.now(timezone.utc).isoformat()
        try:
            data = self.load_adapter_status()
            adapter_ids = self._extract_adapter_ids(data)
            statuses = [self.check_adapter(aid, data) for aid in adapter_ids]

            self._create_alerts(statuses)
            report = self._build_report(generated_at, statuses)
            self._save_history(report)
            return report

        except Exception as exc:  # noqa: BLE001
            log.error("run_check unexpected error: %s", exc)
            return PegReport(
                generated_at=generated_at,
                total_monitored=0,
                stable=0,
                caution=0,
                warning=0,
                critical=0,
                worst_adapter="",
                worst_deviation_pct=0.0,
                statuses=[],
                overall_status="GREEN",
            )

    def get_report(self) -> PegReport:
        """
        Только читает и классифицирует — без создания алертов
        и без записи истории (side-effect-free).
        """
        generated_at = datetime.now(timezone.utc).isoformat()
        try:
            data = self.load_adapter_status()
            adapter_ids = self._extract_adapter_ids(data)
            statuses = [self.check_adapter(aid, data) for aid in adapter_ids]
            return self._build_report(generated_at, statuses)

        except Exception as exc:  # noqa: BLE001
            log.error("get_report unexpected error: %s", exc)
            return PegReport(
                generated_at=generated_at,
                total_monitored=0,
                stable=0,
                caution=0,
                warning=0,
                critical=0,
                worst_adapter="",
                worst_deviation_pct=0.0,
                statuses=[],
                overall_status="GREEN",
            )

    def format_telegram_message(self) -> str:
        """
        Форматирует отчёт для Telegram. ≤1500 символов.

        Содержит overall_status, worst deviation и список non-STABLE адаптеров.
        """
        try:
            report = self.get_report()
            emoji_map = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}
            emoji = emoji_map.get(report.overall_status, "⚪")
            lines = [
                f"{emoji} <b>PegMonitor [{report.overall_status}]</b>",
                f"🕐 {report.generated_at[:19]}Z",
                (
                    f"📊 Adapters: {report.total_monitored} | "
                    f"✅{report.stable} STABLE | "
                    f"⚠️{report.caution} CAUTION | "
                    f"🚨{report.warning} WARNING | "
                    f"🔴{report.critical} CRITICAL"
                ),
            ]
            if report.worst_adapter:
                lines.append(
                    f"🏆 Worst: <code>{report.worst_adapter}</code> "
                    f"dev={report.worst_deviation_pct:.4f}%"
                )

            # List non-STABLE adapters (up to 5)
            non_stable = [s for s in report.statuses if s.status != "STABLE"][:5]
            if non_stable:
                lines.append("")
                lines.append("<b>Non-stable adapters:</b>")
                for s in non_stable:
                    lines.append(
                        f"  [{s.status}] <code>{s.adapter_id}</code> "
                        f"{s.asset}@{s.chain} "
                        f"price={s.current_price:.6f} "
                        f"dev={s.deviation_pct:.4f}%"
                    )

            msg = "\n".join(lines)
            if len(msg) > 1500:
                msg = msg[:1497] + "..."
            return msg
        except Exception as exc:  # noqa: BLE001
            log.error("format_telegram_message error: %s", exc)
            return "PegMonitor: error generating message"

    def to_dict(self) -> dict:
        """Возвращает текущий отчёт (без алертов) как JSON-сериализуемый dict."""
        return self.get_report().to_dict()

    def save_report(self) -> str:
        """
        Сохраняет data/peg_report.json атомарно.
        Возвращает абсолютный путь к файлу.
        """
        report = self.get_report()
        _atomic_write_json(self._peg_report_path, report.to_dict())
        return str(self._peg_report_path)


# ===========================================================================
# CLI
# ===========================================================================

def _main(argv=None) -> int:
    """
    CLI:
        python3 -m spa_core.monitoring.peg_monitor --check   # читает, без записи (default)
        python3 -m spa_core.monitoring.peg_monitor --run     # + запись истории + алерты
        python3 -m spa_core.monitoring.peg_monitor --run --data-dir <dir>
    """
    import sys
    args = sys.argv[1:] if argv is None else list(argv)
    run_mode = "--run" in args
    data_path = None
    for i, arg in enumerate(args):
        if arg == "--data-dir" and i + 1 < len(args):
            data_path = args[i + 1]

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    monitor = PegStabilityMonitor(
        data_path=data_path,
        use_alert_dispatcher=run_mode,
    )

    if run_mode:
        report = monitor.run_check()
        saved = monitor.save_report()
        print(f"Report saved to: {saved}")
    else:
        report = monitor.get_report()

    print(
        f"\nPegMonitor [{report.overall_status}] @ {report.generated_at[:19]}Z"
    )
    print(
        f"Adapters: {report.total_monitored} total | "
        f"{report.stable} STABLE | "
        f"{report.caution} CAUTION | "
        f"{report.warning} WARNING | "
        f"{report.critical} CRITICAL"
    )
    if report.worst_adapter:
        print(
            f"Worst: {report.worst_adapter} — "
            f"deviation={report.worst_deviation_pct:.4f}%"
        )
    for s in report.statuses:
        if s.status != "STABLE":
            print(
                f"  [{s.status}] {s.adapter_id} ({s.asset}@{s.chain}) "
                f"price={s.current_price:.6f} dev={s.deviation_pct:.4f}%"
            )
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
