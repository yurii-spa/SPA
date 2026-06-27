#!/usr/bin/env python3
"""SPA Kill-Switch Engine (MP-108).

Механизм экстренной остановки paper-trading: при срабатывании любого триггера
переводит все позиции в Cash (allocation = {"cash": 1.0, все протоколы: 0.0}).

Триггеры:
1. drawdown_trigger  — просадка equity > 15% от максимума за последние 30 дней,
                       считается СТРОГО по evidenced (real) барам — warmup /
                       backfill / pre-anchor бары исключаются (N1 safety fix).
2. red_flags_trigger — более 5 CRITICAL красных флагов на УДЕРЖИВАЕМЫХ протоколах
                       в data/red_flags.json (advisory/WARN/bootstrap/внешние —
                       не в счёт; N1 safety fix).
3. manual_trigger    — файл data/kill_switch_active.json существует (создаётся вручную)
4. sharpe_trigger    — Sharpe < -1.0 (из data/analytics_summary.json), но только
                       при наличии ≥30 дней данных (малая выборка → артефакт)

Правила:
* LLM FORBIDDEN — детерминированная логика, никаких внешних вызовов.
* Stdlib only. Atomic writes (tmp + os.replace).
* Активация автоматическая; деактивация только через deactivate_kill_switch() вручную.
* approved=False от kill-switch не может быть переопределён агентом.
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from spa_core.utils.atomic import atomic_save

# Honest-track evidence model — the single source of truth for which equity
# bars are REAL (post-anchor, non-warmup, non-backfill, non-reconstructed).
# A warmup bar's inflated equity must NEVER fabricate a drawdown that closes the
# book (N1 safety fix), so the drawdown trigger computes peak/drawdown STRICTLY
# over the evidenced series.
from spa_core.paper_trading.track_evidence import (
    PAPER_REAL_START,
    evidenced_bars,
)

log = logging.getLogger("spa.kill_switch")

# ─── Constants ────────────────────────────────────────────────────────────────

# TWO-TIER drawdown response (owner-approved 2026-06-27, ADR-034):
#   • SOFT_DERISK_THRESHOLD_PCT (5%)  → DE-RISK state: HALT new allocations / no
#     INCREASING exposure (hold + allow only REDUCING), emit an edge-triggered
#     WARNING. Does NOT liquidate. This is the threshold the old RiskPolicy /
#     CLAUDE.md "5% kill switch" actually referred to — it is now the soft
#     de-risk threshold, not a full kill (rationale: a 5% drawdown is most often
#     a recoverable depeg/vol wobble; panic-liquidating it crystallises a loss
#     that would otherwise mean-revert).
#   • DRAWDOWN_THRESHOLD_PCT  (15%)   → HARD kill: close everything to cash
#     (a 15% drawdown on a stablecoin book signals real protocol collapse, not
#     noise — full liquidation is correct). UNCHANGED behaviour.
# Both tiers are computed STRICTLY over the EVIDENCED real series (T6/P5-4) and
# are non-finite-safe (P5-1). See drawdown_tier() / DrawdownTier below.
SOFT_DERISK_THRESHOLD_PCT = 5.0  # % просадки → soft de-risk (no new/increase)
DRAWDOWN_THRESHOLD_PCT = 15.0   # % просадки от 30-дневного максимума → hard kill
RED_FLAGS_THRESHOLD = 5          # количество красных флагов для срабатывания
SHARPE_THRESHOLD = -1.0          # порог Sharpe ratio (нормальный период, ≥60 дней)
LOOKBACK_DAYS = 30               # окно для drawdown/Sharpe
MIN_DAYS_FOR_SHARPE = 30         # минимум дней данных, чтобы Sharpe считался надёжным
                                 # сигналом для kill-switch (малая выборка → деление
                                 # на ~0 волатильность даёт артефактный Sharpe)

# Early-period grace: в первые SHARPE_EARLY_PERIOD_DAYS дней трека Sharpe
# может быть отрицательным из-за малой выборки или раскачки — используем
# мягкий порог SHARPE_EARLY_THRESHOLD вместо SHARPE_THRESHOLD.
# Значения читаются из risk_policy.json; ниже — compile-time дефолты.
SHARPE_EARLY_PERIOD_DAYS = 60   # первые N дней → early period
SHARPE_EARLY_THRESHOLD = -2.0   # мягкий порог в early period

KILL_SWITCH_ACTIVE_FILENAME = "kill_switch_active.json"
KILL_SWITCH_STATUS_FILENAME = "kill_switch_status.json"
DERISK_STATUS_FILENAME = "derisk_status.json"  # soft-tier de-risk state (ADR-034)

# Drawdown-tier enum values (strings, not an Enum, to stay stdlib-trivial and
# JSON-serialisable). The three mutually-exclusive states of the evidenced
# drawdown ladder.
TIER_NONE = "NONE"              # drawdown < SOFT_DERISK_THRESHOLD_PCT → no action
TIER_SOFT_DERISK = "SOFT_DERISK"  # SOFT ≤ drawdown < HARD → halt new/increase
TIER_HARD_KILL = "HARD_KILL"   # drawdown ≥ DRAWDOWN_THRESHOLD_PCT → all-cash
RED_FLAGS_FILENAME = "red_flags.json"
ANALYTICS_FILENAME = "analytics_summary.json"
ADAPTER_STATUS_FILENAME = "adapter_status.json"
POSITIONS_FILENAME = "current_positions.json"

# Fallback список протоколов, если adapter_status.json недоступен
_KNOWN_PROTOCOLS = ["aave_v3", "compound_v3", "morpho_blue", "yearn_v3", "euler_v2", "maple", "sky_susds"]


# ─── Atomic IO helpers ────────────────────────────────────────────────────────


def _load_sharpe_policy(data_dir: Path) -> dict[str, float]:
    """Читает Sharpe-параметры из data/risk_policy.json; fallback → compile-time дефолты.

    Возвращает dict с ключами:
        kill_threshold     — нормальный порог (≥ early_period_days)
        early_period_days  — длина grace-периода (дней)
        early_threshold    — мягкий порог в early period
    """
    policy = _read_json(data_dir / "risk_policy.json", {})
    if not isinstance(policy, dict):
        policy = {}
    return {
        "kill_threshold": float(policy.get("SHARPE_KILL_THRESHOLD", SHARPE_THRESHOLD)),
        "early_period_days": float(policy.get("SHARPE_EARLY_PERIOD_DAYS", SHARPE_EARLY_PERIOD_DAYS)),
        "early_threshold": float(policy.get("SHARPE_EARLY_THRESHOLD", SHARPE_EARLY_THRESHOLD)),
    }


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _read_json(path: Path, default: Any = None) -> Any:
    """Читает JSON защищённо; при ошибке возвращает default (никогда не бросает)."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("%s unreadable (%s) — using default", path.name, exc)
        return default


def _norm_protocol(name: Any) -> str:
    """Canonicalize a protocol slug for cross-source comparison.

    red_flags.json uses hyphen slugs (``ethena-susde``) while
    current_positions.json uses underscore slugs (``aave_v3``). Lower-case and
    collapse ``-``/``_``/space to a single ``_`` so the two namespaces line up.
    """
    return str(name).strip().lower().replace("-", "_").replace(" ", "_")


def _load_held_protocols(data_dir: Path) -> set[str]:
    """Return the set of CURRENTLY HELD protocol slugs (normalized).

    A protocol is "held" iff it appears in ``current_positions.json`` with a
    strictly positive USD position. Read-only; fail-CLOSED to an empty set when
    the file is missing/unreadable (no held protocols → no held-protocol flag
    can trigger the kill-switch). Cash / book-keeping keys are ignored.
    """
    doc = _read_json(data_dir / POSITIONS_FILENAME, None)
    positions: Any = doc
    if isinstance(doc, dict) and isinstance(doc.get("positions"), (dict, list)):
        positions = doc["positions"]

    held: set[str] = set()
    if isinstance(positions, dict):
        for proto, usd in positions.items():
            if _norm_protocol(proto) in ("cash", "usdc", "usd"):
                continue
            try:
                if float(usd) > 0:
                    held.add(_norm_protocol(proto))
            except (TypeError, ValueError):
                continue
    elif isinstance(positions, list):
        for entry in positions:
            if not isinstance(entry, dict):
                continue
            proto = entry.get("protocol") or entry.get("slug") or entry.get("name")
            if not proto or _norm_protocol(proto) in ("cash", "usdc", "usd"):
                continue
            amount = (
                entry.get("usd")
                if entry.get("usd") is not None
                else entry.get("amount_usd", entry.get("size_pct", entry.get("weight")))
            )
            try:
                if amount is None or float(amount) > 0:
                    held.add(_norm_protocol(proto))
            except (TypeError, ValueError):
                held.add(_norm_protocol(proto))
    return held


# ─── Shared evidenced-drawdown computation ──────────────────────────────────────


def evidenced_drawdown_pct(equity_curve: list[dict]) -> float | None:
    """Drawdown (%, ≥ 0) of the EVIDENCED real series over the lookback window.

    The single, shared peak-to-current drawdown computation used by BOTH tiers
    (soft de-risk + hard kill) so they can never disagree about the drawdown.

    SAFETY contracts preserved verbatim from ``check_drawdown_trigger``:
      * EVIDENCED-bars-only (T6/P5-4): warmup / seed / pre-anchor / backfill /
        reconstructed bars are excluded BEFORE the 30-day window is taken, so an
        inflated warmup peak can never fabricate a drawdown.
      * NON-FINITE-SAFE (P5-1): every non-finite / non-positive close is dropped
        as no-data (never masks nor fabricates a drawdown); a non-finite computed
        drawdown returns ``None`` (fail-CLOSED — the caller treats it as "cannot
        verify").

    Returns
    -------
    float
        The drawdown percentage (0.0 = at new highs, positive = below peak).
    None
        Not enough evidenced data to compute a drawdown, OR a corrupt
        (non-finite) result — the caller must fail CLOSED on ``None``.
    """
    if not equity_curve or not isinstance(equity_curve, list):
        return None

    real_bars = evidenced_bars(equity_curve, paper_start=PAPER_REAL_START)
    if not real_bars:
        return None

    window = real_bars[-LOOKBACK_DAYS:]
    if not window:
        return None

    try:
        closes = [float(bar.get("close_equity") or bar.get("equity") or 0.0)
                  for bar in window]
    except (TypeError, ValueError):
        return None

    # Drop every non-finite / non-positive close (corrupt bar == no-data).
    closes = [c for c in closes if math.isfinite(c) and c > 0]
    if len(closes) < 2:
        return None

    peak = max(closes)
    current = closes[-1]
    if peak <= 0:
        return None

    drawdown_pct = (peak - current) / peak * 100.0
    if not math.isfinite(drawdown_pct):
        return None
    return drawdown_pct


def drawdown_tier(equity_curve: list[dict]) -> tuple[str, str]:
    """Classify the evidenced drawdown into the TWO-TIER ladder (ADR-034).

    Deterministic, fail-CLOSED, evidenced-bars-only, non-finite-safe — it is a
    thin classifier over :func:`evidenced_drawdown_pct`.

    Tier boundaries (monotone, half-open intervals so the ladder is exhaustive
    and non-overlapping):
        drawdown < SOFT (5%)            → TIER_NONE
        SOFT (5%) ≤ drawdown < HARD(15%)→ TIER_SOFT_DERISK
        drawdown ≥ HARD (15%)           → TIER_HARD_KILL

    When the drawdown cannot be computed (insufficient / corrupt evidenced data)
    the tier is ``TIER_NONE`` — the per-tier gates (the existing drawdown kill
    trigger and the soft de-risk gate) are themselves the fail-closed authority;
    this classifier never *fabricates* a more severe tier from missing data.

    Returns
    -------
    (tier, reason) : (str, str)
        ``tier`` ∈ {TIER_NONE, TIER_SOFT_DERISK, TIER_HARD_KILL}.
    """
    dd = evidenced_drawdown_pct(equity_curve)
    if dd is None:
        return TIER_NONE, "no/insufficient evidenced drawdown data"
    if dd >= DRAWDOWN_THRESHOLD_PCT:
        return TIER_HARD_KILL, (
            f"drawdown {dd:.2f}% ≥ {DRAWDOWN_THRESHOLD_PCT}% (HARD kill → all-cash)"
        )
    if dd >= SOFT_DERISK_THRESHOLD_PCT:
        return TIER_SOFT_DERISK, (
            f"drawdown {dd:.2f}% ≥ {SOFT_DERISK_THRESHOLD_PCT}% soft de-risk "
            f"(< {DRAWDOWN_THRESHOLD_PCT}% hard) — halt new/increase, hold/reduce only"
        )
    return TIER_NONE, f"drawdown {dd:.2f}% < {SOFT_DERISK_THRESHOLD_PCT}% (no action)"


# ─── KillSwitchChecker ────────────────────────────────────────────────────────


class KillSwitchChecker:
    """Проверяет все 4 триггера kill-switch.

    Parameters
    ----------
    data_dir : путь к папке data/ (по умолчанию <repo>/data)
    """

    def __init__(self, data_dir: str | os.PathLike | None = None) -> None:
        if data_dir is None:
            # По умолчанию: <repo>/data (два уровня вверх от этого файла)
            self.data_dir = Path(__file__).resolve().parents[2] / "data"
        else:
            self.data_dir = Path(data_dir)

    # ── Trigger 1: drawdown ───────────────────────────────────────────────────

    def check_drawdown_trigger(self, equity_curve: list[dict]) -> tuple[bool, str]:
        """Просадка equity > DRAWDOWN_THRESHOLD_PCT% от максимума за 30 дней.

        SAFETY (N1): peak/drawdown are computed STRICTLY over the *evidenced*
        REAL series — warmup / seed / pre-PAPER_REAL_START / backfill /
        reconstructed bars are excluded BEFORE the window is taken. A warmup
        bar's inflated equity (e.g. a pre-teardown demo peak) must never
        fabricate a drawdown that closes the honest go-live track. The drawdown
        THRESHOLD value is intentionally LEFT UNCHANGED (owner-gated).

        Parameters
        ----------
        equity_curve : список дневных баров {"date": "...", "close_equity": float, ...}

        Returns
        -------
        (triggered, reason)
        """
        if not equity_curve or not isinstance(equity_curve, list):
            return False, "no equity data"

        # Shared evidenced + non-finite-safe drawdown (T6/P5-4 + P5-1). Returns
        # None when the drawdown cannot be computed (insufficient / corrupt
        # evidenced data) → fail-CLOSED to "no kill" exactly as before.
        drawdown_pct = evidenced_drawdown_pct(equity_curve)
        if drawdown_pct is None:
            return False, (
                "no/insufficient evidenced drawdown data (warmup/backfill "
                "excluded or corrupt) — fail-closed"
            )

        # HARD tier (≥ DRAWDOWN_THRESHOLD_PCT) → full kill. Boundary semantics
        # UNCHANGED: strictly-greater-than preserves the existing eval-path
        # tests (exactly-15% does NOT fire the kill).
        if drawdown_pct > DRAWDOWN_THRESHOLD_PCT:
            reason = (
                f"drawdown {drawdown_pct:.2f}% > {DRAWDOWN_THRESHOLD_PCT}% threshold "
                f"(window={LOOKBACK_DAYS}d)"
            )
            log.warning("KILL SWITCH drawdown trigger: %s", reason)
            return True, reason

        return False, f"drawdown {drawdown_pct:.2f}% ≤ {DRAWDOWN_THRESHOLD_PCT}%"

    # ── Soft de-risk signal (ADR-034) ─────────────────────────────────────────

    def check_derisk_trigger(self, equity_curve: list[dict]) -> tuple[bool, str]:
        """SOFT tier: drawdown ∈ [SOFT, HARD) → de-risk (no new/increase).

        Parallel to (and STRICTLY weaker than) :meth:`check_drawdown_trigger`:
        it fires ONLY in the band where the hard kill does NOT. The cycle uses
        this to halt new allocations / block any position INCREASE (hold +
        reduce stay allowed) and emit a WARNING — it never liquidates.

        Deterministic, evidenced-bars-only, non-finite-safe, fail-CLOSED:
        a non-computable drawdown returns ``(False, …)`` (no de-risk fabricated
        from missing data — the hard kill trigger is the fail-closed authority).

        Returns
        -------
        (in_soft_band, reason)
        """
        if not equity_curve or not isinstance(equity_curve, list):
            return False, "no equity data"
        tier, reason = drawdown_tier(equity_curve)
        if tier == TIER_SOFT_DERISK:
            log.warning("SOFT DE-RISK trigger: %s", reason)
            return True, reason
        return False, reason

    # ── Trigger 2: red flags ──────────────────────────────────────────────────

    def check_red_flags_trigger(self) -> tuple[bool, str]:
        """Kill-switch on CRITICAL red flags affecting CURRENTLY HELD protocols.

        SAFETY (N1) — three bugs fixed so a ``red_flags.json`` full of advisory /
        WARN / bootstrap flags can NEVER close the honest book, while a real
        CRITICAL flag on a HELD protocol still does:

        (a) **Membership-aware bootstrap guard.** The live writer emits MIXED
            ``sources`` like ``["defillama","bootstrap","snapshot"]``, so the old
            exact-list guard (``doc_sources == ["bootstrap"]``) NEVER matched.
            Document-level ignore now fires only when EVERY source is bootstrap
            (``set(sources) <= {"bootstrap"}``) or ``fallback_used`` is true.
        (b) **Per-flag source filter.** ``RedFlag`` has NO ``bootstrap`` field —
            it carries ``source``. A flag is excluded iff its OWN
            ``source == "bootstrap"`` (was: the never-present ``f["bootstrap"]``).
        (c) **CRITICAL-on-HELD only.** Only ``severity == "CRITICAL"`` flags on
            protocols we ACTUALLY HOLD count toward the trigger. Advisory /
            WARN / external-protocol flags must not close the book.

        Configurable via ``data/risk_policy.json``:
          RED_FLAGS_IGNORE_BOOTSTRAP (bool, default True)
          RED_FLAGS_THRESHOLD        (int,  default 5)

        Returns
        -------
        (triggered, reason)
        """
        doc = _read_json(self.data_dir / RED_FLAGS_FILENAME, {})
        if not isinstance(doc, dict):
            return False, "red_flags.json missing or invalid"

        flags = doc.get("red_flags")
        if not isinstance(flags, list):
            return False, "no red_flags list in file"

        # Читаем параметры из risk_policy.json (с fallback на compile-time defaults)
        policy = _read_json(self.data_dir / "risk_policy.json", {})
        if not isinstance(policy, dict):
            policy = {}
        ignore_bootstrap: bool = bool(policy.get("RED_FLAGS_IGNORE_BOOTSTRAP", True))
        threshold: int = int(policy.get("RED_FLAGS_THRESHOLD", RED_FLAGS_THRESHOLD))

        if ignore_bootstrap:
            # (a) Документ-уровень: fallback_used=true ИЛИ все источники bootstrap
            # → данные — заглушки, не живые. MIXED sources (содержат не только
            # bootstrap) НЕ считаются bootstrap-документом (см. live-писатель).
            doc_fallback = bool(doc.get("fallback_used", False))
            doc_sources = doc.get("sources", [])
            doc_is_bootstrap = (
                isinstance(doc_sources, list)
                and len(doc_sources) > 0
                and set(doc_sources) <= {"bootstrap"}
            )
            if doc_fallback or doc_is_bootstrap:
                log.warning(
                    "red_flags: fallback_used=%s / all-bootstrap-sources=%s — "
                    "ignoring all %d flags for kill_switch (non-live data)",
                    doc_fallback,
                    doc_is_bootstrap,
                    len(flags),
                )
                return False, (
                    f"red_flags: {len(flags)} flags ignored "
                    f"(fallback_used={doc_fallback}, sources={doc_sources})"
                )

            # (b) Флаг-уровень: исключаем флаги, чей СОБСТВЕННЫЙ source=bootstrap
            # (RedFlag не имеет поля "bootstrap" — только "source").
            live_flags = [
                f for f in flags
                if isinstance(f, dict) and f.get("source") != "bootstrap"
            ]
        else:
            live_flags = [f for f in flags if isinstance(f, dict)]

        # (c) Только CRITICAL-флаги на УДЕРЖИВАЕМЫХ протоколах закрывают книгу.
        # Advisory / WARN / флаги на внешних (не в портфеле) протоколах — НЕ в счёт.
        held = _load_held_protocols(self.data_dir)
        critical_on_held = [
            f for f in live_flags
            if str(f.get("severity", "")).upper() == "CRITICAL"
            and _norm_protocol(f.get("protocol", "")) in held
        ]

        count = len(critical_on_held)

        if count > threshold:
            protos = sorted({str(f.get("protocol", "")) for f in critical_on_held})
            reason = (
                f"red_flags count {count} > {threshold} threshold "
                f"(CRITICAL on held protocols: {protos}, from {RED_FLAGS_FILENAME})"
            )
            log.warning("KILL SWITCH red_flags trigger: %s", reason)
            return True, reason

        return False, (
            f"red_flags count {count} ≤ {threshold} "
            f"(CRITICAL-on-held; {len(live_flags)} live flag(s), "
            f"{len(held)} held protocol(s))"
        )

    # ── Trigger 3: manual ────────────────────────────────────────────────────

    def check_manual_trigger(self) -> tuple[bool, str]:
        """Файл data/kill_switch_active.json существует (создаётся вручную).

        Returns
        -------
        (triggered, reason)
        """
        active_path = self.data_dir / KILL_SWITCH_ACTIVE_FILENAME
        if active_path.exists():
            doc = _read_json(active_path, {})
            # Явный active=False означает деактивацию (для сред, где файл нельзя
            # удалить — overwrite вместо unlink). Триггер не срабатывает.
            if isinstance(doc, dict) and doc.get("active") is False:
                return False, (
                    f"{KILL_SWITCH_ACTIVE_FILENAME} present but active=False "
                    f"(reason: {doc.get('reason') or 'deactivated'})"
                )
            manual_reason = ""
            if isinstance(doc, dict):
                manual_reason = str(doc.get("reason") or "")
            reason = f"manual trigger active (file: {KILL_SWITCH_ACTIVE_FILENAME}"
            if manual_reason:
                reason += f", reason: {manual_reason}"
            reason += ")"
            log.warning("KILL SWITCH manual trigger: %s", reason)
            return True, reason

        return False, f"{KILL_SWITCH_ACTIVE_FILENAME} not found"

    # ── Trigger 4: Sharpe ────────────────────────────────────────────────────

    def check_sharpe_trigger(self) -> tuple[bool, str]:
        """Sharpe < threshold за 30+ дней из data/analytics_summary.json.

        Логика порогов (Variant A + B, ADR-ref risk_policy.json):
        - rf=0% (стейблкоин портфель): Sharpe рассчитывается в analytics_runner
          с RISK_FREE_RATE=0.0 — benchmark «держать USDC», не Treasury bills.
        - Early-period grace: если num_days < SHARPE_EARLY_PERIOD_DAYS (60),
          используется мягкий порог SHARPE_EARLY_THRESHOLD (-2.0) вместо
          нормального SHARPE_THRESHOLD (-1.0).

        Returns
        -------
        (triggered, reason)
        """
        doc = _read_json(self.data_dir / ANALYTICS_FILENAME, {})
        if not isinstance(doc, dict):
            return False, f"{ANALYTICS_FILENAME} missing or invalid"

        metrics = doc.get("metrics")
        if not isinstance(metrics, dict):
            return False, "no metrics in analytics_summary"

        sharpe = metrics.get("sharpe")
        if sharpe is None:
            return False, "sharpe not in analytics_summary"

        try:
            sharpe_val = float(sharpe)
        except (TypeError, ValueError):
            return False, f"invalid sharpe value: {sharpe}"

        # Малая выборка → волатильность ≈ 0 → Sharpe artefactно зашкаливает
        # (наблюдали sharpe -61 на 5 днях). Требуем минимум MIN_DAYS_FOR_SHARPE
        # дней данных, иначе Sharpe не считается надёжным сигналом для kill-switch.
        num_days = doc.get("num_days")
        if num_days is None:
            num_days = metrics.get("num_days", 0)
        try:
            num_days = float(num_days) if num_days is not None else 0
        except (TypeError, ValueError):
            num_days = 0
        if num_days < MIN_DAYS_FOR_SHARPE:
            return False, (
                f"sharpe {sharpe_val:.4f} — insufficient data "
                f"({num_days:.0f} days < {MIN_DAYS_FOR_SHARPE} required)"
            )

        # Читаем Sharpe-параметры из risk_policy.json (Variant A+B).
        sp = _load_sharpe_policy(self.data_dir)
        kill_threshold = sp["kill_threshold"]
        early_period_days = sp["early_period_days"]
        early_threshold = sp["early_threshold"]

        # Определяем применимый порог в зависимости от периода трека.
        if num_days < early_period_days:
            effective_threshold = early_threshold
            period_label = (
                f"early_period ({num_days:.0f}d < {early_period_days:.0f}d grace, "
                f"threshold={early_threshold})"
            )
        else:
            effective_threshold = kill_threshold
            period_label = (
                f"normal_period ({num_days:.0f}d ≥ {early_period_days:.0f}d, "
                f"threshold={kill_threshold})"
            )

        if sharpe_val < effective_threshold:
            reason = (
                f"sharpe {sharpe_val:.4f} < {effective_threshold} "
                f"[{period_label}] (from {ANALYTICS_FILENAME})"
            )
            log.warning("KILL SWITCH sharpe trigger: %s", reason)
            return True, reason

        return False, (
            f"sharpe {sharpe_val:.4f} >= {effective_threshold} [{period_label}]"
        )

    # ── Main check ────────────────────────────────────────────────────────────

    def is_kill_switch_active(
        self, equity_curve: list[dict] | None = None
    ) -> tuple[bool, str]:
        """Проверяет все триггеры, возвращает (active, reason) для первого сработавшего.

        Порядок проверки: manual → drawdown → red_flags → sharpe.

        Parameters
        ----------
        equity_curve : список дневных баров; если None — будет прочитан из файла.

        Returns
        -------
        (triggered: bool, reason: str)
        """
        # Порядок: сначала manual (мгновенная остановка), потом метрические
        for check_fn, needs_curve in [
            (self._check_manual_wrap, False),
            (self._check_drawdown_wrap, True),
            (self._check_red_flags_wrap, False),
            (self._check_sharpe_wrap, False),
        ]:
            if needs_curve:
                triggered, reason = check_fn(equity_curve)
            else:
                triggered, reason = check_fn(None)
            if triggered:
                return True, reason

        return False, "all triggers clear"

    def is_derisk_active(
        self, equity_curve: list[dict] | None = None
    ) -> tuple[bool, str]:
        """SOFT-tier de-risk signal — parallel to :meth:`is_kill_switch_active`.

        Returns ``(True, reason)`` iff the evidenced drawdown is in the soft band
        ``[SOFT, HARD)`` — i.e. the cycle must halt new allocations / block any
        increase while still holding (and allowing reductions). It is mutually
        exclusive with the HARD kill: at ≥ HARD the kill owns the response and
        this returns ``(False, …)`` (the all-cash kill already reduces exposure).

        Same ``(bool, reason)`` contract, same deterministic / fail-closed /
        evidenced-bars-only / non-finite-safe guarantees as the hard signal.

        Parameters
        ----------
        equity_curve : список дневных баров; если None — будет прочитан из файла.
        """
        if equity_curve is None:
            equity_doc = _read_json(self.data_dir / "equity_curve_daily.json", {})
            if isinstance(equity_doc, dict):
                equity_curve = equity_doc.get("daily") or []
            else:
                equity_curve = []
        return self.check_derisk_trigger(equity_curve)

    def _check_manual_wrap(self, _curve: Any) -> tuple[bool, str]:
        return self.check_manual_trigger()

    def _check_drawdown_wrap(self, equity_curve: list[dict] | None) -> tuple[bool, str]:
        if equity_curve is None:
            # Читаем из файла
            equity_doc = _read_json(
                self.data_dir / "equity_curve_daily.json", {}
            )
            if isinstance(equity_doc, dict):
                equity_curve = equity_doc.get("daily") or []
            else:
                equity_curve = []
        return self.check_drawdown_trigger(equity_curve)

    def _check_red_flags_wrap(self, _curve: Any) -> tuple[bool, str]:
        return self.check_red_flags_trigger()

    def _check_sharpe_wrap(self, _curve: Any) -> tuple[bool, str]:
        return self.check_sharpe_trigger()

    # ── State management ──────────────────────────────────────────────────────

    def activate_kill_switch(self, reason: str) -> None:
        """Записывает data/kill_switch_active.json атомарно с reason + timestamp.

        Используется для программной активации. При ручной — файл создаётся вручную.
        """
        doc = {
            "activated_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "source": "kill_switch_checker",
        }
        path = self.data_dir / KILL_SWITCH_ACTIVE_FILENAME
        _atomic_write_json(path, doc)
        log.critical("KILL SWITCH ACTIVATED: %s → %s", reason, path)

    def deactivate_kill_switch(self) -> None:
        """Удаляет data/kill_switch_active.json (деактивация kill-switch)."""
        path = self.data_dir / KILL_SWITCH_ACTIVE_FILENAME
        if path.exists():
            path.unlink()
            log.info("Kill switch deactivated: %s removed", path)
        else:
            log.info("Kill switch already inactive (file not found)")

    # ── Allocation ────────────────────────────────────────────────────────────

    def get_kill_switch_allocation(self) -> dict[str, float]:
        """Возвращает all-cash аллокацию: {"cash": 1.0, все протоколы: 0.0}.

        Пытается прочитать список протоколов из data/adapter_status.json;
        при отсутствии использует _KNOWN_PROTOCOLS.
        """
        protocols: list[str] = []

        # Попытка 1: adapter_status.json (execution-домен)
        adapter_status = _read_json(self.data_dir / ADAPTER_STATUS_FILENAME, None)
        if isinstance(adapter_status, dict):
            adapters_list = adapter_status.get("adapters") or []
            if isinstance(adapters_list, list):
                for entry in adapters_list:
                    if isinstance(entry, dict) and entry.get("protocol"):
                        protocols.append(str(entry["protocol"]))

        # Попытка 2: adapter_orchestrator_status.json
        if not protocols:
            orch_status = _read_json(
                self.data_dir / "adapter_orchestrator_status.json", None
            )
            if isinstance(orch_status, dict):
                adapters_list = orch_status.get("adapters") or []
                if isinstance(adapters_list, list):
                    for entry in adapters_list:
                        if isinstance(entry, dict) and entry.get("protocol"):
                            protocols.append(str(entry["protocol"]))

        # Fallback на известный список
        if not protocols:
            protocols = list(_KNOWN_PROTOCOLS)

        allocation: dict[str, float] = {"cash": 1.0}
        for p in protocols:
            allocation[p] = 0.0
        return allocation


# ─── Public entry point ───────────────────────────────────────────────────────


def run_kill_switch_check(
    equity_curve: list[dict] | None = None,
    data_dir: str | os.PathLike | None = None,
) -> dict:
    """Точка входа для cycle_runner.

    Проверяет все триггеры. При срабатывании:
    - Активирует kill-switch (создаёт kill_switch_active.json)
    - Записывает data/kill_switch_status.json

    Если не сработал и ранее был активен — **НЕ деактивирует** (ручная деактивация).

    Returns
    -------
    dict с ключами:
        triggered   : bool
        reason      : str
        allocation  : dict (all-cash при triggered=True, иначе {})
        ts          : str (ISO timestamp)
    """
    checker = KillSwitchChecker(data_dir=data_dir)
    now_ts = datetime.now(timezone.utc).isoformat()

    triggered, reason = checker.is_kill_switch_active(equity_curve=equity_curve)

    allocation: dict[str, float] = {}
    if triggered:
        allocation = checker.get_kill_switch_allocation()
        # Активируем (или обновляем) kill_switch_active.json только если он ещё не стоит
        active_path = checker.data_dir / KILL_SWITCH_ACTIVE_FILENAME
        if not active_path.exists():
            checker.activate_kill_switch(reason)
        # Пишем kill_switch_status.json
        status_doc = {
            "generated_at": now_ts,
            "triggered": True,
            "reason": reason,
            "allocation": allocation,
        }
        try:
            _atomic_write_json(checker.data_dir / KILL_SWITCH_STATUS_FILENAME, status_doc)
        except Exception as exc:
            log.warning("Failed to write kill_switch_status.json: %s", exc)
    else:
        # Пишем статус "не активен"
        status_doc = {
            "generated_at": now_ts,
            "triggered": False,
            "reason": reason,
            "allocation": {},
        }
        try:
            _atomic_write_json(checker.data_dir / KILL_SWITCH_STATUS_FILENAME, status_doc)
        except Exception as exc:
            log.warning("Failed to write kill_switch_status.json: %s", exc)

    return {
        "triggered": triggered,
        "reason": reason,
        "allocation": allocation,
        "ts": now_ts,
    }


def run_derisk_check(
    equity_curve: list[dict] | None = None,
    data_dir: str | os.PathLike | None = None,
) -> dict:
    """SOFT-tier (ADR-034) entry point for cycle_runner — parallel to the kill.

    Evaluates the soft de-risk band ``[SOFT, HARD)`` and persists
    ``data/derisk_status.json``. The WARNING alert is EDGE-TRIGGERED: it is
    flagged ``should_alert=True`` only on the inactive→active transition (the
    prior persisted state was not de-risk-active), so a multi-day de-risk window
    does not flood the alert channel. The actual dispatch is left to the caller
    (cycle_runner) via the existing alert/push_policy path.

    Returns
    -------
    dict with keys:
        active        : bool  — soft de-risk band entered (and not hard-killed)
        reason        : str
        should_alert  : bool  — True only on the inactive→active edge
        tier          : str   — TIER_NONE / TIER_SOFT_DERISK / TIER_HARD_KILL
        ts            : str
    """
    checker = KillSwitchChecker(data_dir=data_dir)
    now_ts = datetime.now(timezone.utc).isoformat()

    tier, tier_reason = drawdown_tier(
        equity_curve
        if equity_curve is not None
        else (
            (_read_json(checker.data_dir / "equity_curve_daily.json", {}) or {}).get(
                "daily"
            )
            or []
        )
    )
    active = tier == TIER_SOFT_DERISK

    # Edge-trigger: alert only on the inactive→active transition.
    prev = _read_json(checker.data_dir / DERISK_STATUS_FILENAME, {})
    prev_active = bool(prev.get("active")) if isinstance(prev, dict) else False
    should_alert = active and not prev_active

    status_doc = {
        "generated_at": now_ts,
        "active": active,
        "tier": tier,
        "reason": tier_reason,
        # The de-risk policy this asserts onto the cycle (advisory record).
        "policy": "halt_new_allocations_no_increase_hold_reduce_only" if active else "none",
    }
    try:
        _atomic_write_json(checker.data_dir / DERISK_STATUS_FILENAME, status_doc)
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to write %s: %s", DERISK_STATUS_FILENAME, exc)

    return {
        "active": active,
        "reason": tier_reason,
        "should_alert": should_alert,
        "tier": tier,
        "ts": now_ts,
    }
