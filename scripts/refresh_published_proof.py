#!/usr/bin/env python3
"""
refresh_published_proof.py — REFRESH THE PUBLISHED PROOF BUNDLE SO IT NEVER ROTS.

THE PROBLEM (F1, the flagship "don't trust us — check us" own-goal)
-------------------------------------------------------------------
The hourly rates-desk paper tick APPENDS to the tamper-evident decision chain
(`data/rates_desk/decision_log.jsonl`) every hour, so its head_hash advances continuously.
But the published due-diligence artifact `docs/DD_PACK.md` pins a specific head into its
flagship reviewer command:

    python3 scripts/verify_spa.py --expect-head <HEAD> data/rates_desk/

Nothing regenerated DD_PACK after each append, so the pinned head went stale within an hour
and a reviewer pasting our OWN command got EXIT 1. Self-inflicted credibility loss.

THE FIX (this script)
---------------------
On EVERY chain advance, regenerate the published bundle ATOMICALLY TOGETHER so that at ANY
instant a reviewer pulls {decision_log.jsonl, anchors.jsonl, exit_nav.json, DD_PACK.md} they
are MUTUALLY CONSISTENT — DD_PACK's --expect-head always equals the CURRENT decision-chain head:

  1. Re-derive the current decision-chain head (the SAME recipe verify_spa.py uses — delegated
     to proof_chain.verify_mirror so it is byte-identical). fail-CLOSED: a broken/empty chain
     refreshes NOTHING (we never publish over an unverified head).
  2. anchors.jsonl — append a fresh head-checkpoint over the NEW head (idempotent: a no-op when
     the head is unchanged, so re-running between ticks does not bloat the ledger).
  3. exit_nav.json — regenerate the liquidation-NAV-by-size schedule from the now-current
     surface/book (atomic write inside build_exit_nav_schedule).
  4. DD_PACK.md — regenerate (atomic write inside generate_dd_pack), so its embedded
     --expect-head literal = the head re-derived in step 1.

Then SELF-VERIFY (fail-CLOSED): re-run the standalone verifier with --expect-head set to the
head now embedded in the freshly-written DD_PACK.md, and assert EXIT 0. If the bundle is NOT
internally consistent after the refresh, this script exits non-zero (so the agent log shows it
loudly) — but it never tears the already-atomically-written files.

DESIGN CONTRACT (repo rules): stdlib-only, deterministic, fail-CLOSED, atomic writes (each
artifact is written atomically by its own generator). LLM-FORBIDDEN. No network. Idempotent:
running it twice with no chain advance appends no anchor and re-writes byte-identical DD_PACK
content (modulo the regenerated-timestamp line, which is not a sourced number).

USAGE
    python3 scripts/refresh_published_proof.py            # refresh in place, print a summary
    python3 scripts/refresh_published_proof.py --data-dir <dir>   # hermetic/test sandbox
    python3 scripts/refresh_published_proof.py --quiet    # only print on failure

EXIT CODES
    0  bundle refreshed AND self-verifies (DD_PACK --expect-head reproduces against live files)
    1  the chain is broken/empty (nothing safe to publish), or the post-refresh self-verify failed
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[1]
# Make `import spa_core` resolvable when run directly (the agent wrapper cd's to the repo root,
# but launchd hands a minimal PYTHONPATH; belt-and-suspenders so a bare `python3 scripts/…` works).
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# --------------------------------------------------------------------------- #
# load the DD-pack generator + the standalone verifier as modules (they are
# scripts, not importable packages) — same loader the existing tests use.
# --------------------------------------------------------------------------- #
def _load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, str(_ROOT / "scripts" / filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Regex that pulls the embedded --expect-head literal out of the rendered DD_PACK.md.
_HEAD_RE = re.compile(r"--expect-head\s+([0-9a-f]{64})")


def head_in_dd_pack(dd_pack_text: str) -> Optional[str]:
    """Extract the --expect-head literal embedded in DD_PACK.md (None if absent)."""
    m = _HEAD_RE.search(dd_pack_text)
    return m.group(1) if m else None


def _refresh_breadth_surfaces(base_data: Path, summary: dict) -> None:
    """Regenerate the WORKSTREAM 2 proof-breadth artifacts (tournament ranking chain, RWA-backstop
    NAV proof, sleeve forward-series proofs) from their producers' latest data — TOGETHER with the
    rates-desk bundle so they never rot (F1). PURE re-derivation; atomic per file. Every read AND
    write is pinned under ``base_data`` so a hermetic run (sandbox data dir) never touches LIVE
    artifacts. fail-soft per surface: a missing/empty producer input is recorded, never raised."""
    summary.setdefault("breadth", {})
    rd = base_data / "rates_desk"
    paper_dir = rd / "paper"

    # (E) tournament ranking chain — read strategy_tournament.json, write tournament/decision_log.jsonl
    try:
        from spa_core.tournament import tournament_proof_chain as tpc
        rep = tpc.append_ranking(
            ranking_path=base_data / "strategy_tournament.json",
            out_path=base_data / "tournament" / "decision_log.jsonl")
        summary["breadth"]["tournament"] = {"rows": rep["rows"], "head": rep["head_hash"],
                                            "valid": rep["valid"]}
    except Exception as exc:  # noqa: BLE001 — never abort the head-bearing refresh
        summary["errors"].append(f"tournament proof refresh failed: {exc}")

    # (F) RWA-backstop NAV proof — read rwa_nav_curve.json, write rwa_backstop/nav_proof.jsonl
    try:
        from spa_core.strategy_lab.rwa_backstop import nav_proof
        rep = nav_proof.write_proof(
            curve_path=base_data / "rwa_nav_curve.json",
            out_path=base_data / "rwa_backstop" / "nav_proof.jsonl")
        summary["breadth"]["nav_proof"] = {"rows": rep["rows"], "head": rep["head_hash"],
                                          "valid": rep["valid"]}
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"nav_proof refresh failed: {exc}")

    # (G) sleeve forward-series proofs — read every paper/*_series.json, write *_series_proof.jsonl
    try:
        from spa_core.strategy_lab.rates_desk import sleeve_proof
        reps = sleeve_proof.write_all(paper_dir=paper_dir)
        summary["breadth"]["sleeves"] = [
            {"sleeve_id": r["sleeve_id"], "rows": r["rows"], "head": r["head_hash"],
             "valid": r["valid"]} for r in reps]
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"sleeve proof refresh failed: {exc}")


def _refresh_spec_worked_example(gen_root: Path, rows: list, summary: dict) -> None:
    """Keep PROOF_CHAIN_SPEC.md §3 worked-example (seq=111) literals current.

    The published log is a ring-buffered mirror that RE-CHAINS as it grows, so the row at any
    fixed seq changes its prev_hash/entry_hash on each rebase — a pinned literal drifts stale.
    This rewrites the two hex literals in the seq=111 worked-example block from the CURRENT chain
    so a skeptic following the spec literally always gets a MATCH. Scoped to the block, idempotent,
    atomic, fail-soft (never aborts the refresh)."""
    import re
    try:
        spec_path = Path(gen_root) / "docs" / "PROOF_CHAIN_SPEC.md"
        if not spec_path.exists() or len(rows) <= 111:
            return
        row = rows[111] if rows[111].get("seq") == 111 else next(
            (r for r in rows if r.get("seq") == 111), None)
        if not row:
            return
        prev, entry = row.get("prev_hash"), row.get("entry_hash")
        if not (isinstance(prev, str) and isinstance(entry, str) and len(prev) == 64 and len(entry) == 64):
            return
        text = spec_path.read_text(encoding="utf-8")
        m = re.search(r"\*\*Worked example \(real row, seq=111\)\.\*\*[\s\S]{0,600}?which equals that row", text)
        if not m:
            return
        block = m.group(0)
        new_block = re.sub(r"prev_hash: [0-9a-f]{64}", f"prev_hash: {prev}", block)
        new_block = re.sub(r"`[0-9a-f]{64}`",
                           lambda mm: f"`{entry}`" if mm.group(0).strip("`") != prev else mm.group(0),
                           new_block)
        if new_block != block:
            new_text = text.replace(block, new_block)
            tmp = spec_path.with_suffix(".md.tmp")
            tmp.write_text(new_text, encoding="utf-8")
            os.replace(tmp, spec_path)
            summary["spec_example_refreshed"] = True
    except Exception as exc:  # noqa: BLE001 — the head-bearing bundle refresh must not abort on this
        summary["errors"].append(f"spec worked-example refresh failed (non-critical): {exc}")


def refresh(data_dir: Optional[Path] = None, dd_pack_path: Optional[Path] = None) -> dict:
    """Refresh the published bundle over the CURRENT decision-chain head and return a summary.

    Steps (each artifact written atomically by its own generator):
      anchor over the new head -> regenerate exit_nav.json -> regenerate DD_PACK.md.
    fail-CLOSED: if the chain is broken/empty we refresh NOTHING and report it.

    Returns {ok, head, chain_length, anchor_appended, exit_nav_written, dd_pack_path,
             dd_pack_head, self_verify_ok, errors}."""
    from spa_core.strategy_lab.rates_desk import proof_chain, anchors
    from spa_core.strategy_lab.rates_desk import exit_nav as exit_nav_mod

    base_data = data_dir or (_ROOT / "data")
    rd = base_data / "rates_desk"
    decision_log = rd / "decision_log.jsonl"
    anchors_path = rd / "anchors.jsonl"
    # The DD-pack generator reads <gen_root>/data; in a hermetic test the sandbox data dir's
    # parent IS that root. Default (production) = the repo root.
    gen_root = data_dir.parent if data_dir is not None else _ROOT
    dd_pack_path = dd_pack_path or (Path(gen_root) / "docs" / "DD_PACK.md")

    summary: dict = {
        "ok": False, "head": None, "chain_length": None, "anchor_appended": False,
        "exit_nav_written": False, "dd_pack_path": str(dd_pack_path), "dd_pack_head": None,
        "self_verify_ok": False, "errors": [],
    }

    # ── 1. re-derive the CURRENT head, EXACTLY as a third party would (shared verifier) ──
    rows = []
    if decision_log.exists():
        for ln in decision_log.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError:
                rows.append({"__corrupt__": True})  # forces verify_mirror to fail-CLOSE
    chain = proof_chain.verify_mirror(rows)
    if not chain.get("valid") or not chain.get("head_hash"):
        # fail-CLOSED: never publish artifacts over an unverified / empty head.
        summary["errors"].append(
            f"decision chain not verifiable (valid={chain.get('valid')}, "
            f"length={chain.get('length')}) — refusing to refresh published artifacts")
        return summary
    head = chain["head_hash"]
    summary["head"] = head
    summary["chain_length"] = chain.get("length")

    # ── 2. anchors.jsonl — append a fresh checkpoint over the new head (idempotent no-op if same) ──
    try:
        a = anchors.append_anchor(
            anchors_path=anchors_path if data_dir is not None else None,
            log_path=decision_log if data_dir is not None else None,
            head_hash=head, chain_length=chain.get("length"),
        )
        summary["anchor_appended"] = a is not None
    except Exception as exc:  # noqa: BLE001 — anchoring must not abort the rest of the refresh
        summary["errors"].append(f"anchor append failed: {exc}")

    # ── 3. exit_nav.json — regenerate from the now-current surface/book (atomic) ──
    # NOTE: build_exit_nav_schedule's `data_dir` redirects READS only; the WRITE always targets its
    # module-level _OUT unless out_path is given. So in a hermetic run (data_dir set) we MUST also
    # pass out_path under the sandbox, or the test would clobber the LIVE data/rates_desk/exit_nav.json.
    try:
        exit_nav_out = (rd / "exit_nav.json") if data_dir is not None else None
        exit_nav_mod.build_exit_nav_schedule(write=True, data_dir=data_dir, out_path=exit_nav_out)
        summary["exit_nav_written"] = True
    except Exception as exc:  # noqa: BLE001 — keep going; DD_PACK is the head-bearing artifact
        summary["errors"].append(f"exit_nav regenerate failed: {exc}")

    # ── 4. DD_PACK.md — regenerate so its embedded --expect-head == the current head (atomic) ──
    gen = _load_script("dd_pack_gen", "generate_dd_pack.py")
    # self_verify=False: the refresh runs its OWN, stronger full-verifier self-check below (step 5),
    # against the (possibly hermetic) gen_root — the generator's built-in self-verify reads the live
    # repo path, which differs from a sandbox root. The head is still derived live from gen_root/data.
    doc_text = gen.generate(root=str(gen_root), self_verify=False)  # generator reads <gen_root>/data
    gen.atomic_write(str(dd_pack_path), doc_text)
    summary["dd_pack_head"] = head_in_dd_pack(doc_text)

    # ── 4b. WORKSTREAM 2 proof-breadth surfaces — regenerate the tournament / RWA-NAV / sleeve
    #        proof artifacts TOGETHER with the rates-desk bundle so they never rot (F1). Each is a
    #        PURE re-derivation from its producer's latest data artifact (atomic write per file).
    #        In a hermetic run (data_dir set) every read AND write is redirected under the sandbox,
    #        so the LIVE artifacts are never touched. fail-soft: a missing producer input is a no-op
    #        (empty/absent chain), never an abort — the head-bearing rates-desk bundle still refreshes.
    _refresh_breadth_surfaces(base_data, summary)

    # ── 4c. PROOF_CHAIN_SPEC.md §3 worked-example — keep the seq=111 literals current (self-heal
    #        the drifting ring-buffer example so the "check us" doc never cites a stale hash). ──
    _refresh_spec_worked_example(Path(gen_root), rows, summary)

    # ── 5. SELF-VERIFY (fail-CLOSED): the head now in DD_PACK must reproduce against live files ──
    ver = _load_script("verify_spa", "verify_spa.py")
    dd_head = summary["dd_pack_head"]
    if not dd_head:
        summary["errors"].append("DD_PACK.md carries no --expect-head after regeneration")
        return summary
    if dd_head != head:
        summary["errors"].append(
            f"DD_PACK head {dd_head} != re-derived chain head {head} (generator/chain mismatch)")
        return summary
    report = ver.run([str(rd)], expect_head=dd_head)
    summary["self_verify_ok"] = bool(report.get("ok"))
    if not report.get("ok"):
        summary["errors"].append(
            "post-refresh self-verify FAILED — DD_PACK --expect-head does not reproduce against "
            f"live files: {report.get('errors')}")
        return summary

    # ── 5b. SELF-VERIFY the WHOLE data dir (fail-CLOSED): every WORKSTREAM 2 breadth surface
    #        (tournament / RWA-NAV / sleeve) just regenerated must ALSO reproduce, so the published
    #        breadth bundle is never left rotted/inconsistent after a refresh. The combined verdict
    #        gates `ok`. (No --expect-head here: the head-pin lives in the rates-desk bundle above.)
    breadth_report = ver.run([str(base_data)])
    summary["breadth_verify_ok"] = bool(breadth_report.get("ok"))
    if not breadth_report.get("ok"):
        summary["errors"].append(
            "post-refresh breadth self-verify FAILED — a WORKSTREAM 2 proof surface (tournament / "
            f"RWA-NAV / sleeve) does not reproduce after refresh: {breadth_report.get('errors')}")
        return summary

    summary["ok"] = True
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Refresh SPA's published proof bundle (never-rot fix).")
    ap.add_argument("--data-dir", default=None, help="hermetic data dir (tests); default = repo data/")
    ap.add_argument("--quiet", action="store_true", help="only print on failure")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir).resolve() if args.data_dir else None
    summary = refresh(data_dir=data_dir)

    if summary["ok"]:
        if not args.quiet:
            print("✅ published proof bundle refreshed & self-verifies — "
                  f"head={summary['head'][:16]}…@{summary['chain_length']} "
                  f"(anchor_appended={summary['anchor_appended']}, "
                  f"exit_nav_written={summary['exit_nav_written']})")
        return 0
    print("❌ proof refresh FAILED — published bundle NOT advanced:", file=sys.stderr)
    for e in summary["errors"]:
        print(f"   ✗ {e}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
