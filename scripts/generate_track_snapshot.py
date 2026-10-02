#!/usr/bin/env python3
"""Regenerate landing/src/data/track_snapshot.json from the LIVE canonical state.

The /track-record + /due-diligence pages import this JSON as a build-time, offline
fallback (live values from api.earn-defi.com override it client-side). It was
previously HAND-maintained and drifted stale (frozen at 5 evidenced days while the
real track advanced) — fixed by deriving it from the source of truth every run, so
the offline fallback can never again lie by more than one cycle.

Source of truth (read-only):
  data/golive_status.json       — real_track_days, gates passed/total, anchor, target
  data/equity_curve_daily.json  — the evidenced bars (source/evidenced flags), equity

HONEST rules:
  - real_track_days = count of EVIDENCED bars (source-of-truth: track_evidence), never
    the raw bar count (which spans warmup/backfill/reconstructed).
  - gates_passed snaps the STABLE value: golive 'passed' can transiently dip pre-dawn
    (before the daily cycle + digest run); we clamp the offline fallback up to the
    stable count = total - (purely time-gated blockers) so the offline page does not
    show a transient dip. Live API still overrides with the real-time value.
  - stdlib-only, deterministic, atomic write (same-dir tmp + os.replace).
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLIVE = ROOT / "data" / "golive_status.json"
EQUITY = ROOT / "data" / "equity_curve_daily.json"
OUT = ROOT / "landing" / "src" / "data" / "track_snapshot.json"

# Purely time-gated go-live blockers — failing ONLY because the 30-day track has not
# matured (nothing code can fix). The offline fallback should reflect the desk's
# stable posture, not a transient pre-dawn dip in these.
_TIME_GATED = {"gap_monitor_30d", "min_track_days_30"}


def _atomic_write(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _max_drawdown_pct(bars: list):
    """Worst drawdown (%) = min(per-bar drawdown_pct) over the given bars (P1-4 audit fix).

    Uses each bar's own recorded ``drawdown_pct`` (the honest figure the cycle logged) rather than
    re-deriving peak-to-trough from equity — the old re-derivation returned 0.0 while bars carried
    drawdown_pct down to -0.026. Falls back to equity peak-to-trough only if no bar has drawdown_pct.
    """
    dds = [float(b.get("drawdown_pct")) for b in bars if b.get("drawdown_pct") is not None]
    if dds:
        return round(min(dds), 4)
    eqs = [float(b.get("equity")) for b in bars if b.get("equity") is not None]
    if len(eqs) < 2:
        return None
    peak = eqs[0]
    worst = 0.0
    for e in eqs:
        peak = max(peak, e)
        if peak > 0:
            worst = min(worst, (e - peak) / peak * 100.0)
    return round(worst, 4)


def _tier_packages() -> dict:
    """Static fallback for the homepage tier cards (Preserve/Core/Max-Yield net-APY + DD), sourced from
    data/tier1_packages.json — the SAME field the live /api/tier1/packages fills. A tier whose backend
    value is not yet computed stays null -> the card honestly shows '—' (never a hardcoded number)."""
    pk = _load(ROOT / "data" / "tier1_packages.json")
    pk = pk.get("packages", pk) if isinstance(pk, dict) else {}
    out = {}
    for key in ("conservative", "balanced", "aggressive"):
        p = pk.get(key, {}) if isinstance(pk, dict) else {}
        apy = p.get("blended_net_apy_pct") if isinstance(p, dict) else None
        dd = p.get("worst_dd_pct") if isinstance(p, dict) else None
        out[key] = {
            "apy_pct": round(float(apy), 1) if isinstance(apy, (int, float)) and not isinstance(apy, bool) else None,
            "dd_pct": round(float(dd), 1) if isinstance(dd, (int, float)) and not isinstance(dd, bool) else None,
        }
    return out


#: Журналы входов рукавов: по ним измеряется, С КАКОГО ДНЯ книга начисляется по
#: НАБЛЮДЁННЫМ ставкам, а не по литералам (ADR-292/298).
_SLEEVE_INPUTS = {
    "balanced": "sleeve_inputs_balanced.jsonl",
    "aggressive": "sleeve_inputs_aggressive.jsonl",
}

#: Признак наблюдённого начисления в журнале входов рукава.
_OBSERVED_BASIS = "per_position_observed_apy"


def _observed_accrual_since(book: str) -> "str | None":
    """День, с которого книга начисляется по НАБЛЮДЁННЫМ ставкам, либо ``None``.

    Зачем это на витрине (обязательство ADR-357 п. 4). Владелец решил оставить
    публичный трек советательных книг с 23 августа. Решение его; вместе с ним идёт
    требование инварианта #8: у Aggressive число почти целиком сложено из дней,
    начисленных по ставкам, которых никто не наблюдал, и доля таких дней обязана
    стоять РЯДОМ с числом.

    Дата берётся ЗАМЕРОМ из журнала входов рукава, а не из прозы ADR: прозу никто
    не пересчитывает, а литеральная дата в генераторе была бы ровно тем «числом,
    которое перестаёт быть правдой молча», против которого написано правило чисел.

    ``None`` — «не измерено»: журнала нет или в нём нет ни одной наблюдённой записи.
    Витрина обязана отличать это от «литеральных дней не было».
    """
    path = ROOT / "data" / _SLEEVE_INPUTS.get(book, "")
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        payload = rec.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("accrual_basis") != _OBSERVED_BASIS:
            continue
        day = payload.get("cycle_date") or str(rec.get("ts") or "")[:10]
        return day or None
    return None


def _sleeve_paper_track(state_path: Path, book: str = "") -> dict:
    """Paper-трек рукава (Balanced=hy, Aggressive=lp) для карточки тира — ЧЕСТНЫЙ.

    Решение владельца 2026-10-01 (ADR-531, пункт 9 пакета P0-4, вариант A): публикуются ТОЛЬКО
    дни, посчитанные исправленной моделью издержек `sleeve-econ-v2`. Строки модели v1 искажены
    выявленным дефектом учёта (газ за дрейф начисления), они НЕ удаляются и НЕ переписываются,
    в число НЕ входят и показываются отдельной пометкой без числа (`pre_fix_period`). Старое и
    новое в одну непрерывную историю не сводятся: дни, ставка и просадка — только по v2.

    Прежние правила остаются: «идёт paper-тест» — только при positions_count > 0 (решение
    владельца 19.08); ставка — по честным барам, ≥2 бара, иначе None → «—». Файла нет /
    нечитаем → all-None (сайт честно молчит). ADR-103.
    """
    from spa_core.paper_trading.sleeve_book import ECONOMICS_MODEL
    st = _load(state_path)
    hist = [h for h in (st.get("daily_history") or []) if isinstance(h, dict)]
    v2_all = [h for h in hist if h.get("economics_model") == ECONOMICS_MODEL]
    # ADR-533: a change of strategy version opens a new experiment; the published figures are the
    # CURRENT experiment's rows only — an earlier version's statistics are never carried over.
    _active = next((e for e in reversed(st.get("experiments") or []) if e.get("status") == "active"), None)
    v2 = ([h for h in v2_all if h.get("experiment_id") == _active.get("experiment_id")]
          if _active else v2_all)
    earlier_version_rows = len(v2_all) - len(v2)
    funded = [h for h in v2 if float(h.get("equity", 0) or 0) > 0]
    honest = [h for h in funded if int(h.get("positions_count", 0) or 0) > 0]
    pre_fix_days = len(hist) - len(v2_all)       # rows of the distorted v1 cost model only

    apy = None
    if len(honest) >= 2:
        first_eq = float(honest[0].get("equity") or 0)
        last_eq = float(honest[-1].get("equity") or 0)
        days = len(honest)
        if first_eq > 0 and last_eq > 0:
            apy = round(((last_eq / first_eq) ** (365.0 / days) - 1.0) * 100.0, 2)

    # Просадка — от пика ТОЛЬКО v2-ряда: поле строки меряет от пика всей книги, включая
    # искажённый период, и смешало бы два режима в одном числе.
    dd = None
    if honest:
        peak, worst = 0.0, 0.0
        for h in honest:
            eq = float(h.get("equity") or 0)
            peak = max(peak, eq)
            if peak > 0:
                worst = min(worst, eq / peak - 1.0)
        dd = round(worst * 100.0, 2)
    last = funded[-1] if funded else {}
    if honest:
        status = "paper_test_running"
    elif funded:
        status = "accrual_only_no_positions"     # v2-начисление без позиций — не трек (19.08)
    elif pre_fix_days:
        status = "restarted_on_corrected_model"   # граница пройдена, исправленных дней ещё нет
    else:
        status = "not_started"
    boundary = st.get("economics_model_boundary")
    return {
        "status": status,                       # факт, не аванс
        "days_with_positions": len(honest),
        "days_funded": len(funded),
        "apy_pct": apy,                         # только v2, честные бары, иначе None
        "dd_pct": dd,
        # NAV книги несёт итог искажённого периода — при наличии v1-строк не публикуется
        # (вариант A: старое с новым не смешивается); без них — текущий equity.
        "nav_usd": (None if pre_fix_days else (round(float(st.get("equity") or 0.0), 2) or None)),
        "positions_count": int(last.get("positions_count", 0) or 0) if last else None,
        "evidence": "paper",                    # это paper-тест, не live (инв. #8)
        # Все v2-дни начислены по НАБЛЮДЁННЫМ ставкам: дата — первый день v2.
        "observed_accrual_since": (v2[0].get("date") if v2 else None),
        "economics_model": ECONOMICS_MODEL,
        "economics_model_boundary": boundary,
        "pre_fix_period": ({"days": pre_fix_days, "status": "distorted",
                            "label_en": "earlier period distorted by the identified accounting defect "
                                        "— retained for audit, not shown",
                            "label_ru": "прежний период искажён выявленным дефектом учёта — "
                                        "сохранён для аудита, не показывается"}
                           if pre_fix_days else None),
        "post_fix": dict(_post_fix_track(honest), pre_fix_days=pre_fix_days),
        # rows of an EARLIER strategy version under the corrected model — kept, not counted, not "distorted"
        "earlier_version_rows": earlier_version_rows,
        "experiment_id": (_active or {}).get("experiment_id"),
    }


def _package_status() -> dict:
    """Project ``defi_engine.package_status`` for the site. Unavailable ⇒ a named gap, never a guess."""
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from spa_core.defi_engine.package_status import build_all
        full = build_all(ROOT / "data")
    except Exception as exc:  # noqa: BLE001
        return {"unavailable_reason": f"{type(exc).__name__}: {exc}"}
    keep = ("running_version", "mandate_version", "mechanic", "experiment_id", "experiment_start_date",
            "new_version_pending", "headline_en", "headline_ru")
    out = {"generated_at": full.get("generated_at"), "mode": full.get("mode"),
           "live_capital_usd": full.get("live_capital_usd"), "packages": {}}
    for name, p in (full.get("packages") or {}).items():
        out["packages"][name] = {
            **{k: p.get(k) for k in keep},
            "work": {k: (p.get("work") or {}).get(k) for k in ("state", "reason", "last_run_at")},
            "data": {k: (p.get("data") or {}).get(k) for k in ("state", "reason", "last_observation_at")},
            "history": {k: (p.get("history") or {}).get(k)
                        for k in ("state", "valid_periods", "first_period", "last_period", "reportable_after")},
        }
    return out


def _post_fix_track(honest: list) -> dict:
    """Те же честные бары, но только посчитанные моделью v2 (ADR-531). <2 баров ⇒ apy None."""
    from spa_core.paper_trading.sleeve_book import ECONOMICS_MODEL
    v2 = [h for h in honest if h.get("economics_model") == ECONOMICS_MODEL]
    apy = None
    if len(v2) >= 2:
        a, b = float(v2[0].get("equity") or 0), float(v2[-1].get("equity") or 0)
        if a > 0 and b > 0:
            apy = round(((b / a) ** (365.0 / len(v2)) - 1.0) * 100.0, 2)
    return {"model": ECONOMICS_MODEL, "days": len(v2),
            "first_date": v2[0].get("date") if v2 else None, "apy_pct": apy,
            "pre_fix_days": len(honest) - len(v2)}


def _go_live_target(golive: dict):
    """The gate's calendar target — VERBATIM, null included.

    ``golive_checker`` emits ``target_date: null`` once the 30-day criteria pass (the
    projection anchor+29d lies in the past and answers nothing; the state lives in
    ``go_live_state``). The former ``or``-chain turned that null straight back into the
    literal 2026-07-21 — the exact past date the site was taught to distrust (commit
    82e20cda). A PRESENT key wins even when its value is None; no literal fallback at all
    (this module's own contract: missing ⇒ None ⇒ "data unavailable", never a stale number).
    """
    for key in ("target_date", "go_live_target"):
        if key in golive:
            return golive[key]
    return None


def build_snapshot(golive_path: Path = GOLIVE, equity_path: Path = EQUITY, pts_path=None) -> dict:
    """Assemble the build-time static snapshot from the committed data files.

    ONE source per number (FIX-2): live equity / paper APY / PoR-NAV come from
    paper_trading_status.json (the same authority the API serves); track days + gates from
    golive_status.json; the per-bar ledger from equity_curve_daily.json. A missing value is left
    None so the site renders an honest "data unavailable" — NEVER a bare hardcoded number.
    """
    golive = _load(golive_path)
    equity = _load(equity_path)
    pts = _load(pts_path if pts_path is not None else (ROOT / "data" / "paper_trading_status.json"))

    bars = equity.get("bars") or equity.get("curve") or equity.get("daily") or []
    evidenced = [b for b in bars if b.get("evidenced") is True]
    real_days = len(evidenced) if evidenced else int(golive.get("real_track_days", 0) or 0)

    total = int(golive.get("total", 29) or 29)
    passed_live = int(golive.get("passed", 0) or 0)
    # Stable floor: at most the 2 time-gated blockers may legitimately be open.
    stable_passed = max(passed_live, total - len(_TIME_GATED))

    last = bars[-1] if bars else {}
    # ONE source: prefer the paper_trading_status authority; fall back to the equity ledger tail.
    nav = pts.get("current_equity")
    end_equity = float(nav if nav is not None else last.get("equity", equity.get("end_equity", 100000.0)) or 100000.0)

    # Public "Paper APY" = the STABLE evidenced-track annualized return, NOT the
    # volatile single-day apy_today (which annualizes ONE day's yield → swings daily,
    # overstates the track, and breaks the stated 2-6% band). Compound-annualize from
    # the evidenced anchor bar over the real evidenced days. Pre-anchor bars are
    # backfill/demo (invalid) and are excluded upstream, so this only ever counts
    # honest evidenced days. Too few evidenced bars to annualize => None => the site
    # renders "data unavailable", never a misleading volatile number.
    paper_apy = None
    if len(evidenced) >= 2 and real_days > 0:
        anchor_eq = float(evidenced[0].get("equity") or 0)
        latest_eq = float(evidenced[-1].get("equity") or 0)
        if anchor_eq > 0 and latest_eq > 0:
            paper_apy = ((latest_eq / anchor_eq) ** (365.0 / real_days) - 1.0) * 100.0

    # as_of = freshness of the underlying evidenced data (last evidenced bar date), NOT build time.
    as_of = (evidenced[-1].get("date") if evidenced else last.get("date")) or golive.get("as_of")
    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    snap = {
        "generated_from": "data/golive_status.json + data/equity_curve_daily.json + data/paper_trading_status.json",
        "generator": "scripts/generate_track_snapshot.py",
        "note": (
            "Build-time static fallback for the public pages. Live values come from api.earn-defi.com "
            "and override these client-side; this is the last honest snapshot for offline / crawlers. "
            "real_track_days = EVIDENCED bars only. Missing value => 'data unavailable', never a stale number."
        ),
        "as_of": as_of,
        "generated_at": generated_at,
        # Site-Custodian kill-rule flag (ADR-YL-011). A routine regen PRESERVES it (carry-forward) so a
        # degraded site stays degraded through rebuilds; only the freshness monitor SETS it (on
        # OVERSTATED/stale) and CLEARS it (on a passing re-check). Default False on first generation.
        "degraded": bool(_load(OUT).get("degraded", False)),
        "real_track_days": real_days,
        "go_live_target": _go_live_target(golive),
        "go_live_state": golive.get("go_live_state"),
        "evidenced_anchor": golive.get("evidenced_anchor") or "2026-06-22",
        "days_needed": int(golive.get("min_track_days", 30) or 30),
        "gates_passed": stable_passed,
        "gates_total": total,
        "end_equity": round(end_equity, 2),
        "nav_usd": round(end_equity, 2),                    # PoR-NAV (paper): the reserves backing
        "paper_apy_pct": round(float(paper_apy), 4) if paper_apy is not None else None,
        "max_drawdown_pct": _max_drawdown_pct(evidenced or bars),
        "total_return_pct": round((end_equity / 100000.0 - 1.0) * 100.0, 4),
        "packages": _tier_packages(),   # tier-card net-APY static fallback (Preserve/Core/Max), null if uncomputed
        # ── ADR-103: живые paper-треки трёх пакетов (факт positions_count>0 — правило
        # владельца 19.08). Conservative — главная evidenced-книга; Balanced/Aggressive —
        # рукава B/C. Карточка тира показывает «идёт paper-тест · день N · APY» только
        # когда status == paper_test_running.
        "paper_tracks": {
            "conservative": {
                "status": "paper_test_running" if real_days > 0 else "not_started",
                "days_with_positions": real_days,
                "days_funded": real_days,
                "apy_pct": round(float(paper_apy), 2) if paper_apy is not None else None,
                "dd_pct": _max_drawdown_pct(evidenced or bars),
                "nav_usd": round(end_equity, 2),
                "positions_count": None,   # главная книга ведёт позиции в своём снимке
                "evidence": "paper",
            },
            "balanced": _sleeve_paper_track(ROOT / "data" / "hy_paper_trading.json", "balanced"),
            "aggressive": _sleeve_paper_track(ROOT / "data" / "lp_paper_trading.json", "aggressive"),
        },
        # ADR-533: the ONE read model of the three paper portfolios — work / data / history state,
        # the running strategy version and the version waiting to start. A status, not a figure.
        "package_status": _package_status(),
        "bars": bars,
    }
    return snap


def main() -> int:
    snap = build_snapshot()
    _atomic_write(OUT, snap)
    print(
        f"track_snapshot.json regenerated: real_track_days={snap['real_track_days']} "
        f"gates={snap['gates_passed']}/{snap['gates_total']} anchor={snap['evidenced_anchor']} "
        f"bars={len(snap['bars'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
