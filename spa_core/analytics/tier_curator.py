"""tier_curator — отчёт тир-кураторов (Y4, слой Head-of-Investment, ADR-055
«тир — динамический»): каждый цикл СОВЕТУЕТ, кого демоутить/промоутить.

╔════════════════════════════════════════════════════════════════════════╗
║ ADVISORY-ONLY. Этот модуль и его отчёт data/tier_curator_report.json   ║
║ НИКОГДА не меняют тир протокола, не гейтят исполнение и не двигают     ║
║ капитал. DEMOTE_SIGNAL — сигнал владельцу/системе, НЕ действие.        ║
║ Автоматический демоушен/промоушен по этому файлу требует ОТДЕЛЬНОГО    ║
║ ADR (и промоушен в T1 всегда owner-gated по ADR-055). Любой код,       ║
║ читающий этот отчёт для изменения tier_map / RiskPolicy / аллокации,   ║
║ нарушает инвариант и должен быть отклонён на ревью.                    ║
╚════════════════════════════════════════════════════════════════════════╝

Роль (ADR-055 §1 «Кураторы тиров»): периодически пере-проверять метрики
(TVL с провенансом, надёжность фида, Tier-A риск-сигналы, стабильность APY)
и ПРЕДЛАГАТЬ движение T3→T2→T1 при устойчивом соответствии критериям и
обратно при деградации. Деградация — немедленный сигнал (fail-CLOSED);
промоушен — только рекомендация после N дней стабильности.

Вердикты по каждому протоколу живой вселенной:
* DEMOTE_SIGNAL     — деградация: Tier-A BLOCK (score>70, живое событие),
                      фид мёртв/стал stale, TVL-провенанс пропал у ДЕРЖИМОЙ
                      позиции, живой TVL < floor RiskPolicy, живой APY вне
                      границ политики. Fail-CLOSED: сомнение трактуется
                      против протокола, не в его пользу.
* PROMOTE_CANDIDATE — T2/T3 с полным пакетом доказательств: свежий Tier-A
                      «OK» (не «нет записи»!), живой TVL ≥ 5×floor,
                      ≥ PROMOTE_MIN_DAYS точек APY с коэффициентом вариации
                      ≤ PROMOTE_MAX_CV в границах политики, Tier-B композит
                      (если есть) ≤ порога. Отсутствие ЛЮБОГО доказательства
                      блокирует промоушен — недостающие данные никогда не
                      считаются «чистыми».
* KEEP              — есть живые доказательства, демоут-сигналов нет,
                      промоушен-пакет не собран (причины перечислены).
* UNCHECKED         — доказательств НЕТ (нет живого провенанса, Tier-A не
                      оценивал, ряда нет). Сознательно НЕ «KEEP»: молчание
                      данных — не подтверждение тира (fail-CLOSED, класс
                      fail-OPEN #29 наоборот).

Источники (все read-only, только data/):
  adapter_orchestrator_status.json — тир/живой TVL+провенанс/статус фида;
  adapter_status.json              — широкая вселенная (тир int, active);
  current_positions.json           — держимые позиции + feed_coverage
                                     (apy_sources / tvl_sources);
  analytics_signals_blocking.json  — Tier-A worst-wins (BLOCK/WARN/OK);
  analytics_signals_advisory.json  — Tier-B композит (advisory);
  _apy_series                      — ряды APY (стабильность);
  _protocol_facts                  — структурные константы (справочно).

Пороги НЕ выдуманы: floor/APY-границы импортируются из RiskConfig v1.0
(read-only, менять их здесь нельзя — это отдельный ADR), Tier-A пороги —
из signal_aggregator (ADR-031, 40/70).

Запись: сам curate() ничего не пишет. Писатель — ТОЛЬКО вызывающий
(дневной цикл) через write_report() → atomic_save.

stdlib-only · детерминированный · LLM FORBIDDEN · read-only по data/.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.analytics import _apy_series
from spa_core.analytics._protocol_facts import facts_for
from spa_core.analytics.signal_aggregator import BLOCK_THRESHOLD, WARN_THRESHOLD
from spa_core.risk.policy import RiskConfig

log = logging.getLogger("spa.analytics.tier_curator")

CURATOR_VERSION = "tier_curator_v1"
REPORT_FILENAME = "tier_curator_report.json"

ORCH_FILE = "adapter_orchestrator_status.json"
ADAPTER_STATUS_FILE = "adapter_status.json"
POSITIONS_FILE = "current_positions.json"
TIER_A_FILE = "analytics_signals_blocking.json"
TIER_B_FILE = "analytics_signals_advisory.json"

VERDICT_KEEP = "KEEP"
VERDICT_DEMOTE = "DEMOTE_SIGNAL"
VERDICT_PROMOTE = "PROMOTE_CANDIDATE"
VERDICT_UNCHECKED = "UNCHECKED"

# ── Пороги кураторов ─────────────────────────────────────────────────────────
_CFG = RiskConfig()                     # read-only снимок политики v1.0
TVL_FLOOR_USD = float(_CFG.min_tvl_usd)             # $5M — вход по политике
APY_MIN_PCT = float(_CFG.min_apy_for_new_position)  # 1%
APY_MAX_PCT = float(_CFG.max_apy_for_new_position)  # 30%

# Промоушен требует ЗАПАСА над минимумом входа: floor — это «пустили на
# порог», повышение тира — «доказал прочность». 5×floor = $25M выбран как
# порядок величины, отделяющий на живой вселенной глубокие рынки (yearn
# $26.6M, maple $2.65B, aave $172M) от пограничных (euler $8.5M, pendle
# $8.3M) — пограничным до промоушена нужно вырасти, а не проскочить.
PROMOTE_TVL_MULT = 5.0
PROMOTE_TVL_USD = TVL_FLOOR_USD * PROMOTE_TVL_MULT

# ADR-055: paper-каданс промоушена «≥N дней подряд по критериям»
# (на реальных активах 14–30 дней) — берём нижнюю границу реального
# диапазона, чтобы paper-рекомендация не была слабее будущей боевой.
PROMOTE_MIN_DAYS = 14
PROMOTE_WINDOW = 30            # окно стабильности — последние 30 точек
PROMOTE_MAX_CV = 0.30          # std/mean в окне: «стабильный live-APY»

# Tier-B композит advisory; >50 = хуже нейтрального (движки центруют ~40-50
# на живой вселенной: сегодня 40.1–41.1) — промоушен при худшем-чем-нейтраль
# композите не рекомендуем.
TIERB_MAX_COMPOSITE = 50.0

# Свежесть доказательств: старше 48h — не доказательство (двое суток
# покрывают выходной цикла; дальше — это уже прошлое, fail-CLOSED).
EVIDENCE_MAX_AGE_H = 48.0

_ADVISORY_NOTE = (
    "ADVISORY-ONLY: report never changes tiers, never gates execution, "
    "never moves capital. DEMOTE_SIGNAL is a signal to the owner/system, "
    "not an action; auto-demotion requires a separate ADR; T1 promotion "
    "is owner-gated (ADR-055)."
)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_fresh(ts: Optional[datetime], now: datetime) -> bool:
    if ts is None:
        return False
    return (now - ts) <= timedelta(hours=EVIDENCE_MAX_AGE_H)


def _tier_str(raw: Any) -> Optional[str]:
    """'T1'/'T2'/'T3' из строки или int; None если не распознан."""
    if isinstance(raw, str):
        t = raw.strip().upper()
        return t if t in ("T1", "T2", "T3") else None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)) and int(raw) in (1, 2, 3):
        return f"T{int(raw)}"
    return None


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


# ─────────────────────────────────────────────────────────────────────────────
# Сбор фактов (read-only)
# ─────────────────────────────────────────────────────────────────────────────

def _gather(data_dir: Path, now: datetime) -> Dict[str, Any]:
    orch = _load_json(data_dir / ORCH_FILE)
    status = _load_json(data_dir / ADAPTER_STATUS_FILE)
    book = _load_json(data_dir / POSITIONS_FILE)
    tier_a_doc = _load_json(data_dir / TIER_A_FILE)
    tier_b_doc = _load_json(data_dir / TIER_B_FILE)

    orch_rows: Dict[str, dict] = {}
    orch_fresh = False
    if isinstance(orch, dict):
        orch_fresh = _is_fresh(_parse_ts(orch.get("generated_at")), now)
        for row in orch.get("adapters") or []:
            if isinstance(row, dict) and isinstance(row.get("protocol"), str):
                orch_rows[row["protocol"]] = row

    status_rows: Dict[str, dict] = {}
    if isinstance(status, dict) and isinstance(status.get("adapters"), dict):
        for name, info in status["adapters"].items():
            if isinstance(info, dict):
                status_rows[str(name)] = info

    held: Dict[str, float] = {}
    feed_tvl_sources: Dict[str, str] = {}
    feed_apy_sources: Dict[str, str] = {}
    book_fresh = False
    if isinstance(book, dict):
        book_fresh = _is_fresh(_parse_ts(book.get("generated_at")), now)
        for k, v in (book.get("positions") or {}).items():
            fv = _num(v)
            if fv is not None and fv > 0:
                held[str(k)] = fv
        fc = book.get("feed_coverage") or {}
        if isinstance(fc, dict):
            if isinstance(fc.get("tvl_sources"), dict):
                feed_tvl_sources = {str(k): str(v)
                                    for k, v in fc["tvl_sources"].items()}
            if isinstance(fc.get("apy_sources"), dict):
                feed_apy_sources = {str(k): str(v)
                                    for k, v in fc["apy_sources"].items()}

    tier_a: Dict[str, dict] = {}
    tier_a_fresh = False
    if isinstance(tier_a_doc, dict):
        tier_a_fresh = _is_fresh(_parse_ts(tier_a_doc.get("generated_at")), now)
        sig = tier_a_doc.get("signals") or tier_a_doc.get("protocols") or {}
        if isinstance(sig, dict):
            for k, v in sig.items():
                if isinstance(v, dict):
                    tier_a[str(k)] = v

    tier_b: Dict[str, dict] = {}
    if isinstance(tier_b_doc, dict):
        sig = tier_b_doc.get("signals") or tier_b_doc.get("protocols") or {}
        if isinstance(sig, dict):
            for k, v in sig.items():
                if isinstance(v, dict):
                    tier_b[str(k)] = v

    return {
        "orch_rows": orch_rows, "orch_fresh": orch_fresh,
        "status_rows": status_rows,
        "held": held, "book_fresh": book_fresh,
        "feed_tvl_sources": feed_tvl_sources,
        "feed_apy_sources": feed_apy_sources,
        "tier_a": tier_a, "tier_a_fresh": tier_a_fresh,
        "tier_b": tier_b,
    }


def _universe(f: Dict[str, Any]) -> List[str]:
    """Живая вселенная: оркестратор ∪ adapter_status ∪ позиции ∪ Tier-A."""
    names = set(f["orch_rows"]) | set(f["status_rows"]) | set(f["held"]) | set(f["tier_a"])
    return sorted(names)


def _series_stats(proto: str, data_dir: Path) -> Optional[Dict[str, Any]]:
    try:
        return _apy_series.stats(proto, min_days=2, window=PROMOTE_WINDOW,
                                 data_dir=data_dir)
    except Exception:  # noqa: BLE001 — ряд не обязан существовать
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Вердикт по одному протоколу
# ─────────────────────────────────────────────────────────────────────────────

def _verdict_for(proto: str, f: Dict[str, Any], data_dir: Path
                 ) -> Dict[str, Any]:
    orch_row = f["orch_rows"].get(proto)
    status_row = f["status_rows"].get(proto)
    ta = f["tier_a"].get(proto)
    tb = f["tier_b"].get(proto)
    held_usd = float(f["held"].get(proto, 0.0))
    is_held = held_usd > 0

    # Текущий тир: оркестратор (строка) > adapter_status (int) > UNKNOWN.
    current_tier = None
    tier_source = None
    if orch_row is not None:
        current_tier = _tier_str(orch_row.get("tier"))
        if current_tier:
            tier_source = "orchestrator"
    if current_tier is None and status_row is not None:
        current_tier = _tier_str(status_row.get("tier"))
        if current_tier:
            tier_source = "adapter_status"
    if current_tier is None:
        current_tier, tier_source = "UNKNOWN", "none"

    # Живой TVL: только оркестраторный ряд со свежим generated_at и
    # tvl_source == "live" (ADR-053: static-литералы floor НЕ проходят).
    tvl_usd: Optional[float] = None
    tvl_live = False
    if orch_row is not None and f["orch_fresh"]:
        if orch_row.get("tvl_source") == "live":
            tvl_usd = _num(orch_row.get("tvl_usd"))
            tvl_live = tvl_usd is not None
    # Провенанс из feed_coverage книги (для протоколов вне оркестратора).
    feed_tvl = f["feed_tvl_sources"].get(proto)
    feed_apy = f["feed_apy_sources"].get(proto)
    if not f["book_fresh"]:
        feed_tvl = feed_apy = None  # протухшая книга — не доказательство

    apy_pct = _num(orch_row.get("apy_pct")) if orch_row else None
    feed_dead = bool(
        orch_row is not None and f["orch_fresh"]
        and (orch_row.get("status") == "error"
             or orch_row.get("live_data") is False)
    )

    stats = _series_stats(proto, data_dir)
    facts = None
    try:
        facts = facts_for(proto)
    except Exception:  # noqa: BLE001
        facts = None

    evidence: Dict[str, Any] = {
        "held_usd": held_usd,
        "tier_source": tier_source,
        "tvl_usd": tvl_usd,
        "tvl_provenance": ("live" if tvl_live
                           else (feed_tvl or ("dead_feed" if feed_dead else "missing"))),
        "apy_pct": apy_pct,
        "apy_provenance": feed_apy or ("live" if (orch_row and f["orch_fresh"]
                                                  and orch_row.get("live_data")) else "missing"),
        "tier_a": (dict(ta) if ta else {"status": "not_evaluated"}),
        "tier_a_fresh": bool(ta and f["tier_a_fresh"]),
        "tier_b_composite": (_num(tb.get("composite_risk_0_100")) if tb else None),
        "apy_series": (
            {"n": stats["n"], "mean": round(stats["mean"], 4),
             "std": round(stats["std"], 4),
             "cv": (round(stats["std"] / stats["mean"], 4)
                    if stats["mean"] else None),
             "last_date": stats["last_date"], "window": PROMOTE_WINDOW}
            if stats else None),
        "structural": ({"kind": facts.get("kind"), "chain": facts.get("chain")}
                       if isinstance(facts, dict) else None),
    }

    # ── 1. Демоут-сигналы (fail-CLOSED, немедленно) ──────────────────────
    demote: List[str] = []
    ta_score = _num(ta.get("score")) if ta else None
    if ta and f["tier_a_fresh"] and (
            ta.get("signal") == "BLOCK"
            or (ta_score is not None and ta_score > BLOCK_THRESHOLD)):
        demote.append(
            f"tier_a_block: score {ta_score} > {BLOCK_THRESHOLD} "
            f"({ta.get('reason')})")
    if feed_dead:
        demote.append(
            "feed_dead: оркестратор видит фид мёртвым "
            f"(status={orch_row.get('status')}, error={orch_row.get('error')})")
    if is_held and not tvl_live and feed_tvl != "live":
        demote.append(
            "held_without_live_tvl: позиция "
            f"${held_usd:,.0f} без живого TVL-провенанса "
            f"(tvl_source={feed_tvl or 'missing'}) — stale-фид ⇒ "
            "демоут-сигнал (ADR-053 fail-CLOSED)")
    if tvl_live and tvl_usd is not None and tvl_usd < TVL_FLOOR_USD:
        demote.append(
            f"tvl_below_floor: живой TVL ${tvl_usd:,.0f} < "
            f"${TVL_FLOOR_USD:,.0f} (RiskPolicy min_tvl_usd)")
    if (apy_pct is not None and orch_row is not None and f["orch_fresh"]
            and orch_row.get("live_data")
            and not (APY_MIN_PCT <= apy_pct <= APY_MAX_PCT)):
        demote.append(
            f"apy_out_of_policy_bounds: живой APY {apy_pct}% вне "
            f"[{APY_MIN_PCT}%, {APY_MAX_PCT}%] RiskPolicy")

    if demote:
        return {"current_tier": current_tier, "verdict": VERDICT_DEMOTE,
                "reasons": demote, "evidence": evidence}

    # ── 2. Промоушен-кандидат (полный пакет доказательств) ──────────────
    promote_blockers: List[str] = []
    if current_tier == "T1":
        promote_blockers.append("already_T1")
    elif current_tier not in ("T2", "T3"):
        promote_blockers.append("tier_unknown")
    if not (ta and f["tier_a_fresh"]):
        promote_blockers.append("tier_a_not_evaluated_fresh")
    elif ta.get("signal") != "OK":
        promote_blockers.append(
            f"tier_a_not_clean: {ta.get('signal')} score {ta_score}")
    if not tvl_live:
        promote_blockers.append("no_live_tvl_provenance")
    elif tvl_usd is None or tvl_usd < PROMOTE_TVL_USD:
        promote_blockers.append(
            f"tvl_below_promote_bar: ${(tvl_usd or 0):,.0f} < "
            f"${PROMOTE_TVL_USD:,.0f} ({PROMOTE_TVL_MULT}×floor)")
    if stats is None or stats["n"] < PROMOTE_MIN_DAYS:
        promote_blockers.append(
            f"apy_history_short: {(stats or {}).get('n', 0)} < "
            f"{PROMOTE_MIN_DAYS} дней")
    else:
        cv = (stats["std"] / stats["mean"]) if stats["mean"] else None
        if cv is None or cv > PROMOTE_MAX_CV:
            promote_blockers.append(
                f"apy_unstable: cv={None if cv is None else round(cv, 3)} > "
                f"{PROMOTE_MAX_CV}")
        if not all(APY_MIN_PCT <= v <= APY_MAX_PCT
                   for v in (stats["min"], stats["max"])):
            promote_blockers.append("apy_window_outside_policy_bounds")
    tbc = evidence["tier_b_composite"]
    if tbc is not None and tbc > TIERB_MAX_COMPOSITE:
        promote_blockers.append(
            f"tier_b_composite_high: {tbc} > {TIERB_MAX_COMPOSITE}")

    if not promote_blockers:
        target = "T1" if current_tier == "T2" else "T2"
        return {"current_tier": current_tier, "verdict": VERDICT_PROMOTE,
                "reasons": [
                    f"stable_apy_{PROMOTE_MIN_DAYS}d+ · live TVL "
                    f"${tvl_usd:,.0f} ≥ {PROMOTE_TVL_MULT}×floor · "
                    "tier_a clean · advisory only"],
                "evidence": evidence,
                "target_tier": target,
                "owner_gated": target == "T1"}

    # ── 3. KEEP требует хоть одного ЖИВОГО доказательства ────────────────
    has_live_evidence = (
        tvl_live
        or feed_tvl == "live"
        or feed_apy == "live"
        or bool(ta and f["tier_a_fresh"])
        or feed_dead  # мёртвый фид — тоже свежее наблюдение (но он демоутит выше)
    )
    if not has_live_evidence:
        return {"current_tier": current_tier, "verdict": VERDICT_UNCHECKED,
                "reasons": ["no_live_evidence: ни живого TVL/APY-провенанса, "
                            "ни свежей Tier-A оценки — молчание данных не "
                            "подтверждает тир (fail-CLOSED)"],
                "evidence": evidence}

    return {"current_tier": current_tier, "verdict": VERDICT_KEEP,
            "reasons": [f"not_promotable: {b}" for b in promote_blockers],
            "evidence": evidence}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def curate(data_dir: Optional[Any] = None,
           now: Optional[datetime] = None) -> Dict[str, Any]:
    """Чистая функция: отчёт кураторов по живой вселенной. Ничего не пишет.

    Возвращает dict с verdicts {protocol: {current_tier, verdict, reasons,
    evidence}} и summary. Пустая/битая data/ → пустые verdicts + honest
    note, никогда не исключение.
    """
    dd = Path(data_dir) if data_dir is not None else (
        Path(__file__).resolve().parent.parent.parent / "data")
    now = now or datetime.now(timezone.utc)

    facts = _gather(dd, now)
    verdicts: Dict[str, Any] = {}
    for proto in _universe(facts):
        try:
            verdicts[proto] = _verdict_for(proto, facts, dd)
        except Exception as exc:  # noqa: BLE001 — один протокол не валит отчёт
            verdicts[proto] = {
                "current_tier": "UNKNOWN", "verdict": VERDICT_UNCHECKED,
                "reasons": [f"curator_error: {type(exc).__name__}: {exc}"],
                "evidence": {}}

    counts = {VERDICT_KEEP: 0, VERDICT_DEMOTE: 0,
              VERDICT_PROMOTE: 0, VERDICT_UNCHECKED: 0}
    held_flagged: List[str] = []
    for proto, v in verdicts.items():
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
        if (v["verdict"] == VERDICT_DEMOTE
                and float((v.get("evidence") or {}).get("held_usd") or 0) > 0):
            held_flagged.append(proto)

    return {
        "schema_version": 1,
        "source": CURATOR_VERSION,
        "generated_at": now.isoformat(),
        "advisory_note": _ADVISORY_NOTE,
        "thresholds": {
            "tvl_floor_usd": TVL_FLOOR_USD,
            "promote_tvl_usd": PROMOTE_TVL_USD,
            "promote_min_days": PROMOTE_MIN_DAYS,
            "promote_window": PROMOTE_WINDOW,
            "promote_max_cv": PROMOTE_MAX_CV,
            "apy_bounds_pct": [APY_MIN_PCT, APY_MAX_PCT],
            "tier_a_block": BLOCK_THRESHOLD,
            "tier_a_warn": WARN_THRESHOLD,
            "tier_b_max_composite": TIERB_MAX_COMPOSITE,
            "evidence_max_age_h": EVIDENCE_MAX_AGE_H,
            "thresholds_source": "RiskConfig v1.0 (read-only) + ADR-031 + ADR-055",
        },
        "verdicts": verdicts,
        "summary": {
            "total": len(verdicts),
            "keep": counts[VERDICT_KEEP],
            "demote_signal": counts[VERDICT_DEMOTE],
            "promote_candidate": counts[VERDICT_PROMOTE],
            "unchecked": counts[VERDICT_UNCHECKED],
            "held_flagged": sorted(held_flagged),
        },
    }


def write_report(data_dir: Optional[Any] = None,
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    """Write-обёртка для вызывающего (дневной цикл): curate + atomic_save.

    ЕДИНСТВЕННОЕ место записи data/tier_curator_report.json. Отчёт —
    advisory; никакой потребитель не вправе менять тир по нему без
    отдельного ADR (см. модульный докстринг).
    """
    from spa_core.utils.atomic import atomic_save
    dd = Path(data_dir) if data_dir is not None else (
        Path(__file__).resolve().parent.parent.parent / "data")
    report = curate(data_dir=dd, now=now)
    atomic_save(report, str(dd / REPORT_FILENAME))
    return report
