"""
MP-795: ProtocolRevenueShareAnalyzer
Analyzes how protocol revenue is distributed to token holders vs treasury vs team.
Ring-buffer log capped 100, atomic write. Pure stdlib.
"""

import json
import os
import time
import tempfile
from typing import Optional

# ── constants ──────────────────────────────────────────────────────────────────

_LOG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "protocol_revenue_share_log.json"
)
_LOG_FILE = os.path.normpath(_LOG_FILE)
_RING_CAP = 100

DISTRIBUTION_HOLDER_FRIENDLY = "HOLDER_FRIENDLY"
DISTRIBUTION_BALANCED = "BALANCED"
DISTRIBUTION_TREASURY_HEAVY = "TREASURY_HEAVY"
DISTRIBUTION_TEAM_HEAVY = "TEAM_HEAVY"


# ── helpers ────────────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _atomic_write(path: str, data) -> None:
    """Write JSON atomically via tmp + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tmp", dir=os.path.dirname(path), delete=False
    ) as fh:
        tmp = fh.name
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def _load_log(path: str) -> list:
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# ── main class ─────────────────────────────────────────────────────────────────

class ProtocolRevenueShareAnalyzer:
    """
    Analyzes revenue distribution across protocol stakeholders.

    Parameters
    ----------
    log_path : str, optional
        Override path to the ring-buffer log file.
    """

    def __init__(self, log_path: Optional[str] = None):
        self._log_path = log_path or _LOG_FILE
        self._last_result: Optional[dict] = None

    # ── public API ─────────────────────────────────────────────────────────────

    def analyze(self, revenue_data: dict) -> dict:
        """
        Compute all metrics for one protocol revenue snapshot.

        Parameters
        ----------
        revenue_data : dict
            Keys:
              protocol              str
              total_revenue_usd_annual  float  ≥ 0
              revenue_to_holders_pct    float  0–100
              revenue_to_treasury_pct   float  0–100
              revenue_to_team_pct       float  0–100
              buyback_pct               float  0–100
              token_holders_count       int    ≥ 1

        Returns
        -------
        dict  with all computed fields plus raw inputs.
        """
        # ── validate / extract ────────────────────────────────────────────────
        protocol = str(revenue_data.get("protocol", "unknown"))
        total_rev = float(revenue_data.get("total_revenue_usd_annual", 0.0))
        holders_pct = float(revenue_data.get("revenue_to_holders_pct", 0.0))
        treasury_pct = float(revenue_data.get("revenue_to_treasury_pct", 0.0))
        team_pct = float(revenue_data.get("revenue_to_team_pct", 0.0))
        buyback_pct = float(revenue_data.get("buyback_pct", 0.0))
        holders_count = max(1, int(revenue_data.get("token_holders_count", 1)))

        # ── holder_yield_usd (per-holder average) ─────────────────────────────
        holder_yield_usd = (total_rev * holders_pct / 100.0) / holders_count

        # ── revenue_sustainability_score ──────────────────────────────────────
        sustainability_score = self._compute_sustainability_score(
            team_pct, buyback_pct, holders_pct
        )

        # ── distribution_fairness ─────────────────────────────────────────────
        distribution_fairness = self.get_distribution_fairness(
            holders_pct, treasury_pct, team_pct
        )

        # ── value_accrual_score ───────────────────────────────────────────────
        value_accrual_score = self.get_value_accrual_score(buyback_pct, holders_pct)

        # ── assemble result ───────────────────────────────────────────────────
        result = {
            "protocol": protocol,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            # inputs (stored for auditability)
            "total_revenue_usd_annual": total_rev,
            "revenue_to_holders_pct": holders_pct,
            "revenue_to_treasury_pct": treasury_pct,
            "revenue_to_team_pct": team_pct,
            "buyback_pct": buyback_pct,
            "token_holders_count": holders_count,
            # computed
            "holder_yield_usd": round(holder_yield_usd, 6),
            "revenue_sustainability_score": sustainability_score,
            "distribution_fairness": distribution_fairness,
            "value_accrual_score": value_accrual_score,
        }

        self._last_result = result
        self._append_log(result)
        return result

    def get_distribution_fairness(
        self,
        holders_pct: float,
        treasury_pct: float,
        team_pct: float,
    ) -> str:
        """
        Classify revenue distribution.

        Rules (evaluated in priority order):
        1. TEAM_HEAVY   – team_pct > 30
        2. TREASURY_HEAVY – treasury_pct > 50
        3. HOLDER_FRIENDLY – holders_pct > 50
        4. BALANCED     – holders_pct in [30, 50]
        """
        if team_pct > 30.0:
            return DISTRIBUTION_TEAM_HEAVY
        if treasury_pct > 50.0:
            return DISTRIBUTION_TREASURY_HEAVY
        if holders_pct > 50.0:
            return DISTRIBUTION_HOLDER_FRIENDLY
        return DISTRIBUTION_BALANCED

    def get_value_accrual_score(
        self,
        buyback_pct: float,
        holders_pct: float,
    ) -> float:
        """
        Compute 0–100 score from buyback and holder revenue combined.

        Formula:
          buyback_component  = clamp(buyback_pct, 0, 50) * 1.0
              → max 50 points if buyback >= 50 %
          holder_component   = clamp(holders_pct, 0, 50) * 1.0
              → max 50 points if holders_pct >= 50 %
          score = buyback_component + holder_component  (already 0–100)
        """
        buyback_component = _clamp(buyback_pct, 0.0, 50.0)
        holder_component = _clamp(holders_pct, 0.0, 50.0)
        score = _clamp(buyback_component + holder_component)
        return round(score, 2)

    # ── private helpers ────────────────────────────────────────────────────────

    def _compute_sustainability_score(
        self,
        team_pct: float,
        buyback_pct: float,
        holders_pct: float,
    ) -> float:
        """
        0–100 composite sustainability score.

        Components:
          team_score     = 40 if team_pct < 20 else max(0, 40 - (team_pct - 20) * 2)
          buyback_score  = 30 if buyback_pct > 0 else 0
                           (bonus: up to 30 extra based on buyback_pct magnitude)
          holders_score  = 30 if holders_pct > 50 else holders_pct / 50 * 30
        """
        # team component (max 40)
        if team_pct < 20.0:
            team_score = 40.0
        else:
            team_score = max(0.0, 40.0 - (team_pct - 20.0) * 2.0)

        # buyback component (max 30)
        if buyback_pct > 0:
            buyback_score = min(30.0, 10.0 + buyback_pct * 0.4)
        else:
            buyback_score = 0.0

        # holders component (max 30)
        if holders_pct > 50.0:
            holders_score = 30.0
        else:
            holders_score = (holders_pct / 50.0) * 30.0

        total = team_score + buyback_score + holders_score
        return round(_clamp(total), 2)

    def _append_log(self, entry: dict) -> None:
        """Append entry to ring-buffer log (cap = 100), atomic write."""
        log = _load_log(self._log_path)
        log.append(entry)
        if len(log) > _RING_CAP:
            log = log[-_RING_CAP:]
        _atomic_write(self._log_path, log)
