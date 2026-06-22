"""
Alert Threshold Manager — MP-622.

Централизованное управление порогами алертов для всех аналитических модулей.
Читает текущие значения из analytics JSON, сравнивает с пороговыми значениями,
генерирует список активных алертов с severity.

Design constraints
------------------
* Pure stdlib — no external deps.
* Advisory only — never touches allocator / risk / execution.
* Atomic writes — tmp + os.replace on every JSON update.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* exit(0) always from CLI.

CLI
---
    python3 -m spa_core.analytics.alert_threshold_manager --check
    python3 -m spa_core.analytics.alert_threshold_manager --run
    python3 -m spa_core.analytics.alert_threshold_manager --telegram
    python3 -m spa_core.analytics.alert_threshold_manager --run --data-dir /path/to/data
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.analytics.alert_threshold_manager")

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

_OUTPUT_FILE = "alert_report.json"

# Ring-buffer: 48 snapshots ≈ 2 дня при hourly запуске
RING_BUFFER_MAX = 48


# ===========================================================================
# Dataclasses
# ===========================================================================

@dataclass
class ThresholdDefinition:
    """Определение одного порогового правила."""
    name: str               # "apy_floor" / "peg_deviation" / "t2_cap" etc.
    metric_path: str        # путь к JSON-файлу (относительно data/)
    operator: str           # "lt" / "gt" / "lte" / "gte"
    threshold_value: float
    severity: str           # "CRITICAL" / "WARNING" / "INFO"
    message_template: str   # "Portfolio APY {value:.2f}% below floor {threshold:.2f}%"

    # Validation helpers
    VALID_OPERATORS = frozenset({"lt", "gt", "lte", "gte"})
    VALID_SEVERITIES = frozenset({"CRITICAL", "WARNING", "INFO"})

    def __post_init__(self) -> None:
        if self.operator not in self.VALID_OPERATORS:
            raise ValueError(
                f"Unknown operator '{self.operator}'; "
                f"valid: {sorted(self.VALID_OPERATORS)}"
            )
        if self.severity not in self.VALID_SEVERITIES:
            raise ValueError(
                f"Unknown severity '{self.severity}'; "
                f"valid: {sorted(self.VALID_SEVERITIES)}"
            )


@dataclass
class AlertEvent:
    """Один сработавший (или не сработавший) алерт-инцидент."""
    threshold_name: str
    severity: str           # "CRITICAL" / "WARNING" / "INFO"
    current_value: float
    threshold_value: float
    message: str
    triggered_at: str       # ISO datetime UTC
    is_active: bool         # True если порог нарушен прямо сейчас

    def to_dict(self) -> dict:
        return {
            "threshold_name": self.threshold_name,
            "severity": self.severity,
            "current_value": self.current_value,
            "threshold_value": self.threshold_value,
            "message": self.message,
            "triggered_at": self.triggered_at,
            "is_active": self.is_active,
        }


@dataclass
class AlertReport:
    """Итоговый отчёт одного прохода AlertThresholdManager."""
    generated_at: str
    thresholds_checked: int
    alerts_active: int
    critical_count: int
    warning_count: int
    info_count: int
    events: List[AlertEvent] = field(default_factory=list)
    all_clear: bool = True      # True если alerts_active == 0
    summary: str = ""           # "3 alerts: 1 CRITICAL, 2 WARNING"

    def __post_init__(self) -> None:
        # Вычислить all_clear и summary если не переданы явно
        if not self.summary:
            self.summary = _build_summary(self)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "thresholds_checked": self.thresholds_checked,
            "alerts_active": self.alerts_active,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "all_clear": self.all_clear,
            "summary": self.summary,
            "events": [e.to_dict() for e in self.events],
        }


def _build_summary(report: AlertReport) -> str:
    """Строит краткое текстовое резюме отчёта."""
    if report.alerts_active == 0:
        return "All clear — no active alerts"
    parts = []
    if report.critical_count:
        parts.append(f"{report.critical_count} CRITICAL")
    if report.warning_count:
        parts.append(f"{report.warning_count} WARNING")
    if report.info_count:
        parts.append(f"{report.info_count} INFO")
    return f"{report.alerts_active} alerts: {', '.join(parts)}"


# ===========================================================================
# Atomic write helper
# ===========================================================================

def _atomic_write_json(path: Path, payload: object) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(payload, str(path))
class AlertThresholdManager:
    """
    Централизованный менеджер порогов алертов.

    Читает текущие метрики из analytics JSON-файлов, сравнивает с
    пороговыми значениями из DEFAULT_THRESHOLDS, генерирует список
    активных AlertEvent с severity CRITICAL / WARNING / INFO.

    Advisory only — никаких транзакций, никаких записей в risk/.
    """

    # -----------------------------------------------------------------------
    # Default thresholds
    # -----------------------------------------------------------------------
    DEFAULT_THRESHOLDS: List[ThresholdDefinition] = [
        # APY метрики
        ThresholdDefinition(
            "apy_floor",
            "data/yield_attribution_tracker.json",
            "lt", 3.0, "CRITICAL",
            "Portfolio APY {value:.2f}% below critical floor {threshold:.2f}%",
        ),
        ThresholdDefinition(
            "apy_warning",
            "data/yield_attribution_tracker.json",
            "lt", 4.0, "WARNING",
            "Portfolio APY {value:.2f}% below warning threshold {threshold:.2f}%",
        ),

        # Tier exposure
        ThresholdDefinition(
            "t2_cap_breach",
            "data/tier_exposure.json",
            "gt", 50.0, "CRITICAL",
            "T2 exposure {value:.1f}% exceeds ADR-019 cap {threshold:.1f}%",
        ),
        ThresholdDefinition(
            "t3_cap_breach",
            "data/tier_exposure.json",
            "gt", 15.0, "CRITICAL",
            "T3 exposure {value:.1f}% exceeds ADR-020 cap {threshold:.1f}%",
        ),

        # Chain exposure
        ThresholdDefinition(
            "chain_concentration",
            "data/chain_exposure.json",
            "gt", 70.0, "WARNING",
            "Single chain exposure {value:.1f}% exceeds policy {threshold:.1f}%",
        ),

        # Capital efficiency
        ThresholdDefinition(
            "deployment_low",
            "data/capital_efficiency.json",
            "lt", 50.0, "WARNING",
            "Deployment rate {value:.1f}% below minimum {threshold:.1f}%",
        ),

        # Risk score
        ThresholdDefinition(
            "risk_score_high",
            "data/integrated_risk.json",
            "gt", 0.50, "CRITICAL",
            "Integrated risk score {value:.2f} exceeds critical threshold {threshold:.2f}",
        ),
        ThresholdDefinition(
            "risk_score_warning",
            "data/integrated_risk.json",
            "gt", 0.25, "WARNING",
            "Integrated risk score {value:.2f} exceeds warning threshold {threshold:.2f}",
        ),

        # Rebalance
        ThresholdDefinition(
            "rebalance_needed",
            "data/rebalance_plan.json",
            "gt", 0, "INFO",
            "Rebalance opportunity available: +{value:.0f} moves suggested",
        ),
    ]

    # -----------------------------------------------------------------------
    # Metric key → extractor mapping
    # -----------------------------------------------------------------------
    # Описывает как извлечь числовое значение из latest-словаря по имени порога.
    _METRIC_KEYS = {
        "apy_floor":          "effective_apy_pct",   # yield_attribution_tracker.json
        "apy_warning":        "effective_apy_pct",   # yield_attribution_tracker.json
        "t2_cap_breach":      "t2_weight_pct",       # tier_exposure.json
        "t3_cap_breach":      "t3_weight_pct",       # tier_exposure.json
        "chain_concentration": "dominant_weight_pct", # chain_exposure.json
        "deployment_low":     "deployment_rate_pct", # capital_efficiency.json
        "risk_score_high":    "overall_score",       # integrated_risk.json
        "risk_score_warning": "overall_score",       # integrated_risk.json
        "rebalance_needed":   "total_moves",         # rebalance_plan.json
    }

    def __init__(
        self,
        data_path: Optional[str] = None,
        thresholds: Optional[List[ThresholdDefinition]] = None,
    ) -> None:
        self._data_dir = Path(data_path) if data_path else _DEFAULT_DATA_DIR
        self._thresholds = thresholds if thresholds is not None else self.DEFAULT_THRESHOLDS

    # -----------------------------------------------------------------------
    # JSON loading
    # -----------------------------------------------------------------------

    def _safe_load_json(self, filepath: str) -> Optional[dict]:
        """
        Читает JSON по абсолютному или относительному пути.

        Относительный путь разрешается от project root (НЕ от data_dir),
        так как metric_path в ThresholdDefinition уже содержит "data/…".
        Если файл не найден или не валидный JSON → возвращает None.
        """
        path = Path(filepath)
        if not path.is_absolute():
            path = _PROJECT_ROOT / filepath
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            log.debug("File not found: %s", path)
            return None
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            log.warning("Failed to load %s: %s", path, exc)
            return None

    def _extract_latest(self, data: dict) -> dict:
        """
        Извлекает 'latest' словарь из загруженных данных.

        Если 'latest' — dict → возвращает его.
        Если 'latest' — list и не пуст → возвращает последний элемент.
        Иначе → возвращает сам data (прямая совместимость).
        """
        latest = data.get("latest")
        if isinstance(latest, dict):
            return latest
        if isinstance(latest, list) and latest:
            last = latest[-1]
            return last if isinstance(last, dict) else data
        # Fallback: treat top-level as the metrics dict
        return data

    # -----------------------------------------------------------------------
    # Metric value loader
    # -----------------------------------------------------------------------

    def load_metric_value(self, threshold: ThresholdDefinition) -> Optional[float]:
        """
        Читает JSON по threshold.metric_path, извлекает числовое значение
        по ключу, соответствующему threshold.name.

        Логика извлечения ключа: _METRIC_KEYS[threshold.name].
        Если файл отсутствует, ключ не найден, значение не число → None.
        """
        data = self._safe_load_json(threshold.metric_path)
        if data is None:
            return None

        # Если данные — это список (ring-buffer без обёртки) → берём последний элемент
        if isinstance(data, list):
            if not data:
                return None
            data = data[-1]
            if not isinstance(data, dict):
                return None

        if not isinstance(data, dict):
            return None

        latest = self._extract_latest(data)

        # Найти нужный ключ по имени порога
        metric_key = self._METRIC_KEYS.get(threshold.name)
        if metric_key is None:
            log.debug("No metric key mapping for threshold '%s'", threshold.name)
            return None

        raw = latest.get(metric_key)
        if raw is None:
            log.debug(
                "Key '%s' not found in latest for threshold '%s'",
                metric_key, threshold.name,
            )
            return None

        # Проверить что это число (не bool)
        if isinstance(raw, bool):
            return None
        if isinstance(raw, (int, float)):
            return float(raw)

        # Попытаться распарсить строку
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    # -----------------------------------------------------------------------
    # Threshold evaluation
    # -----------------------------------------------------------------------

    def check_threshold(
        self, threshold: ThresholdDefinition
    ) -> Optional[AlertEvent]:
        """
        Загружает метрику, сравнивает с порогом, создаёт AlertEvent если нарушен.

        Операторы:
            lt  → triggered если value < threshold_value
            gt  → triggered если value > threshold_value
            lte → triggered если value <= threshold_value
            gte → triggered если value >= threshold_value

        Возвращает None если значение метрики недоступно.
        Возвращает AlertEvent(is_active=False) если порог НЕ нарушен.
        Возвращает AlertEvent(is_active=True) если порог нарушен.
        """
        value = self.load_metric_value(threshold)
        if value is None:
            return None

        op = threshold.operator
        tv = threshold.threshold_value

        if op == "lt":
            triggered = value < tv
        elif op == "gt":
            triggered = value > tv
        elif op == "lte":
            triggered = value <= tv
        elif op == "gte":
            triggered = value >= tv
        else:
            # Не должно происходить (валидация в ThresholdDefinition.__post_init__)
            return None

        message = threshold.message_template.format(
            value=value, threshold=tv
        )
        triggered_at = datetime.now(timezone.utc).isoformat()

        return AlertEvent(
            threshold_name=threshold.name,
            severity=threshold.severity,
            current_value=value,
            threshold_value=tv,
            message=message,
            triggered_at=triggered_at,
            is_active=triggered,
        )

    # -----------------------------------------------------------------------
    # Run all checks
    # -----------------------------------------------------------------------

    def run_all_checks(self) -> AlertReport:
        """
        Запускает check_threshold для каждого threshold.
        Собирает активные AlertEvent (is_active=True).
        all_clear = True если нет активных.
        """
        generated_at = datetime.now(timezone.utc).isoformat()
        active_events: List[AlertEvent] = []
        checked = 0

        for threshold in self._thresholds:
            event = self.check_threshold(threshold)
            checked += 1
            if event is not None and event.is_active:
                active_events.append(event)

        critical = sum(1 for e in active_events if e.severity == "CRITICAL")
        warning = sum(1 for e in active_events if e.severity == "WARNING")
        info = sum(1 for e in active_events if e.severity == "INFO")
        alerts_active = len(active_events)

        report = AlertReport(
            generated_at=generated_at,
            thresholds_checked=checked,
            alerts_active=alerts_active,
            critical_count=critical,
            warning_count=warning,
            info_count=info,
            events=active_events,
            all_clear=(alerts_active == 0),
        )
        return report

    # -----------------------------------------------------------------------
    # Save report
    # -----------------------------------------------------------------------

    def save_report(self, report: Optional[AlertReport] = None) -> str:
        """
        Сохраняет data/alert_report.json атомарно с ring-buffer 48.
        Если report не передан — вычисляет через run_all_checks().
        Возвращает строку пути к файлу.
        """
        if report is None:
            report = self.run_all_checks()

        out_path = self._data_dir / _OUTPUT_FILE

        # Загрузить существующий ring-buffer
        existing_snapshots: list = []
        try:
            with open(out_path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
            if isinstance(existing, dict):
                existing_snapshots = existing.get("snapshots", [])
                if not isinstance(existing_snapshots, list):
                    existing_snapshots = []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            existing_snapshots = []

        new_entry = report.to_dict()
        combined = existing_snapshots + [new_entry]
        if len(combined) > RING_BUFFER_MAX:
            combined = combined[-RING_BUFFER_MAX:]

        payload = {
            "schema_version": 1,
            "source": "alert_threshold_manager",
            "ring_buffer_max": RING_BUFFER_MAX,
            "snapshot_count": len(combined),
            "updated_at": report.generated_at,
            "latest": new_entry,
            "snapshots": combined,
        }

        _atomic_write_json(out_path, payload)
        log.info("Alert report saved to %s", out_path)
        return str(out_path)

    # -----------------------------------------------------------------------
    # Telegram formatter
    # -----------------------------------------------------------------------

    def format_telegram_message(
        self, report: Optional[AlertReport] = None
    ) -> str:
        """
        Форматирует ≤1500 символов Telegram-сообщение.

        🚨 Alert Report — 3 active alerts
        🔴 CRITICAL: T2 exposure 55% exceeds cap
        🟡 WARNING: APY 3.8% below threshold
        ℹ️ INFO: Rebalance moves available
        ✅ All clear (если нет алертов)
        """
        if report is None:
            report = self.run_all_checks()

        severity_emoji = {
            "CRITICAL": "🔴",
            "WARNING": "🟡",
            "INFO": "ℹ️",
        }

        ts = report.generated_at[:19]

        if report.all_clear:
            lines = [
                "✅ *Alert Report — All Clear*",
                f"Thresholds checked: {report.thresholds_checked}",
                f"_Generated: {ts} UTC_",
            ]
        else:
            lines = [
                f"🚨 *Alert Report — {report.alerts_active} active alert"
                f"{'s' if report.alerts_active != 1 else ''}*",
            ]
            if report.critical_count:
                lines.append(f"🔴 CRITICAL: {report.critical_count}")
            if report.warning_count:
                lines.append(f"🟡 WARNING: {report.warning_count}")
            if report.info_count:
                lines.append(f"ℹ️ INFO: {report.info_count}")
            lines.append("")

            for event in report.events:
                emoji = severity_emoji.get(event.severity, "❓")
                lines.append(f"{emoji} {event.message}")

            lines.append(f"\n_Generated: {ts} UTC_")

        msg = "\n".join(lines)
        if len(msg) > 1500:
            msg = msg[:1490] + "\n…"
        return msg

    # -----------------------------------------------------------------------
    # to_dict
    # -----------------------------------------------------------------------

    def to_dict(self, report: Optional[AlertReport] = None) -> dict:
        """Возвращает текущий отчёт как JSON-сериализуемый dict."""
        if report is None:
            report = self.run_all_checks()
        return report.to_dict()


# ===========================================================================
# CLI
# ===========================================================================

def _build_arg_parser():
    import argparse
    p = argparse.ArgumentParser(
        description="Alert Threshold Manager (MP-622)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--check", action="store_true",
        help="Compute and print report without saving (default)",
    )
    group.add_argument(
        "--run", action="store_true",
        help="Compute report AND save to data/alert_report.json",
    )
    group.add_argument(
        "--telegram", action="store_true",
        help="Print Telegram-formatted message",
    )
    p.add_argument(
        "--data-dir", default=None,
        help="Override path to data/ directory",
    )
    return p


def main(argv=None):
    import sys
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    manager = AlertThresholdManager(data_path=args.data_dir)

    try:
        if args.run:
            path = manager.save_report()
            report = manager.run_all_checks()
            print(f"✅ AlertThresholdManager saved → {path}")
            print(f"   thresholds_checked={report.thresholds_checked}")
            print(f"   alerts_active={report.alerts_active} "
                  f"(CRITICAL={report.critical_count}, "
                  f"WARNING={report.warning_count}, "
                  f"INFO={report.info_count})")
            print(f"   all_clear={report.all_clear}")
            print(f"   summary: {report.summary}")
        elif args.telegram:
            print(manager.format_telegram_message())
        else:  # --check (default)
            report = manager.run_all_checks()
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    except Exception as exc:
        log.error("AlertThresholdManager failed: %s", exc, exc_info=True)
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
