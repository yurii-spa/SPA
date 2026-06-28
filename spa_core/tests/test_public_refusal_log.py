"""
Tests for the PUBLIC REFUSAL-LOG surface — the human-readable, independently-verifiable layer over
the tamper-evident rates-desk decision chain.

Covers:
  • refusal_explain.explain() — PURE, deterministic, TOTAL over every KillReason the policy emits,
    EN+RU for each, numbers pulled from the row's OWN hashed decomposition, LLM-FORBIDDEN.
  • docs/PROOF_CHAIN_SPEC.md — third-party-verifiable: recompute a stored entry_hash from the raw
    JSONL following ONLY the published spec → matches.
  • tamper-evidence — flip a byte → verified:false + correct broken_at; clean → verified:true + head.
  • GET /api/rates-desk/refusals — shape, graceful missing log, chain badge, secret-key redaction,
    advisory size labeling.

Run:
    python3 -m pytest spa_core/tests/test_public_refusal_log.py -p no:randomly -q
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in [str(_SPA_CORE), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from spa_core.audit import hash_chain  # noqa: E402
from spa_core.strategy_lab.rates_desk import refusal_explain  # noqa: E402
from spa_core.strategy_lab.rates_desk.contracts import KillReason  # noqa: E402

EVENT_TYPE = "rates_desk_decision"
_REAL_LOG = _PROJECT_ROOT / "data" / "rates_desk" / "decision_log.jsonl"


# ── Fixtures / helpers ───────────────────────────────────────────────────────────
def _decomp(total: str = "0.1647377866666666666666666667") -> dict:
    return {
        "underlying": "eeth", "as_of": "2026-06-25",
        "baseline": "0.029",
        "peg_haircut": "0.024071120",
        "funding_flip_haircut": "0.06",
        "oracle_haircut": "0.006666666666666666666666666668",
        "liquidity_haircut": "0.06",
        "protocol_haircut": "0.014",
        "total_haircut": total,
        "fair_yield": "-0.1357377866666666666666666667",
    }


def _payload(seq: int, *, reason: str, underlying: str = "eeth", approved: bool = False) -> dict:
    """A representative decision payload (the hash-covered body) for one reason token."""
    return {
        "kind": "ENTRY" if approved else "REFUSAL",
        "approved": approved,
        "reason": reason,
        "as_of": "2026-06-25",
        "underlying": underlying,
        "shape": "fixed_carry",
        "net_edge": "0.05" if approved else "-0.1357377866666666666666666667",
        "approved_size_usd": "10000" if approved else "0",
        "decomposition": _decomp(),
        "detail": {"max_total_haircut": "0.12", "note": "tail-comp veto"},
        "proof_hash": f"deadbeef{seq:04d}",
    }


def _write_chain(path: Path, payloads: list) -> list:
    """Write a genuine, internally-consistent hash-chained decision_log.jsonl; return mirror rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    prev = hash_chain.GENESIS_PREV
    for seq, pl in enumerate(payloads):
        ts = "2026-06-25T00:00:00+00:00"
        eh = hash_chain.compute_entry_hash(seq, ts, EVENT_TYPE, pl, prev)
        rows.append({"seq": seq, "ts": ts, "entry_hash": eh, "prev_hash": prev, **pl})
        prev = eh
    path.write_text(
        "\n".join(json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                  for r in rows) + "\n",
        encoding="utf-8",
    )
    return rows


# ── 1. explain() is PURE + TOTAL ─────────────────────────────────────────────────
def test_explain_is_pure_and_total():
    """explain() returns EN+RU for EVERY reason token the policy enum can emit — no KeyError, no
    missing language — and is deterministic (same row → identical output twice)."""
    # The audited dict is proven total over the enum.
    refusal_explain.assert_total()

    for reason in KillReason:
        tok = reason.value
        row = _payload(0, reason=tok, approved=(tok == "none"))
        out_a = refusal_explain.explain(row)
        out_b = refusal_explain.explain(row)
        # both languages present + non-empty for every token
        assert out_a["plain_en"], f"empty EN for {tok}"
        assert out_a["plain_ru"], f"empty RU for {tok}"
        assert out_a["headline"], f"empty headline for {tok}"
        assert out_a["structural_reason"] == tok
        # the underlying is interpolated into both languages
        assert "eeth" in out_a["plain_en"]
        assert "eeth" in out_a["plain_ru"]
        # determinism
        assert out_a == out_b, f"non-deterministic explain for {tok}"
        # never the unmapped fallback for a real enum token
        assert out_a["headline"] != refusal_explain._UNMAPPED_HEADLINE


def test_explain_drivers_trace_to_hashed_numbers():
    """drivers pull the ACTUAL numbers from the row's decomposition, verbatim + as display pct, and
    the EN narrative cites the real total ('16.47%') vs the cap ('12.00%')."""
    row = _payload(0, reason="tail_veto")
    out = refusal_explain.explain(row)
    by_field = {d["field"]: d for d in out["drivers"]}
    # verbatim decimal preserved exactly (hash-anchored)
    assert by_field["peg_haircut"]["decimal"] == "0.024071120"
    assert by_field["peg_haircut"]["pct"] == "2.41%"
    assert by_field["funding_flip_haircut"]["pct"] == "6.00%"
    assert by_field["total_haircut"]["pct"] == "16.47%"
    # the human sentence cites the real numbers + the cap from detail
    assert "16.47%" in out["plain_en"]
    assert "12.00% cap" in out["plain_en"]
    assert "peg 2.41%" in out["plain_en"]


def test_explain_unmapped_fails_closed():
    """A row with a reason token NOT in the audited map degrades to an explicit unmapped/unverifiable
    explanation — NEVER a fabricated benign one. (Defends against a future/unknown producer.)"""
    row = _payload(0, reason="some_unknown_future_token")
    out = refusal_explain.explain(row)
    assert out["headline"] == refusal_explain._UNMAPPED_HEADLINE
    assert "unverifiable" in out["plain_en"].lower()
    assert "eeth" in out["plain_en"]


# ── 2. LLM-FORBIDDEN ──────────────────────────────────────────────────────────────
def test_explain_no_llm():
    """The module carries the # LLM_FORBIDDEN marker and imports NO generative/LLM SDK (reuses the
    lint_llm_forbidden pattern: scan source lines for forbidden import statements)."""
    src_path = Path(refusal_explain.__file__)
    text = src_path.read_text(encoding="utf-8")
    assert "# LLM_FORBIDDEN" in text, "missing LLM_FORBIDDEN marker"

    # Reuse the canonical lint patterns over THIS module's source.
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
    import lint_llm_forbidden as lint  # noqa: E402
    violations = lint.scan_file(str(src_path), lint.FORBIDDEN_PATTERNS)
    assert violations == [], f"forbidden LLM imports found: {violations}"


# ── 3. spec is third-party-reproducible ──────────────────────────────────────────
def _recompute_entry_hash_per_spec(row: dict) -> str:
    """Recompute entry_hash following ONLY docs/PROOF_CHAIN_SPEC.md §3 — independent of our code:
    canonical JSON (sort_keys, compact separators, ensure_ascii=False) over
    {seq, ts, event_type, payload, prev_hash} with payload = row minus the four envelope keys and
    the constant event_type='rates_desk_decision'."""
    envelope = ("seq", "ts", "entry_hash", "prev_hash")
    payload = {k: v for k, v in row.items() if k not in envelope}
    canonical = json.dumps(
        {
            "seq": row["seq"],
            "ts": row["ts"],
            "event_type": "rates_desk_decision",
            "payload": payload,
            "prev_hash": row["prev_hash"],
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_proof_chain_spec_reproducible(tmp_path):
    """Follow the published spec to recompute an entry_hash straight from the raw JSONL → must match
    the stored hash. Proves the spec is correct + a third party can verify without our code.

    Prefers the REAL committed decision_log.jsonl (the actual public artifact); falls back to a
    hermetic fixture so the test is self-contained if the live log is absent."""
    spec = _PROJECT_ROOT / "docs" / "PROOF_CHAIN_SPEC.md"
    assert spec.exists(), "PROOF_CHAIN_SPEC.md missing"

    if _REAL_LOG.exists():
        line = next(ln for ln in _REAL_LOG.read_text(encoding="utf-8").splitlines() if ln.strip())
        row = json.loads(line)
    else:
        log = tmp_path / "decision_log.jsonl"
        rows = _write_chain(log, [_payload(0, reason="tail_veto")])
        row = rows[0]

    recomputed = _recompute_entry_hash_per_spec(row)
    assert recomputed == row["entry_hash"], "spec recompute does not match stored entry_hash"


# ── 4. tamper-evidence (via the server's _verify_decision_log) ───────────────────
def test_chain_verifies_clean(tmp_path):
    """Untouched fixture → verified:true + head_hash = last row's entry_hash."""
    from spa_core.api.routers.rates_desk import _verify_decision_log
    log = tmp_path / "decision_log.jsonl"
    rows = _write_chain(log, [
        _payload(0, reason="tail_veto", underlying="eeth"),
        _payload(1, reason="tail_veto", underlying="susde"),
        _payload(2, reason="none", underlying="ptusdc", approved=True),
    ])
    loaded = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    res = _verify_decision_log(loaded)
    assert res["valid"] is True
    assert res["broken_at"] is None
    assert res["head_hash"] == rows[-1]["entry_hash"]
    assert res["length"] == 3


def test_chain_tamper_detected(tmp_path):
    """Flip one byte in a HISTORICAL decomposition (keeping its stored hash) → verified:false +
    broken_at points at that row."""
    from spa_core.api.routers.rates_desk import _verify_decision_log
    log = tmp_path / "decision_log.jsonl"
    _write_chain(log, [
        _payload(0, reason="tail_veto", underlying="eeth"),
        _payload(1, reason="tail_veto", underlying="susde"),
        _payload(2, reason="none", underlying="ptusdc", approved=True),
    ])
    lines = log.read_text(encoding="utf-8").splitlines()
    row1 = json.loads(lines[1])
    # mutate a single haircut byte inside the hashed decomposition; keep the stored entry_hash.
    row1["decomposition"]["peg_haircut"] = "0.999999999"
    lines[1] = json.dumps(row1, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    loaded = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    res = _verify_decision_log(loaded)
    assert res["valid"] is False
    assert res["broken_at"] == 1


# ── 4b. single-coherent-chain / multi-genesis / forgery / API==spec / regen / interlock ──────────
# These tests target the EXACT adversarial findings: the published file must verify as ONE chain
# (spec §5), a multi-genesis concatenation must FAIL, a forged unlinked row must be REJECTED, the API
# verdict must EQUAL the spec recipe byte-for-byte, the regenerated canonical file must verify, and a
# sandbox run must NOT write the canonical mirror. They FAIL on the old behavior, PASS on the fix.

ENVELOPE = ("seq", "ts", "entry_hash", "prev_hash")


def _spec_verify_chain(rows: list) -> dict:
    """INDEPENDENT re-implementation of docs/PROOF_CHAIN_SPEC.md §5 — uses ONLY the published recipe,
    not our code: seq==idx, prev_hash linkage (genesis '0'*64), self-recompute; head=last entry_hash."""
    expected_prev = "0" * 64
    for idx, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("seq") != idx:
            return {"valid": False, "broken_at": idx, "head_hash": None}
        if row.get("prev_hash") != expected_prev:
            return {"valid": False, "broken_at": idx, "head_hash": None}
        if _recompute_entry_hash_per_spec(row) != row.get("entry_hash"):
            return {"valid": False, "broken_at": idx, "head_hash": None}
        expected_prev = row["entry_hash"]
    return {"valid": True, "broken_at": None,
            "head_hash": rows[-1]["entry_hash"] if rows else None}


def _multi_genesis_rows() -> list:
    """A REAL-SHAPED corrupt mirror: two independent runs' chains concatenated (two genesis rows,
    seq restarts at 0, broken prev-linkage at the boundary) — the exact historical decision_log shape."""
    # run A: seq 0,1 linked from genesis
    runA = _write_chain_rows([_payload(0, reason="tail_veto", underlying="eeth"),
                              _payload(1, reason="tail_veto", underlying="susde")])
    # run B: its OWN genesis seq 0,1 (independent chain) — concatenated after run A
    runB = _write_chain_rows([_payload(0, reason="tail_veto", underlying="usde"),
                              _payload(1, reason="none", underlying="ptusdc", approved=True)])
    return runA + runB


def _write_chain_rows(payloads: list) -> list:
    """Build genuine internally-linked rows (single genesis) WITHOUT touching disk; return mirror rows."""
    rows = []
    prev = hash_chain.GENESIS_PREV
    for seq, pl in enumerate(payloads):
        ts = "2026-06-25T00:00:00+00:00"
        eh = hash_chain.compute_entry_hash(seq, ts, EVENT_TYPE, pl, prev)
        rows.append({"seq": seq, "ts": ts, "entry_hash": eh, "prev_hash": prev, **pl})
        prev = eh
    return rows


def test_multi_genesis_concatenation_rejected():
    """The real-shaped corrupt file (many runs' genesis chains concatenated) must FAIL verification:
    verified:false at the SECOND genesis boundary. The old intrinsic-only verifier passed this."""
    from spa_core.api.routers.rates_desk import _verify_decision_log
    rows = _multi_genesis_rows()
    res = _verify_decision_log(rows)
    assert res["valid"] is False
    # break is at the first row of run B (index 2): its seq==0 != idx==2 (and prev != prior entry_hash)
    assert res["broken_at"] == 2
    assert res["head_hash"] is None
    # spec §5 (independent) reaches the IDENTICAL verdict
    spec = _spec_verify_chain(rows)
    assert spec["valid"] is False and spec["broken_at"] == 2


def test_forged_unlinked_row_rejected():
    """A fabricated unlinked row (seq:999, bogus prev_hash) must be REJECTED (verified:false) and must
    NOT become the published head_hash. The old max-seq head logic would have crowned it."""
    from spa_core.api.routers.rates_desk import _verify_decision_log
    rows = _write_chain_rows([_payload(0, reason="tail_veto", underlying="eeth"),
                              _payload(1, reason="tail_veto", underlying="susde")])
    # The DANGEROUS forgery the old verifier accepted: a fabricated row whose OWN entry_hash
    # recomputes (intrinsically valid) but is UNLINKED — seq:999, bogus prev_hash. The old
    # intrinsic-only check returned valid:true AND crowned it head_hash. A real chain verifier rejects.
    fp = {k: v for k, v in rows[-1].items() if k not in ENVELOPE}
    forged_eh = hash_chain.compute_entry_hash(999, rows[-1]["ts"], EVENT_TYPE, fp, "ff" * 32)
    forged = {"seq": 999, "ts": rows[-1]["ts"], "prev_hash": "ff" * 32, "entry_hash": forged_eh, **fp}
    rows_forged = rows + [forged]
    res = _verify_decision_log(rows_forged)
    assert res["valid"] is False
    assert res["broken_at"] == 2  # seq 999 != idx 2 → rejected at the forged row
    assert res["head_hash"] != forged_eh  # the forged (self-consistent) hash never becomes head
    # spec §5 agrees and also refuses to crown the forgery
    spec = _spec_verify_chain(rows_forged)
    assert spec["valid"] is False and spec["head_hash"] != forged_eh


@pytest.mark.parametrize("broken", [False, True])
def test_api_verdict_equals_spec_recipe(tmp_path, broken):
    """The API verifier and the published spec §5 recipe MUST compute the IDENTICAL verdict on the
    SAME file: clean → both true (+ identical head_hash); broken → both false (+ identical broken_at)."""
    from spa_core.api.routers.rates_desk import _verify_decision_log
    rows = _write_chain_rows([_payload(0, reason="tail_veto", underlying="eeth"),
                              _payload(1, reason="size_floor", underlying="susde"),
                              _payload(2, reason="none", underlying="ptusdc", approved=True)])
    if broken:
        rows[1]["decomposition"]["peg_haircut"] = "0.999999999"  # tamper, keep stored hash
    api = _verify_decision_log(rows)
    spec = _spec_verify_chain(rows)
    assert api["valid"] == spec["valid"]
    assert api["broken_at"] == spec["broken_at"]
    assert api["head_hash"] == spec["head_hash"]
    if not broken:
        assert api["valid"] is True
        assert api["head_hash"] == rows[-1]["entry_hash"]


def test_regenerated_canonical_log_verifies_as_one_chain():
    """The live committed data/rates_desk/decision_log.jsonl must verify as ONE coherent chain per the
    API verifier AND the independent spec §5 recipe (the published artifact is correct NOW)."""
    if not _REAL_LOG.exists():
        pytest.skip("canonical decision_log.jsonl absent")
    from spa_core.api.routers.rates_desk import _verify_decision_log
    rows = [json.loads(ln) for ln in _REAL_LOG.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert rows, "canonical log is empty"
    api = _verify_decision_log(rows)
    spec = _spec_verify_chain(rows)
    assert api["valid"] is True, f"canonical log not a single chain: broken_at={api['broken_at']}"
    assert spec["valid"] is True
    assert api["head_hash"] == spec["head_hash"] == rows[-1]["entry_hash"]
    # single genesis, contiguous seq
    assert rows[0]["prev_hash"] == "0" * 64
    assert [r["seq"] for r in rows] == list(range(len(rows)))


def test_rebase_preserves_decision_body():
    """Re-basing the mirror normalizes ONLY the envelope (seq/prev_hash/entry_hash) — the signed
    decision body (kind/reason/decomposition/proof_hash/…) is preserved verbatim."""
    from spa_core.strategy_lab.rates_desk import proof_chain
    src = _write_chain_rows([_payload(0, reason="tail_veto", underlying="eeth"),
                             _payload(1, reason="none", underlying="ptusdc", approved=True)])
    rebased = proof_chain._rebase_rows(src)
    for s, r in zip(src, rebased):
        assert proof_chain._payload_of(s) == proof_chain._payload_of(r)
    assert proof_chain.verify_mirror(rebased)["valid"] is True


def test_sandbox_run_does_not_write_canonical_mirror(monkeypatch, tmp_path):
    """A sandbox/hermetic run (no explicit log_path) must NOT write the canonical decision_log.jsonl
    (the write-interlock that stops transient runs from re-polluting the published chain). An explicit
    log_path is still honored."""
    from spa_core.strategy_lab.rates_desk import proof_chain
    # point the canonical _LOG at a tmp sentinel and the chain at tmp so we never touch real data
    canonical = tmp_path / "canonical_decision_log.jsonl"
    monkeypatch.setattr(proof_chain, "_LOG", canonical)
    monkeypatch.setattr(hash_chain, "_CHAIN", tmp_path / "audit_chain.jsonl")
    monkeypatch.setattr(proof_chain, "_is_sandbox", lambda: True)

    from spa_core.tests.test_rates_desk_integration import _toxic_and_carry_verdicts  # reuse verdicts
    verdicts = _toxic_and_carry_verdicts()

    # no log_path + sandbox → canonical mirror REFUSED
    proof_chain.record_decisions(verdicts, ts="2026-01-01T00:00:00+00:00")
    assert not canonical.exists(), "sandbox run polluted the canonical decision_log.jsonl"

    # explicit log_path under sandbox → allowed (its own file), and verifies as one chain
    own = tmp_path / "own_log.jsonl"
    proof_chain.record_decisions(verdicts, ts="2026-01-01T00:00:00+00:00", log_path=own)
    assert own.exists()
    rows = [json.loads(ln) for ln in own.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert proof_chain.verify_mirror(rows)["valid"] is True


# ── 5/6. API: shape, graceful, chain badge, redaction, advisory size ─────────────
pytest.importorskip("fastapi", reason="fastapi optional dep not installed — API suite skipped")
from fastapi.testclient import TestClient  # noqa: E402

import spa_core.api.server as server  # noqa: E402


@pytest.fixture()
def refusal_client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path


def test_refusals_endpoint_shape(refusal_client):
    """200 + full public shape; most-recent-first; human-readable EN/RU + drivers + hashes present."""
    client, data_dir = refusal_client
    log = data_dir / "rates_desk" / "decision_log.jsonl"
    _write_chain(log, [
        _payload(0, reason="tail_veto", underlying="eeth"),
        _payload(1, reason="size_floor", underlying="susde"),
        _payload(2, reason="none", underlying="ptusdc", approved=True),
    ])
    r = client.get("/api/rates-desk/refusals")
    assert r.status_code == 200
    d = r.json()
    assert d["model"] == "rates_desk_public_refusal_log"
    assert d["counts"] == {"ENTRY": 1, "REFUSAL": 2}
    assert d["chain"]["verified"] is True
    decs = d["decisions"]
    assert len(decs) == 3
    # most-recent-first
    assert decs[0]["seq"] == 2
    assert decs[-1]["seq"] == 0
    top = decs[0]
    for k in ("headline", "plain_en", "plain_ru", "structural_reason", "drivers",
              "net_edge", "advisory_size_usd", "proof_hash", "entry_hash", "prev_hash"):
        assert k in top, f"missing field {k}"
    assert top["plain_ru"]  # RU present
    assert isinstance(top["drivers"], list) and top["drivers"]


def test_refusals_limit(refusal_client):
    """limit bounds the returned decisions but chain verification still covers the WHOLE log."""
    client, data_dir = refusal_client
    log = data_dir / "rates_desk" / "decision_log.jsonl"
    _write_chain(log, [_payload(i, reason="tail_veto", underlying=f"u{i}") for i in range(10)])
    d = client.get("/api/rates-desk/refusals?limit=3").json()
    assert d["chain"]["chain_length"] == 10
    assert len(d["decisions"]) == 3
    assert d["chain"]["verified"] is True


def test_refusals_missing_log_graceful(refusal_client):
    """No log at all: empty decisions, chain badge present (vacuously verified over length 0), no 500."""
    client, _ = refusal_client
    r = client.get("/api/rates-desk/refusals")
    assert r.status_code == 200
    d = r.json()
    assert d["decisions"] == []
    assert d["chain"]["chain_length"] == 0
    assert d["chain"]["spec"] == "docs/PROOF_CHAIN_SPEC.md"
    assert d["counts"] == {"ENTRY": 0, "REFUSAL": 0}


def test_refusals_chain_badge_fields(refusal_client):
    """The chain badge carries verified/head_hash/chain_length/broken_at/spec; a tampered log flips
    verified=false with the right broken_at."""
    client, data_dir = refusal_client
    log = data_dir / "rates_desk" / "decision_log.jsonl"
    rows = _write_chain(log, [
        _payload(0, reason="tail_veto", underlying="eeth"),
        _payload(1, reason="tail_veto", underlying="susde"),
    ])
    clean = client.get("/api/rates-desk/refusals").json()["chain"]
    assert set(clean) == {"verified", "head_hash", "chain_length", "broken_at", "spec"}
    assert clean["verified"] is True
    assert clean["head_hash"] == rows[-1]["entry_hash"]

    # tamper row 0
    lines = log.read_text(encoding="utf-8").splitlines()
    row0 = json.loads(lines[0])
    row0["net_edge"] = "999.0"
    lines[0] = json.dumps(row0, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    bad = client.get("/api/rates-desk/refusals").json()["chain"]
    assert bad["verified"] is False
    assert bad["broken_at"] == 0


def test_no_secret_keys_in_public_payload(refusal_client):
    """The redaction guard strips ANY key matching secret/token/key/pat/wallet/address from the
    public payload — even if an upstream producer injected one into the log."""
    client, data_dir = refusal_client
    log = data_dir / "rates_desk" / "decision_log.jsonl"
    # craft a payload carrying poison keys, then chain it honestly so it self-verifies.
    poison = _payload(0, reason="tail_veto")
    poison["api_token"] = "SHOULD_NOT_APPEAR"
    poison["wallet_address"] = "0xdeadbeef"
    poison["secret_note"] = "leak"
    poison["private_key"] = "nope"
    _write_chain(log, [poison])

    d = client.get("/api/rates-desk/refusals").json()
    blob = json.dumps(d)
    for needle in ("SHOULD_NOT_APPEAR", "0xdeadbeef", "leak", "private_key", "api_token",
                   "wallet_address", "secret_note"):
        assert needle not in blob, f"denylisted content leaked: {needle}"

    # exhaustive: no key anywhere in the payload matches a denylist substring
    deny = ("secret", "token", "key", "pat", "wallet", "address", "private")

    def _walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(s in str(k).lower() for s in deny), f"denylisted key: {k}"
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)

    _walk(d)


def test_redaction_advisory_size_labeled(refusal_client):
    """Entries expose advisory_size_usd (never an unlabeled 'size' implying real capital)."""
    client, data_dir = refusal_client
    log = data_dir / "rates_desk" / "decision_log.jsonl"
    _write_chain(log, [_payload(0, reason="none", underlying="ptusdc", approved=True)])
    d = client.get("/api/rates-desk/refusals").json()
    top = d["decisions"][0]
    assert "advisory_size_usd" in top
    assert top["advisory_size_usd"] == "10000"
    # no bare 'size' key anywhere in a decision
    assert "size" not in top
    for drv in top["drivers"]:
        assert "size" not in drv
