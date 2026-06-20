"""
spa_core/utils/error_catalog.py — MP-1485 (v11.01)

Machine-readable error catalog for SPA.

Maps short error codes (E001, G001, …) to class name, runtime code pattern,
description, and remediation steps.  Fully stdlib — no external dependencies.

Usage::

    from spa_core.utils.error_catalog import lookup, list_codes, ERROR_CATALOG

    info = lookup("G001")      # {'code': 'G001', 'class': 'GateError', ...}
    all_codes = list_codes()   # ['E001', 'G001', 'S001', ...]
"""

from __future__ import annotations

from typing import Optional

# ── Catalog ───────────────────────────────────────────────────────────────────
# Each entry key is a stable short code (Xnnn).  Runtime error instances may
# carry more specific codes (e.g. "GATE_BACKTEST_FAIL") — see the 'runtime_code'
# field for the pattern.

ERROR_CATALOG: dict[str, dict] = {
    "E001": {
        "code": "E001",
        "class": "SPAError",
        "runtime_code": "SPA_UNKNOWN",
        "module": "spa_core.utils.errors",
        "category": "base",
        "description": (
            "Base class for all SPA exceptions.  Raised when no more specific "
            "subclass applies.  The runtime 'code' field is 'SPA_UNKNOWN' "
            "unless overridden."
        ),
        "when": "Catch-all — when no domain-specific subclass is appropriate.",
        "remediation": (
            "Inspect the 'code' and 'details' fields via e.to_dict(). "
            "Prefer raising a specific subclass (GateError, SourceError, …) "
            "over bare SPAError."
        ),
        "example": "raise SPAError('unexpected condition', code='MY_CODE')",
    },
    "G001": {
        "code": "G001",
        "class": "GateError",
        "runtime_code": "GATE_{GATE}_{STATUS}",
        "module": "spa_core.utils.errors",
        "category": "gate",
        "description": (
            "A validation gate (backtest, pre-paper, paper, live) failed or "
            "returned a non-PASS status.  The runtime code encodes both the "
            "gate name and the observed status, e.g. 'GATE_BACKTEST_FAIL'."
        ),
        "when": (
            "Gate JSON file missing, gate status is FAIL/NOT_READY/BLOCKED, "
            "or gate data is corrupt."
        ),
        "remediation": (
            "Read e.gate and e.status to identify which gate failed. "
            "Re-run the relevant gate script (e.g. python3 -m spa_core.backtesting.backtest_gate). "
            "Check data/backtest/<gate>.json for the root cause."
        ),
        "example": "raise GateError('paper_ready', 'NOT_READY')",
    },
    "S001": {
        "code": "S001",
        "class": "SourceError",
        "runtime_code": "SOURCE_ERROR",
        "module": "spa_core.utils.errors",
        "category": "data_source",
        "description": (
            "A data source (DeFiLlama API, on-chain RPC, local cache) is "
            "unavailable, stale, or returned an unexpected schema."
        ),
        "when": (
            "DeFiLlama timeout, 5xx response, TVL below floor, "
            "APY outside sanity band, or adapter fetch returns None."
        ),
        "remediation": (
            "Check network access and DeFiLlama API status. "
            "Inspect e.source_id and e.reason. "
            "If the feed is down, the cycle will skip rebalance and retry next run."
        ),
        "example": "raise SourceError('aave_v3', 'DeFiLlama timeout after 8s')",
    },
    "V001": {
        "code": "V001",
        "class": "ValidationError",
        "runtime_code": "VALIDATION_ERROR",
        "module": "spa_core.utils.errors",
        "category": "validation",
        "description": (
            "A field-level validation check failed.  Indicates that a value "
            "passed to a function or loaded from a data file is outside its "
            "expected range or type."
        ),
        "when": (
            "Invalid allocation weight (> 1.0), negative TVL, "
            "bad date format in JSON state files, etc."
        ),
        "remediation": (
            "Inspect e.field, e.value, and e.reason. "
            "Correct the upstream data or the calling code."
        ),
        "example": "raise ValidationError('clean_pct', 1.5, 'must be in [0.0, 1.0]')",
    },
    "K001": {
        "code": "K001",
        "class": "KANBANError",
        "runtime_code": "KANBAN_ERROR",
        "module": "spa_core.utils.errors",
        "category": "kanban",
        "description": (
            "A KANBAN.json read, write, or parse operation failed.  May indicate "
            "concurrent write collision or a corrupt KANBAN.json."
        ),
        "when": (
            "KANBAN.json is missing, not valid JSON, or os.replace fails "
            "during an atomic write."
        ),
        "remediation": (
            "Check KANBAN.json with: python3 -c \"import json; json.load(open('KANBAN.json'))\". "
            "Restore from the last GitHub push if corrupt. "
            "Always write KANBAN.json atomically (tmp + os.replace)."
        ),
        "example": "raise KANBANError('KANBAN.json: invalid JSON', code='KANBAN_PARSE_ERROR')",
    },
    "A001": {
        "code": "A001",
        "class": "AdapterError",
        "runtime_code": "ADAPTER_ERROR",
        "module": "spa_core.utils.errors",
        "category": "adapter",
        "description": (
            "A DeFi protocol adapter (Aave V3, Compound V3, Morpho, …) failed "
            "to fetch or parse APY/TVL data from its source."
        ),
        "when": (
            "Network failure, unexpected API response schema, "
            "missing required key in payload, or TVL/APY parse error."
        ),
        "remediation": (
            "Check e.adapter_id and e.reason. "
            "Inspect logs for the specific adapter. "
            "The cycle skips failed adapters and continues with available data."
        ),
        "example": "raise AdapterError('compound_v3', 'missing tvlUsd key in response')",
    },
    "C001": {
        "code": "C001",
        "class": "ConfigError",
        "runtime_code": "CONFIG_ERROR",
        "module": "spa_core.utils.errors",
        "category": "config",
        "description": (
            "A required configuration value is missing or invalid.  Covers "
            "environment variables, macOS Keychain entries, and config file fields."
        ),
        "when": (
            "GITHUB_PAT_SPA not found in Keychain, "
            "DEFILLAMA_API_URL is empty, "
            "or a required JSON config key is absent."
        ),
        "remediation": (
            "Check e.key and e.reason. "
            "For PAT issues: bash setup_pat.sh <token> (see docs/TOKEN_ROTATION_RUNBOOK.md). "
            "For env vars: verify spa_core/adapters/config.py defaults."
        ),
        "example": "raise ConfigError('GITHUB_PAT_SPA', 'not found in Keychain')",
    },
    "W001": {
        "code": "W001",
        "class": "AtomicWriteError",
        "runtime_code": "ATOMIC_WRITE_ERROR",
        "module": "spa_core.utils.errors",
        "category": "io",
        "description": (
            "An atomic file write (mkstemp + os.replace) failed.  This is a "
            "critical error — state files may be corrupt or partially written."
        ),
        "when": (
            "Disk full, permission denied on the target directory, "
            "or os.replace crossing filesystem boundaries."
        ),
        "remediation": (
            "Check disk space: df -h. Check permissions on data/. "
            "Inspect e.path and e.reason. "
            "After fixing the root cause, restore the affected file from the "
            "last GitHub push."
        ),
        "example": "raise AtomicWriteError('data/trades.json', 'os.replace: Permission denied')",
    },
    "R001": {
        "code": "R001",
        "class": "RegistryError",
        "runtime_code": "REGISTRY_ERROR",
        "module": "spa_core.utils.errors",
        "category": "registry",
        "description": (
            "An adapter, strategy, or module was not found in a registry "
            "(ADAPTER_REGISTRY or the strategy registry)."
        ),
        "when": (
            "Requesting an adapter by name that is not in ADAPTER_REGISTRY, "
            "or a strategy key not present in strategy_registry.py."
        ),
        "remediation": (
            "Check ADAPTER_REGISTRY keys: from spa_core.adapters.registry import ADAPTER_REGISTRY; print(list(ADAPTER_REGISTRY)). "
            "Add the missing adapter to the registry if it exists, or correct the name."
        ),
        "example": "raise RegistryError(\"adapter 'unknown_v9' not in ADAPTER_REGISTRY\")",
    },
    "P001": {
        "code": "P001",
        "class": "RiskPolicyError",
        "runtime_code": "RISK_POLICY_ERROR",
        "module": "spa_core.utils.errors",
        "category": "risk",
        "description": (
            "A RiskPolicy constraint was violated.  This includes per-protocol "
            "caps, T2 total cap, TVL floor, APY bounds, or drawdown kill switch."
        ),
        "when": (
            "Proposed allocation exceeds T1 40% / T2 20% cap, "
            "T2 total > 50%, pool TVL < $5M, APY outside 1–30% band, "
            "or portfolio drawdown >= 5%."
        ),
        "remediation": (
            "Check data/risk_policy_blocks.json for the blocking record. "
            "RiskPolicy.approved=False cannot be overridden. "
            "Wait for market conditions to normalize or review the allocation model."
        ),
        "example": "raise RiskPolicyError('T2 total cap exceeded: 52% > 50% limit')",
    },
    "L001": {
        "code": "L001",
        "class": "AllocationError",
        "runtime_code": "ALLOCATION_ERROR",
        "module": "spa_core.utils.errors",
        "category": "allocation",
        "description": (
            "A portfolio allocation is invalid or violates a structural constraint "
            "enforced by StrategyAllocator (not RiskPolicy — use P001 for policy "
            "violations)."
        ),
        "when": (
            "Allocation weights do not sum to 1.0, negative weight, "
            "or StrategyAllocator receives contradictory constraints."
        ),
        "remediation": (
            "Inspect the allocation model output. "
            "Check spa_core/allocator/allocator.py for the relevant constraint. "
            "Ensure the sum of weights rounds to 1.0 within floating-point tolerance."
        ),
        "example": "raise AllocationError('weights sum to 0.97, expected 1.0')",
    },
    "X001": {
        "code": "X001",
        "class": "LiveTradingForbiddenError",
        "runtime_code": "LIVE_TRADING_FORBIDDEN",
        "module": "spa_core.utils.errors",
        "category": "safety",
        "description": (
            "Live (real-money) trading was attempted before all required gates "
            "passed.  This is the hard stop protecting capital during the "
            "paper-trading period."
        ),
        "when": (
            "Any live-execution function is called while paper_ready or "
            "live gate is not PASS.  Also raised by live_trading_forbidden() "
            "decorator/safeguard."
        ),
        "remediation": (
            "Do NOT suppress this exception. "
            "Check data/golive_status.json for the current gate state. "
            "Live trading can only be activated via spa_core/golive/activate.py "
            "with manual confirmation after all 26 GoLiveChecker criteria pass."
        ),
        "example": "raise LiveTradingForbiddenError('paper_ready')",
    },
}


# ── Public API ────────────────────────────────────────────────────────────────

def lookup(code: str) -> dict:
    """Return the catalog entry for a given short code (e.g. 'G001').

    Returns a dict with keys: code, class, runtime_code, module, category,
    description, when, remediation, example.

    Returns a minimal 'unknown' dict if the code is not in the catalog.

    Args:
        code: Short catalog code, e.g. 'E001', 'G001', 'X001'.

    Returns:
        dict with error metadata.

    Example::

        info = lookup('G001')
        print(info['class'])        # 'GateError'
        print(info['remediation'])  # 'Read e.gate and e.status ...'
    """
    return ERROR_CATALOG.get(
        code,
        {
            "code": code,
            "class": "Unknown",
            "runtime_code": "UNKNOWN",
            "module": "unknown",
            "category": "unknown",
            "description": f"Unknown error code: {code!r}",
            "when": "N/A",
            "remediation": "Check ERROR_CATALOG for valid codes.",
            "example": "",
        },
    )


def list_codes() -> list[str]:
    """Return all registered short codes in definition order.

    Example::

        codes = list_codes()
        # ['E001', 'G001', 'S001', 'V001', 'K001', 'A001',
        #  'C001', 'W001', 'R001', 'P001', 'L001', 'X001']
    """
    return list(ERROR_CATALOG.keys())


def lookup_by_class(class_name: str) -> Optional[dict]:
    """Return the catalog entry whose 'class' field matches ``class_name``.

    Returns ``None`` if no entry matches.

    Example::

        entry = lookup_by_class('GateError')
        # {'code': 'G001', 'class': 'GateError', ...}
    """
    for entry in ERROR_CATALOG.values():
        if entry["class"] == class_name:
            return entry
    return None


def lookup_by_category(category: str) -> list[dict]:
    """Return all catalog entries in a given category.

    Categories: base, gate, data_source, validation, kanban,
                adapter, config, io, registry, risk, allocation, safety.

    Example::

        gate_errors = lookup_by_category('gate')
        # [{'code': 'G001', 'class': 'GateError', ...}]
    """
    return [e for e in ERROR_CATALOG.values() if e["category"] == category]


__all__ = [
    "ERROR_CATALOG",
    "lookup",
    "list_codes",
    "lookup_by_class",
    "lookup_by_category",
]
