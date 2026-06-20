"""
Execution Router — adapter dispatcher for cross-protocol APY routing
(SPA-V34-001 / FEAT-005 Phase 2 dependency).

Pure-Python router that wraps the per-protocol adapters (AaveV3Adapter,
CompoundV3Adapter, …) into a single interface so the engine can:

  * Compare APYs across protocols for a (chain, asset) pair
  * Auto-route a supply() to the protocol with the highest *eligible* APY
    given a set of optional risk gates (min_apy, allowed_protocols,
    allowed_chains, blacklisted_protocols)
  * Sweep-withdraw an existing position from whichever protocol currently
    holds it (single-positional model — engine.py tracks where it's
    deposited in SQLite, the router just dispatches)

Phase 1 (this file): pure routing & APY arbitration. All underlying
calls go through each adapter's dry_run/live mode unchanged — the
router does not add its own dry-run flag. Whoever instantiates the
router decides the mode by setting it on each adapter.

Phase 2 (engine.py wiring, future sprint): replace direct
adapter.supply() calls in engine.py / paper_trading/engine.py with
ExecutionRouter.route_supply(). Adds the "auto-route to highest net APY
within risk limits" behaviour described in FEAT-005.

Design notes:
  * Protocol name = lowercase adapter class basename ("aave_v3" /
    "compound_v3") — keeps SQLite protocol column compatible with
    existing whitelist entries.
  * No background work, no I/O, no caching — every routing decision
    re-reads APYs from each adapter (cheap in dry-run; in live mode the
    adapter is expected to cache its own eth_call results).
  * Risk gates are *exclusionary* only: if no adapter passes, the
    router returns a NO_ROUTE record rather than picking a degraded
    fallback. This is intentional — silent fallback to a worse rate is
    a go-live anti-pattern.

Used by: spa_core/orchestration/engine.py (Phase 2 — KNOWN LIMITATION: wiring deferred
         to post-go-live sprint; requires engine.py refactor per FEAT-005),
         spa_core/tests/test_execution_router.py (Phase 1 — this sprint).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol

log = logging.getLogger("spa.execution_router")


# ─── Adapter contract (structural typing) ────────────────────────────────────

from spa_core.utils.errors import SPAError, ValidationError

class _AdapterLike(Protocol):
    """Structural typing contract — every registered adapter must expose
    these attributes / methods. We deliberately do NOT import the
    concrete adapter classes here, so the router stays decoupled and
    new adapters (Morpho, Yearn, …) can plug in without circular imports.
    """
    chain: str
    dry_run: bool
    SUPPORTED_CHAINS: list[str]
    SUPPORTED_ASSETS: list[str]

    def supply(self, asset: str, amount: float) -> dict: ...
    def withdraw(self, asset: str, amount: float) -> dict: ...
    def get_supply_balance(self, asset: str) -> float: ...
    def get_supply_apy(self, asset: str) -> float: ...
    def health_check(self) -> dict: ...


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _protocol_name(adapter: Any) -> str:
    """Map an adapter instance to a canonical protocol-name string.

    AaveV3Adapter      → "aave_v3"
    CompoundV3Adapter  → "compound_v3"
    Generic class Foo  → "foo"

    The name is used in routing decisions, risk gates, and to populate
    the protocol column for SQLite ingestion downstream.
    """
    cls_name = type(adapter).__name__
    # Drop "Adapter" suffix if present; lowercase; CamelCase → snake_case.
    if cls_name.endswith("Adapter"):
        cls_name = cls_name[: -len("Adapter")]
    out: list[str] = []
    for i, ch in enumerate(cls_name):
        if ch.isupper() and i > 0 and not cls_name[i - 1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


# ─── Router ──────────────────────────────────────────────────────────────────

class ExecutionRouter:
    """
    Dispatches supply / withdraw across multiple registered adapters,
    picking the protocol with the highest eligible supply APY.

    Usage::

        aave = AaveV3Adapter(chain="ethereum")
        comp = CompoundV3Adapter(chain="ethereum")
        router = ExecutionRouter([aave, comp])

        # Best-APY routing
        result = router.route_supply("USDC", 1000.0, chain="ethereum")
        # → {"protocol": "compound_v3", "apy": 4.5, "supply_result": {...}, ...}

        # APY comparison without committing
        rates = router.get_apy_comparison("USDC", chain="ethereum")
        # → {"aave_v3": 4.2, "compound_v3": 4.5}

        # Withdraw from a specifically named protocol
        result = router.route_withdraw(
            "USDC", 500.0, chain="ethereum", protocol="aave_v3",
        )

    Risk gates (all optional, all exclusionary):
        min_apy:                 float    — adapters with APY < min_apy
                                            are discarded.
        allowed_protocols:       set[str] — only these protocols may win.
        blacklisted_protocols:   set[str] — these protocols are skipped.
        allowed_chains:          set[str] — adapter.chain must be in set.
    """

    def __init__(self, adapters: Iterable[Any]) -> None:
        """Initialise the router with a sequence of adapter instances.

        Args:
            adapters: Iterable of adapter instances satisfying _AdapterLike.

        Raises:
            ValueError: If two adapters resolve to the same protocol
                name on the same chain — that's an ambiguous registry
                and we refuse to silently overwrite.
        """
        self._adapters: dict[tuple[str, str], Any] = {}
        for adapter in adapters:
            name = _protocol_name(adapter)
            key = (name, adapter.chain)
            if key in self._adapters:
                raise SPAError(f"Duplicate adapter registration: protocol={name!r} chain={adapter.chain!r} already registered")
            self._adapters[key] = adapter
            log.debug(
                "ExecutionRouter registered: protocol=%s chain=%s dry_run=%s",
                name, adapter.chain, adapter.dry_run,
            )

    # ─── Introspection ───────────────────────────────────────────────────────

    def registered_protocols(self) -> list[str]:
        """Return the sorted unique list of registered protocol names."""
        return sorted({name for name, _chain in self._adapters})

    def registered_chains(self) -> list[str]:
        """Return the sorted unique list of chains covered by any adapter."""
        return sorted({chain for _name, chain in self._adapters})

    def get_adapter(self, protocol: str, chain: str) -> Any | None:
        """Return the adapter for (protocol, chain), or None if not registered."""
        return self._adapters.get((protocol, chain))

    # ─── Eligibility ─────────────────────────────────────────────────────────

    def _eligible_adapters(
        self,
        asset: str,
        chain: str,
        *,
        allowed_protocols: set[str] | None,
        blacklisted_protocols: set[str] | None,
        allowed_chains: set[str] | None,
    ) -> list[tuple[str, Any]]:
        """Filter adapters by chain, asset support, and protocol gates.

        Returns a list of (protocol_name, adapter) pairs that are eligible.
        Order of the returned list is undefined — caller is expected to
        sort by APY when needed.
        """
        out: list[tuple[str, Any]] = []
        for (name, ch), adapter in self._adapters.items():
            if ch != chain:
                continue
            if allowed_chains is not None and ch not in allowed_chains:
                continue
            if allowed_protocols is not None and name not in allowed_protocols:
                continue
            if blacklisted_protocols is not None and name in blacklisted_protocols:
                continue
            if asset not in adapter.SUPPORTED_ASSETS:
                continue
            out.append((name, adapter))
        return out

    # ─── APY comparison ──────────────────────────────────────────────────────

    def get_apy_comparison(
        self,
        asset: str,
        chain: str,
        *,
        allowed_protocols: set[str] | None = None,
        blacklisted_protocols: set[str] | None = None,
    ) -> dict[str, float]:
        """Return a {protocol_name: apy_percent} mapping for the (asset, chain).

        Adapters that don't support the asset on this chain are excluded.
        Risk gates (allowed / blacklisted) are honoured. APY units match
        the underlying adapter — percent, not fraction.
        """
        eligible = self._eligible_adapters(
            asset, chain,
            allowed_protocols=allowed_protocols,
            blacklisted_protocols=blacklisted_protocols,
            allowed_chains=None,
        )
        return {name: adapter.get_supply_apy(asset) for name, adapter in eligible}

    # ─── Best protocol selection ─────────────────────────────────────────────

    def select_best_protocol(
        self,
        asset: str,
        chain: str,
        *,
        min_apy: float | None = None,
        allowed_protocols: set[str] | None = None,
        blacklisted_protocols: set[str] | None = None,
    ) -> tuple[str, Any, float] | None:
        """Return (protocol_name, adapter, apy_percent) of the best eligible
        protocol, or None if no adapter qualifies.

        Tie-breaking: when two protocols return identical APYs, the
        protocol that sorts earlier alphabetically wins (deterministic).
        """
        rates = self.get_apy_comparison(
            asset, chain,
            allowed_protocols=allowed_protocols,
            blacklisted_protocols=blacklisted_protocols,
        )
        if not rates:
            return None
        if min_apy is not None:
            rates = {p: r for p, r in rates.items() if r >= min_apy}
        if not rates:
            return None
        # Sort by (-apy, name) → highest APY first, alphabetical for ties.
        best_name = sorted(rates.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        adapter = self._adapters[(best_name, chain)]
        return best_name, adapter, rates[best_name]

    # ─── Routed supply ───────────────────────────────────────────────────────

    def route_supply(
        self,
        asset: str,
        amount: float,
        *,
        chain: str,
        min_apy: float | None = None,
        allowed_protocols: set[str] | None = None,
        blacklisted_protocols: set[str] | None = None,
    ) -> dict:
        """Route a supply() to the protocol with the highest eligible APY.

        Returns a router-level envelope::

            {
                "status":         "ROUTED" | "NO_ROUTE",
                "protocol":       str | None,    # winning protocol_name
                "chain":          str,
                "asset":          str,
                "amount":         float,
                "apy":            float | None,  # winning APY percent
                "comparison":     dict[str, float],   # all candidate APYs
                "supply_result":  dict | None,   # adapter.supply() return
                "reason":         str | None,    # populated when NO_ROUTE
                "timestamp":      str,           # ISO-8601 UTC
            }

        Raises:
            ValueError: On non-positive amount.
        """
        if amount is None or amount <= 0:
            raise ValidationError("amount", amount, "must be a strictly positive number")
        ts = datetime.now(timezone.utc).isoformat()
        comparison = self.get_apy_comparison(
            asset, chain,
            allowed_protocols=allowed_protocols,
            blacklisted_protocols=blacklisted_protocols,
        )
        best = self.select_best_protocol(
            asset, chain,
            min_apy=min_apy,
            allowed_protocols=allowed_protocols,
            blacklisted_protocols=blacklisted_protocols,
        )
        if best is None:
            reason = "no_eligible_adapter"
            if comparison and min_apy is not None:
                reason = f"all_below_min_apy_{min_apy}"
            elif not comparison:
                reason = "no_adapter_supports_asset_on_chain"
            log.warning(
                "[route_supply NO_ROUTE] asset=%s chain=%s reason=%s",
                asset, chain, reason,
            )
            return {
                "status":        "NO_ROUTE",
                "protocol":      None,
                "chain":         chain,
                "asset":         asset,
                "amount":        amount,
                "apy":           None,
                "comparison":    comparison,
                "supply_result": None,
                "reason":        reason,
                "timestamp":     ts,
            }
        protocol_name, adapter, apy = best
        log.info(
            "[route_supply ROUTED] asset=%s chain=%s protocol=%s apy=%.4f",
            asset, chain, protocol_name, apy,
        )
        supply_result = adapter.supply(asset, amount)
        return {
            "status":        "ROUTED",
            "protocol":      protocol_name,
            "chain":         chain,
            "asset":         asset,
            "amount":        amount,
            "apy":           apy,
            "comparison":    comparison,
            "supply_result": supply_result,
            "reason":        None,
            "timestamp":     ts,
        }

    # ─── Routed withdraw ─────────────────────────────────────────────────────

    def route_withdraw(
        self,
        asset: str,
        amount: float,
        *,
        chain: str,
        protocol: str,
    ) -> dict:
        """Withdraw ``amount`` of ``asset`` from a *specifically named*
        protocol on ``chain``.

        Withdrawals are NOT APY-routed — the caller (engine.py) is
        responsible for knowing where the position lives. The router
        only validates the registry, dispatches the call, and wraps the
        adapter response in the standard envelope.

        Returns::

            {
                "status":          "ROUTED" | "NO_ROUTE",
                "protocol":        str,
                "chain":           str,
                "asset":           str,
                "amount":          float,
                "withdraw_result": dict | None,
                "reason":          str | None,
                "timestamp":       str,
            }

        Raises:
            ValueError: On non-positive amount.
        """
        if amount is None or amount <= 0:
            raise ValidationError("amount", amount, "must be a strictly positive number")
        ts = datetime.now(timezone.utc).isoformat()
        adapter = self._adapters.get((protocol, chain))
        if adapter is None:
            log.warning(
                "[route_withdraw NO_ROUTE] no adapter for protocol=%s chain=%s",
                protocol, chain,
            )
            return {
                "status":          "NO_ROUTE",
                "protocol":        protocol,
                "chain":           chain,
                "asset":           asset,
                "amount":          amount,
                "withdraw_result": None,
                "reason":          "no_adapter_for_protocol_chain",
                "timestamp":       ts,
            }
        if asset not in adapter.SUPPORTED_ASSETS:
            log.warning(
                "[route_withdraw NO_ROUTE] protocol=%s does not support asset=%s",
                protocol, asset,
            )
            return {
                "status":          "NO_ROUTE",
                "protocol":        protocol,
                "chain":           chain,
                "asset":           asset,
                "amount":          amount,
                "withdraw_result": None,
                "reason":          "asset_unsupported_by_protocol",
                "timestamp":       ts,
            }
        log.info(
            "[route_withdraw ROUTED] asset=%s chain=%s protocol=%s amount=%.6f",
            asset, chain, protocol, amount,
        )
        return {
            "status":          "ROUTED",
            "protocol":        protocol,
            "chain":           chain,
            "asset":           asset,
            "amount":          amount,
            "withdraw_result": adapter.withdraw(asset, amount),
            "reason":          None,
            "timestamp":       ts,
        }

    # ─── Aggregate balances ──────────────────────────────────────────────────

    def aggregate_balances(self, asset: str, chain: str) -> dict[str, float]:
        """Return per-protocol current balances for (asset, chain).

        Useful for a "where is my money?" sweep on engine boot. Each
        value is whatever adapter.get_supply_balance() returns — dry-run
        mocks today, live eth_call reads in Phase 2.
        """
        out: dict[str, float] = {}
        for (name, ch), adapter in self._adapters.items():
            if ch != chain or asset not in adapter.SUPPORTED_ASSETS:
                continue
            out[name] = adapter.get_supply_balance(asset)
        return out

    # ─── Health snapshot ─────────────────────────────────────────────────────

    def health_check(self) -> dict:
        """Aggregate health snapshot of all registered adapters.

        Returns::

            {
                "router":     "execution_router_v1",
                "adapters":   int,
                "protocols":  list[str],
                "chains":     list[str],
                "details":    {
                    "<protocol>@<chain>": adapter.health_check(),
                    ...
                },
                "timestamp":  str,
            }
        """
        details: dict[str, dict] = {}
        for (name, chain), adapter in self._adapters.items():
            details[f"{name}@{chain}"] = adapter.health_check()
        return {
            "router":    "execution_router_v1",
            "adapters":  len(self._adapters),
            "protocols": self.registered_protocols(),
            "chains":    self.registered_chains(),
            "details":   details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


if __name__ == "__main__":  # pragma: no cover — smoke harness
    import json
    from spa_core.execution.aave_v3_adapter import AaveV3Adapter
    from spa_core.execution.compound_v3_adapter import CompoundV3Adapter

    logging.basicConfig(level=logging.INFO)
    router = ExecutionRouter([
        AaveV3Adapter(chain="ethereum"),
        AaveV3Adapter(chain="arbitrum"),
        AaveV3Adapter(chain="base"),
        CompoundV3Adapter(chain="ethereum"),
        CompoundV3Adapter(chain="arbitrum"),
        CompoundV3Adapter(chain="base"),
    ])
    print("Health:", json.dumps(router.health_check(), indent=2))
    print("APY comparison USDC@ethereum:",
          router.get_apy_comparison("USDC", chain="ethereum"))
    print("Route supply USDC 1000 @ ethereum:",
          json.dumps(router.route_supply("USDC", 1000.0, chain="ethereum"), indent=2))
    print("Aggregate USDC@ethereum balances:",
          router.aggregate_balances("USDC", chain="ethereum"))
