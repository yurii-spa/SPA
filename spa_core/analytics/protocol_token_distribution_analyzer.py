"""
MP-975 ProtocolTokenDistributionAnalyzer
==========================================
Advisory-only, read-only analytics module.
Analyzes token distributions across stakeholder categories for DeFi protocols,
assessing insider concentration, vesting schedules, upcoming unlocks, and
community alignment.

Input token fields:
    name, protocol
    allocations: list of dicts with:
        category          team | investors | community | treasury |
                          ecosystem | public_sale | liquidity
        pct_total         % of total supply in this allocation
        vesting_months    total vesting schedule in months
        cliff_months      cliff before any vesting starts
        already_vested_pct  % of this allocation already vested (0-100)
    total_supply          numeric (informational)
    circulating_supply    numeric (informational)
    token_age_months      age of the token in months

Computed per token:
    team_plus_investor_pct       sum of team + investors category pct_total
    community_pct                sum of community + ecosystem + public_sale pct_total
    insider_lock_remaining_months  max remaining vesting months among team/investor allocs
    gini_coefficient             Gini of pct_total distribution (0=equal, 1=concentrated)
    upcoming_unlock_6m_pct       % of total supply unlocking in next 6 months

Labels (first match wins):
    COMMUNITY_FIRST     community_pct > 60
    INSIDER_DOMINATED   team_plus_investor_pct > 60
    INVESTOR_HEAVY      investor_pct > 30
    TEAM_HEAVY          team_pct > 25
    BALANCED            none of the above

Flags:
    HIGH_INSIDER_PCT       team_plus_investor_pct > 50
    IMMINENT_LARGE_UNLOCK  upcoming_unlock_6m_pct > 10
    VESTING_COMPLETE       all allocations already_vested_pct == 100
    FAIR_LAUNCH            no team or investor allocations present
    LONG_VESTING           max vesting_months among any allocation > 48

Aggregates:
    most_community_aligned    token name with highest community_pct
    most_insider_heavy        token name with highest team_plus_investor_pct
    average_community_pct     mean community_pct across all tokens
    community_first_count     count of COMMUNITY_FIRST tokens
    insider_dominated_count   count of INSIDER_DOMINATED tokens

Ring-buffer log → data/token_distribution_log.json (cap 100, atomic write)
Pure stdlib only. No external dependencies.
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Any, Dict, List, Optional

# ── Constants ─────────────────────────────────────────────────────────────────
_RING_CAP = 100
_LOG_FILENAME = "token_distribution_log.json"

_COMMUNITY_CATEGORIES = {"community", "ecosystem", "public_sale"}
_INSIDER_CATEGORIES = {"team", "investors"}

_COMMUNITY_FIRST_THRESHOLD = 60.0    # community_pct >
_INSIDER_DOMINATED_THRESHOLD = 60.0  # team+investor >
_INVESTOR_HEAVY_THRESHOLD = 30.0     # investor only >
_TEAM_HEAVY_THRESHOLD = 25.0         # team only >

_HIGH_INSIDER_THRESHOLD = 50.0       # team+investor > → HIGH_INSIDER_PCT flag
_LARGE_UNLOCK_THRESHOLD = 10.0       # upcoming_unlock > → IMMINENT_LARGE_UNLOCK flag
_LONG_VESTING_MONTHS = 48            # max vesting > → LONG_VESTING flag
_FORECAST_WINDOW_MONTHS = 6          # upcoming unlock window


# ── Gini coefficient ──────────────────────────────────────────────────────────

def _gini_coefficient(values: List[float]) -> float:
    """
    Compute Gini coefficient for a list of non-negative values.
    Returns 0.0 for uniform / single-value distributions.
    Uses O(n²) sum-of-absolute-differences formula.
    """
    n = len(values)
    if n == 0:
        return 0.0
    total = sum(values)
    if total == 0.0:
        return 0.0
    diff_sum = sum(
        abs(values[i] - values[j])
        for i in range(n)
        for j in range(n)
    )
    return round(diff_sum / (2.0 * n * total), 6)


# ── Upcoming unlock calculation ───────────────────────────────────────────────

def _upcoming_unlock_6m(alloc: Dict, token_age_months: float) -> float:
    """
    Estimate what % of total supply from this allocation unlocks in the next
    6 months, given the current token age.

    Logic:
    - remaining_pct = alloc_pct_total × (1 − already_vested_pct/100)
    - If vesting is complete (already_vested_pct == 100): return 0
    - If vesting_months == 0: everything unlocked at TGE; already handled by vested_pct
    - If cliff has not been crossed AND won't be in 6 months: return 0
    - Otherwise compute fraction vesting within [now, now+6] months
    """
    pct_total = float(alloc.get("pct_total", 0.0))
    already_vested = float(alloc.get("already_vested_pct", 0.0))
    vesting_months = float(alloc.get("vesting_months", 0.0))
    cliff_months = float(alloc.get("cliff_months", 0.0))

    if pct_total <= 0.0 or already_vested >= 100.0:
        return 0.0

    remaining_pct = pct_total * (1.0 - already_vested / 100.0)

    if vesting_months <= 0.0:
        # No vesting schedule → all unlocked at TGE (treat as fully vested)
        return 0.0

    # How far along the vesting schedule is the token?
    age = float(token_age_months)

    # Cliff check: if cliff hasn't started by end of window, nothing unlocks
    if cliff_months > 0.0 and (age + _FORECAST_WINDOW_MONTHS) <= cliff_months:
        return 0.0

    # Months remaining in the vesting schedule from now
    vesting_end = vesting_months
    months_remaining = max(0.0, vesting_end - age)

    if months_remaining <= 0.0:
        # Vesting already ended (but already_vested_pct < 100 ─ edge case)
        return 0.0

    # Months of vesting falling within the 6-month window
    months_in_window = min(_FORECAST_WINDOW_MONTHS, months_remaining)

    # Linear rate: remaining_pct unlocks linearly over months_remaining
    rate_per_month = remaining_pct / months_remaining
    return months_in_window * rate_per_month


# ── Atomic write helper ───────────────────────────────────────────────────────

def _atomic_write(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


# ── Ring-buffer log ───────────────────────────────────────────────────────────

def _append_log(entry: dict, data_dir: str, cap: int) -> None:
    log_path = os.path.join(data_dir, _LOG_FILENAME)
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            log: list = json.load(f)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []
    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]
    _atomic_write(log_path, log)


# ── Main class ────────────────────────────────────────────────────────────────

class ProtocolTokenDistributionAnalyzer:
    """
    Analyzes token distribution for DeFi protocol governance tokens.

    Usage::

        analyzer = ProtocolTokenDistributionAnalyzer()
        result = analyzer.analyze(tokens, config)
    """

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        tokens: List[Dict],
        config: Optional[Dict] = None,
    ) -> Dict:
        """
        Analyze token distributions for all provided tokens.

        Parameters
        ----------
        tokens:
            List of token dicts (see module docstring for fields).
        config:
            Optional configuration overrides:
                data_dir   (str)  Directory for log output. Default: ``"data"``.
                log_cap    (int)  Ring-buffer size. Default: 100.
                write_log  (bool) Whether to persist the log. Default: True.

        Returns
        -------
        dict with keys ``timestamp``, ``tokens`` (list of per-token results),
        ``aggregates``.
        """
        if config is None:
            config = {}

        data_dir = str(config.get("data_dir", "data"))
        log_cap = int(config.get("log_cap", _RING_CAP))
        write_log = bool(config.get("write_log", True))

        token_results = [self._analyze_token(t) for t in tokens]
        aggregates = self._compute_aggregates(token_results)

        output: Dict = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "tokens": token_results,
            "aggregates": aggregates,
        }

        if write_log:
            _append_log(output, data_dir, log_cap)

        return output

    # ── Per-token computation ─────────────────────────────────────────────────

    def _analyze_token(self, t: Dict) -> Dict:
        name = str(t.get("name", "unknown"))
        protocol = str(t.get("protocol", "unknown"))
        token_age = float(t.get("token_age_months", 0.0))
        allocations: List[Dict] = t.get("allocations", [])

        # Category sums
        team_pct = 0.0
        investor_pct = 0.0
        community_sum = 0.0
        all_pcts: List[float] = []

        max_vesting = 0.0
        insider_remaining_list: List[float] = []
        has_team = False
        has_investor = False
        all_vested = True  # assume true until proven otherwise

        for alloc in allocations:
            cat = str(alloc.get("category", "")).lower()
            pct = float(alloc.get("pct_total", 0.0))
            vesting = float(alloc.get("vesting_months", 0.0))
            already = float(alloc.get("already_vested_pct", 0.0))

            all_pcts.append(pct)

            if vesting > max_vesting:
                max_vesting = vesting

            if already < 100.0:
                all_vested = False

            if cat == "team":
                team_pct += pct
                has_team = True
                remaining = vesting * (1.0 - already / 100.0)
                insider_remaining_list.append(remaining)

            elif cat == "investors":
                investor_pct += pct
                has_investor = True
                remaining = vesting * (1.0 - already / 100.0)
                insider_remaining_list.append(remaining)

            elif cat in _COMMUNITY_CATEGORIES:
                community_sum += pct

        team_plus_investor_pct = team_pct + investor_pct
        insider_lock_remaining = (
            max(insider_remaining_list) if insider_remaining_list else 0.0
        )

        # Gini across all allocation pct_total values
        gini = _gini_coefficient(all_pcts)

        # Upcoming unlock in 6 months
        upcoming_unlock = sum(
            _upcoming_unlock_6m(alloc, token_age) for alloc in allocations
        )
        upcoming_unlock = round(min(upcoming_unlock, 100.0), 6)

        # Distribution label
        label = self._distribution_label(community_sum, team_plus_investor_pct, investor_pct, team_pct)

        # Flags
        flags: List[str] = []
        if team_plus_investor_pct > _HIGH_INSIDER_THRESHOLD:
            flags.append("HIGH_INSIDER_PCT")
        if upcoming_unlock > _LARGE_UNLOCK_THRESHOLD:
            flags.append("IMMINENT_LARGE_UNLOCK")
        if len(allocations) > 0 and all_vested:
            flags.append("VESTING_COMPLETE")
        if not has_team and not has_investor:
            flags.append("FAIR_LAUNCH")
        if max_vesting > _LONG_VESTING_MONTHS:
            flags.append("LONG_VESTING")

        return {
            "name": name,
            "protocol": protocol,
            "team_plus_investor_pct": round(team_plus_investor_pct, 6),
            "community_pct": round(community_sum, 6),
            "insider_lock_remaining_months": round(insider_lock_remaining, 4),
            "gini_coefficient": gini,
            "upcoming_unlock_6m_pct": upcoming_unlock,
            "distribution_label": label,
            "flags": flags,
        }

    @staticmethod
    def _distribution_label(
        community_pct: float,
        team_plus_investor_pct: float,
        investor_pct: float,
        team_pct: float,
    ) -> str:
        """
        Assign a distribution label. Priority (first match):
        1. COMMUNITY_FIRST      community_pct > 60
        2. INSIDER_DOMINATED    team+investor > 60
        3. INVESTOR_HEAVY       investor_pct > 30
        4. TEAM_HEAVY           team_pct > 25
        5. BALANCED             (default)
        """
        if community_pct > _COMMUNITY_FIRST_THRESHOLD:
            return "COMMUNITY_FIRST"
        if team_plus_investor_pct > _INSIDER_DOMINATED_THRESHOLD:
            return "INSIDER_DOMINATED"
        if investor_pct > _INVESTOR_HEAVY_THRESHOLD:
            return "INVESTOR_HEAVY"
        if team_pct > _TEAM_HEAVY_THRESHOLD:
            return "TEAM_HEAVY"
        return "BALANCED"

    # ── Aggregates ────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_aggregates(results: List[Dict]) -> Dict:
        if not results:
            return {
                "most_community_aligned": None,
                "most_insider_heavy": None,
                "average_community_pct": 0.0,
                "community_first_count": 0,
                "insider_dominated_count": 0,
            }

        most_community = max(results, key=lambda r: r["community_pct"])
        most_insider = max(results, key=lambda r: r["team_plus_investor_pct"])
        avg_community = sum(r["community_pct"] for r in results) / len(results)
        comm_first = sum(1 for r in results if r["distribution_label"] == "COMMUNITY_FIRST")
        insider_dom = sum(1 for r in results if r["distribution_label"] == "INSIDER_DOMINATED")

        return {
            "most_community_aligned": most_community["name"],
            "most_insider_heavy": most_insider["name"],
            "average_community_pct": round(avg_community, 6),
            "community_first_count": comm_first,
            "insider_dominated_count": insider_dom,
        }
