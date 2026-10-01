#!/usr/bin/env python3
"""SPA Kill-Switch Engine (MP-108).

Механизм экстренной остановки paper-trading: при срабатывании любого триггера
переводит все позиции в Cash (allocation = {"cash": 1.0, все протоколы: 0.0}).

Триггеры:
1. drawdown_trigger  — просадка equity ≥ 10% от максимума за последние 30 дней
                       (ADR-048: 15→10, граница теперь >=), считается СТРОГО по
                       evidenced (real) барам — warmup / backfill / pre-anchor
                       бары исключаются (N1 safety fix).
2. red_flags_trigger — более 5 CRITICAL красных флагов на УДЕРЖИВАЕМЫХ протоколах
                       в data/red_flags.json (advisory/WARN/bootstrap/внешние —
                       не в счёт; N1 safety fix).
3. manual_trigger    — файл data/kill_switch_active.json существует (создаётся вручную)
4. sharpe_trigger    — Sharpe < -1.0, считается СТРОГО по EVIDENCED (real) барам
                       equity_curve_daily.json (WS-2.3 parity с drawdown-триггером;
                       больше НЕ читает non-evidenced analytics_summary.json), но
                       только при ≥30 evidenced днях (малая выборка → THIN/None →
                       fail-closed, без kill)

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
    evidenced_daily_returns,
    real_sharpe_ratio,
)

log = logging.getLogger("spa.kill_switch")

# ─── Constants ────────────────────────────────────────────────────────────────

# TWO-TIER drawdown response (owner-approved 2026-06-27, ADR-034 + ADR-048):
#   • SOFT_DERISK_THRESHOLD_PCT (5%)  → DE-RISK state: HALT new allocations / no
#     INCREASING exposure (hold + allow only REDUCING), emit an edge-triggered
#     WARNING. Does NOT liquidate. This is the threshold the old RiskPolicy /
#     CLAUDE.md "5% kill switch" actually referred to — it is now the soft
#     de-risk threshold, not a full kill (rationale: a 5% drawdown is most often
#     a recoverable depeg/vol wobble; panic-liquidating it crystallises a loss
#     that would otherwise mean-revert).
#   • DRAWDOWN_THRESHOLD_PCT  (10%)   → HARD kill: close everything to cash
#     (a 10% drawdown on a stablecoin book signals real protocol collapse, not
#     noise — full liquidation is correct). LOWERED 15% → 10% (ADR-048,
#     owner-approved 2026-06-27): the hard kill now OWNS the 10% peak-drawdown
#     rung — the stronger ALL-CASH action subsumes the old DailyLimits DL-02
#     10%-peak HALT, which previously SHADOWED the kill by early-returning first.
# Both tiers are computed STRICTLY over the EVIDENCED real series (T6/P5-4) and
# are non-finite-safe (P5-1). See drawdown_tier() / DrawdownTier below.
SOFT_DERISK_THRESHOLD_PCT = 5.0  # % просадки → soft de-risk (no new/increase)
DRAWDOWN_THRESHOLD_PCT = 10.0   # % просадки от 30-дневного максимума → hard kill
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

# ─── Outcome of one trigger (ADR-531, P0-2 аудита ADR-530) ──────────────────────
# До ADR-531 у триггера было два исхода — (сработал, нет), и «нет данных» молча
# становилось «нет»: при `fallback_used=true` red-flags игнорировал ВСЕ флаги, а
# отсутствующий файл давал «not triggered», и статус писал «all triggers clear».
# Инвариант #17: «не измерено» — отдельное значение. Отсутствие доказательства
# опасности не есть доказательство безопасности — и не повод ликвидировать книгу:
# UNMEASURED не срабатывает стоп-краном, но статус НИКОГДА не «clear», а цикл
# держит позиции и не открывает новых (LAW 1, тот же путь, что у упавшей проверки).
OUTCOME_TRIGGERED = "TRIGGERED"
OUTCOME_CLEAR = "CLEAR"                    # измерено, порог не достигнут
OUTCOME_PARTIAL = "PARTIAL"                # измерено по живым источникам; часть входа — не живая (названа)
OUTCOME_NOT_APPLICABLE = "NOT_APPLICABLE"  # триггер ещё не применим: нет доказательного ряда / малая выборка
OUTCOME_UNMEASURED = "UNMEASURED"          # входа нет / протух / нечитаем / весь не живой
#: Свежесть red_flags.json как ВХОДА стоп-крана — объявленное окно живости его
#: производителя (`spa_core/monitoring/uptime_monitor.AGENT_OUTPUT_FILES`,
#: `com.spa.red_flag_monitor` → 1800 с: 5-минутный монитор старше 30 мин считается
#: мёртвым). Паритет держит тест; второго значения нет. `slo_hours` 3.0 манифеста —
#: другой вопрос («артефакт просрочен»), не «наблюдение ещё текущее».
RED_FLAGS_MAX_AGE_S = 1800

KILL_SWITCH_ACTIVE_FILENAME = "kill_switch_active.json"
KILL_SWITCH_STATUS_FILENAME = "kill_switch_status.json"
DERISK_STATUS_FILENAME = "derisk_status.json"  # soft-tier de-risk state (ADR-034)

# Drawdown-tier enum values (strings, not an Enum, to stay stdlib-trivial and
# JSON-serialisable). The three mutually-exclusive states of the evidenced
# drawdown ladder.
TIER_NONE = "NONE"              # drawdown < SOFT_DERISK_THRESHOLD_PCT → no action
TIER_SOFT_DERISK = "SOFT_DERISK"  # SOFT ≤ drawdown < HARD (5–10%) → halt new/increase
TIER_HARD_KILL = "HARD_KILL"   # drawdown ≥ DRAWDOWN_THRESHOLD_PCT (10%) → all-cash
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


def _load_held_protocols_or_none(data_dir: Path) -> set[str] | None:
    """Как ``_load_held_protocols``, но нечитаемый/отсутствующий файл позиций — ``None``.

    Пустое множество означает «измерено: ничего не держим» (в т.ч. файла ещё нет — первый
    цикл, тот же смысл, что у самого цикла); ``None`` — файл есть, но не читается.
    Раньше обе ситуации были пустым множеством, и CRITICAL-флаг на настоящей позиции
    молча не считался, когда файл позиций не читался (ADR-531).
    """
    path = data_dir / POSITIONS_FILENAME
    if not path.exists():
        return set()   # книги ещё нет (первый цикл) — измерено: ничего не держим
    doc = _read_json(path, None)
    if not isinstance(doc, (dict, list)):
        return None    # файл есть, но не читается — НЕ измерено
    return _load_held_protocols(data_dir)


def split_live_red_flags(doc: dict) -> tuple[list[dict], list[dict]]:
    """``(живые, исключённые)`` флаги документа red_flags — ЕДИНОЕ правило (стоп-кран и
    внутридневной реактор зовут его оба, второй копии нет; ADR-531).

    Флаг живой, только если (а) его собственный ``source`` не ``bootstrap`` И (б) его
    категория по ИЗМЕРЕННОЙ провенансной карте монитора (``provenance.by_category``) —
    ``live``. Категория без записи в карте — не живая (не измерена). У документа без
    провенансной карты (старый формат) действует только (а); если такой документ сам
    помечен ``fallback_used``, флаг без названного источника живым не считается.

    Почему (б): у флага ``token_unlock`` с ``source: defillama`` вся категория в тот же
    день была ``bootstrap`` (фикстура базы) — по одному полю флага его посчитали бы живым
    и могли бы ложно закрыть книгу. «Живое» решает измерение монитора, а не ярлык строки.
    """
    flags = [f for f in (doc.get("red_flags") or []) if isinstance(f, dict)]
    prov = doc.get("provenance")
    by_cat = prov.get("by_category") if isinstance(prov, dict) else None
    live, excluded = [], []
    for f in flags:
        src = f.get("source")
        if isinstance(by_cat, dict):
            ok = src != "bootstrap" and by_cat.get(str(f.get("category", ""))) == "live"
        elif doc.get("fallback_used"):
            # документ сам говорит «часть данных — подстановка», карты нет: флаг без
            # названного живого источника — живость НЕ ИЗВЕСТНА, по нему не стреляют
            ok = bool(src) and src != "bootstrap"
        else:
            ok = src != "bootstrap"
        (live if ok else excluded).append(f)
    return live, excluded


def _parse_ts(value: Any) -> datetime | None:
    """ISO-время → aware UTC; нечитаемо ⇒ None (третий исход, а не «сейчас»)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


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


def classify_drawdown_pct(drawdown_pct: float | None) -> tuple[str, str]:
    """Pure tier classifier over a raw drawdown PERCENTAGE — the SINGLE source of
    truth for the TWO-TIER ladder boundaries (ADR-034 + ADR-048).

    This is the one place the tier *boundaries* and *constants*
    (``SOFT_DERISK_THRESHOLD_PCT`` / ``DRAWDOWN_THRESHOLD_PCT``) are applied.
    Both the governance equity-curve path (:func:`drawdown_tier`) and the
    EXECUTION pre-trade gate (``PreExecutionSafety.check_not_in_kill_switch``)
    classify through THIS function, so they can never diverge on either the
    threshold VALUES or the half-open band semantics.

    Tier boundaries (monotone, half-open intervals — exhaustive, non-overlapping,
    both boundaries INCLUSIVE on the upper tier so the ladder AGREES at exactly
    5.0% / 10.0%):
        drawdown < SOFT (5%)              → TIER_NONE
        SOFT (5%) ≤ drawdown < HARD (10%) → TIER_SOFT_DERISK
        drawdown ≥ HARD (10%)             → TIER_HARD_KILL

    Parameters
    ----------
    drawdown_pct : float | None
        The drawdown as a PERCENTAGE (e.g. ``7.5`` for 7.5%), already ≥ 0.
        ``None`` (cannot be computed) → ``TIER_NONE`` (the per-tier gates are the
        fail-closed authority; never fabricate a more severe tier from no data).
    """
    dd = drawdown_pct
    if dd is None or not math.isfinite(dd):
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


def drawdown_tier(equity_curve: list[dict]) -> tuple[str, str]:
    """Classify the evidenced drawdown into the TWO-TIER ladder (ADR-034).

    Deterministic, fail-CLOSED, evidenced-bars-only, non-finite-safe — it is a
    thin classifier composing :func:`evidenced_drawdown_pct` with the shared
    boundary classifier :func:`classify_drawdown_pct` (the single source of the
    threshold constants).

    Tier boundaries (monotone, half-open intervals so the ladder is exhaustive
    and non-overlapping):
        drawdown < SOFT (5%)            → TIER_NONE
        SOFT (5%) ≤ drawdown < HARD(10%)→ TIER_SOFT_DERISK
        drawdown ≥ HARD (10%)           → TIER_HARD_KILL

    When the drawdown cannot be computed (insufficient / corrupt evidenced data)
    the tier is ``TIER_NONE`` — the per-tier gates (the existing drawdown kill
    trigger and the soft de-risk gate) are themselves the fail-closed authority;
    this classifier never *fabricates* a more severe tier from missing data.

    Returns
    -------
    (tier, reason) : (str, str)
        ``tier`` ∈ {TIER_NONE, TIER_SOFT_DERISK, TIER_HARD_KILL}.
    """
    return classify_drawdown_pct(evidenced_drawdown_pct(equity_curve))


# ─── KillSwitchChecker ────────────────────────────────────────────────────────


class KillSwitchChecker:
    """Проверяет все 4 триггера kill-switch.

    Parameters
    ----------
    data_dir : путь к папке data/ (по умолчанию <repo>/data)
    """

    def __init__(self, data_dir: str | os.PathLike | None = None, *,
                 now: datetime | None = None) -> None:
        # Время — вход (свежесть red_flags), а не окружение: тест передаёт `now`.
        self._now = now
        self._sharpe_outcome = OUTCOME_UNMEASURED
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
        fabricate a drawdown that closes the honest go-live track.

        THRESHOLD (ADR-048, owner-approved 2026-06-27): the HARD kill fires at
        ``drawdown >= DRAWDOWN_THRESHOLD_PCT`` (now 10%). The boundary is now
        INCLUSIVE (``>=``, was strictly ``>``) so it AGREES with
        :func:`drawdown_tier` — at EXACTLY 10.0% both the classifier and the
        trigger fire the all-cash kill (the previous 0-width 15.0% gap between
        the ``>=`` classifier and the ``>`` trigger is closed).

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

        # HARD tier (≥ DRAWDOWN_THRESHOLD_PCT) → full kill. Boundary is INCLUSIVE
        # (>=) so the trigger AGREES with drawdown_tier() at exactly 10.0%
        # (ADR-048) — exactly-10% DOES fire the all-cash kill.
        if drawdown_pct >= DRAWDOWN_THRESHOLD_PCT:
            reason = (
                f"drawdown {drawdown_pct:.2f}% ≥ {DRAWDOWN_THRESHOLD_PCT}% threshold "
                f"(window={LOOKBACK_DAYS}d)"
            )
            log.warning("KILL SWITCH drawdown trigger: %s", reason)
            return True, reason

        return False, f"drawdown {drawdown_pct:.2f}% < {DRAWDOWN_THRESHOLD_PCT}%"

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
        outcome, reason = self.evaluate_red_flags()
        return outcome == OUTCOME_TRIGGERED, reason

    def evaluate_red_flags(self) -> tuple[str, str]:
        """Исход red-flags-триггера: TRIGGERED / CLEAR / PARTIAL / UNMEASURED (ADR-531).

        Таблица истинности (порог `RED_FLAGS_THRESHOLD` и правило «CRITICAL на
        удерживаемом протоколе» НЕ менялись):

        ============================================  =============
        вход                                          исход
        ============================================  =============
        файла нет / не JSON / не dict / нет списка     UNMEASURED
        нет или нечитаем ``generated_at``              UNMEASURED
        старше ``RED_FLAGS_MAX_AGE_S``                 UNMEASURED
        все источники bootstrap / ни одной живой категории  UNMEASURED
        позиции книги нечитаемы                        UNMEASURED
        > порога CRITICAL-на-удерживаемом (живые)      TRIGGERED
        ``fallback_used`` / часть флагов не живая      PARTIAL (живые посчитаны, остальные названы)
        только WARN / CRITICAL не на наших / ≤ порога  CLEAR
        ============================================  =============

        Раньше ``fallback_used=true`` отбрасывал ВСЕ флаги, включая живые категории
        (tvl_drop, governance) — живой CRITICAL на удерживаемом протоколе не мог
        сработать. Теперь живость решается по флагу и его категории
        (:func:`split_live_red_flags`).
        """
        path = self.data_dir / RED_FLAGS_FILENAME
        if not path.exists():
            return OUTCOME_UNMEASURED, f"{RED_FLAGS_FILENAME} missing — red flags UNMEASURED"
        doc = _read_json(path, None)
        if not isinstance(doc, dict):
            return OUTCOME_UNMEASURED, f"{RED_FLAGS_FILENAME} unreadable or not an object — UNMEASURED"
        flags = doc.get("red_flags")
        if not isinstance(flags, list):
            return OUTCOME_UNMEASURED, f"no red_flags list in {RED_FLAGS_FILENAME} — UNMEASURED"
        gen = _parse_ts(doc.get("generated_at"))
        if gen is None:
            return OUTCOME_UNMEASURED, f"{RED_FLAGS_FILENAME} has no readable generated_at — UNMEASURED"
        now = self._now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        age_s = (now - gen).total_seconds()
        if age_s < -300:
            return OUTCOME_UNMEASURED, (
                f"{RED_FLAGS_FILENAME} is dated {-age_s / 60:.0f} min in the future — clock skew, UNMEASURED")
        if age_s > RED_FLAGS_MAX_AGE_S:
            return OUTCOME_UNMEASURED, (
                f"{RED_FLAGS_FILENAME} is {age_s / 60:.0f} min old > {RED_FLAGS_MAX_AGE_S // 60} min — "
                "stale, UNMEASURED")

        # Читаем параметры из risk_policy.json (с fallback на compile-time defaults)
        policy = _read_json(self.data_dir / "risk_policy.json", {})
        if not isinstance(policy, dict):
            policy = {}
        ignore_bootstrap: bool = bool(policy.get("RED_FLAGS_IGNORE_BOOTSTRAP", True))
        threshold: int = int(policy.get("RED_FLAGS_THRESHOLD", RED_FLAGS_THRESHOLD))

        dict_flags = [f for f in flags if isinstance(f, dict)]
        doc_fallback = bool(doc.get("fallback_used", False))
        doc_sources = doc.get("sources", [])
        doc_is_bootstrap = (isinstance(doc_sources, list) and len(doc_sources) > 0
                            and set(doc_sources) <= {"bootstrap"})
        if ignore_bootstrap:
            live_flags, excluded = split_live_red_flags(doc)
            # НЕ ИЗМЕРЕНО — только когда ни одна категория не измерена вживую. Живые
            # категории без флагов — это измеренное «чисто», а не пустота (замер 01.10:
            # tvl_drop и governance живые и пустые, все 4 флага — из bootstrap-категорий;
            # считать такой документ «не измерено» значило бы держать книгу каждый день).
            prov = doc.get("provenance")
            by_cat = prov.get("by_category") if isinstance(prov, dict) else None
            no_live_category = (isinstance(by_cat, dict)
                                and not any(v == "live" for v in by_cat.values()))
            # документ сам говорит «подстановка», карты нет и ни одного флага с живым
            # источником — живого наблюдения нет вовсе (review ADR-531 S6)
            if not isinstance(by_cat, dict) and doc_fallback and not live_flags:
                no_live_category = True
            if doc_is_bootstrap or no_live_category:
                return OUTCOME_UNMEASURED, (
                    f"red_flags: no category measured live — {len(dict_flags)} flag(s) ignored "
                    f"(fallback_used={doc_fallback}, sources={doc_sources}, provenance={by_cat}) — "
                    "UNMEASURED")
        else:
            live_flags, excluded = dict_flags, []

        held = _load_held_protocols_or_none(self.data_dir)
        if held is None:
            return OUTCOME_UNMEASURED, (
                f"{POSITIONS_FILENAME} unreadable — cannot tell which flags hit held protocols, "
                "UNMEASURED")
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
            return OUTCOME_TRIGGERED, reason

        base = (f"red_flags count {count} ≤ {threshold} "
                f"(CRITICAL-on-held; {len(live_flags)} live flag(s), {len(held)} held protocol(s))")
        if doc_fallback or excluded:
            cats = sorted({str(f.get("category", "?")) for f in excluded})
            return OUTCOME_PARTIAL, (
                f"{base}; PARTIAL — fallback_used={doc_fallback}, {len(excluded)} non-live flag(s) "
                f"not counted (categories {cats})")
        return OUTCOME_CLEAR, base

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
        """Sharpe < threshold computed STRICTLY over the EVIDENCED equity series.

        HONESTY PARITY (WS-2.3, 2026-06-28): the Sharpe trigger now reads the
        SAME evidenced real series as the drawdown trigger — it no longer reads
        the NON-evidenced ``analytics_summary.json`` (which spans warmup /
        backfill / pre-anchor bars and would let a fabricated pre-teardown wobble
        drive the kill). Sharpe is recomputed from ``equity_curve_daily.json``'s
        evidenced bars via :func:`track_evidence.real_sharpe_ratio`, fail-CLOSED
        exactly like ``check_drawdown_trigger``.

        Логика порогов (Variant A + B, ADR-ref risk_policy.json):
        - rf=0% (стейблкоин портфель): Sharpe считается с RISK_FREE_RATE=0.0 —
          benchmark «держать USDC», не Treasury bills.
        - Early-period grace: если evidenced num_days < SHARPE_EARLY_PERIOD_DAYS
          (60), используется мягкий порог SHARPE_EARLY_THRESHOLD (-2.0) вместо
          нормального SHARPE_THRESHOLD (-1.0).

        Малая выборка → THIN/UNKNOWN: real_sharpe_ratio returns ``None`` below
        MIN_EVIDENCED_RETURNS_FOR_SHARPE evidenced returns (no degenerate
        small-sample Sharpe) → fail-CLOSED to "no kill".

        Returns
        -------
        (triggered, reason)
        """
        # Read the EVIDENCED equity series (single source of truth) — never the
        # non-evidenced analytics_summary.json roll-up.
        equity_doc = _read_json(self.data_dir / "equity_curve_daily.json", {})
        daily = equity_doc.get("daily") if isinstance(equity_doc, dict) else None
        if not isinstance(daily, list) or not daily:
            self._sharpe_outcome = OUTCOME_NOT_APPLICABLE
            return False, "no equity data for evidenced sharpe — NOT_APPLICABLE"

        # Honest evidenced count drives the early-period / min-days gating.
        ev_returns = evidenced_daily_returns(daily, paper_start=PAPER_REAL_START)
        num_days = float(len(ev_returns) + 1)  # bars = returns + 1

        # rf from risk_policy.json (default 0.0 for the stablecoin book).
        policy = _read_json(self.data_dir / "risk_policy.json", {})
        if not isinstance(policy, dict):
            policy = {}
        try:
            rf_rate = float(policy.get("SHARPE_RISK_FREE_RATE", 0.0))
        except (TypeError, ValueError):
            rf_rate = 0.0

        sharpe = real_sharpe_ratio(
            daily, paper_start=PAPER_REAL_START, risk_free_rate=rf_rate
        )
        # THIN/UNKNOWN (None) → not enough evidenced returns, or degenerate
        # dispersion. Fail-CLOSED: never kill on an undefined Sharpe.
        if sharpe is None:
            self._sharpe_outcome = OUTCOME_NOT_APPLICABLE
            return False, (
                f"evidenced sharpe THIN/UNKNOWN — {len(ev_returns)} evidenced "
                f"return(s) < min required (fail-closed, no kill)"
            )
        sharpe_val = float(sharpe)

        if num_days < MIN_DAYS_FOR_SHARPE:
            self._sharpe_outcome = OUTCOME_NOT_APPLICABLE
            return False, (
                f"evidenced sharpe {sharpe_val:.4f} — insufficient data "
                f"({num_days:.0f} evidenced days < {MIN_DAYS_FOR_SHARPE} required)"
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
                f"evidenced sharpe {sharpe_val:.4f} < {effective_threshold} "
                f"[{period_label}] (computed over evidenced equity series)"
            )
            log.warning("KILL SWITCH sharpe trigger: %s", reason)
            self._sharpe_outcome = OUTCOME_TRIGGERED
            return True, reason

        self._sharpe_outcome = OUTCOME_CLEAR
        return False, (
            f"evidenced sharpe {sharpe_val:.4f} >= {effective_threshold} "
            f"[{period_label}]"
        )

    # ── Main check ────────────────────────────────────────────────────────────

    def evaluate_triggers(self, equity_curve: list[dict] | None = None) -> list[dict]:
        """Исход КАЖДОГО триггера: ``[{"trigger", "outcome", "reason"}]`` (ADR-531).

        Порядок: manual → drawdown → red_flags → sharpe (тот же, что был).
        """
        out: list[dict] = []
        trig, why = self.check_manual_trigger()
        out.append({"trigger": "manual", "outcome": OUTCOME_TRIGGERED if trig else OUTCOME_CLEAR,
                    "reason": why})

        curve_unreadable = False
        if equity_curve is None:
            _ep = self.data_dir / "equity_curve_daily.json"
            equity_doc = _read_json(_ep, None)
            # файл есть, но не читается — это НЕ «трек ещё не начался» (review ADR-531 S7)
            curve_unreadable = _ep.exists() and not isinstance(equity_doc, dict)
            equity_curve = (equity_doc.get("daily") or []) if isinstance(equity_doc, dict) else []
        # Всегда через check_drawdown_trigger (его исключение обязано всплыть, а не
        # стать «чисто»); «не сработал» без доказательного ряда — UNMEASURED.
        trig, why = self.check_drawdown_trigger(equity_curve)
        if trig:
            out.append({"trigger": "drawdown", "outcome": OUTCOME_TRIGGERED, "reason": why})
        elif curve_unreadable:
            out.append({"trigger": "drawdown", "outcome": OUTCOME_UNMEASURED,
                        "reason": "equity_curve_daily.json present but unreadable — drawdown UNMEASURED"})
        elif not equity_curve or not isinstance(equity_curve, list) or \
                evidenced_drawdown_pct(equity_curve) is None:
            # Нет доказательного ряда (начало трека) — триггер ещё не применим: назван,
            # не «clear» и не повод держать (иначе новая книга не развернулась бы никогда).
            out.append({"trigger": "drawdown", "outcome": OUTCOME_NOT_APPLICABLE,
                        "reason": f"no evidenced drawdown series yet — NOT_APPLICABLE ({why})"})
        else:
            out.append({"trigger": "drawdown", "outcome": OUTCOME_CLEAR, "reason": why})

        outcome, why = self.evaluate_red_flags()
        out.append({"trigger": "red_flags", "outcome": outcome, "reason": why})

        self._sharpe_outcome = OUTCOME_UNMEASURED
        trig, why = self.check_sharpe_trigger()
        out.append({"trigger": "sharpe",
                    "outcome": OUTCOME_TRIGGERED if trig else self._sharpe_outcome, "reason": why})
        return out

    @staticmethod
    def summarize(results: list[dict]) -> tuple[bool, str, str]:
        """``(triggered, state, reason)`` из исходов триггеров.

        state: ``TRIGGERED`` (первый сработавший) · ``UNMEASURED`` (хоть один не измерен —
        «clear» НЕ пишется) · ``CLEAR_PARTIAL`` (всё измерено, но часть входа не живая или
        триггер ещё не применим — названо) · ``CLEAR`` (всё измерено и чисто — только тогда
        «all triggers clear»).
        """
        for r in results:
            if r["outcome"] == OUTCOME_TRIGGERED:
                return True, OUTCOME_TRIGGERED, r["reason"]
        unm = [r for r in results if r["outcome"] == OUTCOME_UNMEASURED]
        if unm:
            return False, OUTCOME_UNMEASURED, "UNMEASURED — not all-clear: " + "; ".join(
                f"{r['trigger']}: {r['reason']}" for r in unm)
        part = [r for r in results if r["outcome"] in (OUTCOME_PARTIAL, OUTCOME_NOT_APPLICABLE)]
        if part:
            return False, "CLEAR_PARTIAL", "no trigger fired; partial: " + "; ".join(
                f"{r['trigger']} {r['outcome']}: {r['reason']}" for r in part)
        return False, OUTCOME_CLEAR, "all triggers clear"

    def is_kill_switch_active(
        self, equity_curve: list[dict] | None = None
    ) -> tuple[bool, str]:
        """``(active, reason)``: первый сработавший триггер; иначе — состояние (ADR-531).

        «all triggers clear» возвращается ТОЛЬКО когда каждый триггер измерен и чист;
        не измеренный вход называется в причине (``UNMEASURED — …``), а не прячется.
        Порядок проверки: manual → drawdown → red_flags → sharpe.
        """
        triggered, _state, reason = self.summarize(self.evaluate_triggers(equity_curve))
        return triggered, reason

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
    *,
    now: datetime | None = None,
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
        state       : str  (TRIGGERED / UNMEASURED / CLEAR_PARTIAL / CLEAR, ADR-531)
        unmeasured  : list[str] — триггеры без измерения
        triggers    : list[dict] — исход каждого триггера
        reason      : str
        allocation  : dict (all-cash при triggered=True, иначе {})
        ts          : str (ISO timestamp)
    """
    checker = KillSwitchChecker(data_dir=data_dir, now=now)
    now_ts = (now or datetime.now(timezone.utc)).isoformat()

    results = checker.evaluate_triggers(equity_curve=equity_curve)
    triggered, state, reason = checker.summarize(results)

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
            "state": state,
            "reason": reason,
            "triggers": results,
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
            "state": state,
            "reason": reason,
            "triggers": results,
            "allocation": {},
        }
        try:
            _atomic_write_json(checker.data_dir / KILL_SWITCH_STATUS_FILENAME, status_doc)
        except Exception as exc:
            log.warning("Failed to write kill_switch_status.json: %s", exc)

    return {
        "triggered": triggered,
        # ADR-531: TRIGGERED / UNMEASURED / CLEAR_PARTIAL / CLEAR. UNMEASURED не срабатывает
        # стоп-краном, но вызывающий обязан держать позиции (cycle_runner LAW 1).
        "state": state,
        "unmeasured": [r["trigger"] for r in results if r["outcome"] == OUTCOME_UNMEASURED],
        "triggers": results,
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
