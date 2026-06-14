"""
MP-822 AutoCompounderAnalyzer
==============================
Compares auto-compounding vaults vs manual compounding, factoring in
performance fees, gas costs, and optimal compound frequency.

Advisory / read-only. Pure stdlib. Atomic writes. Ring-buffer log (cap=100).
"""

import json
import os
import time
import tempfile

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_HOLDING_PERIOD_DAYS = 365

LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "auto_compounder_log.json"
)
LOG_PATH = os.path.normpath(LOG_PATH)
LOG_CAP = 100

# Guard against overflow with compound frequency: cap at 365*24 (hourly)
MAX_VAULT_FREQ = 365 * 24


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _manual_effective_apy(base_apy: float, harvest_frequency_days: int) -> float:
    """EAR for manual compounding at *harvest_frequency_days* interval."""
    if base_apy <= 0:
        return 0.0
    freq = 365.0 / max(1, harvest_frequency_days)  # compounds per year
    ear = ((1.0 + base_apy / 100.0 / freq) ** freq - 1.0) * 100.0
    return ear


def _vault_effective_apy(
    base_apy: float,
    performance_fee_pct: float,
    compound_frequency_per_day: float,
) -> float:
    """EAR for a vault with performance fee, compounded at *compound_frequency_per_day*."""
    if base_apy <= 0:
        return 0.0
    net_apy = base_apy * (1.0 - performance_fee_pct / 100.0)
    if net_apy <= 0:
        return 0.0
    vault_freq = compound_frequency_per_day * 365.0
    vault_freq = min(vault_freq, MAX_VAULT_FREQ)  # overflow guard
    vault_freq = max(vault_freq, 1.0)
    ear = ((1.0 + net_apy / 100.0 / vault_freq) ** vault_freq - 1.0) * 100.0
    return ear


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(position: dict, vault_options: list, config: dict = None) -> dict:
    """
    Compare auto-compounding vaults against manual compounding.

    Parameters
    ----------
    position : dict
        {
            "principal_usd": float,
            "base_apy": float,
            "manual_gas_usd": float,
            "harvest_frequency_days": int
        }
    vault_options : list[dict]
        Each: {
            "name": str,
            "performance_fee_pct": float,
            "compound_frequency_per_day": float,
            "deposit_fee_pct": float,
            "withdrawal_fee_pct": float
        }
    config : dict, optional
        { "holding_period_days": int }   # default 365

    Returns
    -------
    dict — see module docstring / spec.
    """
    cfg = config or {}
    holding_period_days = int(cfg.get("holding_period_days", DEFAULT_HOLDING_PERIOD_DAYS))

    principal = float(position.get("principal_usd", 0.0))
    base_apy = float(position.get("base_apy", 0.0))
    manual_gas_usd = float(position.get("manual_gas_usd", 0.0))
    harvest_frequency_days = int(position.get("harvest_frequency_days", 1))
    if harvest_frequency_days < 1:
        harvest_frequency_days = 1

    # ---- Manual compounding ------------------------------------------------
    manual_ear = _manual_effective_apy(base_apy, harvest_frequency_days)
    annual_yield_manual = principal * manual_ear / 100.0
    annual_gas = manual_gas_usd * (365.0 / harvest_frequency_days)
    net_annual_yield_manual = annual_yield_manual - annual_gas

    manual_compounding = {
        "effective_apy": round(manual_ear, 6),
        "annual_yield_usd": round(annual_yield_manual, 4),
        "annual_gas_cost_usd": round(annual_gas, 4),
        "net_annual_yield_usd": round(net_annual_yield_manual, 4),
    }

    # ---- Vault analysis ----------------------------------------------------
    vault_results = []
    best_vault_name = None
    best_net = None
    beats_manual_count = 0

    for v in vault_options:
        name = v.get("name", "Unknown")
        perf_fee = float(v.get("performance_fee_pct", 0.0))
        cpd_freq = float(v.get("compound_frequency_per_day", 1.0))
        deposit_fee_pct = float(v.get("deposit_fee_pct", 0.0))
        withdrawal_fee_pct = float(v.get("withdrawal_fee_pct", 0.0))

        vault_ear = _vault_effective_apy(base_apy, perf_fee, cpd_freq)
        compound_boost_pct = vault_ear - manual_ear

        annual_yield_vault = principal * vault_ear / 100.0
        # Performance fee cost = fraction of yield taken by vault
        # net_apy = base_apy * (1 - perf_fee/100)  → perf_fee cost = base_yield * perf_fee/100
        base_annual_yield = principal * base_apy / 100.0
        performance_fee_cost = base_annual_yield * perf_fee / 100.0

        deposit_cost = principal * deposit_fee_pct / 100.0
        withdrawal_cost = principal * withdrawal_fee_pct / 100.0
        total_one_time_costs = deposit_cost + withdrawal_cost

        net_annual_yield_vault = annual_yield_vault - total_one_time_costs
        vs_manual_benefit = net_annual_yield_vault - net_annual_yield_manual

        # break_even_days
        if vs_manual_benefit > 0:
            daily_advantage = vs_manual_benefit / 365.0
            if daily_advantage > 0:
                break_even_days: "float | None" = total_one_time_costs / daily_advantage
            else:
                break_even_days = None
        else:
            break_even_days = None

        # recommendation
        if vs_manual_benefit > 0 and (
            break_even_days is None or break_even_days <= holding_period_days
        ):
            recommendation = "USE"
        else:
            recommendation = "SKIP"

        if vs_manual_benefit > 0:
            beats_manual_count += 1

        if best_net is None or net_annual_yield_vault > best_net:
            best_net = net_annual_yield_vault
            best_vault_name = name

        vault_results.append({
            "name": name,
            "effective_apy": round(vault_ear, 6),
            "compound_boost_pct": round(compound_boost_pct, 6),
            "annual_yield_usd": round(annual_yield_vault, 4),
            "performance_fee_cost_usd": round(performance_fee_cost, 4),
            "deposit_cost_usd": round(deposit_cost, 4),
            "withdrawal_cost_usd": round(withdrawal_cost, 4),
            "total_one_time_costs_usd": round(total_one_time_costs, 4),
            "net_annual_yield_usd": round(net_annual_yield_vault, 4),
            "vs_manual_benefit_usd": round(vs_manual_benefit, 4),
            "break_even_days": round(break_even_days, 4) if break_even_days is not None else None,
            "recommendation": recommendation,
        })

    if not vault_options:
        best_vault_name = None

    result = {
        "manual_compounding": manual_compounding,
        "vaults": vault_results,
        "best_vault": best_vault_name,
        "beats_manual_count": beats_manual_count,
        "timestamp": time.time(),
    }
    return result


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _ensure_log_dir():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)


def _load_log() -> list:
    if not os.path.exists(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_log(entries: list):
    _ensure_log_dir()
    if len(entries) > LOG_CAP:
        entries = entries[-LOG_CAP:]
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(LOG_PATH), suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp_path, LOG_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def log_result(result: dict):
    """Append *result* to the ring-buffer log at data/auto_compounder_log.json."""
    entries = _load_log()
    entries.append(result)
    _save_log(entries)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_demo():
    import json as _json

    position = {
        "principal_usd": 50_000.0,
        "base_apy": 12.0,
        "manual_gas_usd": 30.0,
        "harvest_frequency_days": 7,
    }
    vaults = [
        {
            "name": "Beefy Finance",
            "performance_fee_pct": 4.5,
            "compound_frequency_per_day": 48.0,
            "deposit_fee_pct": 0.0,
            "withdrawal_fee_pct": 0.1,
        },
        {
            "name": "Yearn V3",
            "performance_fee_pct": 10.0,
            "compound_frequency_per_day": 1.0,
            "deposit_fee_pct": 0.0,
            "withdrawal_fee_pct": 0.0,
        },
    ]
    result = analyze(position, vaults)
    print(_json.dumps(result, indent=2))
    log_result(result)
    print(f"\nLogged to {LOG_PATH}")


if __name__ == "__main__":
    _cli_demo()
