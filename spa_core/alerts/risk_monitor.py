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
APY_FEED_MAX_AGE_HOURS      = 8.0   # historical_apy.json старше = stale (>2 цикла при 4h-каденции)
APY_FEED_STALE_CYCLES_ALERT = 2     # подряд stale-циклов до алерта
APY_FEED_PROTOCOL_DROP_PCT  = 0.5   # падение ≥50% числа протоколов между циклами = деградация
APY_FEED_MIN_PROTOCOLS      = 3     # абсолютный пол: < 3 протоколов в фиде = деградация
APY_FEED_TVL_DROP_PCT       = 0.5   # падение совокупного TVL ≥50% между циклами = деградация
APY_FEED_MIN_TVL_USD        = 1.0e7 # абсолютный пол: совокупный TVL фида < $10M = деградация
APY_FEED_PROTOCOL_APY_DROP_PCT = 0.6  # падение APY конкретного протокола ≥60% между циклами = аномалия
APY_FEED_PROTOCOL_TVL_DROP_PCT = 0.6  # падение TVL конкретного протокола ≥60% между циклами = аномалия
APY_FEED_REQUIRED_FIELDS    = ("apy", "tvl_usd")  # минимально ожидаемые числовые поля каждой записи истории
APY_FEED_SCHEMA_MAX_BAD_PCT = 0.5   # доля протоколов с битой схемой ≥50% = schema drift
APY_FEED_SCHEMA_MIN_PROTOCOLS = 1   # абсолютный пол: < 1 пригодного протокола = drift
APY_FEED_PROTOCOL_MAX_AGE_HOURS = 48.0  # последняя запись истории КОНКРЕТНОГО протокола старше = протокол тихо залип (фид при этом может быть свежим)
# Известный набор ключей записи истории — поля вне него считаются "неожиданными" (не фатально).
APY_FEED_KNOWN_FIELDS = (
    "apy", "tvl_usd", "timestamp", "ts", "date", "block",
    "chain", "symbol", "pool", "project",
)


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
        self._apy_feed_health_file = self.data_dir / "apy_feed_health_state.json"
        self._apy_feed_protocol_health_file = self.data_dir / "apy_feed_protocol_health_state.json"
        self._apy_feed_tvl_health_file = self.data_dir / "apy_feed_tvl_health_state.json"
        self._apy_feed_anomaly_health_file = self.data_dir / "apy_feed_anomaly_health_state.json"
        self._apy_feed_schema_health_file = self.data_dir / "apy_feed_schema_health_state.json"
        self._apy_feed_protocol_stale_health_file = self.data_dir / "apy_feed_protocol_stale_health_state.json"

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
    # APY-feed staleness alert
    # ------------------------------------------------------------------

    def alert_apy_feed_stale(
        self,
        feed_path=None,
        *,
        generated_at=None,
        data_source=None,
        now=None,
        sender=None,
    ) -> bool:
        """
        Track historical_apy.json feed health across cycles and fire a Telegram
        alert when the APY feed has silently degraded for several consecutive
        cycles before it ever reaches the covariance synthetic_fallback path.

        A feed is considered degraded on any of:
          • too old — ``generated_at`` age exceeds ``APY_FEED_MAX_AGE_HOURS``
            (or could not be parsed at all);
          • stuck — ``generated_at`` is identical to the previously recorded
            value (file not refreshing / cached);
          • synthetic — ``data_source`` starts with ``"synthetic"``.

        State is persisted in ``self.data_dir / "apy_feed_health_state.json"``
        so the consecutive-stale streak survives across 4h pipeline runs.

        Alert rule: fire when the streak reaches ``APY_FEED_STALE_CYCLES_ALERT``
        and re-fire on every further consecutive stale cycle past that. A
        healthy cycle resets the streak and silences alerting.

        Returns:
            True if an alert was sent on this call, False otherwise.
            Never raises — all failures are logged and swallowed.
        """
        try:
            from datetime import datetime as _dt, timezone as _tz

            # Resolve metadata from the feed file if not supplied directly.
            if generated_at is None and feed_path is not None:
                try:
                    doc = json.loads(
                        Path(feed_path).read_text(encoding="utf-8")
                    )
                    if isinstance(doc, dict):
                        generated_at = doc.get("generated_at")
                        if data_source is None:
                            data_source = doc.get("data_source")
                except Exception as exc:
                    log.debug(f"alert_apy_feed_stale: feed read — {exc}")

            # Normalise `now` to an aware UTC datetime.
            if now is None:
                now = _dt.now(_tz.utc)
            elif now.tzinfo is None:
                now = now.replace(tzinfo=_tz.utc)

            # Parse generated_at into an aware datetime (None on failure).
            gen = None
            if isinstance(generated_at, str):
                try:
                    gen = _dt.fromisoformat(generated_at.replace("Z", "+00:00"))
                    if gen.tzinfo is None:
                        gen = gen.replace(tzinfo=_tz.utc)
                except Exception as exc:
                    log.debug(f"alert_apy_feed_stale: parse generated_at — {exc}")
                    gen = None

            age_hours = None
            if gen is not None:
                age_hours = (now - gen).total_seconds() / 3600.0

            state = self._load_apy_feed_health_state()
            prev_gen = state.get("last_generated_at")
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            # Degradation signals.
            too_old = age_hours is None or age_hours > APY_FEED_MAX_AGE_HOURS
            stuck = (
                generated_at is not None
                and prev_gen is not None
                and prev_gen == generated_at
            )
            synthetic = (data_source or "").lower().startswith("synthetic")
            degraded = bool(too_old or stuck or synthetic)

            if not degraded:
                # Healthy cycle — reset streak, silence alerting.
                state["consecutive_stale"] = 0
                state["last_alerted_cycle"] = 0
                state["last_generated_at"] = generated_at
                state["last_source"] = data_source
                state["updated_at"] = now_iso
                self._write_apy_feed_health_state(state)
                log.info(
                    f"alert_apy_feed_stale: healthy generated_at={generated_at!r}, "
                    f"source={data_source!r}, streak reset"
                )
                return False

            # Degraded cycle — grow the streak.
            state["consecutive_stale"] = int(state.get("consecutive_stale", 0)) + 1
            state["last_generated_at"] = generated_at
            state["last_source"] = data_source
            state["updated_at"] = now_iso
            n = state["consecutive_stale"]
            last_alerted = int(state.get("last_alerted_cycle", 0))

            # Fire once at/over threshold, and again only as the streak grows.
            should_alert = n >= APY_FEED_STALE_CYCLES_ALERT and n != last_alerted
            if not should_alert:
                self._write_apy_feed_health_state(state)
                log.info(
                    f"alert_apy_feed_stale: stale streak={n} "
                    f"(threshold={APY_FEED_STALE_CYCLES_ALERT}), no alert"
                )
                return False

            # Build a human-readable reason string from the active signals.
            reasons = []
            if stuck:
                reasons.append("stuck generated_at")
            if too_old:
                if age_hours is None:
                    reasons.append("generated_at unparseable")
                else:
                    reasons.append(
                        f"age {age_hours:.1f}h > {APY_FEED_MAX_AGE_HOURS}h"
                    )
            if synthetic:
                reasons.append(f"data_source={data_source}")
            reason_str = ", ".join(reasons) if reasons else "stale feed"

            msg = (
                f"⚠️ <b>SPA APY Feed Stale</b>\n\n"
                f"historical_apy.json has been stale for {n} consecutive cycles.\n"
                f"Reason: {reason_str}\n"
                f"generated_at: {generated_at or 'unavailable'}\n"
                f"The covariance/Kelly inputs may silently degrade to synthetic data.\n"
                f"Action: check DeFiLlama fetch + section 9b of export_data.py."
            )

            if sender is None:
                try:
                    from alerts.telegram_sender import TelegramSender
                    sender = TelegramSender()
                except Exception as exc:
                    log.error(
                        f"alert_apy_feed_stale: could not create TelegramSender — {exc}"
                    )
                    # Persist the grown streak even if we couldn't build a sender.
                    self._write_apy_feed_health_state(state)
                    return False

            try:
                ok = sender.send(msg)
            except Exception as exc:
                log.error(f"alert_apy_feed_stale: send error — {exc}")
                self._write_apy_feed_health_state(state)
                return False

            state["last_alerted_cycle"] = n
            self._write_apy_feed_health_state(state)
            log.info(
                f"alert_apy_feed_stale: alert {'sent' if ok else 'failed'} "
                f"(streak={n}, reason={reason_str!r})"
            )
            return bool(ok)
        except Exception as exc:
            log.error(f"alert_apy_feed_stale: unexpected error — {exc}")
            return False

    def _load_apy_feed_health_state(self) -> dict:
        """Load the APY-feed-health state file (graceful — fresh on miss/corrupt)."""
        fresh = {
            "consecutive_stale": 0,
            "last_generated_at": None,
            "last_source": None,
            "last_alerted_cycle": 0,
            "updated_at": None,
        }
        try:
            if self._apy_feed_health_file.exists():
                data = json.loads(
                    self._apy_feed_health_file.read_text(encoding="utf-8")
                )
                if isinstance(data, dict):
                    fresh.update({k: data.get(k, fresh[k]) for k in fresh})
        except Exception as exc:
            log.debug(f"_load_apy_feed_health_state: {exc}")
        return fresh

    def _write_apy_feed_health_state(self, state: dict) -> None:
        """Persist the APY-feed-health state file (graceful — swallows errors)."""
        try:
            self._apy_feed_health_file.parent.mkdir(parents=True, exist_ok=True)
            self._apy_feed_health_file.write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            log.debug(f"_write_apy_feed_health_state: {exc}")

    # ------------------------------------------------------------------
    # APY-feed protocol-count drop alert
    # ------------------------------------------------------------------

    def alert_apy_feed_protocol_drop(
        self,
        feed_path=None,
        *,
        num_protocols=None,
        now=None,
        sender=None,
    ) -> bool:
        """
        Track the number of protocols carried in historical_apy.json across
        cycles and fire a Telegram alert when it drops sharply (e.g. DeFiLlama
        partially failed: 7 protocols → 3) or falls below an absolute floor.

        This closes a blind spot not covered by alert_apy_feed_stale (which
        watches generated_at age / source) nor alert_covariance_degraded
        (which watches the covariance source): the feed can stay "fresh" and
        "live" while silently shedding protocols, quietly thinning the
        covariance / dynamic-Kelly universe.

        A cycle is considered degraded on any of:
          • too few — ``num_protocols < APY_FEED_MIN_PROTOCOLS``;
          • sharp drop — a previous count exists and the current count fell to
            ``prev * (1 - APY_FEED_PROTOCOL_DROP_PCT)`` or below;
          • unreadable — ``num_protocols`` could not be resolved (None).

        State is persisted in
        ``self.data_dir / "apy_feed_protocol_health_state.json"`` so the
        consecutive-drop streak survives across 4h pipeline runs.

        Alert rule: unlike the staleness monitor (threshold 2), a sharp
        protocol drop is alerted immediately on the very first degraded cycle
        (threshold 1, because a collapsing universe is more urgent), then
        re-fires on every further consecutive degraded cycle. A healthy cycle
        resets the streak and silences alerting. ``prev_num_protocols`` is
        always refreshed with the current value after evaluation so the next
        cycle compares against the latest count.

        Returns:
            True if an alert was sent on this call, False otherwise.
            Never raises — all failures are logged and swallowed.
        """
        try:
            from datetime import datetime as _dt, timezone as _tz

            # Resolve num_protocols from the feed file if not supplied directly.
            if num_protocols is None and feed_path is not None:
                try:
                    doc = json.loads(
                        Path(feed_path).read_text(encoding="utf-8")
                    )
                    if isinstance(doc, dict):
                        proto = doc.get("protocols")
                        if proto is None:
                            proto = doc.get("protocol_history")
                        if isinstance(proto, dict):
                            num_protocols = len(proto)
                except Exception as exc:
                    log.debug(f"alert_apy_feed_protocol_drop: feed read — {exc}")

            # Normalise `now` to an aware UTC datetime.
            if now is None:
                now = _dt.now(_tz.utc)
            elif now.tzinfo is None:
                now = now.replace(tzinfo=_tz.utc)
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            state = self._load_apy_feed_protocol_health_state()
            prev = state.get("prev_num_protocols")

            # Degradation signals.
            unreadable = num_protocols is None
            too_few = (not unreadable) and num_protocols < APY_FEED_MIN_PROTOCOLS
            sharp_drop = (
                (not unreadable)
                and prev is not None
                and num_protocols <= prev * (1 - APY_FEED_PROTOCOL_DROP_PCT)
            )
            degraded = bool(unreadable or too_few or sharp_drop)

            if not degraded:
                # Healthy cycle — reset streak, silence alerting, refresh prev.
                state["consecutive_drops"] = 0
                state["last_alerted_cycle"] = 0
                state["prev_num_protocols"] = num_protocols
                state["updated_at"] = now_iso
                self._write_apy_feed_protocol_health_state(state)
                log.info(
                    f"alert_apy_feed_protocol_drop: healthy "
                    f"num_protocols={num_protocols!r}, streak reset"
                )
                return False

            # Degraded cycle — grow the streak.
            state["consecutive_drops"] = int(state.get("consecutive_drops", 0)) + 1
            n = state["consecutive_drops"]
            last_alerted = int(state.get("last_alerted_cycle", 0))
            state["updated_at"] = now_iso

            # Fire immediately on the first degraded cycle (threshold 1), then
            # re-fire on every further consecutive degraded cycle.
            should_alert = n >= 1 and n != last_alerted

            # Always refresh prev_num_protocols with the current value (if known)
            # so the NEXT cycle compares against the actual latest count.
            if num_protocols is not None:
                state["prev_num_protocols"] = num_protocols

            if not should_alert:
                self._write_apy_feed_protocol_health_state(state)
                log.info(
                    f"alert_apy_feed_protocol_drop: degraded streak={n}, no alert"
                )
                return False

            # Build a human-readable reason string from the active signals.
            reasons = []
            if too_few:
                reasons.append(
                    f"only {num_protocols} protocols < {APY_FEED_MIN_PROTOCOLS} floor"
                )
            if sharp_drop:
                reasons.append(
                    f"sharp drop {prev} → {num_protocols} "
                    f"(>= {int(APY_FEED_PROTOCOL_DROP_PCT * 100)}%)"
                )
            if unreadable:
                reasons.append("protocol count unreadable")
            reason_str = ", ".join(reasons) if reasons else "protocol-count drop"

            cur_display = num_protocols if num_protocols is not None else "unavailable"
            msg = (
                f"⚠️ <b>SPA APY Feed Protocol Drop</b>\n\n"
                f"historical_apy.json protocol count has degraded for "
                f"{n} consecutive cycle(s).\n"
                f"Reason: {reason_str}\n"
                f"Protocols now: {cur_display} (was {prev if prev is not None else 'n/a'})\n"
                f"The covariance/Kelly universe is silently thinning.\n"
                f"Action: check DeFiLlama fetch + section 9b of export_data.py."
            )

            if sender is None:
                try:
                    from alerts.telegram_sender import TelegramSender
                    sender = TelegramSender()
                except Exception as exc:
                    log.error(
                        f"alert_apy_feed_protocol_drop: could not create "
                        f"TelegramSender — {exc}"
                    )
                    # Persist the grown streak even if we couldn't build a sender.
                    self._write_apy_feed_protocol_health_state(state)
                    return False

            try:
                ok = sender.send(msg)
            except Exception as exc:
                log.error(f"alert_apy_feed_protocol_drop: send error — {exc}")
                self._write_apy_feed_protocol_health_state(state)
                return False

            state["last_alerted_cycle"] = n
            self._write_apy_feed_protocol_health_state(state)
            log.info(
                f"alert_apy_feed_protocol_drop: alert {'sent' if ok else 'failed'} "
                f"(streak={n}, reason={reason_str!r})"
            )
            return bool(ok)
        except Exception as exc:
            log.error(f"alert_apy_feed_protocol_drop: unexpected error — {exc}")
            return False

    def _load_apy_feed_protocol_health_state(self) -> dict:
        """Load the protocol-count-health state file (graceful — fresh on miss/corrupt)."""
        fresh = {
            "consecutive_drops": 0,
            "prev_num_protocols": None,
            "last_alerted_cycle": 0,
            "updated_at": None,
        }
        try:
            if self._apy_feed_protocol_health_file.exists():
                data = json.loads(
                    self._apy_feed_protocol_health_file.read_text(encoding="utf-8")
                )
                if isinstance(data, dict):
                    fresh.update({k: data.get(k, fresh[k]) for k in fresh})
        except Exception as exc:
            log.debug(f"_load_apy_feed_protocol_health_state: {exc}")
        return fresh

    def _write_apy_feed_protocol_health_state(self, state: dict) -> None:
        """Persist the protocol-count-health state file (graceful — swallows errors)."""
        try:
            self._apy_feed_protocol_health_file.parent.mkdir(parents=True, exist_ok=True)
            self._apy_feed_protocol_health_file.write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            log.debug(f"_write_apy_feed_protocol_health_state: {exc}")

    def alert_apy_feed_tvl_drop(
        self,
        feed_path=None,
        *,
        total_tvl_usd=None,
        now=None,
        sender=None,
    ) -> bool:
        """
        Track the TOTAL TVL carried in historical_apy.json across cycles and
        fire a Telegram alert when it collapses sharply (e.g. DeFiLlama returns
        drastically lower TVL while still reporting the same number of
        protocols) or falls below an absolute floor.

        This closes a blind spot covered by neither alert_apy_feed_stale (which
        watches generated_at age / source) nor alert_apy_feed_protocol_drop
        (which watches the protocol *count*): the feed can stay "fresh", "live"
        and keep the same number of protocols while their aggregate capital
        weight quietly collapses, thinning the covariance / dynamic-Kelly
        universe by capital weight even when protocol count is constant.

        A cycle is considered degraded on any of:
          • too low — ``total_tvl_usd < APY_FEED_MIN_TVL_USD``;
          • sharp drop — a previous total exists and the current total fell to
            ``prev * (1 - APY_FEED_TVL_DROP_PCT)`` or below;
          • unreadable — ``total_tvl_usd`` could not be resolved (None).

        State is persisted in
        ``self.data_dir / "apy_feed_tvl_health_state.json"`` so the
        consecutive-drop streak survives across 4h pipeline runs.

        Alert rule: like the protocol-drop monitor (threshold 1), a sharp TVL
        collapse is alerted immediately on the very first degraded cycle, then
        re-fires on every further consecutive degraded cycle. A healthy cycle
        resets the streak and silences alerting. ``prev_tvl_usd`` is always
        refreshed with the current value after evaluation so the next cycle
        compares against the latest total.

        Returns:
            True if an alert was sent on this call, False otherwise.
            Never raises — all failures are logged and swallowed.
        """
        try:
            from datetime import datetime as _dt, timezone as _tz

            # Resolve total_tvl_usd from the feed file if not supplied directly.
            if total_tvl_usd is None and feed_path is not None:
                try:
                    doc = json.loads(
                        Path(feed_path).read_text(encoding="utf-8")
                    )
                    if isinstance(doc, dict):
                        proto = doc.get("protocols")
                        if proto is None:
                            proto = doc.get("protocol_history")
                        if isinstance(proto, dict):
                            running = 0.0
                            seen = 0
                            for hist in proto.values():
                                if not isinstance(hist, list) or not hist:
                                    continue
                                last = hist[-1]
                                if not isinstance(last, dict):
                                    continue
                                raw = last.get("tvl_usd")
                                if raw is None:
                                    continue
                                try:
                                    running += float(raw)
                                    seen += 1
                                except (TypeError, ValueError):
                                    continue
                            if seen > 0:
                                total_tvl_usd = running
                except Exception as exc:
                    log.debug(f"alert_apy_feed_tvl_drop: feed read — {exc}")

            # Normalise `now` to an aware UTC datetime.
            if now is None:
                now = _dt.now(_tz.utc)
            elif now.tzinfo is None:
                now = now.replace(tzinfo=_tz.utc)
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            state = self._load_apy_feed_tvl_health_state()
            prev = state.get("prev_tvl_usd")

            # Degradation signals.
            unreadable = total_tvl_usd is None
            too_low = (not unreadable) and total_tvl_usd < APY_FEED_MIN_TVL_USD
            sharp_drop = (
                (not unreadable)
                and prev is not None
                and total_tvl_usd <= prev * (1 - APY_FEED_TVL_DROP_PCT)
            )
            degraded = bool(unreadable or too_low or sharp_drop)

            if not degraded:
                # Healthy cycle — reset streak, silence alerting, refresh prev.
                state["consecutive_drops"] = 0
                state["last_alerted_cycle"] = 0
                state["prev_tvl_usd"] = total_tvl_usd
                state["updated_at"] = now_iso
                self._write_apy_feed_tvl_health_state(state)
                log.info(
                    f"alert_apy_feed_tvl_drop: healthy "
                    f"total_tvl_usd={total_tvl_usd!r}, streak reset"
                )
                return False

            # Degraded cycle — grow the streak.
            state["consecutive_drops"] = int(state.get("consecutive_drops", 0)) + 1
            n = state["consecutive_drops"]
            last_alerted = int(state.get("last_alerted_cycle", 0))
            state["updated_at"] = now_iso

            # Fire immediately on the first degraded cycle (threshold 1), then
            # re-fire on every further consecutive degraded cycle.
            should_alert = n >= 1 and n != last_alerted

            # Always refresh prev_tvl_usd with the current value (if known) so
            # the NEXT cycle compares against the actual latest total.
            if total_tvl_usd is not None:
                state["prev_tvl_usd"] = total_tvl_usd

            if not should_alert:
                self._write_apy_feed_tvl_health_state(state)
                log.info(
                    f"alert_apy_feed_tvl_drop: degraded streak={n}, no alert"
                )
                return False

            # Build a human-readable reason string from the active signals.
            reasons = []
            if too_low:
                reasons.append(
                    f"total TVL ${total_tvl_usd:,.0f} < ${APY_FEED_MIN_TVL_USD:,.0f} floor"
                )
            if sharp_drop:
                reasons.append(
                    f"sharp drop ${prev:,.0f} → ${total_tvl_usd:,.0f} "
                    f"(>= {int(APY_FEED_TVL_DROP_PCT * 100)}%)"
                )
            if unreadable:
                reasons.append("total TVL unreadable")
            reason_str = ", ".join(reasons) if reasons else "total-TVL drop"

            cur_display = (
                f"${total_tvl_usd:,.0f}" if total_tvl_usd is not None else "unavailable"
            )
            prev_display = f"${prev:,.0f}" if prev is not None else "n/a"
            msg = (
                f"⚠️ <b>SPA APY Feed TVL Collapse</b>\n\n"
                f"historical_apy.json total TVL has collapsed for "
                f"{n} consecutive cycle(s).\n"
                f"Reason: {reason_str}\n"
                f"TVL now: {cur_display} (was {prev_display})\n"
                f"The covariance/Kelly universe is thinning by capital weight.\n"
                f"Action: check DeFiLlama fetch + section 9b of export_data.py."
            )

            if sender is None:
                try:
                    from alerts.telegram_sender import TelegramSender
                    sender = TelegramSender()
                except Exception as exc:
                    log.error(
                        f"alert_apy_feed_tvl_drop: could not create "
                        f"TelegramSender — {exc}"
                    )
                    # Persist the grown streak even if we couldn't build a sender.
                    self._write_apy_feed_tvl_health_state(state)
                    return False

            try:
                ok = sender.send(msg)
            except Exception as exc:
                log.error(f"alert_apy_feed_tvl_drop: send error — {exc}")
                self._write_apy_feed_tvl_health_state(state)
                return False

            state["last_alerted_cycle"] = n
            self._write_apy_feed_tvl_health_state(state)
            log.info(
                f"alert_apy_feed_tvl_drop: alert {'sent' if ok else 'failed'} "
                f"(streak={n}, reason={reason_str!r})"
            )
            return bool(ok)
        except Exception as exc:
            log.error(f"alert_apy_feed_tvl_drop: unexpected error — {exc}")
            return False

    def _load_apy_feed_tvl_health_state(self) -> dict:
        """Load the total-TVL-health state file (graceful — fresh on miss/corrupt)."""
        fresh = {
            "consecutive_drops": 0,
            "prev_tvl_usd": None,
            "last_alerted_cycle": 0,
            "updated_at": None,
        }
        try:
            if self._apy_feed_tvl_health_file.exists():
                data = json.loads(
                    self._apy_feed_tvl_health_file.read_text(encoding="utf-8")
                )
                if isinstance(data, dict):
                    fresh.update({k: data.get(k, fresh[k]) for k in fresh})
        except Exception as exc:
            log.debug(f"_load_apy_feed_tvl_health_state: {exc}")
        return fresh

    def _write_apy_feed_tvl_health_state(self, state: dict) -> None:
        """Persist the total-TVL-health state file (graceful — swallows errors)."""
        try:
            self._apy_feed_tvl_health_file.parent.mkdir(parents=True, exist_ok=True)
            self._apy_feed_tvl_health_file.write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            log.debug(f"_write_apy_feed_tvl_health_state: {exc}")

    def alert_apy_feed_protocol_anomaly(
        self,
        feed_path=None,
        *,
        snapshot=None,
        now=None,
        sender=None,
    ) -> bool:
        """
        Track each INDIVIDUAL protocol carried in historical_apy.json across
        cycles and fire a Telegram alert when a specific protocol either
        DISAPPEARS from the feed between cycles or its APY / TVL crashes
        sharply, even when the aggregate alerts stay quiet.

        This closes a POINT blind spot covered by neither
        alert_apy_feed_protocol_drop (which watches the protocol *count* — a
        single dropout barely moves it) nor alert_apy_feed_tvl_drop (which
        watches *aggregate* TVL — one protocol collapsing is masked by the
        others holding the total up). A single position can vanish or have its
        APY/TVL halve while count and aggregate TVL look fine — corrupting the
        covariance / dynamic-Kelly view of that exact position.

        The snapshot is a ``dict[str, {"apy": float|None, "tvl_usd": float|None}]``
        built from the LAST history record of every protocol in the feed.

        A cycle is considered anomalous on any of:
          • unreadable — the snapshot could not be resolved (None);
          • disappeared — a key present in the previous snapshot is gone now;
          • apy_crash — a protocol present in both whose prev apy was > 0 and
            whose current apy fell to ``prev * (1 - APY_FEED_PROTOCOL_APY_DROP_PCT)``
            or below;
          • tvl_crash — same rule on ``tvl_usd`` with
            ``APY_FEED_PROTOCOL_TVL_DROP_PCT``.

        State is persisted in
        ``self.data_dir / "apy_feed_anomaly_health_state.json"`` so the
        consecutive-anomaly streak survives across 4h pipeline runs.

        Alert rule: like the protocol-drop monitor (threshold 1), a point
        anomaly is alerted immediately on the very first anomalous cycle, then
        re-fires on every further consecutive anomalous cycle. A healthy cycle
        resets the streak and silences alerting. ``prev_snapshot`` is always
        refreshed with the current snapshot (when known) after evaluation so
        the next cycle compares against the latest state.

        Returns:
            True if an alert was sent on this call, False otherwise.
            Never raises — all failures are logged and swallowed.
        """
        try:
            from datetime import datetime as _dt, timezone as _tz

            # Resolve snapshot from the feed file if not supplied directly.
            if snapshot is None and feed_path is not None:
                try:
                    doc = json.loads(
                        Path(feed_path).read_text(encoding="utf-8")
                    )
                    if isinstance(doc, dict):
                        proto = doc.get("protocols")
                        if proto is None:
                            proto = doc.get("protocol_history")
                        if isinstance(proto, dict):
                            built: dict = {}
                            for key, hist in proto.items():
                                if not isinstance(hist, list) or not hist:
                                    continue
                                last = hist[-1]
                                if not isinstance(last, dict):
                                    continue

                                def _coerce(raw):
                                    if raw is None:
                                        return None
                                    try:
                                        return float(raw)
                                    except (TypeError, ValueError):
                                        return None

                                built[key] = {
                                    "apy": _coerce(last.get("apy")),
                                    "tvl_usd": _coerce(last.get("tvl_usd")),
                                }
                            if built:
                                snapshot = built
                except Exception as exc:
                    log.debug(f"alert_apy_feed_protocol_anomaly: feed read — {exc}")

            # Normalise `now` to an aware UTC datetime.
            if now is None:
                now = _dt.now(_tz.utc)
            elif now.tzinfo is None:
                now = now.replace(tzinfo=_tz.utc)
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            state = self._load_apy_feed_anomaly_health_state()
            prev = state.get("prev_snapshot")
            if not isinstance(prev, dict):
                prev = None

            # Anomaly signals (compare current snapshot against prev_snapshot).
            unreadable = snapshot is None

            disappeared: list[str] = []
            apy_crash: list[str] = []
            tvl_crash: list[str] = []
            if (not unreadable) and prev is not None:
                for key, pdata in prev.items():
                    if key not in snapshot:
                        disappeared.append(key)
                        continue
                    cur = snapshot.get(key) or {}
                    pd = pdata if isinstance(pdata, dict) else {}
                    prev_apy = pd.get("apy")
                    cur_apy = cur.get("apy")
                    if (
                        prev_apy is not None
                        and prev_apy > 0
                        and cur_apy is not None
                        and cur_apy <= prev_apy * (1 - APY_FEED_PROTOCOL_APY_DROP_PCT)
                    ):
                        apy_crash.append(key)
                    prev_tvl = pd.get("tvl_usd")
                    cur_tvl = cur.get("tvl_usd")
                    if (
                        prev_tvl is not None
                        and prev_tvl > 0
                        and cur_tvl is not None
                        and cur_tvl <= prev_tvl * (1 - APY_FEED_PROTOCOL_TVL_DROP_PCT)
                    ):
                        tvl_crash.append(key)

            anomalous = bool(unreadable or disappeared or apy_crash or tvl_crash)

            if not anomalous:
                # Healthy cycle — reset streak, silence alerting, refresh prev.
                state["consecutive_anomalies"] = 0
                state["last_alerted_cycle"] = 0
                if snapshot is not None:
                    state["prev_snapshot"] = snapshot
                state["updated_at"] = now_iso
                self._write_apy_feed_anomaly_health_state(state)
                log.info(
                    f"alert_apy_feed_protocol_anomaly: healthy "
                    f"({len(snapshot) if snapshot else 0} protocols), streak reset"
                )
                return False

            # Anomalous cycle — grow the streak.
            state["consecutive_anomalies"] = (
                int(state.get("consecutive_anomalies", 0)) + 1
            )
            n = state["consecutive_anomalies"]
            last_alerted = int(state.get("last_alerted_cycle", 0))
            state["updated_at"] = now_iso

            # Fire immediately on the first anomalous cycle (threshold 1), then
            # re-fire on every further consecutive anomalous cycle.
            should_alert = n >= 1 and n != last_alerted

            # Always refresh prev_snapshot with the current snapshot (if known)
            # so the NEXT cycle compares against the actual latest state.
            if snapshot is not None:
                state["prev_snapshot"] = snapshot

            if not should_alert:
                self._write_apy_feed_anomaly_health_state(state)
                log.info(
                    f"alert_apy_feed_protocol_anomaly: anomalous streak={n}, no alert"
                )
                return False

            # Build a human-readable detail string from the active signals.
            _LIM = 5
            lines: list[str] = []
            if disappeared:
                lines.append(
                    "disappeared: " + ", ".join(disappeared[:_LIM])
                )
            if apy_crash:
                parts = []
                for key in apy_crash[:_LIM]:
                    pa = (prev or {}).get(key, {}).get("apy")
                    ca = (snapshot or {}).get(key, {}).get("apy")
                    parts.append(f"{key} {pa}→{ca}")
                lines.append("APY crash: " + ", ".join(parts))
            if tvl_crash:
                parts = []
                for key in tvl_crash[:_LIM]:
                    pt = (prev or {}).get(key, {}).get("tvl_usd")
                    ct = (snapshot or {}).get(key, {}).get("tvl_usd")
                    pt_s = f"${pt:,.0f}" if isinstance(pt, (int, float)) else "n/a"
                    ct_s = f"${ct:,.0f}" if isinstance(ct, (int, float)) else "n/a"
                    parts.append(f"{key} {pt_s}→{ct_s}")
                lines.append("TVL crash: " + ", ".join(parts))
            if unreadable:
                lines.append("snapshot unreadable")
            detail_str = "\n".join(lines) if lines else "per-protocol anomaly"

            msg = (
                f"⚠️ <b>SPA APY Feed Protocol Anomaly</b>\n\n"
                f"historical_apy.json has a per-protocol anomaly for "
                f"{n} consecutive cycle(s).\n"
                f"{detail_str}\n"
                f"A specific position dropped out or its APY/TVL crashed while "
                f"aggregate alerts stayed quiet.\n"
                f"Action: check DeFiLlama per-protocol fetch + section 9b export_data.py."
            )

            if sender is None:
                try:
                    from alerts.telegram_sender import TelegramSender
                    sender = TelegramSender()
                except Exception as exc:
                    log.error(
                        f"alert_apy_feed_protocol_anomaly: could not create "
                        f"TelegramSender — {exc}"
                    )
                    # Persist the grown streak even if we couldn't build a sender.
                    self._write_apy_feed_anomaly_health_state(state)
                    return False

            try:
                ok = sender.send(msg)
            except Exception as exc:
                log.error(f"alert_apy_feed_protocol_anomaly: send error — {exc}")
                self._write_apy_feed_anomaly_health_state(state)
                return False

            state["last_alerted_cycle"] = n
            self._write_apy_feed_anomaly_health_state(state)
            log.info(
                f"alert_apy_feed_protocol_anomaly: alert {'sent' if ok else 'failed'} "
                f"(streak={n}, disappeared={len(disappeared)}, "
                f"apy_crash={len(apy_crash)}, tvl_crash={len(tvl_crash)})"
            )
            return bool(ok)
        except Exception as exc:
            log.error(f"alert_apy_feed_protocol_anomaly: unexpected error — {exc}")
            return False

    def _load_apy_feed_anomaly_health_state(self) -> dict:
        """Load the per-protocol-anomaly state file (graceful — fresh on miss/corrupt)."""
        fresh = {
            "prev_snapshot": None,
            "consecutive_anomalies": 0,
            "last_alerted_cycle": 0,
            "updated_at": None,
        }
        try:
            if self._apy_feed_anomaly_health_file.exists():
                data = json.loads(
                    self._apy_feed_anomaly_health_file.read_text(encoding="utf-8")
                )
                if isinstance(data, dict):
                    fresh.update({k: data.get(k, fresh[k]) for k in fresh})
        except Exception as exc:
            log.debug(f"_load_apy_feed_anomaly_health_state: {exc}")
        return fresh

    def _write_apy_feed_anomaly_health_state(self, state: dict) -> None:
        """Persist the per-protocol-anomaly state file (graceful — swallows errors)."""
        try:
            self._apy_feed_anomaly_health_file.parent.mkdir(parents=True, exist_ok=True)
            self._apy_feed_anomaly_health_file.write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            log.debug(f"_write_apy_feed_anomaly_health_state: {exc}")

    # ------------------------------------------------------------------
    # APY-feed schema-drift validation alert
    # ------------------------------------------------------------------

    def alert_apy_feed_schema_drift(
        self,
        feed_path=None,
        *,
        records=None,
        now=None,
        sender=None,
    ) -> bool:
        """
        Validate the STRUCTURE / KEYS / TYPES of historical_apy.json across
        cycles and fire a Telegram alert when the feed schema drifts — e.g.
        ``apy`` / ``tvl_usd`` arrive as strings instead of numbers, a required
        field disappears, a history record stops being a dict, or the per-
        protocol history stops being a list.

        This closes a blind spot covered by NONE of the existing APY-feed
        monitors (stale / protocol-drop / tvl-drop / per-protocol anomaly):
        every one of those already ASSUMES a well-formed schema and silently
        skips or mis-reads malformed records. A schema drift can therefore
        corrupt the covariance / dynamic-Kelly inputs while every aggregate and
        per-protocol alert stays quiet.

        ``records`` (alias ``snapshot``) accepts a ready-made
        ``dict[str, list[record]]`` mapping (protocol -> history) so tests can
        bypass file reads — mirroring the ``snapshot`` kwarg of the per-protocol
        anomaly monitor.

        For each protocol the LAST history record is validated:
          • the per-protocol history must be a ``list`` (else: schema_bad);
          • the last record must be a ``dict`` (else: non-dict record);
          • each required field in ``APY_FEED_REQUIRED_FIELDS`` (``apy``,
            ``tvl_usd``) must be present AND a real number — ``int`` / ``float``
            (NOT ``bool``, NOT ``None``, NOT a non-numeric string). A numeric
            string like ``"5.0"`` is also accepted (coerced via ``float``); a
            non-numeric string like ``"n/a"`` is drift.
          • unexpected fields (outside ``APY_FEED_KNOWN_FIELDS``) are recorded
            for context but are NOT fatal on their own.

        A cycle is considered drifted on any of:
          • unreadable — file missing / corrupt / no usable protocols (None);
          • too_few — fewer than ``APY_FEED_SCHEMA_MIN_PROTOCOLS`` usable
            protocols;
          • schema_bad — the fraction of protocols with a bad-schema last
            record is ``>= APY_FEED_SCHEMA_MAX_BAD_PCT``.

        State is persisted in
        ``self.data_dir / "apy_feed_schema_health_state.json"`` so the
        consecutive-drift streak survives across 4h pipeline runs.

        Alert rule: like the protocol-drop monitor (threshold 1), a schema
        drift is alerted immediately on the very first drifted cycle, then
        re-fires on every further consecutive drifted cycle. A healthy cycle
        resets the streak and silences alerting. State is always updated after
        evaluation.

        Returns:
            True if an alert was sent on this call, False otherwise.
            Never raises — all failures are logged and swallowed.
        """
        try:
            from datetime import datetime as _dt, timezone as _tz

            # Resolve the protocol -> history mapping from the feed file if not
            # supplied directly.
            proto = None
            if records is not None and isinstance(records, dict):
                proto = records
            elif feed_path is not None:
                try:
                    doc = json.loads(
                        Path(feed_path).read_text(encoding="utf-8")
                    )
                    if isinstance(doc, dict):
                        proto = doc.get("protocols")
                        if proto is None:
                            proto = doc.get("protocol_history")
                except Exception as exc:
                    log.debug(f"alert_apy_feed_schema_drift: feed read — {exc}")

            # Normalise `now` to an aware UTC datetime.
            if now is None:
                now = _dt.now(_tz.utc)
            elif now.tzinfo is None:
                now = now.replace(tzinfo=_tz.utc)
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            state = self._load_apy_feed_schema_health_state()

            # ----------------------------------------------------------------
            # Validate the schema of every protocol's LAST history record.
            # ----------------------------------------------------------------
            def _is_number(v) -> bool:
                # Accept real int/float (not bool); accept numeric strings.
                if isinstance(v, bool):
                    return False
                if isinstance(v, (int, float)):
                    return True
                if isinstance(v, str):
                    try:
                        float(v.strip())
                        return True
                    except (TypeError, ValueError):
                        return False
                return False

            bad_keys: list[str] = []         # protocols with a bad-schema record
            bad_reasons: dict[str, str] = {} # protocol -> short reason
            total_usable = 0                 # protocols we could evaluate at all

            if isinstance(proto, dict):
                for key, hist in proto.items():
                    # history must be a list
                    if not isinstance(hist, list):
                        total_usable += 1
                        bad_keys.append(key)
                        bad_reasons[key] = "history not list"
                        continue
                    if not hist:
                        # Empty history — nothing to validate; skip as not usable.
                        continue
                    total_usable += 1
                    last = hist[-1]
                    if not isinstance(last, dict):
                        bad_keys.append(key)
                        bad_reasons[key] = "non-dict record"
                        continue
                    missing = [
                        f for f in APY_FEED_REQUIRED_FIELDS if f not in last
                    ]
                    if missing:
                        bad_keys.append(key)
                        bad_reasons[key] = "missing field " + ",".join(missing)
                        continue
                    bad_type = [
                        f for f in APY_FEED_REQUIRED_FIELDS
                        if not _is_number(last.get(f))
                    ]
                    if bad_type:
                        bad_keys.append(key)
                        bad_reasons[key] = "bad type " + ",".join(bad_type)
                        continue
                    # Record (non-fatal) unexpected fields for context only.
                    unexpected = [
                        f for f in last.keys()
                        if f not in APY_FEED_KNOWN_FIELDS
                    ]
                    if unexpected:
                        log.debug(
                            f"alert_apy_feed_schema_drift: {key} unexpected "
                            f"fields {unexpected}"
                        )

            # Drift signals.
            unreadable = (not isinstance(proto, dict)) or total_usable == 0
            too_few = (not unreadable) and total_usable < APY_FEED_SCHEMA_MIN_PROTOCOLS
            bad_pct = (
                (len(bad_keys) / total_usable) if total_usable > 0 else 0.0
            )
            schema_bad = (
                (not unreadable)
                and len(bad_keys) > 0
                and bad_pct >= APY_FEED_SCHEMA_MAX_BAD_PCT
            )
            drift = bool(unreadable or too_few or schema_bad)

            if not drift:
                # Healthy cycle — reset streak, silence alerting.
                state["consecutive_drifts"] = 0
                state["last_alerted_cycle"] = 0
                state["prev_bad_keys"] = bad_keys
                state["updated_at"] = now_iso
                self._write_apy_feed_schema_health_state(state)
                log.info(
                    f"alert_apy_feed_schema_drift: healthy "
                    f"({total_usable} protocols, {len(bad_keys)} bad), streak reset"
                )
                return False

            # Drifted cycle — grow the streak.
            state["consecutive_drifts"] = int(state.get("consecutive_drifts", 0)) + 1
            n = state["consecutive_drifts"]
            last_alerted = int(state.get("last_alerted_cycle", 0))
            state["prev_bad_keys"] = bad_keys
            state["updated_at"] = now_iso

            # Fire immediately on the first drifted cycle (threshold 1), then
            # re-fire on every further consecutive drifted cycle.
            should_alert = n >= 1 and n != last_alerted

            if not should_alert:
                self._write_apy_feed_schema_health_state(state)
                log.info(
                    f"alert_apy_feed_schema_drift: drift streak={n}, no alert"
                )
                return False

            # Build a human-readable detail string from the active signals.
            _LIM = 6
            lines: list[str] = []
            if unreadable:
                lines.append("feed unreadable / no usable protocols")
            if too_few:
                lines.append(
                    f"only {total_usable} usable protocol(s) "
                    f"< {APY_FEED_SCHEMA_MIN_PROTOCOLS} floor"
                )
            if schema_bad:
                parts = [
                    f"{k} ({bad_reasons.get(k, 'bad schema')})"
                    for k in bad_keys[:_LIM]
                ]
                more = "" if len(bad_keys) <= _LIM else f" (+{len(bad_keys) - _LIM} more)"
                lines.append(
                    f"{len(bad_keys)}/{total_usable} protocols bad-schema "
                    f"({int(bad_pct * 100)}% >= {int(APY_FEED_SCHEMA_MAX_BAD_PCT * 100)}%): "
                    + ", ".join(parts) + more
                )
            detail_str = "\n".join(lines) if lines else "schema drift"

            msg = (
                f"⚠️ <b>SPA APY Feed Schema Drift</b>\n\n"
                f"historical_apy.json schema has drifted for "
                f"{n} consecutive cycle(s).\n"
                f"{detail_str}\n"
                f"Records changed shape/keys/types (string instead of number, "
                f"missing field, non-dict record) — aggregate & per-protocol "
                f"alerts can't see this.\n"
                f"Action: check DeFiLlama parse + section 9b of export_data.py."
            )

            if sender is None:
                try:
                    from alerts.telegram_sender import TelegramSender
                    sender = TelegramSender()
                except Exception as exc:
                    log.error(
                        f"alert_apy_feed_schema_drift: could not create "
                        f"TelegramSender — {exc}"
                    )
                    # Persist the grown streak even if we couldn't build a sender.
                    self._write_apy_feed_schema_health_state(state)
                    return False

            try:
                ok = sender.send(msg)
            except Exception as exc:
                log.error(f"alert_apy_feed_schema_drift: send error — {exc}")
                self._write_apy_feed_schema_health_state(state)
                return False

            state["last_alerted_cycle"] = n
            self._write_apy_feed_schema_health_state(state)
            log.info(
                f"alert_apy_feed_schema_drift: alert {'sent' if ok else 'failed'} "
                f"(streak={n}, bad={len(bad_keys)}/{total_usable})"
            )
            return bool(ok)
        except Exception as exc:
            log.error(f"alert_apy_feed_schema_drift: unexpected error — {exc}")
            return False

    def _load_apy_feed_schema_health_state(self) -> dict:
        """Load the schema-drift state file (graceful — fresh on miss/corrupt)."""
        fresh = {
            "prev_bad_keys": [],
            "consecutive_drifts": 0,
            "last_alerted_cycle": 0,
            "updated_at": None,
        }
        try:
            if self._apy_feed_schema_health_file.exists():
                data = json.loads(
                    self._apy_feed_schema_health_file.read_text(encoding="utf-8")
                )
                if isinstance(data, dict):
                    fresh.update({k: data.get(k, fresh[k]) for k in fresh})
        except Exception as exc:
            log.debug(f"_load_apy_feed_schema_health_state: {exc}")
        return fresh

    def _write_apy_feed_schema_health_state(self, state: dict) -> None:
        """Persist the schema-drift state file (graceful — swallows errors)."""
        try:
            self._apy_feed_schema_health_file.parent.mkdir(parents=True, exist_ok=True)
            self._apy_feed_schema_health_file.write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            log.debug(f"_write_apy_feed_schema_health_state: {exc}")

    # ------------------------------------------------------------------
    # APY-feed PER-PROTOCOL staleness alert (one protocol stops advancing)
    # ------------------------------------------------------------------

    def alert_apy_feed_protocol_stale(
        self,
        feed_path=None,
        *,
        snapshot=None,
        now=None,
        sender=None,
    ) -> bool:
        """
        Track the AGE of each INDIVIDUAL protocol's latest history record in
        historical_apy.json and fire a Telegram alert when a SPECIFIC protocol
        stops advancing in time (its newest dated record is older than
        ``APY_FEED_PROTOCOL_MAX_AGE_HOURS``) while the feed as a whole still
        looks fresh.

        This closes a TIME blind spot covered by none of the existing APY-feed
        monitors:
          • alert_apy_feed_stale watches the feed-level ``generated_at`` — if
            the other protocols keep updating, the file timestamp advances and
            the whole-feed staleness alert never fires even though one
            protocol froze;
          • alert_apy_feed_protocol_anomaly watches per-protocol APY / TVL
            *value* crashes and dropouts — but a protocol whose last record
            simply stops getting fresher dates (its apy / tvl values sit
            unchanged, it never disappears) trips none of those signals.

        A frozen protocol silently feeds a stale data point into the
        covariance / dynamic-Kelly view of that exact position while every
        aggregate and value-based alert stays quiet.

        Snapshot resolution: ``snapshot`` may be passed directly as a
        ``dict[str, str|None]`` mapping ``protocol -> last_record_date_iso``
        (so tests can bypass file reads), mirroring the ``snapshot`` kwarg of
        the per-protocol anomaly monitor. Otherwise it is built from the LAST
        history record of every protocol in the feed, reading whichever of
        ``date`` / ``ts`` / ``timestamp`` is present. Bare ``YYYY-MM-DD`` dates
        are promoted to midnight UTC.

        Cadence note: the feed is dated at DAILY granularity (``YYYY-MM-DD``)
        while the pipeline runs every 4h (6 cycles/day), so within a single day
        every protocol's newest date is legitimately unchanged across cycles.
        Staleness is therefore measured by record AGE in hours — not by
        cycle-to-cycle date equality — so a healthy daily feed never trips it.

        State is persisted in
        ``self.data_dir / "apy_feed_protocol_stale_health_state.json"`` so the
        consecutive-stale streak survives across 4h pipeline runs.

        Alert rule: like the protocol-drop / anomaly monitors (threshold 1), a
        stale protocol is alerted immediately on the first stale cycle, then
        re-fires on every further consecutive stale cycle. A healthy cycle
        resets the streak and silences alerting.

        Returns:
            True if an alert was sent on this call, False otherwise.
            Never raises — all failures are logged and swallowed.
        """
        try:
            from datetime import datetime as _dt, timezone as _tz

            def _parse_dt(raw):
                """Parse a date / ts value into an aware UTC datetime, or None."""
                if raw is None:
                    return None
                # Numeric epoch seconds.
                if isinstance(raw, (int, float)):
                    try:
                        return _dt.fromtimestamp(float(raw), _tz.utc)
                    except (OverflowError, OSError, ValueError):
                        return None
                if not isinstance(raw, str):
                    return None
                s = raw.strip()
                if not s:
                    return None
                # Bare YYYY-MM-DD → midnight UTC.
                if len(s) == 10 and s[4] == "-" and s[7] == "-":
                    s = s + "T00:00:00+00:00"
                s = s.replace("Z", "+00:00")
                try:
                    dt = _dt.fromisoformat(s)
                except ValueError:
                    return None
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=_tz.utc)
                return dt

            # Resolve snapshot (protocol -> last_record_date_iso) from the feed.
            if snapshot is None and feed_path is not None:
                try:
                    doc = json.loads(
                        Path(feed_path).read_text(encoding="utf-8")
                    )
                    if isinstance(doc, dict):
                        proto = doc.get("protocols")
                        if proto is None:
                            proto = doc.get("protocol_history")
                        if isinstance(proto, dict):
                            built: dict = {}
                            for key, hist in proto.items():
                                if not isinstance(hist, list) or not hist:
                                    continue
                                last = hist[-1]
                                if not isinstance(last, dict):
                                    continue
                                raw = (
                                    last.get("date")
                                    if last.get("date") is not None
                                    else last.get("ts")
                                    if last.get("ts") is not None
                                    else last.get("timestamp")
                                )
                                built[key] = raw
                            if built:
                                snapshot = built
                except Exception as exc:
                    log.debug(f"alert_apy_feed_protocol_stale: feed read — {exc}")

            # Normalise `now` to an aware UTC datetime.
            if now is None:
                now = _dt.now(_tz.utc)
            elif now.tzinfo is None:
                now = now.replace(tzinfo=_tz.utc)
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            state = self._load_apy_feed_protocol_stale_health_state()

            # Staleness signals.
            unreadable = snapshot is None
            stale: list[tuple[str, float | None]] = []  # (protocol, age_hours|None)
            if not unreadable:
                for key, raw in snapshot.items():
                    dt = _parse_dt(raw)
                    if dt is None:
                        # A protocol whose newest record has no parseable date
                        # counts as stale (its freshness is unverifiable).
                        stale.append((key, None))
                        continue
                    age_hours = (now - dt).total_seconds() / 3600.0
                    if age_hours > APY_FEED_PROTOCOL_MAX_AGE_HOURS:
                        stale.append((key, age_hours))

            degraded = bool(unreadable or stale)

            if not degraded:
                # Healthy cycle — reset streak, silence alerting.
                state["consecutive_stale"] = 0
                state["last_alerted_cycle"] = 0
                state["last_stale_keys"] = []
                state["updated_at"] = now_iso
                self._write_apy_feed_protocol_stale_health_state(state)
                log.info(
                    f"alert_apy_feed_protocol_stale: healthy "
                    f"({len(snapshot) if snapshot else 0} protocols), streak reset"
                )
                return False

            # Stale cycle — grow the streak.
            state["consecutive_stale"] = int(state.get("consecutive_stale", 0)) + 1
            n = state["consecutive_stale"]
            last_alerted = int(state.get("last_alerted_cycle", 0))
            state["last_stale_keys"] = [k for k, _ in stale]
            state["updated_at"] = now_iso

            # Fire immediately on the first stale cycle (threshold 1), then
            # re-fire on every further consecutive stale cycle.
            should_alert = n >= 1 and n != last_alerted

            if not should_alert:
                self._write_apy_feed_protocol_stale_health_state(state)
                log.info(
                    f"alert_apy_feed_protocol_stale: stale streak={n}, no alert"
                )
                return False

            # Build a human-readable detail string from the active signals.
            _LIM = 5
            lines: list[str] = []
            if stale:
                parts = []
                for key, age in stale[:_LIM]:
                    if age is None:
                        parts.append(f"{key} (no parseable date)")
                    else:
                        parts.append(f"{key} {age:.1f}h old")
                more = f" (+{len(stale) - _LIM} more)" if len(stale) > _LIM else ""
                lines.append("stale: " + ", ".join(parts) + more)
            if unreadable:
                lines.append("snapshot unreadable")
            detail_str = "\n".join(lines) if lines else "per-protocol staleness"

            msg = (
                f"⚠️ <b>SPA APY Feed Protocol Stale</b>\n\n"
                f"historical_apy.json has a per-protocol staleness for "
                f"{n} consecutive cycle(s).\n"
                f"{detail_str}\n"
                f"A specific protocol stopped advancing (record older than "
                f"{APY_FEED_PROTOCOL_MAX_AGE_HOURS:.0f}h) while the feed as a "
                f"whole still looks fresh — its covariance / Kelly input is stale.\n"
                f"Action: check DeFiLlama per-protocol fetch + section 9b export_data.py."
            )

            if sender is None:
                try:
                    from alerts.telegram_sender import TelegramSender
                    sender = TelegramSender()
                except Exception as exc:
                    log.error(
                        f"alert_apy_feed_protocol_stale: could not create "
                        f"TelegramSender — {exc}"
                    )
                    # Persist the grown streak even if we couldn't build a sender.
                    self._write_apy_feed_protocol_stale_health_state(state)
                    return False

            try:
                ok = sender.send(msg)
            except Exception as exc:
                log.error(f"alert_apy_feed_protocol_stale: send error — {exc}")
                self._write_apy_feed_protocol_stale_health_state(state)
                return False

            state["last_alerted_cycle"] = n
            self._write_apy_feed_protocol_stale_health_state(state)
            log.info(
                f"alert_apy_feed_protocol_stale: alert {'sent' if ok else 'failed'} "
                f"(streak={n}, stale={len(stale)})"
            )
            return bool(ok)
        except Exception as exc:
            log.error(f"alert_apy_feed_protocol_stale: unexpected error — {exc}")
            return False

    def _load_apy_feed_protocol_stale_health_state(self) -> dict:
        """Load the per-protocol-staleness state file (graceful — fresh on miss/corrupt)."""
        fresh = {
            "consecutive_stale": 0,
            "last_alerted_cycle": 0,
            "last_stale_keys": [],
            "updated_at": None,
        }
        try:
            if self._apy_feed_protocol_stale_health_file.exists():
                data = json.loads(
                    self._apy_feed_protocol_stale_health_file.read_text(encoding="utf-8")
                )
                if isinstance(data, dict):
                    fresh.update({k: data.get(k, fresh[k]) for k in fresh})
        except Exception as exc:
            log.debug(f"_load_apy_feed_protocol_stale_health_state: {exc}")
        return fresh

    def _write_apy_feed_protocol_stale_health_state(self, state: dict) -> None:
        """Persist the per-protocol-staleness state file (graceful — swallows errors)."""
        try:
            self._apy_feed_protocol_stale_health_file.parent.mkdir(parents=True, exist_ok=True)
            self._apy_feed_protocol_stale_health_file.write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            log.debug(f"_write_apy_feed_protocol_stale_health_state: {exc}")

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
