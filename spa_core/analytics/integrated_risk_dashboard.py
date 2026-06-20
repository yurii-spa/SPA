"""
Integrated Risk Dashboard — MP-605.

Агрегирует сигналы от всех модулей мониторинга в единый risk score.
Читает JSON из data/ директории — не вызывает мониторы напрямую.

Design constraints
------------------
* Pure stdlib — no external deps.
* Advisory only — never touches allocator / risk / execution.
* Atomic writes — tmp + os.replace on every JSON update.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* exit(0) always from CLI.

CLI
---
    python3 -m spa_core.analytics.integrated_risk_dashboard --check
    python3 -m spa_core.analytics.integrated_risk_dashboard --run
    python3 -m spa_core.analytics.integrated_risk_dashboard --telegram
    python3 -m spa_core.analytics.integrated_risk_dashboard --run --data-dir /path/to/data
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

log = logging.getLogger("spa.analytics.integrated_risk_dashboard")

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

# Data source filenames
_PEG_REPORT_FILE = "peg_report.json"
_WATCHDOG_HISTORY_FILE = "watchdog_history.json"
_CONCENTRATION_RISK_FILE = "concentration_risk.json"
_MOMENTUM_REPORT_FILE = "momentum_report.json"
_HEAT_MAP_FILE = "heat_map.json"
_OUTPUT_FILE = "integrated_risk.json"

# Ring buffer size
RING_BUFFER_MAX = 48

# Data freshness threshold in seconds (2 hours)
FRESHNESS_THRESHOLD_SECONDS = 7200


# ===========================================================================
# Dataclasses
# ===========================================================================

@dataclass
class RiskSignal:
    """Single risk signal from one monitoring source."""
    source: str          # "peg" / "watchdog" / "concentration" / "momentum"
    level: str           # "OK" / "INFO" / "WARNING" / "CRITICAL"
    score: float         # 0.0 (ok) → 1.0 (critical)
    summary: str         # краткое описание
    details: dict = field(default_factory=dict)  # raw данные из источника

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "level": self.level,
            "score": self.score,
            "summary": self.summary,
            "details": self.details,
        }


@dataclass
class IntegratedRiskAssessment:
    """Combined risk assessment across all monitoring sources."""
    generated_at: str
    overall_score: float         # 0.0–1.0: weighted avg of signals
    overall_level: str           # "GREEN" / "YELLOW" / "ORANGE" / "RED"
    signals: List[RiskSignal] = field(default_factory=list)
    critical_count: int = 0
    warning_count: int = 0
    top_risk: str = ""
    recommendations: List[str] = field(default_factory=list)
    data_freshness: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "overall_score": self.overall_score,
            "overall_level": self.overall_level,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "top_risk": self.top_risk,
            "recommendations": self.recommendations,
            "data_freshness": self.data_freshness,
            "signals": [s.to_dict() for s in self.signals],
        }


# ===========================================================================
# Atomic write helper
# ===========================================================================

def _atomic_write_json(path: Path, payload: object) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(payload, str(path))
class IntegratedRiskDashboard:
    """
    Aggregates risk signals from all monitoring modules into a single score.
    Reads JSON from data/ directory — does NOT call monitors directly.
    Advisory only — never modifies allocator/risk/execution.
    """

    # Weights for aggregation (must sum to 1.0)
    SIGNAL_WEIGHTS: Dict[str, float] = {
        "peg": 0.35,           # депег — самый критичный риск
        "concentration": 0.25, # smart contract concentration
        "watchdog": 0.25,      # overall adapter health
        "momentum": 0.15,      # APY trends (менее критично)
    }

    # Thresholds overall_score → overall_level
    SCORE_GREEN = 0.10    # < 0.10 → GREEN
    SCORE_YELLOW = 0.30   # < 0.30 → YELLOW
    SCORE_ORANGE = 0.55   # < 0.55 → ORANGE
    # >= 0.55 → RED

    def __init__(self, data_path: Optional[str] = None):
        self._data_dir = Path(data_path) if data_path else _DEFAULT_DATA_DIR

    # ------------------------------------------------------------------
    # JSON loading
    # ------------------------------------------------------------------

    def _safe_load_json(self, filename: str) -> Optional[dict]:
        """Читает JSON файл из data/, возвращает None при ошибке."""
        path = self._data_dir / filename
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            log.debug("File not found: %s", path)
            return None
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            log.warning("Failed to load %s: %s", path, exc)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _score_to_signal_level(self, score: float) -> str:
        """Convert numeric score to signal level string."""
        if score < 0.20:
            return "OK"
        elif score < 0.45:
            return "WARNING"
        else:
            return "CRITICAL"

    def _score_to_overall_level(self, score: float) -> str:
        """Map overall weighted score to traffic-light level."""
        if score < self.SCORE_GREEN:
            return "GREEN"
        elif score < self.SCORE_YELLOW:
            return "YELLOW"
        elif score < self.SCORE_ORANGE:
            return "ORANGE"
        else:
            return "RED"

    def _get_file_timestamp(self, filename: str, data: Optional[dict]) -> Optional[str]:
        """Extract timestamp from loaded data dict, trying common field names."""
        if data is None:
            return None
        for ts_field in ("generated_at", "updated_at", "last_updated", "timestamp"):
            val = data.get(ts_field)
            if val:
                return str(val)
        return None

    # ------------------------------------------------------------------
    # Signal readers
    # ------------------------------------------------------------------

    def _read_peg_signal(self) -> RiskSignal:
        """
        Reads data/peg_report.json.
        overall_status="RED" → score=0.9, "YELLOW" → 0.5, "GREEN" → 0.0
        Missing file → score=0.3 (unknown, better safe than sorry)
        """
        data = self._safe_load_json(_PEG_REPORT_FILE)
        if data is None:
            return RiskSignal(
                source="peg",
                level="WARNING",
                score=0.3,
                summary="Peg report unavailable — unknown peg status",
                details={"file": _PEG_REPORT_FILE, "status": "MISSING"},
            )

        overall_status = data.get("overall_status", "GREEN")
        critical = data.get("critical", 0)
        warning_cnt = data.get("warning", 0)
        caution = data.get("caution", 0)
        total = data.get("total_monitored", 0)
        worst_adapter = data.get("worst_adapter", "")
        worst_dev = data.get("worst_deviation_pct", 0.0)

        if overall_status == "RED":
            score = 0.9
            level = "CRITICAL"
            summary = (
                f"DEPEG ALERT: {critical} critical depeg(s) detected "
                f"out of {total} adapters"
            )
        elif overall_status == "YELLOW":
            score = 0.5
            level = "WARNING"
            summary = (
                f"Peg caution: {warning_cnt} warning, "
                f"{caution} caution out of {total} adapters"
            )
        else:  # GREEN
            score = 0.0
            level = "OK"
            summary = f"All {total} adapters stable (peg OK)"

        return RiskSignal(
            source="peg",
            level=level,
            score=score,
            summary=summary,
            details={
                "overall_status": overall_status,
                "total_monitored": total,
                "critical": critical,
                "warning": warning_cnt,
                "caution": caution,
                "worst_adapter": worst_adapter,
                "worst_deviation_pct": worst_dev,
            },
        )

    def _read_concentration_signal(self) -> RiskSignal:
        """
        Reads data/concentration_risk.json.
        overall_risk="HIGH" → 0.7, "MEDIUM" → 0.4, "LOW" → 0.1, missing → 0.3
        """
        data = self._safe_load_json(_CONCENTRATION_RISK_FILE)
        if data is None:
            return RiskSignal(
                source="concentration",
                level="WARNING",
                score=0.3,
                summary="Concentration risk report unavailable",
                details={"file": _CONCENTRATION_RISK_FILE, "status": "MISSING"},
            )

        # Support both top-level and nested under "latest"
        latest = data.get("latest") if isinstance(data.get("latest"), dict) else data
        overall_risk = latest.get("overall_risk", "LOW")

        if overall_risk == "HIGH":
            score = 0.7
            level = "CRITICAL"
        elif overall_risk == "MEDIUM":
            score = 0.4
            level = "WARNING"
        else:  # LOW or unknown
            score = 0.1
            level = "OK"

        top_protocol = latest.get("top_protocol", "unknown")
        top_weight = latest.get("top_protocol_weight_pct", 0.0)
        total_protocols = latest.get("total_protocols", 0)
        warnings = latest.get("warnings", [])

        summary = (
            f"Concentration risk {overall_risk}: "
            f"top={top_protocol} ({top_weight:.1f}%), "
            f"{total_protocols} protocols"
        )
        if warnings:
            summary += f"; {len(warnings)} warning(s)"

        return RiskSignal(
            source="concentration",
            level=level,
            score=score,
            summary=summary,
            details={
                "overall_risk": overall_risk,
                "top_protocol": top_protocol,
                "top_protocol_weight_pct": top_weight,
                "total_protocols": total_protocols,
                "warnings": warnings,
            },
        )

    def _read_watchdog_signal(self) -> RiskSignal:
        """
        Reads the latest snapshot from data/watchdog_history.json.
        CRITICAL adapters → score > 0.7.
        Formula: score = (critical*0.9 + warning*0.4) / max(total, 1)
        Missing or empty latest → score=0.3 (unknown)
        """
        data = self._safe_load_json(_WATCHDOG_HISTORY_FILE)
        if data is None:
            return RiskSignal(
                source="watchdog",
                level="WARNING",
                score=0.3,
                summary="Watchdog history unavailable",
                details={"file": _WATCHDOG_HISTORY_FILE, "status": "MISSING"},
            )

        latest = data.get("latest", {})
        if not latest:
            return RiskSignal(
                source="watchdog",
                level="INFO",
                score=0.3,
                summary="No watchdog snapshot yet — adapter health unknown",
                details={"snapshot_count": data.get("snapshot_count", 0)},
            )

        total = latest.get("total_adapters", 0)
        critical = latest.get("critical", 0)
        warning_cnt = latest.get("warning", 0)
        healthy = latest.get("healthy", 0)

        raw_score = (critical * 0.9 + warning_cnt * 0.4) / max(total, 1)
        score = round(min(raw_score, 1.0), 6)
        level = self._score_to_signal_level(score)

        summary = (
            f"Adapter health: {healthy}/{total} healthy, "
            f"{warning_cnt} warning, {critical} critical"
        )

        return RiskSignal(
            source="watchdog",
            level=level,
            score=score,
            summary=summary,
            details={
                "total_adapters": total,
                "healthy": healthy,
                "warning": warning_cnt,
                "critical": critical,
                "generated_at": latest.get("generated_at", ""),
            },
        )

    def _read_momentum_signal(self) -> RiskSignal:
        """
        Reads data/momentum_report.json.
        High proportion of FALLING adapters → elevated score.
        score = (falling / max(total, 1)) * 0.6
        Missing → score=0.15
        """
        data = self._safe_load_json(_MOMENTUM_REPORT_FILE)
        if data is None:
            return RiskSignal(
                source="momentum",
                level="OK",
                score=0.15,
                summary="Momentum report unavailable — APY trend unknown",
                details={"file": _MOMENTUM_REPORT_FILE, "status": "MISSING"},
            )

        latest = data.get("latest", {})
        if not latest:
            return RiskSignal(
                source="momentum",
                level="OK",
                score=0.15,
                summary="No momentum snapshot yet",
                details={"snapshot_count": data.get("snapshot_count", 0)},
            )

        total = latest.get("total_adapters", 0)
        falling = latest.get("falling", 0)
        rising = latest.get("rising", 0)
        stable = latest.get("stable", 0)
        unknown = latest.get("unknown", 0)

        raw_score = (falling / max(total, 1)) * 0.6
        score = round(min(raw_score, 1.0), 6)
        level = self._score_to_signal_level(score)

        top_falling = latest.get("top_falling", [])
        top_rising = latest.get("top_rising", [])

        summary = (
            f"APY momentum: {rising} rising, {stable} stable, "
            f"{falling} falling, {unknown} unknown of {total}"
        )
        if top_falling:
            names = []
            for item in top_falling[:2]:
                if isinstance(item, dict):
                    names.append(item.get("adapter_id", "?"))
                else:
                    names.append(str(item))
            summary += f"; falling: {', '.join(names)}"

        # Normalise top_falling / top_rising to list of adapter_id strings
        def _extract_ids(items: list) -> list:
            result = []
            for item in items:
                if isinstance(item, dict):
                    result.append(item.get("adapter_id", "?"))
                else:
                    result.append(str(item))
            return result

        return RiskSignal(
            source="momentum",
            level=level,
            score=score,
            summary=summary,
            details={
                "total_adapters": total,
                "rising": rising,
                "stable": stable,
                "falling": falling,
                "unknown": unknown,
                "top_falling": _extract_ids(top_falling),
                "top_rising": _extract_ids(top_rising),
            },
        )

    # ------------------------------------------------------------------
    # Freshness check
    # ------------------------------------------------------------------

    def _check_data_freshness(self) -> dict:
        """
        Для каждого JSON файла читает generated_at/timestamp.
        Возвращает {source: "OK" / "STALE_Xh" / "MISSING"}.
        STALE если > 2 часов.
        """
        files = {
            "peg": _PEG_REPORT_FILE,
            "watchdog": _WATCHDOG_HISTORY_FILE,
            "concentration": _CONCENTRATION_RISK_FILE,
            "momentum": _MOMENTUM_REPORT_FILE,
        }
        now = datetime.now(timezone.utc)
        result: dict = {}

        for source, filename in files.items():
            data = self._safe_load_json(filename)
            if data is None:
                result[source] = "MISSING"
                continue

            ts_str = self._get_file_timestamp(filename, data)
            if ts_str is None:
                result[source] = "OK"  # file exists but no timestamp — assume fresh
                continue

            try:
                ts_str_clean = ts_str.replace("Z", "+00:00")
                ts = datetime.fromisoformat(ts_str_clean)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_seconds = (now - ts).total_seconds()
                if age_seconds > FRESHNESS_THRESHOLD_SECONDS:
                    age_hours = age_seconds / 3600
                    result[source] = f"STALE_{age_hours:.1f}h"
                else:
                    result[source] = "OK"
            except (ValueError, TypeError):
                result[source] = "OK"

        return result

    # ------------------------------------------------------------------
    # Recommendations & top risk
    # ------------------------------------------------------------------

    def _build_recommendations(self, signals: List[RiskSignal]) -> List[str]:
        """Generate actionable recommendations based on signals."""
        recs: List[str] = []
        signal_map = {s.source: s for s in signals}

        peg = signal_map.get("peg")
        if peg and peg.level == "CRITICAL":
            worst = peg.details.get("worst_adapter", "unknown")
            recs.append(
                f"EMERGENCY: halt new deposits — depeg detected on {worst}"
            )
        elif peg and peg.level == "WARNING":
            recs.append(
                "Monitor peg stability closely — consider reducing stablecoin exposure"
            )

        conc = signal_map.get("concentration")
        if conc and conc.level == "CRITICAL":
            proto = conc.details.get("top_protocol", "unknown")
            weight = conc.details.get("top_protocol_weight_pct", 0.0)
            recs.append(
                f"Reduce {proto} exposure below 35% (currently {weight:.1f}%)"
            )
        elif conc and conc.level == "WARNING":
            proto = conc.details.get("top_protocol", "unknown")
            recs.append(
                f"Review concentration in {proto} — consider diversifying"
            )

        wdog = signal_map.get("watchdog")
        if wdog and wdog.level == "CRITICAL":
            recs.append(
                "Check adapter health immediately — critical adapters detected"
            )
        elif wdog and wdog.level == "WARNING":
            recs.append(
                "Investigate flagged adapters — degraded health signals"
            )

        mom = signal_map.get("momentum")
        if mom and mom.level == "CRITICAL":
            falling = mom.details.get("top_falling", [])
            if falling:
                recs.append(
                    f"APY falling on {', '.join(falling[:2])} — consider rebalancing"
                )
            else:
                recs.append(
                    "Multiple adapters showing falling APY — review allocation"
                )
        elif mom and mom.level == "WARNING":
            recs.append(
                "Some adapters showing declining APY trend — monitor closely"
            )

        if not recs:
            recs.append("All risk signals normal — no action required")

        return recs

    def _find_top_risk(self, signals: List[RiskSignal]) -> str:
        """Find the most critical signal's summary as the top risk description."""
        critical_signals = [s for s in signals if s.level == "CRITICAL"]
        warning_signals = [s for s in signals if s.level == "WARNING"]

        if critical_signals:
            top = max(critical_signals, key=lambda s: s.score)
            return top.summary
        elif warning_signals:
            top = max(warning_signals, key=lambda s: s.score)
            return top.summary
        elif signals:
            return "All systems normal"
        return "No signals available"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assess(self) -> IntegratedRiskAssessment:
        """
        Reads all signals, computes weighted score, generates assessment.
        Pure read — no file writes.
        """
        signals = [
            self._read_peg_signal(),
            self._read_concentration_signal(),
            self._read_watchdog_signal(),
            self._read_momentum_signal(),
        ]

        overall_score = 0.0
        for sig in signals:
            weight = self.SIGNAL_WEIGHTS.get(sig.source, 0.0)
            overall_score += sig.score * weight

        overall_score = round(min(overall_score, 1.0), 6)
        overall_level = self._score_to_overall_level(overall_score)

        critical_count = sum(1 for s in signals if s.level == "CRITICAL")
        warning_count = sum(1 for s in signals if s.level == "WARNING")

        top_risk = self._find_top_risk(signals)
        recommendations = self._build_recommendations(signals)
        data_freshness = self._check_data_freshness()

        return IntegratedRiskAssessment(
            generated_at=datetime.now(timezone.utc).isoformat(),
            overall_score=overall_score,
            overall_level=overall_level,
            signals=signals,
            critical_count=critical_count,
            warning_count=warning_count,
            top_risk=top_risk,
            recommendations=recommendations,
            data_freshness=data_freshness,
        )

    def save_assessment(self, output_path: Optional[str] = None) -> str:
        """
        Saves data/integrated_risk.json atomically with ring-buffer of 48.
        Returns the path written.
        """
        assessment = self.assess()
        out_path = (
            Path(output_path) if output_path
            else (self._data_dir / _OUTPUT_FILE)
        )

        # Load existing ring-buffer
        existing: Optional[dict] = None
        try:
            with open(out_path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            existing = None

        snapshots: list = []
        if existing and isinstance(existing, dict):
            snapshots = existing.get("snapshots", [])

        snapshots.append(assessment.to_dict())
        # Trim ring buffer
        if len(snapshots) > RING_BUFFER_MAX:
            snapshots = snapshots[-RING_BUFFER_MAX:]

        payload = {
            "schema_version": 1,
            "source": "integrated_risk_dashboard",
            "ring_buffer_max": RING_BUFFER_MAX,
            "snapshot_count": len(snapshots),
            "updated_at": assessment.generated_at,
            "latest": assessment.to_dict(),
            "snapshots": snapshots,
        }

        _atomic_write_json(out_path, payload)
        log.info("Integrated risk assessment saved to %s", out_path)
        return str(out_path)

    def to_dict(self) -> dict:
        """Returns current assessment as dict."""
        return self.assess().to_dict()

    def format_telegram_message(self) -> str:
        """
        ≤2000 chars, emoji 🟢🟡🟠🔴 по уровню, топ-риски, recommendations.
        """
        assessment = self.assess()

        emoji_map = {
            "GREEN": "🟢",
            "YELLOW": "🟡",
            "ORANGE": "🟠",
            "RED": "🔴",
        }
        emoji = emoji_map.get(assessment.overall_level, "⚪")

        lines = [
            f"{emoji} *SPA Integrated Risk Dashboard*",
            f"Level: *{assessment.overall_level}* | Score: {assessment.overall_score:.3f}",
            f"Critical: {assessment.critical_count} | Warnings: {assessment.warning_count}",
            "",
            f"*Top Risk:* {assessment.top_risk}",
            "",
            "*Signals:*",
        ]

        level_emoji = {
            "OK": "✅",
            "INFO": "ℹ️",
            "WARNING": "⚠️",
            "CRITICAL": "🚨",
        }
        for sig in assessment.signals:
            sig_emoji = level_emoji.get(sig.level, "❓")
            lines.append(f"  {sig_emoji} [{sig.source.upper()}] {sig.summary}")

        lines.append("")
        lines.append("*Recommendations:*")
        for rec in assessment.recommendations[:3]:
            lines.append(f"  • {rec}")

        lines.append(f"\n_Generated: {assessment.generated_at[:19]} UTC_")

        msg = "\n".join(lines)
        if len(msg) > 2000:
            msg = msg[:1990] + "\n…"
        return msg


# ===========================================================================
# CLI
# ===========================================================================

def _build_arg_parser():
    import argparse
    p = argparse.ArgumentParser(
        description="Integrated Risk Dashboard (MP-605)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--check", action="store_true",
        help="Compute and print assessment without saving (default)",
    )
    group.add_argument(
        "--run", action="store_true",
        help="Compute assessment AND save to data/integrated_risk.json",
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

    dashboard = IntegratedRiskDashboard(data_path=args.data_dir)

    try:
        if args.run:
            path = dashboard.save_assessment()
            assessment = dashboard.assess()
            print(f"✅ IntegratedRiskDashboard saved → {path}")
            print(
                f"   overall_level={assessment.overall_level} "
                f"score={assessment.overall_score:.4f}"
            )
            print(
                f"   critical={assessment.critical_count} "
                f"warning={assessment.warning_count}"
            )
        elif args.telegram:
            print(dashboard.format_telegram_message())
        else:  # --check (default)
            assessment = dashboard.assess()
            print(json.dumps(assessment.to_dict(), indent=2, ensure_ascii=False))
    except Exception as exc:
        log.error("IntegratedRiskDashboard failed: %s", exc, exc_info=True)
        import sys as _sys
        print(f"ERROR: {exc}", file=_sys.stderr)
        _sys.exit(1)

    import sys as _sys
    _sys.exit(0)


if __name__ == "__main__":
    main()
