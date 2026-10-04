"""Tests for spa_core/capital_shadow/{rpc,abi,tokens,simulate,exchange_sim}.py (ADR-556 RM-LIVE-01).

Nothing here touches the network (RpcClient's ``post`` is always injected) except the ONE smoke test at
the bottom, which only runs when ``SPA_LIVE_RPC_SMOKE=1`` is set and hits the real public RPCs declared
in ``contract.RPC_OPERATORS``.
"""
from __future__ import annotations

import json
import os

import pytest

from spa_core.capital_shadow import abi, contract, exchange_sim, simulate, tokens
from spa_core.capital_shadow.keccak import selector as sel
from spa_core.capital_shadow.rpc import ForbiddenMethod, RpcClient

try:
    from eth_abi import encode as eth_abi_encode
    HAVE_ETH_ABI = True
except Exception:  # noqa: BLE001 — optional cross-check only
    HAVE_ETH_ABI = False


# ───────────────────────────── shared fixtures / helpers ───────────────────────────────────────────
USDC = tokens.token(1, "USDC")["address"]
AAVE_POOL = tokens.venue("aave_v3")["address"]
COMET = tokens.venue("compound_v3")["address"]
FLUID = tokens.venue("fluid_fusdc")["address"]

SEL_DECIMALS = sel("decimals()")
SEL_BALANCEOF = sel("balanceOf(address)")
SEL_ALLOWANCE = sel("allowance(address,address)")
SEL_SUPPLY_AAVE = sel("supply(address,uint256,address,uint16)")
SEL_SUPPLY_COMET = sel("supply(address,uint256)")
SEL_WITHDRAW_AAVE = sel("withdraw(address,uint256,address)")
SEL_WITHDRAW_COMET = sel("withdraw(address,uint256)")
SEL_DEPOSIT_4626 = sel("deposit(uint256,address)")
SEL_REDEEM_4626 = sel("redeem(uint256,address,address)")
SEL_PREVIEW_DEPOSIT = sel("previewDeposit(uint256)")
SEL_ASSET = sel("asset()")
SEL_APPROVE = sel("approve(address,uint256)")

THREE_OPERATORS = [("https://op-a.example", "OpA"), ("https://op-b.example", "OpB"), ("https://op-c.example", "OpC")]


def hex_uint(n: int) -> str:
    return "0x" + format(int(n), "064x")


def hex_address(addr: str) -> str:
    return "0x" + abi.encode_address(addr).hex()


def make_intent(**overrides) -> dict:
    # notional_unit defaults to "base_units" because every existing fixture already passes a
    # pre-scaled base-unit amount (review #4 fixed the scaling bug; it did not change what these
    # long-standing fixtures mean) — tests of the HUMAN path set notional_unit="USDC" explicitly.
    base = {
        "intent_id": "intent-" + overrides.get("action_type", "SUPPLY") + "-" + str(overrides.get("notional", 0)),
        "action_type": contract.ACTION_SUPPLY,
        "network_or_venue": "aave_v3",
        "from_asset": "USDC",
        "notional": 1_000_000,
        "notional_unit": "base_units",
    }
    base.update(overrides)
    return base


class FakeNode:
    """A deterministic stand-in for a JSON-RPC node, shared across every declared operator.

    Keyed by (to_lower, selector) for ``eth_call``/``eth_estimateGas``; special-cased for the other
    allow-listed methods. ``unavailable_operators`` makes an operator raise (simulating a dead node);
    ``per_operator`` lets ONE operator answer a specific (to, selector) differently, for disagreement
    tests. Never touches the network — this IS the network, for the test.
    """

    def __init__(self, *, chain_id_hex="0x1", block_number_hex="0x100", block_hash="0x" + "11" * 32,
                 code_by_address=None, call_table=None, gas_table=None, unavailable_operators=(),
                 per_operator=None):
        self.chain_id_hex = chain_id_hex
        self.block_number_hex = block_number_hex
        self.block_hash = block_hash
        self.code_by_address = {k.lower(): v for k, v in (code_by_address or {}).items()}
        self.call_table = call_table or {}
        self.gas_table = gas_table or {}
        self.unavailable_operators = set(unavailable_operators)
        self.per_operator = per_operator or {}  # {(to_lower, selector): {url: entry}}
        self.calls = []

    def post(self, url, payload):
        self.calls.append((url, payload))
        method, params = payload["method"], payload["params"]
        if url in self.unavailable_operators:
            raise ConnectionError("simulated unavailable operator")
        if method == "eth_chainId":
            return {"jsonrpc": "2.0", "id": 1, "result": self.chain_id_hex}
        if method == "eth_blockNumber":
            return {"jsonrpc": "2.0", "id": 1, "result": self.block_number_hex}
        if method == "eth_getBlockByNumber":
            return {"jsonrpc": "2.0", "id": 1, "result": {"hash": self.block_hash, "number": params[0]}}
        if method == "eth_getCode":
            addr = params[0].lower()
            return {"jsonrpc": "2.0", "id": 1, "result": self.code_by_address.get(addr, "0x")}
        if method in ("eth_call", "eth_estimateGas"):
            tx = params[0]
            key = (tx.get("to", "").lower(), (tx.get("data") or "")[:10].lower())
            per_op = self.per_operator.get(key, {})
            entry = per_op[url] if url in per_op else (self.call_table if method == "eth_call" else self.gas_table).get(key)
            if entry is None:
                return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": f"no fake entry for {key}"}}
            if isinstance(entry, dict) and "error" in entry:
                return {"jsonrpc": "2.0", "id": 1, "error": entry["error"]}
            return {"jsonrpc": "2.0", "id": 1, "result": entry}
        return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "unscripted method in FakeNode"}}


def client_with(node: FakeNode, *, chain_id=1, endpoints=None) -> RpcClient:
    return RpcClient(chain_id=chain_id, endpoints=endpoints or THREE_OPERATORS, post=node.post)


def aave_pass_node(**kw) -> FakeNode:
    """Every check PASSES for a 1,000,000-base-unit SUPPLY on aave_v3, unless ``kw`` overrides a piece."""
    defaults = dict(
        code_by_address={AAVE_POOL: "0x6080604052", USDC: "0x6080604052"},
        call_table={
            (USDC.lower(), SEL_DECIMALS): hex_uint(6),
            (USDC.lower(), SEL_BALANCEOF): hex_uint(1_000_000),
            (USDC.lower(), SEL_ALLOWANCE): hex_uint(1_000_000),
            (AAVE_POOL.lower(), SEL_SUPPLY_AAVE): "0x",
        },
        gas_table={(AAVE_POOL.lower(), SEL_SUPPLY_AAVE): hex_uint(150_000)},
    )
    defaults.update(kw)
    return FakeNode(**defaults)


# ══════════════════════════════ rpc.py: ForbiddenMethod (allow-list) ══════════════════════════════
FORBIDDEN_METHODS = [
    "eth_sendRawTransaction", "eth_sendTransaction", "eth_sign", "personal_sign", "eth_signTypedData_v4",
    "Eth_Call", "ETH_CALL", "eth_Call", "eth_accounts", "eth_getBalance", "net_version",
]


@pytest.mark.parametrize("method", FORBIDDEN_METHODS)
def test_request_refuses_every_method_outside_allow_list_before_io(method):
    calls = []

    def spy_post(url, payload):
        calls.append((url, payload))
        return {"result": "0xdeadbeef"}

    client = RpcClient(chain_id=1, endpoints=THREE_OPERATORS, post=spy_post)
    with pytest.raises(ForbiddenMethod):
        client.request(THREE_OPERATORS[0][0], method, [])
    assert calls == []  # post must NEVER be invoked for a refused method
    assert client.security_events and client.security_events[-1]["kind"] == "forbidden_method"


def test_request_refuses_non_list_params_dict_before_io():
    calls = []
    client = RpcClient(chain_id=1, endpoints=THREE_OPERATORS, post=lambda u, p: calls.append((u, p)))
    with pytest.raises(ForbiddenMethod):
        client.request(THREE_OPERATORS[0][0], "eth_call", {"to": AAVE_POOL, "data": "0x"})  # dict, not list
    assert calls == []


def test_request_refuses_batch_style_method_before_io():
    """A JSON-RPC batch smuggled in as the METHOD itself being a list of request names is refused."""
    calls = []
    client = RpcClient(chain_id=1, endpoints=THREE_OPERATORS, post=lambda u, p: calls.append((u, p)))
    with pytest.raises(ForbiddenMethod):
        client.request(THREE_OPERATORS[0][0], ["eth_call", "eth_blockNumber"], [])  # method itself is a list
    assert calls == []


def test_request_refuses_non_string_method_types():
    calls = []
    client = RpcClient(chain_id=1, endpoints=THREE_OPERATORS, post=lambda u, p: calls.append((u, p)))
    for bad_method in (None, 42, {"method": "eth_call"}, ("eth_call",)):
        with pytest.raises(ForbiddenMethod):
            client.request(THREE_OPERATORS[0][0], bad_method, [])
    assert calls == []


def test_quorum_also_refuses_forbidden_method_before_polling_any_operator():
    calls = []
    client = RpcClient(chain_id=1, endpoints=THREE_OPERATORS, post=lambda u, p: calls.append((u, p)))
    with pytest.raises(ForbiddenMethod):
        client.quorum("eth_sendRawTransaction", ["0xsignedtx"], None)
    assert calls == []


def test_allowed_methods_do_not_raise_forbidden():
    client = RpcClient(chain_id=1, endpoints=THREE_OPERATORS, post=lambda u, p: {"result": "0x1"})
    for m in sorted(contract.RPC_ALLOWED_METHODS):
        client.request(THREE_OPERATORS[0][0], m, [])  # must not raise


# ══════════════════════════════ rpc.py: pin_block / quorum mechanics ══════════════════════════════
def test_pin_block_measured_on_independent_agreement():
    node = FakeNode(block_number_hex="0x100", block_hash="0x" + "aa" * 32)
    client = client_with(node)
    pinned = client.pin_block()
    assert pinned["state"] == contract.MEASURED
    assert pinned["number"] == 0x100 - 2
    assert pinned["hash"] == "0x" + "aa" * 32
    assert len(set(pinned["operators"])) >= contract.RPC_MIN_INDEPENDENT_OPERATORS


def test_pin_block_not_measured_when_fewer_than_min_operators_answer():
    node = FakeNode(unavailable_operators={THREE_OPERATORS[1][0], THREE_OPERATORS[2][0]})
    client = client_with(node)
    pinned = client.pin_block()
    assert pinned["state"] == contract.NOT_MEASURED
    assert "eth_blockNumber" in pinned["reason"]


def test_pin_block_not_measured_on_block_hash_disagreement():
    # eth_getBlockByNumber is called per-operator by url, so we can make each operator disagree.
    per_operator_hash = {url: "0x" + f"{i:02x}" * 32 for i, (url, _) in enumerate(THREE_OPERATORS, start=1)}

    class DisagreeingNode(FakeNode):
        def post(self, url, payload):
            if payload["method"] == "eth_getBlockByNumber":
                self.calls.append((url, payload))
                return {"jsonrpc": "2.0", "id": 1, "result": {"hash": per_operator_hash[url]}}
            return super().post(url, payload)

    node = DisagreeingNode()
    client = client_with(node)
    pinned = client.pin_block()
    assert pinned["state"] == contract.NOT_MEASURED
    assert "agreement" in pinned["reason"]


def test_quorum_measured_pass():
    node = aave_pass_node()
    client = client_with(node)
    pinned = client.pin_block()
    q = client.quorum("eth_call", [{"to": USDC, "data": abi.function_call("decimals()", [])}], pinned["number"])
    assert q["state"] == contract.MEASURED
    assert abi.decode_uint256(q["result"]) == 6
    assert len(set(q["operators"])) >= 2


def test_quorum_not_measured_when_unavailable():
    node = FakeNode(unavailable_operators={THREE_OPERATORS[0][0], THREE_OPERATORS[1][0]},
                    call_table={(USDC.lower(), SEL_DECIMALS): hex_uint(6)})
    client = client_with(node)
    pinned = client.pin_block()
    assert pinned["state"] == contract.NOT_MEASURED  # also starved — but exercise quorum() directly too
    q = client.quorum("eth_call", [{"to": USDC, "data": abi.function_call("decimals()", [])}], 100)
    assert q["state"] == contract.NOT_MEASURED
    assert "disagreement" not in q


def test_quorum_not_measured_disagreement_recorded_as_security_event():
    key = (USDC.lower(), SEL_DECIMALS)
    node = FakeNode(call_table={key: hex_uint(6)},
                    per_operator={key: {THREE_OPERATORS[0][0]: hex_uint(6), THREE_OPERATORS[1][0]: hex_uint(18),
                                        THREE_OPERATORS[2][0]: hex_uint(9)}})
    client = client_with(node)
    q = client.quorum("eth_call", [{"to": USDC, "data": abi.function_call("decimals()", [])}], 100)
    assert q["state"] == contract.NOT_MEASURED
    assert q.get("disagreement") is True
    assert any(e["kind"] == "quorum_disagreement" for e in client.security_events)


def test_quorum_measured_revert_on_agreement():
    key = (AAVE_POOL.lower(), SEL_SUPPLY_AAVE)
    revert_entry = {"error": {"code": 3, "message": "execution reverted: insufficient allowance",
                              "data": "0x08c379a0"}}
    node = FakeNode(call_table={key: revert_entry})
    client = client_with(node)
    q = client.quorum("eth_call", [{"to": AAVE_POOL, "data": "0x" + SEL_SUPPLY_AAVE[2:] + "00" * 32}], 100)
    assert q["state"] == contract.MEASURED
    assert q["revert"] is True


def test_quorum_measured_with_dissenting_third_operator_flags_dissent_and_security_event():
    """review #5 (post-impl audit): a 2-of-3 agreement with a dissenting third operator used to come
    back MEASURED with no trace of the dissent anywhere. Now: still MEASURED (the quorum IS satisfied)
    but the response carries "dissent" and a quorum_disagreement security event is recorded."""
    key = (USDC.lower(), SEL_DECIMALS)
    node = FakeNode(call_table={key: hex_uint(6)}, per_operator={key: {THREE_OPERATORS[2][0]: hex_uint(18)}})
    client = client_with(node)
    q = client.quorum("eth_call", [{"to": USDC, "data": abi.function_call("decimals()", [])}], 100)
    assert q["state"] == contract.MEASURED
    assert abi.decode_uint256(q["result"]) == 6
    assert q.get("dissent") == [THREE_OPERATORS[2][1]]
    event = next(e for e in client.security_events if e["kind"] == "quorum_disagreement")
    assert event["detail"]["dissenting"][0]["operator"] == THREE_OPERATORS[2][1]
    # the raw dissenting value must never be echoed back verbatim — only a short digest
    assert "18" not in json.dumps(event["detail"]["dissenting"])


def test_quorum_measured_result_vs_revert_dissent_is_flagged_too():
    """The same bug, the other shape: 2 operators agree on a RESULT while the 3rd reports a REVERT —
    still MEASURED on the result, with the reverting operator named as a dissenter."""
    key = (AAVE_POOL.lower(), SEL_SUPPLY_AAVE)
    node = FakeNode(call_table={key: "0x"},
                    per_operator={key: {THREE_OPERATORS[2][0]: {"error": {"code": 3, "message": "execution reverted"}}}})
    client = client_with(node)
    q = client.quorum("eth_call", [{"to": AAVE_POOL, "data": "0x" + SEL_SUPPLY_AAVE[2:] + "00" * 32}], 100)
    assert q["state"] == contract.MEASURED
    assert not q.get("revert")
    assert q.get("dissent") == [THREE_OPERATORS[2][1]]


def test_pin_block_measured_with_dissenting_block_hash_flags_dissent():
    """Same bug class in pin_block's hash-agreement step (rpc.py's other silent-return site)."""
    per_operator_hash = {THREE_OPERATORS[2][0]: "0x" + "ff" * 32}

    class DissentingHashNode(FakeNode):
        def post(self, url, payload):
            if payload["method"] == "eth_getBlockByNumber" and url in per_operator_hash:
                self.calls.append((url, payload))
                return {"jsonrpc": "2.0", "id": 1, "result": {"hash": per_operator_hash[url]}}
            return super().post(url, payload)

    node = DissentingHashNode(block_hash="0x" + "aa" * 32)
    client = client_with(node)
    pinned = client.pin_block()
    assert pinned["state"] == contract.MEASURED
    assert pinned["hash"] == "0x" + "aa" * 32
    assert pinned.get("dissent") == [THREE_OPERATORS[2][1]]
    event = next(e for e in client.security_events if e["kind"] == "quorum_disagreement")
    assert event["detail"]["dissenting"][0]["operator"] == THREE_OPERATORS[2][1]


def test_quorum_estimategas_treats_rejecting_operator_as_unavailable_not_global_failure():
    """One operator rejecting the 3rd (overrides) param on eth_estimateGas must not flip a legitimate
    2-of-3 agreement into disagreement or unavailability."""
    key = (AAVE_POOL.lower(), SEL_SUPPLY_AAVE)
    node = FakeNode(gas_table={key: hex_uint(150_000)},
                    per_operator={key: {THREE_OPERATORS[2][0]: {"error": {"code": -32602,
                                                                          "message": "overrides not supported"}}}})
    client = client_with(node)
    tx = {"to": AAVE_POOL, "data": "0x" + SEL_SUPPLY_AAVE[2:] + "00" * 32}
    q = client.quorum("eth_estimateGas", [tx, {}], 100)
    assert q["state"] == contract.MEASURED
    assert abi.decode_uint256(q["result"]) == 150_000


# ══════════════════════════════ abi.py: encode/decode vectors ══════════════════════════════════════
def test_function_call_approve_matches_eth_abi_when_importable():
    data = abi.function_call("approve(address,uint256)", [AAVE_POOL, 1_000_000])
    assert data.startswith(SEL_APPROVE)
    if HAVE_ETH_ABI:
        expected = SEL_APPROVE + eth_abi_encode(["address", "uint256"], [AAVE_POOL, 1_000_000]).hex()
        assert data == expected
    else:
        assert len(data) == 2 + 8 + 64 * 2


def test_function_call_supply_aave_matches_eth_abi_when_importable():
    data = abi.function_call("supply(address,uint256,address,uint16)", [USDC, 1_000_000, AAVE_POOL, 0])
    if HAVE_ETH_ABI:
        expected = SEL_SUPPLY_AAVE + eth_abi_encode(["address", "uint256", "address", "uint16"],
                                                     [USDC, 1_000_000, AAVE_POOL, 0]).hex()
        assert data == expected


def test_function_call_deposit_4626_matches_eth_abi_when_importable():
    data = abi.function_call("deposit(uint256,address)", [1_000_000, FLUID])
    if HAVE_ETH_ABI:
        expected = SEL_DEPOSIT_4626 + eth_abi_encode(["uint256", "address"], [1_000_000, FLUID]).hex()
        assert data == expected


def test_decode_uint256_bool_address_roundtrip():
    assert abi.decode_uint256(hex_uint(42)) == 42
    assert abi.decode_bool(hex_uint(1)) is True
    assert abi.decode_bool(hex_uint(0)) is False
    assert abi.decode_address(hex_address(USDC)).lower() == USDC.lower()


def test_decode_revert_reason_error_string():
    # Error(string) with reason "insufficient allowance" — built by hand via abi helpers.
    reason = "insufficient allowance"
    body = hex_uint(0x20)[2:] + format(len(reason), "064x") + reason.encode().hex().ljust(64, "0")
    data = "0x08c379a0" + body
    assert abi.decode_revert_reason(data) == reason


def test_decode_revert_reason_none_for_other_shapes():
    assert abi.decode_revert_reason("0xdeadbeef") is None
    assert abi.decode_revert_reason(None) is None


def test_decode_call_matches_known_signature():
    data = abi.function_call("approve(address,uint256)", [AAVE_POOL, 5])
    decoded = abi.decode_call(data, ["transfer(address,uint256)", "approve(address,uint256)"])
    assert decoded["signature"] == "approve(address,uint256)"
    assert decoded["args"][1] == 5


def test_decode_call_returns_none_for_unknown_selector():
    data = abi.function_call("approve(address,uint256)", [AAVE_POOL, 5])
    assert abi.decode_call(data, ["transfer(address,uint256)"]) is None


# ══════════════════════════════ abi.py: EIP-55 checksum (owner-Safe sender override) ══════════════
# Official EIP-55 test vectors (https://eips.ethereum.org/EIPS/eip-155... checksum spec) — independent
# of this package's own keccak implementation already being cross-checked in test_capital_shadow_keccak.
EIP55_VECTORS = (
    "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
    "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
    "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
    "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb",
)


def test_to_checksum_address_matches_eip55_vectors():
    for v in EIP55_VECTORS:
        assert abi.to_checksum_address(v) == v


def test_is_checksummed_address_accepts_eip55_vectors_and_all_lower_and_all_upper():
    for v in EIP55_VECTORS:
        assert abi.is_checksummed_address(v) is True
    assert abi.is_checksummed_address(EIP55_VECTORS[0].lower()) is True
    assert abi.is_checksummed_address(EIP55_VECTORS[0].upper().replace("X", "x", 1)) is True


def test_is_checksummed_address_rejects_bad_checksum_and_malformed():
    bad_checksum = EIP55_VECTORS[0][:-2] + "ED"  # mixed-case, last byte's case flipped -> wrong checksum
    assert abi.is_checksummed_address(bad_checksum) is False
    assert abi.is_checksummed_address("0x1234") is False
    assert abi.is_checksummed_address(None) is False
    assert abi.is_checksummed_address(12345) is False
    assert abi.is_checksummed_address("not-an-address-at-all") is False


def test_to_checksum_address_refuses_wrong_length_or_non_hex():
    with pytest.raises(ValueError):
        abi.to_checksum_address("0x1234")
    with pytest.raises(ValueError):
        abi.to_checksum_address("0x" + "zz" * 20)


# ══════════════════════════════ tokens.py: registry + slot derivation ═════════════════════════════
def test_registry_digest_is_stable_and_a_hex_digest():
    d1 = tokens.registry_digest()
    d2 = tokens.registry_digest()
    assert d1 == d2
    assert len(d1) == 64
    int(d1, 16)  # must parse as hex


def test_balance_override_word_refuses_the_blacklist_high_bit():
    tokens.balance_override_word(tokens.MAX_SAFE_BALANCE)  # must not raise
    with pytest.raises(ValueError):
        tokens.balance_override_word(tokens.MAX_SAFE_BALANCE + 1)
    with pytest.raises(ValueError):
        tokens.balance_override_word(1 << 255)


def test_balance_and_allowance_slots_are_deterministic_and_distinct():
    owner = "0x" + "11" * 20
    spender = "0x" + "22" * 20
    s1 = tokens.balance_slot(owner, 9)
    s2 = tokens.balance_slot(owner, 9)
    assert s1 == s2
    s3 = tokens.allowance_slot(owner, spender, 10)
    assert s3 != s1
    # swapping owner/spender must change the slot — the mapping is NOT symmetric
    s4 = tokens.allowance_slot(spender, owner, 10)
    assert s4 != s3


def test_venue_kinds_are_the_adr_enum():
    for name, ven in tokens.VENUES.items():
        assert ven["kind"] in {"aave_pool", "comet", "erc4626", "permissioned"}, name


def test_maple_is_permissioned_in_the_contract_set():
    assert "maple" in contract.PERMISSIONED_VENUES
    assert tokens.venue("maple")["kind"] == "permissioned"


# ══════════════════════════════ tokens.py: to_base_units (review #4, post-impl audit) ══════════════
_USDC_TOK = tokens.token(1, "USDC")


def test_to_base_units_scales_human_amount_exactly():
    # the exact example from the review: 1000 USDC (human) must become 1_000_000_000 base units,
    # not 1000 (the bug: "1000 USDC" was simulated as 0.001 USDC).
    assert tokens.to_base_units(1000, "USDC", _USDC_TOK) == 1_000_000_000
    assert tokens.to_base_units("1000", "USDC", _USDC_TOK) == 1_000_000_000
    assert tokens.to_base_units(1, "USDC", _USDC_TOK) == 1_000_000


def test_to_base_units_base_units_passthrough():
    assert tokens.to_base_units(1_000_000_000, "base_units", _USDC_TOK) == 1_000_000_000
    assert tokens.to_base_units(0, "base_units", _USDC_TOK) == 0


def test_to_base_units_refuses_non_integral_base_units():
    with pytest.raises(ValueError):
        tokens.to_base_units(1_000_000.5, "base_units", _USDC_TOK)


def test_to_base_units_refuses_human_precision_finer_than_decimals():
    # USDC has 6 decimals — a 7th decimal digit has no base-unit representation and must be
    # refused, never silently truncated/rounded.
    with pytest.raises(ValueError):
        tokens.to_base_units("1000.0000001", "USDC", _USDC_TOK)


def test_to_base_units_refuses_negative():
    with pytest.raises(ValueError):
        tokens.to_base_units(-1, "USDC", _USDC_TOK)
    with pytest.raises(ValueError):
        tokens.to_base_units(-1, "base_units", _USDC_TOK)


def test_to_base_units_refuses_unrecognised_unit():
    with pytest.raises(ValueError):
        tokens.to_base_units(1000, "ETH", _USDC_TOK)
    with pytest.raises(ValueError):
        tokens.to_base_units(1000, None, _USDC_TOK)


def test_to_base_units_refuses_unknown_token():
    with pytest.raises(ValueError):
        tokens.to_base_units(1000, "base_units", None)


# ══════════════════════════════ simulate.py: encode_action ═══════════════════════════════════════
def test_encode_action_supply_aave_uses_synthetic_sender_as_onbehalfof():
    intent = make_intent(action_type=contract.ACTION_SUPPLY, network_or_venue="aave_v3", notional=1_000_000)
    encoded = simulate.encode_action(intent)
    sender = simulate.synthetic_sender(intent["intent_id"])
    assert encoded["to"].lower() == AAVE_POOL.lower()
    on_behalf = next(a["value"] for a in encoded["args"] if a["name"] == "onBehalfOf")
    assert on_behalf.lower() == sender.lower()
    assert encoded["data"].startswith(SEL_SUPPLY_AAVE)


def test_encode_action_approve_targets_the_token_not_the_venue():
    intent = make_intent(action_type=contract.ACTION_APPROVE, network_or_venue="aave_v3", from_asset="USDC",
                         notional=500_000)
    encoded = simulate.encode_action({**intent, "chain_id": 1})
    assert encoded["to"].lower() == USDC.lower()
    spender = next(a["value"] for a in encoded["args"] if a["name"] == "spender")
    assert spender.lower() == AAVE_POOL.lower()


def test_encode_action_permissioned_venue_still_builds_no_signing_payload_shape():
    """encode_action is never asked to build maple's calldata (simulate_intent returns earlier for a
    permissioned venue) — this test documents that calling it anyway raises rather than guessing."""
    intent = make_intent(action_type=contract.ACTION_SUPPLY, network_or_venue="maple", notional=1)
    with pytest.raises(ValueError):
        simulate.encode_action(intent)


def test_encode_action_scales_human_notional_by_decimals():
    """review #4: encode_action must scale "1000 USDC" (human) to 1_000_000_000 base units — the exact
    live-smoke bug (a nominal "1000" deposit returned 820 shares instead of ~820,239,983,xxx)."""
    intent = make_intent(action_type=contract.ACTION_SUPPLY, network_or_venue="aave_v3", from_asset="USDC",
                         notional=1000, notional_unit="USDC")
    encoded = simulate.encode_action(intent)
    amount_arg = next(a["value"] for a in encoded["args"] if a["name"] == "amount")
    assert amount_arg == 1_000_000_000


def test_encode_action_approve_scales_human_notional_by_decimals():
    intent = make_intent(action_type=contract.ACTION_APPROVE, network_or_venue="aave_v3", from_asset="USDC",
                         notional=1000, notional_unit="USDC")
    encoded = simulate.encode_action({**intent, "chain_id": 1})
    amount_arg = next(a["value"] for a in encoded["args"] if a["name"] == "amount")
    assert amount_arg == 1_000_000_000


def test_encode_action_uses_explicit_sender_override_as_onbehalfof():
    """verify.py's pre-sign check must see the OWNER'S SAFE in the embedded argument, not the
    synthetic placeholder — otherwise re-simulating "from the Safe" would prove nothing."""
    intent = make_intent(action_type=contract.ACTION_SUPPLY, network_or_venue="aave_v3", notional=1_000_000)
    encoded = simulate.encode_action(intent, sender=EIP55_VECTORS[0])
    on_behalf = next(a["value"] for a in encoded["args"] if a["name"] == "onBehalfOf")
    assert on_behalf == EIP55_VECTORS[0]


def test_encode_action_default_sender_is_still_synthetic_when_not_overridden():
    intent = make_intent(action_type=contract.ACTION_SUPPLY, network_or_venue="aave_v3", notional=1_000_000)
    encoded = simulate.encode_action(intent)
    on_behalf = next(a["value"] for a in encoded["args"] if a["name"] == "onBehalfOf")
    assert on_behalf == simulate.synthetic_sender(intent["intent_id"])


# ══════════════════════════════ simulate.py: simulate_intent — the full matrix ═════════════════════
def test_simulate_intent_no_action_is_pass_without_any_rpc():
    intent = make_intent(action_type=contract.ACTION_NO_ACTION, notional=0)
    record = simulate.simulate_intent(intent, client=RpcClient(chain_id=1, post=lambda u, p: (_ for _ in ()).throw(
        AssertionError("NO_ACTION must not touch the network"))))
    assert record["result"] == contract.SIM_PASS
    assert record["schema"] == contract.SCHEMA_SIMULATION
    assert record["label"] == contract.SIM_LABEL
    assert list(record["not_proven"]) == list(contract.NOT_PROVEN)


def test_simulate_intent_permissioned_venue_is_not_simulatable_without_any_rpc():
    intent = make_intent(action_type=contract.ACTION_SUPPLY, network_or_venue="maple", notional=1_000)
    record = simulate.simulate_intent(intent, client=RpcClient(chain_id=1, post=lambda u, p: (_ for _ in ()).throw(
        AssertionError("a permissioned venue must never reach the network"))))
    assert record["result"] == contract.SIM_NOT_SIMULATABLE


def test_simulate_intent_supply_happy_path_is_pass():
    node = aave_pass_node()
    client = client_with(node)
    intent = make_intent(action_type=contract.ACTION_SUPPLY, network_or_venue="aave_v3", notional=1_000_000)
    record = simulate.simulate_intent(intent, client=client)
    assert record["result"] == contract.SIM_PASS, record["checks"]
    assert record["block"]["number"] is not None
    assert record["sender"] == simulate.synthetic_sender(intent["intent_id"])
    assert record["sender_kind"] == "synthetic"
    assert record["call"]["signature"] == "supply(address,uint256,address,uint16)"


# ── sender override: verify.py's pre-sign re-simulation from the owner's Safe ───────────────────────
def test_simulate_intent_owner_safe_sender_override_passes_with_the_safe_as_onbehalfof():
    node = aave_pass_node()
    client = client_with(node)
    intent = make_intent(action_type=contract.ACTION_SUPPLY, network_or_venue="aave_v3", notional=1_000_000)
    record = simulate.simulate_intent(intent, client=client, sender=EIP55_VECTORS[0])
    assert record["result"] == contract.SIM_PASS, record["checks"]
    assert record["sender"] == EIP55_VECTORS[0]
    assert record["sender_kind"] == "owner_safe"
    # the embedded onBehalfOf argument must be the Safe, not the synthetic placeholder — otherwise a
    # "re-simulation from the Safe" would silently still be simulating the synthetic sender's call.
    assert EIP55_VECTORS[0] in record["call"]["args_readable"]
    # not_proven is unchanged either way: a state override never proves the Safe's REAL balance.
    assert "balance" in " ".join(record["not_proven"])


def test_simulate_intent_default_sender_kind_is_synthetic_on_every_early_exit_path():
    """sender_kind must be present and correct even on paths that never reach the chain (NO_ACTION,
    unknown venue, permissioned) — _skeleton defaults it, every call site must agree."""
    no_action = simulate.simulate_intent(make_intent(action_type=contract.ACTION_NO_ACTION, notional=0))
    assert no_action["sender_kind"] == "synthetic"
    unknown = simulate.simulate_intent(make_intent(network_or_venue="not_a_real_venue", notional=1))
    assert unknown["sender_kind"] == "synthetic"
    permissioned = simulate.simulate_intent(make_intent(network_or_venue="maple", notional=1))
    assert permissioned["sender_kind"] == "synthetic"


def test_simulate_intent_owner_safe_sender_override_on_permissioned_venue_still_reports_owner_safe():
    intent = make_intent(network_or_venue="maple", notional=1)
    record = simulate.simulate_intent(intent, sender=EIP55_VECTORS[0])
    assert record["sender_kind"] == "owner_safe"
    assert record["sender"] == EIP55_VECTORS[0]
    assert record["result"] == contract.SIM_NOT_SIMULATABLE


def test_simulate_intent_rejects_malformed_sender_override_before_any_rpc():
    calls = []
    client = RpcClient(chain_id=1, post=lambda u, p: calls.append((u, p)))
    intent = make_intent(notional=1_000_000)
    with pytest.raises(ValueError):
        simulate.simulate_intent(intent, client=client, sender="0x1234")
    assert calls == []


def test_simulate_intent_rejects_sender_override_with_bad_checksum():
    bad_checksum = EIP55_VECTORS[0][:-2] + "ED"  # mixed-case, wrong checksum — likely a typo'd address
    intent = make_intent(notional=1_000_000)
    with pytest.raises(ValueError):
        simulate.simulate_intent(intent, client=client_with(aave_pass_node()), sender=bad_checksum)


def test_simulate_intent_sender_override_computes_its_own_override_slot():
    """A real EVM only returns the overridden value when the balanceOf/allowance CALL's own embedded
    address hashes to the SAME slot the override wrote. This FakeNode acts like a tiny EVM for that one
    question — it decodes the queried address out of the calldata and recomputes the slot the same way
    ``tokens.py`` does, then serves whatever the override's ``stateDiff`` has at THAT slot (default 0
    otherwise). If ``simulate_intent`` wrote the override under one address but queried balanceOf under
    a DIFFERENT one (the exact bug this guards against — e.g. threading the override through but not
    the read, or vice versa), the slots would not match and this comes back 0, not the funded amount."""
    tok = tokens.token(1, "USDC")

    class SlotAwareNode(FakeNode):
        def post(self, url, payload):
            method, params = payload["method"], payload["params"]
            if method == "eth_call" and len(params) >= 2:
                tx = params[0]
                data = tx.get("data") or ""
                sel = data[:10].lower()
                if sel in (SEL_BALANCEOF, SEL_ALLOWANCE) and tx.get("to", "").lower() == USDC.lower():
                    overrides = params[-1] if len(params) >= 3 and isinstance(params[-1], dict) else {}
                    state_diff = overrides.get(USDC, overrides.get(USDC.lower(), {})).get("stateDiff", {})
                    body = data[10:]
                    queried_addr = "0x" + body[:64][-40:]
                    if sel == SEL_BALANCEOF:
                        slot = tokens.balance_slot(queried_addr, tok["balance_slot"])
                    else:
                        spender = "0x" + body[64:128][-40:]
                        slot = tokens.allowance_slot(queried_addr, spender, tok["allowance_slot"])
                    self.calls.append((url, payload))
                    return {"jsonrpc": "2.0", "id": 1, "result": state_diff.get(slot, hex_uint(0))}
            return super().post(url, payload)

    node = SlotAwareNode(
        code_by_address={AAVE_POOL: "0x6080604052", USDC: "0x6080604052"},
        call_table={(USDC.lower(), SEL_DECIMALS): hex_uint(6), (AAVE_POOL.lower(), SEL_SUPPLY_AAVE): "0x"},
        gas_table={(AAVE_POOL.lower(), SEL_SUPPLY_AAVE): hex_uint(150_000)},
    )
    client = client_with(node)
    intent = make_intent(action_type=contract.ACTION_SUPPLY, network_or_venue="aave_v3", notional=1_000_000)
    record = simulate.simulate_intent(intent, client=client, sender=EIP55_VECTORS[0])
    bal_check = next(c for c in record["checks"] if c["check"] == "balance_override_readback")
    allow_check = next(c for c in record["checks"] if c["check"] == "allowance_override_readback")
    assert bal_check["state"] == contract.SIM_PASS, bal_check
    assert allow_check["state"] == contract.SIM_PASS, allow_check
    assert record["result"] == contract.SIM_PASS, record["checks"]

    # and the default (synthetic) sender passes this same slot-aware node too — proving the mechanism
    # is symmetric, not just "whatever address happens to be hardcoded into the FakeNode".
    record_default = simulate.simulate_intent(make_intent(action_type=contract.ACTION_SUPPLY,
                                                          network_or_venue="aave_v3", notional=1_000_000),
                                              client=client_with(node))
    assert record_default["result"] == contract.SIM_PASS, record_default["checks"]


def test_simulate_intent_wrong_chain_fails_chain_id_check():
    node = aave_pass_node(chain_id_hex=hex(5))
    client = client_with(node)
    intent = make_intent(notional=1_000_000)
    record = simulate.simulate_intent(intent, client=client)
    assert record["result"] == contract.SIM_FAIL
    chain_check = next(c for c in record["checks"] if c["check"] == "chain_id")
    assert chain_check["state"] == contract.SIM_FAIL


def test_simulate_intent_no_code_at_instrument_fails():
    node = aave_pass_node(code_by_address={USDC: "0x6080604052"})  # aave pool deliberately absent
    client = client_with(node)
    intent = make_intent(notional=1_000_000)
    record = simulate.simulate_intent(intent, client=client)
    assert record["result"] == contract.SIM_FAIL
    code_check = next(c for c in record["checks"] if c["check"] == "code_at_instrument")
    assert code_check["state"] == contract.SIM_FAIL


def test_simulate_intent_wrong_decimals_fails():
    node = aave_pass_node()
    node.call_table[(USDC.lower(), SEL_DECIMALS)] = hex_uint(18)
    client = client_with(node)
    intent = make_intent(notional=1_000_000)
    record = simulate.simulate_intent(intent, client=client)
    assert record["result"] == contract.SIM_FAIL
    dec_check = next(c for c in record["checks"] if c["check"] == "token_decimals")
    assert dec_check["state"] == contract.SIM_FAIL


def test_simulate_intent_slot_readback_mismatch_is_not_measured_not_fail():
    """ADR-556: a read-back mismatch is NOT_MEASURED ('slot layout unverified'), never a silent FAIL that
    could be confused with a real protocol rejection."""
    node = aave_pass_node()
    node.call_table[(USDC.lower(), SEL_BALANCEOF)] = hex_uint(999)  # wrong value after the override
    client = client_with(node)
    intent = make_intent(notional=1_000_000)
    record = simulate.simulate_intent(intent, client=client)
    bal_check = next(c for c in record["checks"] if c["check"] == "balance_override_readback")
    assert bal_check["state"] == contract.NOT_MEASURED
    assert "slot layout unverified" in bal_check["detail"]
    assert record["result"] == contract.NOT_MEASURED


def test_simulate_intent_gas_over_ceiling_fails_gas_ceiling_only():
    node = aave_pass_node()
    node.gas_table[(AAVE_POOL.lower(), SEL_SUPPLY_AAVE)] = hex_uint(simulate.GAS_CEILING + 1)
    client = client_with(node)
    intent = make_intent(notional=1_000_000)
    record = simulate.simulate_intent(intent, client=client)
    gas_check = next(c for c in record["checks"] if c["check"] == "gas_ceiling")
    assert gas_check["state"] == contract.SIM_FAIL
    assert record["result"] == contract.SIM_FAIL


def test_simulate_intent_action_revert_fails_with_decoded_reason():
    node = aave_pass_node()
    reason = "insufficient collateral"
    body = hex_uint(0x20)[2:] + format(len(reason), "064x") + reason.encode().hex().ljust(64, "0")
    node.call_table[(AAVE_POOL.lower(), SEL_SUPPLY_AAVE)] = {
        "error": {"code": 3, "message": "execution reverted", "data": "0x08c379a0" + body}}
    client = client_with(node)
    intent = make_intent(notional=1_000_000)
    record = simulate.simulate_intent(intent, client=client)
    assert record["result"] == contract.SIM_FAIL
    assert record["revert_reason"] == reason


def test_simulate_intent_approve_normal_amount_passes():
    node = FakeNode(
        code_by_address={USDC: "0x6080604052", AAVE_POOL: "0x6080604052"},
        call_table={(USDC.lower(), SEL_DECIMALS): hex_uint(6), (USDC.lower(), SEL_APPROVE): "0x" + hex_uint(1)[2:]},
        gas_table={(USDC.lower(), SEL_APPROVE): hex_uint(45_000)},
    )
    client = client_with(node)
    intent = make_intent(action_type=contract.ACTION_APPROVE, network_or_venue="aave_v3", from_asset="USDC",
                         notional=250_000)
    record = simulate.simulate_intent(intent, client=client)
    approve_check = next(c for c in record["checks"] if c["check"] == "approve_amount_bounded")
    assert approve_check["state"] == contract.SIM_PASS
    assert record["result"] == contract.SIM_PASS, record["checks"]
    # APPROVE needs neither a balance nor a pre-existing allowance override, so NEITHER check is even
    # emitted (padding with NOT_MEASURED would force this intent out of SIM_PASS by construction).
    assert not any(c["check"] in ("balance_override_readback", "allowance_override_readback")
                   for c in record["checks"])


def test_simulate_intent_approve_unlimited_amount_fails_excessive_allowance():
    node = FakeNode(
        code_by_address={USDC: "0x6080604052", AAVE_POOL: "0x6080604052"},
        call_table={(USDC.lower(), SEL_DECIMALS): hex_uint(6), (USDC.lower(), SEL_APPROVE): "0x" + hex_uint(1)[2:]},
        gas_table={(USDC.lower(), SEL_APPROVE): hex_uint(45_000)},
    )
    client = client_with(node)
    intent = make_intent(action_type=contract.ACTION_APPROVE, network_or_venue="aave_v3", from_asset="USDC",
                         notional=simulate.UINT256_MAX)
    record = simulate.simulate_intent(intent, client=client)
    approve_check = next(c for c in record["checks"] if c["check"] == "approve_amount_bounded")
    assert approve_check["state"] == contract.SIM_FAIL
    assert "excessive allowance" in approve_check["detail"]
    assert record["result"] == contract.SIM_FAIL


def _fluid_deposit_node(*, shares_returned, preview_shares, base_units_amount=1_000_000):
    return FakeNode(
        code_by_address={FLUID: "0x6080604052", USDC: "0x6080604052"},
        call_table={
            (USDC.lower(), SEL_DECIMALS): hex_uint(6),
            (FLUID.lower(), SEL_ASSET): hex_address(USDC),
            (USDC.lower(), SEL_BALANCEOF): hex_uint(base_units_amount),
            (USDC.lower(), SEL_ALLOWANCE): hex_uint(base_units_amount),
            (FLUID.lower(), SEL_DEPOSIT_4626): hex_uint(shares_returned),
            (FLUID.lower(), SEL_PREVIEW_DEPOSIT): hex_uint(preview_shares),
        },
        gas_table={(FLUID.lower(), SEL_DEPOSIT_4626): hex_uint(200_000)},
    )


def test_simulate_intent_deposit_4626_shares_match_preview_passes():
    node = _fluid_deposit_node(shares_returned=999_000, preview_shares=999_000)
    client = client_with(node)
    intent = make_intent(action_type=contract.ACTION_DEPOSIT_4626, network_or_venue="fluid_fusdc",
                         from_asset="USDC", notional=1_000_000)
    record = simulate.simulate_intent(intent, client=client)
    assert record["result"] == contract.SIM_PASS, record["checks"]
    assert record["post_state"]["check"] == "shares_vs_preview"


def test_simulate_intent_deposit_4626_preview_mismatch_fails():
    node = _fluid_deposit_node(shares_returned=900_000, preview_shares=999_000)  # ~10% off, way over 0.01%
    client = client_with(node)
    intent = make_intent(action_type=contract.ACTION_DEPOSIT_4626, network_or_venue="fluid_fusdc",
                         from_asset="USDC", notional=1_000_000)
    record = simulate.simulate_intent(intent, client=client)
    post = record["post_state"]
    assert post["check"] == "shares_vs_preview"
    assert post["state"] == contract.SIM_FAIL
    assert record["result"] == contract.SIM_FAIL


def test_simulate_intent_deposit_4626_scales_human_notional_end_to_end():
    """review #4, end-to-end: an intent saying "1000" with notional_unit="USDC" must simulate
    1_000_000_000 base units (1000 USDC @ 6 decimals), not 1000 base units (0.001 USDC) — the exact
    live-smoke discrepancy (nominal "1000" returned 820 shares instead of ~820,239,983,xxx)."""
    node = _fluid_deposit_node(shares_returned=1_000_000_000, preview_shares=1_000_000_000,
                               base_units_amount=1_000_000_000)
    client = client_with(node)
    intent = make_intent(action_type=contract.ACTION_DEPOSIT_4626, network_or_venue="fluid_fusdc",
                         from_asset="USDC", notional=1000, notional_unit="USDC")
    record = simulate.simulate_intent(intent, client=client)
    assert record["result"] == contract.SIM_PASS, record["checks"]
    bal_check = next(c for c in record["checks"] if c["check"] == "balance_override_readback")
    assert bal_check["state"] == contract.SIM_PASS
    assert "1000000000" in bal_check["detail"]
    assert record["post_state"]["shares_returned"] == 1_000_000_000


def test_simulate_intent_refuses_amount_too_precise_for_decimals_before_any_rpc():
    """A human notional carrying more precision than the token supports is a FAIL, named as such —
    never silently truncated into a smaller real amount."""
    intent = make_intent(action_type=contract.ACTION_SUPPLY, network_or_venue="aave_v3", from_asset="USDC",
                         notional="1000.0000001", notional_unit="USDC")
    record = simulate.simulate_intent(intent, client=client_with(aave_pass_node()))
    assert record["result"] == contract.SIM_FAIL
    scaling_check = next(c for c in record["checks"] if c["check"] == "notional_scaling")
    assert scaling_check["state"] == contract.SIM_FAIL


def test_simulate_intent_withdraw_aave_action_call_not_measured_no_declared_slot():
    """WITHDRAW on aave_v3: no aToken slot declared ⇒ action_eth_call is honestly NOT_MEASURED, and the
    unwind-liquidity probe is ALSO NOT_MEASURED (aToken address not pinned) — a named contract gap."""
    node = aave_pass_node()
    client = client_with(node)
    intent = make_intent(action_type=contract.ACTION_WITHDRAW, network_or_venue="aave_v3", notional=1_000_000)
    record = simulate.simulate_intent(intent, client=client)
    action_check = next(c for c in record["checks"] if c["check"] == "action_eth_call")
    assert action_check["state"] == contract.NOT_MEASURED
    assert record["post_state"]["check"] == "unwind_path"
    assert record["post_state"]["state"] == contract.NOT_MEASURED
    assert record["result"] == contract.NOT_MEASURED


def test_simulate_intent_withdraw_comet_unwind_probe_passes_with_enough_liquidity():
    """The unwind-liquidity SIGNAL is PASS, but the overall result stays NOT_MEASURED by construction:
    WITHDRAW's "balance_override_readback" is a real, named gap (no aToken/Comet-balance slot declared)
    — this layer never claims SIM_PASS for a WITHDRAW/REDEEM it cannot verify the pull side of."""
    node = FakeNode(
        code_by_address={COMET: "0x6080604052", USDC: "0x6080604052"},
        call_table={(USDC.lower(), SEL_DECIMALS): hex_uint(6), (USDC.lower(), SEL_BALANCEOF): hex_uint(10_000_000)},
    )
    client = client_with(node)
    intent = make_intent(action_type=contract.ACTION_WITHDRAW, network_or_venue="compound_v3", notional=1_000_000)
    record = simulate.simulate_intent(intent, client=client)
    assert record["post_state"]["check"] == "unwind_path"
    assert record["post_state"]["state"] == contract.SIM_PASS
    assert record["result"] == contract.NOT_MEASURED, record["checks"]


def test_simulate_intent_withdraw_comet_unwind_probe_fails_with_too_little_liquidity():
    node = FakeNode(
        code_by_address={COMET: "0x6080604052", USDC: "0x6080604052"},
        call_table={(USDC.lower(), SEL_DECIMALS): hex_uint(6), (USDC.lower(), SEL_BALANCEOF): hex_uint(100)},
    )
    client = client_with(node)
    intent = make_intent(action_type=contract.ACTION_WITHDRAW, network_or_venue="compound_v3", notional=1_000_000)
    record = simulate.simulate_intent(intent, client=client)
    assert record["post_state"]["state"] == contract.SIM_FAIL
    assert record["result"] == contract.SIM_FAIL


def test_simulate_intent_redeem_4626_unwind_probe_uses_vault_balance():
    node = FakeNode(
        code_by_address={FLUID: "0x6080604052", USDC: "0x6080604052"},
        call_table={(USDC.lower(), SEL_DECIMALS): hex_uint(6), (FLUID.lower(), SEL_ASSET): hex_address(USDC),
                   (USDC.lower(), SEL_BALANCEOF): hex_uint(5_000_000)},
    )
    client = client_with(node)
    intent = make_intent(action_type=contract.ACTION_REDEEM_4626, network_or_venue="fluid_fusdc", notional=1_000_000)
    record = simulate.simulate_intent(intent, client=client)
    assert record["post_state"]["check"] == "unwind_path"
    assert record["post_state"]["state"] == contract.SIM_PASS
    # same construction as the Comet case above: the pull-side slot is a real, named gap.
    assert record["result"] == contract.NOT_MEASURED, record["checks"]


def test_simulate_intent_unknown_venue_is_not_measured():
    intent = make_intent(network_or_venue="not_a_real_venue", notional=1)
    record = simulate.simulate_intent(intent, client=RpcClient(chain_id=1, post=lambda u, p: (_ for _ in ()).throw(
        AssertionError("an unknown venue must never reach the network"))))
    assert record["result"] == contract.NOT_MEASURED


def test_simulate_intent_morpho_base_is_not_measured_no_operators_declared():
    """morpho_blue_base is chain 8453; contract.RPC_OPERATORS declares chain-1 operators only — pin_block
    starves on eth_blockNumber before any address is even consulted (the documented contract gap)."""
    intent = make_intent(action_type=contract.ACTION_SUPPLY, network_or_venue="morpho_blue_base", notional=1_000)
    record = simulate.simulate_intent(intent)  # default client — real chain_id, but endpoints is empty
    assert record["result"] == contract.NOT_MEASURED


def test_simulate_intent_spot_order_routes_to_exchange_sim_not_rpc():
    intent = make_intent(action_type=contract.ACTION_SPOT_ORDER, network_or_venue="binance", notional=1)
    record = simulate.simulate_intent(intent, client=RpcClient(chain_id=1, post=lambda u, p: (_ for _ in ()).throw(
        AssertionError("SPOT_ORDER must never touch the on-chain RPC path"))))
    assert record["result"] == contract.NOT_MEASURED


# ══════════════════════════════ simulate.py: unwind_probe directly ═════════════════════════════════
def test_unwind_probe_unknown_venue():
    probe = simulate.unwind_probe("not_a_venue", 1000, client=RpcClient(chain_id=1))
    assert probe["state"] == contract.NOT_MEASURED


def test_unwind_probe_permissioned_is_not_simulatable():
    probe = simulate.unwind_probe("maple", 1000, client=RpcClient(chain_id=1))
    assert probe["state"] == contract.SIM_NOT_SIMULATABLE


def test_unwind_probe_aave_is_not_measured_no_atoken_address():
    probe = simulate.unwind_probe("aave_v3", 1000, client=RpcClient(chain_id=1))
    assert probe["state"] == contract.NOT_MEASURED
    assert "aToken" in probe["detail"]


# ══════════════════════════════ simulate.py: preview_deposit_at (review #9) ════════════════════════
def test_preview_deposit_at_asset_ok_requires_matching_registry_address():
    """review #9: asset_ok used to mean 'decode_address() didn't throw' — true for ANY 20-byte address,
    including a wrong one. It must mean the vault's asset() equals the PINNED registry token address."""
    node = FakeNode(
        code_by_address={FLUID: "0x6080604052"},
        call_table={(FLUID.lower(), SEL_ASSET): hex_address("0x" + "99" * 20),  # some OTHER address
                   (FLUID.lower(), SEL_PREVIEW_DEPOSIT): hex_uint(1_000_000)},
    )
    client = client_with(node)
    result = simulate.preview_deposit_at("fluid_fusdc", 1_000_000, client=client)
    assert result["state"] == contract.MEASURED  # previewDeposit itself still answers
    assert result["asset_ok"] is False


def test_preview_deposit_at_asset_ok_true_when_address_matches_registry():
    node = FakeNode(
        code_by_address={FLUID: "0x6080604052"},
        call_table={(FLUID.lower(), SEL_ASSET): hex_address(USDC), (FLUID.lower(), SEL_PREVIEW_DEPOSIT): hex_uint(1_000_000)},
    )
    client = client_with(node)
    result = simulate.preview_deposit_at("fluid_fusdc", 1_000_000, client=client)
    assert result["state"] == contract.MEASURED
    assert result["asset_ok"] is True


# ══════════════════════════════ exchange_sim.py: local deterministic simulator ═════════════════════
BOOK = {"bids": [[100.0, 5.0], [99.5, 10.0]], "asks": [[100.5, 5.0], [101.0, 10.0]]}
FILTERS = {"symbol": "BTCUSD", "lot_size": 0.001, "step_size": 0.001, "tick_size": 0.5, "min_notional": 10.0,
          "fee_bps": 10.0}


def test_simulate_order_market_buy_fills_and_labels_local_simulator():
    order = {"symbol": "BTCUSD", "side": "BUY", "type": "MARKET", "quantity": 2.0, "cash": 10_000.0, "position": 0.0}
    rec = exchange_sim.simulate_order(order, FILTERS, BOOK)
    assert rec["label"] == exchange_sim.LABEL
    assert rec["accepted"] is True
    assert rec["status"] == exchange_sim.STATUS_SIMULATED
    assert rec["filled_qty"] == pytest.approx(2.0)
    assert rec["avg_price"] == pytest.approx(100.5)
    assert rec["cash_after"] < 10_000.0
    assert rec["position_after"] == pytest.approx(2.0)


def test_simulate_order_partial_fill_when_book_is_thin():
    order = {"symbol": "BTCUSD", "side": "BUY", "type": "MARKET", "quantity": 20.0, "cash": 1_000_000.0,
            "position": 0.0}
    rec = exchange_sim.simulate_order(order, FILTERS, BOOK)
    assert rec["accepted"] is True
    assert rec["partial_fill"] is True
    # review #15: a partial fill must be its OWN status, not lumped in with a full "SIMULATED" fill.
    assert rec["status"] == exchange_sim.STATUS_PARTIAL
    assert rec["filled_qty"] == pytest.approx(15.0)  # only 5 + 10 available on the ask side


def test_simulate_order_rejects_insufficient_cash_on_buy():
    """review #15: a BUY was never checked against the cash actually available — before this fix a
    zero-cash order against a liquid book came back "accepted" with a negative cash_after."""
    order = {"symbol": "BTCUSD", "side": "BUY", "type": "MARKET", "quantity": 2.0, "cash": 0.0, "position": 0.0}
    rec = exchange_sim.simulate_order(order, FILTERS, BOOK)
    assert rec["accepted"] is False
    assert rec["status"] == exchange_sim.STATUS_REJECTED
    assert "insufficient cash" in rec["reason"]
    assert rec["cash_after"] is None


def test_simulate_order_rejects_insufficient_cash_exactly_at_the_margin():
    """A BUY whose cost (notional + fee) is a whisker over the available cash must still be rejected —
    not accepted because 'close enough'."""
    order = {"symbol": "BTCUSD", "side": "BUY", "type": "MARKET", "quantity": 1.0, "cash": 100.0, "position": 0.0}
    rec = exchange_sim.simulate_order(order, FILTERS, BOOK)  # ask=100.5, fee 10bps -> cost ~100.6 > 100 cash
    assert rec["accepted"] is False
    assert "insufficient cash" in rec["reason"]


def test_simulate_order_rejects_insufficient_position_on_sell():
    """The mirror bug: a SELL for more than the position actually held must be rejected, not simulated."""
    order = {"symbol": "BTCUSD", "side": "SELL", "type": "MARKET", "quantity": 2.0, "cash": 0.0, "position": 0.5}
    rec = exchange_sim.simulate_order(order, FILTERS, BOOK)
    assert rec["accepted"] is False
    assert rec["status"] == exchange_sim.STATUS_REJECTED
    assert "insufficient position" in rec["reason"]


def test_simulate_order_rejects_step_size_violation():
    order = {"symbol": "BTCUSD", "side": "BUY", "type": "MARKET", "quantity": 1.0001, "cash": 10_000.0,
            "position": 0.0}
    rec = exchange_sim.simulate_order(order, FILTERS, BOOK)
    assert rec["accepted"] is False
    assert "step_size" in rec["reason"]


def test_simulate_order_rejects_tick_size_violation():
    order = {"symbol": "BTCUSD", "side": "BUY", "type": "LIMIT", "price": 100.3, "quantity": 1.0, "cash": 10_000.0,
            "position": 0.0}
    rec = exchange_sim.simulate_order(order, FILTERS, BOOK)
    assert rec["accepted"] is False
    assert "tick_size" in rec["reason"]


def test_simulate_order_rejects_min_notional():
    order = {"symbol": "BTCUSD", "side": "BUY", "type": "MARKET", "quantity": 0.001, "cash": 10_000.0,
            "position": 0.0}
    rec = exchange_sim.simulate_order(order, FILTERS, BOOK)
    assert rec["accepted"] is False
    assert "min_notional" in rec["reason"]


def test_simulate_order_sell_applies_fee_and_reduces_position():
    order = {"symbol": "BTCUSD", "side": "SELL", "type": "MARKET", "quantity": 1.0, "cash": 0.0, "position": 5.0}
    rec = exchange_sim.simulate_order(order, FILTERS, BOOK)
    assert rec["accepted"] is True
    assert rec["position_after"] == pytest.approx(4.0)
    assert rec["fee_paid"] > 0
    assert rec["cash_after"] == pytest.approx(rec["notional"] - rec["fee_paid"])


def test_simulate_order_rejects_symbol_mismatch():
    order = {"symbol": "ETHUSD", "side": "BUY", "type": "MARKET", "quantity": 1.0, "cash": 10_000.0, "position": 0.0}
    rec = exchange_sim.simulate_order(order, FILTERS, BOOK)
    assert rec["accepted"] is False
    assert "symbol mismatch" in rec["reason"]


def test_simulate_order_never_imports_network_modules():
    import spa_core.capital_shadow.exchange_sim as mod
    src = open(mod.__file__).read()
    for forbidden in ("urllib", "socket", "requests", "http.client"):
        assert forbidden not in src


# ══════════════════════════════ construction guards (review #13) ══════════════════════════════════
def test_only_rpc_module_imports_network_libraries():
    import spa_core.capital_shadow.abi as abi_mod
    import spa_core.capital_shadow.exchange_sim as exch_mod
    import spa_core.capital_shadow.simulate as sim_mod
    import spa_core.capital_shadow.tokens as tok_mod
    for mod in (abi_mod, tok_mod, sim_mod, exch_mod):
        src = open(mod.__file__).read()
        for forbidden in ("import urllib", "import http", "import socket", "import ssl"):
            assert forbidden not in src, f"{mod.__name__} must not import {forbidden!r}"


def test_no_dangerous_builtins_anywhere_in_the_package():
    import spa_core.capital_shadow.abi as abi_mod
    import spa_core.capital_shadow.exchange_sim as exch_mod
    import spa_core.capital_shadow.rpc as rpc_mod
    import spa_core.capital_shadow.simulate as sim_mod
    import spa_core.capital_shadow.tokens as tok_mod
    for mod in (abi_mod, tok_mod, sim_mod, exch_mod, rpc_mod):
        src = open(mod.__file__).read()
        for forbidden in ("importlib", "__import__", "subprocess", "os.system", "eval(", "exec("):
            assert forbidden not in src, f"{mod.__name__} must not contain {forbidden!r}"


def test_no_signing_or_execution_imports_anywhere_in_the_package():
    """No RUNTIME import of a signing/execution library — this checks import STATEMENTS, not prose:
    ``abi.py``'s own docstring says "cross-checked against eth_abi in tests", which must not trip this."""
    import ast

    import spa_core.capital_shadow.abi as abi_mod
    import spa_core.capital_shadow.exchange_sim as exch_mod
    import spa_core.capital_shadow.rpc as rpc_mod
    import spa_core.capital_shadow.simulate as sim_mod
    import spa_core.capital_shadow.tokens as tok_mod
    forbidden_roots = {"eth_account", "web3", "spa_core.execution", "eth_hash", "eth_utils", "eth_abi"}
    for mod in (abi_mod, tok_mod, sim_mod, exch_mod, rpc_mod):
        tree = ast.parse(open(mod.__file__).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
            else:
                continue
            for name in names:
                assert not any((name or "").startswith(root) for root in forbidden_roots), \
                    f"{mod.__name__} imports forbidden module {name!r}"


# ══════════════════════════════ LIVE smoke (opt-in only) ═══════════════════════════════════════════
# NOTE on a found tension with this repo's own guard, left unresolved on purpose (invariant #16: never
# silently weaken a guard or a test): ``spa_core/tests/network_guard.py`` blocks EVERY non-loopback
# network call from EVERY test, unconditionally, with no opt-out primitive — by design ("no test is made
# less strict by this module"). So even with SPA_LIVE_RPC_SMOKE=1, running this through `pytest` will
# still get an `OSError` from the guard, not a real RPC response; that is the guard doing its job, not a
# bug in this test. This was run and verified for real OUTSIDE pytest (plain ``python3 -c "..."``,
# calling ``simulate.simulate_intent`` with a real, un-injected ``RpcClient(chain_id=1)``) on 2026-10-04:
#   fluid_fusdc DEPOSIT_4626 (1000 USDC): result=PASS, block=26116128,
#     hash=0xdbb5db417ae6ebf02ec8f7142cb6ed088829c81cd9b8c633bc9a84b04f0ba75b,
#     operators=[Allnodes, Automata, dRPC], gas_estimate=142048,
#     post_state=shares_vs_preview PASS (returned=820239983, preview=820239983)
#   aave_v3 SUPPLY (1 USDC): result=PASS, block=26116129,
#     hash=0x5ad745878cfb4330e1c1e9805957fafaff480ff4c1a963735408dc27d07cd434,
#     operators=[Allnodes, Automata, dRPC] (gas: 2 of 3 agreed, 212407), all checks PASS
# This test is kept, correctly gated, for anyone who wants to re-verify by invoking it the same way
# (outside pytest) or by deliberately uninstalling spa_core.tests.network_guard for the one process —
# that decision belongs to whoever owns that guard, not to this package.
@pytest.mark.skipif(os.environ.get("SPA_LIVE_RPC_SMOKE") != "1",
                    reason="set SPA_LIVE_RPC_SMOKE=1 to hit the real public RPCs declared in "
                           "contract.RPC_OPERATORS — note: spa_core/tests/network_guard.py will still "
                           "refuse the call when run through pytest; see the comment above")
def test_live_smoke_fluid_deposit_and_aave_supply_pass_against_real_rpcs():
    client = RpcClient(chain_id=1)  # real endpoints, real urllib transport — no injected post
    deposit_intent = make_intent(action_type=contract.ACTION_DEPOSIT_4626, network_or_venue="fluid_fusdc",
                                 from_asset="USDC", notional=1_000_000_000)  # 1000 USDC @ 6 decimals
    deposit_record = simulate.simulate_intent(deposit_intent, client=client)
    print("LIVE fluid_fusdc DEPOSIT_4626:", deposit_record["result"], deposit_record["block"],
          deposit_record["gas_estimate"], deposit_record["post_state"])
    assert deposit_record["result"] == contract.SIM_PASS, deposit_record["checks"]

    supply_client = RpcClient(chain_id=1)
    supply_intent = make_intent(action_type=contract.ACTION_SUPPLY, network_or_venue="aave_v3", from_asset="USDC",
                                notional=1_000_000)  # 1 USDC
    supply_record = simulate.simulate_intent(supply_intent, client=supply_client)
    print("LIVE aave_v3 SUPPLY:", supply_record["result"], supply_record["block"], supply_record["gas_estimate"])
    assert supply_record["result"] == contract.SIM_PASS, supply_record["checks"]
