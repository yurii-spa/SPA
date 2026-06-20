"""
MP-775: VaultShareTracker
==========================
Tracks vault share price evolution and dilution events.

Inputs (per vault)::

    {
        "vault_id":           str,
        "share_price_history": [float],   # daily prices, oldest → newest
        "deposit_events":     [{"timestamp": str, "shares_minted": float, "usd_value": float}],
        "total_assets":       float,      # optional — for NAV calc
        "total_shares":       float,      # optional — for NAV calc
    }

Computes:
  share_price_change_7d_pct   — 7-day price change %
  share_price_change_30d_pct  — 30-day price change %
  dilution_events             — mint events where share price dropped >2% after
  dilution_risk               — LOW (0 events) / MEDIUM (1-2) / HIGH (3+)
  nav_per_share               — total_assets / total_shares  (when both supplied)
  vault_apy_from_share_price  — annualised APY derived from share price series

Ring buffer log: data/vault_share_log.json (max 100 entries, atomic write).

Pure stdlib, read-only/advisory domain, exit-0 always.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DILUTION_RISK_LOW: str = "LOW"
DILUTION_RISK_MEDIUM: str = "MEDIUM"
DILUTION_RISK_HIGH: str = "HIGH"

DILUTION_DROP_THRESHOLD_PCT: float = 2.0  # >2 % drop after a mint = dilution

LOG_MAX_ENTRIES: int = 100

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
DEFAULT_LOG_PATH: str = os.path.join(_PROJECT_ROOT, "data", "vault_share_log.json")


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: Any) -> None:
    """Write *data* as JSON to *path* atomically via tmp + os.replace."""
    dirpath = os.path.dirname(path)
    if dirpath and not os.path.exists(dirpath):
        os.makedirs(dirpath, exist_ok=True)
    atomic_save(data, str(path))
def _load_log(path: str) -> List[Dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# Pure helper functions (importable for tests)
# ---------------------------------------------------------------------------

def compute_price_change_pct(prices: List[float], days: int) -> Optional[float]:
    """Return price-change % over *days* calendar days.

    *prices* is a chronological (oldest→newest) list of daily share prices.
    If fewer than days+1 prices are available the full available window is used.
    Returns None when the list has fewer than 2 elements.
    """
    n = len(prices)
    if n < 2:
        return None
    if n >= days + 1:
        start = prices[-(days + 1)]
        end = prices[-1]
    else:
        start = prices[0]
        end = prices[-1]
    if start == 0:
        return None
    return round((end - start) / start * 100.0, 6)


def detect_dilution_events(
    share_price_history: List[float],
    deposit_events: List[Dict],
) -> List[Dict]:
    """Detect dilution events: share price drops >2 % after a large mint.

    Each deposit_event is mapped to the price slot at index i+1 in
    *share_price_history* (the price snapshot just after that mint).
    The slot at index i is the price just before.

    Returns a list of dilution-event dicts with:
      timestamp, shares_minted, usd_value,
      price_before, price_after, drop_pct
    """
    n = len(share_price_history)
    if n < 2:
        return []

    dilution_events: List[Dict] = []
    for i, event in enumerate(deposit_events):
        # position of "after-mint" price in history
        pos = min(i + 1, n - 1)
        prev_pos = pos - 1
        if prev_pos < 0:
            continue

        price_before = share_price_history[prev_pos]
        price_after = share_price_history[pos]

        if price_before == 0:
            continue

        drop_pct = (price_before - price_after) / price_before * 100.0
        if drop_pct > DILUTION_DROP_THRESHOLD_PCT:
            dilution_events.append({
                "timestamp": event.get("timestamp", ""),
                "shares_minted": event.get("shares_minted", 0),
                "usd_value": event.get("usd_value", 0),
                "price_before": price_before,
                "price_after": price_after,
                "drop_pct": round(drop_pct, 6),
            })

    return dilution_events


def compute_dilution_risk(dilution_count: int) -> str:
    """Map dilution event count → risk label.

    LOW    = 0 events
    MEDIUM = 1-2 events
    HIGH   = 3+ events
    """
    if dilution_count == 0:
        return DILUTION_RISK_LOW
    if dilution_count <= 2:
        return DILUTION_RISK_MEDIUM
    return DILUTION_RISK_HIGH


def compute_nav_per_share(total_assets: float, total_shares: float) -> Optional[float]:
    """Return NAV per share; None when total_shares == 0."""
    if total_shares == 0:
        return None
    return round(total_assets / total_shares, 8)


def compute_vault_apy_from_share_price(
    share_price_history: List[float],
    days_per_period: int = 1,
) -> Optional[float]:
    """Annualise APY from a share price time series.

    Assumes each element represents *days_per_period* calendar days.
    Returns None when fewer than 2 data points or when start price <= 0.
    Returns a negative float for shrinking vaults (still a valid APY).
    """
    n = len(share_price_history)
    if n < 2:
        return None
    start = share_price_history[0]
    end = share_price_history[-1]
    if start <= 0:
        return None
    n_periods = n - 1
    total_days = n_periods * days_per_period
    if total_days <= 0:
        return None
    ratio = end / start
    if ratio <= 0:
        return None
    apy = (ratio ** (365.0 / total_days) - 1.0) * 100.0
    return round(apy, 6)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class VaultShareTracker:
    """MP-775 — tracks vault share price evolution and dilution risk.

    Usage::

        tracker = VaultShareTracker()
        result = tracker.track({
            "vault_id": "yearn-usdc-v3",
            "share_price_history": [1.000, 1.001, 1.002, ...],
            "deposit_events": [
                {"timestamp": "2026-06-01T00:00:00+00:00",
                 "shares_minted": 10000, "usd_value": 10050},
            ],
            "total_assets": 5_000_000,
            "total_shares": 4_975_000,
        })
        print(tracker.get_dilution_events())
        print(tracker.get_vault_apy())
    """

    def __init__(self, log_path: Optional[str] = None) -> None:
        self.log_path: str = log_path or DEFAULT_LOG_PATH
        self._results: List[Dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def track(self, vault_data: Dict) -> Dict:
        """Compute all metrics for a single vault and append to log.

        Returns a result dict with:
          timestamp, vault_id,
          share_price_change_7d_pct, share_price_change_30d_pct,
          dilution_events, dilution_event_count, dilution_risk,
          nav_per_share, vault_apy_from_share_price, history_length
        """
        ts = datetime.now(timezone.utc).isoformat()
        vault_id = str(vault_data.get("vault_id", "unknown"))
        history: List[float] = [float(p) for p in vault_data.get("share_price_history", [])]
        deposit_events: List[Dict] = vault_data.get("deposit_events", [])

        raw_assets = vault_data.get("total_assets")
        raw_shares = vault_data.get("total_shares")

        change_7d = compute_price_change_pct(history, 7)
        change_30d = compute_price_change_pct(history, 30)
        dil_events = detect_dilution_events(history, deposit_events)
        dil_risk = compute_dilution_risk(len(dil_events))

        nav = None
        if raw_assets is not None and raw_shares is not None:
            nav = compute_nav_per_share(float(raw_assets), float(raw_shares))

        apy = compute_vault_apy_from_share_price(history)

        result: Dict = {
            "timestamp": ts,
            "vault_id": vault_id,
            "share_price_change_7d_pct": change_7d,
            "share_price_change_30d_pct": change_30d,
            "dilution_events": dil_events,
            "dilution_event_count": len(dil_events),
            "dilution_risk": dil_risk,
            "nav_per_share": nav,
            "vault_apy_from_share_price": apy,
            "history_length": len(history),
        }

        self._results.append(result)
        self._append_to_log([result])
        return result

    def get_dilution_events(self) -> List[Dict]:
        """Return dilution events from the most recently tracked vault."""
        if not self._results:
            return []
        return self._results[-1].get("dilution_events", [])

    def get_vault_apy(self) -> Optional[float]:
        """Return annualised APY from the most recently tracked vault."""
        if not self._results:
            return None
        return self._results[-1].get("vault_apy_from_share_price")

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _append_to_log(self, results: List[Dict]) -> None:
        log = _load_log(self.log_path)
        log.extend(results)
        if len(log) > LOG_MAX_ENTRIES:
            log = log[-LOG_MAX_ENTRIES:]
        _atomic_write(self.log_path, log)
