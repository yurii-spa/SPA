"""
peg_monitor.py — MP-601 PegStabilityMonitor.

Мониторит отклонение цены стейблкоинов от 1.00 по тому, что книги ДЕРЖАТ (+ наличные).
Создаёт CRITICAL алерт при депеге. Цена — только наблюдённая (поле адаптера или кворум
RTMR); нет цены ⇒ UNMEASURED, общий статус UNKNOWN — никогда GREEN (ADR-531).

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

#: Контракт агента (ADR-154/158): что этот агент ПРОИЗВОДИТ.
#: Объявление, а не вывод из кода. Источники: запись, видимая в этом модуле,
#: и авторская карта AGENT_OUTPUT_FILES в spa_core/monitoring/uptime_monitor.py.
#: Сверка — spa_core/monitoring/artifact_contract.py.
PRODUCES = (
    "data/peg_report.json",
)

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
    current_price: Optional[float]  # наблюдённая цена; None = НЕ ИЗМЕРЕНО (ADR-531)
    deviation_pct: Optional[float]  # abs(price - 1.0) * 100; None, когда цены нет
    status: str           # "STABLE" / "CAUTION" / "WARNING" / "CRITICAL" / "UNMEASURED"
    last_checked: str     # ISO timestamp
    price_source: str = "none"   # "adapter" / "rtmr_quorum" / "adapter+rtmr" / "none"
    conflict: bool = False       # источники разошлись ≥ CAUTION — взята худшая цена
    instrument_price: Optional[float] = None   # цена САМОГО инструмента (поле адаптера) — для переоценки

    def to_dict(self) -> dict:
        return {
            "adapter_id": self.adapter_id,
            "asset": self.asset,
            "chain": self.chain,
            "current_price": self.current_price,
            "deviation_pct": self.deviation_pct,
            "status": self.status,
            "last_checked": self.last_checked,
            "price_source": self.price_source,
            "conflict": self.conflict,
            "instrument_price": self.instrument_price,
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
    worst_deviation_pct: Optional[float]   # None — ни одна цена не измерена
    statuses: List[PegStatus] = field(default_factory=list)
    # "GREEN" / "YELLOW" / "RED" / "UNKNOWN". GREEN — ТОЛЬКО когда каждый наблюдаемый
    # актив измерен и стабилен (ADR-531); слепой монитор GREEN не выдаёт.
    overall_status: str = "UNKNOWN"
    unmeasured: int = 0
    reason: Optional[str] = None           # почему UNKNOWN, если так

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "total_monitored": self.total_monitored,
            "stable": self.stable,
            "caution": self.caution,
            "warning": self.warning,
            "critical": self.critical,
            "unmeasured": self.unmeasured,
            "worst_adapter": self.worst_adapter,
            "worst_deviation_pct": self.worst_deviation_pct,
            "overall_status": self.overall_status,
            "reason": self.reason,
            "monitored_set": "held positions of all three books + book cash (ADR-531)",
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
        # Держимые книгами на 2026-10-01 (ADR-531: монитор смотрит на то, что держим).
        "maple":    "USDC",
        "fluid":    "USDC",
        "euler":    "USDC",
        "susde":    "USDe",
        "ethena":   "USDe",
        "cash":     "USDC",
    }

    #: Свежесть мультиисточниковой цены RTMR (сенсор пега, кворум ≥3 бирж, ADR-053).
    RTMR_PRICE_MAX_AGE_S = 1800

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

    def get_peg_price(self, adapter_id: str, data: dict) -> Optional[float]:
        """
        Ищет цену актива в entry адаптера.

        Проверяет поля в порядке приоритета:
            usdc_price → dai_price → frax_price → peg_price → price → asset_price.
        Нет поля ⇒ ``None`` — НЕ ИЗМЕРЕНО. Подстановки 1.0 («assume stable») больше нет
        (ADR-531, P0-3 аудита ADR-530): выдуманная единица выглядела как наблюдение и
        красила монитор в GREEN, а его GREEN читал внутридневной стоп-кран.
        """
        entry = self._find_entry(adapter_id, data)
        for field_name in (
            "usdc_price", "dai_price", "frax_price",
            "peg_price", "price", "asset_price",
        ):
            val = entry.get(field_name)
            if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
                return float(val)
        return None

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

    def _asset_is_mapped(self, adapter_id: str) -> bool:
        lower = adapter_id.lower()
        return lower in self.ASSET_MAP or any(k in lower for k in self.ASSET_MAP)

    def check_adapter(self, adapter_id: str, data: dict,
                      rtmr_prices: Optional[Dict[str, float]] = None) -> PegStatus:
        """Создаёт PegStatus для одного адаптера.

        Цена — только НАБЛЮДЁННАЯ: поле самого адаптера и/или мультиисточниковая цена
        RTMR по базовому активу (кворум бирж, ADR-053). Обе есть и расходятся ≥ CAUTION ⇒
        берётся худшая (большее отклонение), ``conflict=True``. Ни одной ⇒ UNMEASURED.
        Актив, выведенный только запасным «USDC» (имя не опознано), не оценивается —
        цена угаданного актива не есть наблюдение.
        """
        now = datetime.now(timezone.utc).isoformat()
        entry = self._find_entry(adapter_id, data)

        # Asset: prefer assets[] from entry, else infer from adapter_id
        asset = self.infer_asset(adapter_id)
        asset_known = self._asset_is_mapped(adapter_id)
        assets_field = entry.get("assets")
        if isinstance(assets_field, list) and assets_field:
            asset = str(assets_field[0])
            asset_known = True

        chain = self._extract_chain(entry)
        own = self.get_peg_price(adapter_id, data)
        quorum = None
        if asset_known and rtmr_prices:
            seen = [rtmr_prices[a.strip().upper()] for a in str(asset).split("/")
                    if a.strip().upper() in rtmr_prices]
            if seen:
                quorum = max(seen, key=lambda px: abs(px - 1.0))
        conflict = False
        if own is not None and quorum is not None:
            conflict = abs(own - quorum) * 100 >= self.CAUTION_PCT
            price = own if abs(own - 1.0) >= abs(quorum - 1.0) else quorum
            source = "adapter+rtmr"
        elif own is not None:
            price, source = own, "adapter"
        elif quorum is not None:
            price, source = quorum, "rtmr_quorum"
        else:
            price, source = None, "none"

        if price is None:
            return PegStatus(adapter_id=adapter_id, asset=asset, chain=chain,
                             current_price=None, deviation_pct=None, status="UNMEASURED",
                             last_checked=now, price_source="none")
        deviation_pct = round(abs(price - 1.0) * 100, 6)
        return PegStatus(
            adapter_id=adapter_id,
            asset=asset,
            chain=chain,
            current_price=price,
            deviation_pct=deviation_pct,
            status=self.classify_status(deviation_pct),
            last_checked=now,
            price_source=source,
            conflict=conflict,
            instrument_price=own,
        )

    def load_rtmr_prices(self, now_s: Optional[float] = None) -> Dict[str, float]:
        """asset → цена из сенсора пега RTMR (``data/monitoring/signals/latest.json``).

        Берётся только сигнал ``source == "peg"`` с ``staleness_ok`` и числовой ценой, не
        старше ``RTMR_PRICE_MAX_AGE_S``. Нет файла / протух / нечитаем ⇒ ``{}`` (цены нет —
        и это видно как UNMEASURED, а не как «стабильно»).
        """
        try:
            doc = json.loads((self._data_dir / "monitoring" / "signals" / "latest.json")
                             .read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — no quorum file ⇒ no price ⇒ UNMEASURED (visible)
            log.warning("peg_monitor: RTMR signals unreadable (%s) — quorum prices unavailable", exc)
            return {}
        now_s = float(now_s if now_s is not None else datetime.now(timezone.utc).timestamp())
        out: Dict[str, float] = {}
        for s in (doc.get("signals") or []) if isinstance(doc, dict) else []:
            if not isinstance(s, dict) or s.get("source") != "peg" or not s.get("staleness_ok"):
                continue
            ts = s.get("ts")
            if not isinstance(ts, (int, float)) or now_s - float(ts) > self.RTMR_PRICE_MAX_AGE_S:
                continue
            px = (s.get("detail") or {}).get("price")
            scope = str(s.get("scope") or "").strip().upper()
            if scope and isinstance(px, (int, float)) and not isinstance(px, bool) and px > 0:
                out[scope] = float(px)
        return out

    def load_held_ids(self) -> Optional[List[str]]:
        """Протоколы, которые книги держат сейчас (+ ``cash`` при наличных), отсортировано.

        Главная книга (``current_positions.json``) обязательна: нечитаема ⇒ ``None`` —
        «что держим» НЕ ИЗМЕРЕНО. Книги рукавов необязательны (их может не быть), но
        существующий нечитаемый файл тоже даёт ``None``.
        """
        def _read(name):
            path = self._data_dir / name
            if not path.exists():
                return False
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return None
        main = _read("current_positions.json")
        if not isinstance(main, dict) or not isinstance(main.get("positions"), dict):
            return None
        held = set()
        for proto, usd in main["positions"].items():
            try:
                if float(usd) > 0:
                    held.add(str(proto))
            except (TypeError, ValueError):
                return None
        cash = main.get("cash_usd")   # нет поля ⇒ наличных не наблюдали ⇒ их и не смотрим
        if isinstance(cash, (int, float)) and not isinstance(cash, bool) and cash > 0:
            held.add("cash")
        for name in ("hy_paper_trading.json", "lp_paper_trading.json"):
            doc = _read(name)
            if doc is False:
                continue
            if not isinstance(doc, dict):
                return None
            legs = doc.get("positions")
            if legs is not None and not isinstance(legs, list):
                return None
            for leg in legs if isinstance(legs, list) else []:
                if not isinstance(leg, dict) or not leg.get("protocol"):
                    continue
                n = leg.get("notional_usd")
                if isinstance(n, (int, float)) and not isinstance(n, bool) and n > 0:
                    held.add(str(leg["protocol"]))
        return sorted(held)

    def _measure(self) -> PegReport:
        """Один замер наблюдаемого набора; общий путь ``run_check`` и ``get_report``."""
        generated_at = datetime.now(timezone.utc).isoformat()
        held = self.load_held_ids()
        if held is None:
            rep = self._build_report(generated_at, [])
            rep.reason = "held positions unreadable — peg exposure NOT MEASURED"
            return rep
        data = self.load_adapter_status()
        rtmr = self.load_rtmr_prices()
        statuses = [self.check_adapter(aid, data, rtmr) for aid in held]
        rep = self._build_report(generated_at, statuses)
        if rep.overall_status == "UNKNOWN":
            rep.reason = (f"{rep.unmeasured} of {rep.total_monitored} held asset(s) without an "
                          "observed price — NOT MEASURED, never «stable»")
        return rep

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
        """RED > UNKNOWN > YELLOW > GREEN (ADR-531).

        RED — хоть один CRITICAL. UNKNOWN — пустой набор или хоть один UNMEASURED (слепой
        монитор не имеет права сказать GREEN). YELLOW — WARNING/CAUTION. GREEN — только
        когда КАЖДЫЙ наблюдаемый актив измерен и стабилен.
        """
        if any(s.status == "CRITICAL" for s in statuses):
            return "RED"
        if not statuses or any(s.status == "UNMEASURED" for s in statuses):
            return "UNKNOWN"
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
        unmeasured = sum(1 for s in statuses if s.status == "UNMEASURED")

        measured = [s for s in statuses if s.deviation_pct is not None]
        if measured:
            worst = max(measured, key=lambda s: s.deviation_pct)
            worst_adapter = worst.adapter_id
            worst_deviation_pct = worst.deviation_pct
        else:
            worst_adapter = ""
            worst_deviation_pct = None   # ни одной цены — отклонение не измерено, а не 0

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
            unmeasured=unmeasured,
        )

    # ------------------------------------------------------------------
    # Alert creation
    # ------------------------------------------------------------------

    def _is_held_protocol(self, adapter_id: str) -> bool:
        """True if ``adapter_id`` maps to a protocol in current_positions.json.

        Read-only, fail-safe (an unreadable positions file → not held, so a peg
        break that can't be confirmed held is demoted to the digest, never
        spuriously interrupted). Loose substring match handles dashes/suffixes.
        """
        try:
            data_dir = getattr(self, "_data_dir", None) or _DEFAULT_DATA_DIR
            path = Path(data_dir) / "current_positions.json"
            if not path.exists():
                return False
            doc = json.loads(path.read_text(encoding="utf-8"))
            positions = doc.get("positions") if isinstance(doc, dict) else None
            held = {str(k).lower().replace("-", "_") for k in (positions or {})}
            aid = str(adapter_id).lower().replace("-", "_")
            return any(h and (h in aid or aid in h) for h in held)
        except Exception:  # noqa: BLE001 — fail-safe: unknown ⇒ not held ⇒ no push
            return False

    def _push_peg_break(self, status, title: str, message: str) -> None:
        """Route a CRITICAL peg break through push_policy (held-scoped, edge)."""
        try:
            from spa_core.telegram import push_policy
            push_policy.push_critical(
                "peg_break",
                "CRITICAL",
                title,
                message,
                held_protocol=self._is_held_protocol(status.adapter_id),
            )
        except Exception as exc:  # noqa: BLE001 — alerts must never crash the monitor
            log.warning("peg_monitor: push_policy routing failed: %s", exc)

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

            # Tier-1 PUSH path (Phase-1 Telegram rebuild): a CRITICAL peg break on
            # a HELD protocol is a genuine real-time interrupt (live capital at
            # risk) and is routed through the SINGLE push authority, held-scoped
            # + edge-triggered. WARNING / non-held breaks never push (they are
            # advisory → digest count + on-demand /alerts). The dispatcher still
            # records the alert into its own JSON history below.
            if status.status == "CRITICAL":
                self._push_peg_break(status, title, message)

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
        Основной метод: замер держимого набора → алерты → история в peg_history.json.

        Всегда возвращает PegReport (fail-safe). Ошибка — UNKNOWN, никогда не GREEN.
        """
        try:
            report = self._measure()
            self._create_alerts(report.statuses)
            self._save_history(report)
            return report
        except Exception as exc:  # noqa: BLE001
            log.error("run_check unexpected error: %s", exc)
            return self._error_report(exc)

    def get_report(self) -> PegReport:
        """
        Только читает и классифицирует — без создания алертов
        и без записи истории (side-effect-free).
        """
        try:
            return self._measure()
        except Exception as exc:  # noqa: BLE001
            log.error("get_report unexpected error: %s", exc)
            return self._error_report(exc)

    @staticmethod
    def _error_report(exc: Exception) -> PegReport:
        rep = PegStabilityMonitor._build_report(datetime.now(timezone.utc).isoformat(), [])
        rep.reason = f"peg check failed ({type(exc).__name__}) — NOT MEASURED"
        return rep

    def format_telegram_message(self) -> str:
        """
        Форматирует отчёт для Telegram. ≤1500 символов.

        Содержит overall_status, worst deviation и список non-STABLE адаптеров.
        """
        try:
            report = self.get_report()
            emoji_map = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴", "UNKNOWN": "⚪"}
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
            if report.unmeasured:
                lines.append(f"❔ {report.unmeasured} held asset(s) NOT MEASURED (no observed price)")
            if report.worst_adapter and report.worst_deviation_pct is not None:
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
                    px = "n/a" if s.current_price is None else f"{s.current_price:.6f}"
                    dev = "n/a" if s.deviation_pct is None else f"{s.deviation_pct:.4f}%"
                    lines.append(
                        f"  [{s.status}] <code>{s.adapter_id}</code> "
                        f"{s.asset}@{s.chain} price={px} dev={dev}"
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
    if report.worst_adapter and report.worst_deviation_pct is not None:
        print(
            f"Worst: {report.worst_adapter} — "
            f"deviation={report.worst_deviation_pct:.4f}%"
        )
    if report.reason:
        print(f"Reason: {report.reason}")
    for s in report.statuses:
        if s.status != "STABLE":
            px = "n/a" if s.current_price is None else f"{s.current_price:.6f}"
            dev = "n/a" if s.deviation_pct is None else f"{s.deviation_pct:.4f}%"
            print(f"  [{s.status}] {s.adapter_id} ({s.asset}@{s.chain}) price={px} dev={dev}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
