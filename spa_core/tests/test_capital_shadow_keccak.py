"""Vectors + rate-boundary cross-checks for spa_core/capital_shadow/keccak.py (ADR-556 RM-LIVE-01).

Keccak-256 (the Ethereum hash) is the foundation every selector / storage-slot derivation in
``capital_shadow`` depends on; a wrong permutation or wrong padding would silently corrupt every
downstream check. Vectors below were captured from ``eth_hash.auto.keccak`` (installed in this repo for
``eth_account``/``web3`` elsewhere, but NEVER imported at runtime by ``capital_shadow`` — invariant #4);
hardcoded here so the test does not depend on that package being present.
"""
from __future__ import annotations

import pytest

from spa_core.capital_shadow.keccak import keccak256, selector

try:
    from eth_hash.auto import keccak as _eth_keccak
    HAVE_ETH_HASH = True
except Exception:  # noqa: BLE001 — optional cross-check only
    HAVE_ETH_HASH = False

# captured from eth_hash.auto.keccak(b"") / keccak(b"abc") on this machine (see module docstring)
EMPTY_VECTOR = "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
ABC_VECTOR = "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"


def test_empty_string_vector():
    assert keccak256(b"").hex() == EMPTY_VECTOR
    assert len(keccak256(b"")) == 32


def test_abc_vector():
    assert keccak256(b"abc").hex() == ABC_VECTOR


def test_empty_and_abc_cross_checked_against_eth_hash_when_importable():
    if not HAVE_ETH_HASH:
        pytest.skip("eth_hash not importable in this environment — vectors above are the frozen record")
    assert keccak256(b"").hex() == _eth_keccak(b"").hex()
    assert keccak256(b"abc").hex() == _eth_keccak(b"abc").hex()


@pytest.mark.parametrize("length", [135, 136, 137])
def test_rate_boundary_lengths_against_eth_hash(length):
    """136 bytes is exactly one Keccak-256 rate block (_RATE in keccak.py) — 135/136/137 bound the case
    where the padding must open a second block."""
    data = bytes((i % 256 for i in range(length)))
    ours = keccak256(data)
    assert len(ours) == 32
    if HAVE_ETH_HASH:
        assert ours == _eth_keccak(data)


def test_rate_boundary_lengths_are_internally_consistent_without_eth_hash():
    """Same assertion as above, phrased so the boundary is still checked even when eth_hash is absent:
    the three lengths must not collide and must each be stable/deterministic."""
    digests = {n: keccak256(bytes((i % 256 for i in range(n)))) for n in (135, 136, 137)}
    assert len(set(digests.values())) == 3
    for n, d in digests.items():
        assert keccak256(bytes((i % 256 for i in range(n)))) == d


def test_known_selectors():
    # computed independently via eth_hash and widely published (ERC-20 selectors)
    assert selector("transfer(address,uint256)") == "0xa9059cbb"
    assert selector("approve(address,uint256)") == "0x095ea7b3"
    assert selector("balanceOf(address)") == "0x70a08231"
    assert selector("allowance(address,address)") == "0xdd62ed3e"
    assert selector("decimals()") == "0x313ce567"


def test_selector_is_four_bytes_hex():
    sel = selector("supply(address,uint256,address,uint16)")
    assert sel.startswith("0x")
    assert len(sel) == 10  # "0x" + 8 hex chars = 4 bytes


def test_keccak256_rejects_non_bytes():
    with pytest.raises(TypeError):
        keccak256("abc")  # str, not bytes — must be rejected, not silently encoded
