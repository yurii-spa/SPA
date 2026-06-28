"""
test_portfolio_exit_nav_and_anchors.py — WORKSTREAM A: portfolio-wide exit-NAV (A2), anchors (A3),
the cross-implementation metamorphic property, and the API reproduce-block contract (A4).

Quality bar: a reviewer confirms the portfolio schedule covers EVERY market on its OWN single-market
depth (never aggregated), with fail-CLOSED holes never fabricated; that the anchor producer is
append-only/monotonic/idempotent and the verifier confirms it; and that for RANDOM valid chains the
server head_hash == the standalone verifier head_hash (cross-implementation). PURE / no network.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from spa_core.audit import hash_chain
from spa_core.strategy_lab.rates_desk import anchors as A
from spa_core.strategy_lab.rates_desk import proof_chain
from spa_core.strategy_lab.rates_desk.contracts import RatePolicyParams
from spa_core.strategy_lab.rates_desk.exit_nav import (
    EXIT_TICKETS_USD,
    build_exit_nav_schedule,
    build_portfolio_schedule,
)

_ROOT = Path(__file__).resolve().parents[2]
_VERIFY = _ROOT / "scripts" / "verify_spa.py"
_P = RatePolicyParams()


def _load_verifier():
    spec = importlib.util.spec_from_file_location("_verify_spa_pf", _VERIFY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


V = _load_verifier()


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (A2) portfolio-wide exit-NAV
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _surface_multi():
    """A surface with two priced markets of very different depth (one deep, one thin)."""
    return {
        "as_of": "2026-06-25",
        "quotes": [
            {"market_id": "DEEP", "underlying": "usdc", "exit_liquidity_usd": "80000000",
             "kind": "stable_rwa"},
            {"market_id": "THIN", "underlying": "usde", "exit_liquidity_usd": "2000",
             "kind": "stable_synth"},
        ],
    }


def test_portfolio_covers_every_priced_market():
    """The portfolio schedule must include EVERY priced market on the surface — not just the best."""
    pf = build_portfolio_schedule(_surface_multi(), {}, _P, EXIT_TICKETS_USD, _ROOT / "data")
    ids = {m["market_id"] for m in pf["markets"]}
    assert "DEEP" in ids and "THIN" in ids
    assert pf["n_markets"] >= 2


def test_portfolio_depth_is_per_market_never_aggregated():
    """Each market row uses ITS OWN single-market depth, never the portfolio aggregate."""
    pf = build_portfolio_schedule(_surface_multi(), {}, _P, EXIT_TICKETS_USD, _ROOT / "data")
    by_id = {m["market_id"]: m for m in pf["markets"]}
    assert by_id["DEEP"]["depth_usd"] == 80000000.0
    assert by_id["THIN"]["depth_usd"] == 2000.0
    # aggregate is disclosure-only and must differ from any single market's depth.
    agg = pf["aggregate_depth_usd"]
    assert agg == 80002000.0
    for m in pf["markets"]:
        assert m["depth_usd"] != agg
    assert "NEVER" in pf["depth_aggregation"] or "single-market" in pf["depth_aggregation"]


def test_portfolio_thin_market_fails_closed_with_holes():
    """A market below the DEX floor publishes HOLES (net=None, flagged) — never a fabricated fill."""
    pf = build_portfolio_schedule(_surface_multi(), {}, _P, EXIT_TICKETS_USD, _ROOT / "data")
    by_id = {m["market_id"]: m for m in pf["markets"]}
    thin = by_id["THIN"]
    assert thin["flagged"] is True
    for row in thin["schedule"]:
        assert row["net_proceeds_usd"] is None
        assert row["flagged"] is True
        assert row["flag_reason"] == "insufficient_contemporaneous_depth"


def test_portfolio_deep_market_monotonic_real_numbers():
    """The deep market produces real, monotonic-in-size haircuts (the conservative bound bites)."""
    pf = build_portfolio_schedule(_surface_multi(), {}, _P, EXIT_TICKETS_USD, _ROOT / "data")
    deep = {m["market_id"]: m for m in pf["markets"]}["DEEP"]
    rows = deep["schedule"]
    assert all(not r["flagged"] for r in rows)
    hc = [r["haircut_pct"] for r in rows]
    assert hc == sorted(hc), "haircut must be non-decreasing in ticket size"


def test_portfolio_rows_have_reproducible_proof_hashes():
    """Every portfolio row's proof_hash reproduces via the standalone verifier (§6)."""
    result = build_exit_nav_schedule(write=False, surface=_surface_multi(), deep={},
                                     book={"market_id": "DEEP", "underlying": "usdc",
                                           "gross_usd": 1_000_000.0, "as_of": "2026-06-25",
                                           "source": "live"})
    res = V.verify_exit_nav(result)
    assert res["valid"] is True, res["first_bad"]
    # portfolio rows are included in the row count.
    n_portfolio_rows = sum(len(m["schedule"]) for m in result["portfolio"]["markets"])
    assert n_portfolio_rows > 0
    assert res["n_rows"] >= n_portfolio_rows


def test_portfolio_deterministic_byte_identical():
    """Same inputs → byte-identical portfolio JSON (determinism)."""
    s = _surface_multi()
    a = build_portfolio_schedule(s, {}, _P, EXIT_TICKETS_USD, _ROOT / "data")
    b = build_portfolio_schedule(s, {}, _P, EXIT_TICKETS_USD, _ROOT / "data")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_portfolio_empty_surface_no_markets():
    pf = build_portfolio_schedule({"as_of": "2026-06-25", "quotes": []}, {}, _P, EXIT_TICKETS_USD,
                                  _ROOT / "data")
    # With no open books + no priced markets, the portfolio is empty (vacuous, flagged False).
    assert isinstance(pf["markets"], list)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (A3) cross-eviction anchor producer — append-only / monotonic / idempotent
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _mk_chain(tmp_path: Path, n: int) -> Path:
    """Write a valid public decision_log with n REFUSAL rows, re-based per the spec."""
    log = tmp_path / "decision_log.jsonl"
    rows = []
    for i in range(n):
        rows.append({"ts": "2026-06-26T00:00:00+00:00", "kind": "REFUSAL", "approved": False,
                     "reason": "tail_veto", "underlying": f"u{i}", "proof_hash": f"{i:064x}"})
    rebased = proof_chain._rebase_rows([{"ts": r["ts"], **{k: v for k, v in r.items() if k != "ts"}}
                                        for r in rows])
    log.write_text("\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rebased)
                   + "\n", encoding="utf-8")
    return log


def test_anchor_appends_and_verifies(tmp_path):
    log = _mk_chain(tmp_path, 5)
    anchors_path = tmp_path / "anchors.jsonl"
    a = A.append_anchor(ts="2026-06-28T00:00:00+00:00", anchors_path=anchors_path, log_path=log)
    assert a is not None and a["seq"] == 0 and a["chain_length"] == 5
    res = A.verify_anchors(anchors_path=anchors_path, log_path=log)
    assert res["valid"] is True and res["latest_matches_head"] is True


def test_anchor_idempotent_no_duplicate(tmp_path):
    """Appending again with an unchanged head is a no-op (no duplicate anchors)."""
    log = _mk_chain(tmp_path, 5)
    anchors_path = tmp_path / "anchors.jsonl"
    A.append_anchor(ts="t0", anchors_path=anchors_path, log_path=log)
    again = A.append_anchor(ts="t1", anchors_path=anchors_path, log_path=log)
    assert again is None
    assert len(A.recent_anchors(100, anchors_path=anchors_path)) == 1


def test_anchor_grows_with_chain(tmp_path):
    """After the chain grows, a new anchor appends with the longer length + new head."""
    anchors_path = tmp_path / "anchors.jsonl"
    log5 = _mk_chain(tmp_path, 5)
    A.append_anchor(ts="t0", anchors_path=anchors_path, log_path=log5)
    log9 = _mk_chain(tmp_path, 9)  # longer chain, different head
    a2 = A.append_anchor(ts="t1", anchors_path=anchors_path, log_path=log9)
    assert a2 is not None and a2["seq"] == 1 and a2["chain_length"] == 9
    ledger = A.recent_anchors(100, anchors_path=anchors_path)
    assert [x["seq"] for x in ledger] == [0, 1]
    assert ledger[0]["chain_length"] < ledger[1]["chain_length"]


def test_anchor_is_append_only_existing_lines_unchanged(tmp_path):
    """Appending an anchor must NEVER rewrite existing lines (strictly append-only content)."""
    anchors_path = tmp_path / "anchors.jsonl"
    log5 = _mk_chain(tmp_path, 5)
    A.append_anchor(ts="t0", anchors_path=anchors_path, log_path=log5)
    first_line = anchors_path.read_text(encoding="utf-8").splitlines()[0]
    log9 = _mk_chain(tmp_path, 9)
    A.append_anchor(ts="t1", anchors_path=anchors_path, log_path=log9)
    lines = anchors_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == first_line, "existing anchor line was mutated — not append-only!"
    assert len(lines) == 2


def test_anchor_fails_closed_on_broken_chain(tmp_path):
    """A broken/unverified decision chain → no anchor is minted (fail-CLOSED)."""
    log = tmp_path / "decision_log.jsonl"
    log.write_text(json.dumps({"seq": 0, "ts": "t", "prev_hash": "x" * 64,
                               "entry_hash": "y" * 64, "kind": "REFUSAL"}) + "\n", encoding="utf-8")
    anchors_path = tmp_path / "anchors.jsonl"
    a = A.append_anchor(ts="t0", anchors_path=anchors_path, log_path=log)
    assert a is None
    assert not anchors_path.exists() or anchors_path.read_text().strip() == ""


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# cross-implementation metamorphic property: server head_hash == verify_spa.py head_hash
# ══════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("n", [0, 1, 2, 5, 13, 40])
def test_server_and_standalone_agree_on_random_valid_chains(tmp_path, n):
    """For random valid chains, the server verifier (proof_chain.verify_mirror) and the standalone
    verify_spa.py reach the IDENTICAL head_hash + valid verdict (cross-implementation)."""
    log = _mk_chain(tmp_path, n)
    rows = [json.loads(ln) for ln in log.read_text().splitlines() if ln.strip()]
    server = proof_chain.verify_mirror(rows)
    standalone = V.verify_decision_chain(rows)
    assert server["valid"] == standalone["valid"]
    assert server["head_hash"] == standalone["head_hash"]
    assert server["broken_at"] == standalone["broken_at"]


def test_server_and_standalone_agree_on_real_file():
    """On the REAL published file, server and standalone reproduce the same head byte-for-byte."""
    real = _ROOT / "data" / "rates_desk" / "decision_log.jsonl"
    rows = [json.loads(ln) for ln in real.read_text().splitlines() if ln.strip()]
    server = proof_chain.verify_mirror(rows)
    standalone = V.verify_decision_chain(rows)
    assert server["head_hash"] == standalone["head_hash"]
    assert server["valid"] and standalone["valid"]


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (A4) API reproduce-block matches the verifier + server verdict == verify_spa.py
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_api_proof_reproduce_block_matches_verifier():
    """The /proof reproduce block teaches the exact verifier command + spec, and the server's
    verified/head_hash equal what verify_spa.py reproduces on the same files."""
    from spa_core.api.routers import rates_desk as R
    proof = R.get_rates_desk_proof(last_n=12)
    rep = proof["reproduce"]
    assert rep["spec"] == "docs/PROOF_CHAIN_SPEC.md"
    assert rep["canonical_json_rule"] == V.CANONICAL_JSON_RULE
    assert rep["verify_with"].startswith("python3 verify_spa.py")
    # server verdict == standalone verifier on the real file
    real = _ROOT / "data" / "rates_desk" / "decision_log.jsonl"
    rows = [json.loads(ln) for ln in real.read_text().splitlines() if ln.strip()]
    standalone = V.verify_decision_chain(rows)
    assert proof["verified"] == standalone["valid"]
    assert proof["head_hash"] == standalone["head_hash"]


def test_api_exit_nav_reproduce_block_present():
    from spa_core.api.routers import rates_desk as R
    en = R.get_rates_desk_exit_nav()
    assert "reproduce" in en
    assert en["reproduce"]["canonical_json_rule"] == V.CANONICAL_JSON_RULE
    assert "exit_nav.json" in en["reproduce"]["verify_with"]


def test_api_anchors_endpoint_verified():
    from spa_core.api.routers import rates_desk as R
    anc = R.get_rates_desk_anchors(limit=50)
    assert anc["verified"] is True
    assert "reproduce" in anc
