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
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

log = logging.getLogger("spa.alerts.risk_monitor")

# Thresholds
CONCENTRATION_CRITICAL_PCT = 45.0
CONCENTRATION_WARNING_PCT  = 35.0
DAILY_DRAWDOWN_PCT         = 2.0     # single-day drop that triggers alert
APY_DROP_THRESHOLD         = 1.0     # pp drop vs last snapshot
CASH_BUFFER_MIN_PCT        = 3.0
COVARIANCE_DEGRADED_CYCLES_ALERT = 3   # consecutive synthetic/failed covariance cycles before alerting


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
        self._cov_health_file = self.data_dir / "covariance_health_state.json"

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
            from datetime import datetime, timezone
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
    # Covariance health alert
    # ------------------------------------------------------------------

    def alert_covariance_degraded(
        self, cov_source, sender=None, *, section_failed: bool = False
    ) -> bool:
        """
        Track covariance-pipeline health across cycles and fire a Telegram
        alert when the live APY covariance has degraded (running on synthetic
        fallback data, or the section failed) for several consecutive cycles.

        A healthy covariance source is ``"live"`` or ``"partial"``. Anything
        else — ``None``, ``""``, ``"synthetic_fallback"`` — or an explicit
        ``section_failed=True`` counts as degraded.

        State is persisted in ``self.data_dir / "covariance_health_state.json"``
        so the consecutive-degraded streak survives across 4h pipeline runs.

        Alert rule: fire when the streak reaches
        ``COVARIANCE_DEGRADED_CYCLES_ALERT`` and re-fire on every further
        consecutive degraded cycle past that (each new cycle in the streak
        sends once). A healthy cycle resets the streak and silences alerts.

        Returns:
            True if an alert was sent on this call, False otherwise.
            Never raises — all failures are logged and swallowed.
        """
        try:
            degraded = bool(section_failed) or cov_source in (None, "", "synthetic_fallback")

            state = self._load_covariance_health_state()
            from datetime import datetime as _dt, timezone as _tz
            now = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            if not degraded:
                # Healthy cycle — reset streak, silence alerting.
                state["consecutive_degraded"] = 0
                state["last_source"] = cov_source
                state["last_alerted_cycle"] = 0
                state["updated_at"] = now
                self._write_covariance_health_state(state)
                log.info(
                    f"alert_covariance_degraded: healthy source={cov_source!r}, "
                    f"streak reset"
                )
                return False

            # Degraded cycle — grow the streak.
            state["consecutive_degraded"] = int(state.get("consecutive_degraded", 0)) + 1
            state["last_source"] = cov_source
            state["updated_at"] = now
            n = state["consecutive_degraded"]
            last_alerted = int(state.get("last_alerted_cycle", 0))

            # Fire once at/over threshold, and again only as the streak grows.
            should_alert = n >= COVARIANCE_DEGRADED_CYCLES_ALERT and n != last_alerted
            if not should_alert:
                self._write_covariance_health_state(state)
                log.info(
                    f"alert_covariance_degraded: degraded streak={n} "
                    f"(threshold={COVARIANCE_DEGRADED_CYCLES_ALERT}), no alert"
                )
                return False

            src = cov_source if cov_source not in (None, "") else "unavailable"
            msg = (
                f"⚠️ <b>SPA Covariance Degraded</b>\n\n"
                f"Live APY covariance has been unavailable for {n} consecutive cycles.\n"
                f"Source: {src}\n"
                f"The correlation matrix / dynamic Kelly sizing is running on synthetic fallback data.\n"
                f"Action: check DeFiLlama fetch + data/historical_apy.json bridge."
            )

            if sender is None:
                try:
                    from alerts.telegram_sender import TelegramSender
                    sender = TelegramSender()
                except Exception as exc:
                    log.error(
                        f"alert_covariance_degraded: could not create TelegramSender — {exc}"
                    )
                    # Persist the grown streak even if we couldn't build a sender.
                    self._write_covariance_health_state(state)
                    return False

            try:
                ok = sender.send(msg)
            except Exception as exc:
                log.error(f"alert_covariance_degraded: send error — {exc}")
                self._write_covariance_health_state(state)
                return False

            state["last_alerted_cycle"] = n
            self._write_covariance_health_state(state)
            log.info(
                f"alert_covariance_degraded: alert {'sent' if ok else 'failed'} "
                f"(streak={n}, source={cov_source!r})"
            )
            return bool(ok)
        except Exception as exc:
            log.error(f"alert_covariance_degraded: unexpected error — {exc}")
            return False

    def _load_covariance_health_state(self) -> dict:
        """Load the covariance-health state file (graceful — fresh on miss/corrupt)."""
        fresh = {
            "consecutive_degraded": 0,
            "last_source": None,
            "last_alerted_cycle": 0,
            "updated_at": None,
        }
        try:
            if self._cov_health_file.exists():
                data = json.loads(self._cov_health_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    fresh.update({k: data.get(k, fresh[k]) for k in fresh})
        except Exception as exc:
            log.debug(f"_load_covariance_health_state: {exc}")
        return fresh

    def _write_covariance_health_state(self, state: dict) -> None:
        """Persist the covariance-health state file (graceful — swallows errors)."""
        try:
            self._cov_health_file.parent.mkdir(parents=True, exist_ok=True)
            self._cov_health_file.write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            log.debug(f"_write_covariance_health_state: {exc}")

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
