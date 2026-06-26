"""
spa_core/tests/test_rwa_onchain_nav.py — REAL on-chain intrinsic-NAV reader (keyless eth_call).

Pure synthetic, no network (a FakeRpcFetcher injects JSON-RPC responses keyed by selector).
Verifies the deterministic contracts the on-chain NAV layer relies on:
  - the eth_call request encoder + hex uint decoder (selectors, padding, 0x decode)
  - a real ERC-4626 asset (injected totalAssets/totalSupply/decimals/convertToAssets) → intrinsic
    NAV computed and flagged nav_source=onchain_4626
  - a non-4626 token (totalAssets reverts) / RPC down → fail-CLOSED to off_chain_estimate
  - an out-of-band (mis-decoded) NAV → rejected, fail-CLOSED to estimate
  - safety_board wires it in additively: nav_source + onchain_nav fields, coverage counts, the
    board still produces every row on estimate when no RPC responds
  - deterministic (same injected responses → identical output)
"""
# LLM_FORBIDDEN
from __future__ import annotations

from spa_core.strategy_lab.rwa_backstop.collateral_registry import CollateralAsset
from spa_core.strategy_lab.rwa_backstop.onchain_nav import (
    OnchainNAVReader,
    OnchainNAV,
    encode_eth_call,
    encode_convert_to_assets,
    decode_uint,
    SEL_TOTAL_ASSETS,
    SEL_TOTAL_SUPPLY,
    SEL_DECIMALS,
    SEL_CONVERT_TO_ASSETS,
    NAV_SOURCE_ONCHAIN,
    NAV_SOURCE_ESTIMATE,
    _PROBE_4626_CONTRACT,
    _PROBE_EXPECT_DECIMALS,
)
from spa_core.strategy_lab.rwa_backstop import safety_board as sb


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────
def _u256(n: int) -> str:
    """abi-encode a uint256 as a 0x 32-byte hex string (an eth_call return)."""
    return "0x" + f"{n:064x}"


class _FakeRpc:
    """(url, payload) -> json. Routes by JSON-RPC method + the 4-byte selector in eth_call data.

    `selector_returns` maps a 4-byte selector (e.g. SEL_TOTAL_SUPPLY) to either a 0x-hex result
    string OR the sentinel REVERT (→ a JSON-RPC error object, the common revert surface). A missing
    selector → '0x' (empty return). chain_id controls the eth_chainId probe (default mainnet)."""

    REVERT = object()

    def __init__(self, selector_returns=None, chain_id=1, down=False):
        self.selector_returns = selector_returns or {}
        self.chain_id = chain_id
        self.down = down
        self.calls = []

    def __call__(self, url, payload):
        self.calls.append((url, payload))
        if self.down:
            raise OSError("rpc down")
        method = payload.get("method")
        if method == "eth_chainId":
            if self.chain_id is None:
                raise OSError("no chainId")
            return {"jsonrpc": "2.0", "id": payload.get("id"), "result": _u256(self.chain_id)}
        if method == "eth_call":
            to = payload["params"][0]["to"]
            data = payload["params"][0]["data"]
            sel = data[:10]  # 0x + 8 hex
            # the endpoint-validation probe reads decimals() off the canonical sDAI 4626 contract;
            # a usable endpoint must serve it. Honor the probe so select_endpoint() accepts us.
            if to == _PROBE_4626_CONTRACT.lower() and sel == SEL_DECIMALS:
                return {"jsonrpc": "2.0", "id": payload.get("id"),
                        "result": _u256(_PROBE_EXPECT_DECIMALS)}
            ret = self.selector_returns.get(sel, "0x")
            if ret is self.REVERT:
                return {"jsonrpc": "2.0", "id": payload.get("id"),
                        "error": {"code": 3, "message": "execution reverted"}}
            return {"jsonrpc": "2.0", "id": payload.get("id"), "result": ret}
        raise ValueError(f"unexpected method {method}")


def _asset(symbol="VAULT", contract="0xabc0000000000000000000000000000000000001",
           restricted=False):
    return CollateralAsset(
        symbol=symbol, issuer="Test", chain="ethereum", asset_class="tokenized_tbill",
        token_contract=contract, transfer_restricted=restricted,
        redemption_delay_days=1.0, redemption_fee_bps=0.0, min_redemption_usd=0.0,
        redemption_documented=True,
    )


# ── 1. encoder / decoder ──────────────────────────────────────────────────────────────────────────
def test_encode_eth_call_shape():
    req = encode_eth_call("0xABCDEF", SEL_TOTAL_ASSETS, call_id=7)
    assert req["method"] == "eth_call"
    assert req["jsonrpc"] == "2.0"
    assert req["id"] == 7
    assert req["params"][1] == "latest"
    assert req["params"][0]["to"] == "0xabcdef"          # lower-cased
    assert req["params"][0]["data"] == SEL_TOTAL_ASSETS    # selector preserved


def test_encode_convert_to_assets_padding():
    # 6 decimals → one share = 1_000_000 → padded to 64 hex after the selector
    cd = encode_convert_to_assets(6)
    assert cd.startswith(SEL_CONVERT_TO_ASSETS)
    arg = cd[len(SEL_CONVERT_TO_ASSETS):]
    assert len(arg) == 64
    assert int(arg, 16) == 10 ** 6


def test_decode_uint():
    assert decode_uint(_u256(1)) == 1
    assert decode_uint(_u256(123456789)) == 123456789
    # fail-CLOSED on revert/empty/garbage
    assert decode_uint("0x") is None
    assert decode_uint("") is None
    assert decode_uint(None) is None
    assert decode_uint(123) is None
    assert decode_uint("notahexstring") is None
    # wider-than-32-byte return → take last 32 bytes
    assert decode_uint("0x" + "00" * 32 + f"{42:064x}") == 42


# ── 2. real 4626 read → intrinsic NAV, nav_source=onchain_4626 ─────────────────────────────────────
def test_4626_intrinsic_nav_computed():
    # A vault at exactly $1.00/share via convertToAssets: 6 decimals, 1 share → 1_000_000 assets.
    rpc = _FakeRpc({
        SEL_DECIMALS: _u256(6),
        SEL_TOTAL_SUPPLY: _u256(500_000 * 10 ** 6),
        SEL_TOTAL_ASSETS: _u256(500_000 * 10 ** 6),
        SEL_CONVERT_TO_ASSETS: _u256(1_000_000),   # 1 share -> 1.0 asset
    })
    reader = OnchainNAVReader(rpc_fetcher=rpc)
    res = reader.read_nav("VAULT", "0xabc0000000000000000000000000000000000001")
    assert res.nav_source == NAV_SOURCE_ONCHAIN
    assert abs(res.onchain_nav_usd - 1.0) < 1e-9
    assert res.decimals == 6
    assert "convertToAssets" in res.reason


def test_4626_intrinsic_nav_above_par_is_a_signal():
    # convertToAssets returns 1.0234 → a real intrinsic premium over the $1.00 marketing par.
    rpc = _FakeRpc({
        SEL_DECIMALS: _u256(18),
        SEL_TOTAL_SUPPLY: _u256(10 ** 24),
        SEL_TOTAL_ASSETS: _u256(int(1.0234 * 10 ** 24)),
        SEL_CONVERT_TO_ASSETS: _u256(int(1.0234 * 10 ** 18)),
    })
    res = OnchainNAVReader(rpc_fetcher=rpc).read_nav("VAULT", "0xabc0000000000000000000000000000000000001")
    assert res.nav_source == NAV_SOURCE_ONCHAIN
    assert abs(res.onchain_nav_usd - 1.0234) < 1e-6


def test_ratio_fallback_when_no_convert():
    # convertToAssets reverts, but totalAssets/totalSupply give a clean par ratio.
    rpc = _FakeRpc({
        SEL_DECIMALS: _u256(6),
        SEL_TOTAL_SUPPLY: _u256(2_000_000 * 10 ** 6),
        SEL_TOTAL_ASSETS: _u256(2_000_000 * 10 ** 6),
        SEL_CONVERT_TO_ASSETS: _FakeRpc.REVERT,
    })
    res = OnchainNAVReader(rpc_fetcher=rpc).read_nav("VAULT", "0xabc0000000000000000000000000000000000001")
    assert res.nav_source == NAV_SOURCE_ONCHAIN
    assert abs(res.onchain_nav_usd - 1.0) < 1e-9
    assert "totalAssets/totalSupply" in res.reason


# ── 3. fail-CLOSED paths ───────────────────────────────────────────────────────────────────────────
def test_non_4626_reverts_to_estimate():
    # decimals reads, but neither totalAssets nor convertToAssets exist (permissioned token).
    rpc = _FakeRpc({
        SEL_DECIMALS: _u256(6),
        SEL_TOTAL_SUPPLY: _u256(1_000_000 * 10 ** 6),
        SEL_TOTAL_ASSETS: _FakeRpc.REVERT,
        SEL_CONVERT_TO_ASSETS: _FakeRpc.REVERT,
    })
    res = OnchainNAVReader(rpc_fetcher=rpc).read_nav("BUIDL", "0xdef0000000000000000000000000000000000002")
    assert res.nav_source == NAV_SOURCE_ESTIMATE
    assert res.onchain_nav_usd is None


def test_rpc_down_fails_closed():
    res = OnchainNAVReader(rpc_fetcher=_FakeRpc(down=True)).read_nav(
        "VAULT", "0xabc0000000000000000000000000000000000001")
    assert res.nav_source == NAV_SOURCE_ESTIMATE
    assert res.onchain_nav_usd is None
    assert res.rpc_endpoint is None


def test_no_contract_fails_closed():
    res = OnchainNAVReader(rpc_fetcher=_FakeRpc()).read_nav("VBILL", None)
    assert res.nav_source == NAV_SOURCE_ESTIMATE
    assert res.onchain_nav_usd is None
    assert "no public token contract" in res.reason


def test_out_of_band_nav_rejected():
    # A mis-decoded / wrong-ABI read yields a wildly-off NAV → rejected, fail-CLOSED to estimate.
    rpc = _FakeRpc({
        SEL_DECIMALS: _u256(6),
        SEL_TOTAL_SUPPLY: _u256(1_000_000 * 10 ** 6),
        SEL_TOTAL_ASSETS: _u256(1_000_000 * 10 ** 6),
        SEL_CONVERT_TO_ASSETS: _u256(50_000 * 10 ** 6),   # 1 share -> 50,000 assets → absurd
    })
    res = OnchainNAVReader(rpc_fetcher=rpc).read_nav("VAULT", "0xabc0000000000000000000000000000000000001")
    assert res.nav_source == NAV_SOURCE_ESTIMATE
    assert res.onchain_nav_usd is None
    assert "sanity band" in res.reason


def test_zero_supply_fails_closed():
    rpc = _FakeRpc({SEL_DECIMALS: _u256(6), SEL_TOTAL_SUPPLY: _u256(0)})
    res = OnchainNAVReader(rpc_fetcher=rpc).read_nav("VAULT", "0xabc0000000000000000000000000000000000001")
    assert res.nav_source == NAV_SOURCE_ESTIMATE


def test_no_mainnet_endpoint_responds():
    # chainId != 1 on every endpoint → no usable RPC → estimate.
    rpc = _FakeRpc({SEL_DECIMALS: _u256(6)}, chain_id=137)  # polygon, not mainnet
    res = OnchainNAVReader(rpc_fetcher=rpc).read_nav("VAULT", "0xabc0000000000000000000000000000000000001")
    assert res.nav_source == NAV_SOURCE_ESTIMATE
    assert "no keyless mainnet RPC" in res.reason


# ── 4. determinism ────────────────────────────────────────────────────────────────────────────────
def test_deterministic():
    sel = {
        SEL_DECIMALS: _u256(6),
        SEL_TOTAL_SUPPLY: _u256(10 ** 12),
        SEL_TOTAL_ASSETS: _u256(int(1.005 * 10 ** 12)),
        SEL_CONVERT_TO_ASSETS: _u256(int(1.005 * 10 ** 6)),
    }
    a = OnchainNAVReader(rpc_fetcher=_FakeRpc(dict(sel))).read_nav("V", "0xabc0000000000000000000000000000000000001")
    b = OnchainNAVReader(rpc_fetcher=_FakeRpc(dict(sel))).read_nav("V", "0xabc0000000000000000000000000000000000001")
    # identical injected responses → byte-identical derived NAV (deterministic)
    assert a.onchain_nav_usd == b.onchain_nav_usd
    assert abs(a.onchain_nav_usd - 1.005) < 1e-5


# ── 5. safety_board wiring (additive, fail-CLOSED) ─────────────────────────────────────────────────
def _pools_payload(pools):
    return {"status": "success", "data": pools}


class _FakePoolsFetcher:
    def __init__(self, payload):
        self._payload = payload

    def __call__(self, url):
        return self._payload


def test_safety_board_onchain_fields_present(tmp_path):
    asset = _asset("VAULT")
    rpc = _FakeRpc({
        SEL_DECIMALS: _u256(6),
        SEL_TOTAL_SUPPLY: _u256(10 ** 12),
        SEL_TOTAL_ASSETS: _u256(int(1.01 * 10 ** 12)),
        SEL_CONVERT_TO_ASSETS: _u256(int(1.01 * 10 ** 6)),
    })
    rep = sb.build_report(
        write=False, fetcher=_FakePoolsFetcher(_pools_payload([])), assets=[asset],
        onchain=True, rpc_fetcher=rpc,
    )
    row = rep["assets"][0]
    assert row["nav_source"] == NAV_SOURCE_ONCHAIN
    assert abs(row["onchain_nav_usd"] - 1.01) < 1e-6
    # divergence from $1.00 marketing ≈ +1%
    assert abs(row["onchain_nav_divergence_pct"] - 1.0) < 1e-3
    cov = rep["onchain_nav_coverage"]
    assert cov["n_onchain_4626"] == 1
    assert cov["n_off_chain_estimate"] == 0
    assert cov["divergences"][0]["symbol"] == "VAULT"


def test_safety_board_estimate_when_rpc_down(tmp_path):
    asset = _asset("VAULT")
    rep = sb.build_report(
        write=False, fetcher=_FakePoolsFetcher(_pools_payload([])), assets=[asset],
        onchain=True, rpc_fetcher=_FakeRpc(down=True),
    )
    row = rep["assets"][0]
    assert row["nav_source"] == NAV_SOURCE_ESTIMATE
    assert row["onchain_nav_usd"] is None
    # the board STILL produced the row (verdict computed on the estimate)
    assert row["verdict"] in (sb.LIQUID, sb.THIN, sb.REDEMPTION_ONLY, sb.UNSAFE)
    assert rep["onchain_nav_coverage"]["n_onchain_4626"] == 0
    assert rep["onchain_nav_coverage"]["n_off_chain_estimate"] == 1


def test_safety_board_onchain_disabled(tmp_path):
    asset = _asset("VAULT")
    rep = sb.build_report(
        write=False, fetcher=_FakePoolsFetcher(_pools_payload([])), assets=[asset],
        onchain=False,
    )
    assert rep["onchain_nav_coverage"]["enabled"] is False
    assert rep["assets"][0]["nav_source"] == NAV_SOURCE_ESTIMATE


def test_safety_board_mixed_coverage(tmp_path):
    # one 4626 vault + one permissioned non-4626 → partial coverage (the honest result).
    v4626 = _asset("VAULT", contract="0xaaa0000000000000000000000000000000000001")
    perm = CollateralAsset(
        symbol="BUIDL", issuer="BlackRock", chain="ethereum", asset_class="tokenized_mmf",
        token_contract="0xbbb0000000000000000000000000000000000002", transfer_restricted=True,
        redemption_delay_days=1.0, redemption_fee_bps=0.0, min_redemption_usd=250_000.0,
        redemption_documented=True,
    )

    class _Router:
        def __call__(self, url, payload):
            if payload.get("method") == "eth_chainId":
                return {"result": _u256(1)}
            to = payload["params"][0]["to"]
            sel = payload["params"][0]["data"][:10]
            if to == _PROBE_4626_CONTRACT.lower() and sel == SEL_DECIMALS:
                return {"result": _u256(_PROBE_EXPECT_DECIMALS)}
            if to == "0xaaa0000000000000000000000000000000000001":
                table = {
                    SEL_DECIMALS: _u256(6),
                    SEL_TOTAL_SUPPLY: _u256(10 ** 12),
                    SEL_TOTAL_ASSETS: _u256(10 ** 12),
                    SEL_CONVERT_TO_ASSETS: _u256(10 ** 6),
                }
                return {"result": table.get(sel, "0x")}
            # permissioned token: decimals reads but no 4626 views
            if sel == SEL_DECIMALS:
                return {"result": _u256(6)}
            if sel == SEL_TOTAL_SUPPLY:
                return {"result": _u256(10 ** 12)}
            return {"error": {"code": 3, "message": "execution reverted"}}

    rep = sb.build_report(
        write=False, fetcher=_FakePoolsFetcher(_pools_payload([])), assets=[v4626, perm],
        onchain=True, rpc_fetcher=_Router(),
    )
    cov = rep["onchain_nav_coverage"]
    assert cov["n_onchain_4626"] == 1
    assert cov["n_off_chain_estimate"] == 1
    by_sym = {r["symbol"]: r for r in rep["assets"]}
    assert by_sym["VAULT"]["nav_source"] == NAV_SOURCE_ONCHAIN
    assert by_sym["BUIDL"]["nav_source"] == NAV_SOURCE_ESTIMATE


# ── 4. the canonical T6 coverage transparency block ────────────────────────────────────────────
def _coverage_invariants(cov, rows):
    """Shared invariants for the onchain_nav_coverage block: canonical keys present, counts
    consistent (onchain+estimate==total==len(rows)), assets_onchain matches per-asset nav_source,
    legacy aliases mirror the canonical counts, note is a non-empty string."""
    for k in ("onchain_4626", "off_chain_estimate", "total", "assets_onchain", "note"):
        assert k in cov, f"coverage block missing canonical key {k!r}"
    assert cov["total"] == cov["onchain_4626"] + cov["off_chain_estimate"]
    assert cov["total"] == len(rows)
    # assets_onchain must EXACTLY be the rows whose nav_source is the real on-chain read.
    expected = sorted(r["symbol"] for r in rows if r["nav_source"] == NAV_SOURCE_ONCHAIN)
    assert sorted(cov["assets_onchain"]) == expected
    assert len(cov["assets_onchain"]) == cov["onchain_4626"]
    # legacy aliases stay in sync (back-compat)
    assert cov["n_onchain_4626"] == cov["onchain_4626"]
    assert cov["n_off_chain_estimate"] == cov["off_chain_estimate"]
    assert isinstance(cov["note"], str) and cov["note"]


def test_coverage_block_canonical_shape_mixed():
    """Mixed universe: one real 4626 + one permissioned non-4626 → coverage block carries the
    canonical T6 keys with counts/assets_onchain matching per-asset nav_source."""
    v4626 = _asset("VAULT", contract="0xaaa0000000000000000000000000000000000001")
    perm = CollateralAsset(
        symbol="BUIDL", issuer="BlackRock", chain="ethereum", asset_class="tokenized_mmf",
        token_contract="0xbbb0000000000000000000000000000000000002", transfer_restricted=True,
        redemption_delay_days=1.0, redemption_fee_bps=0.0, min_redemption_usd=250_000.0,
        redemption_documented=True,
    )

    class _Router:
        def __call__(self, url, payload):
            if payload.get("method") == "eth_chainId":
                return {"result": _u256(1)}
            to = payload["params"][0]["to"]
            sel = payload["params"][0]["data"][:10]
            if to == _PROBE_4626_CONTRACT.lower() and sel == SEL_DECIMALS:
                return {"result": _u256(_PROBE_EXPECT_DECIMALS)}
            if to == "0xaaa0000000000000000000000000000000000001":
                table = {
                    SEL_DECIMALS: _u256(6), SEL_TOTAL_SUPPLY: _u256(10 ** 12),
                    SEL_TOTAL_ASSETS: _u256(10 ** 12), SEL_CONVERT_TO_ASSETS: _u256(10 ** 6),
                }
                return {"result": table.get(sel, "0x")}
            if sel == SEL_DECIMALS:
                return {"result": _u256(6)}
            if sel == SEL_TOTAL_SUPPLY:
                return {"result": _u256(10 ** 12)}
            return {"error": {"code": 3, "message": "execution reverted"}}

    rep = sb.build_report(write=False, fetcher=_FakePoolsFetcher(_pools_payload([])),
                          assets=[v4626, perm], onchain=True, rpc_fetcher=_Router())
    cov = rep["onchain_nav_coverage"]
    _coverage_invariants(cov, rep["assets"])
    assert cov["onchain_4626"] == 1
    assert cov["off_chain_estimate"] == 1
    assert cov["assets_onchain"] == ["VAULT"]
    assert "VAULT" in cov["note"]


def test_coverage_block_zero_when_rpc_down():
    """Fail-CLOSED: RPC down → 0 on-chain, all estimate, total==len, board still valid, note honest."""
    a = _asset("VAULT")
    b = _asset("OTHER", contract="0xccc0000000000000000000000000000000000003")
    rep = sb.build_report(write=False, fetcher=_FakePoolsFetcher(_pools_payload([])),
                          assets=[a, b], onchain=True, rpc_fetcher=_FakeRpc(down=True))
    cov = rep["onchain_nav_coverage"]
    _coverage_invariants(cov, rep["assets"])
    assert cov["onchain_4626"] == 0
    assert cov["off_chain_estimate"] == 2
    assert cov["total"] == 2
    assert cov["assets_onchain"] == []
    assert "0/2" in cov["note"]
    # board still valid: every row carries a verdict from the closed set
    for row in rep["assets"]:
        assert row["verdict"] in (sb.LIQUID, sb.THIN, sb.REDEMPTION_ONLY, sb.UNSAFE)


def test_coverage_block_full_registry_counts_match_nav_source():
    """On the REAL registry (no rpc → fail-closed estimate everywhere) the coverage counts and
    assets_onchain are internally consistent with per-asset nav_source. Hermetic (no network)."""
    rep = sb.build_report(write=False, fetcher=_FakePoolsFetcher(_pools_payload([])),
                          onchain=True, rpc_fetcher=_FakeRpc(down=True))
    _coverage_invariants(rep["onchain_nav_coverage"], rep["assets"])
