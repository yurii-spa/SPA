"""
MP-789: ProtocolAdoptionScorer
Scores protocol user adoption velocity and stickiness.
Pure stdlib, read-only analytics, atomic write, ring-buffer log (cap 100).
"""

import json
import os
import time
from typing import Any, Dict, List, Optional

from spa_core.utils.errors import SPAError

RING_BUFFER_CAP = 100
_DEFAULT_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "protocol_adoption_log.json"
)


class ProtocolAdoptionScorer:
    """
    Computes adoption velocity and stickiness score for a DeFi protocol.

    Inputs (protocol_data dict):
      - protocol            : str
      - unique_users_30d    : int/float  — unique users last 30 days
      - unique_users_90d    : int/float  — unique users last 90 days
      - txn_count_30d       : int/float  — transaction count last 30 days
      - tvl_usd             : float      — current TVL
      - tvl_3m_ago_usd      : float      — TVL 3 months ago
      - retention_rate_pct  : float      — retention rate 0-100

    Derived metrics:
      - user_growth_pct     = (users_30d - users_90d/3) / (users_90d/3) * 100
      - tvl_growth_pct      = (tvl - tvl_3m_ago) / tvl_3m_ago * 100
      - engagement_score    = txn_count_30d / unique_users_30d
      - adoption_score      : 0-100 composite
          user_growth 40% + tvl_growth 30% + retention 20% + engagement 10%
      - adoption_tier       : VIRAL (>80) | GROWING (>60) | STEADY (>40) | STAGNANT (≤40)
    """

    def __init__(self, log_path: Optional[str] = None) -> None:
        self.log_path: str = log_path or os.path.normpath(_DEFAULT_LOG)
        self._result: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, protocol_data: Dict[str, Any]) -> Dict[str, Any]:
        """Compute adoption score. Returns result dict and appends to ring-buffer log."""
        protocol: str = protocol_data["protocol"]
        unique_users_30d: float = float(protocol_data["unique_users_30d"])
        unique_users_90d: float = float(protocol_data["unique_users_90d"])
        txn_count_30d: float = float(protocol_data["txn_count_30d"])
        tvl_usd: float = float(protocol_data["tvl_usd"])
        tvl_3m_ago_usd: float = float(protocol_data["tvl_3m_ago_usd"])
        retention_rate_pct: float = float(protocol_data["retention_rate_pct"])

        # ── user_growth_pct ────────────────────────────────────────────
        monthly_base = unique_users_90d / 3.0 if unique_users_90d > 0 else 0.0
        if monthly_base > 0:
            user_growth_pct = (unique_users_30d - monthly_base) / monthly_base * 100.0
        else:
            user_growth_pct = 0.0

        # ── tvl_growth_pct ─────────────────────────────────────────────
        if tvl_3m_ago_usd > 0:
            tvl_growth_pct = (tvl_usd - tvl_3m_ago_usd) / tvl_3m_ago_usd * 100.0
        else:
            tvl_growth_pct = 0.0

        # ── engagement_score (txns per user) ──────────────────────────
        if unique_users_30d > 0:
            engagement_score = txn_count_30d / unique_users_30d
        else:
            engagement_score = 0.0

        # ── normalise each component to [0, 100] ──────────────────────
        # user_growth: [-100, +200] → [0, 100]  (shift+scale: /3 of shifted)
        user_growth_norm = max(0.0, min(100.0, (user_growth_pct + 100.0) / 3.0))

        # tvl_growth:  [-100, +200] → [0, 100]
        tvl_growth_norm = max(0.0, min(100.0, (tvl_growth_pct + 100.0) / 3.0))

        # retention: already 0-100
        retention_norm = max(0.0, min(100.0, retention_rate_pct))

        # engagement: [0, 50] → [0, 100]  (×2, cap at 100)
        engagement_norm = max(0.0, min(100.0, engagement_score * 2.0))

        # ── composite adoption_score ───────────────────────────────────
        adoption_score = (
            user_growth_norm * 0.40
            + tvl_growth_norm * 0.30
            + retention_norm * 0.20
            + engagement_norm * 0.10
        )
        adoption_score = round(min(100.0, max(0.0, adoption_score)), 4)

        # ── adoption_tier ──────────────────────────────────────────────
        adoption_tier = self._compute_tier(adoption_score)

        growth_breakdown: Dict[str, Any] = {
            "user_growth_norm": round(user_growth_norm, 4),
            "tvl_growth_norm": round(tvl_growth_norm, 4),
            "retention_norm": round(retention_norm, 4),
            "engagement_norm": round(engagement_norm, 4),
            "weights": {
                "user_growth": 0.40,
                "tvl_growth": 0.30,
                "retention": 0.20,
                "engagement": 0.10,
            },
        }

        result: Dict[str, Any] = {
            "protocol": protocol,
            "unique_users_30d": unique_users_30d,
            "unique_users_90d": unique_users_90d,
            "txn_count_30d": txn_count_30d,
            "tvl_usd": tvl_usd,
            "tvl_3m_ago_usd": tvl_3m_ago_usd,
            "retention_rate_pct": retention_rate_pct,
            "user_growth_pct": round(user_growth_pct, 6),
            "tvl_growth_pct": round(tvl_growth_pct, 6),
            "engagement_score": round(engagement_score, 6),
            "adoption_score": adoption_score,
            "adoption_tier": adoption_tier,
            "growth_breakdown": growth_breakdown,
            "timestamp": int(time.time()),
        }

        self._result = result
        self._append_log(result)
        return result

    def get_adoption_tier(self) -> str:
        """Return adoption_tier from last score() call."""
        if self._result is None:
            raise SPAError("Call score() before get_adoption_tier()", code="NOT_INITIALIZED")
        return self._result["adoption_tier"]

    def get_growth_breakdown(self) -> Dict[str, Any]:
        """Return growth_breakdown dict from last score() call."""
        if self._result is None:
            raise SPAError("Call score() before get_growth_breakdown()", code="NOT_INITIALIZED")
        return self._result["growth_breakdown"]

    def get_last_result(self) -> Optional[Dict[str, Any]]:
        """Return full result dict from the last score() call, or None."""
        return self._result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_tier(score: float) -> str:
        if score > 80:
            return "VIRAL"
        if score > 60:
            return "GROWING"
        if score > 40:
            return "STEADY"
        return "STAGNANT"

    def _append_log(self, entry: Dict[str, Any]) -> None:
        log = self._read_log()
        log.append(entry)
        if len(log) > RING_BUFFER_CAP:
            log = log[-RING_BUFFER_CAP:]
        self._write_log(log)

    def _read_log(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.log_path):
            try:
                with open(self.log_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        return data
            except (json.JSONDecodeError, OSError):
                pass
        return []

    def _write_log(self, log: List[Dict[str, Any]]) -> None:
        log_dir = os.path.dirname(self.log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        tmp = self.log_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp, self.log_path)
