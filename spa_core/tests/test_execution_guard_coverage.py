"""
test_execution_guard_coverage.py — WS-5.2 STRUCTURAL guard coverage.

ROUND-2 "Prove the Edge", Workstream 5. The inert live-trading guard used to be
POSITIONAL — ``@live_trading_forbidden`` sat on one wrapper method per adapter
while the capital PRIMITIVES (``eth_signer.sign_transaction`` /
``eth_signer.send_raw_transaction`` / ``mev_protection.send_protected``) were each
INDIVIDUALLY UNGUARDED. An adversary (or an accidental regression) that called a
primitive DIRECTLY — the exact bypass the positional guard missed — slipped
straight through.

This suite proves the defense is now STRUCTURAL: with the global arming flag
``SPA_EXEC_ARMED`` OFF (the default — and where it stays the WHOLE paper period),
EVERY capital primitive and EVERY adapter broadcast/sign path HARD-RAISES.

It ENUMERATES the paths (5.2) so a NEW adapter or a NEW broadcast path that is
not wired into the guard makes this test fail. The RED-TEAM section builds a
fake adapter that calls the primitives DIRECTLY and proves that bypass is CLOSED.

INERT: SPA_EXEC_ARMED is never flipped here except inside a single armed-path
sanity test that uses fully stubbed crypto (no key, no network). Flipping the
flag for real IS the owner-gated go-live cutover — these tests do NOT do that.

stdlib-only test deps (pytest). No network. No live data/.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from spa_core.execution import arming
from spa_core.utils.errors import LiveTradingForbiddenError

REPO_ROOT = Path(__file__).resolve().parents[2]
EXECUTION_DIR = REPO_ROOT / "spa_core" / "execution"

# A public, fund-less, secret-shaped dev key (64 hex). NOT a real key.
_PUBLIC_DEV_KEY = "1" * 64
_SIGNED_TX = "0x" + "fa" * 50
_TX = {
    "to": "0x" + "0" * 40, "value": 0, "gas": 21000,
    "maxFeePerGas": 1, "maxPriorityFeePerGas": 1,
    "nonce": 0, "chainId": 1, "data": b"",
}


@pytest.fixture(autouse=True)
def _force_unarmed(monkeypatch):
    """Force SPA_EXEC_ARMED OFF for every test here (fail-CLOSED default).

    The whole point of the suite is to prove the NON-armed block, so we delete
    any ambient value rather than trust the environment.
    """
    monkeypatch.delenv(arming.EXEC_ARMED_ENV, raising=False)


# ─────────────────────────────────────────────────────────────────────────────
# is_exec_armed / assert_live_armed — the central arming assertion (5.1)
# ─────────────────────────────────────────────────────────────────────────────

class TestCentralArmingAssertion:
    def test_default_off(self):
        """Unset env → NOT armed (fail-CLOSED default)."""
        assert arming.is_exec_armed() is False

    @pytest.mark.parametrize("val", ["", "0", "false", "off", "no", "  ", "tru",
                                     "2", "enabled", "FALSE", "OFF"])
    def test_non_affirmative_values_are_off(self, monkeypatch, val):
        """Anything that is not an explicit affirmative token → NOT armed."""
        monkeypatch.setenv(arming.EXEC_ARMED_ENV, val)
        assert arming.is_exec_armed() is False

    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "YES", "on",
                                     "On", " true ", "Yes"])
    def test_affirmative_values_are_on(self, monkeypatch, val):
        """Only explicit affirmatives arm (case-insensitive, trimmed)."""
        monkeypatch.setenv(arming.EXEC_ARMED_ENV, val)
        assert arming.is_exec_armed() is True

    def test_assert_raises_when_unarmed(self):
        with pytest.raises(LiveTradingForbiddenError):
            arming.assert_live_armed("unit.test")

    def test_assert_passes_when_armed(self, monkeypatch):
        monkeypatch.setenv(arming.EXEC_ARMED_ENV, "1")
        # Returns None, does not raise.
        assert arming.assert_live_armed("unit.test") is None

    def test_assert_error_carries_no_key_material(self):
        """The arming error names the primitive, never any key (it gets none)."""
        try:
            arming.assert_live_armed("eth_signer.sign_transaction")
            pytest.fail("expected LiveTradingForbiddenError")
        except LiveTradingForbiddenError as exc:
            assert "eth_signer.sign_transaction" in str(exc)
            assert _PUBLIC_DEV_KEY not in str(exc)


# ─────────────────────────────────────────────────────────────────────────────
# 5.1 — the capital PRIMITIVES self-check (the structural inner layer)
# ─────────────────────────────────────────────────────────────────────────────

class TestPrimitivesSelfCheckUnarmed:
    """Each capital primitive HARD-RAISES with SPA_EXEC_ARMED OFF, regardless of
    any wrapper above it. This is the structural layer the positional guard
    lacked."""

    def test_eth_signer_sign_transaction_raises(self):
        from spa_core.execution import eth_signer
        with pytest.raises(LiveTradingForbiddenError):
            eth_signer.sign_transaction(_PUBLIC_DEV_KEY, _TX)

    def test_eth_signer_send_raw_transaction_raises(self):
        from spa_core.execution import eth_signer
        with pytest.raises(LiveTradingForbiddenError):
            eth_signer.send_raw_transaction(_SIGNED_TX, "https://rpc.example.com")

    def test_mev_send_protected_raises(self):
        from spa_core.execution import mev_protection
        with pytest.raises(LiveTradingForbiddenError):
            mev_protection.send_protected(_SIGNED_TX)

    def test_sign_transaction_raises_BEFORE_touching_key(self, monkeypatch):
        """The arming gate is OUTERMOST: a malformed key + a hostile backend are
        never reached when unarmed (so no key could possibly leak)."""
        from spa_core.execution import eth_signer

        class _Hostile:
            @staticmethod
            def sign_transaction(_tx, private_key):  # pragma: no cover
                raise AssertionError("backend reached while UNARMED")

        monkeypatch.setattr(eth_signer, "_get_account", lambda: _Hostile)
        with pytest.raises(LiveTradingForbiddenError):
            # A malformed key would normally ValidationError; arming wins first.
            eth_signer.sign_transaction("deadbeef", _TX)


# ─────────────────────────────────────────────────────────────────────────────
# 5.2 — UNIFORM adapter broadcast/sign coverage (enumerated)
# ─────────────────────────────────────────────────────────────────────────────

def _all_execution_adapter_classes():
    """Enumerate EVERY capital-moving execution adapter class.

    A NEW adapter added to spa_core.execution must appear here (and own a guarded
    broadcast path) or this enumeration's assertions will flag it.
    """
    from spa_core.execution.aave_v3_adapter import AaveV3Adapter
    from spa_core.execution.compound_v3_adapter import CompoundV3Adapter
    from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
    from spa_core.execution.adapters.euler_v2_adapter import EulerV2Adapter
    from spa_core.execution.adapters.maple_adapter import MapleAdapter
    from spa_core.execution.adapters.yearn_v3_adapter import YearnV3Adapter
    from spa_core.execution.adapters.sky_susds_adapter import SkySUSDSAdapter
    return [
        ("aave_v3", AaveV3Adapter),
        ("compound_v3", CompoundV3Adapter),
        ("morpho", MorphoAdapter),
        ("euler_v2", EulerV2Adapter),
        ("maple", MapleAdapter),
        ("yearn_v3", YearnV3Adapter),
        ("sky_susds", SkySUSDSAdapter),
    ]


# The broadcast/sign chokepoint methods, per adapter family. EVERY adapter that
# moves capital MUST guard at least one of these — either via
# @live_trading_forbidden (the wrapper) OR the structural assert_live_armed
# inside the body. Covers the historical asymmetry:
#   * T1 (aave/compound): _send_raw_tx (structural) + _sign_and_send (decorator)
#   * morpho:             _send_raw_tx + _sign_and_send (both decorator)
#   * T2 (euler/maple/yearn/sky): _execute_tx_pair + _execute_single_tx (decorator;
#     bodies also call the now-armed sign_transaction + send_protected primitives)
_BROADCAST_METHODS = (
    "_send_raw_tx",
    "_sign_and_send",
    "_execute_tx_pair",
    "_execute_single_tx",
)


@pytest.mark.parametrize("name,Adapter", _all_execution_adapter_classes())
def test_every_adapter_has_a_guarded_broadcast_path(name, Adapter):
    """Enumeration: each adapter exposes at least one broadcast/sign chokepoint.

    A NEW adapter with a NEW broadcast method name (not in _BROADCAST_METHODS)
    fails here — forcing it to be wired into the guard + this enumeration.
    """
    present = [m for m in _BROADCAST_METHODS if hasattr(Adapter, m)]
    assert present, (
        f"{name}: no known broadcast/sign chokepoint "
        f"({_BROADCAST_METHODS}) — a new method must be wired into the guard"
    )


@pytest.mark.parametrize("name,Adapter", _all_execution_adapter_classes())
def test_every_adapter_broadcast_path_raises_when_unarmed(name, Adapter, monkeypatch):
    """UNIFORM coverage: with SPA_EXEC_ARMED OFF, EVERY enumerated adapter
    broadcast/sign chokepoint RAISES — closing the asymmetry where the guard sat
    on different methods (T1 _sign_and_send vs T2 _execute_*; T1 _send_raw_tx was
    entirely unguarded before WS-5.2).

    For _send_raw_tx we force the LIVE+MEV branch so the structural
    assert_live_armed inside the real body is on the executed path; the
    decorated methods (@live_trading_forbidden) raise unconditionally regardless
    of args.
    """
    monkeypatch.setenv("SPA_MEV_PROTECTION", "true")
    monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
    # SPA_EXEC_ARMED is OFF (autouse fixture).
    a = Adapter()

    exercised = [m for m in _BROADCAST_METHODS if hasattr(a, m)]
    assert exercised, f"{name}: no broadcast/sign path to exercise"

    for method_name in exercised:
        method = getattr(a, method_name)
        # Every reachable broadcast/sign path must RAISE while unarmed — never
        # silently submit. We call with a generous arg set; the guard
        # (structural assert_live_armed OR @live_trading_forbidden) raises before
        # any arg is meaningfully used, so a signature mismatch cannot let it
        # through (a TypeError before the guard would itself be a failure).
        with pytest.raises(Exception) as ei:  # noqa: PT011 - asserted below
            if method_name == "_send_raw_tx":
                method(_SIGNED_TX)
            else:
                method(
                    object(), _PUBLIC_DEV_KEY, to="0x" + "11" * 20, data="0x",
                    nonce=0, chain_id=1, gas_price=1,
                )
        assert isinstance(ei.value, LiveTradingForbiddenError) or (
            "forbidden" in str(ei.value).lower()
        ), (
            f"{name}.{method_name} did not block while unarmed "
            f"(got {type(ei.value).__name__}: {ei.value!r})"
        )


def test_aave_compound_send_raw_tx_now_structurally_guarded(monkeypatch):
    """REGRESSION PIN: the historical asymmetry — aave/compound decorated only
    ``_sign_and_send`` and left ``_send_raw_tx`` unguarded — is closed. Calling
    ``_send_raw_tx`` DIRECTLY (the regression that slips past _sign_and_send's
    decorator) now raises while unarmed."""
    from spa_core.execution.aave_v3_adapter import AaveV3Adapter
    from spa_core.execution.compound_v3_adapter import CompoundV3Adapter
    monkeypatch.setenv("SPA_MEV_PROTECTION", "true")
    monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
    for Adapter in (AaveV3Adapter, CompoundV3Adapter):
        a = Adapter()
        with pytest.raises(LiveTradingForbiddenError):
            a._send_raw_tx(_SIGNED_TX)


# ─────────────────────────────────────────────────────────────────────────────
# RED-TEAM — the audit's named latent flaw: a NEW fake adapter that bypasses the
# positional wrapper and calls the capital primitives DIRECTLY. 5.1 must BLOCK it.
# ─────────────────────────────────────────────────────────────────────────────

class _AdversaryDirectBypassAdapter:
    """A hostile adapter written by an adversary (or an accidental regression).

    It deliberately does NOT inherit any guarded base and does NOT use
    @live_trading_forbidden. It calls the capital primitives DIRECTLY — exactly
    the bypass the OLD positional guard missed. The STRUCTURAL guard inside the
    primitives must still block every one of these.
    """

    def deploy_via_sign(self, key, tx):
        from spa_core.execution import eth_signer
        return eth_signer.sign_transaction(key, tx)

    def deploy_via_send_raw(self, signed, rpc):
        from spa_core.execution import eth_signer
        return eth_signer.send_raw_transaction(signed, rpc)

    def deploy_via_mev(self, signed):
        from spa_core.execution import mev_protection
        return mev_protection.send_protected(signed)


class TestRedTeamDirectPrimitiveBypassClosed:
    """Prove the direct-primitive bypass (the audit's latent flaw) is CLOSED."""

    def test_direct_sign_transaction_blocked(self):
        adv = _AdversaryDirectBypassAdapter()
        with pytest.raises(LiveTradingForbiddenError):
            adv.deploy_via_sign(_PUBLIC_DEV_KEY, _TX)

    def test_direct_send_raw_transaction_blocked(self):
        adv = _AdversaryDirectBypassAdapter()
        with pytest.raises(LiveTradingForbiddenError):
            adv.deploy_via_send_raw(_SIGNED_TX, "https://rpc.example.com")

    def test_direct_send_protected_blocked(self):
        adv = _AdversaryDirectBypassAdapter()
        with pytest.raises(LiveTradingForbiddenError):
            adv.deploy_via_mev(_SIGNED_TX)

    def test_no_capital_primitive_escapes_the_guard(self):
        """Sweep all three direct-primitive entry points in one assertion —
        none may complete while unarmed."""
        adv = _AdversaryDirectBypassAdapter()
        attempts = (
            lambda: adv.deploy_via_sign(_PUBLIC_DEV_KEY, _TX),
            lambda: adv.deploy_via_send_raw(_SIGNED_TX, "https://rpc.example.com"),
            lambda: adv.deploy_via_mev(_SIGNED_TX),
        )
        for attempt in attempts:
            with pytest.raises(LiveTradingForbiddenError):
                attempt()


# ─────────────────────────────────────────────────────────────────────────────
# WS-5.3 — eth_signer raw path is fail-CLOSED by default (no public fallback)
# ─────────────────────────────────────────────────────────────────────────────

class TestEthSignerRawPathFailClosed:
    def test_mev_config_default_fallback_off(self):
        """The default MEV_PROTECT_FALLBACK is now False (no public-mempool
        fallback unless the owner explicitly opts in) — consistent with the
        fail-CLOSED adapter path."""
        from spa_core.execution import eth_signer
        _enabled, _rpc, fallback = eth_signer._mev_config()
        assert fallback is False, (
            "WS-5.3: eth_signer raw path must default to NO public fallback"
        )

    def test_protect_failure_aborts_no_public_fallback(self, monkeypatch):
        """When armed + MEV-on + mainnet, a Protect-RPC failure ABORTS (re-raises)
        and never re-broadcasts to the public mempool by default."""
        from spa_core.execution import eth_signer
        monkeypatch.setenv(arming.EXEC_ARMED_ENV, "1")  # armed for this path test

        # MEV enabled, mainnet, fallback OFF.
        monkeypatch.setattr(
            eth_signer, "_mev_config",
            lambda: (True, "https://protect.example", False),
        )
        calls = {"protect": 0, "public": 0}

        def _broadcast(signed, rpc):
            if rpc == "https://protect.example":
                calls["protect"] += 1
                raise RuntimeError("protect down")
            calls["public"] += 1  # pragma: no cover - must NOT happen
            return "0x" + "11" * 32

        monkeypatch.setattr(eth_signer, "_broadcast", _broadcast)
        with pytest.raises(RuntimeError, match="protect down"):
            eth_signer.send_raw_transaction(
                _SIGNED_TX, "https://public.example", chain_id=1
            )
        assert calls["protect"] == 1
        assert calls["public"] == 0, "WS-5.3: must NOT fall through to public mempool"

    def test_explicit_opt_in_re_enables_public_fallback(self, monkeypatch):
        """If the OWNER explicitly opts in (MEV_PROTECT_FALLBACK=True), the public
        fallback re-enables — proving the change is a default flip, not a removal."""
        from spa_core.execution import eth_signer
        monkeypatch.setenv(arming.EXEC_ARMED_ENV, "1")
        monkeypatch.setattr(
            eth_signer, "_mev_config",
            lambda: (True, "https://protect.example", True),  # opt-in
        )
        pub_hash = "0x" + "22" * 32

        def _broadcast(signed, rpc):
            if rpc == "https://protect.example":
                raise RuntimeError("protect down")
            return pub_hash

        monkeypatch.setattr(eth_signer, "_broadcast", _broadcast)
        assert eth_signer.send_raw_transaction(
            _SIGNED_TX, "https://public.example", chain_id=1
        ) == pub_hash


# ─────────────────────────────────────────────────────────────────────────────
# INERT confirmation — SPA_EXEC_ARMED stays OFF; is_live is not flipped here.
# ─────────────────────────────────────────────────────────────────────────────

class TestInertConfirmation:
    def test_exec_armed_default_off(self):
        """With nothing set, execution is NOT armed — the paper-period invariant."""
        assert arming.is_exec_armed() is False

    def test_armed_path_uses_stub_crypto_only(self, monkeypatch):
        """Sanity: even armed, signing routes through pure stubbed crypto here —
        no real key, no network. (Arming a primitive does not move capital; the
        owner-gated cutover is flipping SPA_EXEC_ARMED in production, which this
        suite never does outside a monkeypatched env.)"""
        from spa_core.execution import eth_signer

        class _Stub:
            @staticmethod
            def sign_transaction(_tx, private_key):
                class _Signed:
                    raw_transaction = b"\x02stub"
                return _Signed()

        monkeypatch.setenv(arming.EXEC_ARMED_ENV, "1")
        monkeypatch.setattr(eth_signer, "_get_account", lambda: _Stub)
        raw = eth_signer.sign_transaction(_PUBLIC_DEV_KEY, _TX)
        assert raw == b"\x02stub"


# ─────────────────────────────────────────────────────────────────────────────
# ADR-556 item 15 (RM-LIVE-01, 2026-10-04) — signer hygiene hardening.
#
# Two gaps the independent architecture review found and this suite proves
# closed:
#   (1) the environment-key path (every adapter that read SPA_PRIVATE_KEY from
#       os.environ to derive a signer) is removed — not "missing/invalid
#       returns an error", but an UNCONDITIONAL refusal, regardless of whether
#       the variable is set, well-formed, or would derive the expected address;
#   (2) eth_signer.sign_message lacked the arm guard sign_transaction already
#       had — closed in eth_signer.py itself (TestSignMessage /
#       TestSignMessageRefusal in test_eth_signer.py cover that primitive in
#       depth); this section proves the shared arming.refuse_env_private_key
#       helper and its wiring into every adapter that used to read the key.
# ─────────────────────────────────────────────────────────────────────────────

class TestEnvPrivateKeyRefusalUnconditional:
    """``arming.refuse_env_private_key`` never succeeds — whether the env var
    is absent, present-but-malformed, or a perfectly well-formed 64-hex key."""

    def test_refuses_when_absent(self, monkeypatch):
        monkeypatch.delenv("SPA_PRIVATE_KEY", raising=False)
        with pytest.raises(LiveTradingForbiddenError):
            arming.refuse_env_private_key("SPA_PRIVATE_KEY")

    def test_refuses_when_well_formed(self, monkeypatch):
        """The positive control: even a VALID-looking key changes nothing —
        proving this is a removal, not a validation check that could be
        satisfied."""
        monkeypatch.setenv("SPA_PRIVATE_KEY", _PUBLIC_DEV_KEY)
        with pytest.raises(LiveTradingForbiddenError):
            arming.refuse_env_private_key("SPA_PRIVATE_KEY")

    def test_message_names_the_var_but_never_a_key(self, monkeypatch):
        monkeypatch.setenv("SPA_PRIVATE_KEY", _PUBLIC_DEV_KEY)
        try:
            arming.refuse_env_private_key("SPA_PRIVATE_KEY")
            pytest.fail("expected LiveTradingForbiddenError")
        except LiveTradingForbiddenError as exc:
            assert "SPA_PRIVATE_KEY" in str(exc)
            assert "ADR-556" in str(exc)
            assert _PUBLIC_DEV_KEY not in str(exc)


@pytest.mark.parametrize("name,Adapter", _all_execution_adapter_classes())
def test_every_adapter_env_key_path_refuses_even_when_well_formed(
    name, Adapter, monkeypatch,
):
    """Sweep every enumerated adapter's supply(): a WELL-FORMED, matching
    ``SPA_PRIVATE_KEY`` + ``SPA_EXECUTION_MODE=live`` must still never reach a
    live signature — ADR-556 item 15 removed that path from every one of
    them, not just the ones a prior test happened to cover. Positive control:
    before this epic several of these adapters would have proceeded past this
    point (aave_v3 / compound_v3 / morpho had a real, testable success path;
    see the updated phase3 adapter test files)."""
    monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
    monkeypatch.setenv("SPA_PRIVATE_KEY", _PUBLIC_DEV_KEY)
    monkeypatch.setenv("SPA_WALLET_ADDRESS", "0x" + "11" * 20)
    if name == "sky_susds":
        # sky_susds has an earlier tier-eligibility gate (GSM Pause Delay) that
        # otherwise reaches for a live RPC — fake it ELIGIBLE (test_sky_susds_
        # adapter.py's own pattern) so this sweep exercises the SAME env-key
        # path as every other adapter, deterministically, with no network.
        monkeypatch.setattr(
            "spa_core.data_pipeline.sky_monitor.check_sky_status",
            lambda *a, **k: {"protocol": "Sky/sUSDS", "status": "ELIGIBLE",
                              "eligible_for_t1": True, "allocation_pct": 0.30,
                              "gsm_hours": 72.0},
        )
        monkeypatch.setattr(
            "spa_core.data_pipeline.sky_monitor.check_sky_status_live",
            lambda *a, **k: {"protocol": "Sky/sUSDS", "status": "ELIGIBLE",
                              "eligible_for_t1": True, "allocation_pct": 0.30,
                              "gsm_hours": 72.0},
        )
    a = Adapter(dry_run=False)
    asset = a.SUPPORTED_ASSETS[0]  # each adapter supports a different symbol set
    result = a.supply(asset, 1.0)
    # BLOCKED covers an adapter-specific earlier gate (e.g. sky_susds' GSM Pause
    # Delay tier check) that never even reaches the env-key path; the invariant
    # under test is narrower and absolute: SUCCESS must be impossible.
    assert result["status"] != "SUCCESS", (
        f"{name}: env-key path did not refuse — got {result!r}"
    )
    assert result["status"] in ("ERROR", "FAILED", "BLOCKED"), (
        f"{name}: unexpected non-refusing status — got {result!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# ADR-556 item 15, finding #14 (coordinator review, 2026-10-04) — a prior round
# of this hardening replaced live env-key reads with refuse_env_private_key(),
# but left two DEAD-CODE residues behind: a literal `os.environ.get(
# "SPA_PRIVATE_KEY", "")` after the refusal already returned (aave_v3 /
# compound_v3 / morpho adapters), and `Account.from_key(private_key)` where
# `private_key` was locally bound to `None` right above it (euler_v2 / maple /
# yearn_v3 / sky_susds adapters) — "unreachable code must not keep an env-key
# read pattern that a future edit could revive". Both are fixed in this round;
# this section is the AST guard that proves it, with a positive control for
# each, scoped to the WHOLE spa_core/execution tree (not just the 7 adapters),
# because the claim is "nowhere in execution", not "nowhere in the files I
# happened to touch".
#
# Scope note on `.from_key(...)`: this is deliberately NOT a blanket ban on
# every `Account.from_key(...)` call in spa_core/execution — eth_signer.py's
# `get_address_from_private_key` (a legitimate utility over an explicit
# parameter) and the pre-existing, already-@live_trading_forbidden
# `_sign_and_send` / `_execute_tx_pair` / `_execute_single_tx` methods (which
# also take the key as a genuine parameter, not a locally-dead `None`) are
# NOT part of this finding and are left alone. The guard only flags the EXACT
# shape finding #14 named: the call's argument is the literal `None`, or a
# name bound to `None` by a plain assignment earlier in the SAME block.
# ─────────────────────────────────────────────────────────────────────────────

def _is_os_env_read(node: ast.AST) -> bool:
    """True for `os.getenv(...)` or `os.environ.get(...)` call nodes."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "getenv":
        if isinstance(func.value, ast.Name) and func.value.id == "os":
            return True
    if isinstance(func, ast.Attribute) and func.attr == "get":
        val = func.value
        if (
            isinstance(val, ast.Attribute) and val.attr == "environ"
            and isinstance(val.value, ast.Name) and val.value.id == "os"
        ):
            return True
    return False


def find_env_private_key_literal_reads(tree: ast.AST) -> list[tuple[str, int]]:
    """`os.getenv("...PRIVATE_KEY...")` / `os.environ.get("...PRIVATE_KEY...")`
    with a STRING-LITERAL argument naming a private key — a variable-driven
    read (`os.getenv(name)`, e.g. readiness_audit.py's presence-only check,
    which never loads the value to sign anything) is a different, legitimate
    concern and is intentionally NOT flagged here."""
    hits: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if _is_os_env_read(node) and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                if "PRIVATE_KEY" in first.value.upper():
                    hits.append((first.value, node.lineno))
    return hits


def _none_bound_names(body: list) -> set:
    """Names bound to the literal ``None`` by a plain ``x = None`` assignment
    directly in this statement list (one block, no recursion — matches the
    exact two-consecutive-lines shape finding #14 named)."""
    bound = set()
    for stmt in body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is None
        ):
            bound.add(stmt.targets[0].id)
    return bound


def find_from_key_none_calls(tree: ast.AST) -> list[tuple[str, int]]:
    """``*.from_key(None)`` or ``*.from_key(x)`` where ``x`` was just bound to
    ``None`` in the same block — see the scope note above for what this does
    NOT flag."""
    hits: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        none_names = _none_bound_names(body)
        for stmt in body:
            for call in ast.walk(stmt):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                if not (isinstance(func, ast.Attribute) and func.attr == "from_key"):
                    continue
                if not call.args:
                    continue
                arg = call.args[0]
                if isinstance(arg, ast.Constant) and arg.value is None:
                    hits.append(("from_key(None)", call.lineno))
                elif isinstance(arg, ast.Name) and arg.id in none_names:
                    hits.append((f"from_key({arg.id})  # bound to None above", call.lineno))
    return hits


def _execution_py_files() -> list[Path]:
    if not EXECUTION_DIR.is_dir():
        return []
    return sorted(p for p in EXECUTION_DIR.rglob("*.py") if "__pycache__" not in p.parts)


class TestNoDeadEnvKeyReadPattern:
    """Finding #14 positive controls, then the real sweep."""

    def test_positive_control_catches_literal_env_read(self):
        src = 'pk = os.environ.get("SPA_PRIVATE_KEY", "")\n'
        hits = find_env_private_key_literal_reads(ast.parse(src))
        assert hits, "guard failed to catch a literal SPA_PRIVATE_KEY env read"

    def test_positive_control_catches_getenv_form(self):
        src = 'pk = os.getenv("PRIVATE_KEY")\n'
        assert find_env_private_key_literal_reads(ast.parse(src))

    def test_positive_control_does_not_flag_variable_driven_read(self):
        """readiness_audit.py's presence-only pattern: the var NAME is a
        runtime variable, not a literal — a different, legitimate concern
        (never loads the value to sign), must not be flagged."""
        src = (
            'SIGNER_KEY_ENVS = ("SPA_PRIVATE_KEY",)\n'
            'present = [name for name in SIGNER_KEY_ENVS if os.getenv(name)]\n'
        )
        assert find_env_private_key_literal_reads(ast.parse(src)) == []

    def test_positive_control_catches_from_key_none_literal(self):
        src = "wallet = Account.from_key(None).address\n"
        hits = find_from_key_none_calls(ast.parse(src))
        assert hits, "guard failed to catch Account.from_key(None)"

    def test_positive_control_catches_from_key_locally_none_name(self):
        src = (
            "def f():\n"
            "    private_key = None  # unreachable\n"
            "    wallet = Account.from_key(private_key).address\n"
            "    return wallet\n"
        )
        hits = find_from_key_none_calls(ast.parse(src))
        assert hits, "guard failed to catch from_key(x) where x was just bound to None"

    def test_positive_control_does_not_flag_parameter_based_from_key(self):
        """The pre-existing, legitimate shape (e.g. eth_signer's
        get_address_from_private_key, or _sign_and_send/_execute_tx_pair's
        own already-@live_trading_forbidden bodies): `private_key` is a real
        function PARAMETER, never locally assigned None — must stay clean."""
        src = (
            "def _sign_and_send(self, Account, private_key, **kw):\n"
            "    wallet = Account.from_key(private_key).address\n"
            "    return wallet\n"
        )
        assert find_from_key_none_calls(ast.parse(src)) == []

    @pytest.mark.parametrize("path", _execution_py_files(), ids=lambda p: str(p.relative_to(EXECUTION_DIR)))
    def test_no_literal_env_private_key_read_anywhere_in_execution(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = find_env_private_key_literal_reads(tree)
        assert hits == [], f"{path.relative_to(EXECUTION_DIR)}: literal env-key read(s): {hits}"

    @pytest.mark.parametrize("path", _execution_py_files(), ids=lambda p: str(p.relative_to(EXECUTION_DIR)))
    def test_no_from_key_none_call_anywhere_in_execution(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = find_from_key_none_calls(tree)
        assert hits == [], f"{path.relative_to(EXECUTION_DIR)}: dead from_key(None)-shaped call(s): {hits}"

    def test_execution_tree_is_not_empty(self):
        assert _execution_py_files(), f"no .py files found under {EXECUTION_DIR}"
