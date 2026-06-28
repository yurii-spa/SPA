#!/usr/bin/env python3
"""
scripts/smoke_test_flagship.py — END-TO-END SMOKE TEST for SPA's two flagship surfaces.

The single command the owner (or CI) runs to confirm the flagship is healthy:

  1. Liquidation-NAV-by-size  — the per-ticket forced-unwind EXIT schedule for the desk's
     own carry book (a conservative LOWER BOUND, fail-CLOSED, never a fabricated fill).
  2. Public Refusal-log       — the tamper-evident "what we traded AND what we refused + why"
     decision chain, with EN+RU human rationales for every reason token.

What it does (REAL data, no mutation of canonical git state — engines write their OWN
gitignored artifacts, which is fine):

  STEP 1  run `python3 -m spa_core.strategy_lab.rates_desk.exit_nav` and assert the written
          data/rates_desk/exit_nav.json is SANE: illustrative schedule non-empty + MONOTONIC
          (haircut non-decreasing, net-frac non-increasing across tickets), every FINITE haircut
          in [0,100], flagged rows have net_proceeds_usd=null (no fabrication), the live
          `schedule` present (holes OK), conservative-bound model label + validation_ref present.
  STEP 2  verify the refusal chain: load data/rates_desk/decision_log.jsonl, run the same
          intrinsic hash recompute the public API uses + the authoritative
          spa_core.audit.hash_chain.verify_chain() over data/audit_chain.jsonl; assert
          refusal_explain.explain() returns EN+RU for EVERY reason token present in the log.
  STEP 3  hit the APIs via FastAPI TestClient (no network): GET /api/rates-desk/exit-nav,
          /api/rates-desk/refusals, /api/rates-desk/proof — assert 200, fail-closed shapes,
          chain.verified, head_hash, counts. No 500s.
  STEP 4  `cd landing && npm run build` → assert exit 0 (dashboard compiles with the 2 panels);
          grep dist/ for the panel markers (exit-nav, refusal, integrity).
  STEP 5  print a one-screen SUMMARY: the illustrative ticket schedule table, the live-book
          holes, refusal counts + head_hash + chain verified, and a final
          "NUMBERS SANE: YES/NO" + "SMOKE TEST: PASS/FAIL".

Deterministic, idempotent, safe to re-run. Exit 0 = all good, 1 = any failure.
stdlib + repo deps only; runs the project python. LLM-FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── make the repo importable regardless of CWD ──────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_EXIT_NAV_JSON = _ROOT / "data" / "rates_desk" / "exit_nav.json"
_DECISION_LOG = _ROOT / "data" / "rates_desk" / "decision_log.jsonl"
_LANDING = _ROOT / "landing"
_DIST = _LANDING / "dist"

# Collected failures (each a precise string). Empty ⇒ PASS.
FAILS: List[str] = []
# Collected non-fatal notes (informational; do not fail the smoke test).
NOTES: List[str] = []


def _fail(msg: str) -> None:
    FAILS.append(msg)
    print(f"  ✗ FAIL: {msg}")


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _note(msg: str) -> None:
    NOTES.append(msg)
    print(f"  · {msg}")


def _is_finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def _fmt_usd(x) -> str:
    if x is None:
        return "—"
    try:
        return f"${float(x):,.0f}"
    except (TypeError, ValueError):
        return str(x)


# ════════════════════════════════════════════════════════════════════════════════════════════
# STEP 1 — run the exit_nav engine + assert the schedule is sane
# ════════════════════════════════════════════════════════════════════════════════════════════
def step1_exit_nav() -> Optional[dict]:
    print("\n[1/5] Liquidation-NAV-by-size — run engine + assert sanity")
    # Run the engine as a module (exactly what the agent runs). It writes its own gitignored
    # artifact; we never touch the live paper track destructively.
    proc = subprocess.run(
        [sys.executable, "-m", "spa_core.strategy_lab.rates_desk.exit_nav"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        _fail(f"exit_nav engine exited {proc.returncode}\n--- stderr ---\n{proc.stderr.strip()[:1500]}")
        return None
    _ok("engine ran (exit 0)")

    if not _EXIT_NAV_JSON.exists():
        _fail(f"exit_nav.json not written at {_EXIT_NAV_JSON}")
        return None
    try:
        data = json.loads(_EXIT_NAV_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _fail(f"exit_nav.json unreadable: {exc}")
        return None
    _ok(f"exit_nav.json written + parsed ({_EXIT_NAV_JSON.relative_to(_ROOT)})")

    # ── conservative-bound model label + validation_ref present ──
    model = data.get("model")
    if model != "constant_product_amm_conservative_lower_bound":
        _fail(f"model label wrong / missing: {model!r}")
    else:
        _ok(f"model label = {model}")
    if not data.get("validation_ref"):
        _fail("validation_ref missing")
    else:
        _ok(f"validation_ref = {data['validation_ref']}")

    # ── live schedule present (holes OK) ──
    live_sched = data.get("schedule")
    if not isinstance(live_sched, list):
        _fail("live `schedule` is not a list")
    else:
        _ok(f"live schedule present ({len(live_sched)} rows; holes OK)")
        _assert_rows_failclosed(live_sched, "live")

    # ── illustrative schedule non-empty + monotonic ──
    ill = data.get("illustrative")
    if not isinstance(ill, dict):
        _fail("illustrative schedule absent (must demonstrate the model on a real deep market)")
    else:
        isched = ill.get("schedule")
        if not isinstance(isched, list) or not isched:
            _fail("illustrative.schedule empty")
        else:
            _ok(f"illustrative schedule present ({len(isched)} rows)")
            _assert_rows_failclosed(isched, "illustrative")
            _assert_monotonic(isched)
            _assert_haircut_range(isched)
    return data


def _assert_rows_failclosed(rows: List[dict], label: str) -> None:
    """Flagged rows MUST have net_proceeds_usd=null + haircut_pct=null (no fabrication)."""
    bad = 0
    for r in rows:
        if not isinstance(r, dict):
            bad += 1
            continue
        if r.get("flagged"):
            if r.get("net_proceeds_usd") is not None or r.get("haircut_pct") is not None:
                _fail(f"{label}: flagged row ticket={r.get('ticket_usd')} has a fabricated "
                      f"net/haircut (must be null)")
                bad += 1
            if not r.get("flag_reason"):
                _fail(f"{label}: flagged row ticket={r.get('ticket_usd')} missing flag_reason")
                bad += 1
    if bad == 0:
        _ok(f"{label}: fail-closed contract holds (flagged ⇒ net/haircut null)")


def _assert_haircut_range(rows: List[dict]) -> None:
    """Every FINITE haircut_pct must be in [0, 100]."""
    bad = False
    for r in rows:
        hc = r.get("haircut_pct")
        if hc is None:
            continue
        if not _is_finite(hc) or not (0.0 <= float(hc) <= 100.0):
            _fail(f"illustrative: haircut_pct out of [0,100] at ticket={r.get('ticket_usd')}: {hc}")
            bad = True
    if not bad:
        _ok("illustrative: every finite haircut in [0,100]")


def _assert_monotonic(rows: List[dict]) -> None:
    """Across ascending tickets: haircut_pct non-decreasing, net-fraction non-increasing.

    Compares only over FINITE-valued adjacent pairs (a flagged hole resets the comparison —
    a hole is not a violation, it's a fail-closed gap). net-fraction = net_proceeds_usd / gross_usd.
    """
    # rows are in ticket order as built by the engine; assert ascending tickets first.
    tickets = [r.get("ticket_usd") for r in rows if _is_finite(r.get("ticket_usd"))]
    if tickets != sorted(tickets):
        _fail(f"illustrative: tickets not ascending: {tickets}")
        return

    haircut_ok = True
    netfrac_ok = True
    prev_hc: Optional[float] = None
    prev_nf: Optional[float] = None
    for r in rows:
        hc = r.get("haircut_pct")
        gross = r.get("gross_usd")
        net = r.get("net_proceeds_usd")
        # net-fraction only when both finite + gross>0
        nf: Optional[float] = None
        if _is_finite(net) and _is_finite(gross) and float(gross) > 0:
            nf = float(net) / float(gross)

        if _is_finite(hc):
            if prev_hc is not None and float(hc) + 1e-9 < prev_hc:
                _fail(f"illustrative: haircut DECREASED across tickets "
                      f"({prev_hc:.6f}% → {float(hc):.6f}% at ticket={r.get('ticket_usd')})")
                haircut_ok = False
            prev_hc = float(hc)
        if nf is not None:
            if prev_nf is not None and nf > prev_nf + 1e-9:
                _fail(f"illustrative: net-fraction INCREASED across tickets "
                      f"({prev_nf:.6f} → {nf:.6f} at ticket={r.get('ticket_usd')})")
                netfrac_ok = False
            prev_nf = nf

    if haircut_ok:
        _ok("illustrative: haircut non-decreasing across tickets (monotonic)")
    if netfrac_ok:
        _ok("illustrative: net-fraction non-increasing across tickets (monotonic)")


# ════════════════════════════════════════════════════════════════════════════════════════════
# STEP 2 — verify the refusal chain + EN/RU explanations
# ════════════════════════════════════════════════════════════════════════════════════════════
def step2_refusal_chain() -> Tuple[Optional[List[dict]], dict]:
    print("\n[2/5] Refusal chain — load decision_log + verify integrity + EN/RU explain")
    summary: Dict[str, Any] = {"counts": {"ENTRY": 0, "REFUSAL": 0}, "head_hash": None,
                               "chain_verified": False, "reasons": {}}

    if not _DECISION_LOG.exists():
        _fail(f"decision_log.jsonl absent at {_DECISION_LOG}")
        return None, summary

    rows: List[dict] = []
    corrupt = 0
    for ln in _DECISION_LOG.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            corrupt += 1
    if corrupt:
        _fail(f"decision_log has {corrupt} corrupt line(s)")
    _ok(f"decision_log loaded ({len(rows)} rows)")

    # ── (a) authoritative append-only hash_chain over data/audit_chain.jsonl ──
    try:
        from spa_core.audit import hash_chain
        vc = hash_chain.verify_chain()
        if vc.get("valid"):
            _ok(f"hash_chain.verify_chain() valid:true (len={vc.get('length')}, authoritative audit_chain.jsonl)")
        else:
            _fail(f"hash_chain.verify_chain() valid:FALSE broken_at={vc.get('broken_at')} "
                  f"(authoritative audit_chain.jsonl)")
    except Exception as exc:  # noqa: BLE001
        _fail(f"hash_chain.verify_chain() raised: {exc}")
        hash_chain = None  # type: ignore

    # ── (b) GENUINE single-chain verification over the PUBLIC decision_log mirror (spec §5) ──
    #
    # This is EXACTLY the integrity model the public /api/rates-desk/{refusals,proof} endpoints
    # enforce (spa_core.api.routers.rates_desk._verify_decision_log → proof_chain.verify_mirror) AND
    # the published docs/PROOF_CHAIN_SPEC.md §5 recipe a third party runs by hand: walk in seq order
    # requiring (1) seq == idx (contiguous, single genesis), (2) prev_hash == previous row's
    # entry_hash (prev-linkage; genesis prev_hash = "0"*64), (3) recompute_entry_hash(row) ==
    # entry_hash. head_hash = the LAST row's entry_hash. This is a REAL chain check — a multi-genesis,
    # reordered, or forged/unlinked row fails it (the old "intrinsic-only, skip prev-linkage" check
    # silently passed the corrupt concatenated file; this does not).
    head_hash = None
    try:
        from spa_core.strategy_lab.rates_desk import proof_chain
        vm = proof_chain.verify_mirror(rows)
        if vm["valid"]:
            head_hash = vm["head_hash"]
            summary["chain_verified"] = True
            _ok(f"decision_log verifies as ONE chain per PROOF_CHAIN_SPEC.md §5 "
                f"(len={vm['length']}, head={str(head_hash)[:16]}…) — seq-contiguous, prev-linked, "
                f"single genesis; API verdict == spec verdict")
        else:
            _fail(f"decision_log NOT a single coherent chain: verified:FALSE broken_at={vm['broken_at']} "
                  f"(spec §5 / API agree) — published file would fail third-party verification")
    except Exception as exc:  # noqa: BLE001
        _fail(f"proof_chain.verify_mirror raised: {exc}")
    summary["head_hash"] = head_hash

    # ── counts ──
    for r in rows:
        k = r.get("kind")
        if k in summary["counts"]:
            summary["counts"][k] += 1
        rs = r.get("reason")
        summary["reasons"][rs] = summary["reasons"].get(rs, 0) + 1
    _ok(f"counts: ENTRY={summary['counts']['ENTRY']} REFUSAL={summary['counts']['REFUSAL']}")

    # ── EN/RU explanation for EVERY reason token present ──
    try:
        from spa_core.strategy_lab.rates_desk import refusal_explain
        # the dict must be TOTAL over the policy enum (a new KillReason cannot ship unexplained)
        refusal_explain.assert_total()
        _ok("refusal_explain.assert_total() — every KillReason mapped EN+RU+headline")
        # and every token ACTUALLY in the log must produce a non-empty EN+RU explanation
        seen = set()
        bad = False
        for r in rows:
            tok = r.get("reason")
            if tok in seen:
                continue
            seen.add(tok)
            ex = refusal_explain.explain(r)
            en, ru = ex.get("plain_en"), ex.get("plain_ru")
            if not (isinstance(en, str) and en.strip()) or not (isinstance(ru, str) and ru.strip()):
                _fail(f"refusal_explain.explain(): missing EN/RU for reason token {tok!r}")
                bad = True
            if ex.get("headline") in (None, ""):
                _fail(f"refusal_explain.explain(): missing headline for reason token {tok!r}")
                bad = True
        if not bad:
            _ok(f"EN+RU explanation present for all {len(seen)} reason tokens in log: "
                f"{sorted(str(t) for t in seen)}")
    except Exception as exc:  # noqa: BLE001
        _fail(f"refusal_explain failed: {exc}")

    return rows, summary


# ════════════════════════════════════════════════════════════════════════════════════════════
# STEP 3 — hit the APIs via FastAPI TestClient (fail-closed shapes, no 500s)
# ════════════════════════════════════════════════════════════════════════════════════════════
def step3_apis() -> dict:
    print("\n[3/5] APIs — TestClient (no network): exit-nav / refusals / proof")
    api_summary: Dict[str, Any] = {}
    try:
        from fastapi.testclient import TestClient
        from spa_core.api.server import app
    except Exception as exc:  # noqa: BLE001
        _fail(f"could not import FastAPI app / TestClient: {exc}")
        return api_summary

    client = TestClient(app)

    # GET /api/rates-desk/exit-nav
    r = client.get("/api/rates-desk/exit-nav")
    if r.status_code != 200:
        _fail(f"GET /api/rates-desk/exit-nav → {r.status_code} (expected 200)")
    else:
        j = r.json()
        missing = [f for f in ("schedule", "illustrative", "model", "validation_ref", "is_advisory")
                   if f not in j]
        if missing:
            _fail(f"exit-nav payload missing fields: {missing}")
        elif j.get("is_advisory") is not True:
            _fail("exit-nav is_advisory must be true")
        elif not isinstance(j.get("schedule"), list):
            _fail("exit-nav schedule not a list (fail-closed shape)")
        else:
            _ok("GET /api/rates-desk/exit-nav → 200, schedule+illustrative+provenance present")
            api_summary["exit_nav_rows"] = len(j["schedule"])

    # GET /api/rates-desk/refusals
    r = client.get("/api/rates-desk/refusals")
    if r.status_code != 200:
        _fail(f"GET /api/rates-desk/refusals → {r.status_code} (expected 200)")
    else:
        j = r.json()
        chain = j.get("chain") or {}
        if "chain" not in j or "counts" not in j or "decisions" not in j:
            _fail(f"refusals payload missing top-level fields (have {sorted(j.keys())})")
        elif chain.get("verified") is not True:
            _fail(f"refusals chain.verified is not true: {chain.get('verified')} "
                  f"(broken_at={chain.get('broken_at')})")
        elif not chain.get("head_hash"):
            _fail("refusals chain.head_hash missing")
        else:
            _ok(f"GET /api/rates-desk/refusals → 200, chain.verified=true, "
                f"head={str(chain.get('head_hash'))[:12]}…, counts={j.get('counts')}")
            api_summary["refusals_counts"] = j.get("counts")
            api_summary["refusals_head"] = chain.get("head_hash")

    # GET /api/rates-desk/proof
    r = client.get("/api/rates-desk/proof")
    if r.status_code != 200:
        _fail(f"GET /api/rates-desk/proof → {r.status_code} (expected 200)")
    else:
        j = r.json()
        if j.get("verified") is not True:
            _fail(f"proof verified is not true: {j.get('verified')} (broken_at={j.get('broken_at')})")
        elif not j.get("head_hash"):
            _fail("proof head_hash missing")
        else:
            _ok(f"GET /api/rates-desk/proof → 200, verified=true, chain_length={j.get('chain_length')}")
            api_summary["proof_head"] = j.get("head_hash")
    return api_summary


# ════════════════════════════════════════════════════════════════════════════════════════════
# STEP 4 — landing build + grep dist for the panel markers
# ════════════════════════════════════════════════════════════════════════════════════════════
def step4_landing_build() -> None:
    print("\n[4/5] Landing — npm run build + grep dist for the 2 panels")
    if not (_LANDING / "package.json").exists():
        _fail(f"landing/package.json absent at {_LANDING}")
        return
    if not (_LANDING / "node_modules").exists():
        _fail("landing/node_modules absent — run `npm install` in landing/ first")
        return

    env = dict(os.environ)
    env.setdefault("CI", "true")
    proc = subprocess.run(
        ["npm", "run", "build"], cwd=str(_LANDING),
        capture_output=True, text=True, env=env,
    )
    if proc.returncode != 0:
        _fail(f"`npm run build` exited {proc.returncode}\n--- tail stdout ---\n"
              f"{proc.stdout.strip()[-1200:]}\n--- tail stderr ---\n{proc.stderr.strip()[-1200:]}")
        return
    _ok("npm run build → exit 0 (dashboard compiles)")

    if not _DIST.exists():
        _fail(f"dist/ not produced at {_DIST}")
        return

    # Read every text-ish dist file once; grep for distinctive panel markers (these string
    # literals from DashboardLive.jsx survive into the compiled JS bundle).
    blob_parts: List[str] = []
    for p in _DIST.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".js", ".html", ".mjs", ".css"):
            try:
                blob_parts.append(p.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
    blob = "\n".join(blob_parts)

    markers = {
        "exit-nav panel": "/api/rates-desk/exit-nav",
        "refusal-log panel": "/api/rates-desk/refusals",
        "refusal-log title": "Public refusal log",
        "integrity badge": "INTEGRITY BROKEN",
    }
    for name, needle in markers.items():
        if needle in blob:
            _ok(f"dist contains {name} marker ({needle!r})")
        else:
            _fail(f"dist MISSING {name} marker ({needle!r})")


# ════════════════════════════════════════════════════════════════════════════════════════════
# STEP 5 — one-screen SUMMARY
# ════════════════════════════════════════════════════════════════════════════════════════════
def step5_summary(exit_nav: Optional[dict], refusal_summary: dict, api_summary: dict) -> None:
    print("\n[5/5] SUMMARY")
    print("=" * 88)

    # ── illustrative ticket schedule table ──
    print("Liquidation-NAV-by-size — ILLUSTRATIVE schedule (hypothetical book on a REAL deep market)")
    if exit_nav and isinstance(exit_nav.get("illustrative"), dict):
        ill = exit_nav["illustrative"]
        print(f"  market={ill.get('market')} ({ill.get('underlying')})  depth={_fmt_usd(ill.get('depth_usd'))}  "
              f"as_of={ill.get('as_of')}")
        hdr = f"  {'ticket':>10s} {'net $':>14s} {'haircut%':>10s} {'tte(d)':>7s}  flag"
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))
        for r in ill.get("schedule", []):
            hc = r.get("haircut_pct")
            print(f"  {_fmt_usd(r.get('ticket_usd')):>10s} {_fmt_usd(r.get('net_proceeds_usd')):>14s} "
                  f"{(f'{hc:.4f}' if _is_finite(hc) else '—'):>10s} "
                  f"{(str(r.get('time_to_exit_days')) if r.get('time_to_exit_days') is not None else '—'):>7s}  "
                  f"{(r.get('flag_reason') or '') if r.get('flagged') else ''}")
    else:
        print("  (illustrative schedule unavailable)")

    # ── live book holes ──
    print("\nOur LIVE book (honest — holes, not fabricated fills):")
    if exit_nav:
        book = exit_nav.get("book") or {}
        print(f"  source={book.get('source')}  market={book.get('market_id')} ({book.get('underlying')})  "
              f"gross={_fmt_usd(book.get('gross_usd'))}  depth={_fmt_usd(exit_nav.get('depth_usd'))}")
        live = exit_nav.get("schedule", [])
        holes = sum(1 for r in live if r.get("flagged"))
        filled = sum(1 for r in live if not r.get("flagged"))
        print(f"  {len(live)} tickets → {filled} priced · {holes} flagged holes "
              f"({'all holes' if holes == len(live) and live else 'mixed'})")
    else:
        print("  (live schedule unavailable)")

    # ── refusal summary ──
    print("\nPublic refusal log:")
    c = refusal_summary.get("counts", {})
    print(f"  ENTRY={c.get('ENTRY')}  REFUSAL={c.get('REFUSAL')}  "
          f"reason-mix={refusal_summary.get('reasons')}")
    print(f"  chain verified: {refusal_summary.get('chain_verified')}  "
          f"head_hash={str(refusal_summary.get('head_hash'))[:16]}…")
    if api_summary:
        print(f"  API: exit-nav rows={api_summary.get('exit_nav_rows')}  "
              f"refusals counts={api_summary.get('refusals_counts')}")

    # ── verdicts ──
    numbers_sane = "YES" if not FAILS else "NO"
    print("\n" + "=" * 88)
    if NOTES:
        print(f"notes: {len(NOTES)} (non-fatal)")
    print(f"NUMBERS SANE: {numbers_sane}")
    print(f"SMOKE TEST: {'PASS' if not FAILS else 'FAIL'}"
          + ("" if not FAILS else f"  ({len(FAILS)} failure(s))"))
    if FAILS:
        print("\nFAILURES:")
        for i, f in enumerate(FAILS, 1):
            print(f"  {i}. {f}")
    print("=" * 88)


def main() -> int:
    print("SPA FLAGSHIP SMOKE TEST — Liquidation-NAV-by-size + Public Refusal-log")
    print(f"repo: {_ROOT}")
    print(f"python: {sys.executable}")

    exit_nav = step1_exit_nav()
    _rows, refusal_summary = step2_refusal_chain()
    api_summary = step3_apis()
    step4_landing_build()
    step5_summary(exit_nav, refusal_summary, api_summary)

    return 0 if not FAILS else 1


if __name__ == "__main__":
    raise SystemExit(main())
