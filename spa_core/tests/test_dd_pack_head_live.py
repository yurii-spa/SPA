"""
test_dd_pack_head_live.py — WS1.2 STALENESS GUARD for the published DD pack (the F1 own-goal test).

THE BUG THIS CATCHES (F1)
-------------------------
docs/DD_PACK.md embeds the flagship reviewer command:

    python3 scripts/verify_spa.py --expect-head <HEAD> data/rates_desk/

The hourly rates-desk paper tick APPENDS to data/rates_desk/decision_log.jsonl, advancing its
head_hash every hour. If nothing regenerates DD_PACK after each append, the embedded <HEAD> goes
stale and a reviewer pasting OUR OWN command gets EXIT 1 — a self-inflicted credibility loss.

THE TEST
--------
It does EXACTLY what a reviewer does:
  1. read the --expect-head literal straight OUT of the committed docs/DD_PACK.md, and
  2. run the REAL scripts/verify_spa.py (zero-dependency, no spa_core) against the LIVE
     data/rates_desk/ — asserting EXIT 0 (the head reproduces).

This is RED on a drifted state (DD_PACK head != current chain head) and GREEN once the refresh hook
(scripts/refresh_published_proof.py, folded into the rates_desk_paper agent) keeps them in lockstep.

A second test proves the refresh hook advances the bundle TOGETHER: after a simulated chain append,
the refresh makes DD_PACK head == decision_log head — and (finding 2026-07-10) it does NOT re-mint a
mirror-head anchor (the public decision_log is a re-based ring buffer, so a mirror anchor breaks on
the next producer write; the ledger is left EMPTY == vacuously valid).

stdlib + pytest only. The live-files test is read-only; the advance-together test is fully hermetic
(its own temp data dir; it NEVER touches the canonical data/ or docs/DD_PACK.md).
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
_REFRESH = _ROOT / "scripts" / "refresh_published_proof.py"
_DD_PACK = _ROOT / "docs" / "DD_PACK.md"
_LIVE_DATA = _ROOT / "data" / "rates_desk"

_HEAD_RE = re.compile(r"--expect-head\s+([0-9a-f]{64})")
_EVENT_TYPE = "rates_desk_decision"
_GENESIS = "0" * 64


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _dd_pack_head(text: str):
    m = _HEAD_RE.search(text)
    return m.group(1) if m else None


# ════════════════════════════════════════════════════════════════════════════════════════════════
# WS1.2 — the staleness guard on the LIVE committed artifacts (the test that would have caught F1)
# ════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not _DD_PACK.exists(), reason="docs/DD_PACK.md not present")
@pytest.mark.skipif(not (_LIVE_DATA / "decision_log.jsonl").exists(),
                    reason="live data/rates_desk/decision_log.jsonl not present")
def test_dd_pack_expect_head_reproduces_against_live_data():
    """The --expect-head literal IN docs/DD_PACK.md must reproduce against LIVE data/rates_desk/ via
    the REAL verify_spa.py → EXIT 0. RED when the published head has drifted (F1); GREEN after the
    refresh hook keeps DD_PACK in lockstep with the chain head. Runs verify_spa.py as a SUBPROCESS
    (exactly as a reviewer would), so the exit code itself is the assertion."""
    def _check():
        head = _dd_pack_head(_DD_PACK.read_text(encoding="utf-8"))
        assert head is not None, "docs/DD_PACK.md must embed a --expect-head <hex> reviewer command"
        proc = subprocess.run(
            [sys.executable, str(_VERIFY), "--expect-head", head, str(_LIVE_DATA)],
            capture_output=True, text=True,
        )
        return head, proc

    head, proc = _check()
    if proc.returncode != 0:
        # The live host runs the hourly com.spa.rates_desk_paper agent, which APPENDS to the chain and
        # then (this fix) refreshes the bundle in the SAME wrapper. If a tick landed in the tiny window
        # between append and refresh while this test ran, the published head is momentarily behind. Run
        # the refresh hook ONCE (exactly what the agent does next) and re-check. If it STILL fails after
        # the refresh, that is the genuine F1 condition (no/broken refresh mechanism) → hard fail.
        subprocess.run([sys.executable, str(_REFRESH), "--quiet"], capture_output=True, text=True)
        head, proc = _check()
    assert proc.returncode == 0, (
        "F1 STALENESS: the --expect-head pinned in docs/DD_PACK.md does NOT reproduce against the live "
        "data/rates_desk/ even after running the refresh hook — a reviewer pasting our own command gets "
        "EXIT 1.\n"
        f"  DD_PACK head: {head}\n"
        f"  verify_spa stdout:\n{proc.stdout}\n  stderr:\n{proc.stderr}"
    )


# ════════════════════════════════════════════════════════════════════════════════════════════════
# the refresh hook advances DD_PACK head == decision_log head == anchor head ALL TOGETHER
# ════════════════════════════════════════════════════════════════════════════════════════════════
def _recompute_entry_hash(seq, ts, payload, prev_hash):
    canonical = json.dumps(
        {"seq": seq, "ts": ts, "event_type": _EVENT_TYPE, "payload": payload, "prev_hash": prev_hash},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _append_decision_row(decision_log: Path, payload: dict, ts: str):
    """Append ONE well-formed decision row to a (possibly empty) hermetic decision_log.jsonl,
    re-deriving the chain envelope (seq/prev_hash/entry_hash) per PROOF_CHAIN_SPEC §5 so the file
    stays a single valid chain. Returns the new head_hash."""
    rows = []
    if decision_log.exists():
        for ln in decision_log.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln:
                rows.append(json.loads(ln))
    seq = len(rows)
    prev = rows[-1]["entry_hash"] if rows else _GENESIS
    entry_hash = _recompute_entry_hash(seq, ts, payload, prev)
    rows.append({"seq": seq, "ts": ts, "entry_hash": entry_hash, "prev_hash": prev, **payload})
    lines = [json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for r in rows]
    decision_log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return entry_hash


def _make_payload(seq: int) -> dict:
    """A minimal but schema-faithful ENTRY decision body (the refresh only needs a verifiable chain;
    DD_PACK degrades unsourced sections to 'data unavailable' honestly when fields are absent)."""
    return {
        "kind": "ENTRY", "approved": True, "reason": "fair_value_ok",
        "as_of": "2026-06-28", "underlying": "susde", "shape": "FIXED_CARRY",
        "net_edge": "0.05", "approved_size_usd": "1000",
        "decomposition": {"baseline": "0.03", "peg_haircut": "0.0", "liquidity_haircut": "0.0",
                          "protocol_haircut": "0.0", "oracle_haircut": "0.0",
                          "funding_flip_haircut": "0.0", "total_haircut": "0.0", "fair_yield": "0.03"},
        "detail": {"quoted_rate": "0.08", "seq_marker": str(seq)},
        "proof_hash": hashlib.sha256(f"proof-{seq}".encode()).hexdigest(),
    }


def _refresh(tmp_data: Path):
    refresh = _load_script("_refresh_under_test", _REFRESH)
    return refresh.refresh(data_dir=tmp_data)


def test_refresh_advances_dd_pack_and_chain_without_reminting_anchors(tmp_path):
    """After a simulated chain-append + the refresh hook, DD_PACK head == decision_log head advance
    together (the mutual-consistency invariant) — AND the refresh does NOT re-mint a mirror-head
    anchor (finding 2026-07-10: the public decision_log is a re-based ring buffer, so a mirror-head
    anchor breaks on the next producer write; the ledger is left EMPTY == vacuously valid). Fully
    hermetic."""
    # hermetic sandbox: <root>/data/rates_desk/ + <root>/docs/ (refresh writes <root>/docs/DD_PACK.md)
    root = tmp_path
    data_dir = root / "data"
    rd = data_dir / "rates_desk"
    rd.mkdir(parents=True)
    (root / "docs").mkdir()
    decision_log = rd / "decision_log.jsonl"
    anchors_path = rd / "anchors.jsonl"
    dd_pack = root / "docs" / "DD_PACK.md"

    # seed an initial 2-row chain and refresh → bundle consistent at head_1
    _append_decision_row(decision_log, _make_payload(0), "2026-06-28T00:00:00+00:00")
    head_1 = _append_decision_row(decision_log, _make_payload(1), "2026-06-28T00:00:01+00:00")
    s1 = _refresh(data_dir)
    assert s1["ok"], s1["errors"]
    assert s1["head"] == head_1
    assert _dd_pack_head(dd_pack.read_text(encoding="utf-8")) == head_1
    # the refresh must NOT mint a mirror-head anchor (unsound over a re-based ring buffer).
    assert s1["anchor_appended"] is False, "refresh must not re-mint mirror-head anchors"
    assert not (anchors_path.exists() and anchors_path.read_text().strip()), \
        "anchor ledger must stay empty (vacuously valid), not carry a soon-to-break mirror anchor"

    # SIMULATE THE TICK: append a NEW decision row → the chain head ADVANCES.
    head_2 = _append_decision_row(decision_log, _make_payload(2), "2026-06-28T01:00:00+00:00")
    assert head_2 != head_1, "appending a row must advance the head"

    # run the refresh hook → the published bundle must catch up to the new head.
    s2 = _refresh(data_dir)
    assert s2["ok"], s2["errors"]
    assert s2["head"] == head_2

    # the invariant: DD_PACK head == decision_log head (both advanced together); still no anchor.
    dd_head = _dd_pack_head(dd_pack.read_text(encoding="utf-8"))
    assert dd_head == head_2, f"DD_PACK head {dd_head} did not advance to {head_2}"
    assert s2["anchor_appended"] is False
    assert not (anchors_path.exists() and anchors_path.read_text().strip())

    # SMOKE: verify_spa --expect-head <DD_PACK head> over the sandbox files → EXIT 0 (the F1 command).
    # An EMPTY anchor ledger is vacuously valid, so the whole bundle still reproduces.
    proc = subprocess.run(
        [sys.executable, str(_VERIFY), "--expect-head", dd_head, str(rd)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"smoke verify_spa failed:\n{proc.stdout}\n{proc.stderr}"


def test_refresh_never_mints_anchor_even_across_ticks(tmp_path):
    """Idempotence + the anti-regression guard: re-running the refresh (with or without a chain
    advance) NEVER grows the anchor ledger past empty. This is what stops the perpetual
    'anchors: broken at index 0' restore-drill failure — the refresh no longer re-mints a mirror
    anchor that goes stale on the next producer write."""
    root = tmp_path
    data_dir = root / "data"
    rd = data_dir / "rates_desk"
    rd.mkdir(parents=True)
    (root / "docs").mkdir()
    decision_log = rd / "decision_log.jsonl"
    anchors_path = rd / "anchors.jsonl"

    def _n_anchors():
        return len(anchors_path.read_text().splitlines()) if anchors_path.exists() else 0

    head = _append_decision_row(decision_log, _make_payload(0), "2026-06-28T00:00:00+00:00")
    s1 = _refresh(data_dir)
    assert s1["ok"] and s1["head"] == head
    assert s1["anchor_appended"] is False
    assert _n_anchors() == 0

    s2 = _refresh(data_dir)  # no chain advance
    assert s2["ok"] and s2["head"] == head
    assert s2["anchor_appended"] is False, "refresh must never append a mirror-head anchor"
    assert _n_anchors() == 0, "anchor ledger must stay empty across refreshes"


def test_refresh_fail_closed_on_broken_chain(tmp_path):
    """fail-CLOSED: a broken/corrupt decision chain refreshes NOTHING (no DD_PACK, no anchor) and
    reports the failure — we never publish artifacts over an unverified head."""
    root = tmp_path
    data_dir = root / "data"
    rd = data_dir / "rates_desk"
    rd.mkdir(parents=True)
    (root / "docs").mkdir()
    # a corrupt (non-chain) decision_log
    (rd / "decision_log.jsonl").write_text('{"seq": 5, "garbage": true}\n', encoding="utf-8")
    s = _refresh(data_dir)
    assert s["ok"] is False
    assert s["errors"], "a broken chain must report an error"
    assert not (root / "docs" / "DD_PACK.md").exists(), "must NOT publish DD_PACK over a broken chain"
