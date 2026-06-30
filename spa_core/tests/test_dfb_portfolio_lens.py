"""
test_dfb_portfolio_lens.py — the property + RED-TEAM + smoke quality bar for the DFB read-only
portfolio risk lens (Lane-C / WS-2.4) + the flag-gated /api/dfb/portfolio endpoint + the
zero-dependency per-pool verifier (scripts/verify_dfb_pool.py).

THE non-negotiables this file pins:
  • READ-ONLY: there is NO signer / private-key / transaction / wallet-connect path anywhere in
    spa_core/dfb/portfolio.py (AST + grep proof) — a read-only address STRING only.
  • RISK IS SURFACED, NEVER HIDDEN: a holding in a REFUSE-grade / class-D pool is flagged in the
    portfolio summary (has_refuse_grade_holdings + the itemized list), never silently rolled up.
  • FLAG OFF ⇒ TOTAL 404: with SPA_DFB_PORTFOLIO_LENS unset/false the endpoint does not exist
    (no surface leak); a graded view is only reachable with the flag explicitly ON.
  • FAIL-CLOSED: a malformed/path-traversing address → honest empty / 404; an unknown pool_id →
    flagged `unresolved`, never a fabricated position.
  • THE VERIFIER reproduces a clean pool row byte-for-byte (zero spa_core import) and catches a
    tampered cell + a broken chain with a precise broken_at.

PURE / no network (overlay rows graded from in-memory published dicts; universe injected).
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from spa_core.dfb import portfolio as P

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
_PORTFOLIO_SRC = _HERE.parent / "dfb" / "portfolio.py"
_VERIFIER = _PROJECT_ROOT / "scripts" / "verify_dfb_pool.py"


# ── shared published-overlay fixtures (the API path grades against these proof-hashed rows) ──
def _overlay_row(pool_id, *, risk_class="A", verdict="SAFE", tail_veto=False, flagged_exit=False):
    return {
        "pool_id": pool_id, "protocol": "aave_v3", "chain": "Ethereum", "asset": "USDC",
        "tier": "T1", "apy": {"total": 0.04, "base": 0.04, "reward": None}, "tvl_usd": 1.2e9,
        "risk_class": risk_class, "risk_class_label": f"{risk_class} label",
        "structural_haircut": 0.005, "total_haircut": 0.01,
        "exit_liquidity": [
            {"ticket_usd": 1_000_000,
             "absorbable_usd": (None if flagged_exit else 990_000.0),
             "dex_exit_frac": (None if flagged_exit else 0.99), "flagged": flagged_exit},
            {"ticket_usd": 5_000_000, "absorbable_usd": 4.9e6, "dex_exit_frac": 0.98, "flagged": False},
            {"ticket_usd": 10_000_000, "absorbable_usd": 9.8e6, "dex_exit_frac": 0.98, "flagged": False},
        ],
        "refusal": {"verdict": verdict, "reason": ("tail_veto" if tail_veto else "none"),
                    "tail_veto": tail_veto},
        "as_of": "2026-06-30", "data_source": "live", "feed_coverage": "full",
        "flagged": False, "flag_reason": None,
        "engine_proof_hash": "abc", "prev_hash": "0" * 64, "row_hash": "def",
    }


def _rows_by_id(*rows):
    return {r["pool_id"]: r for r in rows}


# ══════════════════════════════ PROPERTY ══════════════════════════════
def test_address_normalize_read_only_label():
    assert P.normalize_address("0x" + "A" * 40) == "0x" + "a" * 40   # EVM lowercased
    assert P.normalize_address("Vitalik.ETH") == "vitalik.eth"        # ENS lowercased
    # malformed / path-traversal / control / unsafe charset → None (fail-CLOSED)
    assert P.normalize_address("../../etc/passwd") is None      # path traversal
    assert P.normalize_address("") is None
    assert P.normalize_address(None) is None
    assert P.normalize_address("has space") is None             # disallowed charset
    assert P.normalize_address("x") is None                     # too short for a label
    assert P.normalize_address("a" * 300) is None               # over the length bound


def test_grades_positions_against_published_rows():
    rows = _rows_by_id(
        _overlay_row("a__eth__usdc", risk_class="A", verdict="SAFE"),
        _overlay_row("c__eth__usdc", risk_class="C", verdict="REFUSE"),
    )
    src = P.DeclaredHoldingsSource.from_raw([
        {"pool_id": "a__eth__usdc", "value_usd": 300_000},
        {"pool_id": "c__eth__usdc", "value_usd": 100_000},
    ])
    view = P.portfolio_view_from_published("0x" + "a" * 40, src, rows)
    assert view["address_validated"] is True
    assert view["n_positions"] == 2
    # the value-weighted class split is exact (300k A, 100k C → 75% / 25%)
    pct = view["summary"]["pct_by_risk_class"]
    assert pct["A"] == 75.0 and pct["C"] == 25.0
    # deterministic: same inputs → identical view
    again = P.portfolio_view_from_published("0x" + "a" * 40, src, rows)
    assert json.dumps(view, sort_keys=True) == json.dumps(again, sort_keys=True)


def test_exit_liquidity_hole_not_fabricated():
    rows = _rows_by_id(_overlay_row("h__eth__usdc", flagged_exit=True))
    src = P.DeclaredHoldingsSource.from_raw([{"pool_id": "h__eth__usdc", "value_usd": 100_000}])
    view = P.portfolio_view_from_published("0x" + "b" * 40, src, rows)
    cell = view["positions"][0]["exit_liquidity"][0]
    assert cell["flagged"] is True and cell["absorbable_usd"] is None  # a HOLE, never filled
    # the $1M slot in the summary counts the hole, never sums a fabricated absorbable
    slot = next(s for s in view["summary"]["exit_liquidity_at_size"] if s["ticket_usd"] == 1_000_000)
    assert slot["n_holes"] == 1 and slot["total_absorbable_usd"] == 0.0


# ══════════════════════════════ RED-TEAM ══════════════════════════════
def test_refuse_grade_holding_is_surfaced_not_hidden():
    """The worst lie a portfolio rollup can tell: bury a position the desk would REFUSE. It MUST be
    flagged in the summary (the risk surfaced), itemized, and its value counted."""
    rows = _rows_by_id(
        _overlay_row("safe__eth__usdc", risk_class="A", verdict="SAFE"),
        _overlay_row("toxic__eth__ezeth", risk_class="D", verdict="REFUSE", tail_veto=True),
    )
    src = P.DeclaredHoldingsSource.from_raw([
        {"pool_id": "safe__eth__usdc", "value_usd": 900_000},
        {"pool_id": "toxic__eth__ezeth", "value_usd": 100_000},
    ])
    view = P.portfolio_view_from_published("0x" + "c" * 40, src, rows)
    s = view["summary"]
    assert s["has_refuse_grade_holdings"] is True
    assert s["n_refuse_grade_holdings"] == 1
    assert s["value_in_refuse_grade_usd"] == 100_000.0
    flagged = s["refuse_grade_holdings"]
    assert len(flagged) == 1
    assert flagged[0]["pool_id"] == "toxic__eth__ezeth"
    assert flagged[0]["risk_class"] == "D"
    assert flagged[0]["tail_veto"] is True
    assert flagged[0]["refusal_verdict"] == "REFUSE"


def test_no_signing_or_private_key_path_in_portfolio_module():
    """RED-TEAM: AST + grep proof that the portfolio lens has NO signer / key / tx / wallet-connect
    path — read-only address STRING only. Scans every import and call name in the module AST; the
    only allowed mentions are in docstrings/comments (the negations themselves)."""
    src = _PORTFOLIO_SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)

    forbidden_substrings = (
        "privatekey", "private_key", "secp256k1", "mnemonic", "seedphrase", "seed_phrase",
        "keystore", "eth_account", "web3", "walletconnect", "wallet_connect",
        "send_transaction", "sendtransaction", "sign_transaction", "signtransaction",
    )
    # 1. no forbidden module is imported
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                low = n.name.lower().replace(".", "")
                assert not any(f.replace("_", "") in low for f in forbidden_substrings), \
                    f"forbidden import: {n.name}"
        if isinstance(node, ast.ImportFrom):
            mod = (node.module or "").lower().replace(".", "")
            assert "execution" not in mod, "NO execution import allowed"
            assert not any(f.replace("_", "") in mod for f in forbidden_substrings), \
                f"forbidden import-from: {node.module}"
    # 2. no attribute/name call literally named sign(...) / sign_transaction(...) etc.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = None
            if isinstance(fn, ast.Attribute):
                name = fn.attr.lower()
            elif isinstance(fn, ast.Name):
                name = fn.id.lower()
            if name:
                assert name not in ("sign", "sign_transaction", "send_transaction",
                                    "signtransaction", "sendtransaction"), \
                    f"forbidden call: {name}"
    # 3. grep belt-and-suspenders: outside strings/comments there is no `.sign(` etc. We approximate
    #    by asserting these tokens only appear on lines that are clearly prose (contain spaces and a
    #    word like 'never'/'no'/'NEVER' — the doc negations) OR not at all as executable code.
    for token in (".sign(", "send_transaction(", "private_key"):
        for ln in src.splitlines():
            if token in ln:
                stripped = ln.strip()
                # must be a comment / docstring prose line, not executable code
                assert stripped.startswith(("#", '"', "'", "║", "*")) or "NEVER" in ln or "no " in ln.lower() \
                    or "never" in ln.lower(), f"executable use of {token!r}: {ln!r}"


def test_unknown_pool_id_is_unresolved_not_fabricated():
    rows = _rows_by_id(_overlay_row("known__eth__usdc"))
    src = P.DeclaredHoldingsSource.from_raw([
        {"pool_id": "known__eth__usdc", "value_usd": 50_000},
        {"pool_id": "does_not_exist__x__y", "value_usd": 999_000},
    ])
    view = P.portfolio_view_from_published("0x" + "d" * 40, src, rows)
    assert view["n_positions"] == 1                       # only the known pool graded
    assert len(view["unresolved"]) == 1
    assert view["unresolved"][0]["pool_id"] == "does_not_exist__x__y"
    # the unknown pool contributes NOTHING to the graded summary (no fabricated grade)
    assert view["summary"]["total_value_usd"] == 50_000.0


def test_malformed_address_fails_closed_empty():
    src = P.DeclaredHoldingsSource.from_raw([{"pool_id": "x__y__z", "value_usd": 1}])
    view = P.portfolio_view_from_published("../../secret", src, _rows_by_id())
    assert view["address_validated"] is False
    assert view["n_positions"] == 0 and view["positions"] == []


def test_malformed_holding_values_dropped():
    src = P.DeclaredHoldingsSource.from_raw([
        {"pool_id": "a__b__c", "value_usd": "not a number"},
        {"pool_id": "a__b__c", "value_usd": -5},
        {"pool_id": "", "value_usd": 10},
        {"no_pool": True},
        "garbage",
    ])
    # every malformed cell dropped → empty source
    assert src.resolve("0x" + "e" * 40) == []


def test_data_source_limit_always_stamped():
    """The honest data-source limit MUST be on every response — the surface can never imply it
    auto-read the chain. And the only wired source declares it does not read a chain."""
    rows = _rows_by_id(_overlay_row("a__b__c"))
    src = P.DeclaredHoldingsSource([])
    view = P.portfolio_view_from_published("0x" + "f" * 40, src, rows)
    assert "data_source_limit" in view and view["data_source_limit"]
    assert view["read_only"] is True and view["no_custody"] is True
    assert view["source_reads_chain"] is False
    assert P.DeclaredHoldingsSource.reads_chain is False


# ══════════════════════════════ API flag-gating (SMOKE) ══════════════════════════════
@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import spa_core.api.server as server
    return TestClient(server.app)


def test_endpoint_404_when_flag_off(client, monkeypatch):
    """Flag OFF (default) ⇒ the portfolio endpoint is a TOTAL 404 (no surface leak)."""
    monkeypatch.delenv("SPA_DFB_PORTFOLIO_LENS", raising=False)
    r = client.get("/api/dfb/portfolio/0x" + "a" * 40)
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "portfolio_lens_disabled"


def test_endpoint_works_when_flag_on(client, monkeypatch):
    monkeypatch.setenv("SPA_DFB_PORTFOLIO_LENS", "1")
    r = client.get("/api/dfb/portfolio/0x" + "a" * 40, params={"holdings": "[]"})
    assert r.status_code == 200
    d = r.json()
    assert d["model"] == "dfb_portfolio_lens"
    assert d["read_only"] is True and d["is_advisory"] is True
    assert "data_source_limit" in d


def test_endpoint_path_traversal_address_404(client, monkeypatch):
    monkeypatch.setenv("SPA_DFB_PORTFOLIO_LENS", "1")
    r = client.get("/api/dfb/portfolio/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code == 404


# ══════════════════════════════ the zero-dependency verifier ══════════════════════════════
def _row_hash_recipe(row: dict, prev_hash: str) -> str:
    """The published recipe, reproduced here independently (the verifier must match this)."""
    import hashlib
    body = {k: v for k, v in row.items() if k not in ("prev_hash", "row_hash")}
    blob = json.dumps({"body": body, "prev_hash": prev_hash}, sort_keys=True,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _signed_row(pool_id, prev="0" * 64, **kw):
    row = _overlay_row(pool_id, **kw)
    row["prev_hash"] = prev
    row["row_hash"] = _row_hash_recipe(row, prev)
    return row


def _run_verifier(*args, cwd=None):
    """Run the verifier on a CLEAN machine (env -i, no spa_core on the path)."""
    return subprocess.run(
        [sys.executable, str(_VERIFIER), *args],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}, cwd=cwd)


def test_verifier_reproduces_clean_pool(tmp_path):
    row = _signed_row("aave__eth__usdc")
    f = tmp_path / "pool.json"
    f.write_text(json.dumps(row, indent=1), encoding="utf-8")
    res = _run_verifier(str(f))
    assert res.returncode == 0, res.stdout + res.stderr
    assert "PASS" in res.stdout


def test_verifier_catches_tampered_row(tmp_path):
    """Tamper a published cell (REFUSE→SAFE) WITHOUT updating the hash → the verifier must FAIL with
    a precise broken_at on that pool_id (exit 1)."""
    row = _signed_row("c__eth__usdc", risk_class="C", verdict="REFUSE")
    row["refusal"]["verdict"] = "SAFE"   # the lie
    row["risk_class"] = "A"
    f = tmp_path / "tampered.json"
    f.write_text(json.dumps(row, indent=1), encoding="utf-8")
    res = _run_verifier(str(f))
    assert res.returncode == 1, res.stdout
    assert "FAIL" in res.stdout
    assert "c__eth__usdc" in res.stdout  # the precise broken_at


def test_verifier_catches_broken_chain(tmp_path):
    """A pools.json chain with a dropped row breaks the prev_hash linkage → exit 1, broken_at."""
    r1 = _signed_row("p1__eth__usdc")
    r2 = _signed_row("p2__eth__usdc", prev=r1["row_hash"])
    r3 = _signed_row("p3__eth__usdc", prev=r2["row_hash"])
    wrapped = {"schema": "dfb_pool_overlay_v1", "pools": [r1, r3]}  # r2 dropped → r3 link breaks
    f = tmp_path / "pools.json"
    f.write_text(json.dumps(wrapped, indent=1), encoding="utf-8")
    res = _run_verifier(str(f))
    assert res.returncode == 1, res.stdout
    assert "chain break" in res.stdout or "broken_at" in res.stdout


def test_verifier_zero_dependency_no_spa_core_import():
    """The verifier source must NOT import spa_core (clean-machine guarantee)."""
    src = _VERIFIER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                assert not n.name.startswith("spa_core"), f"verifier imports {n.name}"
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("spa_core"), \
                f"verifier imports from {node.module}"


def test_verifier_no_input_exit_2(tmp_path):
    res = _run_verifier(str(tmp_path / "does_not_exist"))
    assert res.returncode == 2
