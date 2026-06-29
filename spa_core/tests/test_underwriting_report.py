# LLM_FORBIDDEN
"""test_underwriting_report.py — Lane C (Layer-3 moat) Week-1 quality bar.

The underwriting report is the productized artifact the desk SELLS: the MEASUREMENT + the PROOF,
hash-anchored and publicly verifiable. These tests pin its contract:

  C1.1 — schema: a thin report builds today; every section carries a proof_hash + chains.
  C1.2 — verify_spa.py surface (H): the standalone, zero-spa_core verifier re-derives the
         report's proof chain (clean machine, exit 0) and reports a precise broken_at on tamper.
  C1.3 — VERBATIM-PASSTHROUGH GUARD (the anti-happy-laundering core): the published
         survives_at_aum_usd equals Lane B's realized_at_size.json value byte-for-byte.
  C1.4 — owner-only flag SPA_UNDERWRITING_PUBLISH (default OFF): report written to data/ only.
  C1.5 — RED-TEAM: post-hoc edit of a published value; reorder/drop a section; claim a REFUSED
         market as underwritten capacity. Single-genesis + contiguous; refusal-consistency.

All hermetic: synthetic fixtures + tmp_path, never the live track.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from spa_core.strategy_lab.underwriting import report as R

_ROOT = Path(__file__).resolve().parents[2]
_VERIFY = _ROOT / "scripts" / "verify_spa.py"
_FIX = Path(__file__).resolve().parent / "fixtures" / "underwriting"


# ── load the standalone verifier by path (proves zero spa_core coupling for surface H) ─────────────
def _load_verifier():
    spec = importlib.util.spec_from_file_location("_verify_spa_under_test_uw", _VERIFY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


V = _load_verifier()


# ── a deterministic Lane-B fixture trio (the FROZEN DATA CONTRACT) written to a tmp dir ────────────
def _write_inputs(tmp: Path, *, realized=None, refusals=None, depth=None) -> dict:
    """Write a realized_at_size.json + depth_at_size.json + refusal_status.json triple into tmp and
    return their paths. Defaults: SURVIVES_AT $5M, one REFUSE market (ezeth)."""
    realized = realized if realized is not None else {
        "model": "rates_desk_realized_at_size", "verdict": "SURVIVES_AT",
        "survives_at_aum_usd": 5000000.0, "floor_plus_bps_at_5M": 42.0, "as_of": "2026-06-29",
        "data_source": "lane_b_realized", "markets": [
            {"symbol": "susds", "realized_above_floor_bps": 91.0, "survives": True},
            {"symbol": "ptUSDe", "realized_above_floor_bps": 38.0, "survives": True},
            {"symbol": "ezeth", "realized_above_floor_bps": -120.0, "survives": False},
        ]}
    refusals = refusals if refusals is not None else {
        "model": "rates_desk_refusal_engine", "underlyings": [
            {"symbol": "susds", "group": "stable", "verdict": "SAFE", "tail_score": 0.04, "reason": "ok"},
            {"symbol": "ptUSDe", "group": "PT", "verdict": "WATCH", "tail_score": 0.31, "reason": "watch"},
            {"symbol": "ezeth", "group": "LRT", "verdict": "REFUSE", "tail_score": 0.62, "reason": "tail"},
        ]}
    depth = depth if depth is not None else {
        "model": "rates_desk_depth_at_size", "markets": [
            {"symbol": "susds", "depth_usd": 18000000.0, "max_safe_size_usd": 9000000.0}]}
    rp = tmp / "realized_at_size.json"
    dp = tmp / "depth_at_size.json"
    fp = tmp / "refusal_status.json"
    rp.write_text(json.dumps(realized), encoding="utf-8")
    dp.write_text(json.dumps(depth), encoding="utf-8")
    fp.write_text(json.dumps(refusals), encoding="utf-8")
    return {"realized": rp, "depth": dp, "refusal": fp}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# C1.1 — schema: thin report builds; every section carries a proof_hash + chains
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_report_builds_thin_today(tmp_path):
    paths = _write_inputs(tmp_path)
    rep, err = R.build_report(realized_path=paths["realized"], depth_path=paths["depth"],
                              refusal_path=paths["refusal"], generated_at="2026-06-29T00:00:00+00:00")
    assert err is None and rep is not None
    assert rep["schema_version"] == R.REPORT_SCHEMA_VERSION
    ids = [s["section_id"] for s in rep["sections"]]
    assert ids == ["meta", "refusals", "depth", "realized", "capacity"]
    # every section carries its own proof_hash + chain envelope
    for s in rep["sections"]:
        assert isinstance(s["proof_hash"], str) and len(s["proof_hash"]) == 64
        assert "seq" in s and "prev_hash" in s and "entry_hash" in s


def test_report_chain_is_single_genesis_contiguous(tmp_path):
    paths = _write_inputs(tmp_path)
    rep, _ = R.build_report(realized_path=paths["realized"], depth_path=paths["depth"],
                            refusal_path=paths["refusal"], generated_at="2026-06-29T00:00:00+00:00")
    res = R.verify_report_chain(rep["sections"])
    assert res["valid"] and res["broken_at"] is None
    assert rep["sections"][0]["prev_hash"] == "0" * 64           # single genesis
    assert [s["seq"] for s in rep["sections"]] == list(range(len(rep["sections"])))  # contiguous
    assert rep["head_hash"] == res["head_hash"]


def test_report_is_deterministic(tmp_path):
    paths = _write_inputs(tmp_path)
    a, _ = R.build_report(realized_path=paths["realized"], depth_path=paths["depth"],
                          refusal_path=paths["refusal"], generated_at="2026-06-29T00:00:00+00:00")
    b, _ = R.build_report(realized_path=paths["realized"], depth_path=paths["depth"],
                          refusal_path=paths["refusal"], generated_at="2026-06-29T00:00:00+00:00")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_per_section_proof_hash_recomputes(tmp_path):
    """A reviewer recomputes each section's proof_hash from the section body alone."""
    paths = _write_inputs(tmp_path)
    rep, _ = R.build_report(realized_path=paths["realized"], depth_path=paths["depth"],
                            refusal_path=paths["refusal"], generated_at="2026-06-29T00:00:00+00:00")
    for s in rep["sections"]:
        body = {k: v for k, v in s.items() if k not in ("seq", "prev_hash", "entry_hash")}
        assert R.section_proof_hash(body) == s["proof_hash"]


def test_fail_closed_on_missing_realized(tmp_path):
    rep, err = R.build_report(realized_path=tmp_path / "nope.json")
    assert rep is None and err is not None and "realized_at_size" in err


def test_fail_closed_on_unknown_verdict(tmp_path):
    paths = _write_inputs(tmp_path, realized={"verdict": "TOTALLY_FINE_TRUST_ME",
                                              "survives_at_aum_usd": 1e9})
    rep, err = R.build_report(realized_path=paths["realized"], refusal_path=paths["refusal"])
    assert rep is None and "vocabulary" in err  # refuse to publish an out-of-vocab verdict


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# C1.3 — VERBATIM-PASSTHROUGH GUARD (anti-happy-laundering): C MUST NOT recompute B's number
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_survives_at_aum_usd_is_byte_for_byte_lane_b(tmp_path):
    """The published survives_at_aum_usd equals Lane B's raw realized_at_size.json value, byte-for-byte.
    This is THE guard test the spec mandates — a recompute path would diverge and fail here loudly."""
    # an intentionally NON-round Lane B value: a recompute would almost certainly not reproduce it.
    raw = {"verdict": "DOES_NOT_SURVIVE_PAST", "survives_at_aum_usd": 3271884.5519999999,
           "floor_plus_bps_at_5M": -17.25, "markets": []}
    paths = _write_inputs(tmp_path, realized=raw)
    rep, _ = R.build_report(realized_path=paths["realized"], refusal_path=paths["refusal"])
    realized_sec = next(s for s in rep["sections"] if s["section_id"] == "realized")
    # read the RAW bytes Lane B published and compare the parsed value identity-style.
    raw_doc = json.loads(paths["realized"].read_text(encoding="utf-8"))
    assert realized_sec["survives_at_aum_usd"] == raw_doc["survives_at_aum_usd"]
    assert realized_sec["floor_plus_bps_at_5M"] == raw_doc["floor_plus_bps_at_5M"]
    assert realized_sec["verdict"] == raw_doc["verdict"]
    # byte-for-byte: the canonical JSON of the value reproduces the raw token.
    assert (json.dumps(realized_sec["survives_at_aum_usd"])
            == json.dumps(raw_doc["survives_at_aum_usd"]))


def test_passthrough_carries_a_does_not_survive_verdict_unchanged(tmp_path):
    """C does not 'upgrade' a bad verdict: a DOES_NOT_SURVIVE_PAST flows through verbatim."""
    paths = _write_inputs(tmp_path, realized={"verdict": "DOES_NOT_SURVIVE_PAST",
                                              "survives_at_aum_usd": 250000.0,
                                              "floor_plus_bps_at_5M": -40.0, "markets": []})
    rep, _ = R.build_report(realized_path=paths["realized"], refusal_path=paths["refusal"])
    realized_sec = next(s for s in rep["sections"] if s["section_id"] == "realized")
    assert realized_sec["verdict"] == "DOES_NOT_SURVIVE_PAST"
    assert realized_sec["survives_at_aum_usd"] == 250000.0


def test_no_recompute_arithmetic_on_realized_in_source():
    """Structural anti-laundering guard: the realized read path is a pure passthrough — the source of
    read_realized_verbatim performs no arithmetic on B's load-bearing numbers (docstrings/comments
    excluded; we inspect the CODE tokens only via the AST)."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(R.read_realized_verbatim))
    # any binary arithmetic op in the function body would be a recompute path.
    forbidden = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp):
            assert not isinstance(node.op, forbidden), (
                "verbatim reader contains an arithmetic op — possible happy-laundering recompute path")
        # no round()/sum()/max()/min() calls that could transform B's value either.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("round", "sum", "max", "min"), (
                f"verbatim reader calls {node.func.id}() — possible recompute path")


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# C1.4 — owner-only flag SPA_UNDERWRITING_PUBLISH (default OFF)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_publish_flag_default_off(monkeypatch, tmp_path):
    monkeypatch.delenv(R.PUBLISH_FLAG_ENV, raising=False)
    assert R.is_publish_enabled() is False
    paths = _write_inputs(tmp_path)
    rep, _ = R.build_report(realized_path=paths["realized"], refusal_path=paths["refusal"])
    assert rep["published"] is False
    meta = next(s for s in rep["sections"] if s["section_id"] == "meta")
    assert meta["published"] is False and meta["publish_gate"] == "owner"


@pytest.mark.parametrize("val,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("", False), ("maybe", False), ("2", False),
])
def test_publish_flag_parsing(monkeypatch, val, expected):
    monkeypatch.setenv(R.PUBLISH_FLAG_ENV, val)
    assert R.is_publish_enabled() is expected


def test_report_written_to_data_even_when_flag_off(monkeypatch, tmp_path):
    """Flag OFF → the report is STILL written to data/ (the proof chain must grow + be verifiable),
    just marked published:false (no public surfacing)."""
    monkeypatch.delenv(R.PUBLISH_FLAG_ENV, raising=False)
    paths = _write_inputs(tmp_path)
    out = tmp_path / "underwriting_report.json"
    proof = tmp_path / "report_proof.jsonl"
    res = R.write_report(realized_path=paths["realized"], depth_path=paths["depth"],
                         refusal_path=paths["refusal"], out_path=out, proof_path=proof,
                         generated_at="2026-06-29T00:00:00+00:00")
    assert res["ok"] and res["published"] is False
    assert out.exists() and proof.exists()                 # written to data/ regardless
    assert json.loads(out.read_text())["published"] is False


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# C1.5 — RED-TEAM (adversarial) + the refusal-consistency / single-genesis properties
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_refused_market_never_appears_as_capacity(tmp_path):
    """A market the refusal layer REFUSED (ezeth) must be EXCLUDED from the capacity section."""
    paths = _write_inputs(tmp_path)
    rep, _ = R.build_report(realized_path=paths["realized"], refusal_path=paths["refusal"])
    cap = next(s for s in rep["sections"] if s["section_id"] == "capacity")
    cap_syms = {m.get("symbol") for m in cap["capacity_markets"]}
    assert "ezeth" not in cap_syms                          # refused → excluded
    assert "ezeth" in cap["excluded_refused_markets"]       # and audited as excluded
    assert {"susds", "ptUSDe"} <= cap_syms                  # the safe markets remain


def test_redteam_posthoc_edit_breaks_chain(tmp_path):
    """Post-hoc edit of a published section value → the verifier reports a precise broken_at."""
    paths = _write_inputs(tmp_path)
    rep, _ = R.build_report(realized_path=paths["realized"], refusal_path=paths["refusal"],
                            generated_at="2026-06-29T00:00:00+00:00")
    secs = [dict(s) for s in rep["sections"]]
    # forge survives_at_aum_usd in the realized section (the happy-laundering attack).
    realized_idx = next(i for i, s in enumerate(secs) if s["section_id"] == "realized")
    secs[realized_idx]["survives_at_aum_usd"] = 999_000_000.0
    res = R.verify_report_chain(secs)
    assert res["valid"] is False and res["broken_at"] == realized_idx


def test_redteam_reorder_sections_breaks_chain(tmp_path):
    """Reordering report sections breaks the single-genesis prev-linkage → broken_at."""
    paths = _write_inputs(tmp_path)
    rep, _ = R.build_report(realized_path=paths["realized"], refusal_path=paths["refusal"])
    secs = list(rep["sections"])
    secs[1], secs[2] = secs[2], secs[1]                     # swap refusals <-> depth
    res = R.verify_report_chain(secs)
    assert res["valid"] is False


def test_redteam_drop_section_breaks_chain(tmp_path):
    paths = _write_inputs(tmp_path)
    rep, _ = R.build_report(realized_path=paths["realized"], refusal_path=paths["refusal"])
    secs = [s for s in rep["sections"] if s["section_id"] != "depth"]  # drop a middle section
    res = R.verify_report_chain(secs)
    assert res["valid"] is False


def test_redteam_smuggle_refused_market_caught_by_standalone_verifier(tmp_path):
    """The hardest attack: smuggle a REFUSED market into capacity AND fully re-seal the chain (all
    per-section + chain hashes valid). The standalone verifier (surface H) STILL catches it via the
    cross-section refusal-consistency property — a re-sealed chain cannot relabel a REFUSE verdict."""
    paths = _write_inputs(tmp_path)
    rep, _ = R.build_report(realized_path=paths["realized"], refusal_path=paths["refusal"])
    secs = [dict(s) for s in rep["sections"]]
    cap_idx = next(i for i, s in enumerate(secs) if s["section_id"] == "capacity")
    secs[cap_idx]["capacity_markets"] = list(secs[cap_idx]["capacity_markets"]) + [
        {"symbol": "ezeth", "realized_above_floor_bps": 50.0}]   # smuggle the refused market
    secs[cap_idx]["n_capacity_markets"] = len(secs[cap_idx]["capacity_markets"])
    # FULLY re-seal: recompute every per-section proof_hash AND the prev-linked entry_hash chain.
    resealed = _reseal_chain(secs)
    # write to a tmp report_proof.jsonl and run the standalone verifier over it.
    proof = tmp_path / "report_proof.jsonl"
    proof.write_text("\n".join(json.dumps(s, sort_keys=True, separators=(",", ":"))
                               for s in resealed) + "\n", encoding="utf-8")
    out = V.run([str(proof)])
    assert out["ok"] is False
    assert out["underwriting"]["refusal_consistent"] is False
    assert "ezeth" in out["underwriting"]["smuggled_markets"]


def _reseal_chain(secs):
    """Recompute every per-section proof_hash AND the chain entry_hash so a tampered file passes all
    hash checks (the attacker controls the file). Mirrors report.section_proof_hash/chain_entry_hash
    so the test re-seal is byte-identical to the producer."""
    EVENT = R.UNDERWRITING_EVENT_TYPE
    ENV = ("seq", "prev_hash", "entry_hash")

    def can(o):
        return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    out = []
    prev = "0" * 64
    for s in secs:
        seq = s["seq"]
        sid = s["section_id"]
        body = {k: v for k, v in s.items() if k not in ENV + ("proof_hash",)}
        body["proof_hash"] = hashlib.sha256(can(body).encode()).hexdigest()
        eh = hashlib.sha256(can({"seq": seq, "section_id": sid, "event_type": EVENT,
                                 "payload": body, "prev_hash": prev}).encode()).hexdigest()
        out.append({"seq": seq, "prev_hash": prev, "entry_hash": eh, **body})
        prev = eh
    return out


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# C1.2 — verify_spa.py surface (H): standalone, zero-spa_core re-derivation
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_verify_spa_surface_h_clean(tmp_path):
    """The standalone verifier re-derives the report's section chain and returns ok=True (exit 0)."""
    paths = _write_inputs(tmp_path)
    proof = tmp_path / "report_proof.jsonl"
    R.write_report(realized_path=paths["realized"], depth_path=paths["depth"],
                   refusal_path=paths["refusal"], out_path=tmp_path / "underwriting_report.json",
                   proof_path=proof, generated_at="2026-06-29T00:00:00+00:00")
    out = V.run([str(proof)])
    assert out["ok"] is True
    assert out["underwriting"]["valid"] is True
    assert out["underwriting"]["refusal_consistent"] is True


def test_verify_spa_surface_h_tamper_reports_broken_at(tmp_path):
    """Surface H tamper (forge a value WITHOUT re-sealing) → precise broken_at, exit non-zero."""
    paths = _write_inputs(tmp_path)
    proof = tmp_path / "report_proof.jsonl"
    R.write_report(realized_path=paths["realized"], depth_path=paths["depth"],
                   refusal_path=paths["refusal"], out_path=tmp_path / "underwriting_report.json",
                   proof_path=proof, generated_at="2026-06-29T00:00:00+00:00")
    rows = [json.loads(ln) for ln in proof.read_text().splitlines() if ln.strip()]
    for r in rows:
        if r.get("section_id") == "realized":
            r["survives_at_aum_usd"] = 999_000_000.0       # forge, do NOT re-seal
    proof.write_text("\n".join(json.dumps(r, sort_keys=True, separators=(",", ":"))
                               for r in rows) + "\n", encoding="utf-8")
    out = V.run([str(proof)])
    assert out["ok"] is False
    assert out["underwriting"]["broken_at"] == 3            # the realized section index


def test_verify_spa_expect_surface_h_absent_fails_closed(tmp_path):
    """--expect-surfaces H over a dir with no report_proof.jsonl fails CLOSED (no silent pass)."""
    # supply an unrelated (valid) surface so the run is non-empty, then require H (absent).
    other = tmp_path / "equity_track.jsonl"
    other.write_text("", encoding="utf-8")                 # empty equity track = present surface D
    out = V.run([str(other)], expect_surfaces=["H"])
    assert out["ok"] is False
    assert any("required surface [H]" in e for e in out["errors"])
