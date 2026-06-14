"""
SPA Engine Bridge — FEAT-004/005 Phase 4 (Sprint v3.11 / SPA-V41-001).

Thin façade that connects ``spa_core.paper_trading.engine.PaperTrader`` to the
two live execution adapters (``AaveV3Adapter`` / ``CompoundV3Adapter``) WITHOUT
touching the paper-trading bookkeeping path.

Design contract (mirrors the Phase 3 cards verbatim):

  * The paper book is the source of truth — every SQLite ``paper_trades``
    INSERT in ``PaperTrader`` happens unconditionally. The live adapter call
    is purely ADDITIVE.

  * Default behaviour is BYTE-IDENTICAL paper trading. The bridge is only
    invoked when the engine explicitly opts in via the per-strategy
    ``live_execution=True`` flag AND the global ``SPA_EXECUTION_MODE=live``
    env var is set. Anything else returns a structured
    ``{"status": "SKIPPED", "reason": "..."}`` record.

  * Adapters are imported LAZILY (inside the methods, on first use) so the
    happy-path engine startup keeps its current dependency surface and tests
    stay fast.

  * Live writes NEVER raise. Every failure mode (unparseable protocol_key,
    unsupported protocol, adapter exception, FAILED/BLOCKED/ERROR adapter
    response) returns a structured dict. The bridge also appends a
    structured row to ``data/live_execution_log.json`` for every non-skipped
    invocation (capped at ~1000 entries — oldest dropped first).

Supported protocol_key shapes:

  * ``aave-v3-<asset>-<chain>``      → AaveV3Adapter   (USDC / USDT / DAI)
  * ``compound-v3-<asset>-<chain>``  → CompoundV3Adapter (USDC only)

Anything else returns ``{"status": "SKIPPED", "reason": "unsupported_protocol"}``.

Usage (called from PaperTrader.open_position / .close_position):

    from spa_core.execution.engine_bridge import LiveExecutionBridge

    bridge = LiveExecutionBridge()
    supply_result = bridge.execute_supply("aave-v3-usdc-ethereum", 3000.0)
    # → {"status": "SKIPPED", "reason": "execution_mode_paper"} (default)
    # → {"status": "SUCCESS", "supply_tx": "0x...", ...}        (live mode)
    # → {"status": "FAILED",  "reason": "...", "phase": "..."}   (live mode, RPC flake)

The bridge is intentionally STATELESS aside from the lazy adapter cache, so
tests can re-instantiate it per-test without side effects beyond the on-disk
log file (which they redirect via ``log_path``).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("spa.engine_bridge")


# ─── Constants ────────────────────────────────────────────────────────────────

# Default location of the append-only live execution audit log. Relative to
# the repo root (one level above spa_core/). Test fixtures override via the
# ``log_path`` constructor arg.
_DEFAULT_LOG_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "live_execution_log.json"
)

# Hard rotation cap. We keep the most recent N entries; older entries are
# dropped on each append. Chosen large enough to keep ~weeks of go-live
# diagnostics but small enough that one JSON load stays cheap.
LOG_MAX_ENTRIES: int = 1000

# Supported protocol prefixes mapped to adapter family keys. The asset/chain
# tail is parsed by ``_parse_protocol_key``.
_PROTOCOL_PREFIX_TO_FAMILY: dict[str, str] = {
    "aave-v3":     "aave_v3",
    "compound-v3": "compound_v3",
    "morpho-blue": "morpho",        # T1 Morpho Blue — Sprint v3.48 / SPA-V348-001 (longest-prefix)
    "morpho":      "morpho",        # T1 — Sprint v3.24 / SPA-V324-002
    "yearn-v3":    "yearn_v3",      # T2 — Sprint v3.25 / SPA-V325-001
    "euler-v2":    "euler_v2",      # T2 — Sprint v3.25 / SPA-V325-002
    "maple":       "maple",         # T2 — Sprint v3.25 / SPA-V325-003
    "pendle-pt":   "pendle_pt",     # T2 — Sprint v3.28 / SPA-V328-001
    "sky-susds":   "sky_susds",     # Conditional T1 — Sprint v3.29 / SPA-V329-001
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _execution_mode_live() -> bool:
    """True iff SPA_EXECUTION_MODE env var is exactly ``live`` (case-insensitive).

    Mirrors the gate used by both AaveV3Adapter and CompoundV3Adapter so the
    bridge fails-closed in the same direction as the adapters themselves.
    """
    return os.environ.get("SPA_EXECUTION_MODE", "").strip().lower() == "live"


def _parse_protocol_key(protocol_key: str) -> Optional[dict]:
    """Split a SPA-canonical protocol key into ``(family, asset, chain)``.

    Accepts:
        ``aave-v3-usdc-ethereum``     → {"family": "aave_v3",     "asset": "USDC", "chain": "ethereum"}
        ``compound-v3-usdc-arbitrum`` → {"family": "compound_v3", "asset": "USDC", "chain": "arbitrum"}
        ``aave-v3-dai-base``          → {"family": "aave_v3",     "asset": "DAI",  "chain": "base"}

    Returns ``None`` for any key that doesn't start with a known prefix or
    that has fewer than the expected segments. Callers should treat ``None``
    as a SKIPPED outcome.

    Args:
        protocol_key: The protocol key string from the engine.

    Returns:
        Parsed dict or None if unparseable.
    """
    if not isinstance(protocol_key, str) or not protocol_key:
        return None

    key = protocol_key.strip().lower()

    matched_prefix: Optional[str] = None
    # Longest-prefix-first so multi-word prefixes (e.g. "morpho-blue") win
    # over their shorter base ("morpho"). SPA-V348.
    for prefix in sorted(_PROTOCOL_PREFIX_TO_FAMILY, key=len, reverse=True):
        # Match exact "<prefix>-..." form so "aave-v3-foo" matches but
        # "aave-v3" or "aave-v3foo" does not.
        if key.startswith(prefix + "-"):
            matched_prefix = prefix
            break

    if matched_prefix is None:
        return None

    tail = key[len(matched_prefix) + 1:]
    parts = tail.split("-")
    if len(parts) < 2:
        return None

    # Tail is "<asset>-<chain>" — asset is everything but the last segment
    # so that future multi-word assets (e.g. "pt-steth") survive without a
    # rewrite. Today every asset is a single token.
    asset = "-".join(parts[:-1]).upper()
    chain = parts[-1]

    if not asset or not chain:
        return None

    return {
        "family": _PROTOCOL_PREFIX_TO_FAMILY[matched_prefix],
        "asset":  asset,
        "chain":  chain,
    }


# ─── Bridge ───────────────────────────────────────────────────────────────────

class LiveExecutionBridge:
    """Thin façade over Aave V3 / Compound V3 adapters for engine.py.

    The bridge is responsible for three things and three things only:

      1. Hard-gate on ``SPA_EXECUTION_MODE=live`` (everything else → SKIPPED).
      2. Parse the SPA protocol_key, dispatch to the right adapter family
         and instantiate (lazily, cached per (family, chain) pair) the
         adapter with ``dry_run=False`` so the live signing path runs.
      3. Append a structured audit row to ``data/live_execution_log.json``
         for every non-skipped invocation.

    Failure semantics are documented in the module docstring — TL;DR the
    bridge NEVER raises; every error path returns a structured dict.
    """

    def __init__(self, log_path: Optional[Path] = None) -> None:
        """Initialise the bridge.

        Args:
            log_path: Optional override for the audit-log path. Tests pass
                a ``tmp_path`` here so they don't pollute the real
                ``data/live_execution_log.json``. ``None`` uses the default
                repo-root path.
        """
        self.log_path: Path = Path(log_path) if log_path else _DEFAULT_LOG_PATH
        # Adapter cache keyed by (family, chain). Adapters are constructed
        # lazily on first use — see _get_adapter().
        self._adapters: dict[tuple[str, str], object] = {}

    # ── Public API ─────────────────────────────────────────────────────────

    def execute_supply(self, protocol_key: str, amount_usd: float) -> dict:
        """Forward a supply() call to the right adapter, or SKIP.

        Returns one of:
            * ``{"status": "SKIPPED", "reason": "execution_mode_paper"}``
                — SPA_EXECUTION_MODE not "live"
            * ``{"status": "SKIPPED", "reason": "unparseable_protocol_key", ...}``
            * ``{"status": "SKIPPED", "reason": "unsupported_protocol", ...}``
                — protocol prefix isn't aave-v3 / compound-v3
            * Whatever the adapter returns (SUCCESS / FAILED / BLOCKED / ERROR)
              — augmented with ``bridge_action=supply`` and ``protocol_key``.

        Args:
            protocol_key: SPA-canonical key, e.g. ``"aave-v3-usdc-ethereum"``.
            amount_usd:   Position size in USD (float).

        Returns:
            dict (never raises).
        """
        return self._execute("supply", protocol_key, amount_usd)

    def execute_withdraw(self, protocol_key: str, amount_usd: float) -> dict:
        """Forward a withdraw() call to the right adapter, or SKIP.

        Same return contract as ``execute_supply``. The amount must be a
        strictly-positive USD figure; the adapter does its own validation.

        Args:
            protocol_key: SPA-canonical key (e.g. ``"compound-v3-usdc-base"``).
            amount_usd:   Amount to withdraw in USD (float).

        Returns:
            dict (never raises).
        """
        return self._execute("withdraw", protocol_key, amount_usd)

    # ── Internals ──────────────────────────────────────────────────────────

    def _execute(
        self,
        action: str,
        protocol_key: str,
        amount_usd: float,
    ) -> dict:
        """Common gate + dispatch path for supply/withdraw."""
        ts = _now_iso()

        # 1) Global hard-gate — SPA_EXECUTION_MODE must be "live".
        if not _execution_mode_live():
            return {
                "status":       "SKIPPED",
                "reason":       "execution_mode_paper",
                "bridge_action": action,
                "protocol_key": protocol_key,
                "amount_usd":   amount_usd,
                "timestamp":    ts,
            }

        # 2) Parse the protocol key.
        parsed = _parse_protocol_key(protocol_key)
        if parsed is None:
            result = {
                "status":        "SKIPPED",
                "reason":        "unparseable_protocol_key",
                "bridge_action": action,
                "protocol_key":  protocol_key,
                "amount_usd":    amount_usd,
                "timestamp":     ts,
            }
            self._append_log(result)
            return result

        family = parsed["family"]
        asset  = parsed["asset"]
        chain  = parsed["chain"]

        # 3) Resolve adapter (also handles unsupported chain/asset).
        try:
            adapter = self._get_adapter(family, chain)
        except Exception as exc:  # noqa: BLE001 — never raise
            result = {
                "status":        "SKIPPED",
                "reason":        "adapter_init_failed",
                "detail":        str(exc),
                "bridge_action": action,
                "protocol_key":  protocol_key,
                "family":        family,
                "chain":         chain,
                "asset":         asset,
                "amount_usd":    amount_usd,
                "timestamp":     ts,
            }
            self._append_log(result)
            log.warning(
                "[engine_bridge] %s: adapter init failed for %s: %s",
                action, protocol_key, exc,
            )
            return result

        if adapter is None:
            result = {
                "status":        "SKIPPED",
                "reason":        "unsupported_protocol",
                "bridge_action": action,
                "protocol_key":  protocol_key,
                "family":        family,
                "chain":         chain,
                "asset":         asset,
                "amount_usd":    amount_usd,
                "timestamp":     ts,
            }
            self._append_log(result)
            return result

        # 4) Run the live call. Adapters guarantee they never raise — but we
        #    still wrap defensively so a future-adapter regression can't
        #    crash the paper engine.
        try:
            if action == "supply":
                adapter_result = adapter.supply(asset, float(amount_usd))
            elif action == "withdraw":
                adapter_result = adapter.withdraw(asset, float(amount_usd))
            else:  # pragma: no cover — internal misuse
                raise ValueError(f"unknown action {action!r}")
        except Exception as exc:  # noqa: BLE001
            adapter_result = {
                "status":    "ERROR",
                "reason":    f"adapter raised: {exc}",
                "asset":     asset,
                "amount":    amount_usd,
                "chain":     chain,
                "timestamp": ts,
            }
            log.warning(
                "[engine_bridge] %s: adapter raised for %s: %s",
                action, protocol_key, exc,
            )

        # 5) Augment + log + return.
        enriched = dict(adapter_result) if isinstance(adapter_result, dict) else {
            "status": "ERROR", "reason": "adapter returned non-dict",
            "raw": repr(adapter_result),
        }
        enriched.setdefault("bridge_action", action)
        enriched.setdefault("protocol_key", protocol_key)
        enriched.setdefault("family", family)
        enriched.setdefault("amount_usd", amount_usd)
        enriched.setdefault("timestamp", ts)

        self._append_log(enriched)

        status = enriched.get("status", "UNKNOWN")
        if status in ("FAILED", "BLOCKED", "ERROR"):
            log.warning(
                "[engine_bridge] %s NON-SUCCESS protocol=%s status=%s reason=%s",
                action, protocol_key, status, enriched.get("reason"),
            )
        else:
            log.info(
                "[engine_bridge] %s status=%s protocol=%s amount=%.4f",
                action, status, protocol_key, float(amount_usd),
            )

        return enriched

    def _get_adapter(self, family: str, chain: str) -> Optional[object]:
        """Lazy-construct + cache the adapter for (family, chain).

        Returns ``None`` if ``family`` is unknown OR if the adapter rejects
        ``chain`` (raises ValueError) — both routes map to "unsupported"
        in the caller.

        Raises:
            ImportError: If the adapter module itself isn't importable.
                Re-raised so the caller can log a structured SKIPPED row
                via the outer try/except. We don't expect this in practice
                because the adapters live in the same repo as the bridge.
        """
        cache_key = (family, chain)
        cached = self._adapters.get(cache_key)
        if cached is not None:
            return cached

        # Lazy import — keep the engine startup path clean.
        if family == "aave_v3":
            from spa_core.execution.aave_v3_adapter import AaveV3Adapter
            adapter_cls = AaveV3Adapter
        elif family == "compound_v3":
            from spa_core.execution.compound_v3_adapter import CompoundV3Adapter
            adapter_cls = CompoundV3Adapter
        elif family == "morpho":
            from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
            adapter_cls = MorphoAdapter
        elif family == "yearn_v3":
            from spa_core.execution.adapters.yearn_v3_adapter import YearnV3Adapter
            adapter_cls = YearnV3Adapter
        elif family == "euler_v2":
            from spa_core.execution.adapters.euler_v2_adapter import EulerV2Adapter
            adapter_cls = EulerV2Adapter
        elif family == "maple":
            from spa_core.execution.adapters.maple_adapter import MapleAdapter
            adapter_cls = MapleAdapter
        elif family == "pendle_pt":
            from spa_core.execution.adapters.pendle_pt_adapter import PendlePTAdapter
            adapter_cls = PendlePTAdapter
        elif family == "sky_susds":
            from spa_core.execution.adapters.sky_susds_adapter import SkySUSDSAdapter
            adapter_cls = SkySUSDSAdapter
        else:
            return None

        try:
            adapter = adapter_cls(chain=chain, dry_run=False)
        except ValueError as exc:
            # Unsupported chain on this adapter — treat as unsupported_protocol.
            log.debug(
                "[engine_bridge] %s rejected chain=%s: %s",
                family, chain, exc,
            )
            return None

        self._adapters[cache_key] = adapter
        return adapter

    # ── Audit log ──────────────────────────────────────────────────────────

    def _append_log(self, entry: dict) -> None:
        """Append ``entry`` to the audit log, cap at LOG_MAX_ENTRIES.

        The on-disk format is a JSON array (not JSON-lines) for easier
        ad-hoc inspection from the dashboard. We re-read + truncate +
        re-write on every call; this is O(N) but N is bounded by
        LOG_MAX_ENTRIES and live writes are infrequent (~one per rebalance
        cycle in steady state).

        All I/O exceptions are swallowed and logged at WARNING — the
        audit log must never block a paper-trade.
        """
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

            entries: list = []
            if self.log_path.exists():
                try:
                    raw = self.log_path.read_text(encoding="utf-8")
                    if raw.strip():
                        loaded = json.loads(raw)
                        if isinstance(loaded, list):
                            entries = loaded
                        else:
                            # File is something else — start fresh rather than
                            # destroy whatever it is. Log loudly so an operator
                            # notices.
                            log.warning(
                                "[engine_bridge] live_execution_log.json is "
                                "not a list (type=%s) — resetting",
                                type(loaded).__name__,
                            )
                            entries = []
                except (ValueError, OSError) as exc:
                    log.warning(
                        "[engine_bridge] live_execution_log.json unreadable "
                        "(%s) — resetting", exc,
                    )
                    entries = []

            entries.append(entry)

            # Rotate: keep the most recent LOG_MAX_ENTRIES rows.
            if len(entries) > LOG_MAX_ENTRIES:
                entries = entries[-LOG_MAX_ENTRIES:]

            self.log_path.write_text(
                json.dumps(entries, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 — never raise from logging
            log.warning(
                "[engine_bridge] failed to write audit log: %s", exc,
            )


# ─── Convenience ──────────────────────────────────────────────────────────────

# Module-level singleton — engines can either import the class and own their
# own instance (preferred for test isolation) OR grab this default for ad-hoc
# scripts. PaperTrader uses its own instance.
default_bridge = LiveExecutionBridge()


if __name__ == "__main__":  # pragma: no cover — manual sanity check
    logging.basicConfig(level=logging.INFO)
    b = LiveExecutionBridge()
    print("supply (paper):  ", json.dumps(b.execute_supply("aave-v3-usdc-ethereum", 100.0), indent=2))
    print("withdraw (paper):", json.dumps(b.execute_withdraw("compound-v3-usdc-arbitrum", 50.0), indent=2))
