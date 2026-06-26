"""
SPA APY-feed health monitors — extracted from risk_monitor.py (P3-6 refactor).

This module holds the APY-feed health-check family that used to live as a
copy-pasted ~10x triad inside the ``RiskMonitor`` god-class:

    alert_apy_feed_<X>()  +  _load_<X>_health_state()  +  _write_<X>_health_state()

Each of those triads shared the *exact same* mechanics — a JSON state file with
graceful load/write, a consecutive-degraded streak that grows on a bad cycle and
resets on a healthy one, a "fire once at/over threshold then re-fire as the
streak grows" alert rule, a lazy ``TelegramSender`` fallback, and a
persist-even-on-send-failure guarantee — differing only in the per-monitor
*evaluation* logic, the *state schema*, the alert *threshold*, and the *message*
text.

``FeedHealthAlert`` captures that shared mechanics once: the graceful state
load/write (which alone was ~10 hand-written ``_load_*`` / ``_write_*`` method
pairs) and the lazy-sender fallback. Each concrete monitor is now a subclass
that supplies a ``STATE_FILENAME`` + ``FRESH_STATE`` and a single ``run()`` with
its own (unchanged) decision logic, delegating I/O to the base.

Behaviour is byte-identical to the pre-refactor methods: the same state files,
the same fired messages, the same return values on the same fixtures.

stdlib-only, deterministic, no LLM. The ``from alerts.telegram_sender import
TelegramSender`` lazy import is preserved verbatim so it keeps resolving under
``export_data.py``'s ``sys.path`` bootstrap (which puts ``spa_core/`` on path).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("spa.alerts.risk_monitor")


def _live_threshold(name: str, default):
    """
    Read a threshold by NAME, preferring the value currently bound on the
    ``alerts.risk_monitor`` module if it is importable.

    Both ``apy_feed_monitors`` and ``risk_monitor`` expose these constants (the
    latter re-exports the former), and existing tests monkeypatch the name on
    ``alerts.risk_monitor`` and expect the live monitor to honour it. Resolving
    the value at call time keeps that historic patch-point working while the
    constant still has exactly one canonical definition below.
    """
    try:
        import sys
        rm = sys.modules.get("alerts.risk_monitor")
        if rm is not None and hasattr(rm, name):
            return getattr(rm, name)
    except Exception:
        pass
    return default


# ──────────────────────────────────────────────────────────────────────────
# Thresholds / config constants (moved verbatim from risk_monitor.py).
# Re-exported by risk_monitor so existing `from alerts.risk_monitor import …`
# imports keep working unchanged.
# ──────────────────────────────────────────────────────────────────────────
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
# SPA-V349: APY-feed VALUE-RANGE sanity-bounds. Все health-мониторы выше проверяют
# свежесть/счётчики/дельты/структуру/ТИПЫ — но НИ ОДИН не проверяет, что ЗНАЧЕНИЯ
# попадают в адекватный ДИАПАЗОН. Мусор-но-валидный-по-типу (apy=50000%, apy<0,
# tvl_usd<=0, абсурдно большой tvl) проходит все проверки, но отравляет
# covariance/Kelly-вселенную. Конвенция единиц apy: фид DeFiLlama хранит apy как
# ПРОЦЕНТНОЕ ЧИСЛО (6.3057 = 6.3057%, см. execution/defillama_apy_feed.py
# get_live_apy "Return live APY (%)" и data/historical_apy.json), поэтому верхняя
# граница задана как 1000.0 (== 1000%). tvl_usd — сырые доллары.
APY_FEED_APY_MIN = 0.0          # apy < 0 невалиден
APY_FEED_APY_MAX = 1000.0       # 1000% как процентное число (apy хранится как percent, не доля)
APY_FEED_TVL_MIN = 0.0          # tvl_usd должен быть > 0 (<= 0 невалиден)
APY_FEED_TVL_MAX = 1.0e13       # 10 трлн USD — абсурдный верхний sanity-cap
APY_FEED_BOUNDS_MAX_BAD_PCT = 0.5   # доля протоколов вне границ ≥50% = алерт
APY_FEED_BOUNDS_MIN_PROTOCOLS = 1   # абсолютный пол: < 1 пригодного числового протокола
# SPA-V350: APY-feed DATE MONOTONICITY & CONTINUITY. Все health-мониторы выше
# проверяют свежесть/счётчики/дельты/структуру/ТИПЫ/ДИАПАЗОНЫ — но НИ ОДИН не
# проверяет, что даты записей истории КАЖДОГО протокола идут МОНОТОННО ВПЕРЁД и
# БЕЗ БОЛЬШИХ РАЗРЫВОВ. Регрессия даты (date[i+1] < date[i]) или пропущенные дни
# (разрыв > 72ч при суточной гранулярности) тихо ломают rolling-90d
# covariance/Kelly-расчёт, проходя все остальные проверки.
APY_FEED_MAX_DATE_GAP_HOURS = 72.0  # фид суточной гранулярности; разрыв > 72ч = ≥2 пропущенных дня = деградация
APY_FEED_MONO_MAX_BAD_PCT = 0.5     # доля протоколов с битой монотонностью/непрерывностью ≥50% = алерт
APY_FEED_MONO_MIN_PROTOCOLS = 1     # абсолютный пол: < 1 пригодного протокола с историей


# ──────────────────────────────────────────────────────────────────────────
# FeedHealthAlert base class — captures the repeated triad mechanics.
# ──────────────────────────────────────────────────────────────────────────

class FeedHealthAlert:
    """
    Base for a single APY-feed health monitor.

    Subclasses declare a ``STATE_FILENAME`` and a ``FRESH_STATE`` default dict,
    then implement ``run(...)`` with their own (unchanged) decision logic,
    delegating the three pieces of genuinely-identical boilerplate to the base:

      • ``load_state()``  — graceful read (fresh on miss/corrupt);
      • ``write_state()`` — graceful atomic-ish write (swallows errors);
      • ``ensure_sender()`` — lazy ``TelegramSender`` fallback.

    This collapses what were ~10 hand-written ``_load_*_health_state`` /
    ``_write_*_health_state`` method pairs (plus 10 inlined sender fallbacks)
    into one shared implementation, byte-identical on the wire and on disk.
    """

    STATE_FILENAME: str = ""
    FRESH_STATE: dict = {}
    LOG_NAME: str = ""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.state_file = self.data_dir / self.STATE_FILENAME

    # -- state I/O (graceful — fresh on miss/corrupt; swallows write errors) --

    def load_state(self) -> dict:
        """Load the state file, falling back to a copy of FRESH_STATE."""
        fresh = {
            k: (list(v) if isinstance(v, list) else v)
            for k, v in self.FRESH_STATE.items()
        }
        try:
            if self.state_file.exists():
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    fresh.update({k: data.get(k, fresh[k]) for k in fresh})
        except Exception as exc:
            log.debug(f"_load_{self.LOG_NAME}_state: {exc}")
        return fresh

    def write_state(self, state: dict) -> None:
        """Persist the state file (graceful — swallows errors)."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            log.debug(f"_write_{self.LOG_NAME}_state: {exc}")

    # -- shared lazy TelegramSender fallback --

    @staticmethod
    def ensure_sender(sender):
        """Return (sender, error). On miss, lazily build a TelegramSender."""
        if sender is not None:
            return sender, None
        try:
            from alerts.telegram_sender import TelegramSender
            return TelegramSender(), None
        except Exception as exc:
            return None, exc

    # -- shared run() lifecycle (template method) ---------------------------
    #
    # Every concrete monitor's run() is the SAME state-machine — load_state →
    # evaluate a per-monitor predicate → grow/reset a consecutive-degraded
    # streak → "fire once at/over threshold then re-fire as the streak grows"
    # → persist (even on send failure). The only per-monitor differences are
    # the detection logic + which bookkeeping fields are written + the alert
    # message + the log strings. ``_drive_lifecycle`` owns the identical
    # skeleton; each run() now supplies ONLY those differences.

    def _drive_lifecycle(
        self,
        state: dict,
        *,
        degraded: bool,
        counter_key: str,
        threshold: int,
        log_prefix: str,
        healthy_updates: dict,
        healthy_log: str,
        degraded_updates: dict,
        build_message,
        no_alert_log,
        fired_log,
        sender,
    ) -> bool:
        """
        Run the shared streak/debounce/fire skeleton against ``state``.

        Behaviour is byte-identical to the historic per-monitor run() tail:

          • healthy → apply ``healthy_updates``, zero the streak +
            ``last_alerted_cycle``, persist, log ``healthy_log``, return False;
          • degraded → ++streak (n), apply ``degraded_updates``, debounce with
            ``n >= threshold and n != last_alerted_cycle``; below threshold →
            persist, log ``no_alert_log(n)``, return False;
          • fire → build the message, lazily resolve the sender (persist + bail
            on miss), send (persist + bail on send error), record
            ``last_alerted_cycle = n``, persist, log ``fired_log(n, ok)``,
            return ``bool(ok)``.

        ``healthy_updates`` / ``degraded_updates`` carry the per-monitor
        bookkeeping fields exactly as the original code wrote them (same keys,
        same conditional inclusion, same values). The streak counter and
        ``last_alerted_cycle`` are owned here so they are never duplicated.
        """
        if not degraded:
            state.update(healthy_updates)
            state[counter_key] = 0
            state["last_alerted_cycle"] = 0
            self.write_state(state)
            log.info(healthy_log)
            return False

        state[counter_key] = int(state.get(counter_key, 0)) + 1
        n = state[counter_key]
        last_alerted = int(state.get("last_alerted_cycle", 0))
        state.update(degraded_updates)

        should_alert = n >= threshold and n != last_alerted
        if not should_alert:
            self.write_state(state)
            log.info(no_alert_log(n))
            return False

        msg = build_message(n)

        sender, exc = self.ensure_sender(sender)
        if sender is None:
            log.error(
                f"{log_prefix}: could not create TelegramSender — {exc}"
            )
            self.write_state(state)
            return False

        try:
            ok = sender.send(msg)
        except Exception as exc:
            log.error(f"{log_prefix}: send error — {exc}")
            self.write_state(state)
            return False

        state["last_alerted_cycle"] = n
        self.write_state(state)
        log.info(fired_log(n, ok))
        return bool(ok)


# ══════════════════════════════════════════════════════════════════════════
# Concrete monitors.  Each ``run()`` preserves the original decision logic
# verbatim; only the state I/O + sender fallback are delegated to the base.
# ══════════════════════════════════════════════════════════════════════════


class CovarianceHealthAlert(FeedHealthAlert):
    STATE_FILENAME = "covariance_health_state.json"
    LOG_NAME = "covariance_health"
    FRESH_STATE = {
        "consecutive_degraded": 0,
        "last_source": None,
        "last_alerted_cycle": 0,
        "updated_at": None,
    }

    def run(self, cov_source, sender=None, *, section_failed: bool = False) -> bool:
        try:
            degraded = bool(section_failed) or cov_source in (None, "", "synthetic_fallback")

            state = self.load_state()
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            def build_message(n):
                src = cov_source if cov_source not in (None, "") else "unavailable"
                return (
                    f"⚠️ <b>SPA Covariance Degraded</b>\n\n"
                    f"Live APY covariance has been unavailable for {n} consecutive cycles.\n"
                    f"Source: {src}\n"
                    f"The correlation matrix / dynamic Kelly sizing is running on synthetic fallback data.\n"
                    f"Action: check DeFiLlama fetch + data/historical_apy.json bridge."
                )

            return self._drive_lifecycle(
                state,
                degraded=degraded,
                counter_key="consecutive_degraded",
                threshold=COVARIANCE_DEGRADED_CYCLES_ALERT,
                log_prefix="alert_covariance_degraded",
                healthy_updates={"last_source": cov_source, "updated_at": now},
                healthy_log=(
                    f"alert_covariance_degraded: healthy source={cov_source!r}, "
                    f"streak reset"
                ),
                degraded_updates={"last_source": cov_source, "updated_at": now},
                build_message=build_message,
                no_alert_log=lambda n: (
                    f"alert_covariance_degraded: degraded streak={n} "
                    f"(threshold={COVARIANCE_DEGRADED_CYCLES_ALERT}), no alert"
                ),
                fired_log=lambda n, ok: (
                    f"alert_covariance_degraded: alert {'sent' if ok else 'failed'} "
                    f"(streak={n}, source={cov_source!r})"
                ),
                sender=sender,
            )
        except Exception as exc:
            log.error(f"alert_covariance_degraded: unexpected error — {exc}")
            return False


class ApyFeedStaleAlert(FeedHealthAlert):
    STATE_FILENAME = "apy_feed_health_state.json"
    LOG_NAME = "apy_feed_health"
    FRESH_STATE = {
        "consecutive_stale": 0,
        "last_generated_at": None,
        "last_source": None,
        "last_alerted_cycle": 0,
        "updated_at": None,
    }

    def run(
        self,
        feed_path=None,
        *,
        generated_at=None,
        data_source=None,
        now=None,
        sender=None,
    ) -> bool:
        try:
            from datetime import datetime as _dt, timezone as _tz

            if generated_at is None and feed_path is not None:
                try:
                    doc = json.loads(Path(feed_path).read_text(encoding="utf-8"))
                    if isinstance(doc, dict):
                        generated_at = doc.get("generated_at")
                        if data_source is None:
                            data_source = doc.get("data_source")
                except Exception as exc:
                    log.debug(f"alert_apy_feed_stale: feed read — {exc}")

            if now is None:
                now = _dt.now(_tz.utc)
            elif now.tzinfo is None:
                now = now.replace(tzinfo=_tz.utc)

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

            state = self.load_state()
            prev_gen = state.get("last_generated_at")
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            too_old = age_hours is None or age_hours > APY_FEED_MAX_AGE_HOURS
            stuck = (
                generated_at is not None
                and prev_gen is not None
                and prev_gen == generated_at
            )
            synthetic = (data_source or "").lower().startswith("synthetic")
            degraded = bool(too_old or stuck or synthetic)

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

            bookkeeping = {
                "last_generated_at": generated_at,
                "last_source": data_source,
                "updated_at": now_iso,
            }

            def build_message(n):
                return (
                    f"⚠️ <b>SPA APY Feed Stale</b>\n\n"
                    f"historical_apy.json has been stale for {n} consecutive cycles.\n"
                    f"Reason: {reason_str}\n"
                    f"generated_at: {generated_at or 'unavailable'}\n"
                    f"The covariance/Kelly inputs may silently degrade to synthetic data.\n"
                    f"Action: check DeFiLlama fetch + section 9b of export_data.py."
                )

            return self._drive_lifecycle(
                state,
                degraded=degraded,
                counter_key="consecutive_stale",
                threshold=APY_FEED_STALE_CYCLES_ALERT,
                log_prefix="alert_apy_feed_stale",
                healthy_updates=dict(bookkeeping),
                healthy_log=(
                    f"alert_apy_feed_stale: healthy generated_at={generated_at!r}, "
                    f"source={data_source!r}, streak reset"
                ),
                degraded_updates=dict(bookkeeping),
                build_message=build_message,
                no_alert_log=lambda n: (
                    f"alert_apy_feed_stale: stale streak={n} "
                    f"(threshold={APY_FEED_STALE_CYCLES_ALERT}), no alert"
                ),
                fired_log=lambda n, ok: (
                    f"alert_apy_feed_stale: alert {'sent' if ok else 'failed'} "
                    f"(streak={n}, reason={reason_str!r})"
                ),
                sender=sender,
            )
        except Exception as exc:
            log.error(f"alert_apy_feed_stale: unexpected error — {exc}")
            return False


class ApyFeedProtocolDropAlert(FeedHealthAlert):
    STATE_FILENAME = "apy_feed_protocol_health_state.json"
    LOG_NAME = "apy_feed_protocol_health"
    FRESH_STATE = {
        "consecutive_drops": 0,
        "prev_num_protocols": None,
        "last_alerted_cycle": 0,
        "updated_at": None,
    }

    def run(
        self,
        feed_path=None,
        *,
        num_protocols=None,
        now=None,
        sender=None,
    ) -> bool:
        try:
            from datetime import datetime as _dt, timezone as _tz

            if num_protocols is None and feed_path is not None:
                try:
                    doc = json.loads(Path(feed_path).read_text(encoding="utf-8"))
                    if isinstance(doc, dict):
                        proto = doc.get("protocols")
                        if proto is None:
                            proto = doc.get("protocol_history")
                        if isinstance(proto, dict):
                            num_protocols = len(proto)
                except Exception as exc:
                    log.debug(f"alert_apy_feed_protocol_drop: feed read — {exc}")

            if now is None:
                now = _dt.now(_tz.utc)
            elif now.tzinfo is None:
                now = now.replace(tzinfo=_tz.utc)
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            state = self.load_state()
            prev = state.get("prev_num_protocols")

            unreadable = num_protocols is None
            too_few = (not unreadable) and num_protocols < APY_FEED_MIN_PROTOCOLS
            sharp_drop = (
                (not unreadable)
                and prev is not None
                and num_protocols <= prev * (1 - APY_FEED_PROTOCOL_DROP_PCT)
            )
            degraded = bool(unreadable or too_few or sharp_drop)

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

            # prev_num_protocols: always written when readable (healthy →
            # num_protocols which is non-None; degraded → only when not None).
            degraded_updates = {"updated_at": now_iso}
            if num_protocols is not None:
                degraded_updates["prev_num_protocols"] = num_protocols

            def build_message(n):
                cur_display = (
                    num_protocols if num_protocols is not None else "unavailable"
                )
                return (
                    f"⚠️ <b>SPA APY Feed Protocol Drop</b>\n\n"
                    f"historical_apy.json protocol count has degraded for "
                    f"{n} consecutive cycle(s).\n"
                    f"Reason: {reason_str}\n"
                    f"Protocols now: {cur_display} (was {prev if prev is not None else 'n/a'})\n"
                    f"The covariance/Kelly universe is silently thinning.\n"
                    f"Action: check DeFiLlama fetch + section 9b of export_data.py."
                )

            return self._drive_lifecycle(
                state,
                degraded=degraded,
                counter_key="consecutive_drops",
                threshold=1,
                log_prefix="alert_apy_feed_protocol_drop",
                healthy_updates={
                    "prev_num_protocols": num_protocols,
                    "updated_at": now_iso,
                },
                healthy_log=(
                    f"alert_apy_feed_protocol_drop: healthy "
                    f"num_protocols={num_protocols!r}, streak reset"
                ),
                degraded_updates=degraded_updates,
                build_message=build_message,
                no_alert_log=lambda n: (
                    f"alert_apy_feed_protocol_drop: degraded streak={n}, no alert"
                ),
                fired_log=lambda n, ok: (
                    f"alert_apy_feed_protocol_drop: alert {'sent' if ok else 'failed'} "
                    f"(streak={n}, reason={reason_str!r})"
                ),
                sender=sender,
            )
        except Exception as exc:
            log.error(f"alert_apy_feed_protocol_drop: unexpected error — {exc}")
            return False


class ApyFeedTvlDropAlert(FeedHealthAlert):
    STATE_FILENAME = "apy_feed_tvl_health_state.json"
    LOG_NAME = "apy_feed_tvl_health"
    FRESH_STATE = {
        "consecutive_drops": 0,
        "prev_tvl_usd": None,
        "last_alerted_cycle": 0,
        "updated_at": None,
    }

    def run(
        self,
        feed_path=None,
        *,
        total_tvl_usd=None,
        now=None,
        sender=None,
    ) -> bool:
        try:
            from datetime import datetime as _dt, timezone as _tz

            if total_tvl_usd is None and feed_path is not None:
                try:
                    doc = json.loads(Path(feed_path).read_text(encoding="utf-8"))
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

            if now is None:
                now = _dt.now(_tz.utc)
            elif now.tzinfo is None:
                now = now.replace(tzinfo=_tz.utc)
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            state = self.load_state()
            prev = state.get("prev_tvl_usd")

            unreadable = total_tvl_usd is None
            too_low = (not unreadable) and total_tvl_usd < APY_FEED_MIN_TVL_USD
            sharp_drop = (
                (not unreadable)
                and prev is not None
                and total_tvl_usd <= prev * (1 - APY_FEED_TVL_DROP_PCT)
            )
            degraded = bool(unreadable or too_low or sharp_drop)

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

            degraded_updates = {"updated_at": now_iso}
            if total_tvl_usd is not None:
                degraded_updates["prev_tvl_usd"] = total_tvl_usd

            def build_message(n):
                cur_display = (
                    f"${total_tvl_usd:,.0f}"
                    if total_tvl_usd is not None else "unavailable"
                )
                prev_display = f"${prev:,.0f}" if prev is not None else "n/a"
                return (
                    f"⚠️ <b>SPA APY Feed TVL Collapse</b>\n\n"
                    f"historical_apy.json total TVL has collapsed for "
                    f"{n} consecutive cycle(s).\n"
                    f"Reason: {reason_str}\n"
                    f"TVL now: {cur_display} (was {prev_display})\n"
                    f"The covariance/Kelly universe is thinning by capital weight.\n"
                    f"Action: check DeFiLlama fetch + section 9b of export_data.py."
                )

            return self._drive_lifecycle(
                state,
                degraded=degraded,
                counter_key="consecutive_drops",
                threshold=1,
                log_prefix="alert_apy_feed_tvl_drop",
                healthy_updates={
                    "prev_tvl_usd": total_tvl_usd,
                    "updated_at": now_iso,
                },
                healthy_log=(
                    f"alert_apy_feed_tvl_drop: healthy "
                    f"total_tvl_usd={total_tvl_usd!r}, streak reset"
                ),
                degraded_updates=degraded_updates,
                build_message=build_message,
                no_alert_log=lambda n: (
                    f"alert_apy_feed_tvl_drop: degraded streak={n}, no alert"
                ),
                fired_log=lambda n, ok: (
                    f"alert_apy_feed_tvl_drop: alert {'sent' if ok else 'failed'} "
                    f"(streak={n}, reason={reason_str!r})"
                ),
                sender=sender,
            )
        except Exception as exc:
            log.error(f"alert_apy_feed_tvl_drop: unexpected error — {exc}")
            return False


class ApyFeedProtocolAnomalyAlert(FeedHealthAlert):
    STATE_FILENAME = "apy_feed_anomaly_health_state.json"
    LOG_NAME = "apy_feed_anomaly_health"
    FRESH_STATE = {
        "prev_snapshot": None,
        "consecutive_anomalies": 0,
        "last_alerted_cycle": 0,
        "updated_at": None,
    }

    def run(
        self,
        feed_path=None,
        *,
        snapshot=None,
        now=None,
        sender=None,
    ) -> bool:
        try:
            from datetime import datetime as _dt, timezone as _tz

            if snapshot is None and feed_path is not None:
                try:
                    doc = json.loads(Path(feed_path).read_text(encoding="utf-8"))
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

            if now is None:
                now = _dt.now(_tz.utc)
            elif now.tzinfo is None:
                now = now.replace(tzinfo=_tz.utc)
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            state = self.load_state()
            prev = state.get("prev_snapshot")
            if not isinstance(prev, dict):
                prev = None

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

            # prev_snapshot is only persisted when the current snapshot is
            # readable (same condition on both healthy + anomalous paths).
            healthy_updates = {"updated_at": now_iso}
            degraded_updates = {"updated_at": now_iso}
            if snapshot is not None:
                healthy_updates["prev_snapshot"] = snapshot
                degraded_updates["prev_snapshot"] = snapshot

            def build_message(n):
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
                return (
                    f"⚠️ <b>SPA APY Feed Protocol Anomaly</b>\n\n"
                    f"historical_apy.json has a per-protocol anomaly for "
                    f"{n} consecutive cycle(s).\n"
                    f"{detail_str}\n"
                    f"A specific position dropped out or its APY/TVL crashed while "
                    f"aggregate alerts stayed quiet.\n"
                    f"Action: check DeFiLlama per-protocol fetch + section 9b export_data.py."
                )

            return self._drive_lifecycle(
                state,
                degraded=anomalous,
                counter_key="consecutive_anomalies",
                threshold=1,
                log_prefix="alert_apy_feed_protocol_anomaly",
                healthy_updates=healthy_updates,
                healthy_log=(
                    f"alert_apy_feed_protocol_anomaly: healthy "
                    f"({len(snapshot) if snapshot else 0} protocols), streak reset"
                ),
                degraded_updates=degraded_updates,
                build_message=build_message,
                no_alert_log=lambda n: (
                    f"alert_apy_feed_protocol_anomaly: anomalous streak={n}, no alert"
                ),
                fired_log=lambda n, ok: (
                    f"alert_apy_feed_protocol_anomaly: alert {'sent' if ok else 'failed'} "
                    f"(streak={n}, disappeared={len(disappeared)}, "
                    f"apy_crash={len(apy_crash)}, tvl_crash={len(tvl_crash)})"
                ),
                sender=sender,
            )
        except Exception as exc:
            log.error(f"alert_apy_feed_protocol_anomaly: unexpected error — {exc}")
            return False


class ApyFeedSchemaDriftAlert(FeedHealthAlert):
    STATE_FILENAME = "apy_feed_schema_health_state.json"
    LOG_NAME = "apy_feed_schema_health"
    FRESH_STATE = {
        "prev_bad_keys": [],
        "consecutive_drifts": 0,
        "last_alerted_cycle": 0,
        "updated_at": None,
    }

    def run(
        self,
        feed_path=None,
        *,
        records=None,
        now=None,
        sender=None,
    ) -> bool:
        try:
            from datetime import datetime as _dt, timezone as _tz

            proto = None
            if records is not None and isinstance(records, dict):
                proto = records
            elif feed_path is not None:
                try:
                    doc = json.loads(Path(feed_path).read_text(encoding="utf-8"))
                    if isinstance(doc, dict):
                        proto = doc.get("protocols")
                        if proto is None:
                            proto = doc.get("protocol_history")
                except Exception as exc:
                    log.debug(f"alert_apy_feed_schema_drift: feed read — {exc}")

            if now is None:
                now = _dt.now(_tz.utc)
            elif now.tzinfo is None:
                now = now.replace(tzinfo=_tz.utc)
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            state = self.load_state()

            def _is_number(v) -> bool:
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

            bad_keys: list[str] = []
            bad_reasons: dict[str, str] = {}
            total_usable = 0

            if isinstance(proto, dict):
                for key, hist in proto.items():
                    if not isinstance(hist, list):
                        total_usable += 1
                        bad_keys.append(key)
                        bad_reasons[key] = "history not list"
                        continue
                    if not hist:
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
                    unexpected = [
                        f for f in last.keys()
                        if f not in APY_FEED_KNOWN_FIELDS
                    ]
                    if unexpected:
                        log.debug(
                            f"alert_apy_feed_schema_drift: {key} unexpected "
                            f"fields {unexpected}"
                        )

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

            updates = {"prev_bad_keys": bad_keys, "updated_at": now_iso}

            def build_message(n):
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
                return (
                    f"⚠️ <b>SPA APY Feed Schema Drift</b>\n\n"
                    f"historical_apy.json schema has drifted for "
                    f"{n} consecutive cycle(s).\n"
                    f"{detail_str}\n"
                    f"Records changed shape/keys/types (string instead of number, "
                    f"missing field, non-dict record) — aggregate & per-protocol "
                    f"alerts can't see this.\n"
                    f"Action: check DeFiLlama parse + section 9b of export_data.py."
                )

            return self._drive_lifecycle(
                state,
                degraded=drift,
                counter_key="consecutive_drifts",
                threshold=1,
                log_prefix="alert_apy_feed_schema_drift",
                healthy_updates=dict(updates),
                healthy_log=(
                    f"alert_apy_feed_schema_drift: healthy "
                    f"({total_usable} protocols, {len(bad_keys)} bad), streak reset"
                ),
                degraded_updates=dict(updates),
                build_message=build_message,
                no_alert_log=lambda n: (
                    f"alert_apy_feed_schema_drift: drift streak={n}, no alert"
                ),
                fired_log=lambda n, ok: (
                    f"alert_apy_feed_schema_drift: alert {'sent' if ok else 'failed'} "
                    f"(streak={n}, bad={len(bad_keys)}/{total_usable})"
                ),
                sender=sender,
            )
        except Exception as exc:
            log.error(f"alert_apy_feed_schema_drift: unexpected error — {exc}")
            return False


class ApyFeedValueBoundsAlert(FeedHealthAlert):
    STATE_FILENAME = "apy_feed_bounds_health_state.json"
    LOG_NAME = "apy_feed_bounds_health"
    FRESH_STATE = {
        "prev_bad_keys": [],
        "consecutive_bounds": 0,
        "last_alerted_cycle": 0,
        "updated_at": None,
    }

    def run(
        self,
        feed_path=None,
        *,
        records=None,
        now=None,
        sender=None,
    ) -> bool:
        try:
            from datetime import datetime as _dt, timezone as _tz

            proto = None
            if records is not None and isinstance(records, dict):
                proto = records
            elif feed_path is not None:
                try:
                    doc = json.loads(Path(feed_path).read_text(encoding="utf-8"))
                    if isinstance(doc, dict):
                        proto = doc.get("protocols")
                        if proto is None:
                            proto = doc.get("protocol_history")
                except Exception as exc:
                    log.debug(f"alert_apy_feed_value_bounds: feed read — {exc}")

            if now is None:
                now = _dt.now(_tz.utc)
            elif now.tzinfo is None:
                now = now.replace(tzinfo=_tz.utc)
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            state = self.load_state()

            def _coerce_float(v):
                if isinstance(v, bool):
                    return None
                if isinstance(v, (int, float)):
                    return float(v)
                if isinstance(v, str):
                    try:
                        return float(v.strip())
                    except (TypeError, ValueError):
                        return None
                return None

            bad_keys: list[str] = []
            bad_reasons: dict[str, str] = {}
            total_usable = 0

            if isinstance(proto, dict):
                for key, hist in proto.items():
                    if not isinstance(hist, list) or not hist:
                        continue
                    last = hist[-1]
                    if not isinstance(last, dict):
                        continue
                    apy = _coerce_float(last.get("apy"))
                    tvl = _coerce_float(last.get("tvl_usd"))
                    if apy is None or tvl is None:
                        continue
                    total_usable += 1
                    reasons: list[str] = []
                    if apy < APY_FEED_APY_MIN:
                        reasons.append(f"apy {apy:g} < {APY_FEED_APY_MIN:g}")
                    elif apy > APY_FEED_APY_MAX:
                        reasons.append(f"apy {apy:g} > {APY_FEED_APY_MAX:g}")
                    if tvl <= APY_FEED_TVL_MIN:
                        reasons.append(f"tvl_usd {tvl:g} <= {APY_FEED_TVL_MIN:g}")
                    elif tvl > APY_FEED_TVL_MAX:
                        reasons.append(f"tvl_usd {tvl:g} > {APY_FEED_TVL_MAX:g}")
                    if reasons:
                        bad_keys.append(key)
                        bad_reasons[key] = "; ".join(reasons)

            bounds_min_protocols = _live_threshold(
                "APY_FEED_BOUNDS_MIN_PROTOCOLS", APY_FEED_BOUNDS_MIN_PROTOCOLS
            )
            unreadable = (not isinstance(proto, dict)) or total_usable == 0
            too_few = (not unreadable) and total_usable < bounds_min_protocols
            bad_pct = (
                (len(bad_keys) / total_usable) if total_usable > 0 else 0.0
            )
            bounds_bad = (
                (not unreadable)
                and len(bad_keys) > 0
                and bad_pct >= APY_FEED_BOUNDS_MAX_BAD_PCT
            )
            bad = bool(unreadable or too_few or bounds_bad)

            updates = {"prev_bad_keys": bad_keys, "updated_at": now_iso}

            def build_message(n):
                _LIM = 6
                lines: list[str] = []
                if unreadable:
                    lines.append("feed unreadable / no usable numeric protocols")
                if too_few:
                    lines.append(
                        f"only {total_usable} usable numeric protocol(s) "
                        f"< {bounds_min_protocols} floor"
                    )
                if bounds_bad:
                    parts = [
                        f"{k} ({bad_reasons.get(k, 'out of bounds')})"
                        for k in bad_keys[:_LIM]
                    ]
                    more = "" if len(bad_keys) <= _LIM else f" (+{len(bad_keys) - _LIM} more)"
                    lines.append(
                        f"{len(bad_keys)}/{total_usable} protocols out-of-bounds "
                        f"({int(bad_pct * 100)}% >= {int(APY_FEED_BOUNDS_MAX_BAD_PCT * 100)}%): "
                        + ", ".join(parts) + more
                    )
                detail_str = "\n".join(lines) if lines else "value out of bounds"
                return (
                    f"⚠️ <b>SPA APY Feed Value Bounds</b>\n\n"
                    f"historical_apy.json carries out-of-range values for "
                    f"{n} consecutive cycle(s).\n"
                    f"{detail_str}\n"
                    f"Type-valid garbage numbers (apy>1000% / apy<0 / tvl_usd<=0 / "
                    f"tvl_usd>$10T) pass stale/drop/anomaly/schema checks but poison "
                    f"the covariance & Kelly universe.\n"
                    f"Action: check DeFiLlama parse + section 9b of export_data.py."
                )

            return self._drive_lifecycle(
                state,
                degraded=bad,
                counter_key="consecutive_bounds",
                threshold=1,
                log_prefix="alert_apy_feed_value_bounds",
                healthy_updates=dict(updates),
                healthy_log=(
                    f"alert_apy_feed_value_bounds: healthy "
                    f"({total_usable} numeric protocols, {len(bad_keys)} oob), "
                    f"streak reset"
                ),
                degraded_updates=dict(updates),
                build_message=build_message,
                no_alert_log=lambda n: (
                    f"alert_apy_feed_value_bounds: bad streak={n}, no alert"
                ),
                fired_log=lambda n, ok: (
                    f"alert_apy_feed_value_bounds: alert {'sent' if ok else 'failed'} "
                    f"(streak={n}, oob={len(bad_keys)}/{total_usable})"
                ),
                sender=sender,
            )
        except Exception as exc:
            log.error(f"alert_apy_feed_value_bounds: unexpected error — {exc}")
            return False


class ApyFeedDateMonotonicityAlert(FeedHealthAlert):
    STATE_FILENAME = "apy_feed_monotonicity_health_state.json"
    LOG_NAME = "apy_feed_monotonicity_health"
    FRESH_STATE = {
        "prev_bad_keys": [],
        "consecutive_mono": 0,
        "last_alerted_cycle": 0,
        "updated_at": None,
    }

    def run(
        self,
        feed_path=None,
        *,
        snapshot=None,
        now=None,
        sender=None,
    ) -> bool:
        try:
            from datetime import datetime as _dt, timezone as _tz

            def _parse_dt(raw):
                if raw is None:
                    return None
                if isinstance(raw, bool):
                    return None
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

            proto = None
            if snapshot is not None and isinstance(snapshot, dict):
                proto = snapshot
            elif feed_path is not None:
                try:
                    doc = json.loads(Path(feed_path).read_text(encoding="utf-8"))
                    if isinstance(doc, dict):
                        proto = doc.get("protocols")
                        if proto is None:
                            proto = doc.get("protocol_history")
                except Exception as exc:
                    log.debug(
                        f"alert_apy_feed_date_monotonicity: feed read — {exc}"
                    )

            if now is None:
                now = _dt.now(_tz.utc)
            elif now.tzinfo is None:
                now = now.replace(tzinfo=_tz.utc)
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            state = self.load_state()

            bad_keys: list[str] = []
            bad_reasons: dict[str, str] = {}
            total_usable = 0

            if isinstance(proto, dict):
                for key, hist in proto.items():
                    if not isinstance(hist, list) or not hist:
                        continue
                    total_usable += 1
                    dates: list = []
                    unparseable = False
                    for rec in hist:
                        if not isinstance(rec, dict):
                            unparseable = True
                            break
                        raw = (
                            rec.get("date")
                            if rec.get("date") is not None
                            else rec.get("ts")
                            if rec.get("ts") is not None
                            else rec.get("timestamp")
                        )
                        dt = _parse_dt(raw)
                        if dt is None:
                            unparseable = True
                            break
                        dates.append(dt)

                    if unparseable:
                        bad_keys.append(key)
                        bad_reasons[key] = "unparseable date"
                        continue
                    if not dates:
                        bad_keys.append(key)
                        bad_reasons[key] = "no valid dates"
                        continue
                    if len(dates) < 2:
                        continue

                    reasons: list[str] = []
                    for i in range(len(dates) - 1):
                        delta_h = (
                            dates[i + 1] - dates[i]
                        ).total_seconds() / 3600.0
                        if delta_h < 0:
                            reasons.append(
                                f"regression at idx {i + 1} "
                                f"({delta_h:.1f}h)"
                            )
                            break
                        if delta_h > APY_FEED_MAX_DATE_GAP_HOURS:
                            reasons.append(
                                f"gap {delta_h:.1f}h at idx {i + 1}"
                            )
                            break
                    if reasons:
                        bad_keys.append(key)
                        bad_reasons[key] = "; ".join(reasons)

            mono_min_protocols = _live_threshold(
                "APY_FEED_MONO_MIN_PROTOCOLS", APY_FEED_MONO_MIN_PROTOCOLS
            )
            unreadable = (not isinstance(proto, dict)) or total_usable == 0
            too_few = (
                (not unreadable) and total_usable < mono_min_protocols
            )
            bad_pct = (
                (len(bad_keys) / total_usable) if total_usable > 0 else 0.0
            )
            monotonicity_bad = (
                (not unreadable)
                and len(bad_keys) > 0
                and bad_pct >= APY_FEED_MONO_MAX_BAD_PCT
            )
            bad = bool(unreadable or too_few or monotonicity_bad)

            updates = {"prev_bad_keys": bad_keys, "updated_at": now_iso}

            def build_message(n):
                _LIM = 5
                lines: list[str] = []
                if unreadable:
                    lines.append("feed unreadable / no usable protocols")
                if too_few:
                    lines.append(
                        f"only {total_usable} usable protocol(s) "
                        f"< {mono_min_protocols} floor"
                    )
                if monotonicity_bad:
                    parts = [
                        f"{k} ({bad_reasons.get(k, 'date order broken')})"
                        for k in bad_keys[:_LIM]
                    ]
                    more = (
                        "" if len(bad_keys) <= _LIM
                        else f" (+{len(bad_keys) - _LIM} more)"
                    )
                    lines.append(
                        f"{len(bad_keys)}/{total_usable} protocols with broken date "
                        f"series ({int(bad_pct * 100)}% >= "
                        f"{int(APY_FEED_MONO_MAX_BAD_PCT * 100)}%): "
                        + ", ".join(parts) + more
                    )
                detail_str = "\n".join(lines) if lines else "date series broken"
                return (
                    f"⚠️ <b>SPA APY Feed Date Monotonicity</b>\n\n"
                    f"historical_apy.json has non-monotonic / discontinuous dates for "
                    f"{n} consecutive cycle(s).\n"
                    f"{detail_str}\n"
                    f"Date regression (history runs backwards) or a >"
                    f"{APY_FEED_MAX_DATE_GAP_HOURS:.0f}h gap (skipped days) passes "
                    f"stale/drop/anomaly/schema/bounds checks but silently breaks the "
                    f"rolling-90d covariance & Kelly computation.\n"
                    f"Action: check DeFiLlama history merge + section 9b export_data.py."
                )

            return self._drive_lifecycle(
                state,
                degraded=bad,
                counter_key="consecutive_mono",
                threshold=1,
                log_prefix="alert_apy_feed_date_monotonicity",
                healthy_updates=dict(updates),
                healthy_log=(
                    f"alert_apy_feed_date_monotonicity: healthy "
                    f"({total_usable} protocols, {len(bad_keys)} bad), "
                    f"streak reset"
                ),
                degraded_updates=dict(updates),
                build_message=build_message,
                no_alert_log=lambda n: (
                    f"alert_apy_feed_date_monotonicity: bad streak={n}, no alert"
                ),
                fired_log=lambda n, ok: (
                    f"alert_apy_feed_date_monotonicity: alert "
                    f"{'sent' if ok else 'failed'} "
                    f"(streak={n}, bad={len(bad_keys)}/{total_usable})"
                ),
                sender=sender,
            )
        except Exception as exc:
            log.error(
                f"alert_apy_feed_date_monotonicity: unexpected error — {exc}"
            )
            return False


class ApyFeedProtocolStaleAlert(FeedHealthAlert):
    STATE_FILENAME = "apy_feed_protocol_stale_health_state.json"
    LOG_NAME = "apy_feed_protocol_stale_health"
    FRESH_STATE = {
        "consecutive_stale": 0,
        "last_alerted_cycle": 0,
        "last_stale_keys": [],
        "updated_at": None,
    }

    def run(
        self,
        feed_path=None,
        *,
        snapshot=None,
        now=None,
        sender=None,
    ) -> bool:
        try:
            from datetime import datetime as _dt, timezone as _tz

            def _parse_dt(raw):
                if raw is None:
                    return None
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

            if snapshot is None and feed_path is not None:
                try:
                    doc = json.loads(Path(feed_path).read_text(encoding="utf-8"))
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

            if now is None:
                now = _dt.now(_tz.utc)
            elif now.tzinfo is None:
                now = now.replace(tzinfo=_tz.utc)
            now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            state = self.load_state()

            unreadable = snapshot is None
            stale: list[tuple[str, float | None]] = []
            if not unreadable:
                for key, raw in snapshot.items():
                    dt = _parse_dt(raw)
                    if dt is None:
                        stale.append((key, None))
                        continue
                    age_hours = (now - dt).total_seconds() / 3600.0
                    if age_hours > APY_FEED_PROTOCOL_MAX_AGE_HOURS:
                        stale.append((key, age_hours))

            degraded = bool(unreadable or stale)

            def build_message(n):
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
                return (
                    f"⚠️ <b>SPA APY Feed Protocol Stale</b>\n\n"
                    f"historical_apy.json has a per-protocol staleness for "
                    f"{n} consecutive cycle(s).\n"
                    f"{detail_str}\n"
                    f"A specific protocol stopped advancing (record older than "
                    f"{APY_FEED_PROTOCOL_MAX_AGE_HOURS:.0f}h) while the feed as a "
                    f"whole still looks fresh — its covariance / Kelly input is stale.\n"
                    f"Action: check DeFiLlama per-protocol fetch + section 9b export_data.py."
                )

            return self._drive_lifecycle(
                state,
                degraded=degraded,
                counter_key="consecutive_stale",
                threshold=1,
                log_prefix="alert_apy_feed_protocol_stale",
                healthy_updates={"last_stale_keys": [], "updated_at": now_iso},
                healthy_log=(
                    f"alert_apy_feed_protocol_stale: healthy "
                    f"({len(snapshot) if snapshot else 0} protocols), streak reset"
                ),
                degraded_updates={
                    "last_stale_keys": [k for k, _ in stale],
                    "updated_at": now_iso,
                },
                build_message=build_message,
                no_alert_log=lambda n: (
                    f"alert_apy_feed_protocol_stale: stale streak={n}, no alert"
                ),
                fired_log=lambda n, ok: (
                    f"alert_apy_feed_protocol_stale: alert {'sent' if ok else 'failed'} "
                    f"(streak={n}, stale={len(stale)})"
                ),
                sender=sender,
            )
        except Exception as exc:
            log.error(f"alert_apy_feed_protocol_stale: unexpected error — {exc}")
            return False
