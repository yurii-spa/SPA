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
