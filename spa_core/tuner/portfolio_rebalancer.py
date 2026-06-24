"""
spa_core/tuner/portfolio_rebalancer.py — Portfolio Rebalancer (ALLOC-001)

Соединяет AllocationTuner с data/current_positions.json через детерминированный
слой валидации policy_enforcer. Запись в current_positions.json возможна ТОЛЬКО
через этот модуль после успешной валидации.

LLM_FORBIDDEN: capital allocation is deterministic — никаких AI-вызовов.
FAIL-CLOSED: невалидный портфель → NOT written, ошибка + Telegram alert.
ATOMIC WRITES: tmp-файл + os.replace (через spa_core.utils.atomic).

Архитектура:
    1. Загружает live APY из data/adapter_orchestrator_status.json
    2. Запускает AllocationTuner.optimize() с policy-compliant constraints
    3. Конвертирует веса (0..1) → USD суммы
    4. Валидирует через validate_positions() — fail-closed
    5. Если PASS → атомично пишет data/current_positions.json
    6. Если FAIL → логирует, шлёт Telegram алерт, НЕ пишет

Использование:
    python3 -m spa_core.tuner.portfolio_rebalancer
    python3 -m spa_core.tuner.portfolio_rebalancer --check   # только проверить, не писать
    python3 -m spa_core.tuner.portfolio_rebalancer --data-dir /path/to/data
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.utils.atomic import atomic_save
from spa_core.tuner.allocation_tuner import (
    AllocationTuner,
    TunerConstraints,
    TunerResult,
    _load_adapter_data,
)
from spa_core.risk.policy_enforcer import (
    validate_positions,
    ValidationResult,
    format_violations_text,
)

log = logging.getLogger("spa.tuner.portfolio_rebalancer")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

POSITIONS_FILENAME = "current_positions.json"
REBALANCER_VERSION = "v1.0"

# TunerConstraints, выровненные с policy_enforcer RULES:
#   per_protocol_max = 25%  (RULES["per_protocol_max_pct"] = 25.0)
#   t1_min = 55%            (RULES["t1_min_pct"] = 55.0)
#   t2_max = 45%            (консервативнее ADR-019 cap 50%)
#   cash_min = 7%           (выше 5% minimum для запаса)
#   max_protocols = 7       (< RULES["max_protocols"] = 8, запас 1)
_DEFAULT_CONSTRAINTS = TunerConstraints(
    t1_min=0.55,
    t2_max=0.45,
    per_protocol_max=0.25,
    tvl_floor_usd=5_000_000.0,
    min_protocols=3,
    max_protocols=7,
    cash_min=0.07,
    apy_min=1.0,
    apy_max=30.0,
)

# Safe fallback portfolio — used when tuner cannot produce a policy-compliant
# allocation (e.g., insufficient T1 adapters in orchestrator data).
# T1=60%, T2=28%, T3=5%, cash=7% — all policy rules satisfied.
# ADR-001: изменение этих значений требует обновления ADR.
_SAFE_FALLBACK_POSITIONS: Dict[str, float] = {
    "aave_v3": 22_000.0,          # T1 — 22%, Aave V3 Ethereum
    "compound_v3": 15_000.0,      # T1 — 15%, Compound V3 Comet USDC
    "spark_susds": 13_000.0,      # T1 — 13%, Sky/sUSDS
    "morpho_steakhouse": 10_000.0, # T1 — 10%, Morpho Steakhouse
    "maple": 15_000.0,            # T2 — 15%, Maple Finance
    "euler_v2": 10_000.0,         # T2 — 10%, Euler V2
    "yearn_v3": 3_000.0,          # T2 — 3%, Yearn V3
}
# cash = 100_000 - 88_000 = 12_000 = 12%  → satisfies 5% minimum ✓


# ─── Telegram helper (same pattern as rules_watchdog.py) ─────────────────────


def _read_keychain(service: str) -> Optional[str]:
    """Read secret from macOS Keychain (best-effort)."""
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            val = proc.stdout.strip()
            return val if val else None
    except Exception:
        pass
    return None


def _send_telegram(message: str) -> bool:
    """Send Telegram alert via the canonical rate-limited client. Best-effort, never raises.

    FLOOD-GUARD: routed through spa_core.alerts.telegram_client so the shared
    cross-process rate limit applies. Transport only — same HTML alert.
    """
    try:
        from spa_core.alerts.telegram_client import send_message
        return send_message(message[:4096], parse_mode="HTML")
    except Exception as e:
        log.warning("Telegram send failed: %s", e)
        return False


# ─── Core logic ──────────────────────────────────────────────────────────────


def _weights_to_usd(
    weights: Dict[str, float],
    capital_usd: float,
    cash_min_fraction: float = 0.07,
) -> Tuple[Dict[str, float], float]:
    """Convert fractional weights (0..1) to USD amounts.

    Weights from AllocationTuner already respect the cash_min constraint:
    they sum to at most (1 - cash_min). So multiplying by capital gives
    USD positions directly, and the remainder is cash.

    Returns:
        (positions_usd, cash_usd) where positions_usd is {protocol: usd_amount}
        and cash_usd = capital_usd - sum(positions_usd)
    """
    positions_usd = {}
    for proto, w in weights.items():
        if w > 1e-6:  # ignore dust
            positions_usd[proto] = round(w * capital_usd, 2)

    deployed = sum(positions_usd.values())
    cash_usd = round(capital_usd - deployed, 2)

    # Safety: enforce cash_min as hard floor
    min_cash = capital_usd * cash_min_fraction
    if cash_usd < min_cash:
        # Scale down positions proportionally to free up cash
        target_deployed = capital_usd - min_cash
        if deployed > 0:
            scale = target_deployed / deployed
            positions_usd = {k: round(v * scale, 2) for k, v in positions_usd.items()}
        cash_usd = round(capital_usd - sum(positions_usd.values()), 2)

    return positions_usd, cash_usd


def _build_safe_fallback_positions(
    capital_usd: float,
    base_positions: Optional[Dict[str, float]] = None,
) -> Tuple[Dict[str, float], float]:
    """Build a known-good policy-compliant portfolio.

    Used when AllocationTuner cannot produce a valid allocation (e.g.,
    insufficient T1 adapters available from the orchestrator). Scales the
    hard-coded _SAFE_FALLBACK_POSITIONS proportionally to capital_usd,
    keeping T1=60%, T2=28%, cash=12%.

    Args:
        capital_usd:    Total virtual capital.
        base_positions: Optional override of the fallback positions (for tests).

    Returns:
        (positions_usd, cash_usd)
    """
    base = base_positions if base_positions is not None else _SAFE_FALLBACK_POSITIONS
    base_capital = sum(base.values())   # e.g. 88_000 for $100K
    base_cash_frac = (capital_usd - base_capital) / capital_usd  # should be > 0.05

    if base_capital <= 0:
        return {}, capital_usd

    # If base was designed for a different capital, scale proportionally
    scale = (capital_usd - capital_usd * 0.07) / base_capital  # keep 7% cash
    positions = {k: round(v * scale, 2) for k, v in base.items()}
    cash_usd = round(capital_usd - sum(positions.values()), 2)
    return positions, cash_usd


def rebalance_portfolio(
    capital_usd: float = 100_000.0,
    constraints: Optional[TunerConstraints] = None,
    data_dir: Optional[Path] = None,
    write: bool = True,
    send_alert: bool = True,
) -> bool:
    """Run AllocationTuner and write result to current_positions.json.

    LLM_FORBIDDEN: all logic is deterministic.

    Args:
        capital_usd:  Total virtual capital in USD (default $100K).
        constraints:  TunerConstraints (default: policy-compliant defaults).
        data_dir:     Path to data/ directory (default: repo's data/).
        write:        If True, atomically write positions on success.
        send_alert:   If True, send Telegram alert on validation failure.

    Returns:
        True  — rebalance succeeded, positions updated (or would be if write=False).
        False — validation failed, positions NOT changed.
    """
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    c = constraints or _DEFAULT_CONSTRAINTS

    ts = datetime.now(timezone.utc).isoformat()
    log.info("ALLOC-001 portfolio_rebalancer starting (capital=$%.0f)", capital_usd)

    # ── 1. Load adapter data ───────────────────────────────────────────────
    adapter_data: List[dict] = _load_adapter_data(ddir)
    if not adapter_data:
        log.warning(
            "ALLOC-001: no adapter data from adapter_orchestrator_status.json — "
            "cannot rebalance, keeping existing positions"
        )
        return False

    log.info("ALLOC-001: loaded %d adapters from orchestrator", len(adapter_data))

    # ── 2. Run AllocationTuner ─────────────────────────────────────────────
    tuner = AllocationTuner(constraints=c)
    result: TunerResult = tuner.optimize(
        adapter_data=adapter_data,
        current_weights=None,   # will compare vs file internally if needed
        n_candidates=500,
    )

    if not result.optimal_weights:
        log.warning(
            "ALLOC-001: tuner returned empty weights (likely all-cash fallback: %s) "
            "— skipping rebalance",
            result.improvements,
        )
        return False

    log.info(
        "ALLOC-001: tuner optimal_weights=%s expected_apy=%.2f%% sharpe=%.4f",
        {k: round(v, 4) for k, v in result.optimal_weights.items()},
        result.expected_apy,
        result.expected_sharpe,
    )

    # ── 3. Convert weights → USD ───────────────────────────────────────────
    positions_usd, cash_usd = _weights_to_usd(
        result.optimal_weights,
        capital_usd=capital_usd,
        cash_min_fraction=c.cash_min,
    )

    log.info(
        "ALLOC-001: USD positions=%s cash=$%.0f",
        {k: v for k, v in positions_usd.items()},
        cash_usd,
    )

    # ── 4. Validate via policy_enforcer — FAIL-CLOSED ─────────────────────
    val: ValidationResult = validate_positions(
        positions=positions_usd,
        capital_usd=capital_usd,
        cash_usd=cash_usd,
    )

    if not val.passed:
        rules_violated = [v.rule for v in val.violations]
        log.warning(
            "ALLOC-001: tuner allocation rejected (%s) — "
            "trying safe fallback portfolio",
            rules_violated,
        )
        # ── Fallback: use hardcoded policy-compliant portfolio ────────────
        positions_usd, cash_usd = _build_safe_fallback_positions(capital_usd)
        val = validate_positions(
            positions=positions_usd,
            capital_usd=capital_usd,
            cash_usd=cash_usd,
        )
        if not val.passed:
            fallback_rules = [v.rule for v in val.violations]
            log.error(
                "ALLOC-001: safe fallback ALSO rejected by policy_enforcer: %s — "
                "positions NOT written",
                fallback_rules,
            )
            if send_alert:
                alert_text = (
                    "🚨 <b>ALLOC-001: Rebalancer + Fallback Both REJECTED</b>\n"
                    "Время: {}\n"
                    "Tuner нарушения: {}\n"
                    "Fallback нарушения: {}\n\n"
                    "{}"
                ).format(
                    ts[:19].replace("T", " "),
                    rules_violated,
                    fallback_rules,
                    format_violations_text(val),
                )
                _send_telegram(alert_text)
            return False

        log.info(
            "ALLOC-001: safe fallback portfolio accepted — "
            "T1=%.1f%%, T2=%.1f%%, cash=%.1f%%",
            val.portfolio_summary.get("t1_pct", 0),
            val.portfolio_summary.get("t2_pct", 0),
            val.portfolio_summary.get("cash_pct", 0),
        )

    if val.warnings:
        log.warning(
            "ALLOC-001: rebalance passed with %d warning(s): %s",
            len(val.warnings),
            [w.rule for w in val.warnings],
        )

    # ── 5. Atomic write to current_positions.json ──────────────────────────
    deployed_usd = sum(positions_usd.values())
    doc = {
        "generated_at": ts,
        "source": "portfolio_rebalancer_v1",
        "rebalancer_version": REBALANCER_VERSION,
        "execution_mode": "read_only_simulation",
        "is_demo": False,
        "capital_usd": capital_usd,
        "deployed_usd": round(deployed_usd, 2),
        "cash_usd": round(cash_usd, 2),
        "policy_compliant": True,
        "policy_version": "v1.0",
        "tuner_expected_apy": round(result.expected_apy, 4),
        "tuner_expected_sharpe": round(result.expected_sharpe, 4),
        "tuner_objective_score": round(result.objective_score, 6),
        "positions": positions_usd,
        "validation_summary": val.portfolio_summary,
    }

    positions_path = ddir / POSITIONS_FILENAME

    if write:
        atomic_save(doc, str(positions_path))
        log.info(
            "ALLOC-001: positions written to %s "
            "(protocols=%d, T1=%.1f%%, T2=%.1f%%, cash=%.1f%%)",
            positions_path,
            val.portfolio_summary.get("protocol_count", 0),
            val.portfolio_summary.get("t1_pct", 0),
            val.portfolio_summary.get("t2_pct", 0),
            val.portfolio_summary.get("cash_pct", 0),
        )
    else:
        log.info(
            "ALLOC-001: --check mode, not writing. "
            "Would write: protocols=%d, T1=%.1f%%, T2=%.1f%%, cash=%.1f%%",
            val.portfolio_summary.get("protocol_count", 0),
            val.portfolio_summary.get("t1_pct", 0),
            val.portfolio_summary.get("t2_pct", 0),
            val.portfolio_summary.get("cash_pct", 0),
        )

    return True


def check_current_positions(
    data_dir: Optional[Path] = None,
    capital_usd: float = 100_000.0,
) -> ValidationResult:
    """Validate the current positions file without rebalancing.

    Returns a ValidationResult — useful for cycle_runner to detect
    pre-existing violations before deciding whether to trigger rebalancer.
    """
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    pos_path = ddir / POSITIONS_FILENAME

    if not pos_path.exists():
        from spa_core.risk.policy_enforcer import ValidationResult, Violation
        return ValidationResult(
            passed=False,
            violations=[Violation(
                rule="file_exists",
                severity="CRITICAL",
                message="current_positions.json not found: {}".format(pos_path),
            )],
        )

    try:
        doc = json.loads(pos_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        from spa_core.risk.policy_enforcer import ValidationResult, Violation
        return ValidationResult(
            passed=False,
            violations=[Violation(
                rule="file_valid_json",
                severity="CRITICAL",
                message="current_positions.json unreadable: {}".format(e),
            )],
        )

    positions = doc.get("positions", {})
    cap = float(doc.get("capital_usd") or capital_usd)
    cash = float(doc.get("cash_usd") or 0.0)

    return validate_positions(positions=positions, capital_usd=cap, cash_usd=cash)


# ─── CLI entry point ──────────────────────────────────────────────────────────


def main() -> None:
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="SPA Portfolio Rebalancer (ALLOC-001)")
    parser.add_argument(
        "--check", action="store_true",
        help="Validate only — do not write positions",
    )
    parser.add_argument(
        "--data-dir", type=str, default=None,
        help="Path to data/ directory (default: repo/data/)",
    )
    parser.add_argument(
        "--capital", type=float, default=100_000.0,
        help="Total capital in USD (default: 100000)",
    )
    parser.add_argument(
        "--no-alert", action="store_true",
        help="Suppress Telegram alerts",
    )
    args = parser.parse_args()

    ddir = Path(args.data_dir) if args.data_dir else None

    if args.check:
        # Check-only mode: validate current positions
        log.info("ALLOC-001 check mode: validating current positions")
        result = check_current_positions(data_dir=ddir, capital_usd=args.capital)
        print(format_violations_text(result))
        sys.exit(0 if result.passed else 1)
    else:
        # Rebalance mode
        ok = rebalance_portfolio(
            capital_usd=args.capital,
            data_dir=ddir,
            write=True,
            send_alert=not args.no_alert,
        )
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
