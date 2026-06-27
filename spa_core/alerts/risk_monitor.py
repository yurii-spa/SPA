"""
SPA Risk Monitor — immediate Telegram alerts for threshold breaches.

Runs on every GitHub Actions cycle (every 4h). Unlike the daily digest,
these alerts fire immediately whenever a limit is crossed.

Thresholds:
  • Concentration: any position > 45% of portfolio
  • Daily drawdown: PnL drop > 2% vs previous day's capital
  • APY drop: any position APY falls > 1 pp vs last recorded snapshot
  • Cash buffer: cash < 3% of total capital

Usage (called from export_data.py):
    monitor = RiskMonitor(data_dir=OUTPUT_DIR)
    alerts = monitor.check_and_alert(portfolio_status, pnl_history, sender)

Module layout (P3-6 refactor):
    • ``RiskMonitor`` here keeps the orchestrator + PORTFOLIO-risk checks
      (concentration / drawdown / APY-drop / cash) + the pipeline-failure
      alert + the prev-APY persistence helpers.
    • The APY-FEED-HEALTH monitor family (covariance / stale / protocol-drop /
      tvl-drop / per-protocol anomaly / schema-drift / value-bounds /
      date-monotonicity / per-protocol-stale) lives in
      ``spa_core/alerts/apy_feed_monitors.py`` behind a shared
      ``FeedHealthAlert`` base. ``RiskMonitor.alert_apy_feed_*`` /
      ``alert_covariance_degraded`` here are thin delegations to those, so the
      public method names + the ``from alerts.risk_monitor import …`` surface
      are unchanged. All threshold constants are re-exported from this module
      verbatim.
"""

from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import Optional

# Re-export every threshold constant + the FeedHealthAlert base from the
# extracted module so existing `from alerts.risk_monitor import <CONST>` and
# `from alerts.risk_monitor import …` imports (the ~10 test files + export_data)
# keep working byte-for-byte.
from alerts.apy_feed_monitors import (  # noqa: F401
    FeedHealthAlert,
    CovarianceHealthAlert,
    ApyFeedStaleAlert,
    ApyFeedProtocolDropAlert,
    ApyFeedTvlDropAlert,
    ApyFeedProtocolAnomalyAlert,
    ApyFeedSchemaDriftAlert,
    ApyFeedValueBoundsAlert,
    ApyFeedDateMonotonicityAlert,
    ApyFeedProtocolStaleAlert,
    COVARIANCE_DEGRADED_CYCLES_ALERT,
    APY_FEED_MAX_AGE_HOURS,
    APY_FEED_STALE_CYCLES_ALERT,
    APY_FEED_PROTOCOL_DROP_PCT,
    APY_FEED_MIN_PROTOCOLS,
    APY_FEED_TVL_DROP_PCT,
    APY_FEED_MIN_TVL_USD,
    APY_FEED_PROTOCOL_APY_DROP_PCT,
    APY_FEED_PROTOCOL_TVL_DROP_PCT,
    APY_FEED_REQUIRED_FIELDS,
    APY_FEED_SCHEMA_MAX_BAD_PCT,
    APY_FEED_SCHEMA_MIN_PROTOCOLS,
    APY_FEED_PROTOCOL_MAX_AGE_HOURS,
    APY_FEED_KNOWN_FIELDS,
    APY_FEED_APY_MIN,
    APY_FEED_APY_MAX,
    APY_FEED_TVL_MIN,
    APY_FEED_TVL_MAX,
    APY_FEED_BOUNDS_MAX_BAD_PCT,
    APY_FEED_BOUNDS_MIN_PROTOCOLS,
    APY_FEED_MAX_DATE_GAP_HOURS,
    APY_FEED_MONO_MAX_BAD_PCT,
    APY_FEED_MONO_MIN_PROTOCOLS,
)

log = logging.getLogger("spa.alerts.risk_monitor")

# ──────────────────────────────────────────────────────────────────────────
# Portfolio-risk thresholds (owner-tunable). These are ADVISORY Telegram-alert
# thresholds — NOT the hard RiskPolicy gate (spa_core/risk/policy.py caps
# per-protocol concentration at 40% T1 / 20% T2 and CANNOT be overridden here).
# OWNER DECISION 2026-06-27: tighten the concentration ALERT from 45% → 30% to
# match the stricter RiskPolicy intent (stricter = safer). The hard cap in
# policy.py is unchanged; this only makes the monitor warn/alert earlier.
# ──────────────────────────────────────────────────────────────────────────
CONCENTRATION_CRITICAL_PCT = 30.0    # OWNER DECISION 2026-06-27: advisory alert tightened 45% → 30%
CONCENTRATION_WARNING_PCT  = 25.0    # warning tier kept below the 30% critical (was 35%)
DAILY_DRAWDOWN_PCT         = 2.0     # single-day drop that triggers alert
APY_DROP_THRESHOLD         = 1.0     # pp drop vs last snapshot
CASH_BUFFER_MIN_PCT        = 3.0


class RiskMonitor:
    """
    Stateless risk checker that compares current portfolio state against
    thresholds and fires Telegram alerts for any breach detected.

    The APY-drop check uses a small persistence file (.prev_position_apys.json)
    so it can compare against the previous run.
    """

    def __init__(self, data_dir: Optional[str | Path] = None) -> None:
        if data_dir is None:
            data_dir = Path(__file__).parent.parent.parent / "data"
        self.data_dir = Path(data_dir)
        self._prev_apys_file = self.data_dir / ".prev_position_apys.json"
        # APY-feed-health monitors (extracted). Each owns its own state file.
        self._covariance_alert = CovarianceHealthAlert(self.data_dir)
        self._apy_feed_stale_alert = ApyFeedStaleAlert(self.data_dir)
        self._apy_feed_protocol_drop_alert = ApyFeedProtocolDropAlert(self.data_dir)
        self._apy_feed_tvl_drop_alert = ApyFeedTvlDropAlert(self.data_dir)
        self._apy_feed_anomaly_alert = ApyFeedProtocolAnomalyAlert(self.data_dir)
        self._apy_feed_schema_alert = ApyFeedSchemaDriftAlert(self.data_dir)
        self._apy_feed_bounds_alert = ApyFeedValueBoundsAlert(self.data_dir)
        self._apy_feed_monotonicity_alert = ApyFeedDateMonotonicityAlert(self.data_dir)
        self._apy_feed_protocol_stale_alert = ApyFeedProtocolStaleAlert(self.data_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_and_alert(
        self,
        portfolio_status: dict,
        pnl_history: list[dict],
        sender,
    ) -> list[dict]:
        """
        Run all risk checks. Fire a Telegram alert for every breach found.
        Returns the list of alert dicts that were generated (empty = all clear).

        Args:
            portfolio_status: dict with keys ``portfolio`` and ``positions``
                              (same shape as data/status.json).
            pnl_history:      list of strategy_state records (oldest first),
                              same shape as data/pnl_history.json.
            sender:           TelegramSender instance (send() called if alerts found).
        """
        alerts: list[dict] = []

        portfolio = portfolio_status.get("portfolio", portfolio_status)
        positions = portfolio_status.get("positions", [])

        alerts.extend(self._check_concentration(portfolio, positions))
        alerts.extend(self._check_daily_drawdown(pnl_history))
        alerts.extend(self._check_apy_drops(positions))
        alerts.extend(self._check_cash_buffer(portfolio))

        if alerts:
            self._fire_alert(alerts, portfolio, sender)

        # Always persist current APYs for next-run comparison
        self._save_current_apys(positions)

        return alerts

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_concentration(
        self, portfolio: dict, positions: list[dict]
    ) -> list[dict]:
        """Flag any position whose allocation exceeds the concentration limit."""
        total = portfolio.get("total_capital_usd", 0.0) or 0.0
        if total <= 0:
            return []

        alerts = []
        for pos in positions:
            amt = pos.get("amount_usd") or pos.get("entry_value_usd") or 0.0
            pct = amt / total * 100
            protocol = pos.get("protocol_key") or pos.get("protocol", "?")

            if pct > CONCENTRATION_CRITICAL_PCT:
                alerts.append({
                    "severity": "critical",
                    "type": "concentration",
                    "protocol": protocol,
                    "message": (
                        f"Position concentration {pct:.1f}% "
                        f"exceeds {CONCENTRATION_CRITICAL_PCT:.0f}% limit"
                    ),
                    "pct": round(pct, 2),
                    "amount_usd": amt,
                })
            elif pct > CONCENTRATION_WARNING_PCT:
                alerts.append({
                    "severity": "warning",
                    "type": "concentration",
                    "protocol": protocol,
                    "message": (
                        f"Position concentration {pct:.1f}% "
                        f"approaching {CONCENTRATION_CRITICAL_PCT:.0f}% limit"
                    ),
                    "pct": round(pct, 2),
                    "amount_usd": amt,
                })

        return alerts

    def _check_daily_drawdown(self, pnl_history: list[dict]) -> list[dict]:
        """
        Alert if the most recent day's capital dropped > DAILY_DRAWDOWN_PCT
        compared to the previous day's capital.
        """
        if not pnl_history or len(pnl_history) < 2:
            return []

        # pnl_history is oldest-first; get the last two distinct calendar days
        daily: dict[str, float] = {}
        for rec in pnl_history:
            ts   = rec.get("timestamp", "")
            cap  = rec.get("total_capital_usd") or 0.0
            day  = str(ts)[:10]
            if day:
                daily[day] = cap   # keep last value for each day

        dates = sorted(daily.keys())
        if len(dates) < 2:
            return []

        prev_cap = daily[dates[-2]]
        curr_cap = daily[dates[-1]]

        if prev_cap <= 0:
            return []

        change_pct = (curr_cap - prev_cap) / prev_cap * 100
        if change_pct < -DAILY_DRAWDOWN_PCT:
            return [{
                "severity": "critical",
                "type": "daily_drawdown",
                "protocol": "portfolio",
                "message": (
                    f"Daily PnL drop {change_pct:.2f}% "
                    f"exceeds -{DAILY_DRAWDOWN_PCT:.1f}% threshold"
                ),
                "pct": round(change_pct, 2),
                "prev_capital": prev_cap,
                "curr_capital": curr_cap,
            }]

        return []

    def _check_apy_drops(self, positions: list[dict]) -> list[dict]:
        """
        Compare current position APYs against the last persisted snapshot.
        Alert if any position APY dropped > APY_DROP_THRESHOLD pp.
        """
        prev_apys = self._load_prev_apys()
        if not prev_apys:
            return []   # first run — nothing to compare

        alerts = []
        for pos in positions:
            protocol = pos.get("protocol_key") or pos.get("protocol", "?")
            curr_apy = pos.get("current_apy")
            if curr_apy is None:
                continue
            prev_apy = prev_apys.get(protocol)
            if prev_apy is None:
                continue

            drop = prev_apy - curr_apy
            if drop > APY_DROP_THRESHOLD:
                alerts.append({
                    "severity": "warning",
                    "type": "apy_drop",
                    "protocol": protocol,
                    "message": (
                        f"APY dropped {drop:.2f}pp "
                        f"({prev_apy:.2f}% → {curr_apy:.2f}%)"
                    ),
                    "prev_apy": round(prev_apy, 4),
                    "curr_apy": round(curr_apy, 4),
                    "drop_pp": round(drop, 4),
                })

        return alerts

    def _check_cash_buffer(self, portfolio: dict) -> list[dict]:
        """Alert if cash reserves fall below the minimum buffer percentage."""
        total = portfolio.get("total_capital_usd", 0.0) or 0.0
        cash  = portfolio.get("cash_usd", 0.0) or 0.0
        if total <= 0:
            return []

        cash_pct = cash / total * 100
        if cash_pct < CASH_BUFFER_MIN_PCT:
            return [{
                "severity": "warning",
                "type": "low_cash",
                "protocol": "portfolio",
                "message": (
                    f"Cash buffer {cash_pct:.1f}% "
                    f"below {CASH_BUFFER_MIN_PCT:.0f}% minimum"
                ),
                "pct": round(cash_pct, 2),
                "cash_usd": cash,
            }]

        return []

    # ------------------------------------------------------------------
    # Alert dispatch
    # ------------------------------------------------------------------

    def _fire_alert(
        self, alerts: list[dict], portfolio: dict, sender
    ) -> None:
        """Send a Telegram risk alert; swallows all errors."""
        try:
            sent = sender.send_risk_alert(alerts, portfolio)
            log.info(
                f"RiskMonitor: fired {len(alerts)} alert(s) via Telegram "
                f"({'sent' if sent else 'failed/not configured'})"
            )
        except Exception as exc:
            log.error(f"RiskMonitor._fire_alert: {exc}")

    # ------------------------------------------------------------------
    # Pipeline failure alert
    # ------------------------------------------------------------------

    def alert_pipeline_failure(self, health: dict, sender=None) -> bool:
        """
        Send a Telegram alert if the pipeline health indicates serious problems.

        Fires when:
          • sections_failed > 2, OR
          • total_pools_fetched == 0

        Args:
            health:  pipeline_health dict (same schema as data/pipeline_health.json).
            sender:  TelegramSender instance. If None, tries to instantiate one.

        Returns:
            True if an alert was sent, False otherwise.
        """
        sections_failed   = health.get("sections_failed", 0)
        total_pools       = health.get("total_pools_fetched", 0)
        sections_run      = health.get("sections_run", 0)
        failed_sections   = health.get("failed_sections", [])
        timestamp         = health.get("timestamp", "")

        should_alert = sections_failed > 2 or total_pools == 0
        if not should_alert:
            log.info(
                f"alert_pipeline_failure: no alert needed "
                f"(failed={sections_failed}, pools={total_pools})"
            )
            return False

        # Format time for display
        try:
            from datetime import datetime
            ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            ts_display = ts.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            ts_display = timestamp[:16] if timestamp else "unknown"

        failed_list = ", ".join(failed_sections) if failed_sections else "none listed"
        msg = (
            f"🚨 <b>SPA Pipeline Issue</b>\n\n"
            f"⚠️ {sections_failed}/{sections_run} sections failed\n"
            f"📊 Pools fetched: {total_pools}\n"
            f"🕒 {ts_display}\n\n"
            f"Failed: {failed_list}\n"
            f"Action: Check GitHub Actions logs"
        )

        if sender is None:
            try:
                from alerts.telegram_sender import TelegramSender
                sender = TelegramSender()
            except Exception as exc:
                log.error(f"alert_pipeline_failure: could not create TelegramSender — {exc}")
                return False

        try:
            ok = sender.send(msg)
            log.info(
                f"alert_pipeline_failure: alert {'sent' if ok else 'failed'} "
                f"(failed={sections_failed}, pools={total_pools})"
            )
            return bool(ok)
        except Exception as exc:
            log.error(f"alert_pipeline_failure: send error — {exc}")
            return False

    # ------------------------------------------------------------------
    # APY-feed / covariance health alerts (delegated to FeedHealthAlert family)
    #
    # These thin wrappers keep the historic public method names + signatures so
    # the ~10 risk_monitor test files and export_data continue to call
    # ``RiskMonitor.alert_*`` unchanged. The behaviour (state files, fired
    # messages, return values) lives in spa_core/alerts/apy_feed_monitors.py.
    # ------------------------------------------------------------------

    def alert_covariance_degraded(
        self, cov_source, sender=None, *, section_failed: bool = False
    ) -> bool:
        return self._covariance_alert.run(
            cov_source, sender=sender, section_failed=section_failed
        )

    def alert_apy_feed_stale(
        self,
        feed_path=None,
        *,
        generated_at=None,
        data_source=None,
        now=None,
        sender=None,
    ) -> bool:
        return self._apy_feed_stale_alert.run(
            feed_path,
            generated_at=generated_at,
            data_source=data_source,
            now=now,
            sender=sender,
        )

    def alert_apy_feed_protocol_drop(
        self,
        feed_path=None,
        *,
        num_protocols=None,
        now=None,
        sender=None,
    ) -> bool:
        return self._apy_feed_protocol_drop_alert.run(
            feed_path, num_protocols=num_protocols, now=now, sender=sender
        )

    def alert_apy_feed_tvl_drop(
        self,
        feed_path=None,
        *,
        total_tvl_usd=None,
        now=None,
        sender=None,
    ) -> bool:
        return self._apy_feed_tvl_drop_alert.run(
            feed_path, total_tvl_usd=total_tvl_usd, now=now, sender=sender
        )

    def alert_apy_feed_protocol_anomaly(
        self,
        feed_path=None,
        *,
        snapshot=None,
        now=None,
        sender=None,
    ) -> bool:
        return self._apy_feed_anomaly_alert.run(
            feed_path, snapshot=snapshot, now=now, sender=sender
        )

    def alert_apy_feed_schema_drift(
        self,
        feed_path=None,
        *,
        records=None,
        now=None,
        sender=None,
    ) -> bool:
        return self._apy_feed_schema_alert.run(
            feed_path, records=records, now=now, sender=sender
        )

    def alert_apy_feed_value_bounds(
        self,
        feed_path=None,
        *,
        records=None,
        now=None,
        sender=None,
    ) -> bool:
        return self._apy_feed_bounds_alert.run(
            feed_path, records=records, now=now, sender=sender
        )

    def alert_apy_feed_date_monotonicity(
        self,
        feed_path=None,
        *,
        snapshot=None,
        now=None,
        sender=None,
    ) -> bool:
        return self._apy_feed_monotonicity_alert.run(
            feed_path, snapshot=snapshot, now=now, sender=sender
        )

    def alert_apy_feed_protocol_stale(
        self,
        feed_path=None,
        *,
        snapshot=None,
        now=None,
        sender=None,
    ) -> bool:
        return self._apy_feed_protocol_stale_alert.run(
            feed_path, snapshot=snapshot, now=now, sender=sender
        )

    # ------------------------------------------------------------------
    # State-file load/write helpers — preserved as thin delegations so any
    # caller / test that pokes the historic private method names still works.
    # ------------------------------------------------------------------

    def _load_covariance_health_state(self) -> dict:
        return self._covariance_alert.load_state()

    def _write_covariance_health_state(self, state: dict) -> None:
        self._covariance_alert.write_state(state)

    def _load_apy_feed_health_state(self) -> dict:
        return self._apy_feed_stale_alert.load_state()

    def _write_apy_feed_health_state(self, state: dict) -> None:
        self._apy_feed_stale_alert.write_state(state)

    def _load_apy_feed_protocol_health_state(self) -> dict:
        return self._apy_feed_protocol_drop_alert.load_state()

    def _write_apy_feed_protocol_health_state(self, state: dict) -> None:
        self._apy_feed_protocol_drop_alert.write_state(state)

    def _load_apy_feed_tvl_health_state(self) -> dict:
        return self._apy_feed_tvl_drop_alert.load_state()

    def _write_apy_feed_tvl_health_state(self, state: dict) -> None:
        self._apy_feed_tvl_drop_alert.write_state(state)

    def _load_apy_feed_anomaly_health_state(self) -> dict:
        return self._apy_feed_anomaly_alert.load_state()

    def _write_apy_feed_anomaly_health_state(self, state: dict) -> None:
        self._apy_feed_anomaly_alert.write_state(state)

    def _load_apy_feed_schema_health_state(self) -> dict:
        return self._apy_feed_schema_alert.load_state()

    def _write_apy_feed_schema_health_state(self, state: dict) -> None:
        self._apy_feed_schema_alert.write_state(state)

    def _load_apy_feed_bounds_health_state(self) -> dict:
        return self._apy_feed_bounds_alert.load_state()

    def _write_apy_feed_bounds_health_state(self, state: dict) -> None:
        self._apy_feed_bounds_alert.write_state(state)

    def _load_apy_feed_monotonicity_health_state(self) -> dict:
        return self._apy_feed_monotonicity_alert.load_state()

    def _write_apy_feed_monotonicity_health_state(self, state: dict) -> None:
        self._apy_feed_monotonicity_alert.write_state(state)

    def _load_apy_feed_protocol_stale_health_state(self) -> dict:
        return self._apy_feed_protocol_stale_alert.load_state()

    def _write_apy_feed_protocol_stale_health_state(self, state: dict) -> None:
        self._apy_feed_protocol_stale_alert.write_state(state)

    # ------------------------------------------------------------------
    # APY persistence helpers
    # ------------------------------------------------------------------

    def _load_prev_apys(self) -> dict[str, float]:
        try:
            if self._prev_apys_file.exists():
                return json.loads(
                    self._prev_apys_file.read_text(encoding="utf-8")
                )
        except Exception as exc:
            log.debug(f"_load_prev_apys: {exc}")
        return {}

    def _save_current_apys(self, positions: list[dict]) -> None:
        snapshot: dict[str, float] = {}
        for pos in positions:
            protocol = pos.get("protocol_key") or pos.get("protocol")
            apy      = pos.get("current_apy")
            if protocol and apy is not None:
                snapshot[protocol] = apy
        try:
            self._prev_apys_file.parent.mkdir(parents=True, exist_ok=True)
            self._prev_apys_file.write_text(
                json.dumps(snapshot, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            log.debug(f"_save_current_apys: {exc}")
