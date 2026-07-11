"""
test_verify_spa_standalone.py — the quality bar for WORKSTREAM A "Proof-of-Risk".

A skeptical Gauntlet/Credora reviewer downloads ONLY scripts/verify_spa.py + the public JSON files
and reaches our EXACT verdicts, finding nothing fabricated/unreproducible. These tests pin that:

  • the standalone verifier (imported as a plain module, NOT via spa_core) reproduces the published
    decision-chain head + every exit-NAV proof_hash on the REAL published files;
  • one mutated byte → correct broken_at; a forged unlinked row → rejected;
  • the cross-eviction anchor matches the producer/decision head; append-only + monotonic enforced;
  • the portfolio exit-NAV schedule is per-market-depth (NEVER aggregated) + fail-CLOSED holes;
  • the API `reproduce` block matches the verifier; the server verdict == verify_spa.py.

The verifier is loaded by FILE PATH with a CLEAN module namespace (no spa_core) to prove it has zero
repo coupling — exactly how a stranger would run it. PURE / no network / no live-data mutation.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_VERIFY = _ROOT / "scripts" / "verify_spa.py"
_DATA = _ROOT / "data" / "rates_desk"
_DECISION_LOG = _DATA / "decision_log.jsonl"
_EXIT_NAV = _DATA / "exit_nav.json"
_ANCHORS = _DATA / "anchors.jsonl"


def _load_verifier():
    """Import scripts/verify_spa.py by path with a private module name — proves NO spa_core coupling.
    (If verify_spa.py imported spa_core, this would still work, but the dedicated clean-room test
    below asserts the file contains no such import.)"""
    spec = importlib.util.spec_from_file_location("_verify_spa_under_test", _VERIFY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


V = _load_verifier()


def _require_live_rates_desk():
    """WS4 hermeticity: these tests reproduce verdicts over the LIVE published
    rates_desk proof files. On a clean checkout with an empty data/ those files
    are absent — skip (this is a published-artifact reproduction guard, not a
    hermetic unit test). The synthetic-fixture tests in this module do NOT call
    this and keep running on empty data/."""
    if not _DECISION_LOG.exists():
        pytest.skip(f"live-data artifact absent (clean checkout): {_DECISION_LOG}")


def _read_jsonl(path: Path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# clean-room guarantees: the verifier has ZERO spa_core dependency
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_verifier_does_not_import_spa_core():
    """The 'don't trust us' artifact must be runnable with NO repo on sys.path — so its source must
    never import spa_core (or any third-party dep)."""
    src = _VERIFY.read_text(encoding="utf-8")
    assert "import spa_core" not in src
    assert "from spa_core" not in src


def test_verifier_only_uses_stdlib():
    """Every top-level import in verify_spa.py must be stdlib (zero-dependency contract)."""
    import ast
    tree = ast.parse(_VERIFY.read_text(encoding="utf-8"))
    stdlib_ok = {"argparse", "hashlib", "json", "sys", "pathlib", "typing", "__future__",
                 "datetime",   # datetime: stdlib, used by the WS6 --check-fundability date math
                 "decimal"}    # decimal: stdlib, used by the Q2-2 --replay verdict re-derivation
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                assert n.name.split(".")[0] in stdlib_ok, f"non-stdlib import: {n.name}"
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] in stdlib_ok, f"non-stdlib: {node.module}"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (A) decision chain — reproduces the REAL published head
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_reproduces_published_decision_head():
    _require_live_rates_desk()
    """On the REAL published decision_log.jsonl the verifier reproduces a valid chain + the head."""
    rows = _read_jsonl(_DECISION_LOG)
    res = V.verify_decision_chain(rows)
    assert res["valid"] is True
    assert res["broken_at"] is None
    assert res["head_hash"] == rows[-1]["entry_hash"]
    assert res["length"] == len(rows)


def test_one_mutated_byte_breaks_at_correct_row():
    _require_live_rates_desk()
    """Flip a single byte inside a hashed field of a middle row → verifier rejects at THAT row."""
    rows = _read_jsonl(_DECISION_LOG)
    idx = len(rows) // 2
    rows[idx] = dict(rows[idx])
    # mutate a hashed payload value (reason) while keeping the stored entry_hash → must diverge.
    rows[idx]["reason"] = (rows[idx].get("reason") or "x") + "_TAMPERED"
    res = V.verify_decision_chain(rows)
    assert res["valid"] is False
    assert res["broken_at"] == idx


def test_forged_unlinked_row_rejected():
    _require_live_rates_desk()
    """A fabricated row appended with a bogus prev_hash (a forged seq) → rejected at that row."""
    rows = _read_jsonl(_DECISION_LOG)
    forged = dict(rows[-1])
    forged["seq"] = len(rows)
    forged["prev_hash"] = "f" * 64  # not the real previous head → linkage break
    forged["entry_hash"] = "e" * 64
    rows.append(forged)
    res = V.verify_decision_chain(rows)
    assert res["valid"] is False
    assert res["broken_at"] == len(rows) - 1


def test_empty_chain_vacuously_valid():
    res = V.verify_decision_chain([])
    assert res["valid"] is True and res["head_hash"] is None and res["length"] == 0


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (B) exit-NAV proof hashes — reproduces every published proof_hash across all 3 sections
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_reproduces_all_exit_nav_proof_hashes():
    _require_live_rates_desk()
    """Every proof_hash in live + illustrative + portfolio reproduces from the row's published inputs."""
    doc = json.loads(_EXIT_NAV.read_text(encoding="utf-8"))
    res = V.verify_exit_nav(doc)
    assert res["valid"] is True, res["first_bad"]
    assert res["n_rows"] == res["n_verified"]
    assert res["n_rows"] >= 10  # at least the live ladder; with portfolio many more


def test_exit_nav_mutated_input_breaks_proof():
    _require_live_rates_desk()
    """Changing a published input (depth_usd) without recomputing proof_hash → mismatch detected."""
    doc = json.loads(_EXIT_NAV.read_text(encoding="utf-8"))
    # find any row with a proof_hash and a depth_usd
    target = None
    for _, row in V._iter_schedule_rows(doc):
        if row.get("depth_usd") is not None:
            target = row
            break
    assert target is not None
    target["depth_usd"] = (target["depth_usd"] or 0) + 1.0
    res = V.verify_exit_nav(doc)
    assert res["valid"] is False
    assert "proof_hash mismatch" in (res["first_bad"] or "")


def test_exit_nav_forged_output_detected():
    _require_live_rates_desk()
    """RED-TEAM FAIL #2: forging a published OUTPUT (net_proceeds/haircut/flagged) on a real row,
    keeping the stored proof_hash → the verifier (now hashing outputs too) detects it. OLD behavior
    (inputs-only hash) PASSED this forgery; the fix MUST reject it."""
    doc = json.loads(_EXIT_NAV.read_text(encoding="utf-8"))
    # forge a flagged hole into a fat fill (the exact red-team attack: 9,999,999 net, haircut 0.0001)
    forged = None
    for _, row in V._iter_schedule_rows(doc):
        if row.get("flagged") and row.get("net_proceeds_usd") is None:
            row["net_proceeds_usd"] = 9_999_999.0
            row["haircut_pct"] = 0.0001
            row["flagged"] = False
            row["flag_reason"] = None
            forged = row
            break
    assert forged is not None, "expected at least one flagged hole row to forge"
    res = V.verify_exit_nav(doc)
    assert res["valid"] is False
    assert "proof_hash mismatch" in (res["first_bad"] or "")


def test_exit_nav_input_only_recompute_no_longer_passes():
    _require_live_rates_desk()
    """Editing an input AND recomputing the OLD inputs-only hash must NOT pass — outputs + prev_hash
    are now in the hashed object, so the inputs-only digest is wrong."""
    import hashlib
    doc = json.loads(_EXIT_NAV.read_text(encoding="utf-8"))
    target = None
    for _, row in V._iter_schedule_rows(doc):
        if row.get("depth_usd") is not None and not row.get("flagged"):
            target = row
            break
    assert target is not None
    target["depth_usd"] = target["depth_usd"] * 1.5
    # attacker recomputes the OLD inputs-only recipe
    ri = {k: target[k] for k in V.EXIT_NAV_ROW_INPUT_KEYS}
    blob = json.dumps(ri, sort_keys=True, separators=(",", ":"), default=str)
    target["proof_hash"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    res = V.verify_exit_nav(doc)
    assert res["valid"] is False  # inputs-only hash no longer satisfies the verifier


def test_exit_nav_reordered_row_caught_by_chain():
    _require_live_rates_desk()
    """A reordered (or dropped) schedule row breaks the per-schedule prev_hash chain → caught."""
    doc = json.loads(_EXIT_NAV.read_text(encoding="utf-8"))
    sched = doc.get("schedule") or []
    assert len(sched) >= 2
    sched[0], sched[1] = sched[1], sched[0]
    res = V.verify_exit_nav(doc)
    assert res["valid"] is False
    assert "chain broken" in (res["first_bad"] or "")


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (C) anchors — append-only, monotonic, head-consistent
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_anchor_matches_producer_head():
    """On the REAL published anchors the verifier finds NO fabricated checkpoint
    against the live decision chain.

    WS4 hermeticity fix: the live chain is mutated forward continuously by the
    rates_desk_paper agent, so the latest anchor legitimately lags the current
    head (chain grows between anchor events). In that transient state
    ``latest_matches_head`` is ``None`` (no anchor checkpoints the CURRENT
    length) — a benign, non-fabricated state, NOT False. The invariant that
    actually matters and must hold over live mutable data is ``valid is True``
    (every present anchor reproduces its checkpoint; none is forged). Forged-head
    detection is covered deterministically by ``test_anchor_wrong_head_rejected``
    with a synthetic fixture, so this live test no longer flakes on data drift.
    """
    _require_live_rates_desk()
    rows = _read_jsonl(_DECISION_LOG)
    chain = V.verify_decision_chain(rows)
    anchors = _read_jsonl(_ANCHORS) if _ANCHORS.exists() else []
    res = V.verify_anchors(anchors, chain["head_hash"], chain["length"], rows)
    assert res["valid"] is True, res
    if anchors:
        # True when the chain was just anchored; None while it has advanced past
        # the last anchor. Both are honest, non-fabricated states; False (a
        # forged checkpoint at the current length) is the only failure.
        assert res["latest_matches_head"] in (True, None), res


def test_anchor_wrong_head_rejected():
    _require_live_rates_desk()
    """An anchor that checkpoints the current length but with a WRONG head → rejected."""
    rows = _read_jsonl(_DECISION_LOG)
    chain = V.verify_decision_chain(rows)
    forged = [{"event_type": "rates_desk_anchor", "seq": 0, "ts": "2026-06-28T00:00:00+00:00",
               "head_hash": "a" * 64, "chain_length": chain["length"]}]
    res = V.verify_anchors(forged, chain["head_hash"], chain["length"], rows)
    assert res["valid"] is False
    assert res["latest_matches_head"] is False


def test_fabricated_historical_anchor_rejected():
    _require_live_rates_desk()
    """WEAKNESS #3: a fabricated HISTORICAL anchor (wrong head at an OLDER in-window length) must be
    REJECTED — not silently passed with latest_matches_head=None. Because the public mirror is a
    single-genesis re-based chain, the head at length K == rows[K-1].entry_hash, so an in-window
    historical anchor IS independently checkable."""
    rows = _read_jsonl(_DECISION_LOG)
    chain = V.verify_decision_chain(rows)
    assert chain["length"] >= 110
    fab = {"event_type": "rates_desk_anchor", "seq": 0, "ts": "2026-06-27T00:00:00+00:00",
           "head_hash": "a" * 64, "chain_length": 100}  # WRONG head at length 100
    real = {"event_type": "rates_desk_anchor", "seq": 1, "ts": "2026-06-28T00:00:00+00:00",
            "head_hash": chain["head_hash"], "chain_length": chain["length"]}
    res = V.verify_anchors([fab, real], chain["head_hash"], chain["length"], rows)
    assert res["valid"] is False, "fabricated historical anchor must be rejected, not silently passed"
    assert res["broken_at"] == 0


def test_genuine_historical_anchor_verified_in_window():
    _require_live_rates_desk()
    """A GENUINE historical anchor (true head at an older in-window length) passes AND is counted as
    verified_in_window (the honesty fix verifies it, not just the current head)."""
    rows = _read_jsonl(_DECISION_LOG)
    chain = V.verify_decision_chain(rows)
    assert chain["length"] >= 110
    true_head_100 = rows[99]["entry_hash"]
    good = {"event_type": "rates_desk_anchor", "seq": 0, "ts": "2026-06-27T00:00:00+00:00",
            "head_hash": true_head_100, "chain_length": 100}
    real = {"event_type": "rates_desk_anchor", "seq": 1, "ts": "2026-06-28T00:00:00+00:00",
            "head_hash": chain["head_hash"], "chain_length": chain["length"]}
    res = V.verify_anchors([good, real], chain["head_hash"], chain["length"], rows)
    assert res["valid"] is True
    assert res["n_historical_verified"] == 1
    assert res["latest_matches_head"] is True


def test_evicted_or_forward_anchor_marked_uncheckable_not_passed():
    _require_live_rates_desk()
    """An anchor claiming MORE rows than the public chain (or a prefix not in-window) cannot be
    re-derived from public files → counted UNCHECKABLE (honest), the ledger still valid but the count
    flags it rests on the producer ledger."""
    rows = _read_jsonl(_DECISION_LOG)
    chain = V.verify_decision_chain(rows)
    fwd = {"event_type": "rates_desk_anchor", "seq": 0, "ts": "2026-06-28T00:00:00+00:00",
           "head_hash": "b" * 64, "chain_length": chain["length"] + 5_000}  # claims more rows
    res = V.verify_anchors([fwd], chain["head_hash"], chain["length"], rows)
    assert res["valid"] is True
    assert res["n_uncheckable"] == 1


def test_anchor_non_monotonic_chain_length_rejected():
    """chain_length must never decrease across anchors (append-only producer ledger only grows)."""
    forged = [
        {"event_type": "rates_desk_anchor", "seq": 0, "ts": "t0", "head_hash": "a" * 64,
         "chain_length": 500},
        {"event_type": "rates_desk_anchor", "seq": 1, "ts": "t1", "head_hash": "b" * 64,
         "chain_length": 400},  # SHORTER → invalid
    ]
    res = V.verify_anchors(forged, None, None)
    assert res["valid"] is False and res["broken_at"] == 1


def test_anchor_non_contiguous_seq_rejected():
    forged = [
        {"event_type": "rates_desk_anchor", "seq": 0, "ts": "t0", "head_hash": "a" * 64,
         "chain_length": 1},
        {"event_type": "rates_desk_anchor", "seq": 5, "ts": "t1", "head_hash": "b" * 64,
         "chain_length": 2},  # gap → invalid
    ]
    res = V.verify_anchors(forged, None, None)
    assert res["valid"] is False and res["broken_at"] == 1


def test_anchor_empty_vacuously_valid():
    res = V.verify_anchors([], "deadbeef" * 8, 1)
    assert res["valid"] is True and res["length"] == 0


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# end-to-end run() over the real files — exit 0 + expected head
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_run_over_real_files_ok_with_expected_head():
    _require_live_rates_desk()
    """The full run() over the real directory reproduces, with --expect-head matching the published head."""
    rows = _read_jsonl(_DECISION_LOG)
    expected = rows[-1]["entry_hash"]
    report = V.run([str(_DATA)], expect_head=expected)
    assert report["ok"] is True, report["errors"]
    assert report["decision_chain"]["head_hash"] == expected
    assert report["exit_nav"]["valid"] is True
    assert report["anchors"]["valid"] is True


def test_run_with_wrong_expected_head_fails():
    _require_live_rates_desk()
    report = V.run([str(_DATA)], expect_head="0" * 64)
    assert report["ok"] is False
    assert any("head mismatch" in e for e in report["errors"])


def test_run_no_files_fails_closed():
    report = V.run([str(_ROOT / "nonexistent_dir_xyz")])
    assert report["ok"] is False
    assert report["errors"]


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# Q2-2 --replay: re-DERIVE each verdict from its own published numbers (hermetic synthetic fixtures)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _clean_verdict():
    # approved book with a positive published edge + a self-consistent decomposition
    return {"approved": True, "reason": "", "net_edge": "0.30",
            "decomposition": {"baseline": "0.05", "total_haircut": "0.01", "fair_yield": "0.04",
                              "peg_haircut": "0.005", "protocol_haircut": "0.005"}}


def test_replay_clean_verdicts_pass():
    rep = V.verify_decision_replay([_clean_verdict(), _clean_verdict()])
    assert rep["failed"] == 0 and rep["passed"] == 2
    assert rep["invariants"]["d1_identity"] == 2
    assert rep["invariants"]["d3_approve_edge"] == 2


def test_replay_empty_is_vacuously_ok():
    rep = V.verify_decision_replay([])
    assert rep["failed"] == 0 and rep["checked"] == 0


def test_replay_catches_broken_fair_value_identity():
    # D1: fair_yield no longer equals baseline − total_haircut → tamper caught
    bad = _clean_verdict()
    bad["decomposition"]["fair_yield"] = "0.99"
    rep = V.verify_decision_replay([bad])
    assert rep["failed"] == 1
    assert rep["first_bad"]["check"] == "D1_identity"


def test_replay_catches_approved_nonpositive_edge():
    # D3: a flipped `approved` on a non-positive-edge book (refusal-first violation)
    bad = _clean_verdict()
    bad["net_edge"] = "-0.5"
    rep = V.verify_decision_replay([bad])
    assert rep["failed"] == 1
    assert rep["first_bad"]["check"] == "D3_approve_edge"


def test_replay_catches_refusal_without_reason():
    # D4: every refusal must carry a reason
    bad = {"approved": False, "reason": "", "net_edge": "0.2"}
    rep = V.verify_decision_replay([bad])
    assert rep["failed"] == 1
    assert rep["first_bad"]["check"] == "D4_refuse_reason"


def test_replay_catches_negative_haircut():
    # D2: a fabricated negative haircut (a "credit" inflating fair value)
    bad = _clean_verdict()
    bad["decomposition"]["peg_haircut"] = "-0.02"
    rep = V.verify_decision_replay([bad])
    assert rep["failed"] == 1
    assert rep["first_bad"]["check"] == "D2_nonneg"


def test_replay_over_live_data_all_verdicts_follow_from_inputs():
    # every REAL published verdict must re-derive from its own published numbers
    _require_live_rates_desk()
    rows = _read_jsonl(_DECISION_LOG)
    rep = V.verify_decision_replay(rows)
    assert rep["failed"] == 0, rep["first_bad"]
    assert rep["checked"] == len(rows)


def test_replay_flag_wired_into_run_and_fails_closed_on_tamper(tmp_path):
    # a tampered decision_log fed through the full run(..., replay=True) fails CLOSED
    bad = _clean_verdict()
    bad["net_edge"] = "-1"          # approved but negative edge
    # minimal valid chain fields so the chain-walk doesn't short-circuit before replay runs
    bad.update({"seq": 0, "prev_hash": "0" * 64})
    bad["entry_hash"] = V.recompute_entry_hash(bad)
    log = tmp_path / "decision_log.jsonl"
    log.write_text(json.dumps(bad) + "\n", encoding="utf-8")
    report = V.run([str(log)], replay=True)
    assert report["decision_replay"]["failed"] == 1
    assert any("decision_replay" in e for e in report["errors"])
    assert report["ok"] is False


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# Q2-10 --offline: verify a FROZEN checksummed snapshot against its SNAPSHOT_MANIFEST.json (hermetic)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _make_snapshot(tmp_path):
    import hashlib
    d = tmp_path / "snap"
    d.mkdir()
    payload = b'{"seq":0,"marker":"x"}\n'
    (d / "decision_log.jsonl").write_bytes(payload)
    manifest = {
        "expected_decision_head": "dead" * 16,
        "expected_surfaces": ["A"],
        "files": [{"arcname": "decision_log.jsonl", "surface": "A",
                   "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}],
    }
    (d / "SNAPSHOT_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d


def test_snapshot_integrity_clean(tmp_path):
    integ = V.verify_snapshot_manifest(_make_snapshot(tmp_path))
    assert integ["manifest_present"] is True
    assert integ["matched"] == 1 and integ["mismatched"] == 0
    assert integ["expected_surfaces"] == ["A"]


def test_snapshot_integrity_catches_tampered_bytes(tmp_path):
    d = _make_snapshot(tmp_path)
    f = d / "decision_log.jsonl"
    f.write_bytes(f.read_bytes() + b"tamper")   # breaks sha256 + size
    integ = V.verify_snapshot_manifest(d)
    assert integ["mismatched"] == 1
    assert integ["first_bad"]["reason"] == "sha256/size mismatch"


def test_snapshot_integrity_catches_missing_pinned_file(tmp_path):
    d = _make_snapshot(tmp_path)
    (d / "decision_log.jsonl").unlink()
    integ = V.verify_snapshot_manifest(d)
    assert integ["mismatched"] == 1
    assert integ["first_bad"]["reason"] == "pinned file missing"


def test_snapshot_integrity_no_manifest_fails_closed(tmp_path):
    integ = V.verify_snapshot_manifest(tmp_path)
    assert integ["manifest_present"] is False


def test_offline_flag_fails_closed_on_tampered_snapshot(tmp_path):
    d = _make_snapshot(tmp_path)
    f = d / "decision_log.jsonl"
    f.write_bytes(f.read_bytes() + b"tamper")
    rc = V.main([str(d), "--offline", "--json"])
    assert rc == 1   # fail-CLOSED via exit code


def test_offline_over_live_snapshot_if_present():
    # if the real frozen DD snapshot exists, every pinned file must be byte-identical
    snap = _ROOT / "data" / "dd_snapshot"
    if not (snap / "SNAPSHOT_MANIFEST.json").exists():
        pytest.skip("live DD snapshot absent (clean checkout)")
    integ = V.verify_snapshot_manifest(snap)
    assert integ["mismatched"] == 0, integ["first_bad"]
    assert integ["matched"] == integ["checked"] and integ["checked"] > 0


# --- Regression (2026-07-11): whole-`data/` discovery must not adopt frozen-copy chains ----------
def test_under_frozen_copy_excludes_snapshot_and_backup_subdirs(tmp_path):
    """`verify_spa data/` walks recursively; a frozen dd_snapshot/ copy (a checksummed daily freeze,
    replayed only via --offline) sorts BEFORE rates_desk/ and would hand surface [A] a STALE head,
    breaking --expect-head. The discovery must skip snapshot/backup SUBDIRS — but NOT when the
    snapshot IS the explicit target (root), so --offline still works."""
    root = tmp_path
    # frozen-copy subdirs under the walked root → excluded
    assert V._under_frozen_copy(root / "dd_snapshot" / "decision_log.jsonl", root) is True
    assert V._under_frozen_copy(root / "backups" / "spa.jsonl", root) is True
    # an intermediate dir archived with a .orphaned suffix is also skipped
    assert V._under_frozen_copy(root / "rates_desk.orphaned" / "decision_log.jsonl", root) is True
    # the live surface → kept
    assert V._under_frozen_copy(root / "rates_desk" / "decision_log.jsonl", root) is False
    # --offline: when root IS the snapshot dir, nothing between root and file matches → still discovered
    snap = root / "dd_snapshot"
    assert V._under_frozen_copy(snap / "decision_log.jsonl", snap) is False
