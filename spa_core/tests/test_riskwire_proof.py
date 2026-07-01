"""
test_riskwire_proof.py — WS1.4 unified RISKWIRE proof + zero-dependency verifier (property + red-team + smoke).

Covers spa_core/riskwire/proof.py (the per-row + per-artifact proof glue) AND scripts/verify_riskwire.py
(the standalone, no-spa_core verifier). The red-team probes prove the proof covers OUTPUTS not just
inputs, is tamper-evident at the exact broken_at, and reproduces on a clean machine.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from spa_core.riskwire import (
    ExitLiquidityBySize, RISKWIRE_CLASS_LABELS, RiskWireClass, RiskWireMeasurement,
    RiskWireRefusal, SubjectKind,
)
from spa_core.riskwire import proof

_ROOT = Path(__file__).resolve().parents[2]
_VERIFIER = _ROOT / "scripts" / "verify_riskwire.py"
_PY = sys.executable


# ── fixtures ────────────────────────────────────────────────────────────────────────────────────
def _mk(sid, kind, cls, native, seed, seed_hash, refusal=None, exits=(), nav=None,
        struct=None, total=None, as_of="2026-06-30", flagged=False, flag_reason=None):
    return RiskWireMeasurement(
        subject_id=sid, kind=kind, display_name=sid.split("::")[-1], risk_class=cls,
        risk_class_label=RISKWIRE_CLASS_LABELS[cls], native_verdict=native, refusal=refusal,
        exit_liquidity_by_size=list(exits), liquidation_nav=nav, structural_haircut=struct,
        total_haircut=total, seed=seed, seed_proof_hash=seed_hash, as_of=as_of, flagged=flagged,
        flag_reason=flag_reason, provenance=f"{seed}:seed", prev_hash="")


def _sample_measurements():
    return [
        _mk("pool::aave_v3-usdc", SubjectKind.POOL, RiskWireClass.A, "A", "dfb", "a" * 64,
            refusal=RiskWireRefusal("SAFE", "clean", False),
            exits=[ExitLiquidityBySize(1_000_000, 980000.0, 0.98, False)], struct=0.004, total=0.02),
        _mk("pool::ezeth-pt", SubjectKind.POOL, RiskWireClass.D, "D", "dfb", "b" * 64,
            refusal=RiskWireRefusal("REFUSE", "structural tail-comp veto", True),
            exits=[ExitLiquidityBySize(1_000_000, None, None, True)], struct=0.097, total=0.31),
        _mk("rwa_collateral::buidl", SubjectKind.RWA_COLLATERAL, RiskWireClass.B, "LIQUID",
            "rwa_backstop", "c" * 64, refusal=RiskWireRefusal("SAFE", "liquid", False),
            nav={"frac_1m": 0.99, "usd_1m": 990000.0}),
        _mk("book::fixed_carry", SubjectKind.BOOK, RiskWireClass.A, "SURVIVES_AT",
            "underwriting", "d" * 64),
    ]


def _write_day30(riskwire_dir: Path):
    """Write a WS1.3-shaped day-30 review (state + review_hash over content minus review_hash/
    generated_at) — the REAL schema spa_core.riskwire.day30_review publishes. We build it minimally
    here (WS1.3 owns the real pipeline); the point is proof.compute_review_hash reproduces its hash."""
    riskwire_dir.mkdir(parents=True, exist_ok=True)
    review = {
        "schema": "day30-review-v1",
        "model": "day30_review",
        "llm_forbidden": True,
        "deterministic": True,
        "generated_at": "2026-06-30T09:05:00+00:00",
        "state": "TRACK_MATURING",
        "ready_for_review": False,
        "min_track_days": 30,
        "day30_artifact": {"schema": "day30-v1", "generated_at": "2026-06-30T09:05:01+00:00",
                           "readiness_pct": 30.0, "proof_hash": "e" * 64},
        "note": "thin track, INSUFFICIENT_DATA",
    }
    review["review_hash"] = proof.compute_review_hash(review)
    (riskwire_dir / "day30_review.json").write_text(json.dumps(review, indent=1))
    return review


@pytest.fixture
def rw_data(tmp_path):
    """Write a clean RISKWIRE dataset to an isolated data/riskwire/ under tmp_path."""
    ms = _sample_measurements()
    proof.write_measurements(ms, generated_at="2026-06-30T09:00:00+00:00", as_of="2026-06-30",
                             data_dir=tmp_path)
    _write_day30(tmp_path / "riskwire")
    return tmp_path / "riskwire"


# ── PROPERTY: determinism + valid chains ──────────────────────────────────────────────────────────
def test_measurements_artifact_deterministic():
    a = proof.build_measurements_artifact(_sample_measurements(),
                                          generated_at="2026-06-30T09:00:00+00:00", as_of="2026-06-30")
    b = proof.build_measurements_artifact(_sample_measurements(),
                                          generated_at="2026-06-30T09:00:00+00:00", as_of="2026-06-30")
    assert a == b
    assert a["artifact_hash"] == b["artifact_hash"]


def test_measurements_artifact_verifies():
    a = proof.build_measurements_artifact(_sample_measurements(),
                                          generated_at="2026-06-30T09:00:00+00:00", as_of="2026-06-30")
    res = proof.verify_artifact(a, "measurements")
    assert res["valid"] is True
    assert res["n_rows"] == 4
    assert res["head_hash"] == a["head_hash"]
    assert res["artifact_hash"] == a["artifact_hash"]


def test_day30_review_verifies(tmp_path):
    review = _write_day30(tmp_path / "riskwire")
    res = proof.verify_day30_review(review)
    assert res["valid"] is True
    assert res["review_hash"] == review["review_hash"]


def test_day30_review_tamper_breaks(tmp_path):
    review = _write_day30(tmp_path / "riskwire")
    review["state"] = "READY_FOR_REVIEW"     # forge the review verdict, don't re-hash
    res = proof.verify_day30_review(review)
    assert res["valid"] is False and res["broken_at"] == "review_hash"


def test_day30_nested_artifact_tamper_breaks(tmp_path):
    """The nested day30_artifact.proof_hash IS hash-covered — forging it breaks review_hash."""
    review = _write_day30(tmp_path / "riskwire")
    review["day30_artifact"]["proof_hash"] = "f" * 64
    assert proof.verify_day30_review(review)["valid"] is False


def test_day30_review_hash_matches_ws13_recipe(tmp_path):
    """proof.compute_review_hash reproduces spa_core.riskwire.day30_review.compute_review_hash byte-for-byte."""
    from spa_core.riskwire import day30_review as ws13
    review = _write_day30(tmp_path / "riskwire")
    assert proof.compute_review_hash(review) == ws13.compute_review_hash(review)


def test_empty_artifact_is_still_anchored():
    a = proof.build_measurements_artifact([], generated_at="2026-06-30T09:00:00+00:00", as_of=None)
    res = proof.verify_artifact(a, "measurements")
    assert res["valid"] is True and res["n_rows"] == 0 and res["head_hash"] is None


def test_verify_all_over_disk(rw_data):
    res = proof.verify_all(data_dir=rw_data.parent)
    assert res["all_ok"] is True
    assert res["artifacts"]["measurements.json"]["valid"]
    assert res["artifacts"]["day30_review.json"]["valid"]


def test_verify_all_missing_is_fail_closed(tmp_path):
    # no data/riskwire/ written → all_ok must be False, not silently True
    res = proof.verify_all(data_dir=tmp_path)
    assert res["all_ok"] is False
    assert res["artifacts"]["measurements.json"]["present"] is False


# ── RED-TEAM: proof covers OUTPUTS, tamper-evident at exact broken_at ──────────────────────────────
def test_forged_output_breaks_chain():
    """Forge an OUTPUT (a risk_class D→A, laundering a toxic book) → the row chain breaks."""
    a = proof.build_measurements_artifact(_sample_measurements(),
                                          generated_at="2026-06-30T09:00:00+00:00", as_of="2026-06-30")
    a["measurements"][1]["risk_class"] = "A"          # forge the toxic ezeth-pt to safe
    res = proof.verify_artifact(a, "measurements")
    assert res["valid"] is False
    assert res["broken_at"] == 1                       # exact row index


def test_forged_count_breaks_artifact_hash():
    """Forge a wrapper COUNT (hide the refusal) → per-row passes but artifact_hash diverges."""
    a = proof.build_measurements_artifact(_sample_measurements(),
                                          generated_at="2026-06-30T09:00:00+00:00", as_of="2026-06-30")
    a["n_refused"] = 0
    res = proof.verify_artifact(a, "measurements")
    assert res["valid"] is False and res["broken_at"] == "artifact_hash"


def test_dropped_row_breaks_head():
    """Splice out a row → the wrapper head_hash no longer matches the re-derived chain head."""
    a = proof.build_measurements_artifact(_sample_measurements(),
                                          generated_at="2026-06-30T09:00:00+00:00", as_of="2026-06-30")
    a["measurements"] = a["measurements"][:-1]
    res = proof.verify_artifact(a, "measurements")
    assert res["valid"] is False and res["broken_at"] == "head_hash"


def test_reordered_rows_break():
    a = proof.build_measurements_artifact(_sample_measurements(),
                                          generated_at="2026-06-30T09:00:00+00:00", as_of="2026-06-30")
    a["measurements"][0], a["measurements"][1] = a["measurements"][1], a["measurements"][0]
    res = proof.verify_artifact(a, "measurements")
    assert res["valid"] is False


# ── SMOKE + RED-TEAM: the STANDALONE verifier on a CLEAN machine (env -i, no spa_core) ─────────────
def _run_clean(*args):
    """Run verify_riskwire.py with a scrubbed env (no PYTHONPATH → no spa_core) — the clean machine."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    return subprocess.run([_PY, str(_VERIFIER), *args], capture_output=True, text=True, env=env)


def test_verifier_clean_machine_exit0(rw_data):
    r = _run_clean(str(rw_data))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK — every RISKWIRE artifact reproduces" in r.stdout
    assert "spa_core" not in r.stdout.lower() or "no spa_core import" in r.stdout.lower()


def test_verifier_no_spa_core_on_path(rw_data):
    """Prove it genuinely does not need spa_core: block it on sys.path entirely."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": "/nonexistent"}
    r = subprocess.run([_PY, "-c",
                        "import sys; sys.argv=['v', %r]; "
                        "assert 'spa_core' not in sys.modules; "
                        "exec(open(%r).read())" % (str(rw_data), str(_VERIFIER))],
                       capture_output=True, text=True, env=env)
    # the exec runs main() via SystemExit; exit 0 means clean reproduce with spa_core never imported
    assert r.returncode == 0, r.stdout + r.stderr


def test_verifier_catches_tamper_broken_at(rw_data, tmp_path):
    """Tamper a measurement OUTPUT on disk → the clean-machine verifier reports broken_at + exit 1."""
    m = rw_data / "measurements.json"
    doc = json.loads(m.read_text())
    doc["measurements"][1]["native_verdict"] = "A"   # forge the toxic book's verdict
    m.write_text(json.dumps(doc, indent=1))
    r = _run_clean(str(m))
    assert r.returncode == 1
    assert "broken_at=1" in r.stdout


def test_verifier_catches_day30_tamper(rw_data):
    d = rw_data / "day30_review.json"
    doc = json.loads(d.read_text())
    doc["state"] = "READY_FOR_REVIEW"                  # forge the review verdict (no re-hash)
    d.write_text(json.dumps(doc, indent=1))
    r = _run_clean(str(d))
    assert r.returncode == 1 and "broken_at=review_hash" in r.stdout


def test_verifier_no_input_exit2(tmp_path):
    r = _run_clean(str(tmp_path))     # empty dir → no artifacts
    assert r.returncode == 2
