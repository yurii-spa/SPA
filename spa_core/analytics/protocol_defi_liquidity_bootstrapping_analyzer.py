"""
MP-1007 ProtocolDeFiLiquidityBootstrappingAnalyzer
Analyzes Liquidity Bootstrapping Pool (LBP) events and evaluates fairness
of price discovery. Advisory/read-only. Pure stdlib. Atomic writes only.
"""

import json
import os
import time
import tempfile
from typing import Optional

_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "lbp_analysis_log.json"
)
_LOG_CAP = 100

# ---------------------------------------------------------------------------
# Per-event calculations
# ---------------------------------------------------------------------------

def _price_efficiency_ratio(end_price: float, start_price: float) -> float:
    """end/start; ideal LBP has ~0.1-0.3 (price decayed significantly)."""
    if start_price <= 0:
        return 1.0
    return round(end_price / start_price, 4)


def _bot_extraction_usd(bot_pct: float, total_raised: float) -> float:
    """Estimated USD extracted by bots in first 10 blocks."""
    return round(bot_pct / 100.0 * total_raised, 2)


def _community_allocation_pct(team_pct: float, bot_pct: float) -> float:
    """Estimated % of tokens going to genuine community (not team, not bots)."""
    community = 100.0 - team_pct - bot_pct
    return round(max(0.0, min(100.0, community)), 2)


def _lbp_success_score(fair_launch: float, price_eff_ratio: float,
                        community_pct: float) -> float:
    """
    Composite LBP success score 0-100.
    fair_launch × price_efficiency × community_allocation / 100
    Price efficiency: how much the price decayed (1 - ratio → higher is better).
    """
    price_decay_factor = max(0.0, 1.0 - price_eff_ratio)
    community_factor = community_pct / 100.0
    score = fair_launch * price_decay_factor * community_factor
    return round(max(0.0, min(100.0, score)), 2)


def _lbp_label(success: float, bot_pct: float,
                price_eff_ratio: float) -> str:
    """Assign LBP outcome label."""
    if bot_pct > 20.0:
        return "BOT_DOMINATED"
    if success > 80.0 and bot_pct < 5.0 and price_eff_ratio < 0.5:
        return "IDEAL_LBP"
    if success >= 60.0:
        return "FAIR_LAUNCH"
    if success >= 35.0:
        return "ACCEPTABLE"
    return "FAILED_LBP"


def _compute_flags(bot_pct: float, price_eff_ratio: float,
                   team_pct: float, community_pct: float,
                   vesting_months: float, success: float) -> list:
    """Return list of flag strings for an LBP event."""
    flags = []
    if bot_pct > 15.0:
        flags.append("BOT_SNIPED")
    if price_eff_ratio > 0.8:
        flags.append("PRICE_DIDN_NOT_DECAY")
    if team_pct > 30.0:
        flags.append("TEAM_HEAVY")
    if community_pct > 60.0:
        flags.append("FAIR_COMMUNITY_DISTRIBUTION")
    if vesting_months < 6.0:
        flags.append("SHORT_VESTING_RISK")
    if success > 75.0:
        flags.append("SUCCESSFUL_PRICE_DISCOVERY")
    return flags


# ---------------------------------------------------------------------------
# Ring-buffer log writer
# ---------------------------------------------------------------------------

def _append_log(record: dict, log_path: str = _LOG_PATH,
                 cap: int = _LOG_CAP) -> None:
    """Atomically append record to ring-buffer log JSON file."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            entries = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        entries = []

    entries.append(record)
    if len(entries) > cap:
        entries = entries[-cap:]

    dir_name = os.path.dirname(log_path)
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_name, delete=False, suffix=".tmp", encoding="utf-8"
    ) as tmp:
        json.dump(entries, tmp, indent=2)
        tmp_path = tmp.name
    os.replace(tmp_path, log_path)


# ---------------------------------------------------------------------------
# Main analyze function
# ---------------------------------------------------------------------------

def analyze(lbp_events: list, config: Optional[dict] = None) -> dict:
    """
    Analyze Liquidity Bootstrapping Pool events for price discovery fairness.

    Parameters
    ----------
    lbp_events : list[dict]
        Each item must include:
            name                        str
            protocol                    str
            start_price_usd             float
            end_price_usd               float
            current_price_usd           float
            duration_hours              float
            starting_weight_pct         float  % of token in pool at start (e.g. 90-95)
            ending_weight_pct           float  % of token at end (e.g. 50)
            total_raised_usd            float
            tokens_sold_pct             float  % of supply sold
            bot_snipe_first_block_pct   float  % bought in first 10 blocks
            price_decay_rate_pct_per_hour float
            fair_launch_score           float  0-100
            team_allocation_pct         float
            vesting_period_months       float

    config : dict (optional)
        Override log_path, log_cap, write_log.

    Returns
    -------
    dict with per-event analyses and aggregate summary.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)
    log_cap = int(cfg.get("log_cap", _LOG_CAP))
    write_log = cfg.get("write_log", True)

    if not isinstance(lbp_events, list) or len(lbp_events) == 0:
        return {
            "error": "lbp_events must be a non-empty list",
            "event_analyses": [],
            "summary": {},
        }

    results = []
    for ev in lbp_events:
        name = ev.get("name", "unknown")
        protocol = ev.get("protocol", "unknown")
        start_price = float(ev.get("start_price_usd", 1.0))
        end_price = float(ev.get("end_price_usd", 1.0))
        current_price = float(ev.get("current_price_usd", end_price))
        duration_hours = float(ev.get("duration_hours", 0.0))
        starting_weight = float(ev.get("starting_weight_pct", 90.0))
        ending_weight = float(ev.get("ending_weight_pct", 50.0))
        total_raised = float(ev.get("total_raised_usd", 0.0))
        tokens_sold = float(ev.get("tokens_sold_pct", 0.0))
        bot_pct = float(ev.get("bot_snipe_first_block_pct", 0.0))
        decay_rate = float(ev.get("price_decay_rate_pct_per_hour", 0.0))
        fair_launch = float(ev.get("fair_launch_score", 50.0))
        team_pct = float(ev.get("team_allocation_pct", 0.0))
        vesting = float(ev.get("vesting_period_months", 12.0))

        per = _price_efficiency_ratio(end_price, start_price)
        discovered_fair_value = end_price
        bot_extraction = _bot_extraction_usd(bot_pct, total_raised)
        community_pct = _community_allocation_pct(team_pct, bot_pct)
        success = _lbp_success_score(fair_launch, per, community_pct)
        label = _lbp_label(success, bot_pct, per)
        flags = _compute_flags(bot_pct, per, team_pct, community_pct, vesting, success)

        results.append({
            "name": name,
            "protocol": protocol,
            "start_price_usd": start_price,
            "end_price_usd": end_price,
            "current_price_usd": current_price,
            "duration_hours": duration_hours,
            "starting_weight_pct": starting_weight,
            "ending_weight_pct": ending_weight,
            "total_raised_usd": total_raised,
            "tokens_sold_pct": tokens_sold,
            "bot_snipe_first_block_pct": bot_pct,
            "price_decay_rate_pct_per_hour": decay_rate,
            "fair_launch_score": fair_launch,
            "team_allocation_pct": team_pct,
            "vesting_period_months": vesting,
            "price_efficiency_ratio": per,
            "discovered_fair_value_usd": discovered_fair_value,
            "bot_extraction_usd": bot_extraction,
            "community_allocation_pct": community_pct,
            "lbp_success_score": success,
            "lbp_label": label,
            "flags": flags,
        })

    # Aggregates
    if results:
        sorted_by_success = sorted(results, key=lambda r: r["lbp_success_score"], reverse=True)
        most_successful = sorted_by_success[0]["name"]
        least_successful = sorted_by_success[-1]["name"]
        avg_success = round(
            sum(r["lbp_success_score"] for r in results) / len(results), 2
        )
        bot_dom_count = sum(1 for r in results if r["lbp_label"] == "BOT_DOMINATED")
        ideal_count = sum(1 for r in results if r["lbp_label"] == "IDEAL_LBP")
    else:
        most_successful = None
        least_successful = None
        avg_success = 0.0
        bot_dom_count = 0
        ideal_count = 0

    summary = {
        "event_count": len(results),
        "most_successful": most_successful,
        "least_successful": least_successful,
        "avg_success_score": avg_success,
        "bot_dominated_count": bot_dom_count,
        "ideal_count": ideal_count,
        "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    output = {
        "event_analyses": results,
        "summary": summary,
    }

    if write_log:
        log_record = {
            "timestamp": summary["analyzed_at"],
            "event_count": len(results),
            "avg_success_score": avg_success,
            "bot_dominated_count": bot_dom_count,
            "ideal_count": ideal_count,
        }
        _append_log(log_record, log_path=log_path, cap=log_cap)

    return output
