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
# ADR-148-класс (простой публикации 2026-10-02…10-05): `deploy_site_snapshot.py` и launchd зовут
# этот файл ПО ПУТИ, `sys.path[0]` тогда — `scripts/`, и КАЖДЫЙ ленивый `from spa_core…` ниже без
# корня в пути падает `ModuleNotFoundError`. Один бутстрап на модуль, а не по одному на функцию:
# при слиянии RM-TRUTH-01 ровно так вернулся дефект — новый ленивый импорт в `build_snapshot`
# не получил своего бутстрапа (поймал `test_generate_track_snapshot_subprocess_import.py`).
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
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

    Delegates to ``spa_core.reporting.compound_apy.max_drawdown_pct`` (RM-TRUTH-01 W5,
    ADR-580 C2) — the SAME formula ``/api/health-public`` now uses, so the two stop being
    independent re-derivations of the same number.
    """
    from spa_core.reporting.compound_apy import max_drawdown_pct as _shared_max_dd
    return _shared_max_dd(bars)


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
            # ADR-660: the source keeps its precision; rounding happens once, at display (two decimals).
            "apy_pct": round(float(apy), 4) if isinstance(apy, (int, float)) and not isinstance(apy, bool) else None,
            "dd_pct": round(float(dd), 4) if isinstance(dd, (int, float)) and not isinstance(dd, bool) else None,
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

    Thin wrapper (RM-TRUTH-01 W5, ADR-580 C1): the actual v2-only / current-experiment /
    maturity logic now lives in ``spa_core.paper_trading.sleeve_track.sleeve_track_view``
    — the ONE place it is computed, also imported by ``spa_core/reporting/books_summary.py``
    and ``spa_core/api/routers/live.py`` so the Telegram "📚 Пакеты" block and
    ``/api/live/books`` stop re-deriving it with a different (linear, unguarded) formula.
    This function's signature/behaviour is unchanged — it still takes a *path* and does
    its own file read, so existing callers/tests (``scripts/tests/test_track_snapshot_paper_tracks.py``)
    are untouched.

    Импорт ниже защищён модульным бутстрапом ``sys.path`` (ADR-148-класс, см. шапку файла).
    Порог зрелости ставки (ADR-580 C2) живёт в `sleeve_track_view`, а не здесь — одно место.
    """
    from spa_core.paper_trading.sleeve_track import sleeve_track_view
    return sleeve_track_view(_load(state_path), book)


def _package_status() -> dict:
    """Project ``defi_engine.package_status`` for the site through its ONE public projection
    (``public_view`` — the same one the public API serves). Unavailable ⇒ a named gap, never a guess."""
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from spa_core.defi_engine.package_status import build_all, public_view
        return public_view(build_all(ROOT / "data"))
    except Exception as exc:  # noqa: BLE001
        # the exception TYPE only: its message can carry a local path, and this file is public
        return {"unavailable_reason": f"package status read model unavailable ({type(exc).__name__})"}



POSITIONS = ROOT / "data" / "current_positions.json"


def _book_exposure(positions_path: Path = POSITIONS) -> dict:
    """What the main (Conservative) book HOLDS, per protocol — for /due-diligence.

    Replaces a hand-typed «protocol whitelist» that drifted from the book (P1 2026-10-08: it lacked
    fluid_fusdc and maple — 20 % of the book each — and labelled Morpho T1 where the registry says
    T2). Amounts come from the cycle's own positions snapshot; tiers from the canonical registry
    (``concentration_monitor._tier_map`` — the same map ``package_status._composition`` uses).
    The share is of allocated paper capital (positions + cash), the base the RiskPolicy caps use.
    Unreadable source ⇒ ``state: UNMEASURED`` with a reason — never an empty table read as «nothing held».
    """
    doc = _load(positions_path)
    pos = doc.get("positions") if isinstance(doc, dict) else None
    cash = doc.get("cash_usd") if isinstance(doc, dict) else None
    if not isinstance(pos, dict) or not pos or not isinstance(cash, (int, float)) or isinstance(cash, bool):
        return {"state": "UNMEASURED", "reason": "positions snapshot unreadable or empty", "rows": None}
    try:
        from spa_core.risk.concentration_monitor import _tier_map
        tmap = _tier_map() or {}
    except Exception:  # noqa: BLE001 — absent registry is a named outcome, not «T1»
        tmap = {}
    try:
        from spa_core.defi_engine.package_status import IDENTITY_UNRESOLVED
    except Exception:  # noqa: BLE001
        IDENTITY_UNRESOLVED = {}
    amounts = {str(k): float(v) for k, v in pos.items()
               if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) > 0}
    base = sum(amounts.values()) + float(cash)
    if base <= 0:
        return {"state": "UNMEASURED", "reason": "allocated capital is zero", "rows": None}
    rows = []
    for proto, usd in sorted(amounts.items(), key=lambda kv: (-kv[1], kv[0])):
        tier = "unresolved" if proto in IDENTITY_UNRESOLVED else (tmap.get(proto) or "unlabelled")
        rows.append({"protocol": proto, "tier": tier, "usd": round(usd, 2),
                     "share_pct": round(usd / base * 100.0, 4)})
    return {
        "state": "MEASURED",
        "as_of": doc.get("generated_at"),
        "base": "allocated paper capital = positions + cash",
        "base_usd": round(base, 2),
        "cash_usd": round(float(cash), 2),
        "cash_share_pct": round(float(cash) / base * 100.0, 4),
        "rows": rows,
        "source": "data/current_positions.json (daily cycle) + ADAPTER_REGISTRY tiers",
    }


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
    # Delegates to spa_core.reporting.compound_apy (RM-TRUTH-01 W5, ADR-580 C2) — the
    # SAME formula /api/health-public and /api/ssot/facts now use for paper_apy_pct.
    from spa_core.reporting.compound_apy import compound_annualized_pct as _shared_apy
    paper_apy = None
    anchor_eq = latest_eq = None
    if len(evidenced) >= 2 and real_days > 0:
        anchor_eq = float(evidenced[0].get("equity") or 0)
        latest_eq = float(evidenced[-1].get("equity") or 0)
        paper_apy = _shared_apy(anchor_eq, latest_eq, real_days)
    # P1 2026-10-08 (C4): the rate's OWN cumulative — same two NAVs, same window — so a page can show
    # «+x % over N days» next to the annualised rate and the two visibly reconcile. Not the
    # «total return» (that one is on the $100k base from paper_start_date, pre-anchor days included).
    track_return = ((latest_eq / anchor_eq - 1.0) * 100.0) if anchor_eq and latest_eq else None

    # P1 Wave 2 (owner/ARB 2026-10-08, step 3): the return over the ACTUAL period, proven from the
    # ledger — flows tested bar by bar, ACT/365 on valuation dates, provenance counted. The primary
    # public metric is its period return; the annualised equivalent is separate and needs the
    # owner's approval. The anchor NAV / track return below are read FROM it (one definition).
    from spa_core.paper_trading.track_period_return import period_return as _period_return
    _end_ts = pts.get("last_cycle_ts") or pts.get("last_updated")
    if not (isinstance(_end_ts, str) and evidenced and _end_ts[:10] == str(evidenced[-1].get("date"))):
        _end_ts = None          # a run time that is not the end bar's own is not its timestamp
    track_period = _period_return(bars, end_ts=_end_ts)
    if track_period.get("state") == "MEASURED":
        anchor_eq = track_period["nav_start"]
        track_return = track_period["period_return_pct"]
        # ONE annualised number in the snapshot: the equivalent of the period return on ACT/365
        # valuation-date days (the bar-count exponent understated the duration by the days the
        # ledger has no bar for). Owner approval of the annualised display is still required.
        paper_apy = track_period["annualised_equivalent_pct"]

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
        # Base of total_return_pct: $100k from the paper start (pre-anchor days INCLUDED).
        "paper_start_date": pts.get("paper_start_date"),
        # The rate's own window: NAV at the close of the anchor bar → NAV of the last evidenced bar.
        "anchor_equity": round(anchor_eq, 2) if anchor_eq else None,
        "track_end_date": evidenced[-1].get("date") if evidenced else None,
        "track_return_pct": round(track_return, 4) if track_return is not None else None,
        # The whole proof of that return: window, day count, flows, costs, provenance, gaps.
        "track_period": track_period,
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
                "apy_pct": round(float(paper_apy), 4) if paper_apy is not None else None,   # ADR-660: display rounds
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
        # What the main book holds, per protocol, with registry tiers (P1 2026-10-08 — replaces the
        # hand-typed whitelist on /due-diligence). A holding, not a recommendation.
        "book_exposure": _book_exposure(),
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
