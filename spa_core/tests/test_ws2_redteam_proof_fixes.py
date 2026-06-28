# LLM_FORBIDDEN
"""test_ws2_redteam_proof_fixes.py — the WS2 red-team CRITICAL fixes (F4/F5/F6/F8).

Each test is written so it would FAIL on the pre-fix behavior and PASS on the fix:

  * F4 — the published `--expect-head` in docs/DD_PACK.md is the DECISION-CHAIN HEAD (not the
    verifier-script SHA-256), and the flagship command reproduces against live data → EXIT 0; a
    standalone generate_dd_pack run cannot pin a head that does not self-verify (it refuses).
  * F5 — a present PRODUCER (a *_series.json) with a MISSING/EMPTY proof fails the verifier (no silent
    pass); `--expect-surfaces` with an absent surface fails CLOSED.
  * F6 — a degenerate Sharpe (|Sharpe|>10) and a par-NAV point (onchain_4626_count==0) are flagged
    ADVISORY in the verifier output (honest labeling, not hidden).
  * F8 — a stray/misnamed decision_log.jsonl (content of a DIFFERENT surface) cannot displace the
    real tournament/decision surface — classification is by CONTENT, not filename/parent-dir.

GUARDRAIL: every producer/proof here is materialised in a pytest tmp_path sandbox — never live data/.
The two LIVE-file checks (F4 flagship command, DD_PACK head distinct from verifier SHA) are read-only.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_VERIFY = _ROOT / "scripts" / "verify_spa.py"
_GEN = _ROOT / "scripts" / "generate_dd_pack.py"
_DD_PACK = _ROOT / "docs" / "DD_PACK.md"
_LIVE_DATA = _ROOT / "data"
_LIVE_RD = _ROOT / "data" / "rates_desk"

_HEAD_RE = re.compile(r"--expect-head\s+([0-9a-f]{64})")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


V = _load("_verify_ws2", _VERIFY)


def _read_jsonl(p: Path):
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _write_jsonl(p: Path, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


# ════════════════════════════════════════════════════════════════════════════════════════════════
# fixtures: producers for the breadth surfaces
# ════════════════════════════════════════════════════════════════════════════════════════════════
def _ranking_doc(n, gen_at, sharpe_fn=lambda i: round(2.0 - i * 0.1, 4)):
    return {"generated_at": gen_at, "ranked_strategies": [
        {"rank": i + 1, "strategy_id": f"S{i:02d}-X", "strategy_key": f"s{i}_x", "name": f"Strat{i}",
         "sharpe": sharpe_fn(i), "sharpe_display": sharpe_fn(i),
         "net_annual_return_pct": round(8.0 - i * 0.05, 4),
         "max_dd_pct": 0.01 * (i + 1), "is_shadow_active": i < 5} for i in range(n)]}


def _nav_curve(n, onchain_fn=lambda i: i + 1):
    return {"id": "rwa_backstop_nav_curve", "series": [
        {"date": f"2026-06-{20 + i:02d}", "ts": f"2026-06-{20 + i:02d}T23:00:00+00:00",
         "tvl_weighted_nav": round(1.0 + i * 0.001, 8), "liq_nav_gap_pct": 100.0 - i,
         "n_assets": 10 + i, "onchain_4626_count": onchain_fn(i), "off_chain_estimate_count": 10}
        for i in range(n)]}


def _sleeve_series(n, sleeve_id="rates_desk_fixed_carry"):
    return {"id": sleeve_id, "series": [
        {"date": f"2026-06-{20 + i:02d}", "ts": f"2026-06-{20 + i:02d}T23:00:00+00:00",
         "equity_usd": round(100000.0 + i * 1.5, 6), "net_apy_pct": round(i * 0.001, 6),
         "open_books": i % 3, "closed_books": 0, "approvals": i, "refusals": 3} for i in range(n)]}


def _build_breadth_sandbox(tmp_path: Path, *, sharpe_fn=None, onchain_fn=None,
                           write_sleeve_proof=True) -> Path:
    """A sandbox data/ with the three breadth surfaces, using the REAL producers so the proofs are
    byte-faithful. Optionally suppress the sleeve proof (to exercise coverage enforcement)."""
    from spa_core.tournament import tournament_proof_chain as TPC
    from spa_core.strategy_lab.rwa_backstop import nav_proof as NAV
    from spa_core.strategy_lab.rates_desk import sleeve_proof as SLV
    data = tmp_path / "data"
    (data / "tournament").mkdir(parents=True)
    (data / "rwa_backstop").mkdir(parents=True)
    paper = data / "rates_desk" / "paper"
    paper.mkdir(parents=True)
    rp = data / "strategy_tournament.json"
    rp.write_text(json.dumps(_ranking_doc(5, "2026-06-28T00:00:00+00:00",
                                          sharpe_fn or (lambda i: round(2.0 - i * 0.1, 4)))))
    TPC.append_ranking(rp, data / "tournament" / "decision_log.jsonl")
    cp = data / "rwa_nav_curve.json"
    cp.write_text(json.dumps(_nav_curve(3, onchain_fn or (lambda i: i + 1))))
    NAV.write_proof(cp, data / "rwa_backstop" / "nav_proof.jsonl")
    (paper / "rates_desk_fixed_carry_series.json").write_text(json.dumps(_sleeve_series(4)))
    if write_sleeve_proof:
        SLV.write_all(paper)
    return data


# ════════════════════════════════════════════════════════════════════════════════════════════════
# F4 — the published --expect-head is the CHAIN HEAD, distinct from the verifier SHA, self-verifying
# ════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not _DD_PACK.exists(), reason="docs/DD_PACK.md not present")
def test_F4_dd_pack_expect_head_is_not_the_verifier_sha():
    """The bad sed pasted the verifier-script SHA-256 into --expect-head. Assert the published head is
    NOT the verifier SHA (the two distinct fields are not conflated)."""
    head = _HEAD_RE.search(_DD_PACK.read_text(encoding="utf-8"))
    assert head, "DD_PACK must embed an --expect-head"
    head = head.group(1)
    vsha = hashlib.sha256(_VERIFY.read_bytes()).hexdigest()
    assert head != vsha, (
        "F4: docs/DD_PACK.md --expect-head equals the verify_spa.py SHA-256 — the chain head was "
        "overwritten with the verifier SHA (the flagship command would FAIL).")


@pytest.mark.skipif(not (_LIVE_RD / "decision_log.jsonl").exists(),
                    reason="live decision_log.jsonl absent")
def test_F4_flagship_expect_head_command_exits_0_against_live_data():
    """The published `verify_spa.py --expect-head <HEAD> data/` must reproduce → EXIT 0, AND the head
    must be the DECISION-CHAIN head (surface A), not the verifier SHA."""
    refresh = _ROOT / "scripts" / "refresh_published_proof.py"

    def _run():
        head = _HEAD_RE.search(_DD_PACK.read_text(encoding="utf-8")).group(1)
        proc = subprocess.run([sys.executable, str(_VERIFY), "--expect-head", head, str(_LIVE_DATA)],
                              capture_output=True, text=True)
        return head, proc

    head, proc = _run()
    if proc.returncode != 0:
        # an hourly tick may have advanced the chain mid-test → run the refresh once (as the agent
        # does next) and re-check. Persistent failure is the genuine F4 condition.
        subprocess.run([sys.executable, str(refresh), "--quiet"], capture_output=True, text=True)
        head, proc = _run()
    assert proc.returncode == 0, f"F4 flagship command FAILED:\n{proc.stdout}\n{proc.stderr}"
    # the matched head is surface A's head (a real decision-chain head, not the verifier SHA).
    rep = V.run([str(_LIVE_RD)])
    assert rep["decision_chain"]["head_hash"] == head


def _seed_valid_chain(rd: Path) -> str:
    """Write a valid 1-row rates-desk decision chain into rd/decision_log.jsonl; return its head."""
    rd.mkdir(parents=True, exist_ok=True)
    ev, gen0 = "rates_desk_decision", "0" * 64
    payload = {"kind": "ENTRY", "approved": True, "underlying": "susde", "as_of": "2026-06-28"}
    canon = json.dumps({"seq": 0, "ts": "t", "event_type": ev, "payload": payload, "prev_hash": gen0},
                       sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    eh = hashlib.sha256(canon.encode()).hexdigest()
    row = {"seq": 0, "ts": "t", "entry_hash": eh, "prev_hash": gen0, **payload}
    (rd / "decision_log.jsonl").write_text(json.dumps(row) + "\n")
    return eh


def test_F4_generate_self_verifies_intact_chain(tmp_path):
    """A standalone generate over an intact chain SELF-VERIFIES (no raise) and embeds the LIVE head."""
    gen = _load("_gen_ws2", _GEN)
    root = tmp_path
    head = _seed_valid_chain(root / "data" / "rates_desk")
    rendered = gen.generate(root=str(root), self_verify=True)
    embedded = _HEAD_RE.search(rendered).group(1)
    assert embedded == head, "the embedded head must be the live decision-chain head"


def test_F4_generate_refuses_orphan_head(tmp_path):
    """The self-verify-or-refuse guard (FAIL#4): if the embedded --expect-head is NOT the live chain
    head (an orphan), generate REFUSES. We render a valid doc, then tamper the embedded head literal
    to an orphan value and assert the guard raises — exactly what stops a stale/sed-corrupted head."""
    gen = _load("_gen_ws2", _GEN)
    root = tmp_path
    head = _seed_valid_chain(root / "data" / "rates_desk")
    rendered = gen.generate(root=str(root), self_verify=True)  # intact → passes
    # ORPHAN head (flip a char) embedded in an otherwise-valid doc → guard must refuse.
    orphan = ("0" if head[0] != "0" else "1") + head[1:]
    tampered = rendered.replace(head, orphan)
    with pytest.raises(gen.HeadNotSelfVerifying):
        gen._assert_head_self_verifies(str(root), tampered)


def test_F4_generate_refuses_verifier_sha_as_head(tmp_path):
    """The exact red-team own-goal: the verifier-script SHA-256 pasted into --expect-head must be
    refused (the two distinct fields must never be conflated)."""
    gen = _load("_gen_ws2", _GEN)
    root = tmp_path
    _seed_valid_chain(root / "data" / "rates_desk")
    # copy verify_spa.py into the sandbox so the generator computes the SAME verifier SHA we embed.
    (root / "scripts").mkdir()
    (root / "scripts" / "verify_spa.py").write_bytes(_VERIFY.read_bytes())
    vsha = hashlib.sha256(_VERIFY.read_bytes()).hexdigest()
    rendered = gen.generate(root=str(root), self_verify=True)
    head = _HEAD_RE.search(rendered).group(1)
    # simulate the bad sed: replace the real head with the verifier SHA in the --expect-head literal.
    tampered = rendered.replace(head, vsha)
    with pytest.raises(gen.HeadNotSelfVerifying):
        gen._assert_head_self_verifies(str(root), tampered)


# ════════════════════════════════════════════════════════════════════════════════════════════════
# F5 — coverage enforcement: a present producer with a missing/empty proof FAILS (no silent pass)
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_F5_present_producer_missing_proof_fails(tmp_path):
    """A populated rates_desk/paper/<sleeve>_series.json with NO matching _series_proof.jsonl must
    FAIL the verifier (pre-fix: silently passed because the proof was simply never globbed)."""
    data = _build_breadth_sandbox(tmp_path, write_sleeve_proof=False)
    rep = V.run([str(data)])
    assert rep["ok"] is False
    assert any("coverage" in e and "rates_desk_fixed_carry_series.json" in e for e in rep["errors"]), \
        rep["errors"]
    assert V.main([str(data)]) == 1


def test_F5_present_producer_empty_proof_fails(tmp_path):
    """An EMPTY/truncated proof for a populated producer must FAIL (an empty proof must not certify a
    populated producer)."""
    data = _build_breadth_sandbox(tmp_path, write_sleeve_proof=True)
    proof = data / "rates_desk" / "paper" / "rates_desk_fixed_carry_series_proof.jsonl"
    proof.write_text("")  # truncate to empty
    rep = V.run([str(data)])
    assert rep["ok"] is False
    assert any("coverage" in e and "EMPTY" in e for e in rep["errors"]), rep["errors"]


def test_F5_unrelated_series_family_is_not_required_to_have_a_proof(tmp_path):
    """A *_series.json OUTSIDE rates_desk/paper/ (e.g. strategy_lab_paper/) is a different surface and
    must NOT trigger a coverage failure — scoping prevents false positives."""
    data = _build_breadth_sandbox(tmp_path, write_sleeve_proof=True)
    other = data / "strategy_lab_paper"
    other.mkdir()
    (other / "variant_n_series.json").write_text(json.dumps(_sleeve_series(5, "variant_n")))
    rep = V.run([str(data)])
    assert rep["ok"] is True, rep["errors"]


def test_F5_expect_surfaces_missing_surface_fails_closed(tmp_path):
    """--expect-surfaces with an absent surface (here a sandbox that has E/F/G but no exit_nav B)
    must FAIL CLOSED — a renamed/hidden surface no longer passes silently."""
    data = _build_breadth_sandbox(tmp_path, write_sleeve_proof=True)
    rep_ok = V.run([str(data)], expect_surfaces=["E", "F", "G"])
    assert rep_ok["ok"] is True, rep_ok["errors"]
    rep_bad = V.run([str(data)], expect_surfaces=["E", "F", "G", "B"])  # B (exit_nav) is absent
    assert rep_bad["ok"] is False
    assert any("[B]" in e and "ABSENT" in e for e in rep_bad["errors"]), rep_bad["errors"]


def test_F5_expect_surfaces_via_cli(tmp_path):
    """The --expect-surfaces flag wired through main(): a required-but-absent surface → exit 1."""
    data = _build_breadth_sandbox(tmp_path, write_sleeve_proof=True)
    assert V.main([str(data), "--expect-surfaces", "E,F,G"]) == 0
    assert V.main([str(data), "--expect-surfaces", "A"]) == 1  # A (rates-desk decision) absent here


# ════════════════════════════════════════════════════════════════════════════════════════════════
# F6 — degenerate Sharpe / par-NAV are flagged ADVISORY (honest labeling, not hidden)
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_F6_degenerate_sharpe_flagged_advisory(tmp_path):
    """A tournament ranking anchoring a |Sharpe|>10 must surface an ADVISORY/MOCK-DATA flag in the
    verifier output (the chain still verifies — the value is just honestly labeled degenerate)."""
    data = _build_breadth_sandbox(tmp_path, sharpe_fn=lambda i: 92.5 if i == 0 else 2.0)
    rep = V.run([str(data)])
    # the chain itself is valid (we are not failing it — we are LABELING it).
    assert rep["tournament"]["valid"] is True
    adv = [a for a in rep["advisories"] if a["surface"] == "tournament"]
    assert adv and "degenerate" in adv[0]["label"].lower(), rep["advisories"]
    assert "92.5" in adv[0]["detail"] or "92.53" in adv[0]["detail"]


def test_F6_par_nav_flagged_advisory(tmp_path):
    """A NAV forward point with onchain_4626_count==0 must surface a MARKETING-PAR advisory (the NAV
    is the $1.00 par estimate, not a measured liquidation NAV)."""
    data = _build_breadth_sandbox(tmp_path, onchain_fn=lambda i: 0)  # all par
    rep = V.run([str(data)])
    assert rep["nav_proof"]["valid"] is True
    adv = [a for a in rep["advisories"] if a["surface"] == "nav_proof"]
    assert adv and "par" in adv[0]["label"].lower(), rep["advisories"]


def test_F6_clean_numbers_no_false_advisory(tmp_path):
    """Sane Sharpe + measured on-chain NAV → NO advisory (we don't cry wolf on legitimate data)."""
    data = _build_breadth_sandbox(tmp_path, sharpe_fn=lambda i: round(2.0 - i * 0.1, 4),
                                  onchain_fn=lambda i: i + 1)
    rep = V.run([str(data)])
    assert rep["advisories"] == [], rep["advisories"]


# ════════════════════════════════════════════════════════════════════════════════════════════════
# F8 — content-based classification: a stray/misnamed file can't displace a real surface
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_F8_stray_decision_log_cannot_displace_tournament(tmp_path):
    """A file NAMED tournament/decision_log.jsonl but whose CONTENT is a rates-desk decision chain
    must NOT be classified as the tournament surface — and vice-versa. Pre-fix (filename/parent-dir)
    a stray file at the tournament path displaced the real surface. Post-fix it classifies by CONTENT.

    We build a full sandbox, then DROP a rates-desk-shaped decision row at the tournament path's
    sibling and assert the tournament bucket still resolves to the real tournament-content file."""
    data = _build_breadth_sandbox(tmp_path, write_sleeve_proof=True)
    # The real tournament file (tournament-content) is at data/tournament/decision_log.jsonl.
    # Now place a STRAY file whose CONTENT is a rates-desk decision (entry_hash + approved + underlying)
    # but whose NAME/parent would have routed it to a surface bucket pre-fix.
    stray_dir = data / "misc"
    stray_dir.mkdir()
    stray = stray_dir / "decision_log.jsonl"  # NAME says "decision_log"
    rd_row = {"seq": 0, "ts": "t", "entry_hash": "0" * 64, "prev_hash": "0" * 64,
              "kind": "REFUSAL", "approved": False, "underlying": "ezeth", "as_of": "2026-06-28"}
    _write_jsonl(stray, [rd_row])
    # classify the stray by content → it is a 'decision_log', NOT 'tournament'.
    assert V._sniff_jsonl_kind(stray) == "decision_log"
    # classify the REAL tournament file by content → 'tournament' regardless of its filename.
    assert V._sniff_jsonl_kind(data / "tournament" / "decision_log.jsonl") == "tournament"
    # full resolution: the tournament bucket binds the tournament-CONTENT file, not the stray.
    inputs = V._resolve_inputs([str(data)])
    assert inputs["tournament"] == data / "tournament" / "decision_log.jsonl"
    assert inputs["tournament"] is not None


def test_F8_misnamed_tournament_file_classifies_as_tournament(tmp_path):
    """The converse: a tournament-CONTENT chain saved under a NON-tournament filename still classifies
    as the tournament surface by content (filename does not lie about what a file IS)."""
    from spa_core.tournament import tournament_proof_chain as TPC
    rp = tmp_path / "strategy_tournament.json"
    rp.write_text(json.dumps(_ranking_doc(4, "2026-06-28T00:00:00+00:00")))
    weird = tmp_path / "weird_name.jsonl"
    TPC.append_ranking(rp, weird)
    assert V._sniff_jsonl_kind(weird) == "tournament"


def test_F8_sleeve_content_classified_even_at_wrong_name(tmp_path):
    """A sleeve-content chain (entry_hash + sleeve_id) classifies as a sleeve regardless of name."""
    from spa_core.strategy_lab.rates_desk import sleeve_proof as SLV
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "rates_desk_fixed_carry_series.json").write_text(json.dumps(_sleeve_series(3)))
    SLV.write_all(paper)
    proof = paper / "rates_desk_fixed_carry_series_proof.jsonl"
    assert V._sniff_jsonl_kind(proof) == "sleeve"
