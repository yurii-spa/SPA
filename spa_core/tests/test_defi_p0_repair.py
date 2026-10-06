"""DeFi vNext Phase 0 — P0 repair (ADR-531). Positive controls replay the defects measured on 2026-10-01.

P0-1  Balanced/Aggressive books charged full ETH gas on daily accrual drift ($48.03 vs $13.77 yield).
P0-2  kill switch: `fallback_used=true` ignored every red flag; a missing file read as «not triggered».
P0-3  peg_monitor: no price ⇒ 1.0 ⇒ GREEN, read by the intraday kill path.
Hermetic: every scene is a tmp data dir; time is an input (relative timestamps, injected `now`).
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.governance import kill_switch as ks
from spa_core.paper_trading import sleeve_book as sb


def _w(d: Path, name: str, doc) -> None:
    p = d / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc) if not isinstance(doc, str) else doc, encoding="utf-8")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(hours_ago: float = 0.0) -> str:
    return (_now() - timedelta(hours=hours_ago)).isoformat()


# ════════════════════════════════════════════════════════════════ P0-1 sleeve economics

CANDS = [{"protocol": "maple", "apy_pct": 5.14}, {"protocol": "fluid_fusdc", "apy_pct": 5.30},
         {"protocol": "compound_v3", "apy_pct": 6.11}]
CHAINS = {"maple": "ethereum", "fluid_fusdc": "ethereum", "compound_v3": "ethereum"}


def _day(book, equity, *, model):
    """One sleeve day exactly as hy_cycle/lp_cycle compute it, under `model` (v1 or v2)."""
    before = copy.deepcopy(book)
    v2 = model == sb.ECONOMICS_MODEL
    dust = sb.dust_band_usd(equity) if v2 else 0.0
    after, opened, closed = sb.rebalance_book(book, CANDS[:2], equity, today="d",
                                              max_positions=2, cap_pct=60.0, keep_within_usd=dust)
    snap = copy.deepcopy(after)
    dy, _dep = sb.accrue_book(after, CANDS, compound_in_place=v2)
    cost = sb.book_move_cost(before, snap, CHAINS, dust_usd=dust)
    return after, equity + dy - cost["cost_usd"], dy, cost


def _seed():
    book, _, _ = sb.rebalance_book([], CANDS[:2], 100_000.0, today="d0", max_positions=2, cap_pct=60.0)
    return book


def test_v1_reproduces_the_measured_defect_positive_control():
    book, eq = _seed(), 100_000.0
    book, eq, dy, _ = _day(book, eq, model=sb.ECONOMICS_MODEL_V1)
    _, _, dy2, cost = _day(book, eq, model=sb.ECONOMICS_MODEL_V1)
    assert cost["cost_usd"] >= 24.0 > dy2          # $12 per leg × 2 legs for a few dollars of drift
    assert cost["touched"] == ["fluid_fusdc", "maple"]


def test_v2_drift_only_days_charge_nothing_and_compound_in_place():
    book, eq = _seed(), 100_000.0
    for _ in range(10):
        book, eq, dy, cost = _day(book, eq, model=sb.ECONOMICS_MODEL)
        assert cost["cost_usd"] == 0.0 and cost["turnover_usd"] == 0.0 and dy > 0
    assert abs(sum(p["notional_usd"] for p in book) - eq) < 1.0   # yield stayed inside the positions


def test_v2_a_real_move_still_pays_the_cost_model():
    book, eq = _seed(), 100_000.0
    book, eq, _, _ = _day(book, eq, model=sb.ECONOMICS_MODEL)
    before = copy.deepcopy(book)
    dust = sb.dust_band_usd(eq)
    # maple leaves the candidate set: a close + an open is an actual action
    after, opened, closed = sb.rebalance_book(book, [CANDS[1], CANDS[2]], eq, today="d2",
                                              max_positions=2, cap_pct=60.0, keep_within_usd=dust)
    cost = sb.book_move_cost(before, after, CHAINS, dust_usd=dust)
    assert closed == ["maple"] and opened == ["compound_v3"]
    assert cost["gas_usd"] == 24.0 and cost["cost_usd"] > 24.0   # 2 legs gas + slippage on the turnover


def test_v2_never_holds_more_than_equity():
    # both legs inside the dust band of their target, but together above equity (v1 left the
    # book over-deployed after charging phantom gas) ⇒ every leg is re-sized, at no cost
    book = [{"protocol": "maple", "notional_usd": 50_300.0}, {"protocol": "fluid_fusdc", "notional_usd": 50_300.0}]
    dust = sb.dust_band_usd(100_000.0)
    after, _, _ = sb.rebalance_book(copy.deepcopy(book), CANDS[:2], 100_000.0, today="d", max_positions=2,
                                    cap_pct=60.0, keep_within_usd=dust)
    assert [p["notional_usd"] for p in after] == [50_000.0, 50_000.0]
    assert sb.book_move_cost(book, after, CHAINS, dust_usd=dust)["cost_usd"] == 0.0   # $300 legs are dust
    assert sb.book_move_cost(book, after, CHAINS)["cost_usd"] > 24.0                   # v1 would charge


def test_v2_dust_legs_are_not_moved():
    book = [{"protocol": "maple", "notional_usd": 50_010.0}, {"protocol": "fluid_fusdc", "notional_usd": 49_980.0}]
    after, _, _ = sb.rebalance_book(copy.deepcopy(book), CANDS[:2], 99_990.0, today="d", max_positions=2,
                                    cap_pct=60.0, keep_within_usd=sb.dust_band_usd(99_990.0))
    assert [p["notional_usd"] for p in after] == [50_010.0, 49_980.0]


def test_dust_band_is_the_main_book_rule_not_a_second_number():
    from spa_core.allocator.rebalance_economics import TriggerParams
    assert sb.dust_band_usd(100_000.0) == pytest.approx(TriggerParams.for_mode().min_leg_frac * 100_000.0)


def test_model_boundary_names_old_rows_without_touching_them():
    hist = [{"date": "a", "cost_usd": 48.0}, {"date": "b", "cost_usd": 48.0}]
    frozen = copy.deepcopy(hist)
    b = sb.model_boundary(hist, first_v2_date="c", activated_at="t")
    assert hist == frozen
    assert (b["v1_rows"], b["v1_last_date"], b["first_v2_date"]) == (2, "b", "c")
    assert "DISTORTED" in b["v1_classification"]


def test_replay_uses_the_model_that_wrote_each_day(tmp_path):
    """v1 archive records keep replaying under v1 (history is not rewritten); v2 records under v2."""
    from spa_core.audit import sleeve_inputs_archive as arc, sleeve_replay
    book, eq, hist = _seed(), 100_000.0, []
    for i, model in enumerate([sb.ECONOMICS_MODEL_V1, sb.ECONOMICS_MODEL_V1, sb.ECONOMICS_MODEL, sb.ECONOMICS_MODEL]):
        before = copy.deepcopy(book)
        v2 = model == sb.ECONOMICS_MODEL
        dust = sb.dust_band_usd(eq) if v2 else 0.0
        after, _, _ = sb.rebalance_book(book, CANDS[:2], eq, today=f"2000-01-0{i + 1}", max_positions=2,
                                        cap_pct=60.0, keep_within_usd=dust)
        snap = copy.deepcopy(after)
        dy, _ = sb.accrue_book(after, CANDS, compound_in_place=v2)
        cost = sb.book_move_cost(before, snap, CHAINS, dust_usd=dust)
        open_eq, eq = eq, eq + dy - cost["cost_usd"]
        rec = arc.build_record(book="aggressive", cycle_date=f"2000-01-0{i + 1}", run_ts="t", open_equity=open_eq,
                               close_equity=eq, book_before=before, book_after=snap, candidates=CANDS,
                               chains=CHAINS, prices={}, marks_before={}, daily_yield_usd=dy,
                               cost_usd=cost["cost_usd"], mtm_pnl_usd=0.0, accrual_basis=sb.ACCRUAL_BASIS,
                               economics_model=model if v2 else None, cost_dust_usd=dust if v2 else None)
        arc.append_record(tmp_path, "aggressive", rec, f"t{i}")
        hist.append({"date": f"2000-01-0{i + 1}", "equity": round(eq, 2)})
        book = after
    _w(tmp_path, "lp_paper_trading.json", {"daily_history": hist})
    res = sleeve_replay.replay(tmp_path, "aggressive")
    assert res["status"] == "PASS" and res["days"] == 4, res


def test_snapshot_separates_post_fix_days_and_keeps_the_published_number(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("gts", Path(__file__).resolve().parents[2] / "scripts" /
                                                  "generate_track_snapshot.py")
    gts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gts)
    rows = [{"date": f"d{i}", "equity": 100_000 - 30 * i, "positions_count": 2} for i in range(5)]
    rows += [{"date": f"e{i}", "equity": 99_850 + 15 * i, "positions_count": 2,
              "economics_model": sb.ECONOMICS_MODEL} for i in range(3)]
    _w(tmp_path, "lp.json", {"equity": 99_880, "daily_history": rows,
                             "economics_model_boundary": {"first_v2_date": "e0"}})
    tr = gts._sleeve_paper_track(tmp_path / "lp.json")
    assert tr["post_fix"]["days"] == 3 and tr["post_fix"]["pre_fix_days"] == 5
    # Option A (owner, 2026-10-01): the published figure is the v2 figure; the pre-fix
    # period is a label without a number and never merged into the series.
    #
    # CHANGED 2026-10-05 (ADR-580 C2, inv. #16 — explicit reason, not a silent weakening).
    # Before this change ``apy_pct`` and ``post_fix.apy_pct`` were computed by the SAME
    # >=2-bar rule and were therefore always equal. C2 adds a maturity gate
    # (``REPORTABLE_AFTER`` = 30 honest bars, the canon in
    # ``spa_core.defi_engine.package_status``) to the PUBLISHED ``apy_pct`` only — this
    # repairs defect D6 (`docs/rm_truth/A3_product.md` §2.1 / `REVIEW_1.md` claim 11): the
    # generator used to publish a rate from 2 bars while the page itself suppressed it
    # below 30, and the undelivered 2026-10-04 shelf carried "Balanced -11.5%" on exactly
    # 3 bars because of that split gate. ``post_fix`` stays ungated on purpose: it is an
    # AUDIT figure (no page reads it — verified by grep, RM-TRUTH-01 workstream W4), and an
    # auditor needs the raw v2 number even before it is fit to publish. So with 3 v2 bars
    # (< 30) the two numbers now correctly DIVERGE: post_fix still shows the raw figure,
    # the published apy_pct is None + reportable=False until maturity.
    assert tr["post_fix"]["apy_pct"] > 0
    assert tr["apy_pct"] is None and tr["reportable"] is False
    assert tr["reportable_after"] == 30
    assert tr["days_with_positions"] == 3 and tr["pre_fix_period"]["days"] == 5
    assert tr["nav_usd"] is None
    assert tr["economics_model_boundary"]["first_v2_date"] == "e0"


def test_published_apy_matches_post_fix_once_it_reaches_maturity():
    """Положительный контроль РЯДОМ с предыдущим: на 30 честных v2-барах равенство,
    которое прежний тест проверял безусловно, ВОЗВРАЩАЕТСЯ — C2 не разводит числа
    навсегда, только ниже порога зрелости."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gts2", Path(__file__).resolve().parents[2] / "scripts" / "generate_track_snapshot.py")
    gts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gts)
    import tempfile
    rows = [{"date": f"e{i}", "equity": 99_850 + 15 * i, "positions_count": 2,
            "economics_model": sb.ECONOMICS_MODEL} for i in range(30)]
    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        _w(tmp_path, "lp.json", {"equity": rows[-1]["equity"], "daily_history": rows,
                                 "economics_model_boundary": {"first_v2_date": "e0"}})
        tr = gts._sleeve_paper_track(tmp_path / "lp.json")
    assert tr["reportable"] is True
    assert tr["apy_pct"] == tr["post_fix"]["apy_pct"]


# ════════════════════════════════════════════════════════════════ P0-2 kill-switch truth table

HELD = {"positions": {"aave_v3": 40_000.0, "maple": 20_000.0}, "cash_usd": 5_000.0}


def _flag(proto="aave_v3", sev="CRITICAL", source="defillama", cat="tvl_drop"):
    return {"protocol": proto, "severity": sev, "source": source, "category": cat}


def _rf(tmp, flags, *, age_h=0.0, fallback=False, sources=("defillama",), gen=True, prov=None):
    doc = {"red_flags": flags, "fallback_used": fallback, "sources": list(sources)}
    if prov is not None:
        doc["provenance"] = {"by_category": prov}
    if gen:
        doc["generated_at"] = _iso(age_h)
    _w(tmp, "red_flags.json", doc)


@pytest.fixture()
def scene(tmp_path):
    _w(tmp_path, "current_positions.json", HELD)
    return tmp_path


def _out(d):
    return ks.KillSwitchChecker(data_dir=d, now=_now()).evaluate_red_flags()[0]


@pytest.mark.parametrize("case,expect", [
    ("healthy", ks.OUTCOME_CLEAR),
    ("warning", ks.OUTCOME_CLEAR),
    ("critical", ks.OUTCOME_TRIGGERED),
    ("fallback_live_critical", ks.OUTCOME_TRIGGERED),
    ("fallback_bootstrap_only_flags", ks.OUTCOME_UNMEASURED),      # no provenance, nothing live (review S6)
    ("fallback_no_provenance_no_flags", ks.OUTCOME_UNMEASURED),
    ("future_dated", ks.OUTCOME_UNMEASURED),
    ("bootstrap_category_with_live_looking_source", ks.OUTCOME_PARTIAL),
    ("live_categories_empty_bootstrap_flags_only", ks.OUTCOME_PARTIAL),
    ("provenance_without_any_live_category", ks.OUTCOME_UNMEASURED),
    ("fallback_mixed_below_threshold", ks.OUTCOME_PARTIAL),
    ("all_bootstrap_sources", ks.OUTCOME_UNMEASURED),
    ("missing", ks.OUTCOME_UNMEASURED),
    ("stale", ks.OUTCOME_UNMEASURED),
    ("malformed_json", ks.OUTCOME_UNMEASURED),
    ("not_an_object", ks.OUTCOME_UNMEASURED),
    ("no_flag_list", ks.OUTCOME_UNMEASURED),
    ("no_generated_at", ks.OUTCOME_UNMEASURED),
    ("positions_unreadable", ks.OUTCOME_UNMEASURED),
])
def test_red_flag_truth_table(scene, case, expect):
    crit = [_flag() for _ in range(ks.RED_FLAGS_THRESHOLD + 1)]
    if case == "healthy":
        _rf(scene, [])
    elif case == "warning":
        _rf(scene, [_flag(sev="WARN") for _ in range(10)])
    elif case == "critical":
        _rf(scene, crit)
    elif case == "fallback_live_critical":           # the measured 2026-10-01 defect
        _rf(scene, crit, fallback=True, sources=("defillama", "bootstrap", "snapshot"),
            prov={"tvl_drop": "live", "apy_spike": "bootstrap"})
    elif case == "bootstrap_category_with_live_looking_source":   # measured 2026-10-01 shape
        _rf(scene, [_flag(cat="token_unlock") for _ in range(ks.RED_FLAGS_THRESHOLD + 1)], fallback=True,
            sources=("defillama", "bootstrap"), prov={"tvl_drop": "live", "token_unlock": "bootstrap"})
    elif case == "fallback_bootstrap_only_flags":
        _rf(scene, [_flag(source="bootstrap", cat="apy_spike")], fallback=True,
            sources=("defillama", "bootstrap"))
    elif case == "live_categories_empty_bootstrap_flags_only":     # the exact live shape of 2026-10-01
        _rf(scene, [_flag("aave_v3", cat="apy_spike", source="historical_apy"),
                    _flag("aave_v3", cat="token_unlock")], fallback=True,
            sources=("defillama", "bootstrap", "snapshot"),
            prov={"tvl_drop": "live", "apy_spike": "bootstrap", "governance_proposal": "live",
                  "token_unlock": "bootstrap"})
    elif case == "provenance_without_any_live_category":
        _rf(scene, [_flag()], fallback=True, sources=("defillama", "bootstrap"),
            prov={"tvl_drop": "bootstrap", "apy_spike": "bootstrap"})
    elif case == "fallback_no_provenance_no_flags":
        _rf(scene, [], fallback=True, sources=("defillama", "bootstrap"))
    elif case == "future_dated":
        _rf(scene, [], age_h=-2)
    elif case == "fallback_mixed_below_threshold":
        _rf(scene, [_flag(), _flag(source="bootstrap", cat="apy_spike")], fallback=True,
            sources=("defillama", "bootstrap"))
    elif case == "all_bootstrap_sources":
        _rf(scene, [_flag(source="bootstrap")], sources=("bootstrap",))
    elif case == "missing":
        pass
    elif case == "stale":
        _rf(scene, crit, age_h=ks.RED_FLAGS_MAX_AGE_S / 3600.0 + 1)
    elif case == "malformed_json":
        _w(scene, "red_flags.json", "{not json")
    elif case == "not_an_object":
        _w(scene, "red_flags.json", [1, 2])
    elif case == "no_flag_list":
        _w(scene, "red_flags.json", {"generated_at": _iso(), "red_flags": "x"})
    elif case == "no_generated_at":
        _rf(scene, [], gen=False)
    elif case == "positions_unreadable":
        _rf(scene, crit)
        _w(scene, "current_positions.json", "{broken")
    assert _out(scene) == expect


def _all_measured(d):
    _rf(d, [])
    curve = [{"date": (_now() - timedelta(days=80 - i)).date().isoformat(),
              "close_equity": 100_000.0 + i, "open_equity": 100_000.0 + i} for i in range(80)]
    _w(d, "equity_curve_daily.json", {"daily": curve})
    return curve


def test_all_triggers_clear_only_when_everything_is_measured(scene):
    curve = _all_measured(scene)
    c = ks.KillSwitchChecker(data_dir=scene, now=_now())
    trig, state, why = c.summarize(c.evaluate_triggers(curve))
    assert not trig and state in (ks.OUTCOME_CLEAR, "CLEAR_PARTIAL")
    (scene / "red_flags.json").unlink()
    trig, state, why = c.summarize(c.evaluate_triggers(curve))
    assert (trig, state) == (False, ks.OUTCOME_UNMEASURED)
    assert "all triggers clear" not in why and "red_flags" in why


def test_run_kill_switch_check_persists_the_state_and_never_writes_clear_for_unmeasured(scene):
    curve = _all_measured(scene)
    (scene / "red_flags.json").unlink()
    res = ks.run_kill_switch_check(equity_curve=curve, data_dir=scene, now=_now())
    doc = json.loads((scene / ks.KILL_SWITCH_STATUS_FILENAME).read_text())
    assert res["state"] == doc["state"] == ks.OUTCOME_UNMEASURED and res["unmeasured"] == ["red_flags"]
    assert doc["triggered"] is False and doc["reason"] != "all triggers clear"
    assert not (scene / ks.KILL_SWITCH_ACTIVE_FILENAME).exists()   # unmeasured never liquidates


def test_no_equity_series_is_named_not_applicable_never_all_clear(scene):
    """Track start: no evidenced series. Not a reason to hold (a new book must be able to deploy),
    and never reported as «all triggers clear» either."""
    _rf(scene, [])
    c = ks.KillSwitchChecker(data_dir=scene, now=_now())
    res = c.evaluate_triggers([])
    outcomes = {r["trigger"]: r["outcome"] for r in res}
    assert outcomes["drawdown"] == outcomes["sharpe"] == ks.OUTCOME_NOT_APPLICABLE
    trig, state, why = c.summarize(res)
    assert (trig, state) == (False, "CLEAR_PARTIAL") and "all triggers clear" not in why


def test_unreadable_equity_file_is_unmeasured_not_track_start(scene):
    _rf(scene, [])
    _w(scene, "equity_curve_daily.json", "{corrupt")
    c = ks.KillSwitchChecker(data_dir=scene, now=_now())
    outcomes = {r["trigger"]: r["outcome"] for r in c.evaluate_triggers()}
    assert outcomes["drawdown"] == ks.OUTCOME_UNMEASURED


def test_red_flag_freshness_is_the_declared_liveness_window():
    from spa_core.monitoring.uptime_monitor import AGENT_OUTPUT_FILES
    assert AGENT_OUTPUT_FILES["com.spa.red_flag_monitor"] == ("data/red_flags.json", ks.RED_FLAGS_MAX_AGE_S)


def test_numeric_limits_unchanged():
    assert (ks.RED_FLAGS_THRESHOLD, ks.SOFT_DERISK_THRESHOLD_PCT, ks.DRAWDOWN_THRESHOLD_PCT) == (5, 5.0, 10.0)


# ════════════════════════════════════════════════════════════════ P0-3 peg monitor

def _peg(d):
    from spa_core.monitoring.peg_monitor import PegStabilityMonitor
    return PegStabilityMonitor(data_path=str(d), use_alert_dispatcher=False)


def _rtmr(d, prices: dict, *, age_s=0, staleness_ok=True):
    ts = _now().timestamp() - age_s
    _w(d, "monitoring/signals/latest.json", {"signals": [
        {"ts": ts, "source": "peg", "scope": a, "staleness_ok": staleness_ok, "detail": {"price": p, "n_fresh": 4}}
        for a, p in prices.items()]})


@pytest.fixture()
def peg_scene(tmp_path):
    _w(tmp_path, "current_positions.json", {"positions": {"aave_v3": 50_000.0, "maple": 45_000.0},
                                            "cash_usd": 5_000.0})
    _w(tmp_path, "adapter_status.json", {"adapters": []})
    return tmp_path


def test_peg_no_price_anywhere_is_unknown_never_green(peg_scene):
    r = _peg(peg_scene).get_report()
    assert r.overall_status == "UNKNOWN" and r.unmeasured == r.total_monitored == 3
    assert all(s.current_price is None and s.status == "UNMEASURED" for s in r.statuses)
    assert r.worst_deviation_pct is None


def test_peg_get_price_has_no_synthetic_one():
    from spa_core.monitoring.peg_monitor import PegStabilityMonitor
    assert PegStabilityMonitor(use_alert_dispatcher=False).get_peg_price("aave_v3", {}) is None


def test_peg_quorum_price_measures_held_assets_green_positive_control(peg_scene):
    _rtmr(peg_scene, {"USDC": 0.9999})
    r = _peg(peg_scene).get_report()
    assert r.overall_status == "GREEN" and r.unmeasured == 0
    assert {s.adapter_id for s in r.statuses} == {"aave_v3", "maple", "cash"}   # held + cash, nothing else
    assert all(s.price_source == "rtmr_quorum" for s in r.statuses)


def test_peg_partial_coverage_is_unknown(peg_scene):
    _w(peg_scene, "hy_paper_trading.json", {"positions": [{"protocol": "susde", "notional_usd": 25_000.0}]})
    _rtmr(peg_scene, {"USDC": 1.0})
    r = _peg(peg_scene).get_report()
    assert r.overall_status == "UNKNOWN" and r.unmeasured == 1
    assert next(s for s in r.statuses if s.adapter_id == "susde").status == "UNMEASURED"


def test_peg_stale_or_untrusted_quorum_is_not_a_price(peg_scene):
    _rtmr(peg_scene, {"USDC": 1.0}, age_s=10_000)
    assert _peg(peg_scene).get_report().overall_status == "UNKNOWN"
    _rtmr(peg_scene, {"USDC": 1.0}, staleness_ok=False)
    assert _peg(peg_scene).get_report().overall_status == "UNKNOWN"


def test_peg_conflicting_sources_take_the_worse_price(peg_scene):
    _w(peg_scene, "adapter_status.json", {"aave_v3": {"usdc_price": 0.95}})
    _rtmr(peg_scene, {"USDC": 1.0})
    r = _peg(peg_scene).get_report()
    a = next(s for s in r.statuses if s.adapter_id == "aave_v3")
    assert a.conflict and a.current_price == 0.95 and a.status == "CRITICAL"
    assert r.overall_status == "RED"


def test_peg_depeg_via_quorum_is_red(peg_scene):
    _rtmr(peg_scene, {"USDC": 0.97})
    assert _peg(peg_scene).get_report().overall_status == "RED"


def test_peg_held_positions_unreadable_is_unknown(peg_scene):
    _w(peg_scene, "current_positions.json", "{broken")
    r = _peg(peg_scene).get_report()
    assert r.overall_status == "UNKNOWN" and "unreadable" in (r.reason or "")


def test_sleeve_marks_use_the_instrument_price_not_the_worse_peg_price(tmp_path):
    _w(tmp_path, "peg_history.json", {"latest": {"statuses": [
        {"adapter_id": "pt_x", "current_price": 0.985, "instrument_price": 0.999, "price_source": "adapter+rtmr"}]}})
    assert sb.observed_prices(tmp_path / "peg_history.json") == {"pt_x": 0.999}


def test_legacy_synthetic_marks_are_dropped_at_the_model_boundary(tmp_path, monkeypatch):
    """review S3: a v1 leg carrying the old monitor's invented mark 1.0 must not become the base of
    the first v2 re-mark (that would bake a phantom jump into the notional)."""
    from spa_core.paper_trading import hy_cycle
    monkeypatch.setattr(hy_cycle, "_HY_DATA_PATH", tmp_path / "hy_paper_trading.json")
    monkeypatch.setattr(sb, "_APY_RANKING", tmp_path / "apy_ranking.json")
    monkeypatch.setattr(sb, "_PEG_HISTORY", tmp_path / "peg_history.json")
    _w(tmp_path, "apy_ranking.json", {"by_apy": [{"protocol": "maple", "apy_pct": 5.0, "apy_source": "live",
                                                   "tvl_source": "live", "tvl_usd": 1e9, "network": "ethereum"}]})
    _w(tmp_path, "hy_paper_trading.json", {"equity": 100_000.0, "peak_equity": 100_000.0, "seed_equity": 100_000.0,
                                            "positions": [{"protocol": "maple", "notional_usd": 100_000.0,
                                                           "mark_price": 1.0}], "daily_history": []})
    _w(tmp_path, "peg_history.json", {"latest": {"statuses": [
        {"adapter_id": "maple", "current_price": 1.08, "instrument_price": 1.08, "price_source": "adapter"}]}})
    hy_cycle.run_hy_cycle(dry_run=False)
    st = json.loads((tmp_path / "hy_paper_trading.json").read_text())
    assert st["daily_history"][-1]["mtm_pnl_usd"] == 0.0          # first real mark = base, no jump
    assert st["positions"][0]["mark_price"] == 1.08


def test_sleeve_marks_only_instrument_prices(tmp_path):
    _w(tmp_path, "peg_history.json", {"latest": {"statuses": [
        {"adapter_id": "maple", "current_price": 0.9999, "price_source": "rtmr_quorum"},
        {"adapter_id": "morpho_steakhouse", "current_price": 1.0},                     # legacy row: synthetic 1.0
        {"adapter_id": "pt_x", "current_price": 0.98, "price_source": "adapter"}]}})
    assert sb.observed_prices(tmp_path / "peg_history.json") == {"pt_x": 0.98}


# ════════════════════════════════════════════════════════════════ downstream (E2E)

def _reactor(monkeypatch, d):
    from spa_core.monitoring import threat_reactor as tr
    monkeypatch.setattr(tr, "_DATA", d)
    monkeypatch.setattr(tr, "_STATUS", d / "threat_reactor_status.json")
    return tr


def _healthy_inputs(d):
    _w(d, "current_positions.json", {"positions": {"aave_v3": 50_000.0}, "cash_usd": 5_000.0})
    _rf(d, [])
    _w(d, "emergency_status.json", {"status": "CLEAR"})
    _rtmr(d, {"USDC": 1.0})
    _w(d, "adapter_status.json", {"adapters": []})
    _peg(d).save_report()


def test_blind_peg_sensor_cannot_reach_the_reactor_as_clear(tmp_path, monkeypatch):
    _healthy_inputs(tmp_path)
    tr = _reactor(monkeypatch, tmp_path)
    assert tr.run_reactor(dry_run=True)["clear"] is True        # positive control: all measured
    (tmp_path / "monitoring" / "signals" / "latest.json").unlink()
    _peg(tmp_path).save_report()                                  # monitor now blind
    rep = tr.run_reactor(dry_run=True)
    assert rep["clear"] is False and any(u.startswith("peg_report") for u in rep["unmeasured"])
    assert not rep["acted"] and rep["threats"] == []              # unknown is not a reason to liquidate


def test_reactor_counts_live_critical_flags_in_a_fallback_document(tmp_path, monkeypatch):
    _healthy_inputs(tmp_path)
    tr = _reactor(monkeypatch, tmp_path)
    # one live CRITICAL flag on a held protocol inside a fallback document → threat (was ignored)
    _rf(tmp_path, [_flag("aave_v3")], fallback=True, sources=("defillama", "bootstrap"), prov={"tvl_drop": "live"})
    assert any("aave_v3" in t for t in tr._detect_threats())
    # a stale document does not fire the intraday kill
    _rf(tmp_path, [_flag("aave_v3")], age_h=ks.RED_FLAGS_MAX_AGE_S / 3600 + 1, prov={"tvl_drop": "live"})
    assert tr._detect_threats() == []
    # exact held match: a flag on «aave» does not hit the held «aave_v3»
    _rf(tmp_path, [_flag("aave")], prov={"tvl_drop": "live"})
    assert tr._detect_threats() == []
    _rf(tmp_path, [_flag("aave_v3", source="bootstrap")], fallback=True, sources=("defillama", "bootstrap"))
    assert tr._detect_threats() == []
    # a bootstrap CATEGORY never fires the intraday kill, whatever the flag's own source says
    _rf(tmp_path, [_flag("aave_v3", cat="token_unlock")], fallback=True, sources=("defillama", "bootstrap"),
        prov={"tvl_drop": "live", "token_unlock": "bootstrap"})
    assert tr._detect_threats() == []


def test_reactor_does_not_announce_recovery_on_unmeasured_kill_inputs(tmp_path, monkeypatch):
    _healthy_inputs(tmp_path)
    (tmp_path / "red_flags.json").unlink()
    tr = _reactor(monkeypatch, tmp_path)
    assert tr._kill_switch_state() == tr.KS_UNKNOWN


def test_integrated_dashboard_does_not_paint_unknown_green(tmp_path):
    from spa_core.analytics.integrated_risk_dashboard import IntegratedRiskDashboard
    _w(tmp_path, "peg_report.json", {"overall_status": "UNKNOWN", "unmeasured": 2, "total_monitored": 3})
    out = IntegratedRiskDashboard(data_path=str(tmp_path))._read_peg_signal()
    assert out.level != "OK" and out.score > 0
    _w(tmp_path, "peg_report.json", {"total_monitored": 3})          # no status field at all
    assert IntegratedRiskDashboard(data_path=str(tmp_path))._read_peg_signal().level != "OK"


# ════════════════════════════════════════════════════════════════ cycle E2E (LAW 1 wiring)

def _cycle(tmp, *, red_flags):
    """The real run_cycle in a tmp sandbox (hermetic fakes, the same shape as test_cycle_derisk_e2e)."""
    from types import SimpleNamespace
    from spa_core.paper_trading import cycle_runner as cr
    from spa_core.telegram import push_policy
    now = _now().replace(microsecond=0)
    held = {"aave_v3": 40_000.0, "compound_v3": 40_000.0}
    _w(tmp, "current_positions.json", {"positions": held, "cash_usd": 20_000.0})
    curve = [{"date": (now - timedelta(days=60 - i)).date().isoformat(),
              "close_equity": 100_000.0 + i, "open_equity": 100_000.0 + i} for i in range(60)]
    _w(tmp, "equity_curve_daily.json", {"source": "cycle_runner", "daily": curve})
    if red_flags:
        _w(tmp, "red_flags.json", {"generated_at": now.isoformat(), "red_flags": [], "fallback_used": False,
                                   "sources": ["defillama"], "provenance": {"by_category": {"tvl_drop": "live"}}})
    adapters = [{"protocol": p, "id": p, "apy_pct": 4.0, "tvl_usd": 1e8, "tvl_source": "live", "tier": "T1",
                 "status": "ok", "chain": f"c_{p}"} for p in ("aave_v3", "compound_v3", "morpho_blue")]

    class _Alloc:
        def allocate(self):
            t = {"aave_v3": 30_000.0, "compound_v3": 30_000.0, "morpho_blue": 30_000.0}
            return SimpleNamespace(target_usd=t, target_weights={k: v / 1e5 for k, v in t.items()},
                                   expected_apy_pct=4.0, model_used="fake", strategy_loop_active=False)

    sent = []
    orig = push_policy._send
    push_policy._send = lambda text: sent.append(text) or True
    try:
        res = cr.run_cycle(data_dir=str(tmp), now=now,
                           orchestrator_fn=lambda d: SimpleNamespace(adapters=adapters, status="ok",
                                                                    data_freshness="live"),
                           allocator=_Alloc(), risk_scorer_fn=lambda d: None, track_persister_fn=lambda d: None,
                           write=True, allow_live_write=False)
    finally:
        push_policy._send = orig
    return res, held


def test_cycle_holds_when_kill_switch_input_is_unmeasured(tmp_path):
    res, held = _cycle(tmp_path, red_flags=False)
    assert res.status == "blocked_safety_check_error"
    assert any("kill_switch_unmeasured" in n for n in res.notes)
    assert res.kill_switch_active is False                       # held, not liquidated
    assert {k: v for k, v in res.positions.items() if v} == held   # no new trade


def test_cycle_proceeds_when_kill_switch_inputs_are_measured(tmp_path):
    res, _ = _cycle(tmp_path, red_flags=True)
    assert res.status != "blocked_safety_check_error"
    assert not any("kill_switch_unmeasured" in n for n in res.notes)


def test_downstream_readers_do_not_read_unmeasured_kill_status_as_ok(tmp_path, monkeypatch):
    """review S5: readers of kill_switch_status.json honour `state`, not only `triggered`."""
    import importlib.util
    _w(tmp_path, "kill_switch_status.json", {"triggered": False, "state": "UNMEASURED", "reason": "red_flags missing"})
    spec = importlib.util.spec_from_file_location(
        "gpf", Path(__file__).resolve().parents[2] / "scripts" / "golive_preflight.py")
    gpf = importlib.util.module_from_spec(spec)
    import sys
    monkeypatch.setitem(sys.modules, "gpf", gpf)   # dataclasses resolve their module by name
    spec.loader.exec_module(gpf)
    assert gpf._check_kill_switch_not_active(tmp_path).status == "warn"
    from spa_core.monitoring import rules_watchdog as rw
    now = _iso()
    _w(tmp_path, "kill_switch_status.json", {"generated_at": now, "triggered": False, "state": "UNMEASURED",
                                             "reason": "red_flags missing"})
    _w(tmp_path, "derisk_status.json", {"generated_at": now, "active": False, "tier": "NONE"})
    monkeypatch.setattr(rw, "_KILL_SWITCH_STATUS_PATH", tmp_path / "kill_switch_status.json")
    monkeypatch.setattr(rw, "_DERISK_STATUS_PATH", tmp_path / "derisk_status.json")
    res = rw.check_circuit_breaker()
    assert res.status != "OK" and "UNMEASURED" in str(res.message)
