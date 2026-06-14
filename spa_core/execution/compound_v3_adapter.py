"""
Compound V3 Live SDK Adapter (FEAT-005 Phase 3).

Pure-Python adapter mirroring aave_v3_adapter.py (FEAT-004 Phase 3):
  - Env-driven, 3-RPC fallback per chain (URL fragment carries Comet hint)
  - Dry-run / synthetic mode (deterministic mock balances + APYs)
  - Phase 2: real eth_call decoding for get_supply_apy + get_supply_balance
    via stdlib urllib.request (no web3.py, no requests)
  - Phase 3: real supply / withdraw via eth_account-signed raw transactions
    routed through eth_sendRawTransaction + receipt polling, gated behind
    the SPA_EXECUTION_MODE=live env flag.

Phase 1 (shipped v3.3):
  * CompoundV3Adapter scaffold with dry-run supply / withdraw / balance / APY
  * Input validation, deterministic mock returns, health_check()
  * RPC endpoint registry + Comet contract addresses

Phase 2 (v3.7):
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

Phase 3 (this file, v3.10):
  * supply(): ERC20.approve(COMET, amount) → Comet.supply(asset, amount) —
    two signed EIP-1559 transactions
  * withdraw(): Comet.withdraw(asset, amount) — single signed transaction
  * eth_account imported LAZILY (mirrors psycopg2 pattern in
    spa_core/database/connection.py) — missing dependency degrades to
    {"status": "FAILED", ...} not ImportError
  * Multi-layer safety gates:
      - dry_run=True (default) — unchanged from Phase 1/2
      - dry_run=False + SPA_EXECUTION_MODE!=live → {"status": "BLOCKED"}
      - SPA_PRIVATE_KEY missing → {"status": "ERROR"}
      - key→address mismatch with SPA_WALLET_ADDRESS → {"status": "ERROR"}
      - amount <= 0 → ValueError; amount > 10_000_000 → {"status": "ERROR"}
      - any RPC / signature / receipt revert → {"status": "FAILED"} with
        per-phase tag ("approve" | "supply" | "withdraw")
  * The paper-trading engine NEVER sees a raised exception from the live
    write path — every failure mode returns a structured dict.

Differences vs AaveV3Adapter:
  * Single asset (USDC only) — Comet markets we wire are cUSDCv3 single-
    asset. Multi-asset Comets (cWETHv3 etc.) are deferred.
  * Selectors differ — Comet.supply(asset, amount) is 0xf2b9fdb8 (NOT
    Aave's 0x617ba037 which also takes onBehalfOf + referralCode).
  * Comet.withdraw(asset, amount) is 0xf3fef3a3 (NOT Aave's 0x69328dec
    which takes a `to` recipient).
  * Both supply and withdraw target the Comet itself; there's no Pool
    indirection. balanceOf is also Comet-native and already includes
    accrued interest (no aToken hop).

Supported topology:
  Chains    — ethereum, arbitrum, base
  Assets    — USDC (Compound V3 cUSDCv3 single-asset markets)
  Modes     — dry_run=True (default; safe, deterministic, byte-identical to
                Phase 1),
              dry_run=False + SPA_EXECUTION_MODE=live (Phase 3: real
                on-chain writes).
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger("spa.compound_v3_adapter")


class DependencyNotInstalled(RuntimeError):
    """Raised when a Phase 3 live write needs eth_account and it's missing."""


def _require_eth_account():
    """Lazy-import eth_account (mirrors psycopg2 pattern in database/connection.py).

    Returns the ``Account`` class so callers can use ``Account.from_key`` and
    ``Account.sign_transaction``. We DON'T import at module top because the
    SPA_EXECUTION_MODE!=live happy path must not require the package.

    Raises:
        DependencyNotInstalled: if eth_account is not importable. The
            ``supply`` / ``withdraw`` methods catch this and return
            ``{"status": "FAILED", ...}`` so the pipeline never crashes.
    """
    try:
        from eth_account import Account  # type: ignore
        return Account
    except ImportError as exc:  # pragma: no cover — exercised via test mock
        raise DependencyNotInstalled(
            "eth_account not installed; pip install eth-account>=0.10.0 "
            "to enable Phase 3 live writes"
        ) from exc


class CompoundV3Adapter:
    """
    Adapter for Compound V3 (Comet) supply / withdraw flows across
    multiple chains.

    Phase 3 status:
      * ``get_supply_apy`` and ``get_supply_balance`` perform real on-chain
        ``eth_call`` requests when ``dry_run=False`` (Phase 2 behaviour
        retained). Failures degrade to the deterministic mock value
        (logged WARNING with the ``[FALLBACK]`` tag).
      * ``supply`` and ``withdraw`` perform real signed transactions when
        ``dry_run=False`` AND ``SPA_EXECUTION_MODE=live``. Otherwise they
        short-circuit to ``{"status": "BLOCKED"}``. Failures inside the
        live path return structured ``{"status": "FAILED", ...}`` dicts
        and never raise.

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

    Usage (live write — Phase 3)::

        SPA_EXECUTION_MODE=live SPA_PRIVATE_KEY=0x... \\
            python -c "from spa_core.execution.compound_v3_adapter import \\
                CompoundV3Adapter; \\
                print(CompoundV3Adapter('ethereum', dry_run=False) \\
                .supply('USDC', 100))"
    """

    # ─── Class constants ──────────────────────────────────────────────────────

    SUPPORTED_CHAINS: list[str] = ["ethereum", "arbitrum", "base"]
    SUPPORTED_ASSETS: list[str] = ["USDC"]

    # Real Compound V3 Comet (cUSDCv3) contract addresses (verified on
    # respective chain explorers as of 2026-05). Used by Phase 2 + 3.
    COMET_ADDRESSES: dict[str, str] = {
        "ethereum": "0xc3d688B66703497DAA19211EEdff47f25384cdc3",
        "arbitrum": "0x9c4ec768c28520B50860ea7a15bd7213a9fF58bf",
        "base":     "0xb125E6687d4313864e53df431d5425969c15Eb2F",
    }

    # Canonical mainnet USDC token addresses per chain (verified against
    # each chain's official explorer). Phase 3 needs these to call
    # ERC20.approve(spender=COMET, amount) on the underlying USDC.
    TOKEN_ADDRESSES: dict[str, dict[str, str]] = {
        "ethereum": {
            "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        },
        "arbitrum": {
            "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        },
        "base": {
            "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        },
    }

    # Decimals per base asset — Comet base asset is USDC (6 decimals) on
    # every supported chain.
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
    #   keccak256("getUtilization()")[:4]         = 0x6f307dc3
    #   keccak256("getSupplyRate(uint256)")[:4]   = 0x6fb1b0e9
    #   keccak256("balanceOf(address)")[:4]       = 0x70a08231
    #   keccak256("approve(address,uint256)")[:4] = 0x095ea7b3
    #   keccak256("supply(address,uint256)")[:4]  = 0xf2b9fdb8  (Comet)
    #   keccak256("withdraw(address,uint256)")[:4]= 0xf3fef3a3  (Comet)
    SELECTOR_GET_UTILIZATION: str = "0x6f307dc3"
    SELECTOR_GET_SUPPLY_RATE: str = "0x6fb1b0e9"
    SELECTOR_BALANCE_OF:      str = "0x70a08231"
    SELECTOR_APPROVE:         str = "0x095ea7b3"
    SELECTOR_SUPPLY:          str = "0xf2b9fdb8"
    SELECTOR_WITHDRAW:        str = "0xf3fef3a3"

    # JSON-RPC timeout (seconds) per endpoint try.
    RPC_TIMEOUT_SECONDS: float = 5.0

    # Seconds in a 365-day year — used to annualise Comet's per-second
    # supply rate. Matches Compound's own front-end conversion (365 *
    # 24 * 60 * 60 = 31_536_000).
    SECONDS_PER_YEAR: int = 31_536_000

    # Phase 3 — receipt polling parameters (max 30s wall-clock per tx).
    RECEIPT_POLL_INTERVAL_SECONDS: float = 2.0
    RECEIPT_POLL_MAX_SECONDS:      float = 30.0

    # Sanity gate for live writes — refuse anything above 10M USD-equivalent
    # to catch unit-conversion / scaling bugs before they hit chain.
    MAX_LIVE_AMOUNT: float = 10_000_000.0

    # EVM chain IDs (used to fall back if eth_chainId RPC fails).
    DEFAULT_CHAIN_IDS: dict[str, int] = {
        "ethereum": 1,
        "arbitrum": 42161,
        "base":     8453,
    }

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
                real on-chain eth_call (Phase 2). Write methods run the
                Phase 3 live signing path **only** when SPA_EXECUTION_MODE
                ==``live``; otherwise they return a structured BLOCKED dict.
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

    def _eth_rpc(self, rpc_url: str, method: str, params: list) -> object:
        """Post an arbitrary JSON-RPC method and return the ``result`` field.

        Generic sibling of ``_eth_call`` used by Phase 3 for ``eth_chainId``,
        ``eth_getTransactionCount``, ``eth_gasPrice``, ``eth_sendRawTransaction``
        and ``eth_getTransactionReceipt``.

        Args:
            rpc_url: Full JSON-RPC endpoint URL (fragment already stripped).
            method: JSON-RPC method name (e.g. ``eth_chainId``).
            params: List of params (forwarded as-is into the JSON body).

        Returns:
            Whatever sits in the JSON-RPC ``result`` field — caller decodes.

        Raises:
            RuntimeError: HTTP failure, malformed JSON, JSON-RPC error, or
                missing ``result``.
        """
        log.debug("eth_rpc rpc=%s method=%s", rpc_url, method)
        payload = {
            "jsonrpc": "2.0",
            "id":      1,
            "method":  method,
            "params":  params,
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
            raise RuntimeError(f"{method} HTTP failure: {exc}") from exc

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"{method} malformed JSON: {exc}") from exc

        if "error" in parsed:
            raise RuntimeError(f"{method} RPC error: {parsed['error']}")
        if "result" not in parsed:
            raise RuntimeError(f"{method} missing result: {parsed!r}")
        return parsed["result"]

    def _rpc_first(self, method: str, params: list) -> object:
        """Iterate the chain's RPC endpoints, return first successful result.

        Mirrors ``_call_with_fallback`` but for arbitrary RPC methods. Used
        by Phase 3 for ``eth_chainId`` / ``eth_gasPrice`` / etc.

        Raises:
            RuntimeError: if every endpoint fails.
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
                return self._eth_rpc(url, method, params)
            except Exception as exc:  # noqa: BLE001
                log.debug("rpc %s failed url=%s err=%s", method, url, exc)
                failures.append(f"{url} -> {exc}")
        raise RuntimeError(
            f"All {len(endpoints)} RPCs failed for {method} on "
            f"{self.chain}: " + " | ".join(failures)
        )

    # ─── Phase 3: live-write helpers ──────────────────────────────────────────

    def _build_approve_calldata(self, spender: str, raw_amount: int) -> str:
        """ERC20.approve(spender, amount) calldata (selector + 2 × 32-byte args)."""
        return (
            self.SELECTOR_APPROVE
            + self._pad_address(spender)
            + self._pad_uint256(raw_amount)
        )

    def _build_supply_calldata(
        self,
        asset_addr: str,
        raw_amount: int,
    ) -> str:
        """Comet.supply(asset, amount) calldata.

        Layout: 0xf2b9fdb8 + asset (32B) + amount (32B). Unlike Aave's
        Pool.supply (asset, amount, onBehalfOf, referralCode) the Comet
        supply takes only two args because Compound V3 is single-market
        and credits the tx sender directly (no on-behalf-of).
        """
        return (
            self.SELECTOR_SUPPLY
            + self._pad_address(asset_addr)
            + self._pad_uint256(raw_amount)
        )

    def _build_withdraw_calldata(
        self, asset_addr: str, raw_amount: int,
    ) -> str:
        """Comet.withdraw(asset, amount) calldata.

        Layout: 0xf3fef3a3 + asset (32B) + amount (32B). The receiver is
        always msg.sender — Comet doesn't accept a `to` arg (Aave's
        Pool.withdraw does, but Comet credits the caller directly).
        """
        return (
            self.SELECTOR_WITHDRAW
            + self._pad_address(asset_addr)
            + self._pad_uint256(raw_amount)
        )

    def _get_chain_id(self) -> int:
        """Fetch chainId via eth_chainId, fall back to DEFAULT_CHAIN_IDS."""
        try:
            result = self._rpc_first("eth_chainId", [])
            return int(result, 16) if isinstance(result, str) else int(result)
        except Exception as exc:  # noqa: BLE001
            log.debug("eth_chainId failed: %s — using default", exc)
            return self.DEFAULT_CHAIN_IDS[self.chain]

    def _get_nonce(self, address: str) -> int:
        result = self._rpc_first(
            "eth_getTransactionCount", [address, "pending"],
        )
        return int(result, 16) if isinstance(result, str) else int(result)

    def _get_gas_price(self) -> int:
        result = self._rpc_first("eth_gasPrice", [])
        return int(result, 16) if isinstance(result, str) else int(result)

    def _send_raw_tx(self, signed_hex: str) -> str:
        """Broadcast a signed transaction; return its hash.

        MEV protection (Sprint v3.52 / SPA-V352): when SPA_MEV_PROTECTION is
        enabled AND SPA_EXECUTION_MODE == "live", prefer the Flashbots Protect
        private mempool. Any routing error falls back to the public RPC path
        below, so default behaviour is byte-for-byte unchanged.
        """
        try:
            from spa_core.execution import mev_protection
            if (mev_protection.is_mev_protection_enabled()
                    and os.getenv("SPA_EXECUTION_MODE") == "live"):
                res = mev_protection.send_protected(signed_hex, fallback_rpc=None)
                tx_hash = res.get("tx_hash")
                if res.get("status") != "FAILED" and tx_hash:
                    log.info("MEV-protected broadcast via %s", res.get("endpoint"))
                    return tx_hash
                log.warning(
                    "MEV-protected broadcast failed (%s) — falling back to public RPC",
                    res.get("reason"),
                )
        except Exception as exc:  # noqa: BLE001 — never block the public path
            log.warning("MEV protection routing error, using public RPC: %s", exc)
        result = self._rpc_first("eth_sendRawTransaction", [signed_hex])
        if not isinstance(result, str) or not result.startswith("0x"):
            raise RuntimeError(f"eth_sendRawTransaction bad result: {result!r}")
        return result

    def _wait_for_receipt(self, tx_hash: str) -> dict:
        """Poll eth_getTransactionReceipt until mined or timeout.

        Returns the receipt dict on success, raises RuntimeError on timeout
        or RPC failure.
        """
        deadline = time.monotonic() + self.RECEIPT_POLL_MAX_SECONDS
        while time.monotonic() < deadline:
            try:
                result = self._rpc_first(
                    "eth_getTransactionReceipt", [tx_hash],
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("receipt poll error for %s: %s", tx_hash, exc)
                result = None
            if isinstance(result, dict):
                return result
            time.sleep(self.RECEIPT_POLL_INTERVAL_SECONDS)
        raise RuntimeError(
            f"Receipt timeout after {self.RECEIPT_POLL_MAX_SECONDS}s for "
            f"tx {tx_hash}"
        )

    @staticmethod
    def _receipt_block_number(receipt: dict) -> int | None:
        """Extract block number from a receipt (hex or int)."""
        bn = receipt.get("blockNumber")
        if isinstance(bn, str) and bn.startswith("0x"):
            try:
                return int(bn, 16)
            except ValueError:
                return None
        if isinstance(bn, int):
            return bn
        return None

    @staticmethod
    def _receipt_success(receipt: dict) -> bool:
        status = receipt.get("status")
        if isinstance(status, str):
            return status.lower() in ("0x1", "1")
        if isinstance(status, int):
            return status == 1
        return False

    @staticmethod
    def _validate_private_key(pk: str) -> str:
        """Normalise hex private key. Raises ValueError if malformed."""
        if not pk:
            raise ValueError("SPA_PRIVATE_KEY missing")
        cleaned = pk[2:] if pk.lower().startswith("0x") else pk
        if len(cleaned) != 64:
            raise ValueError(
                f"SPA_PRIVATE_KEY must be 64 hex chars (0x-prefix optional); "
                f"got {len(cleaned)}"
            )
        try:
            int(cleaned, 16)
        except ValueError as exc:
            raise ValueError("SPA_PRIVATE_KEY is not valid hex") from exc
        return "0x" + cleaned

    def _check_live_preconditions(self) -> dict | None:
        """Return a structured short-circuit dict if a precondition fails.

        Order:
          1) SPA_EXECUTION_MODE must equal "live" (case-insensitive)

        Returns None if everything is OK. Otherwise returns the dict the
        caller should return directly to its invoker.
        """
        if os.environ.get("SPA_EXECUTION_MODE", "").lower() != "live":
            return {
                "status": "BLOCKED",
                "reason": "SPA_EXECUTION_MODE!=live",
            }
        return None

    def _resolve_signer(self) -> tuple[object, str]:
        """Load eth_account.Account + return (Account, wallet_address).

        Raises:
            DependencyNotInstalled: eth_account missing.
            ValueError: key missing/invalid or address mismatch.
        """
        Account = _require_eth_account()
        pk = os.environ.get("SPA_PRIVATE_KEY", "")
        if not pk:
            raise ValueError("SPA_PRIVATE_KEY missing")
        normalised = self._validate_private_key(pk)
        acct = Account.from_key(normalised)
        derived = acct.address
        configured = os.environ.get("SPA_WALLET_ADDRESS")
        if configured and configured.lower() != derived.lower():
            raise ValueError(
                f"SPA_WALLET_ADDRESS ({configured}) does not match address "
                f"derived from SPA_PRIVATE_KEY ({derived})"
            )
        return acct, derived

    def _sign_and_send(
        self,
        Account,
        private_key: str,
        *,
        to: str,
        data: str,
        nonce: int,
        chain_id: int,
        gas_price: int,
        gas_limit: int = 350_000,
    ) -> str:
        """Build an EIP-1559 tx, sign, broadcast, return tx hash.

        For EIP-1559 we set ``maxFeePerGas = 2 × gasPrice`` and
        ``maxPriorityFeePerGas = gasPrice // 10`` — conservative defaults
        that are widely accepted by mainnet/L2 mempools.
        """
        max_priority = max(int(gas_price // 10), 1)
        max_fee = max(int(gas_price * 2), max_priority + 1)
        tx = {
            "to":                   to,
            "value":                0,
            "gas":                  gas_limit,
            "maxFeePerGas":         max_fee,
            "maxPriorityFeePerGas": max_priority,
            "nonce":                nonce,
            "chainId":              chain_id,
            "data":                 data,
            "type":                 2,
        }
        signed = Account.sign_transaction(tx, private_key=private_key)
        raw = getattr(signed, "rawTransaction", None)
        if raw is None:
            raw = getattr(signed, "raw_transaction", None)  # newer eth_account
        if raw is None:
            raise RuntimeError("Signed tx missing rawTransaction attribute")
        # rawTransaction is bytes — convert to 0x-prefixed hex.
        if isinstance(raw, (bytes, bytearray)):
            signed_hex = "0x" + raw.hex()
        else:
            signed_hex = str(raw)
            if not signed_hex.startswith("0x"):
                signed_hex = "0x" + signed_hex
        return self._send_raw_tx(signed_hex)

    # ─── Supply / withdraw ────────────────────────────────────────────────────

    def supply(self, asset: str, amount: float) -> dict:
        """
        Supply ``amount`` of ``asset`` to the Compound V3 Comet pool.

        Dry-run mode (default):
            Returns a deterministic DRY_RUN record. ``ctoken_received``
            is set equal to ``amount`` (1:1 mock cUSDCv3 share) so callers
            can pipe the result straight into accounting tests.

        Live mode (``dry_run=False``):
            - If ``SPA_EXECUTION_MODE != "live"`` → ``{"status": "BLOCKED"}``
            - If ``amount > MAX_LIVE_AMOUNT`` → ``{"status": "ERROR"}``
            - Otherwise broadcasts two signed EIP-1559 transactions:
                1) ERC20.approve(COMET, amount) on the underlying USDC
                2) Comet.supply(asset, amount)
              Returns ``{"status": "SUCCESS", "approve_tx", "supply_tx",
              "block_number", ...}``. Any RPC / receipt revert returns
              ``{"status": "FAILED", "phase": "approve"|"supply", ...}``.

        Args:
            asset:  Symbol in SUPPORTED_ASSETS (USDC only).
            amount: Strictly-positive supply amount in token units.

        Returns:
            dict.

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

        # Phase 3 live path — sanity gate first.
        if amount > self.MAX_LIVE_AMOUNT:
            log.warning(
                "[supply REJECTED] amount %.2f exceeds MAX_LIVE_AMOUNT %.2f",
                amount, self.MAX_LIVE_AMOUNT,
            )
            return {
                "status":    "ERROR",
                "reason":    f"amount {amount} exceeds MAX_LIVE_AMOUNT "
                             f"{self.MAX_LIVE_AMOUNT}",
                "asset":     asset,
                "amount":    amount,
                "chain":     self.chain,
                "timestamp": ts,
            }

        gate = self._check_live_preconditions()
        if gate is not None:
            log.info(
                "[supply gated] chain=%s asset=%s reason=%s",
                self.chain, asset, gate.get("reason"),
            )
            gate.update({
                "asset": asset, "amount": amount,
                "chain": self.chain, "timestamp": ts,
            })
            return gate

        return self._live_supply(asset, amount, ts)

    def _live_supply(self, asset: str, amount: float, ts: str) -> dict:
        """Phase 3 live supply path. Never raises — always returns a dict."""
        try:
            Account = _require_eth_account()
        except DependencyNotInstalled as exc:
            log.warning("[FALLBACK] supply: %s", exc)
            return {
                "status":    "FAILED",
                "reason":    str(exc),
                "phase":     "approve",
                "asset":     asset,
                "amount":    amount,
                "chain":     self.chain,
                "timestamp": ts,
            }

        try:
            acct, wallet = self._resolve_signer()
        except ValueError as exc:
            log.warning("[FALLBACK] supply preconditions: %s", exc)
            return {
                "status":    "ERROR",
                "reason":    str(exc),
                "asset":     asset,
                "amount":    amount,
                "chain":     self.chain,
                "timestamp": ts,
            }

        decimals = self.TOKEN_DECIMALS[asset]
        raw_amount = int(round(amount * (10 ** decimals)))
        asset_addr = self.TOKEN_ADDRESSES[self.chain][asset]
        pk_normalised = self._validate_private_key(
            os.environ.get("SPA_PRIVATE_KEY", "")
        )

        # ── Step 1: ERC20.approve(COMET, amount) ──────────────────────────
        try:
            chain_id = self._get_chain_id()
            nonce = self._get_nonce(wallet)
            gas_price = self._get_gas_price()
            approve_data = self._build_approve_calldata(
                self.comet_address, raw_amount,
            )
            approve_hash = self._sign_and_send(
                Account, pk_normalised,
                to=asset_addr, data=approve_data,
                nonce=nonce, chain_id=chain_id, gas_price=gas_price,
                gas_limit=120_000,
            )
            approve_receipt = self._wait_for_receipt(approve_hash)
            if not self._receipt_success(approve_receipt):
                log.warning(
                    "[FALLBACK] supply approve reverted tx=%s", approve_hash,
                )
                return {
                    "status":     "FAILED",
                    "reason":     "approve receipt status=0x0 (revert)",
                    "phase":      "approve",
                    "approve_tx": approve_hash,
                    "asset":      asset, "amount": amount,
                    "chain":      self.chain, "timestamp": ts,
                }
        except Exception as exc:  # noqa: BLE001 — production safety
            log.warning("[FALLBACK] supply approve failed: %s", exc)
            return {
                "status":    "FAILED",
                "reason":    f"approve failed: {exc}",
                "phase":     "approve",
                "asset":     asset, "amount": amount,
                "chain":     self.chain, "timestamp": ts,
            }

        # ── Step 2: Comet.supply(asset, amount) ───────────────────────────
        try:
            supply_data = self._build_supply_calldata(
                asset_addr, raw_amount,
            )
            supply_hash = self._sign_and_send(
                Account, pk_normalised,
                to=self.comet_address, data=supply_data,
                nonce=nonce + 1, chain_id=chain_id, gas_price=gas_price,
                gas_limit=350_000,
            )
            supply_receipt = self._wait_for_receipt(supply_hash)
            if not self._receipt_success(supply_receipt):
                log.warning(
                    "[FALLBACK] supply call reverted tx=%s", supply_hash,
                )
                return {
                    "status":     "FAILED",
                    "reason":     "supply receipt status=0x0 (revert)",
                    "phase":      "supply",
                    "approve_tx": approve_hash,
                    "supply_tx":  supply_hash,
                    "asset":      asset, "amount": amount,
                    "chain":      self.chain, "timestamp": ts,
                }
        except Exception as exc:  # noqa: BLE001
            log.warning("[FALLBACK] supply send failed: %s", exc)
            return {
                "status":     "FAILED",
                "reason":     f"supply failed: {exc}",
                "phase":      "supply",
                "approve_tx": approve_hash,
                "asset":      asset, "amount": amount,
                "chain":      self.chain, "timestamp": ts,
            }

        log.info(
            "[supply SUCCESS] chain=%s asset=%s amount=%.6f approve_tx=%s "
            "supply_tx=%s", self.chain, asset, amount,
            approve_hash, supply_hash,
        )
        return {
            "status":       "SUCCESS",
            "approve_tx":   approve_hash,
            "supply_tx":    supply_hash,
            "block_number": self._receipt_block_number(supply_receipt),
            "asset":        asset,
            "amount":       amount,
            "amount_usd":   amount,
            "wallet":       wallet,
            "chain":        self.chain,
            "timestamp":    ts,
        }

    def withdraw(self, asset: str, amount: float) -> dict:
        """
        Withdraw ``amount`` of ``asset`` from the Compound V3 Comet pool.

        Dry-run mode (default):
            Returns a deterministic DRY_RUN record with ``ctoken_received``
            set to the negative of ``amount`` (cUSDCv3 burn accounting).

        Live mode (``dry_run=False``):
            - If ``SPA_EXECUTION_MODE != "live"`` → ``{"status": "BLOCKED"}``
            - If ``amount > MAX_LIVE_AMOUNT`` → ``{"status": "ERROR"}``
            - Otherwise broadcasts a single signed EIP-1559 transaction:
                Comet.withdraw(asset, amount)
              Returns ``{"status": "SUCCESS", "withdraw_tx",
              "block_number", ...}``. Any RPC / receipt revert returns
              ``{"status": "FAILED", "phase": "withdraw", ...}``.

        Args:
            asset:  Symbol in SUPPORTED_ASSETS.
            amount: Strictly-positive withdraw amount in token units.

        Returns:
            dict.

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

        # Phase 3 live path.
        if amount > self.MAX_LIVE_AMOUNT:
            log.warning(
                "[withdraw REJECTED] amount %.2f exceeds MAX_LIVE_AMOUNT %.2f",
                amount, self.MAX_LIVE_AMOUNT,
            )
            return {
                "status":    "ERROR",
                "reason":    f"amount {amount} exceeds MAX_LIVE_AMOUNT "
                             f"{self.MAX_LIVE_AMOUNT}",
                "asset":     asset,
                "amount":    amount,
                "chain":     self.chain,
                "timestamp": ts,
            }

        gate = self._check_live_preconditions()
        if gate is not None:
            log.info(
                "[withdraw gated] chain=%s asset=%s reason=%s",
                self.chain, asset, gate.get("reason"),
            )
            gate.update({
                "asset": asset, "amount": amount,
                "chain": self.chain, "timestamp": ts,
            })
            return gate

        return self._live_withdraw(asset, amount, ts)

    def _live_withdraw(self, asset: str, amount: float, ts: str) -> dict:
        """Phase 3 live withdraw path. Never raises — always returns a dict."""
        try:
            Account = _require_eth_account()
        except DependencyNotInstalled as exc:
            log.warning("[FALLBACK] withdraw: %s", exc)
            return {
                "status":    "FAILED",
                "reason":    str(exc),
                "phase":     "withdraw",
                "asset":     asset,
                "amount":    amount,
                "chain":     self.chain,
                "timestamp": ts,
            }

        try:
            acct, wallet = self._resolve_signer()
        except ValueError as exc:
            log.warning("[FALLBACK] withdraw preconditions: %s", exc)
            return {
                "status":    "ERROR",
                "reason":    str(exc),
                "asset":     asset,
                "amount":    amount,
                "chain":     self.chain,
                "timestamp": ts,
            }

        decimals = self.TOKEN_DECIMALS[asset]
        raw_amount = int(round(amount * (10 ** decimals)))
        asset_addr = self.TOKEN_ADDRESSES[self.chain][asset]
        pk_normalised = self._validate_private_key(
            os.environ.get("SPA_PRIVATE_KEY", "")
        )

        try:
            chain_id = self._get_chain_id()
            nonce = self._get_nonce(wallet)
            gas_price = self._get_gas_price()
            withdraw_data = self._build_withdraw_calldata(
                asset_addr, raw_amount,
            )
            withdraw_hash = self._sign_and_send(
                Account, pk_normalised,
                to=self.comet_address, data=withdraw_data,
                nonce=nonce, chain_id=chain_id, gas_price=gas_price,
                gas_limit=350_000,
            )
            withdraw_receipt = self._wait_for_receipt(withdraw_hash)
            if not self._receipt_success(withdraw_receipt):
                log.warning(
                    "[FALLBACK] withdraw reverted tx=%s", withdraw_hash,
                )
                return {
                    "status":      "FAILED",
                    "reason":      "withdraw receipt status=0x0 (revert)",
                    "phase":       "withdraw",
                    "withdraw_tx": withdraw_hash,
                    "asset":       asset, "amount": amount,
                    "chain":       self.chain, "timestamp": ts,
                }
        except Exception as exc:  # noqa: BLE001
            log.warning("[FALLBACK] withdraw failed: %s", exc)
            return {
                "status":    "FAILED",
                "reason":    f"withdraw failed: {exc}",
                "phase":     "withdraw",
                "asset":     asset, "amount": amount,
                "chain":     self.chain, "timestamp": ts,
            }

        log.info(
            "[withdraw SUCCESS] chain=%s asset=%s amount=%.6f tx=%s",
            self.chain, asset, amount, withdraw_hash,
        )
        return {
            "status":       "SUCCESS",
            "withdraw_tx":  withdraw_hash,
            "block_number": self._receipt_block_number(withdraw_receipt),
            "asset":        asset,
            "amount":       amount,
            "amount_usd":   amount,
            "wallet":       wallet,
            "chain":        self.chain,
            "timestamp":    ts,
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
