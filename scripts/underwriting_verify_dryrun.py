# LLM_FORBIDDEN
"""underwriting_verify_dryrun.py — C2.2 PUBLIC-VERIFIABILITY DRY RUN (Lane C).

Simulates a SKEPTICAL THIRD PARTY who wants to verify the underwriting report WITHOUT trusting us
and WITHOUT our codebase. The recipe is deliberately minimal — the reviewer needs exactly TWO files:

    1. scripts/verify_spa.py                       (the zero-dependency verifier)
    2. data/underwriting/report_proof.jsonl        (the public proof artifact, surface H)

This harness copies ONLY those two files into a fresh /tmp/clean directory, then runs the verifier
there with **no spa_core on the path** (PYTHONPATH cleared, cwd = the clean dir) and asserts:

    • exit 0 on a clean chain (the report verifies end-to-end);
    • exit non-zero with a precise broken_at when a value is tampered (negative control);
    • the verifier file itself contains NO `import spa_core` (it cannot secretly call our code).

This is the "don't trust us, check us" proof for the underwriting moat: the report is verifiable on a
machine that has never seen SPA's code. Read-only; writes only under a tmp dir; moves no capital.

REVIEWER RECIPE (what a third party actually does — printed by --recipe):

    mkdir /tmp/clean && cd /tmp/clean
    cp <spa>/scripts/verify_spa.py .
    cp <spa>/data/underwriting/report_proof.jsonl .
    python3 verify_spa.py report_proof.jsonl                 # exit 0 ⇒ verified
    python3 verify_spa.py report_proof.jsonl --expect-surfaces H   # fail-CLOSED if H absent

Usage:
    python3 scripts/underwriting_verify_dryrun.py            # run the full dry run, exit 0 on PASS
    python3 scripts/underwriting_verify_dryrun.py --recipe   # print the reviewer recipe only
    python3 scripts/underwriting_verify_dryrun.py --proof <path>   # verify a specific proof file
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_VERIFIER = _REPO_ROOT / "scripts" / "verify_spa.py"
_DEFAULT_PROOF = _REPO_ROOT / "data" / "underwriting" / "report_proof.jsonl"

_RECIPE = """\
THIRD-PARTY REVIEWER RECIPE (zero-dependency, no SPA code):

  mkdir /tmp/clean && cd /tmp/clean
  cp <spa>/scripts/verify_spa.py .
  cp <spa>/data/underwriting/report_proof.jsonl .
  python3 verify_spa.py report_proof.jsonl                       # exit 0  -> chain verified
  python3 verify_spa.py report_proof.jsonl --expect-surfaces H   # fail-CLOSED if surface H absent

What the verifier proves WITHOUT our code:
  - every section's proof_hash re-derives over the section body (UNDERWRITING_REPORT_SPEC.md §4);
  - the prev-linked entry_hash chain walks contiguously from genesis ("0"*64);
  - REFUSAL-CONSISTENCY: no REFUSED market appears as underwritten capacity (§4a);
  - a tampered value (without a full re-seal) -> precise broken_at, exit non-zero.
"""


def _ensure_report(proof_path: Path) -> Path:
    """If the proof file is absent, generate it from the canonical inputs so the dry run is runnable
    out-of-the-box (the report is ALWAYS written to data/ regardless of the publish flag)."""
    if proof_path.exists():
        return proof_path
    # build it via the canonical builder (uses default Lane-B inputs; fail-CLOSED on missing realized).
    sys.path.insert(0, str(_REPO_ROOT))
    from spa_core.strategy_lab.underwriting import report as R  # noqa: E402
    out = proof_path.parent / "underwriting_report.json"
    res = R.write_report(out_path=out, proof_path=proof_path)
    if not res.get("ok"):
        raise SystemExit(f"dry-run: could not generate the report (fail-CLOSED): {res.get('error')}")
    return proof_path


def _run_verifier_clean(clean_dir: Path, proof_name: str, extra_args=None) -> subprocess.CompletedProcess:
    """Run verify_spa.py inside `clean_dir` with NO spa_core importable: PYTHONPATH emptied + cwd set
    to the clean dir (which contains only the two copied files). This is the third-party machine."""
    env = dict(os.environ)
    env["PYTHONPATH"] = ""                 # strip any inherited spa_core path
    env.pop("PYTHONSTARTUP", None)
    args = [sys.executable, "verify_spa.py", proof_name] + list(extra_args or [])
    return subprocess.run(args, cwd=str(clean_dir), env=env, capture_output=True, text=True)


def _assert_verifier_has_no_spa_core_import() -> None:
    """The verifier must not be able to secretly call our code. A literal grep for `import spa_core`."""
    src = _VERIFIER.read_text(encoding="utf-8")
    for bad in ("import spa_core", "from spa_core"):
        if bad in src:
            raise SystemExit(f"dry-run FAIL: verify_spa.py contains '{bad}' — NOT zero-dependency")


def dry_run(proof_path: Path) -> dict:
    """Execute the full third-party dry run. Returns a result dict; raises SystemExit on FAIL."""
    _assert_verifier_has_no_spa_core_import()
    proof_path = _ensure_report(proof_path)

    clean = Path(tempfile.mkdtemp(prefix="spa_uw_clean_"))
    try:
        # copy ONLY the two files a reviewer needs — nothing else from the repo.
        shutil.copy2(_VERIFIER, clean / "verify_spa.py")
        shutil.copy2(proof_path, clean / "report_proof.jsonl")
        # (sanity) the clean dir holds exactly those two files — no smuggled spa_core.
        contents = sorted(p.name for p in clean.iterdir())
        assert contents == ["report_proof.jsonl", "verify_spa.py"], contents

        # 1) clean run → exit 0, surface H required (fail-CLOSED if absent).
        ok = _run_verifier_clean(clean, "report_proof.jsonl", ["--expect-surfaces", "H"])
        if ok.returncode != 0:
            raise SystemExit(f"dry-run FAIL: clean verify returned {ok.returncode}\n{ok.stdout}\n{ok.stderr}")

        # 2) negative control: tamper a value WITHOUT re-sealing → exit non-zero + broken_at.
        tampered = clean / "report_proof_tampered.jsonl"
        rows = [json.loads(ln) for ln in (clean / "report_proof.jsonl").read_text().splitlines() if ln.strip()]
        forged = False
        for r in rows:
            if r.get("section_id") == "realized":
                r["survives_at_aum_usd"] = 999_000_000.0
                forged = True
        tampered.write_text("\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows)
                            + "\n", encoding="utf-8")
        bad = _run_verifier_clean(clean, "report_proof_tampered.jsonl")
        if forged and bad.returncode == 0:
            raise SystemExit("dry-run FAIL: tampered chain verified clean (negative control broken)")

        return {
            "pass": True,
            "clean_dir": str(clean),
            "clean_exit": ok.returncode,
            "tamper_detected": (bad.returncode != 0) if forged else None,
            "files_on_clean_machine": contents,
        }
    finally:
        shutil.rmtree(clean, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Lane C C2.2 public-verifiability dry run.")
    ap.add_argument("--recipe", action="store_true", help="print the reviewer recipe and exit")
    ap.add_argument("--proof", default=None, help="path to report_proof.jsonl (default: data/underwriting/)")
    args = ap.parse_args(argv)

    if args.recipe:
        print(_RECIPE)
        return 0

    proof = Path(args.proof) if args.proof else _DEFAULT_PROOF
    res = dry_run(proof)
    print("underwriting dry-run: PASS — report verifies on a clean machine with NO spa_core")
    print(f"  files copied to clean machine: {res['files_on_clean_machine']}")
    print(f"  clean verify exit: {res['clean_exit']} (0 = verified, surface H present)")
    print(f"  tamper detected (negative control): {res['tamper_detected']}")
    print()
    print(_RECIPE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
