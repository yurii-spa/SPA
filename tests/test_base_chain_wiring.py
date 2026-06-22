"""
MP-452: Base chain read-only import wiring tests.

Verifies that:
1. BASE_CHAIN_ADAPTERS dict exists (may be empty — adapters are optional)
2. scripts/base_chain_apy_fetch.py exists
3. docs/adr/ADR-025-base-chain-expansion.md exists
4. spa_core/risk/policy.py contains BASE_CHAIN_CAP
5. cycle_runner.py or adapters/__init__.py references Base chain

ADR-025 Phase 1 — read-only APY feeds, no allocation.
"""
import os


# ── helpers ─────────────────────────────────────────────────────────────────

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _file_contains(path: str, needle: str) -> bool:
    """Return True if *needle* is found literally in the file at *path*."""
    try:
        with open(path, encoding="utf-8") as f:
            return needle in f.read()
    except FileNotFoundError:
        return False


# ── tests ────────────────────────────────────────────────────────────────────


def test_base_chain_adapters_dict_exists():
    """BASE_CHAIN_ADAPTERS must be importable and be a dict (may be empty)."""
    from spa_core.adapters import BASE_CHAIN_ADAPTERS
    assert isinstance(BASE_CHAIN_ADAPTERS, dict), (
        "BASE_CHAIN_ADAPTERS must be a dict (ADR-025)"
    )


def test_base_chain_apy_fetch_script_exists():
    """scripts/base_chain_apy_fetch.py must exist (MP-452 deliverable)."""
    script = os.path.join(PROJECT_ROOT, "scripts", "base_chain_apy_fetch.py")
    assert os.path.isfile(script), (
        f"Expected script not found: {script}"
    )


def test_adr025_document_exists():
    """ADR-025 architecture decision record must exist."""
    adr = os.path.join(
        PROJECT_ROOT, "docs", "adr", "ADR-025-base-chain-expansion.md"
    )
    assert os.path.isfile(adr), (
        f"ADR-025 document not found: {adr}"
    )


def test_risk_policy_has_base_chain_cap():
    """spa_core/risk/policy.py must declare BASE_CHAIN_CAP (ADR-025 §Phase 2)."""
    policy_path = os.path.join(
        PROJECT_ROOT, "spa_core", "risk", "policy.py"
    )
    assert _file_contains(policy_path, "BASE_CHAIN_CAP"), (
        "BASE_CHAIN_CAP not found in spa_core/risk/policy.py — "
        "add per ADR-025 Phase 2 (max 20% Base exposure)"
    )


def test_base_chain_referenced_in_adapters_or_cycle_runner():
    """adapters/__init__.py or cycle_runner.py must reference Base chain."""
    init_path = os.path.join(
        PROJECT_ROOT, "spa_core", "adapters", "__init__.py"
    )
    runner_path = os.path.join(
        PROJECT_ROOT, "spa_core", "paper_trading", "cycle_runner.py"
    )
    init_ok = _file_contains(init_path, "base")
    runner_ok = _file_contains(runner_path, "BASE_CHAIN")
    assert init_ok or runner_ok, (
        "Neither adapters/__init__.py (contains 'base') nor "
        "cycle_runner.py (contains 'BASE_CHAIN') references Base chain — "
        "wiring incomplete for MP-452"
    )
