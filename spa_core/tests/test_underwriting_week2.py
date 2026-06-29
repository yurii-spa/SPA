# LLM_FORBIDDEN
"""test_underwriting_week2.py — Lane C (Layer-3 moat) WEEK-2 quality bar (C2.1-C2.5).

  C2.1 — per-market underwriting verdict rows: EVERY market appears with its refusal verdict +
         depth-at-size + why-refused/why-underwritten. A REFUSED market is never underwritten.
  C2.3 — flag-gated API: /api/underwriting/report + /proof + /full-chain are 404 when
         SPA_UNDERWRITING_PUBLISH is OFF; served VERBATIM when ON; the proof verdict matches the
         standalone verifier.
  C2.4 — honest fundability framing: the report embeds the thesis band (floor+50-150 bps, NOT
         +1000) AND Lane B's realized verdict VERBATIM (incl. INSUFFICIENT_DATA / a null).
  C2.5 — RED-TEAM: a depth-flagged-insufficient market cannot carry a fabricated bound; the report
         headline cannot over-claim vs Lane B's realized verdict; flagged markets show NULL not a #.

Hermetic: synthetic fixtures + tmp_path; the API tests redirect server._DATA_DIR. Never the live track.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from spa_core.strategy_lab.underwriting import report as R

_FIX = Path(__file__).resolve().parent / "fixtures" / "underwriting"


# ── a deterministic Lane-B fixture trio written to tmp ────────────────────────────────────────────
def _write_inputs(tmp: Path, *, realized=None, refusals=None, depth=None) -> dict:
    realized = realized if realized is not None else {
        "model": "rates_desk_realized_at_size", "verdict": "SURVIVES_AT",
        "survives_at_aum_usd": 5000000.0, "floor_plus_bps_at_5M": 128.81, "as_of": "2026-06-29",
        "markets": [
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
            {"symbol": "susds", "depth_usd": 18000000.0, "max_safe_size_usd": 9000000.0,
             "flagged": False},
            {"symbol": "ptUSDe", "depth_usd": 6000000.0, "max_safe_size_usd": 3000000.0,
             "flagged": False},
            {"symbol": "ezeth", "exit_liquidity_usd": 2000.0, "flagged": True,
             "flag_reason": "insufficient_contemporaneous_depth",
             "tickets": [{"ticket_usd": 1000000, "absorbable_usd": None}]},
        ]}
    rp, dp, fp = tmp / "realized.json", tmp / "depth.json", tmp / "refusal.json"
    rp.write_text(json.dumps(realized), encoding="utf-8")
    dp.write_text(json.dumps(depth), encoding="utf-8")
    fp.write_text(json.dumps(refusals), encoding="utf-8")
    return {"realized": rp, "depth": dp, "refusal": fp}


def _build(tmp, **kw):
    paths = _write_inputs(tmp, **kw)
    rep, err = R.build_report(realized_path=paths["realized"], depth_path=paths["depth"],
                              refusal_path=paths["refusal"], generated_at="2026-06-29T00:00:00+00:00")
    assert err is None and rep is not None
    return rep


def _section(rep, sid):
    return next(s for s in rep["sections"] if s["section_id"] == sid)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# C2.1 — per-market underwriting verdict rows
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_per_market_section_present_and_chains(tmp_path):
    rep = _build(tmp_path)
    ids = [s["section_id"] for s in rep["sections"]]
    assert ids == ["meta", "refusals", "depth", "realized", "capacity", "per_market", "fundability"]
    assert R.verify_report_chain(rep["sections"])["valid"]


def test_every_market_appears_with_verdict_depth_and_why(tmp_path):
    """The product: EVERY market appears once, with refusal verdict + depth + why string."""
    pm = _section(_build(tmp_path), "per_market")
    by = {r["symbol"]: r for r in pm["rows"]}
    assert set(by) == {"susds", "ptUSDe", "ezeth"}
    for r in pm["rows"]:
        assert r["refusal_verdict"] is not None          # verdict present
        assert "depth" in r and r["depth"] is not None    # depth-at-size present (or available:false)
        assert isinstance(r["why"], str) and r["why"]     # a why-refused/why-underwritten string


def test_refused_market_is_never_underwritten_in_per_market(tmp_path):
    """A REFUSED market (ezeth) is status=REFUSED, underwritten=False, even though realized has a row."""
    pm = _section(_build(tmp_path), "per_market")
    ez = next(r for r in pm["rows"] if r["symbol"] == "ezeth")
    assert ez["status"] == "REFUSED"
    assert ez["underwritten"] is False
    assert "REFUSED" in ez["why"]
    su = next(r for r in pm["rows"] if r["symbol"] == "susds")
    assert su["status"] == "UNDERWRITTEN" and su["underwritten"] is True
    pt = next(r for r in pm["rows"] if r["symbol"] == "ptUSDe")
    assert pt["status"] == "WATCH" and pt["underwritten"] is False


def test_per_market_fields_are_verbatim_no_recompute(tmp_path):
    """Every per-market number is COPIED VERBATIM from the inputs — no recompute."""
    paths = _write_inputs(tmp_path)
    rep, _ = R.build_report(realized_path=paths["realized"], depth_path=paths["depth"],
                            refusal_path=paths["refusal"])
    raw_ref = json.loads(paths["refusal"].read_text())["underlyings"]
    raw_dep = {m["symbol"]: m for m in json.loads(paths["depth"].read_text())["markets"]}
    raw_rea = {m["symbol"]: m for m in json.loads(paths["realized"].read_text())["markets"]}
    by = {r["symbol"]: r for r in _section(rep, "per_market")["rows"]}
    for ref in raw_ref:
        row = by[ref["symbol"]]
        assert row["tail_score"] == ref["tail_score"]                     # verbatim
        assert row["refusal_reason"] == ref["reason"]
        assert row["depth"] == raw_dep[ref["symbol"]]                     # depth row byte-for-byte
        assert row["realized"] == raw_rea[ref["symbol"]]                  # realized row byte-for-byte


def test_market_refused_before_any_realized_track_still_appears(tmp_path):
    """A market REFUSED before it ever produced a realized track STILL appears (the refusal IS the
    product) — universe is realized ∪ refusals ∪ depth."""
    rep = _build(tmp_path, realized={"verdict": "INSUFFICIENT_DATA", "survives_at_aum_usd": None,
                                     "floor_plus_bps_at_5M": None, "markets": []})  # NO realized rows
    pm = _section(rep, "per_market")
    by = {r["symbol"]: r for r in pm["rows"]}
    assert "ezeth" in by and by["ezeth"]["status"] == "REFUSED"           # refused w/o realized track
    assert by["susds"]["status"] == "NO_REALIZED_TRACK"                   # safe but no realized row yet
    assert by["susds"]["realized"] is None


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# C2.4 — honest fundability framing
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_fundability_band_is_50_to_150_bps_not_1000(tmp_path):
    fu = _section(_build(tmp_path), "fundability")
    assert fu["thesis_floor_plus_bps_band"] == [50.0, 150.0]
    assert fu["not_claimed_floor_plus_bps"] == 1000.0
    assert "1000" in fu["thesis"] and "NOT" in fu["thesis"]
    assert fu["target_aum_usd"] == 5_000_000.0


def test_fundability_carries_lane_b_verdict_verbatim(tmp_path):
    """The funder reads Lane B's realized verdict VERBATIM — incl. a thin INSUFFICIENT_DATA + null."""
    rep = _build(tmp_path, realized={"verdict": "INSUFFICIENT_DATA", "survives_at_aum_usd": None,
                                     "floor_plus_bps_at_5M": 128.8097, "markets": []})
    fu = _section(rep, "fundability")
    assert fu["lane_b_verdict"] == "INSUFFICIENT_DATA"        # not laundered to a green verdict
    assert fu["lane_b_survives_at_aum_usd"] is None           # null flows through
    assert fu["lane_b_floor_plus_bps_at_5M"] == 128.8097      # verbatim
    assert fu["verdict_passthrough"] == "VERBATIM_FROM_LANE_B"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# C2.5 — RED-TEAM (adversarial)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_redteam_depth_flagged_market_shows_null_not_fabricated_bound(tmp_path):
    """A market whose depth is FLAGGED insufficient must show its NULL/flagged depth VERBATIM — the
    report can NOT invent an absorbable bound for it."""
    pm = _section(_build(tmp_path), "per_market")
    ez = next(r for r in pm["rows"] if r["symbol"] == "ezeth")
    assert ez["depth"]["flagged"] is True
    assert ez["depth"]["flag_reason"] == "insufficient_contemporaneous_depth"
    # the flagged ticket's absorbable bound is NULL — never a fabricated number.
    assert ez["depth"]["tickets"][0]["absorbable_usd"] is None
    # PROPERTY: no flagged depth row carries a non-null absorbable/max-safe number it didn't have.
    for r in pm["rows"]:
        d = r["depth"]
        if isinstance(d, dict) and d.get("flagged"):
            for t in (d.get("tickets") or []):
                assert t.get("absorbable_usd") is None


def test_redteam_report_apy_cannot_overclaim_vs_lane_b(tmp_path):
    """Property: the report's headline fundability number ≤ Lane B's realized verdict ∀ sections.
    Concretely — the report NEVER publishes a survives_at / floor_plus_bps_at_5M that exceeds the raw
    Lane B value. We feed a NON-ROUND B value; a recompute would diverge upward → caught."""
    raw = {"verdict": "DOES_NOT_SURVIVE_PAST", "survives_at_aum_usd": 271884.55,
           "floor_plus_bps_at_5M": -17.25, "markets": []}
    rep = _build(tmp_path, realized=raw)
    realized_sec = _section(rep, "realized")
    fu = _section(rep, "fundability")
    # the report's published realized numbers equal B's (never a happier, larger number).
    assert realized_sec["survives_at_aum_usd"] == raw["survives_at_aum_usd"]
    assert realized_sec["floor_plus_bps_at_5M"] == raw["floor_plus_bps_at_5M"]
    assert fu["lane_b_floor_plus_bps_at_5M"] == raw["floor_plus_bps_at_5M"] == -17.25  # below floor!
    assert fu["lane_b_verdict"] == "DOES_NOT_SURVIVE_PAST"   # a bad verdict is NOT upgraded
    # the thesis band is a STATED THESIS, never presented as the realized number.
    assert fu["lane_b_floor_plus_bps_at_5M"] < fu["thesis_floor_plus_bps_band"][0]


def test_redteam_smuggle_refused_into_per_market_underwritten_is_pinned(tmp_path):
    """Even if an attacker controls the refusal/realized inputs to try to mark a REFUSED market as
    underwritten, the per_market builder pins status=REFUSED / underwritten=False (fail-CLOSED)."""
    # ezeth is REFUSE in refusals AND has a survives:true realized row — the trap.
    rep = _build(tmp_path, realized={
        "verdict": "SURVIVES_AT", "survives_at_aum_usd": 5e6, "floor_plus_bps_at_5M": 100.0,
        "markets": [{"symbol": "ezeth", "realized_above_floor_bps": 999.0, "survives": True}]})
    ez = next(r for r in _section(rep, "per_market")["rows"] if r["symbol"] == "ezeth")
    assert ez["status"] == "REFUSED" and ez["underwritten"] is False
    # ezeth is ALSO excluded from the capacity section (refusal-consistency).
    cap = _section(rep, "capacity")
    assert "ezeth" not in {m.get("symbol") for m in cap["capacity_markets"]}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# C2.3 — flag-gated API (server._DATA_DIR redirect; flip the publish flag)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _client_with_report(tmp_path, monkeypatch, *, flag_on: bool, write_report: bool = True):
    """Build a TestClient with _DATA_DIR → tmp_path, the report written under data/underwriting/, and
    the publish flag set on/off."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    if write_report:
        paths = _write_inputs(tmp_path, refusals=None)
        outdir = tmp_path / "underwriting"
        R.write_report(realized_path=paths["realized"], depth_path=paths["depth"],
                       refusal_path=paths["refusal"], out_path=outdir / "underwriting_report.json",
                       proof_path=outdir / "report_proof.jsonl",
                       generated_at="2026-06-29T00:00:00+00:00")

    if flag_on:
        monkeypatch.setenv(R.PUBLISH_FLAG_ENV, "1")
    else:
        monkeypatch.delenv(R.PUBLISH_FLAG_ENV, raising=False)

    from spa_core.api import server as srv
    monkeypatch.setattr(srv, "_DATA_DIR", tmp_path)
    return TestClient(srv.app, raise_server_exceptions=False)


def test_api_report_is_404_when_flag_off(tmp_path, monkeypatch):
    client = _client_with_report(tmp_path, monkeypatch, flag_on=False)
    r = client.get("/api/underwriting/report")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "underwriting_surface_disabled"
    assert client.get("/api/underwriting/proof").status_code == 404
    assert client.get("/api/underwriting/full-chain").status_code == 404


def test_api_report_served_verbatim_when_flag_on(tmp_path, monkeypatch):
    client = _client_with_report(tmp_path, monkeypatch, flag_on=True)
    r = client.get("/api/underwriting/report")
    assert r.status_code == 200
    body = r.json()
    # the per_market + fundability sections reach the wire VERBATIM.
    ids = [s["section_id"] for s in body["sections"]]
    assert "per_market" in ids and "fundability" in ids
    # served VERBATIM: the on-disk file equals the wire payload minus the appended reproduce block.
    on_disk = json.loads((tmp_path / "underwriting" / "underwriting_report.json").read_text())
    assert body["head_hash"] == on_disk["head_hash"]
    assert body["sections"] == on_disk["sections"]


def test_api_proof_verdict_matches_chain(tmp_path, monkeypatch):
    client = _client_with_report(tmp_path, monkeypatch, flag_on=True)
    r = client.get("/api/underwriting/proof")
    assert r.status_code == 200
    body = r.json()
    assert body["verified"] is True
    assert body["refusal_consistent"] is True
    assert body["broken_at"] is None
    assert body["smuggled_markets"] == []


def test_api_proof_detects_tamper(tmp_path, monkeypatch):
    """Forge a value in the on-disk proof WITHOUT re-sealing → the API reports verified:false + broken_at."""
    client = _client_with_report(tmp_path, monkeypatch, flag_on=True)
    proof = tmp_path / "underwriting" / "report_proof.jsonl"
    rows = [json.loads(ln) for ln in proof.read_text().splitlines() if ln.strip()]
    for row in rows:
        if row.get("section_id") == "realized":
            row["survives_at_aum_usd"] = 999_000_000.0       # forge, do NOT re-seal
    proof.write_text("\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows)
                     + "\n", encoding="utf-8")
    body = client.get("/api/underwriting/proof").json()
    assert body["verified"] is False
    assert body["broken_at"] == 3                            # the realized section index


def test_api_report_graceful_when_file_absent_but_flag_on(tmp_path, monkeypatch):
    """Flag ON but no report written → honest available:false, NEVER a 500."""
    client = _client_with_report(tmp_path, monkeypatch, flag_on=True, write_report=False)
    r = client.get("/api/underwriting/report")
    assert r.status_code == 200
    assert r.json()["available"] is False
    # proof over an absent chain is vacuously valid (length 0), not a 500.
    pr = client.get("/api/underwriting/proof")
    assert pr.status_code == 200 and pr.json()["chain_length"] == 0


def test_api_full_chain_verbatim_when_flag_on(tmp_path, monkeypatch):
    client = _client_with_report(tmp_path, monkeypatch, flag_on=True)
    r = client.get("/api/underwriting/full-chain")
    assert r.status_code == 200
    on_disk = (tmp_path / "underwriting" / "report_proof.jsonl").read_text()
    assert r.text == on_disk                                 # byte-for-byte


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# C2.2 — public-verifiability dry run (third-party simulation, no spa_core on path)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _load_dryrun():
    import importlib.util
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "_uw_dryrun_under_test", root / "scripts" / "underwriting_verify_dryrun.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dryrun_verifies_on_clean_machine(tmp_path):
    """The C2.2 dry run: copy ONLY verify_spa.py + report_proof.jsonl to a clean dir, run with no
    spa_core on path → exit 0 (clean) + tamper detected (negative control)."""
    D = _load_dryrun()
    # write a hermetic report into tmp so we don't touch the live data/underwriting artifact.
    paths = _write_inputs(tmp_path)
    proof = tmp_path / "report_proof.jsonl"
    R.write_report(realized_path=paths["realized"], depth_path=paths["depth"],
                   refusal_path=paths["refusal"], out_path=tmp_path / "underwriting_report.json",
                   proof_path=proof, generated_at="2026-06-29T00:00:00+00:00")
    res = D.dry_run(proof)
    assert res["pass"] is True
    assert res["clean_exit"] == 0
    assert res["tamper_detected"] is True
    assert res["files_on_clean_machine"] == ["report_proof.jsonl", "verify_spa.py"]


def test_dryrun_asserts_verifier_zero_dependency():
    """The verifier must not be able to call our code: a literal grep for `import spa_core`."""
    D = _load_dryrun()
    D._assert_verifier_has_no_spa_core_import()  # raises SystemExit on failure
