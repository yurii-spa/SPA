"""
MP-933: ProtocolAirdropEligibilityOptimizer
=============================================
Advisory-only analytics module.
Evaluates and optimizes eligibility for upcoming protocol airdrops.

Input (per wallet):
  address, protocols_interacted (list), tx_count_total, unique_days_active,
  volume_usd_total, earliest_interaction_days_ago, nft_count,
  governance_votes_count, bridged_chains (list), referrals_count

Per wallet × per airdrop_program (from config):
  eligibility_score (0-100), estimated_tokens, estimated_usd_value,
  missing_criteria (list), completion_pct
  opportunity_label: HIGHLY_ELIGIBLE / ELIGIBLE / PARTIAL /
                     LOW_CHANCE / INELIGIBLE

Per-wallet flags:
  OG_USER (earliest_interaction_days_ago ≥ 365)
  POWER_USER (tx ≥ 500 AND volume ≥ $100k)
  MULTI_CHAIN (bridged_chains ≥ 2)
  GOVERNANCE_PARTICIPANT (governance_votes ≥ 1)
  SYBIL_RISK (tx ≤ 10 AND unique_days_active == 1)

Per-wallet aggregates:
  total_estimated_usd, top_opportunity, completion_roadmap

Ring-buffer log → data/airdrop_eligibility_log.json (cap 100).
Atomic writes: tmp + os.replace.

Pure stdlib. No external dependencies.
"""

import json
import os
import tempfile
import time
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))

LOG_PATH = os.path.join(_REPO_ROOT, "data", "airdrop_eligibility_log.json")
LOG_MAX_ENTRIES = 100

# Flag thresholds
OG_USER_DAYS_AGO: int = 365
POWER_USER_TX_MIN: int = 500
POWER_USER_VOL_MIN: float = 100_000.0
MULTI_CHAIN_MIN: int = 2
GOVERNANCE_VOTES_MIN: int = 1
SYBIL_TX_MAX: int = 10         # at most this many txs
SYBIL_DAYS_ACTIVE: int = 1     # only 1 active day → likely bot/farm wallet


# ---------------------------------------------------------------------------
# Pure helpers (importable for testing)
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp *value* to [lo, hi]."""
    return max(lo, min(hi, value))


def _eligibility_label(score: float) -> str:
    """Map score 0-100 → descriptive label."""
    if score >= 80:
        return "HIGHLY_ELIGIBLE"
    if score >= 60:
        return "ELIGIBLE"
    if score >= 40:
        return "PARTIAL"
    if score >= 20:
        return "LOW_CHANCE"
    return "INELIGIBLE"


def _compute_wallet_flags(wallet: dict) -> List[str]:
    """Return list of applicable flag strings for a wallet."""
    flags: List[str] = []

    earliest = wallet.get("earliest_interaction_days_ago", 0)
    tx = wallet.get("tx_count_total", 0)
    vol = wallet.get("volume_usd_total", 0.0)
    bridged = wallet.get("bridged_chains", [])
    votes = wallet.get("governance_votes_count", 0)
    days_active = wallet.get("unique_days_active", 0)

    if earliest >= OG_USER_DAYS_AGO:
        flags.append("OG_USER")
    if tx >= POWER_USER_TX_MIN and vol >= POWER_USER_VOL_MIN:
        flags.append("POWER_USER")
    if len(bridged) >= MULTI_CHAIN_MIN:
        flags.append("MULTI_CHAIN")
    if votes >= GOVERNANCE_VOTES_MIN:
        flags.append("GOVERNANCE_PARTICIPANT")
    if 0 < tx <= SYBIL_TX_MAX and days_active == SYBIL_DAYS_ACTIVE:
        flags.append("SYBIL_RISK")

    return flags


def _score_criterion(actual, required, weight: float = 20.0):
    """
    Return (score_contribution, met) where score_contribution ∈ [0, weight].
    Partial credit proportional to actual/required.
    """
    if required is None or required == 0:
        return weight, True
    if actual >= required:
        return weight, True
    ratio = actual / required
    return ratio * weight, False


def _compute_program_eligibility(wallet: dict, program: dict) -> dict:
    """
    Evaluate eligibility for a single airdrop program for one wallet.

    Supported criteria keys:
        min_tx_count, min_volume_usd, min_unique_days, required_protocols,
        min_governance_votes, min_chains_bridged, min_nft_count
    """
    name = program.get("name", "Unknown")
    criteria = program.get("criteria", {})
    token_price = program.get("token_price_usd", 1.0)
    base_allocation = program.get("base_allocation_tokens", 1000.0)

    score_parts: List[float] = []
    max_parts: List[float] = []
    missing: List[str] = []

    weight_each = 20.0  # each criterion is equally weighted at 20 pts max

    # 1. tx_count
    if "min_tx_count" in criteria:
        req = criteria["min_tx_count"]
        actual = wallet.get("tx_count_total", 0)
        pts, met = _score_criterion(actual, req, weight_each)
        score_parts.append(pts)
        max_parts.append(weight_each)
        if not met:
            missing.append(f"Need {req} txs (have {actual})")

    # 2. volume
    if "min_volume_usd" in criteria:
        req = criteria["min_volume_usd"]
        actual = wallet.get("volume_usd_total", 0.0)
        pts, met = _score_criterion(actual, req, weight_each)
        score_parts.append(pts)
        max_parts.append(weight_each)
        if not met:
            missing.append(
                f"Need ${req:,.0f} volume (have ${actual:,.0f})"
            )

    # 3. unique days
    if "min_unique_days" in criteria:
        req = criteria["min_unique_days"]
        actual = wallet.get("unique_days_active", 0)
        pts, met = _score_criterion(actual, req, weight_each)
        score_parts.append(pts)
        max_parts.append(weight_each)
        if not met:
            missing.append(
                f"Need {req} unique active days (have {actual})"
            )

    # 4. required protocols
    if "required_protocols" in criteria:
        req_set = set(criteria["required_protocols"])
        have_set = set(wallet.get("protocols_interacted", []))
        if req_set:
            overlap = req_set & have_set
            ratio = len(overlap) / len(req_set)
            pts = ratio * weight_each
            met = (ratio == 1.0)
        else:
            pts = weight_each
            met = True
        score_parts.append(pts)
        max_parts.append(weight_each)
        if not met:
            gap = req_set - have_set
            missing.append(f"Interact with: {', '.join(sorted(gap))}")

    # 5. governance votes
    if "min_governance_votes" in criteria:
        req = criteria["min_governance_votes"]
        actual = wallet.get("governance_votes_count", 0)
        pts, met = _score_criterion(actual, req, weight_each)
        score_parts.append(pts)
        max_parts.append(weight_each)
        if not met:
            missing.append(
                f"Need {req} governance votes (have {actual})"
            )

    # 6. chains bridged
    if "min_chains_bridged" in criteria:
        req = criteria["min_chains_bridged"]
        actual = len(wallet.get("bridged_chains", []))
        pts, met = _score_criterion(actual, req, weight_each)
        score_parts.append(pts)
        max_parts.append(weight_each)
        if not met:
            missing.append(f"Need {req} chains bridged (have {actual})")

    # 7. NFT count
    if "min_nft_count" in criteria:
        req = criteria["min_nft_count"]
        actual = wallet.get("nft_count", 0)
        pts, met = _score_criterion(actual, req, weight_each)
        score_parts.append(pts)
        max_parts.append(weight_each)
        if not met:
            missing.append(f"Need {req} NFTs (have {actual})")

    # Aggregate score
    total_max = sum(max_parts) if max_parts else 0.0
    if total_max > 0:
        raw = (sum(score_parts) / total_max) * 100.0
    else:
        # No criteria defined → fully eligible by default
        raw = 80.0

    score = _clamp(raw)

    # completion_pct = fraction of criteria fully met
    if max_parts:
        fully_met = sum(
            1 for s, m in zip(score_parts, max_parts) if s >= m
        )
        completion_pct = (fully_met / len(max_parts)) * 100.0
    else:
        completion_pct = 100.0

    # Token allocation — base × (score/100), with bonuses for power users
    token_multiplier = score / 100.0
    estimated_tokens = base_allocation * token_multiplier
    tx = wallet.get("tx_count_total", 0)
    vol = wallet.get("volume_usd_total", 0.0)
    if tx >= POWER_USER_TX_MIN:
        estimated_tokens *= 1.5
    if vol >= POWER_USER_VOL_MIN:
        estimated_tokens *= 1.2
    estimated_tokens = round(estimated_tokens, 2)
    estimated_usd = round(estimated_tokens * token_price, 2)

    return {
        "program": name,
        "token_symbol": program.get("token_symbol", "TKN"),
        "eligibility_score": round(score, 2),
        "opportunity_label": _eligibility_label(score),
        "estimated_tokens": estimated_tokens,
        "estimated_usd_value": estimated_usd,
        "completion_pct": round(completion_pct, 2),
        "missing_criteria": missing,
    }


def _compute_wallet_result(
    wallet: dict, programs: List[dict], config: dict
) -> dict:
    """Build the full per-wallet result dict."""
    address = wallet.get("address", "0x0")
    flags = _compute_wallet_flags(wallet)
    program_results = [_compute_program_eligibility(wallet, p) for p in programs]

    total_usd = sum(pr["estimated_usd_value"] for pr in program_results)

    top_opportunity: Optional[str] = None
    if program_results:
        best = max(program_results, key=lambda pr: pr["estimated_usd_value"])
        top_opportunity = best["program"]

    # Completion roadmap: deduplicated, sorted set of all missing criteria
    all_missing: List[str] = []
    for pr in program_results:
        all_missing.extend(pr["missing_criteria"])
    completion_roadmap = sorted(set(all_missing))

    return {
        "address": address,
        "flags": flags,
        "airdrop_programs": program_results,
        "total_estimated_usd": round(total_usd, 2),
        "top_opportunity": top_opportunity,
        "completion_roadmap": completion_roadmap,
    }


# ---------------------------------------------------------------------------
# Atomic ring-buffer log
# ---------------------------------------------------------------------------

def _atomic_log(
    entry: dict,
    log_path: str,
    max_entries: int = LOG_MAX_ENTRIES,
) -> None:
    """Append *entry* to ring-buffer JSON log. Atomic: tmp + os.replace."""
    try:
        log_dir = os.path.dirname(log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        existing: List[dict] = []
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
        existing.append(entry)
        if len(existing) > max_entries:
            existing = existing[-max_entries:]
        tmp_fd, tmp_path = tempfile.mkstemp(dir=log_dir or ".", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(existing, fh, indent=2)
            os.replace(tmp_path, log_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception:
        pass  # advisory module — log failures are non-fatal


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class ProtocolAirdropEligibilityOptimizer:
    """
    MP-933 — Advisory analytics for protocol airdrop eligibility.

    Usage::

        optimizer = ProtocolAirdropEligibilityOptimizer()
        result    = optimizer.optimize(wallets, config)

    config keys:
        airdrop_programs  – list of program dicts (see module header)
        write_log         – bool, default True
        log_path          – override default log path

    Each program dict supports:
        name, token_symbol, token_price_usd, base_allocation_tokens,
        criteria (dict with optional keys):
            min_tx_count, min_volume_usd, min_unique_days,
            required_protocols, min_governance_votes,
            min_chains_bridged, min_nft_count
    """

    def optimize(
        self, wallets: List[dict], config: Optional[dict] = None
    ) -> dict:
        if config is None:
            config = {}

        write_log = config.get("write_log", True)
        log_path = config.get("log_path", LOG_PATH)
        programs = config.get("airdrop_programs", [])

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if not wallets:
            result: dict = {
                "status": "ok",
                "wallets_analyzed": 0,
                "wallets": [],
                "programs_evaluated": len(programs),
                "timestamp": timestamp,
            }
            if write_log:
                _atomic_log(result, log_path)
            return result

        wallet_results = [
            _compute_wallet_result(w, programs, config) for w in wallets
        ]

        result = {
            "status": "ok",
            "wallets_analyzed": len(wallet_results),
            "wallets": wallet_results,
            "programs_evaluated": len(programs),
            "timestamp": timestamp,
        }

        if write_log:
            _atomic_log(result, log_path)

        return result
