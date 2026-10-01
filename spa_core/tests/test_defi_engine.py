"""DeFi Engine vNext Phase 1 foundation (ADR-532) — every component, with controls both ways.

# LLM_FORBIDDEN

Offline: every test builds its own sandbox ``data/`` dir; the live tree is never read. Dates in the
fixtures are opaque labels (the engine never parses them); ``now`` is injected where freshness
matters, so no test depends on the calendar.
"""
from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.defi_engine import apy_contract, books, coverage, engine, exit_model, loss_budget
from spa_core.defi_engine import mechanics as M
from spa_core.defi_engine import tiers

REPO = Path(__file__).resolve().parents[2]
V2 = "sleeve-econ-v2"


# ── sandbox ──────────────────────────────────────────────────────────────────

def _w(d: Path, name: str, obj) -> None:
    p = d / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def _sandbox(tmp_path: Path, *, sleeve_v2_rows: int = 0, now: datetime | None = None) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    _w(d, "current_positions.json", {
        "capital_usd": 100000.0, "current_equity_usd": 100100.0, "cash_usd": 5000.0,
        "positions": {"aave_v3": 40000.0, "maple": 20000.0, "fluid_fusdc": 35000.0}})
    daily = [{"date": f"d{i:02d}", "equity": 100000.0 + 10.0 * i, "cost_usd": 0.0,
              "daily_yield_usd": 10.0, "evidenced": True} for i in range(11)]
    daily[5]["cost_usd"] = 4.0
    daily.append({"date": "pre", "equity": 1.0, "evidenced": False})     # never counted
    _w(d, "equity_curve_daily.json", {"daily": daily})
    _w(d, "adapter_orchestrator_status.json", {"generated_at": "snap", "adapters": [
        {"protocol": "aave_v3", "tier": "T1", "apy_pct": 4.0, "tvl_usd": 4.0e8, "tvl_source": "live",
         "live_data": True, "pool_id": "p-aave"},
        {"protocol": "maple", "tier": "T2", "apy_pct": 6.0, "tvl_usd": 1.0e8, "tvl_source": "live",
         "live_data": True},
        {"protocol": "fluid_fusdc", "tier": "T2", "apy_pct": 5.0, "tvl_usd": 2.0e9, "tvl_source": "static",
         "live_data": True}]})
    hist = [{"date": f"v1-{i}", "equity": 100000.0 - 30 * i} for i in range(3)]
    hist += [{"date": f"v2-{i}", "equity": 99900.0 + 12 * i, "cost_usd": 0.0, "daily_yield_usd": 12.0,
              "economics_model": V2} for i in range(sleeve_v2_rows)]
    for name, legs in (("hy_paper_trading.json", [("maple", 25000.0), ("susde", 25000.0),
                                                  ("fluid_fusdc", 25000.0), ("morpho_steakhouse", 24900.0)]),
                       ("lp_paper_trading.json", [("maple", 50000.0), ("fluid_fusdc", 50000.0)])):
        _w(d, name, {"equity": 99900.0, "seed_equity": 100000.0, "daily_history": hist,
                     "positions": [{"protocol": k, "notional_usd": v, "apy_pct": 5.0, "stale": False,
                                    "is_delta_neutral": True} for k, v in legs]})
    _w(d, "apy_series_daily.json", {"series": {
        "aave_v3": [[f"s{i}", 4.0] for i in range(10)],
        "maple": [[f"s{i}", 2.0] for i in range(10)],          # spot 6.0 = 3× ⇒ shock
        "fluid_fusdc": [[f"s{i}", 5.0] for i in range(3)]}})   # too short ⇒ unmeasured
    now = now or datetime.now(timezone.utc)
    _w(d, "monitoring/signals/latest.json", {"ts": now.timestamp() - 60, "signals": [
        {"source": "peg", "scope": "USDC", "staleness_ok": True},
        {"source": "liquidity", "scope": "aave_v3", "staleness_ok": True},
        {"source": "tvl", "scope": "aave_v3", "staleness_ok": True},
        {"source": "tvl", "scope": "fluid", "staleness_ok": False}]})
    return d


# ── mechanics: the second risk axis ──────────────────────────────────────────

def test_every_registry_key_has_a_mechanic():
    from spa_core.adapters import ADAPTER_REGISTRY
    missing = sorted(e[0] for e in ADAPTER_REGISTRY if e[0] not in M.POSITION_MECHANIC)
    assert not missing, f"registry keys without a mechanic (would be an unclassified position): {missing}"
    bad = sorted(k for k, (mech, _a) in M.POSITION_MECHANIC.items() if mech not in M.MECHANICS)
    assert not bad, f"mechanic outside the vocabulary: {bad}"


def test_neutrality_is_computed_not_stamped():
    assert M.price_delta_neutral("maple") is True           # USD credit, non-directional
    assert M.price_delta_neutral("susde") is True           # USD synthetic (depeg is the peg sensor's job)
    assert M.price_delta_neutral("tbtc_lending") is False   # BTC underlying ⇒ price delta in a USD book
    assert M.price_delta_neutral("no_such_pool") is None    # unknown is NOT measured, never True


def test_composite_risk_takes_the_worse_axis():
    r = M.position_risk("aave_v3")
    assert r["composite"] == max(r["protocol_score"], r["mechanic_score"])
    assert M.position_risk("susde")["binding_axis"] in ("protocol", "mechanic")
    assert M.position_risk("no_such_pool")["composite"] is None


def test_mechanic_cap_findings_both_ways():
    inside = M.mechanic_exposure([{"protocol": "maple", "notional_usd": 25_050.0}], 100_000.0)
    assert inside["findings"] == [], "within the 0.1 pp tolerance of the cap is AT the cap"
    over = M.mechanic_exposure([{"protocol": "maple", "notional_usd": 50_000.0}], 100_000.0)
    assert [f["mechanic"] for f in over["findings"]] == ["rwa_credit"]
    unknown = M.mechanic_exposure([{"protocol": "mystery", "notional_usd": 1.0}], 100.0)
    assert unknown["findings"][0]["finding"] == "position with an unclassified mechanic"
    assert M.mechanic_exposure([], None)["measured"] is False


# ── APY contract ─────────────────────────────────────────────────────────────

def _site_formula(bars):
    """Verbatim method of scripts/generate_track_snapshot.py (paper_apy_pct)."""
    ev = [b for b in bars if b.get("evidenced") is True]
    return ((ev[-1]["equity"] / ev[0]["equity"]) ** (365.0 / len(ev)) - 1.0) * 100.0


def test_track_net_equals_the_site_headline_method(tmp_path):
    d = _sandbox(tmp_path)
    b = books.load_books(d)["conservative"]
    got = apy_contract.book_contract(b)["track_realized_apy_net"]["value"]
    bars = json.loads((d / "equity_curve_daily.json").read_text())["daily"]
    assert got == round(_site_formula(bars), 4)


def test_gross_adds_back_costs_and_net_subtracts_drag(tmp_path):
    c = apy_contract.book_contract(books.load_books(_sandbox(tmp_path))["conservative"])
    assert c["track_realized_apy_gross"]["value"] > c["track_realized_apy_net"]["value"]
    assert c["track_realized_apy_gross"]["costs_added_back_usd"] == 4.0
    gross_spot = (40000 * 4 + 20000 * 6 + 35000 * 5) / 95000
    assert c["book_spot_apy_gross"]["value"] == round(gross_spot, 4)
    assert c["book_spot_apy_on_nav"]["value"] == round((40000 * 4 + 20000 * 6 + 35000 * 5) / 100100, 4)
    assert c["book_spot_apy_net"]["value"] == pytest.approx(
        c["book_spot_apy_on_nav"]["value"] - c["book_cost_drag_30d"]["value"], abs=1e-3)
    # drag pinned by hand: 11 bars with an observed cost, one charge of $4 after the first bar
    eqs = [100000.0 + 10.0 * i for i in range(11)]
    want = 4.0 / (sum(eqs) / 11) * 365.0 / 10 * 100.0
    assert c["book_cost_drag_30d"]["value"] == round(want, 4)
    assert c["book_cost_drag_30d"]["window_days"] == 10


def test_a_bar_without_a_cost_field_is_not_a_zero_cost_bar():
    series = [{"date": "a", "equity": 100.0, "cost_usd": 0.0},
              {"date": "b", "equity": 101.0, "cost_usd": None},     # pre-ADR-298 bar: no field
              {"date": "c", "equity": 102.0, "cost_usd": 1.0},
              {"date": "d", "equity": 103.0, "cost_usd": 0.0}]
    c = apy_contract.book_contract({"measured": True, "positions": [], "nav_usd": 103.0,
                                    "cash_usd": 103.0, "series": series})
    assert c["book_cost_drag_30d"]["window_days"] == 1, "the run of observed costs stops at the gap"
    assert c["book_cost_drag_30d"]["cost_usd"] == 0.0, "the run's first bar opens the window, its cost is outside"
    assert c["track_realized_apy_gross"]["bars_without_cost_field"] == 1
    assert c["track_realized_apy_gross"]["costs_added_back_usd"] == 1.0
    only_gap = apy_contract.book_contract({"measured": True, "positions": [], "nav_usd": 1.0,
                                           "cash_usd": 1.0, "series": series[:2]})
    assert only_gap["book_cost_drag_30d"]["value"] is None


def test_unmeasured_is_a_reason_not_a_zero(tmp_path):
    c = apy_contract.book_contract(books.load_books(_sandbox(tmp_path))["balanced"])
    for k in ("track_realized_apy_net", "track_realized_apy_gross", "cumulative_return_pct",
              "book_cost_drag_30d", "book_spot_apy_net"):
        assert c[k]["value"] is None and c[k]["unmeasured_reason"], k
    gone = apy_contract.book_contract({"measured": False, "reason": "file absent"})
    assert all(v["value"] is None for v in gone.values())


# ── books: owner Option A ────────────────────────────────────────────────────

def test_loading_keeps_a_missing_cost_as_none(tmp_path):
    d = _sandbox(tmp_path)
    curve = json.loads((d / "equity_curve_daily.json").read_text())
    del curve["daily"][3]["cost_usd"]
    (d / "equity_curve_daily.json").write_text(json.dumps(curve))
    b = books.load_books(d)["conservative"]
    assert b["series"][3]["cost_usd"] is None
    assert apy_contract.book_contract(b)["track_realized_apy_gross"]["bars_without_cost_field"] == 1


def test_sleeve_cash_is_unmeasured_not_a_residual(tmp_path):
    bk = books.load_books(_sandbox(tmp_path, sleeve_v2_rows=3))
    bal = bk["balanced"]
    assert bal["cash_usd"] is None and bal["cash_reason"]
    assert bal["notional_minus_nav_usd"] == round(99900.0 - 99900.0, 2)
    c = apy_contract.book_contract(bal)
    assert c["book_spot_apy_on_nav"]["value"] is None, "no cash ⇒ no NAV-based income share"
    ex = exit_model.book_exit(bal, books.pool_snapshot(tmp_path / "data")["pools"])
    assert ex["share_exitable_24h"] is None and ex["share_basis"].startswith("deployed")
    assert ex["share_illiquid"] <= 1.0


def test_sleeve_series_is_v2_only(tmp_path):
    b = books.load_books(_sandbox(tmp_path, sleeve_v2_rows=4))["aggressive"]
    assert len(b["series"]) == 4 and b["pre_fix_rows"] == 3
    assert all(r["date"].startswith("v2-") for r in b["series"])
    assert books.load_books(tmp_path / "nope")["balanced"]["measured"] is False


def test_book_stops_are_read_from_the_enforcing_code(tmp_path):
    from spa_core.governance import kill_switch as ks
    from spa_core.paper_trading import hy_cycle, lp_cycle
    g = books.gates()
    assert g["conservative"]["stops"][0]["drawdown_pct"] == ks.SOFT_DERISK_THRESHOLD_PCT
    assert g["balanced"]["stops"][0]["drawdown_pct"] == round(abs(hy_cycle._KILL_DRAWDOWN_THRESHOLD) * 100, 4)
    assert g["aggressive"]["stops"][0]["drawdown_pct"] == round(abs(lp_cycle.IL_KILL_THRESHOLD) * 100, 4)


# ── exit model ───────────────────────────────────────────────────────────────

def test_latency_comes_from_the_adapter_class():
    from spa_core.adapters.maple import MapleAdapter
    assert exit_model.latency_hours("maple") == MapleAdapter.EXIT_LATENCY_HOURS == 336.0
    assert exit_model.latency_hours("fluid_fusdc") == 0.0, \
        "the legacy mirror lacks fluid_fusdc and calls 20 % of the book illiquid"
    assert exit_model.latency_hours("no_such_pool") is None


def test_book_exit_profile_and_policy(tmp_path):
    d = _sandbox(tmp_path)
    bk = books.load_books(d)
    pools = books.pool_snapshot(d)["pools"]
    agg = exit_model.book_exit(bk["aggressive"], pools)
    assert agg["policy_ok"] is False and agg["illiquid_positions"] == ["maple"]
    cons = exit_model.book_exit(bk["conservative"], pools)
    assert cons["policy_ok"] is True                     # maple 20k of 100.1k ≤ 25 %
    rows = {r["protocol"]: r for r in cons["positions"]}
    assert rows["aave_v3"]["share_of_pool_tvl"] == pytest.approx(40000 / 4.0e8)
    assert rows["fluid_fusdc"]["share_of_pool_tvl"] is None, "static TVL is not exit depth (ADR-053)"


# ── loss budget ──────────────────────────────────────────────────────────────

def test_runtime_budget_mirror_equals_the_published_page():
    bands = json.loads((REPO / "landing/src/lib/tier_bands.json").read_text(encoding="utf-8"))
    for book, pct in loss_budget.PUBLISHED_BUDGET_PCT.items():
        m = re.search(r"≤\s*(\d+(?:\.\d+)?)\s*%\s*drawdown", bands[book]["band_en"])
        assert m, f"{book}: published band carries no drawdown budget"
        assert float(m.group(1)) == pct, f"{book}: page {m.group(1)} % vs engine {pct} %"


def test_budget_binding_and_levels(tmp_path):
    bk = books.load_books(_sandbox(tmp_path))
    cons = loss_budget.book_budget("conservative", bk["conservative"])
    assert cons["bound_by_enforced_stop"] is False and cons["unbound_gap_pct"] == 2.0
    assert cons["status"] == "ok"
    bal = loss_budget.book_budget("balanced", bk["balanced"])
    assert bal["bound_by_enforced_stop"] is True and bal["status"] == "unmeasured"
    drop = {"measured": True, "gate": bk["conservative"]["gate"],
            "series": [{"equity": 100.0}, {"equity": 97.0}]}
    assert loss_budget.book_budget("conservative", drop)["status"] == "breach"
    assert loss_budget.book_budget("conservative", {**drop, "series": [{"equity": 100.0}, {"equity": 98.5}]}
                                   )["status"] == "watch"
    recovered = loss_budget.book_budget("conservative", {**drop, "series": [{"equity": 100.0}, {"equity": 97.0},
                                                                            {"equity": 100.0}]})
    assert recovered["status"] == "breach" and recovered["current_drawdown_pct"] == 0.0, \
        "a budget once spent stays spent: the WORST drawdown consumes it"
    single = loss_budget.book_budget("conservative", {**drop, "series": [{"equity": 100.0}]})
    assert single["status"] == "unmeasured"
    unknown_stop = loss_budget.book_budget("conservative", {**drop, "gate": {"stops": []}})
    assert unknown_stop["bound_by_enforced_stop"] is None and unknown_stop["bound_reason"]


# ── tier authority census ────────────────────────────────────────────────────

#: Money-path tier copies LOOSER than the authority, measured 2026-10-01. May only SHRINK: closing
#: one is an owner-permitted tier change (ADR-532 §Owner gate); adding one is a regression.
KNOWN_LOOSER_ON_MONEY_PATH = {("policy_enforcer", "aave_v3_base"), ("policy_enforcer", "morpho_steakhouse")}


def test_no_new_money_path_copy_is_looser_than_the_authority():
    cen = tiers.census(None)
    looser = {(r["copy"], r["protocol"]) for r in cen["disagreements"]
              if r["money_path"] and r["direction"] == "looser"}
    assert looser - KNOWN_LOOSER_ON_MONEY_PATH == set(), f"new looser money-path tier copy: {looser}"
    assert KNOWN_LOOSER_ON_MONEY_PATH - looser == set(), \
        f"closed {KNOWN_LOOSER_ON_MONEY_PATH - looser} — remove it from KNOWN_LOOSER_ON_MONEY_PATH"


def test_census_catches_a_planted_disagreement(monkeypatch):
    from spa_core.risk import policy_enforcer as pe
    monkeypatch.setattr(pe, "T1_ADAPTERS", frozenset(pe.T1_ADAPTERS) | {"maple"})
    rows = [r for r in tiers.census(None)["disagreements"] if r["protocol"] == "maple"
            and r["copy"] == "policy_enforcer"]
    assert rows and rows[0]["direction"] == "looser" and rows[0]["money_path"] is True


def test_census_names_unmeasured_copies_instead_of_agreeing():
    cen = tiers.census(None)
    assert {"data_registry", "orchestrator_live"} <= set(cen["copies_unmeasured"])


# ── coverage ─────────────────────────────────────────────────────────────────

def test_coverage_declared_vs_observed(tmp_path):
    now = datetime.now(timezone.utc)
    d = _sandbox(tmp_path, now=now)
    rep = coverage.coverage_report(books.load_books(d), d, now.timestamp())
    cons = {r["protocol"]: r for r in rep["books"]["conservative"]}
    assert cons["aave_v3"]["dimensions"]["liquidity"]["observed"] is True
    assert "liquidity" in cons["maple"]["uncovered"], "maple: no liquidity sensor scope"
    assert cons["fluid_fusdc"]["dimensions"]["tvl"]["observed"] is False, "stale signal is not coverage"
    agg = {r["protocol"]: r for r in rep["books"]["aggressive"]}
    assert agg["maple"]["dimensions"]["liquidity"]["declared"] is False, "sleeves are not sized"
    assert all("rate" in r["uncovered"] for rows in rep["books"].values() for r in rows)


def test_a_stale_signal_file_is_unmeasured_not_uncovered(tmp_path):
    now = datetime.now(timezone.utc)
    d = _sandbox(tmp_path, now=now)
    rep = coverage.coverage_report(books.load_books(d), d, now.timestamp() + 3600)
    assert rep["observed"]["measured"] is False and rep["observed"]["fresh_scopes"] == []
    aave = next(r for r in rep["books"]["conservative"] if r["protocol"] == "aave_v3")
    assert "liquidity" in aave["unmeasured"] and "liquidity" not in aave["uncovered"]
    assert "rate" in aave["uncovered"], "no declared scope stays uncovered whatever the signals say"
    assert rep["totals"]["fully_covered"] == 0 and rep["totals"]["with_unmeasured"] > 0


def test_rate_watch_both_ways():
    series = {"a": [[i, 4.0] for i in range(10)], "b": [[i, 2.0] for i in range(10)],
              "c": [[i, 5.0] for i in range(3)]}
    assert coverage.rate_watch("a", 4.4, series)["status"] == "ok"
    assert coverage.rate_watch("b", 6.0, series)["status"] == "shock"
    assert coverage.rate_watch("c", 5.0, series)["status"] == "unmeasured"
    assert coverage.rate_watch("a", None, series)["status"] == "unmeasured"


# ── engine: status contract + passports ──────────────────────────────────────

def test_publish_writes_both_documents(tmp_path):
    d = _sandbox(tmp_path, sleeve_v2_rows=3)
    status = engine.publish(d)
    on_disk = json.loads((d / "defi_engine" / "status.json").read_text())
    passports = json.loads((d / "defi_engine" / "passports.json").read_text())["passports"]
    assert on_disk["schema"] == "defi-engine-status/1" and on_disk["money_path_effect"].startswith("none")
    assert len(passports) == status["n_passports"] == 3 + 4 + 2
    p = next(x for x in passports if x["id"] == "aggressive:maple")
    assert p["what_it_is"]["mechanic"] == "rwa_credit" and p["exit"]["exit_latency_hours"] == 336.0
    assert p["risk"]["protocol_tier"] == "T2" and p["evidence_level"] == "L3 · paper track"
    kinds = {(f.get("book"), f["kind"]) for f in status["findings"]}
    assert ("aggressive", "exit_liquidity") in kinds and ("conservative", "loss_budget_unbound") in kinds
    assert ("conservative", "rate_shock") in kinds


def test_publish_advisory_names_the_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    why = engine.publish_advisory(tmp_path)
    assert why and "boom" in why


def test_money_path_never_imports_the_engine():
    """Advisory by construction: no gate, allocator, policy or cycle body imports defi_engine."""
    roots = [REPO / "spa_core" / d for d in ("risk", "governance", "allocator", "execution", "tuner")]
    files = [p for r in roots for p in r.rglob("*.py")]
    files += [REPO / "spa_core/paper_trading" / f for f in ("cycle_runner.py", "cycle_gates.py",
                                                             "risk_gate.py", "sleeve_book.py")]
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            mods = ([a.name for a in n.names] if isinstance(n, ast.Import)
                    else [n.module or ""] if isinstance(n, ast.ImportFrom) else [])
            assert not any(m.startswith("spa_core.defi_engine") for m in mods), f"{f} imports defi_engine"


def test_cycles_publish_only_from_their_cli_block():
    """The call sits in the CLI block, AFTER the cycle ran, INSIDE a try — never in the cycle body."""
    for name, cycle_fn in (("hy_cycle.py", "run_hy_cycle"), ("lp_cycle.py", "run_lp_cycle")):
        tree = ast.parse((REPO / "spa_core/paper_trading" / name).read_text(encoding="utf-8"))
        main = [n for n in tree.body if isinstance(n, ast.If) and "__main__" in ast.unparse(n.test)]
        assert main, name
        rest = ast.unparse(ast.Module(body=[n for n in tree.body if n not in main], type_ignores=[]))
        assert "defi_engine" not in rest, f"{name}: the cycle body must not depend on the engine"
        calls = [n for n in ast.walk(main[0]) if isinstance(n, ast.Call)]
        cyc = [c.lineno for c in calls if getattr(c.func, "id", None) == cycle_fn]
        pub = [c for c in calls if getattr(c.func, "id", None) == "publish_advisory"]
        assert cyc and pub, f"{name}: missing cycle call or publish call"
        assert all(p.lineno > max(cyc) for p in pub), f"{name}: publish must run after the cycle"
        tries = [n for n in ast.walk(main[0]) if isinstance(n, ast.Try)]
        inside = {id(c) for tr in tries for c in ast.walk(ast.Module(body=tr.body, type_ignores=[]))}
        assert all(id(p) in inside for p in pub), f"{name}: publish must be guarded by try/except"
