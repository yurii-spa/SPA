"""test_api_dfb.py — the DFB — DeFi Board (LANE 2) /api/dfb/* router contract.

Verifies the public risk-first pool-analytics surface end-to-end against a HERMETIC
fixture matching the SHARED CONTRACT (Lane 1's output). Lane 1 (spa_core/dfb/* engine)
may not have shipped its live files yet, so these tests build the contract fixture
themselves under a redirected `_DATA_DIR` — the same monkeypatch the rest of the API
suite uses — so they pin the SERVE behavior regardless of Lane 1's progress.

SHARED CONTRACT fixture (documented here so Lane 1 + Lane 3 can match it):

  data/dfb/pools.json              = list[ <pool overlay object> ]
  data/dfb/pool/<pool_id>.json     = one <pool overlay object>
  data/dfb/history/<pool_id>.jsonl = proof-chained rows (prev_hash/row_hash, keyed on as_of)

  <pool overlay object> = {
    pool_id, protocol, chain, asset, tier,
    apy:{total,base,reward}, tvl_usd,
    risk_class (A/B/C/D), structural_haircut, total_haircut,
    exit_liquidity:[{ticket_usd,absorbable_usd,dex_exit_frac,flagged}],
    refusal:{verdict,reason,tail_veto},
    as_of, data_source, feed_coverage, prev_hash, row_hash
  }

Three verifications per the charter:
  • PROPERTY — response schema stable; the served list is byte-identical to pools.json;
    a re-derivable per-pool proof chain.
  • RED-TEAM — missing/corrupt pools.json → honest "unavailable" (no fabricated
    leaderboard); unknown/path-traversing pool_id → 404 (no guess); an insufficient-
    exit-liquidity pool serves its NULL/flagged cell verbatim (never a fabricated
    absorbable number); the /proof endpoint serves the COMPLETE chain (so the hash
    re-derives); a tampered proof row breaks chain verification.
  • SMOKE — each endpoint via TestClient → correct shape; GET-public works.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in [str(_SPA_CORE), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest

pytest.importorskip(
    "fastapi", reason="fastapi optional dep not installed — API suite skipped"
)
from fastapi.testclient import TestClient  # noqa: E402

import spa_core.api.server as server  # noqa: E402

GENESIS_PREV = "0" * 64


# ── contract fixture builders ────────────────────────────────────────────────────────
def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _pool_obj(
    pool_id: str,
    *,
    risk_class: str = "B",
    verdict: str = "ALLOW",
    tail_veto: bool = False,
    exit_flagged: bool = False,
    absorbable_1m=950_000.0,
    as_of: str = "2026-06-30T00:00:00+00:00",
) -> dict:
    """Build ONE pool overlay object matching the shared contract.

    `exit_flagged=True` (a thin/insufficient-depth pool) sets the $1M ticket's
    absorbable_usd to None and flagged=True — the fail-CLOSED HOLE the router must serve
    VERBATIM (never a fabricated fill)."""
    exit_1m = {
        "ticket_usd": 1_000_000,
        "absorbable_usd": (None if exit_flagged else absorbable_1m),
        "dex_exit_frac": (None if exit_flagged else 0.95),
        "flagged": exit_flagged,
    }
    return {
        "pool_id": pool_id,
        "protocol": "aave_v3",
        "chain": "ethereum",
        "asset": "USDC",
        "tier": "T1",
        "apy": {"total": 4.2, "base": 3.8, "reward": 0.4},
        "tvl_usd": 1_200_000_000.0,
        "risk_class": risk_class,
        "structural_haircut": 0.02,
        "total_haircut": 0.05,
        "exit_liquidity": [
            {"ticket_usd": 100_000, "absorbable_usd": 100_000.0, "dex_exit_frac": 1.0, "flagged": False},
            exit_1m,
        ],
        "refusal": {"verdict": verdict, "reason": ("structural_tail" if verdict == "REFUSE" else None),
                    "tail_veto": tail_veto},
        "as_of": as_of,
        "data_source": "defillama_feed",
        "feed_coverage": "full",
        "prev_hash": GENESIS_PREV,
        "row_hash": "deadbeef" * 8,
    }


def _write_universe(data_dir: Path, pools: list) -> None:
    """Write pools.json + the per-pool detail files matching the contract."""
    dfb = data_dir / "dfb"
    (dfb / "pool").mkdir(parents=True, exist_ok=True)
    (dfb / "pools.json").write_text(_canonical(pools), encoding="utf-8")
    for p in pools:
        (dfb / "pool" / f"{p['pool_id']}.json").write_text(_canonical(p), encoding="utf-8")


def _write_history(data_dir: Path, pool_id: str, n: int = 3, tamper_idx: int | None = None):
    """Write a proof-chained history JSONL using the SHARED engine's compute_row_hash
    (prev_hash/row_hash keyed on as_of) — so the router's verify_series re-derives it.

    `tamper_idx` mutates a row's payload AFTER hashing → the chain must fail at that row."""
    from spa_core.strategy_lab.rates_desk import books_series

    hist = data_dir / "dfb" / "history"
    hist.mkdir(parents=True, exist_ok=True)
    rows = []
    prev = GENESIS_PREV
    for seq in range(n):
        as_of = f"2026-06-{20 + seq:02d}T00:00:00+00:00"
        payload = {
            "pool_id": pool_id,
            "apy_base": 3.8 + seq * 0.01,
            "apy_reward": 0.4,
            "tvl_usd": 1_000_000_000.0 + seq,
            "il_risk": "no",
            "risk_class": "B",
            "refusal_state": "ALLOW",
        }
        row_hash = books_series.compute_row_hash(seq, as_of, payload, prev)
        rows.append({**payload, "as_of": as_of, "prev_hash": prev, "row_hash": row_hash})
        prev = row_hash
    if tamper_idx is not None:
        # Forge an OUTPUT without re-hashing → breaks the chain at tamper_idx.
        rows[tamper_idx]["apy_base"] = 999.0
    lines = "\n".join(_canonical(r) for r in rows) + "\n"
    (hist / f"{pool_id}.jsonl").write_text(lines, encoding="utf-8")
    return rows


@pytest.fixture()
def empty_client(tmp_path, monkeypatch):
    """TestClient with an EMPTY data dir → every endpoint takes its fail-CLOSED branch."""
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def populated_client(tmp_path, monkeypatch):
    """TestClient over a hermetic universe matching the shared contract.

    Pools:
      • dfb_pool_a — class A, ALLOW, healthy $1M exit (absorbable filled).
      • dfb_pool_toxic — class D, REFUSE, tail_veto=True (the toxic-LRT red-team subject).
      • dfb_pool_thin — class C, exit-liquidity at $1M FLAGGED (absorbable=None hole).
    History only for dfb_pool_a (proof-chained, 3 rows)."""
    pools = [
        _pool_obj("dfb_pool_a", risk_class="A", verdict="ALLOW"),
        _pool_obj("dfb_pool_toxic", risk_class="D", verdict="REFUSE", tail_veto=True),
        _pool_obj("dfb_pool_thin", risk_class="C", verdict="WATCH", exit_flagged=True),
    ]
    _write_universe(tmp_path, pools)
    _write_history(tmp_path, "dfb_pool_a", n=3)
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path, pools


# ══════════════════════════════════════════════════════════════════════════════════════
# SMOKE — each endpoint serves the contract; GET-public works.
# ══════════════════════════════════════════════════════════════════════════════════════
def test_smoke_all_endpoints_public_get(populated_client):
    client, _, pools = populated_client
    assert client.get("/api/dfb/pools").status_code == 200
    assert client.get("/api/dfb/pool/dfb_pool_a").status_code == 200
    assert client.get("/api/dfb/pool/dfb_pool_a/history").status_code == 200
    assert client.get("/api/dfb/pool/dfb_pool_a/proof").status_code == 200
    assert client.get("/api/dfb/summary").status_code == 200


def test_pools_serves_full_list_verbatim(populated_client):
    """PROPERTY: the screener serves the COMPLETE list, byte-identical to pools.json."""
    client, data_dir, pools = populated_client
    body = client.get("/api/dfb/pools").json()
    assert body["available"] is True
    assert body["is_advisory"] is True
    assert body["n_pools"] == 3
    on_disk = json.loads((data_dir / "dfb" / "pools.json").read_text())
    assert body["pools"] == on_disk  # served verbatim, no recomputation
    assert body["note"] is None


def test_pool_detail_serves_overlay_with_schedule_and_refusal(populated_client):
    """PROPERTY: detail = overlay object + exit-liquidity schedule + refusal decomposition."""
    client, _, _ = populated_client
    body = client.get("/api/dfb/pool/dfb_pool_toxic").json()
    assert body["pool_id"] == "dfb_pool_toxic"
    assert body["risk_class"] == "D"
    assert body["refusal"]["verdict"] == "REFUSE"
    assert body["refusal"]["tail_veto"] is True
    assert isinstance(body["exit_liquidity"], list)
    assert body["is_advisory"] is True


def test_history_serves_verified_chain(populated_client):
    """PROPERTY: history serves the proof-chained series + a verified chain badge."""
    client, _, _ = populated_client
    body = client.get("/api/dfb/pool/dfb_pool_a/history").json()
    assert body["pool_id"] == "dfb_pool_a"
    assert body["n_records"] == 3
    assert body["chain"]["verified"] is True
    assert body["chain"]["chain_length"] == 3
    assert body["chain"]["head_hash"]  # non-empty head
    assert len(body["series"]) == 3


def test_summary_universe_stats(populated_client):
    """PROPERTY: summary aggregates verdicts/classes — counts only, no risk math."""
    client, _, _ = populated_client
    body = client.get("/api/dfb/summary").json()
    assert body["available"] is True
    assert body["n_pools"] == 3
    assert body["n_by_risk_class"] == {"A": 1, "B": 0, "C": 1, "D": 1, "UNKNOWN": 0}
    assert body["n_refused"] == 1  # only dfb_pool_toxic REFUSEs
    # only dfb_pool_a + dfb_pool_toxic have a non-flagged $1M fill; dfb_pool_thin is a hole.
    assert body["n_exit_liquidity_1m"] == 2
    assert body["as_of"] == "2026-06-30T00:00:00+00:00"


# ══════════════════════════════════════════════════════════════════════════════════════
# RED-TEAM — make the feature LIE; it must be CAUGHT, not handled.
# ══════════════════════════════════════════════════════════════════════════════════════
def test_redteam_missing_pools_is_honest_unavailable_not_fabricated(empty_client):
    """RED-TEAM: a missing pools.json → 200 honest 'unavailable', NEVER a fabricated leaderboard."""
    body = empty_client.get("/api/dfb/pools").json()
    assert body["available"] is False
    assert body["n_pools"] == 0
    assert body["pools"] == []           # no fabricated rows
    assert "unavailable" in body["note"].lower()
    # summary too: zeroed, not invented.
    s = empty_client.get("/api/dfb/summary").json()
    assert s["available"] is False
    assert s["n_pools"] == 0
    assert s["n_refused"] == 0
    assert s["n_by_risk_class"] == {"A": 0, "B": 0, "C": 0, "D": 0, "UNKNOWN": 0}


def test_redteam_corrupt_pools_json_is_unavailable_not_500(tmp_path, monkeypatch):
    """RED-TEAM: a corrupt pools.json (non-array / garbage) → honest empty, never a 500."""
    (tmp_path / "dfb").mkdir(parents=True, exist_ok=True)
    # (a) not-an-array
    (tmp_path / "dfb" / "pools.json").write_text('{"oops": "not a list"}', encoding="utf-8")
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        body = c.get("/api/dfb/pools")
        assert body.status_code == 200
        assert body.json()["available"] is False
        # (b) outright garbage bytes
        (tmp_path / "dfb" / "pools.json").write_text("{not json at all", encoding="utf-8")
        body2 = c.get("/api/dfb/pools")
        assert body2.status_code == 200
        assert body2.json()["pools"] == []


def test_redteam_unknown_pool_id_is_404_not_guess(populated_client):
    """RED-TEAM: an unknown pool_id → 404, NEVER a fabricated pool."""
    client, _, _ = populated_client
    assert client.get("/api/dfb/pool/does_not_exist").status_code == 404
    assert client.get("/api/dfb/pool/does_not_exist/history").status_code == 200  # empty chain, not a guess
    assert client.get("/api/dfb/pool/does_not_exist/proof").status_code == 404


def test_redteam_path_traversal_pool_id_is_404(populated_client):
    """RED-TEAM: a path-traversing pool_id must NEVER resolve outside data/dfb/ → 404."""
    client, _, _ = populated_client
    for bad in ("..%2f..%2fsecret", "../../etc/passwd", "a/b", "x".ljust(200, "y")):
        assert client.get(f"/api/dfb/pool/{bad}").status_code == 404
        assert client.get(f"/api/dfb/pool/{bad}/proof").status_code == 404


def test_redteam_insufficient_exit_liquidity_serves_null_not_fabricated(populated_client):
    """RED-TEAM: a pool flagged insufficient-exit-liquidity serves NULL/flagged at $1M —
    NEVER a fabricated absorbable number."""
    client, _, _ = populated_client
    body = client.get("/api/dfb/pool/dfb_pool_thin").json()
    one_m = next(t for t in body["exit_liquidity"] if t["ticket_usd"] == 1_000_000)
    assert one_m["flagged"] is True
    assert one_m["absorbable_usd"] is None  # the hole is served as a hole
    assert one_m["dex_exit_frac"] is None
    # and the summary does NOT count this thin pool as having $1M exit liquidity.
    s = client.get("/api/dfb/summary").json()
    assert s["n_exit_liquidity_1m"] == 2  # a + toxic, NOT thin


def test_redteam_toxic_pool_not_graded_safe(populated_client):
    """RED-TEAM: the toxic-LRT-shaped pool must surface as class D + REFUSE + tail_veto —
    it is NOT served indistinguishable from a safe pool. (The desk's veto, served verbatim.)"""
    client, _, _ = populated_client
    body = client.get("/api/dfb/pool/dfb_pool_toxic").json()
    assert body["risk_class"] == "D"
    assert body["refusal"]["verdict"] == "REFUSE"
    assert body["refusal"]["tail_veto"] is True


def test_redteam_proof_serves_complete_chain_rederivable(populated_client):
    """RED-TEAM: /proof serves the COMPLETE chain VERBATIM (uncapped, raw bytes) so a third
    party re-derives the proof_hash. Re-hash each row → matches the published row_hash."""
    from spa_core.strategy_lab.rates_desk import books_series

    client, data_dir, _ = populated_client
    resp = client.get("/api/dfb/pool/dfb_pool_a/proof")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    raw = resp.text
    # served byte-for-byte from disk (no reformat) → the verifier hashes the same bytes.
    on_disk = (data_dir / "dfb" / "history" / "dfb_pool_a.jsonl").read_text(encoding="utf-8")
    assert raw == on_disk
    # RE-DERIVE the chain from the served bytes alone (no spa_core overlay re-run).
    rows = [json.loads(ln) for ln in raw.splitlines() if ln.strip()]
    prev = GENESIS_PREV
    for seq, row in enumerate(rows):
        payload = {k: v for k, v in row.items() if k not in ("as_of", "prev_hash", "row_hash")}
        recomputed = books_series.compute_row_hash(seq, row["as_of"], payload, prev)
        assert recomputed == row["row_hash"], f"row {seq} hash does not re-derive"
        assert row["prev_hash"] == prev
        prev = row["row_hash"]


def test_redteam_tampered_proof_row_breaks_chain(tmp_path, monkeypatch):
    """RED-TEAM: tamper with a stored row (forge an output, keep its old hash) → the
    history chain badge must report verified=false at the tampered row (tamper-evident),
    NEVER silently pass."""
    pools = [_pool_obj("dfb_pool_t", risk_class="B", verdict="ALLOW")]
    _write_universe(tmp_path, pools)
    _write_history(tmp_path, "dfb_pool_t", n=3, tamper_idx=1)
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        body = c.get("/api/dfb/pool/dfb_pool_t/history").json()
        assert body["chain"]["verified"] is False
        assert body["chain"]["broken_at"] == 1


def test_redteam_nonfinite_in_pools_is_scrubbed_not_500(tmp_path, monkeypatch):
    """RED-TEAM: a corrupt pool carrying a NaN/inf must be scrubbed to null, never crash
    the serializer (no 500)."""
    pool = _pool_obj("dfb_pool_nan", risk_class="B")
    # inject a non-finite via the raw JSON tokens json.loads accepts.
    raw = _canonical(pool).replace('"tvl_usd":1200000000.0', '"tvl_usd":NaN')
    (tmp_path / "dfb" / "pool").mkdir(parents=True, exist_ok=True)
    (tmp_path / "dfb" / "pools.json").write_text("[" + raw + "]", encoding="utf-8")
    (tmp_path / "dfb" / "pool" / "dfb_pool_nan.json").write_text(raw, encoding="utf-8")
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        b = c.get("/api/dfb/pools")
        assert b.status_code == 200
        assert b.json()["pools"][0]["tvl_usd"] is None  # NaN scrubbed → null
        d = c.get("/api/dfb/pool/dfb_pool_nan")
        assert d.status_code == 200
        assert d.json()["tvl_usd"] is None


def test_reproduce_block_present_on_proof_bearing_responses(populated_client):
    """PROPERTY: the 'don't trust us, check us' reproduce block is embedded on the
    screener + detail + history surfaces."""
    client, _, _ = populated_client
    for path in ("/api/dfb/pools", "/api/dfb/pool/dfb_pool_a", "/api/dfb/pool/dfb_pool_a/history"):
        rb = client.get(path).json()["reproduce"]
        assert rb["spec"] == "docs/PROOF_CHAIN_SPEC.md"
        assert "verify_spa.py" in rb["verifier"]
