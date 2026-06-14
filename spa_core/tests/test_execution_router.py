"""
Deterministic unit tests for spa_core.execution.router.ExecutionRouter
(SPA-V34-001 / FEAT-005 Phase 2 dependency).

No DB, no network — uses dry-run adapter instances + in-line fake
adapters where finer-grained APY control is needed.
"""
from __future__ import annotations

import pytest

from spa_core.execution.aave_v3_adapter import AaveV3Adapter
from spa_core.execution.compound_v3_adapter import CompoundV3Adapter
from spa_core.execution.router import ExecutionRouter, _protocol_name


# ─── Fixtures ────────────────────────────────────────────────────────────────


class _FakeAdapter:
    """Minimal fake satisfying _AdapterLike — lets tests pin specific APYs
    and supported assets without monkey-patching the real adapter mocks."""

    SUPPORTED_CHAINS = ["ethereum", "arbitrum", "base"]

    def __init__(
        self,
        name: str,
        chain: str,
        apys: dict[str, float],
        balances: dict[str, float] | None = None,
        supported_assets: list[str] | None = None,
        dry_run: bool = True,
    ) -> None:
        # name is used only to control _protocol_name() output via class
        # name — we create a unique subclass per fake to keep distinct names.
        type(self).__name__ = name
        self.chain = chain
        self.dry_run = dry_run
        self._apys = apys
        self._balances = balances or {a: 0.0 for a in apys}
        self.SUPPORTED_ASSETS = supported_assets or list(apys.keys())
        self.supply_calls: list[tuple[str, float]] = []
        self.withdraw_calls: list[tuple[str, float]] = []

    def supply(self, asset: str, amount: float) -> dict:
        self.supply_calls.append((asset, amount))
        return {"status": "DRY_RUN", "asset": asset, "amount": amount}

    def withdraw(self, asset: str, amount: float) -> dict:
        self.withdraw_calls.append((asset, amount))
        return {"status": "DRY_RUN", "asset": asset, "amount": amount}

    def get_supply_balance(self, asset: str) -> float:
        return self._balances.get(asset, 0.0)

    def get_supply_apy(self, asset: str) -> float:
        return self._apys.get(asset, 0.0)

    def health_check(self) -> dict:
        return {"chain": self.chain, "dry_run": self.dry_run, "fake": True}


def _make_fake(name: str, chain: str, apys: dict[str, float], **kw) -> _FakeAdapter:
    """Create a fresh subclass of _FakeAdapter so _protocol_name() picks up
    the test-controlled class name."""
    cls = type(name, (_FakeAdapter,), {})
    return cls(name=name, chain=chain, apys=apys, **kw)


# ─── _protocol_name helper ───────────────────────────────────────────────────


class TestProtocolName:
    def test_aave_v3_adapter_name(self):
        assert _protocol_name(AaveV3Adapter(chain="ethereum")) == "aave_v3"

    def test_compound_v3_adapter_name(self):
        assert _protocol_name(CompoundV3Adapter(chain="ethereum")) == "compound_v3"

    def test_generic_camelcase_to_snake_case(self):
        class MorphoBlueAdapter:
            chain = "ethereum"
            dry_run = True
            SUPPORTED_CHAINS = ["ethereum"]
            SUPPORTED_ASSETS = ["USDC"]
        assert _protocol_name(MorphoBlueAdapter()) == "morpho_blue"

    def test_strips_adapter_suffix(self):
        class FooAdapter:
            chain = "ethereum"
            dry_run = True
            SUPPORTED_CHAINS = ["ethereum"]
            SUPPORTED_ASSETS = ["USDC"]
        assert _protocol_name(FooAdapter()) == "foo"


# ─── Router registry ─────────────────────────────────────────────────────────


class TestRouterRegistry:
    def test_register_real_adapters(self):
        aave = AaveV3Adapter(chain="ethereum")
        comp = CompoundV3Adapter(chain="ethereum")
        router = ExecutionRouter([aave, comp])
        assert set(router.registered_protocols()) == {"aave_v3", "compound_v3"}
        assert router.registered_chains() == ["ethereum"]

    def test_register_multiple_chains(self):
        adapters = [
            AaveV3Adapter(chain="ethereum"),
            AaveV3Adapter(chain="arbitrum"),
            AaveV3Adapter(chain="base"),
            CompoundV3Adapter(chain="ethereum"),
        ]
        router = ExecutionRouter(adapters)
        assert router.registered_chains() == ["arbitrum", "base", "ethereum"]
        assert router.registered_protocols() == ["aave_v3", "compound_v3"]

    def test_duplicate_adapter_rejected(self):
        with pytest.raises(ValueError, match="Duplicate adapter"):
            ExecutionRouter([
                AaveV3Adapter(chain="ethereum"),
                AaveV3Adapter(chain="ethereum"),
            ])

    def test_get_adapter_returns_instance(self):
        aave = AaveV3Adapter(chain="ethereum")
        router = ExecutionRouter([aave])
        assert router.get_adapter("aave_v3", "ethereum") is aave
        assert router.get_adapter("aave_v3", "arbitrum") is None
        assert router.get_adapter("compound_v3", "ethereum") is None


# ─── APY comparison ──────────────────────────────────────────────────────────


class TestAPYComparison:
    def test_apy_comparison_two_protocols(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),
            CompoundV3Adapter(chain="ethereum"),
        ])
        rates = router.get_apy_comparison("USDC", chain="ethereum")
        # AaveV3 mock USDC APY = 4.2, CompoundV3 mock USDC APY = 4.5
        assert rates == {"aave_v3": 4.2, "compound_v3": 4.5}

    def test_apy_comparison_skips_unsupported_asset(self):
        # Compound V3 only supports USDC — querying DAI must skip it.
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),
            CompoundV3Adapter(chain="ethereum"),
        ])
        rates = router.get_apy_comparison("DAI", chain="ethereum")
        assert rates == {"aave_v3": 3.5}

    def test_apy_comparison_respects_allowed_protocols(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),
            CompoundV3Adapter(chain="ethereum"),
        ])
        rates = router.get_apy_comparison(
            "USDC", chain="ethereum",
            allowed_protocols={"aave_v3"},
        )
        assert rates == {"aave_v3": 4.2}

    def test_apy_comparison_respects_blacklist(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),
            CompoundV3Adapter(chain="ethereum"),
        ])
        rates = router.get_apy_comparison(
            "USDC", chain="ethereum",
            blacklisted_protocols={"compound_v3"},
        )
        assert rates == {"aave_v3": 4.2}

    def test_apy_comparison_unknown_chain_returns_empty(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),
        ])
        assert router.get_apy_comparison("USDC", chain="optimism") == {}


# ─── Best-protocol selection ─────────────────────────────────────────────────


class TestSelectBestProtocol:
    def test_picks_highest_apy(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),       # USDC = 4.2
            CompoundV3Adapter(chain="ethereum"),   # USDC = 4.5
        ])
        best = router.select_best_protocol("USDC", chain="ethereum")
        assert best is not None
        name, adapter, apy = best
        assert name == "compound_v3"
        assert apy == pytest.approx(4.5)

    def test_returns_none_when_no_adapter(self):
        router = ExecutionRouter([AaveV3Adapter(chain="ethereum")])
        assert router.select_best_protocol("USDC", chain="optimism") is None

    def test_min_apy_filter_excludes_all(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),
            CompoundV3Adapter(chain="ethereum"),
        ])
        # Both mock APYs are <10 — every adapter is filtered out.
        assert router.select_best_protocol(
            "USDC", chain="ethereum", min_apy=10.0,
        ) is None

    def test_min_apy_filter_keeps_one(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),       # 4.2
            CompoundV3Adapter(chain="ethereum"),   # 4.5
        ])
        best = router.select_best_protocol(
            "USDC", chain="ethereum", min_apy=4.3,
        )
        assert best is not None
        assert best[0] == "compound_v3"

    def test_alphabetic_tiebreak(self):
        # Two fakes with identical APY — winner sorts alphabetically.
        a = _make_fake("ZebraAdapter", "ethereum", {"USDC": 5.0})
        b = _make_fake("AlphaAdapter", "ethereum", {"USDC": 5.0})
        router = ExecutionRouter([a, b])
        best = router.select_best_protocol("USDC", chain="ethereum")
        assert best is not None
        assert best[0] == "alpha"   # 'alpha' < 'zebra'

    def test_blacklist_excludes_winner(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),       # 4.2
            CompoundV3Adapter(chain="ethereum"),   # 4.5
        ])
        best = router.select_best_protocol(
            "USDC", chain="ethereum",
            blacklisted_protocols={"compound_v3"},
        )
        assert best is not None
        assert best[0] == "aave_v3"


# ─── route_supply ────────────────────────────────────────────────────────────


class TestRouteSupply:
    def test_routed_to_best(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),
            CompoundV3Adapter(chain="ethereum"),
        ])
        result = router.route_supply("USDC", 1000.0, chain="ethereum")
        assert result["status"] == "ROUTED"
        assert result["protocol"] == "compound_v3"   # higher APY mock
        assert result["asset"] == "USDC"
        assert result["amount"] == 1000.0
        assert result["apy"] == pytest.approx(4.5)
        assert result["supply_result"]["status"] == "DRY_RUN"
        assert result["reason"] is None
        assert "timestamp" in result

    def test_no_route_when_min_apy_too_high(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),
            CompoundV3Adapter(chain="ethereum"),
        ])
        result = router.route_supply(
            "USDC", 1000.0, chain="ethereum", min_apy=10.0,
        )
        assert result["status"] == "NO_ROUTE"
        assert result["protocol"] is None
        assert result["supply_result"] is None
        assert "all_below_min_apy" in result["reason"]

    def test_no_route_when_unknown_chain(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),
        ])
        result = router.route_supply("USDC", 100.0, chain="optimism")
        assert result["status"] == "NO_ROUTE"
        assert result["reason"] == "no_adapter_supports_asset_on_chain"
        assert result["comparison"] == {}

    def test_invalid_amount_raises(self):
        router = ExecutionRouter([AaveV3Adapter(chain="ethereum")])
        with pytest.raises(ValueError, match="positive number"):
            router.route_supply("USDC", 0.0, chain="ethereum")
        with pytest.raises(ValueError, match="positive number"):
            router.route_supply("USDC", -100.0, chain="ethereum")

    def test_allowed_protocols_restricts_routing(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),
            CompoundV3Adapter(chain="ethereum"),
        ])
        result = router.route_supply(
            "USDC", 500.0, chain="ethereum",
            allowed_protocols={"aave_v3"},
        )
        assert result["status"] == "ROUTED"
        assert result["protocol"] == "aave_v3"
        assert result["apy"] == pytest.approx(4.2)

    def test_blacklist_excludes_winner(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),
            CompoundV3Adapter(chain="ethereum"),
        ])
        result = router.route_supply(
            "USDC", 500.0, chain="ethereum",
            blacklisted_protocols={"compound_v3"},
        )
        assert result["status"] == "ROUTED"
        assert result["protocol"] == "aave_v3"

    def test_comparison_field_includes_all_eligible(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),
            CompoundV3Adapter(chain="ethereum"),
        ])
        result = router.route_supply("USDC", 100.0, chain="ethereum")
        assert set(result["comparison"]) == {"aave_v3", "compound_v3"}

    def test_supply_is_actually_called(self):
        fake = _make_fake("WinningAdapter", "ethereum", {"USDC": 9.0})
        router = ExecutionRouter([fake])
        router.route_supply("USDC", 250.0, chain="ethereum")
        assert fake.supply_calls == [("USDC", 250.0)]


# ─── route_withdraw ──────────────────────────────────────────────────────────


class TestRouteWithdraw:
    def test_routed_to_named_protocol(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),
            CompoundV3Adapter(chain="ethereum"),
        ])
        result = router.route_withdraw(
            "USDC", 100.0, chain="ethereum", protocol="aave_v3",
        )
        assert result["status"] == "ROUTED"
        assert result["protocol"] == "aave_v3"
        assert result["withdraw_result"]["status"] == "DRY_RUN"

    def test_unknown_protocol_returns_no_route(self):
        router = ExecutionRouter([AaveV3Adapter(chain="ethereum")])
        result = router.route_withdraw(
            "USDC", 50.0, chain="ethereum", protocol="bogus",
        )
        assert result["status"] == "NO_ROUTE"
        assert result["reason"] == "no_adapter_for_protocol_chain"

    def test_unsupported_asset_for_protocol(self):
        # Compound V3 doesn't support DAI in Phase 1.
        router = ExecutionRouter([CompoundV3Adapter(chain="ethereum")])
        result = router.route_withdraw(
            "DAI", 50.0, chain="ethereum", protocol="compound_v3",
        )
        assert result["status"] == "NO_ROUTE"
        assert result["reason"] == "asset_unsupported_by_protocol"

    def test_invalid_amount_raises(self):
        router = ExecutionRouter([AaveV3Adapter(chain="ethereum")])
        with pytest.raises(ValueError):
            router.route_withdraw(
                "USDC", -10.0, chain="ethereum", protocol="aave_v3",
            )

    def test_withdraw_actually_called_on_adapter(self):
        fake = _make_fake("CustomAdapter", "ethereum", {"USDC": 5.0})
        router = ExecutionRouter([fake])
        router.route_withdraw(
            "USDC", 300.0, chain="ethereum", protocol="custom",
        )
        assert fake.withdraw_calls == [("USDC", 300.0)]


# ─── Aggregate balances ──────────────────────────────────────────────────────


class TestAggregateBalances:
    def test_collects_balances_per_protocol(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),       # USDC mock balance = 10000
            CompoundV3Adapter(chain="ethereum"),   # USDC mock balance =  8000
        ])
        bals = router.aggregate_balances("USDC", chain="ethereum")
        assert bals == {"aave_v3": 10000.0, "compound_v3": 8000.0}

    def test_skips_chains_without_asset_support(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),
            CompoundV3Adapter(chain="ethereum"),
        ])
        # DAI: only Aave supports it.
        assert router.aggregate_balances("DAI", chain="ethereum") == {
            "aave_v3": 2500.0,
        }

    def test_empty_on_unknown_chain(self):
        router = ExecutionRouter([AaveV3Adapter(chain="ethereum")])
        assert router.aggregate_balances("USDC", chain="optimism") == {}


# ─── Health check ────────────────────────────────────────────────────────────


class TestHealthCheck:
    def test_health_check_structure(self):
        router = ExecutionRouter([
            AaveV3Adapter(chain="ethereum"),
            CompoundV3Adapter(chain="ethereum"),
        ])
        h = router.health_check()
        assert h["router"] == "execution_router_v1"
        assert h["adapters"] == 2
        assert set(h["protocols"]) == {"aave_v3", "compound_v3"}
        assert h["chains"] == ["ethereum"]
        assert "aave_v3@ethereum" in h["details"]
        assert "compound_v3@ethereum" in h["details"]
        assert h["details"]["aave_v3@ethereum"]["chain"] == "ethereum"
        assert "timestamp" in h
