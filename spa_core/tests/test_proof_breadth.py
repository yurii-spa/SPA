# LLM_FORBIDDEN
"""test_proof_breadth.py — WORKSTREAM 2 "Proof That Doesn't Rot" quality bar.

Extends the rates-desk verifiable hash-chain pattern to the OTHER desks (tournament ranking,
RWA-backstop NAV forward record, sleeve forward paper series) and pins, per surface AND for the
generalized one-command verifier:

  * METAMORPHIC: append N rows → the head changes DETERMINISTICALLY (re-build with the same data
    → byte-identical head; one more row → a different head); mutate ONE byte of a published value
    → the verifier reports the EXACT broken_at row.
  * FORGE (the FAIL#2 lesson): rewrite a published OUTPUT (a ranking net_return/sharpe, a NAV
    number, a sleeve equity) WITHOUT recomputing the hash → CAUGHT by the output-covering chain,
    never silently passed.
  * CLEAN-ROOM (the WORKSTREAM-A bar): the standalone verify_spa.py — loaded BY FILE PATH with NO
    spa_core in its namespace — auto-discovers + verifies ALL surfaces with one exit code.

GUARDRAIL: every producer run here writes ONLY into a pytest tmp_path sandbox — never live data/.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from spa_core.tournament import tournament_proof_chain as TPC
from spa_core.strategy_lab.rwa_backstop import nav_proof as NAV
from spa_core.strategy_lab.rates_desk import sleeve_proof as SLV

_ROOT = Path(__file__).resolve().parents[2]
_VERIFY = _ROOT / "scripts" / "verify_spa.py"


# ── shared helpers ───────────────────────────────────────────────────────────────────────────────
def _load_verifier():
    """Import scripts/verify_spa.py by path with a private module name — proves NO spa_core coupling."""
    spec = importlib.util.spec_from_file_location("_verify_spa_breadth", _VERIFY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


V = _load_verifier()


def _read_jsonl(path: Path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _ranking_doc(n: int, gen_at: str):
    """A synthetic tournament ranking doc (strategy_tournament.json shape) with n strategies."""
    return {
        "generated_at": gen_at,
        "ranked_strategies": [
            {"rank": i + 1, "strategy_id": f"S{i:02d}-X", "strategy_key": f"s{i}_x",
             "name": f"Strat{i}", "sharpe": round(10.0 - i * 0.1, 4),
             "sharpe_display": round(10.0 - i * 0.1, 4),
             "net_annual_return_pct": round(8.0 - i * 0.05, 4),
             "max_dd_pct": 0.01 * (i + 1), "is_shadow_active": i < 5}
            for i in range(n)
        ],
    }


def _nav_curve(n: int):
    return {"id": "rwa_backstop_nav_curve", "series": [
        {"date": f"2026-06-{20 + i:02d}", "ts": f"2026-06-{20 + i:02d}T23:00:00+00:00",
         "tvl_weighted_nav": round(1.0 + i * 0.001, 8), "liq_nav_gap_pct": 100.0 - i,
         "n_assets": 10 + i, "onchain_4626_count": i, "off_chain_estimate_count": 10}
        for i in range(n)]}


def _sleeve_series(n: int, sleeve_id="rates_desk_fixed_carry"):
    return {"id": sleeve_id, "series": [
        {"date": f"2026-06-{20 + i:02d}", "ts": f"2026-06-{20 + i:02d}T23:00:00+00:00",
         "equity_usd": round(100000.0 + i * 1.5, 6), "net_apy_pct": round(i * 0.001, 6),
         "open_books": i % 3, "closed_books": 0, "approvals": i, "refusals": 3}
        for i in range(n)]}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (E) TOURNAMENT ranking chain
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_tournament_builds_valid_output_covering_chain(tmp_path):
    rpath = tmp_path / "strategy_tournament.json"
    rpath.write_text(json.dumps(_ranking_doc(5, "2026-06-28T00:00:00+00:00")))
    out = tmp_path / "tournament" / "decision_log.jsonl"
    rep = TPC.append_ranking(rpath, out)
    assert rep["valid"] and rep["rows"] == 5
    rows = _read_jsonl(out)
    # the OUTPUTS are present in each row's payload (FAIL#2: proof covers outputs, not just inputs).
    for r in rows:
        for k in ("rank", "strategy_id", "sharpe", "net_annual_return_pct"):
            assert k in r
    assert V.verify_tournament_chain(rows)["valid"]


def test_tournament_metamorphic_append_changes_head_deterministically(tmp_path):
    rpath = tmp_path / "strategy_tournament.json"
    out = tmp_path / "tournament" / "decision_log.jsonl"
    rpath.write_text(json.dumps(_ranking_doc(5, "2026-06-27T00:00:00+00:00")))
    rep1 = TPC.append_ranking(rpath, out)
    # re-build with the SAME data (same generated_at) → idempotent → byte-identical head.
    rep1b = TPC.append_ranking(rpath, out)
    assert rep1["head_hash"] == rep1b["head_hash"]
    assert rep1b["rows"] == 5
    # append a NEW day's ranking → MORE rows, a DIFFERENT (deterministic) head.
    rpath.write_text(json.dumps(_ranking_doc(5, "2026-06-28T00:00:00+00:00")))
    rep2 = TPC.append_ranking(rpath, out)
    assert rep2["rows"] == 10
    assert rep2["head_hash"] != rep1["head_hash"]
    # determinism: same two-day history rebuilt fresh → same head.
    out2 = tmp_path / "t2" / "decision_log.jsonl"
    rpath.write_text(json.dumps(_ranking_doc(5, "2026-06-27T00:00:00+00:00")))
    TPC.append_ranking(rpath, out2)
    rpath.write_text(json.dumps(_ranking_doc(5, "2026-06-28T00:00:00+00:00")))
    rep2b = TPC.append_ranking(rpath, out2)
    assert rep2b["head_hash"] == rep2["head_hash"]


def test_tournament_one_byte_mutation_exact_broken_at(tmp_path):
    rpath = tmp_path / "strategy_tournament.json"
    rpath.write_text(json.dumps(_ranking_doc(6, "2026-06-28T00:00:00+00:00")))
    out = tmp_path / "tournament" / "decision_log.jsonl"
    TPC.append_ranking(rpath, out)
    rows = _read_jsonl(out)
    assert V.verify_tournament_chain(rows)["valid"]
    # mutate ONE published byte (flip a hex char of row 3's entry_hash) → exact broken_at.
    rows[3]["entry_hash"] = ("0" if rows[3]["entry_hash"][0] != "0" else "1") + rows[3]["entry_hash"][1:]
    res = V.verify_tournament_chain(rows)
    assert res["valid"] is False and res["broken_at"] == 3


def test_tournament_FORGE_published_output_is_caught(tmp_path):
    """FAIL#2: forge a published net_return WITHOUT recomputing the hash → CAUGHT (output-covered)."""
    rpath = tmp_path / "strategy_tournament.json"
    rpath.write_text(json.dumps(_ranking_doc(5, "2026-06-28T00:00:00+00:00")))
    out = tmp_path / "tournament" / "decision_log.jsonl"
    TPC.append_ranking(rpath, out)
    rows = _read_jsonl(out)
    rows[0]["net_annual_return_pct"] = 999.9999       # forge the headline output
    res = V.verify_tournament_chain(rows)
    assert res["valid"] is False and res["broken_at"] == 0


def test_tournament_FORGE_reorder_is_caught(tmp_path):
    rpath = tmp_path / "strategy_tournament.json"
    rpath.write_text(json.dumps(_ranking_doc(5, "2026-06-28T00:00:00+00:00")))
    out = tmp_path / "tournament" / "decision_log.jsonl"
    TPC.append_ranking(rpath, out)
    rows = _read_jsonl(out)
    rows[0], rows[1] = rows[1], rows[0]               # reorder the ranking → breaks the chain
    res = V.verify_tournament_chain(rows)
    assert res["valid"] is False and res["broken_at"] == 0


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (F) RWA-backstop NAV forward-record proof
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_nav_proof_builds_valid_chained_proof(tmp_path):
    curve = tmp_path / "rwa_nav_curve.json"
    curve.write_text(json.dumps(_nav_curve(4)))
    out = tmp_path / "rwa_backstop" / "nav_proof.jsonl"
    rep = NAV.write_proof(curve, out)
    assert rep["valid"] and rep["rows"] == 4
    rows = _read_jsonl(out)
    # genesis + chained
    assert rows[0]["prev_hash"] == "0" * 64
    assert rows[1]["prev_hash"] == rows[0]["proof_hash"]
    assert V.verify_nav_proof(rows)["valid"]


def test_nav_proof_metamorphic_append_changes_head(tmp_path):
    out = tmp_path / "rwa_backstop" / "nav_proof.jsonl"
    c = tmp_path / "rwa_nav_curve.json"
    c.write_text(json.dumps(_nav_curve(3)))
    rep3 = NAV.write_proof(c, out)
    c.write_text(json.dumps(_nav_curve(3)))
    assert NAV.write_proof(c, out)["head_hash"] == rep3["head_hash"]  # determinism
    c.write_text(json.dumps(_nav_curve(4)))                            # +1 forward point
    rep4 = NAV.write_proof(c, out)
    assert rep4["rows"] == 4 and rep4["head_hash"] != rep3["head_hash"]


def test_nav_proof_one_byte_mutation_exact_broken_at(tmp_path):
    c = tmp_path / "rwa_nav_curve.json"
    c.write_text(json.dumps(_nav_curve(5)))
    out = tmp_path / "rwa_backstop" / "nav_proof.jsonl"
    NAV.write_proof(c, out)
    rows = _read_jsonl(out)
    rows[2]["proof_hash"] = ("0" if rows[2]["proof_hash"][0] != "0" else "1") + rows[2]["proof_hash"][1:]
    res = V.verify_nav_proof(rows)
    assert res["valid"] is False and res["broken_at"] == 2


def test_nav_proof_FORGE_published_nav_is_caught(tmp_path):
    """FAIL#2: forge the published tvl_weighted_nav → CAUGHT (the proof_hash covers the output)."""
    c = tmp_path / "rwa_nav_curve.json"
    c.write_text(json.dumps(_nav_curve(4)))
    out = tmp_path / "rwa_backstop" / "nav_proof.jsonl"
    NAV.write_proof(c, out)
    rows = _read_jsonl(out)
    rows[1]["tvl_weighted_nav"] = 1.5                 # forge the headline NAV
    res = V.verify_nav_proof(rows)
    assert res["valid"] is False and res["broken_at"] == 1


def test_nav_proof_FORGE_drop_row_is_caught(tmp_path):
    c = tmp_path / "rwa_nav_curve.json"
    c.write_text(json.dumps(_nav_curve(5)))
    out = tmp_path / "rwa_backstop" / "nav_proof.jsonl"
    NAV.write_proof(c, out)
    rows = _read_jsonl(out)
    del rows[2]                                       # drop a forward point → breaks the chain
    res = V.verify_nav_proof(rows)
    assert res["valid"] is False and res["broken_at"] == 2


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (G) SLEEVE forward-series proof
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_sleeve_builds_valid_output_covering_chain(tmp_path):
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "rates_desk_fixed_carry_series.json").write_text(json.dumps(_sleeve_series(4)))
    reps = SLV.write_all(paper)
    assert len(reps) == 1 and reps[0]["valid"] and reps[0]["rows"] == 4
    out = paper / "rates_desk_fixed_carry_series_proof.jsonl"
    rows = _read_jsonl(out)
    for r in rows:
        for k in ("equity_usd", "net_apy_pct", "open_books", "approvals", "refusals"):
            assert k in r
    assert V.verify_sleeve_chain(rows)["valid"]


def test_sleeve_discovers_multiple_series(tmp_path):
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "alpha_series.json").write_text(json.dumps(_sleeve_series(3, "alpha")))
    (paper / "beta_series.json").write_text(json.dumps(_sleeve_series(5, "beta")))
    reps = SLV.write_all(paper)
    ids = sorted(r["sleeve_id"] for r in reps)
    assert ids == ["alpha", "beta"]
    assert all(r["valid"] for r in reps)
    assert (paper / "alpha_series_proof.jsonl").exists()
    assert (paper / "beta_series_proof.jsonl").exists()


def test_sleeve_metamorphic_append_changes_head(tmp_path):
    paper = tmp_path / "paper"
    paper.mkdir()
    sp = paper / "rates_desk_fixed_carry_series.json"
    sp.write_text(json.dumps(_sleeve_series(4)))
    h4 = SLV.write_all(paper)[0]["head_hash"]
    sp.write_text(json.dumps(_sleeve_series(4)))
    assert SLV.write_all(paper)[0]["head_hash"] == h4     # determinism
    sp.write_text(json.dumps(_sleeve_series(5)))           # +1 forward day
    rep5 = SLV.write_all(paper)[0]
    assert rep5["rows"] == 5 and rep5["head_hash"] != h4


def test_sleeve_one_byte_mutation_exact_broken_at(tmp_path):
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "rates_desk_fixed_carry_series.json").write_text(json.dumps(_sleeve_series(6)))
    SLV.write_all(paper)
    rows = _read_jsonl(paper / "rates_desk_fixed_carry_series_proof.jsonl")
    rows[4]["entry_hash"] = ("0" if rows[4]["entry_hash"][0] != "0" else "1") + rows[4]["entry_hash"][1:]
    res = V.verify_sleeve_chain(rows)
    assert res["valid"] is False and res["broken_at"] == 4


def test_sleeve_FORGE_published_equity_is_caught(tmp_path):
    """FAIL#2: forge the published forward equity_usd → CAUGHT (the chain covers the output)."""
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "rates_desk_fixed_carry_series.json").write_text(json.dumps(_sleeve_series(5)))
    SLV.write_all(paper)
    out = paper / "rates_desk_fixed_carry_series_proof.jsonl"
    rows = _read_jsonl(out)
    rows[2]["equity_usd"] = 200000.0                  # forge the forward equity the ladder reads
    res = V.verify_sleeve_chain(rows)
    assert res["valid"] is False and res["broken_at"] == 2


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (2.4) GENERALIZED ONE-COMMAND VERIFIER — auto-discovers ALL surfaces, one exit code
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _build_full_sandbox(tmp_path: Path) -> Path:
    """A sandbox data/ dir with ALL THREE breadth surfaces materialised (no live data touched)."""
    data = tmp_path / "data"
    (data / "tournament").mkdir(parents=True)
    (data / "rwa_backstop").mkdir(parents=True)
    (data / "rates_desk" / "paper").mkdir(parents=True)
    # tournament
    rp = data / "strategy_tournament.json"
    rp.write_text(json.dumps(_ranking_doc(5, "2026-06-28T00:00:00+00:00")))
    TPC.append_ranking(rp, data / "tournament" / "decision_log.jsonl")
    # nav
    cp = data / "rwa_nav_curve.json"
    cp.write_text(json.dumps(_nav_curve(3)))
    NAV.write_proof(cp, data / "rwa_backstop" / "nav_proof.jsonl")
    # sleeves
    paper = data / "rates_desk" / "paper"
    (paper / "rates_desk_fixed_carry_series.json").write_text(json.dumps(_sleeve_series(4)))
    SLV.write_all(paper)
    return data


def test_generalized_verifier_autodiscovers_all_surfaces_exit0(tmp_path):
    data = _build_full_sandbox(tmp_path)
    report = V.run([str(data)])
    assert report["ok"] is True, report["errors"]
    # every breadth surface was discovered + verified.
    assert report["tournament"]["valid"] and report["tournament"]["length"] == 5
    assert report["nav_proof"]["valid"] and report["nav_proof"]["length"] == 3
    assert report["sleeves"]["valid"] and report["sleeves"]["n_sleeves"] == 1
    assert V.main([str(data)]) == 0       # one exit code, exit 0


def test_generalized_verifier_one_forged_surface_fails_whole_run(tmp_path):
    """A forge in ANY surface fails the combined run with exit 1 (one exit code)."""
    data = _build_full_sandbox(tmp_path)
    # forge a tournament output in place (the realistic `verify_spa.py data/` path).
    tlog = data / "tournament" / "decision_log.jsonl"
    rows = _read_jsonl(tlog)
    rows[0]["sharpe"] = 9999.0
    tlog.write_text("".join(json.dumps(r, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False) + "\n" for r in rows))
    report = V.run([str(data)])
    assert report["ok"] is False
    assert report["tournament"]["valid"] is False
    assert V.main([str(data)]) == 1


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# ANTI-ROT (F1): the refresh regenerates ALL breadth surfaces together with the producer bundle
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_refresh_regenerates_breadth_surfaces_together(tmp_path):
    """F1: the refresh's breadth step must regenerate the tournament / RWA-NAV / sleeve proof
    artifacts FROM their producers' latest data, so they never rot — and then the WHOLE data dir
    self-verifies. Runs in a SELF-CONTAINED minimal sandbox (GUARDRAIL: never reads or writes live
    data/ — no copytree race with the live agents)."""
    refresh = _load_script("refresh_published_proof.py")
    data = tmp_path / "data"
    (data / "rates_desk" / "paper").mkdir(parents=True)
    # seed ONLY the producer inputs the breadth step reads (no live data touched).
    (data / "strategy_tournament.json").write_text(
        json.dumps(_ranking_doc(5, "2026-06-28T00:00:00+00:00")))
    (data / "rwa_nav_curve.json").write_text(json.dumps(_nav_curve(3)))
    (data / "rates_desk" / "paper" / "rates_desk_fixed_carry_series.json").write_text(
        json.dumps(_sleeve_series(4)))

    summary: dict = {}
    refresh._refresh_breadth_surfaces(data, summary)
    assert not summary.get("errors"), summary.get("errors")
    # all three breadth artifacts now exist in the sandbox.
    assert (data / "tournament" / "decision_log.jsonl").exists()
    assert (data / "rwa_backstop" / "nav_proof.jsonl").exists()
    assert list((data / "rates_desk" / "paper").glob("*_series_proof.jsonl")), "no sleeve proof"
    # the breadth summary records each surface as valid.
    b = summary["breadth"]
    assert b["tournament"]["valid"] and b["tournament"]["rows"] == 5
    assert b["nav_proof"]["valid"] and b["nav_proof"]["rows"] == 3
    assert b["sleeves"] and b["sleeves"][0]["valid"] and b["sleeves"][0]["rows"] == 4
    # and the WHOLE data dir self-verifies via the generalized verifier (the never-rot guarantee).
    assert V.run([str(data)])["ok"] is True
    # GUARDRAIL: the breadth refresh was handed ONLY the sandbox dir, so live data/ is untouched by
    # construction (every read/write inside _refresh_breadth_surfaces is pinned under `data`).


def _load_script(filename: str):
    spec = importlib.util.spec_from_file_location(
        "_" + filename.replace(".", "_"), _ROOT / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generalized_verifier_is_zero_dependency():
    """The 'don't trust us' artifact must run with NO repo on sys.path — source imports stdlib only."""
    import ast
    src = _VERIFY.read_text(encoding="utf-8")
    assert "import spa_core" not in src and "from spa_core" not in src
    tree = ast.parse(src)
    # datetime: stdlib, used by the WS6 --check-fundability date math (kept in sync with the sibling
    # test_verify_spa_standalone.py allowlist — the zero-dependency contract is "stdlib only").
    stdlib_ok = {"argparse", "hashlib", "json", "sys", "pathlib", "typing", "__future__", "datetime",
                 "decimal"}  # decimal: stdlib, used by the Q2-2 --replay verdict re-derivation
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                assert n.name.split(".")[0] in stdlib_ok, f"non-stdlib import: {n.name}"
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] in stdlib_ok, f"non-stdlib: {node.module}"
