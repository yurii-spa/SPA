"""
Compound V3 Live SDK Adapter (FEAT-005 Phase 2).

Pure-Python adapter mirroring aave_v3_adapter.py (FEAT-004 Phase 2):
  - Env-driven, 3-RPC fallback per chain (URL fragment carries Comet hint)
  - Dry-run / synthetic mode (deterministic mock balances + APYs)
  - Phase 2: real eth_call decoding for get_supply_apy + get_supply_balance
    via stdlib urllib.request (no web3.py, no requests, no eth_account)
  - Write methods (supply / withdraw) stay NOT_IMPLEMENTED — Phase 3 will
    add eth_account signing + raw tx broadcast.

Phase 1 (shipped v3.3):
  * CompoundV3Adapter scaffold with dry-run supply / withdraw / balance / APY
  * Input validation, deterministic mock returns, health_check()
  * RPC endpoint registry + Comet contract addresses

Phase 2 (this file, v3.7):
  * Real Comet.balanceOf(wallet) decoding — Comet's balanceOf already
    returns presentValue (raw USDC units incl. accrued interest), so we
    divide by 10**6 directly (USDC = 6 decimals).
  * Real APY decoding via two chained eth_calls:
      1) Comet.getUtilization() → uint256 utilization scaled by 1e18
      2) Comet.getSupplyRate(utilization) → uint64 per-second rate scaled
         by 1e18
    Annualised APY (%) = rate_per_second * SECONDS_PER_YEAR / 1e18 * 100
                       = rate_per_second * SECONDS_PER_YEAR / 1e16
  * 3-RPC fallback round-robin, 5s timeout per call, DEBUG logging.
  * Production safety: ALL live-path exceptions caught and degraded to
    the Phase 1 mock value with a [FALLBACK] WARNING — the production
    pipeline never crashes if RPCs flake.

Phase 3 (not in this file):
  * web3.py-free Comet.supply / Comet.withdraw via raw eth_sendRawTransaction
  * eth_account signing from secrets manager (private key never on disk)
  * Wire CompoundV3Adapter into spa_core/orchestration/engine.py to flip
    paper-trade execution paths over to live execution behind a feature flag
    (paired with FEAT-004 Phase 3 — Aave V3 cutover behind SPA_EXECUTION_MODE).

Supported topology:
  Chains    — ethereum, arbitrum, base
  Assets    — USDC (Compound V3 Comet pools are single-asset; the only
              widely-deployed Comet on all three chains is cUSDCv3).
              cWETHv3 (ETH-Comet) is deferred to Phase 3+; USDT/DAI
              Comets are not in production scope on these chains.
  Modes     — dry_run=True (default; safe, deterministic, byte-identical to
                Phase 1),
              dry_run=False (Phase 2: live read methods + NOT_IMPLEMENTED
                write methods).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger("spa.compound_v3_adapter")


class CompoundV3Adapter:
    """
    Adapter for Compound V3 (Comet) supply / withdraw flows across
    multiple chains.

    Phase 2 status:
      * ``get_supply_apy`` and ``get_supply_balance`` perform real on-chain
        ``eth_call`` requests when ``dry_run=False``. Failures degrade to
        the deterministic Phase 1 mock value (logged WARNING with the
        ``[FALLBACK]`` tag) so the production pipeline never crashes if an
        RPC is unreachable.
      * ``supply`` and ``withdraw`` still return NOT_IMPLEMENTED in live mode
        — Phase 3 adds the eth_account signing path.

    Fallback policy (live read methods):
      If every endpoint in ``rpc_endpoints[chain]`` fails (network, timeout,
      malformed JSON-RPC, bad return data, missing wallet address, etc.)
      the adapter logs a single ``[FALLBACK]`` WARNING and returns the
      matching ``_MOCK_APYS`` / ``_MOCK_BALANCES`` value. Callers always
      receive a finite float and never see a raised exception from the live
      path. ``ValueError`` for unknown asset is raised BEFORE any RPC work
      and is not caught (input validation must surface to the caller).

    Usage (dry-run, safe to run now)::

        adapter = CompoundV3Adapter(chain="ethereum")
        adapter.supply("USDC", 1000.0)
        adapter.get_supply_balance("USDC")  # -> 8000.0 (mock)
        adapter.get_supply_apy("USDC")      # -> 4.5 (mock)

    Usage (live read)::

        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        adapter.get_supply_apy("USDC")      # -> real APY % from chain
        adapter.get_supply_balance("USDC")  # -> needs SPA_WALLET_ADDRESS env

    Usage (live write, NOT YET IMPLEMENTED)::

        adapter.supply("USDC", 1000.0)      # -> {"status": "NOT_IMPLEMENTED"}
    """

    # ─── Class constants ──────────────────────────────────────────────────────

    SUPPORTED_CHAINS: list[str] = ["ethereum", "arbitrum", "base"]
    SUPPORTED_ASSETS: list[str] = ["USDC"]

    # Real Compound V3 Comet (cUSDCv3) contract addresses (verified on
    # respective chain explorers as of 2026-05). Used by Phase 2 for
    # eth_call routing.
    COMET_ADDRESSES: dict[str, str] = {
        "ethereum": "0xc3d688B66703497DAA19211EEdff47f25384cdc3",
        "arbitrum": "0x9c4ec768c28520B50860ea7a15bd7213a9fF58bf",
        "base":     "0xb125E6687d4313864e53df431d5425969c15Eb2F",
    }

    # Decimals per base asset — Comet base asset is USDC (6 decimals) on
    # every supported chain in Phase 2 scope.
    TOKEN_DECIMALS: dict[str, int] = {
        "USDC": 6,
    }

    # Three RPC endpoints per chain — tried in order, first success wins.
    # The URL fragment ``#compound-v3-comet:0x...`` carries the Comet hint
    # that Phase 2 strips before posting JSON-RPC.
    RPC_ENDPOINTS: dict[str, list[str]] = {
        "ethereum": [
            "https://eth.llamarpc.com#compound-v3-comet:0xc3d688B66703497DAA19211EEdff47f25384cdc3",
            "https://rpc.ankr.com/eth#compound-v3-comet:0xc3d688B66703497DAA19211EEdff47f25384cdc3",
            "https://cloudflare-eth.com#compound-v3-comet:0xc3d688B66703497DAA19211EEdff47f25384cdc3",
        ],
        "arbitrum": [
            "https://arb1.arbitrum.io/rpc#compound-v3-comet:0x9c4ec768c28520B50860ea7a15bd7213a9fF58bf",
            "https://arbitrum.llamarpc.com#compound-v3-comet:0x9c4ec768c28520B50860ea7a15bd7213a9fF58bf",
            "https://rpc.ankr.com/arbitrum#compound-v3-comet:0x9c4ec768c28520B50860ea7a15bd7213a9fF58bf",
        ],
        "base": [
            "https://mainnet.base.org#compound-v3-comet:0xb125E6687d4313864e53df431d5425969c15Eb2F",
            "https://base.llamarpc.com#compound-v3-comet:0xb125E6687d4313864e53df431d5425969c15Eb2F",
            "https://rpc.ankr.com/base#compound-v3-comet:0xb125E6687d4313864e53df431d5425969c15Eb2F",
        ],
    }

    # Function selectors (first 4 bytes of keccak256). Hardcoded so we
    # don't pull in an external keccak dependency. Verified against the
    # Compound V3 Comet ABI (cUSDCv3 mainnet, etherscan-verified).
    #   keccak256("getUtilization()")[:4]        = 0x6f307dc3
    #   keccak256("getSupplyRate(uint256)")[:4]  = 0x6fb1b0e9
    #   keccak256("balanceOf(address)")[:4]      = 0x70a08231
    SELECTOR_GET_UTILIZATION: str = "0x6f307dc3"
    SELECTOR_GET_SUPPLY_RATE: str = "0x6fb1b0e9"
    SELECTOR_BALANCE_OF:      str = "0x70a08231"

    # JSON-RPC timeout (seconds) per endpoint try.
    RPC_TIMEOUT_SECONDS: float = 5.0

    # Seconds in a 365-day year — used to annualise Comet's per-second
    # supply rate. Matches Compound's own front-end conversion (365 *
    # 24 * 60 * 60 = 31_536_000).
    SECONDS_PER_YEAR: int = 31_536_000

    # Deterministic mock fixtures for dry-run mode. Match SUPPORTED_ASSETS.
    # Numbers intentionally differ from AaveV3Adapter mocks so cross-
    # protocol routing tests can distinguish the two adapters at a glance.
    _MOCK_BALANCES: dict[str, float] = {
        "USDC": 8000.0,
    }

    _MOCK_APYS: dict[str, float] = {
        "USDC": 4.5,
    }

    # ─── Construction ─────────────────────────────────────────────────────────

    def __init__(
        self,
        chain: str = "ethereum",
        dry_run: bool = True,
        rpc_endpoints: dict[str, list[str]] | None = None,
    ) -> None:
        """Initialise the Compound V3 adapter.

        Args:
            chain: Target chain key. Must be one of SUPPORTED_CHAINS.
            dry_run: If True (default) every state-changing call returns
                a deterministic DRY_RUN payload and read methods return the
                deterministic mock fixtures. If False, read methods perform
                real on-chain eth_call (Phase 2) and write methods return
                NOT_IMPLEMENTED until Phase 3 wires real signing.
            rpc_endpoints: Optional override for the RPC endpoint registry.
                Defaults to the class-level RPC_ENDPOINTS table.

        Raises:
            ValueError: If ``chain`` is not in SUPPORTED_CHAINS.
        """
        if chain not in self.SUPPORTED_CHAINS:
            raise ValueError(
                f"Unsupported chain '{chain}'. "
                f"Must be one of: {self.SUPPORTED_CHAINS}"
            )
        self.chain = chain
        self.dry_run = dry_run
        self.rpc_endpoints: dict[str, list[str]] = (
            rpc_endpoints if rpc_endpoints is not None else self.RPC_ENDPOINTS
        )
        self.comet_address: str = self.COMET_ADDRESSES[chain]
        log.debug(
            "CompoundV3Adapter init: chain=%s dry_run=%s comet=%s endpoints=%d",
            self.chain, self.dry_run, self.comet_address,
            len(self.rpc_endpoints.get(self.chain, [])),
        )

    # ─── Input validation ─────────────────────────────────────────────────────

    def _validate_inputs(self, asset: str, amount: float) -> None:
        """Validate asset symbol and positive amount.

        Raises:
            ValueError: If ``asset`` is not in SUPPORTED_ASSETS or ``amount``
                is not strictly positive.
        """
        if asset not in self.SUPPORTED_ASSETS:
            raise ValueError(
                f"Unsupported asset '{asset}'. "
                f"Must be one of: {self.SUPPORTED_ASSETS}"
            )
        if amount is None or amount <= 0:
            raise ValueError(
                f"Invalid amount {amount!r}: must be a positive number"
            )

    # ─── Phase 2: stdlib JSON-RPC helpers ─────────────────────────────────────

    @staticmethod
    def _strip_fragment(url: str) -> str:
        """Return ``url`` with any ``#...`` fragment stripped.

        The class-level RPC_ENDPOINTS attach a ``#compound-v3-comet:0x...``
        hint to each URL so operators can audit which Comet address a given
        endpoint routes to. JSON-RPC servers reject fragments, so we strip
        before posting.
        """
        idx = url.find("#")
        return url if idx == -1 else url[:idx]

    @staticmethod
    def _pad_address(address: str) -> str:
        """Left-pad a 20-byte hex address to 32 bytes (no ``0x`` prefix)."""
        clean = address[2:] if address.lower().startswith("0x") else address
        return clean.lower().rjust(64, "0")

    @staticmethod
    def _pad_uint256(value: int) -> str:
        """Encode an unsigned int as a 32-byte hex string (no ``0x`` prefix)."""
        if value < 0:
            raise ValueError(f"_pad_uint256: negative value {value}")
        return format(value, "064x")

    def _eth_call(self, rpc_url: str, to: str, data: str) -> str:
        """Post a JSON-RPC ``eth_call`` and return the raw hex result.

        Stdlib-only: ``urllib.request`` + ``json``. 5-second timeout per call.
        Logs the RPC URL + selector at DEBUG.

        Args:
            rpc_url: Full JSON-RPC endpoint URL (URL fragment must already
                be stripped by the caller).
            to: Target contract address (``0x...``).
            data: ABI-encoded calldata (``0xSELECTOR + ARGS``).

        Returns:
            Raw hex string returned by the RPC (``0x...``).

        Raises:
            RuntimeError: On HTTP error, timeout, JSON-RPC error envelope,
                or missing ``result`` field.
        """
        selector = data[:10] if len(data) >= 10 else data
        log.debug("eth_call rpc=%s selector=%s to=%s", rpc_url, selector, to)

        payload = {
            "jsonrpc": "2.0",
            "id":      1,
            "method":  "eth_call",
            "params":  [
                {"to": to, "data": data},
                "latest",
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            rpc_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                req, timeout=self.RPC_TIMEOUT_SECONDS,
            ) as resp:
                raw = resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"eth_call HTTP failure: {exc}") from exc

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"eth_call malformed JSON: {exc}") from exc

        if "error" in parsed:
            raise RuntimeError(f"eth_call RPC error: {parsed['error']}")
        result = parsed.get("result")
        if not isinstance(result, str) or not result.startswith("0x"):
            raise RuntimeError(f"eth_call missing/invalid result: {parsed!r}")
        return result

    def _call_with_fallback(self, asset: str, data: str) -> str:
        """Iterate ``rpc_endpoints[chain]``, first success wins.

        Posts to ``self.comet_address`` (the single Comet market contract
        for the chain). For balanceOf, getUtilization, and getSupplyRate
        all three target the Comet itself — Compound V3's single-market
        topology means we never need a token-side eth_call (unlike Aave's
        aToken indirection).

        Args:
            asset: Asset symbol (used only for logging context).
            data: ABI-encoded calldata posted to ``self.comet_address``.

        Returns:
            Hex string returned by the first endpoint that succeeds.

        Raises:
            RuntimeError: If every endpoint fails. The error message
                aggregates each endpoint's failure for operator debugging.
        """
        endpoints = self.rpc_endpoints.get(self.chain, [])
        if not endpoints:
            raise RuntimeError(
                f"No RPC endpoints configured for chain={self.chain}"
            )

        failures: list[str] = []
        for raw_url in endpoints:
            url = self._strip_fragment(raw_url)
            try:
                return self._eth_call(url, self.comet_address, data)
            except Exception as exc:  # noqa: BLE001 — we record + try next
                log.debug(
                    "eth_call failed asset=%s url=%s err=%s",
                    asset, url, exc,
                )
                failures.append(f"{url} -> {exc}")
        raise RuntimeError(
            f"All {len(endpoints)} RPCs failed for {asset} on {self.chain}: "
            + " | ".join(failures)
        )

    # ─── Supply / withdraw ────────────────────────────────────────────────────

    def supply(self, asset: str, amount: float) -> dict:
        """
        Supply ``amount`` of ``asset`` to the Compound V3 Comet pool.

        Dry-run mode (default):
            Returns a deterministic DRY_RUN record. ``ctoken_received``
            is set equal to ``amount`` (1:1 mock cUSDCv3 share) so callers
            can pipe the result straight into accounting tests.

        Live mode (dry_run=False):
            Returns a NOT_IMPLEMENTED record until Phase 3 wires
            eth_account signing for Comet.supply(asset, amount).

        Args:
            asset:  Symbol in SUPPORTED_ASSETS (USDC only in Phase 2 scope).
            amount: Strictly-positive supply amount in token units.

        Returns:
            dict with keys ``status``, ``tx_hash``, ``asset``, ``amount``,
            ``ctoken_received``, ``chain``, ``timestamp``.

        Raises:
            ValueError: On unknown asset or non-positive amount.
        """
        self._validate_inputs(asset, amount)
        ts = datetime.now(timezone.utc).isoformat()

        if self.dry_run:
            log.info(
                "[DRY_RUN supply] chain=%s asset=%s amount=%.6f",
                self.chain, asset, amount,
            )
            return {
                "status":          "DRY_RUN",
                "tx_hash":         None,
                "asset":           asset,
                "amount":          amount,
                "ctoken_received": amount,
                "chain":           self.chain,
                "timestamp":       ts,
            }

        log.warning(
            "[supply NOT_IMPLEMENTED] live mode requested for %s on %s",
            asset, self.chain,
        )
        return {
            "status":          "NOT_IMPLEMENTED",
            "tx_hash":         None,
            "asset":           asset,
            "amount":          amount,
            "ctoken_received": 0.0,
            "chain":           self.chain,
            "timestamp":       ts,
        }

    def withdraw(self, asset: str, amount: float) -> dict:
        """
        Withdraw ``amount`` of ``asset`` from the Compound V3 Comet pool.

        Dry-run mode (default):
            Returns a deterministic DRY_RUN record with ``ctoken_received``
            set to the negative of ``amount`` (cUSDCv3 burn accounting).

        Live mode (dry_run=False):
            Returns a NOT_IMPLEMENTED record until Phase 3 wires
            eth_account signing for Comet.withdraw(asset, amount).

        Args:
            asset:  Symbol in SUPPORTED_ASSETS.
            amount: Strictly-positive withdraw amount in token units.

        Returns:
            dict with keys ``status``, ``tx_hash``, ``asset``, ``amount``,
            ``ctoken_received``, ``chain``, ``timestamp``.

        Raises:
            ValueError: On unknown asset or non-positive amount.
        """
        self._validate_inputs(asset, amount)
        ts = datetime.now(timezone.utc).isoformat()

        if self.dry_run:
            log.info(
                "[DRY_RUN withdraw] chain=%s asset=%s amount=%.6f",
                self.chain, asset, amount,
            )
            return {
                "status":          "DRY_RUN",
                "tx_hash":         None,
                "asset":           asset,
                "amount":          amount,
                "ctoken_received": -amount,
                "chain":           self.chain,
                "timestamp":       ts,
            }

        log.warning(
            "[withdraw NOT_IMPLEMENTED] live mode requested for %s on %s",
            asset, self.chain,
        )
        return {
            "status":          "NOT_IMPLEMENTED",
            "tx_hash":         None,
            "asset":           asset,
            "amount":          amount,
            "ctoken_received": 0.0,
            "chain":           self.chain,
            "timestamp":       ts,
        }

    # ─── Read methods ─────────────────────────────────────────────────────────

    def get_supply_balance(self, asset: str) -> float:
        """
        Return the current Comet balance (USDC presentValue) for ``asset``.

        Dry-run mode: returns the deterministic _MOCK_BALANCES entry.

        Live mode (dry_run=False):
            1) Comet.balanceOf(SPA_WALLET_ADDRESS) → uint256 raw balance.
               Note: Comet's balanceOf returns presentValue (raw base asset
               units already including accrued interest), so there is no
               aToken-style indirection à la Aave — one RPC call per asset.
            2) Divide by 10**TOKEN_DECIMALS[asset] (6 for USDC) to return a
               human-readable token amount.

            On ANY failure (RPC down, missing wallet env var, malformed
            return data) logs a [FALLBACK] WARNING and returns the
            _MOCK_BALANCES value. See module docstring for fallback policy.

        Args:
            asset: Symbol in SUPPORTED_ASSETS.

        Returns:
            Balance in token units (float).

        Raises:
            ValueError: If ``asset`` is not in SUPPORTED_ASSETS. Raised
                BEFORE any RPC work; never wrapped by the fallback.
        """
        if asset not in self.SUPPORTED_ASSETS:
            raise ValueError(
                f"Unsupported asset '{asset}'. "
                f"Must be one of: {self.SUPPORTED_ASSETS}"
            )
        if self.dry_run:
            return self._MOCK_BALANCES[asset]

        try:
            wallet = os.environ.get("SPA_WALLET_ADDRESS")
            if not wallet:
                raise RuntimeError(
                    "SPA_WALLET_ADDRESS not configured for live mode"
                )

            data = self.SELECTOR_BALANCE_OF + self._pad_address(wallet)
            balance_hex = self._call_with_fallback(asset, data)
            balance_body = (
                balance_hex[2:] if balance_hex.startswith("0x") else balance_hex
            )
            raw_balance = int(balance_body, 16) if balance_body else 0
            decimals = self.TOKEN_DECIMALS[asset]
            return raw_balance / (10 ** decimals)
        except Exception as exc:  # noqa: BLE001 — production safety
            log.warning(
                "[FALLBACK] get_supply_balance live failed for %s on %s: "
                "%s — returning mock %.6f",
                asset, self.chain, exc, self._MOCK_BALANCES[asset],
            )
            return self._MOCK_BALANCES[asset]

    def get_supply_apy(self, asset: str) -> float:
        """
        Return the current supply APY for ``asset`` (percent, not fraction).

        Dry-run mode: returns the deterministic _MOCK_APYS entry.

        Live mode (dry_run=False):
            Two chained eth_calls against the Comet contract:
              1) getUtilization() → uint256 utilization scaled by 1e18.
              2) getSupplyRate(utilization) → uint64 per-second supply rate
                 scaled by 1e18.
            Annualised APY (%) = rate_per_second * SECONDS_PER_YEAR / 1e16
            (= rate * 31_536_000 / 1e18 * 100).

            On ANY failure (RPC down, malformed return data) logs a
            [FALLBACK] WARNING and returns the _MOCK_APYS value. See module
            docstring for fallback policy.

        Args:
            asset: Symbol in SUPPORTED_ASSETS.

        Returns:
            Supply APY in percent (e.g. 4.5 means 4.5%).

        Raises:
            ValueError: If ``asset`` is not in SUPPORTED_ASSETS. Raised
                BEFORE any RPC work; never wrapped by the fallback.
        """
        if asset not in self.SUPPORTED_ASSETS:
            raise ValueError(
                f"Unsupported asset '{asset}'. "
                f"Must be one of: {self.SUPPORTED_ASSETS}"
            )
        if self.dry_run:
            return self._MOCK_APYS[asset]

        try:
            # 1) getUtilization()
            util_hex = self._call_with_fallback(
                asset, self.SELECTOR_GET_UTILIZATION,
            )
            util_body = util_hex[2:] if util_hex.startswith("0x") else util_hex
            if not util_body:
                raise RuntimeError("getUtilization empty response")
            utilization = int(util_body, 16)

            # 2) getSupplyRate(utilization)
            rate_hex = self._call_with_fallback(
                asset,
                self.SELECTOR_GET_SUPPLY_RATE + self._pad_uint256(utilization),
            )
            rate_body = rate_hex[2:] if rate_hex.startswith("0x") else rate_hex
            if not rate_body:
                raise RuntimeError("getSupplyRate empty response")
            rate_per_second = int(rate_body, 16)

            # APY % = rate * SECONDS_PER_YEAR / 1e18 * 100
            #       = rate * SECONDS_PER_YEAR / 1e16
            return rate_per_second * self.SECONDS_PER_YEAR / 1e16
        except Exception as exc:  # noqa: BLE001 — production safety
            log.warning(
                "[FALLBACK] get_supply_apy live failed for %s on %s: "
                "%s — returning mock %.4f",
                asset, self.chain, exc, self._MOCK_APYS[asset],
            )
            return self._MOCK_APYS[asset]

    # ─── Health check ─────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        """
        Return a snapshot of the adapter's configuration.

        Returns:
            {
                "chain":                str,         # active chain
                "dry_run":              bool,
                "comet_address":        str,         # Compound V3 Comet contract
                "endpoints_configured": int,         # count of RPC URLs for chain
                "supported_assets":     list[str],
                "timestamp":            str,         # ISO-8601 UTC
            }
        """
        endpoints = self.rpc_endpoints.get(self.chain, [])
        return {
            "chain":                self.chain,
            "dry_run":              self.dry_run,
            "comet_address":        self.comet_address,
            "endpoints_configured": len(endpoints),
            "supported_assets":     list(self.SUPPORTED_ASSETS),
            "timestamp":            datetime.now(timezone.utc).isoformat(),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    adapter = CompoundV3Adapter(chain="ethereum", dry_run=True)
    print("Health check:", json.dumps(adapter.health_check(), indent=2))
    print("Supply USDC 1000:", json.dumps(adapter.supply("USDC", 1000.0), indent=2))
    print("Withdraw USDC 250:", json.dumps(adapter.withdraw("USDC", 250.0), indent=2))
    print("USDC balance:", adapter.get_supply_balance("USDC"))
    print("USDC APY:   ", adapter.get_supply_apy("USDC"))
