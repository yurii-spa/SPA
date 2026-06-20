"""Protocol Registry — MP-583.

Centralised security metadata store for DeFi protocols used by SPA.

Computes four derived signals per protocol:

    audit_score      [0..100]  — weighted by audit count, recency, firm tier
    hack_risk_flag   bool      — True if any hack within the last 2 years
    age_score        [0..100]  — proxy for protocol maturity
    tvl_score        [0..100]  — absolute liquidity cushion
    safety_score     [0..100]  — 60% audit + 20% age + 20% tvl

Pre-populated for 15 protocols: aave, morpho, spark, compound, euler,
maple, pendle, sky, yearn, frax, sdai, sfrax, stusd, scrvusd, wusdm.

Design constraints
------------------
* **Stdlib only** — no numpy, requests, web3, pandas, scipy, openai, anthropic.
* **Pure advisory** — never touches allocator / risk / execution domains.
* **Read-only imports** — no execution/, monitoring/, feed_health/ imports.
* **Atomic writes** — tmp + os.replace on every JSON save.
* **LLM_FORBIDDEN** — deterministic arithmetic only; no AI/LLM calls.

Usage
-----
::

    from spa_core.analytics.protocol_registry import ProtocolRegistry

    reg = ProtocolRegistry()
    score = reg.compute_safety_score("aave")   # → 85.4
    flag  = reg.get_hack_risk_flag("euler")    # → False (hack > 2y ago)
    report = reg.get_registry_report()
    reg.save_registry()
    reg.load_registry()

CLI::

    python3 -m spa_core.analytics.protocol_registry --check
    python3 -m spa_core.analytics.protocol_registry --run
    python3 -m spa_core.analytics.protocol_registry --run --data-dir data
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.analytics.protocol_registry")

# ─────────────────────────────────────────────────────────────────────────────
# Module-level constants
# ─────────────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DATA_DIR = str(_REPO_ROOT / "data")
REGISTRY_FILENAME = "protocol_registry.json"

# Audit firm reputation tiers ─────────────────────────────────────────────────
_FIRMS_TOP: frozenset = frozenset({
    "trail of bits",
    "openzeppelin",
    "chainsecurity",
    "consensys diligence",
    "abdk",
    "spearbit",
    "cantina",
    "zellic",
})

_FIRMS_MID: frozenset = frozenset({
    "certik",
    "sigma prime",
    "quantstamp",
    "peckshield",
    "hacken",
    "mixbytes",
    "halborn",
    "ackee",
    "code4rena",
    "sherlock",
    "secure3",
    "trust security",
})

# Points awarded per audit (before recency discount)
_FIRM_PTS_TOP: float = 20.0
_FIRM_PTS_MID: float = 15.0
_FIRM_PTS_OTHER: float = 10.0

# Recency discount for each audit: (age_days_threshold, factor)
# Applied to the oldest threshold that the audit age *exceeds*.
_AUDIT_RECENCY: Tuple[Tuple[int, float], ...] = (
    (365,  1.0),    # < 1 year → full value
    (730,  0.8),    # 1–2 years
    (1095, 0.6),    # 2–3 years
)
_AUDIT_RECENCY_FALLBACK: float = 0.3   # ≥ 3 years

# Age breakpoints (days since launch) → age_score
_AGE_BREAKPOINTS: Tuple[Tuple[int, float], ...] = (
    (1825, 100.0),   # ≥ 5 years
    (1095, 75.0),    # ≥ 3 years
    (730,  55.0),    # ≥ 2 years
    (365,  35.0),    # ≥ 1 year
    (180,  15.0),    # ≥ 6 months
    (0,     5.0),    # < 6 months (any history)
)

# TVL breakpoints (USD) → tvl_score
_TVL_BREAKPOINTS: Tuple[Tuple[float, float], ...] = (
    (5_000_000_000.0, 100.0),   # ≥ $5 B
    (1_000_000_000.0,  80.0),   # ≥ $1 B
    (500_000_000.0,    60.0),   # ≥ $500 M
    (100_000_000.0,    40.0),   # ≥ $100 M
    (10_000_000.0,     20.0),   # ≥ $10 M
    (0.0,               5.0),   # < $10 M (any TVL)
)

# Safety score component weights (must sum to 1.0)
_W_AUDIT: float = 0.60
_W_AGE:   float = 0.20
_W_TVL:   float = 0.20

# Hack risk window
_HACK_RISK_WINDOW_DAYS: int = 730  # 2 years

# ─────────────────────────────────────────────────────────────────────────────
# Pre-populated protocol seed data
# ─────────────────────────────────────────────────────────────────────────────

_SEED_PROTOCOLS: List[Dict[str, Any]] = [
    {
        "protocol_id": "aave",
        "name": "Aave V3",
        "tier": "T1",
        "tvl_usd": 12_000_000_000.0,
        "launch_date": "2017-11-01",
        "chain": "ethereum",
        "category": "lending",
        "risk_score": 0.25,
        "audits": [
            {"firm": "Trail of Bits",  "date": "2023-01-15", "scope": "V3 core"},
            {"firm": "OpenZeppelin",   "date": "2022-10-01", "scope": "V3 core"},
            {"firm": "Chainsecurity",  "date": "2021-11-01", "scope": "V3 pre-launch"},
            {"firm": "Sigma Prime",    "date": "2023-03-20", "scope": "V3 safety module"},
            {"firm": "Certik",         "date": "2022-06-01", "scope": "V3 misc"},
        ],
        "hacks": [],
    },
    {
        "protocol_id": "morpho",
        "name": "Morpho Blue",
        "tier": "T1",
        "tvl_usd": 3_000_000_000.0,
        "launch_date": "2024-01-15",
        "chain": "ethereum",
        "category": "lending",
        "risk_score": 0.28,
        "audits": [
            {"firm": "Spearbit",       "date": "2024-01-05", "scope": "Morpho Blue core"},
            {"firm": "Cantina",        "date": "2023-12-01", "scope": "Morpho Blue"},
            {"firm": "OpenZeppelin",   "date": "2024-02-01", "scope": "Morpho Blue vaults"},
            {"firm": "Trail of Bits",  "date": "2024-03-01", "scope": "Morpho Blue edge cases"},
        ],
        "hacks": [],
    },
    {
        "protocol_id": "spark",
        "name": "Spark Protocol (SparkLend)",
        "tier": "T1",
        "tvl_usd": 2_000_000_000.0,
        "launch_date": "2023-05-10",
        "chain": "ethereum",
        "category": "lending",
        "risk_score": 0.27,
        "audits": [
            {"firm": "Chainsecurity",  "date": "2023-04-20", "scope": "SparkLend V1"},
            {"firm": "Certik",         "date": "2023-05-01", "scope": "SparkLend"},
            {"firm": "OpenZeppelin",   "date": "2024-01-10", "scope": "Spark PSM"},
        ],
        "hacks": [],
    },
    {
        "protocol_id": "compound",
        "name": "Compound V3 (Comet)",
        "tier": "T1",
        "tvl_usd": 2_000_000_000.0,
        "launch_date": "2019-09-26",
        "chain": "ethereum",
        "category": "lending",
        "risk_score": 0.26,
        "audits": [
            {"firm": "OpenZeppelin",   "date": "2023-06-01", "scope": "Comet V3"},
            {"firm": "Trail of Bits",  "date": "2020-08-01", "scope": "V2 core"},
            {"firm": "Chainsecurity",  "date": "2022-07-01", "scope": "Comet V3 pre-launch"},
            {"firm": "OpenZeppelin",   "date": "2022-05-01", "scope": "Comet V3 initial"},
        ],
        "hacks": [],
    },
    {
        "protocol_id": "euler",
        "name": "Euler V2",
        "tier": "T2",
        "tvl_usd": 400_000_000.0,
        "launch_date": "2021-12-01",
        "chain": "ethereum",
        "category": "lending",
        "risk_score": 0.45,
        "audits": [
            {"firm": "Halborn",        "date": "2024-04-01", "scope": "Euler V2 core"},
            {"firm": "Certik",         "date": "2024-05-01", "scope": "Euler V2"},
            {"firm": "OpenZeppelin",   "date": "2024-03-01", "scope": "Euler V2 vaults"},
        ],
        "hacks": [
            {
                "date": "2023-03-13",
                "amount_usd": 197_000_000,
                "description": "Flash loan donation attack on Euler V1 (197M USD; funds partially recovered via negotiation)",
                "v1_only": True,
            }
        ],
    },
    {
        "protocol_id": "maple",
        "name": "Maple Finance",
        "tier": "T2",
        "tvl_usd": 300_000_000.0,
        "launch_date": "2021-05-01",
        "chain": "ethereum",
        "category": "institutional_credit",
        "risk_score": 0.50,
        "audits": [
            {"firm": "OpenZeppelin",   "date": "2021-06-01", "scope": "Maple V1"},
            {"firm": "Code4rena",      "date": "2022-07-01", "scope": "Maple V2 contest"},
        ],
        "hacks": [
            {
                "date": "2022-12-05",
                "amount_usd": 36_000_000,
                "description": "Orthogonal Trading borrower default — credit risk event, not a smart contract exploit",
                "type": "credit_default",
            }
        ],
    },
    {
        "protocol_id": "pendle",
        "name": "Pendle Finance",
        "tier": "T2",
        "tvl_usd": 2_000_000_000.0,
        "launch_date": "2021-06-15",
        "chain": "ethereum",
        "category": "yield_tokenisation",
        "risk_score": 0.40,
        "audits": [
            {"firm": "Ackee",          "date": "2022-05-01", "scope": "Pendle V2"},
            {"firm": "Code4rena",      "date": "2023-04-01", "scope": "Pendle V2 contest"},
            {"firm": "Zellic",         "date": "2024-01-01", "scope": "Pendle V2 router"},
        ],
        "hacks": [],
    },
    {
        "protocol_id": "sky",
        "name": "Sky (formerly MakerDAO)",
        "tier": "T1",
        "tvl_usd": 8_000_000_000.0,
        "launch_date": "2017-12-18",
        "chain": "ethereum",
        "category": "stablecoin_cdp",
        "risk_score": 0.22,
        "audits": [
            {"firm": "Trail of Bits",  "date": "2022-04-01", "scope": "MCD core"},
            {"firm": "Chainsecurity",  "date": "2023-02-01", "scope": "DAI PSM + Sky"},
            {"firm": "Certik",         "date": "2022-11-01", "scope": "MCD misc"},
            {"firm": "OpenZeppelin",   "date": "2023-09-01", "scope": "USDS / Sky migration"},
        ],
        "hacks": [],
    },
    {
        "protocol_id": "yearn",
        "name": "Yearn Finance V3",
        "tier": "T2",
        "tvl_usd": 500_000_000.0,
        "launch_date": "2020-02-01",
        "chain": "ethereum",
        "category": "yield_aggregator",
        "risk_score": 0.38,
        "audits": [
            {"firm": "Trail of Bits",  "date": "2022-03-01", "scope": "V3 vaults"},
            {"firm": "Certik",         "date": "2021-04-01", "scope": "V2 vaults"},
        ],
        "hacks": [
            {
                "date": "2023-04-13",
                "amount_usd": 11_600_000,
                "description": "Reentrancy exploit targeting legacy Yearn V1 USDT vault (V2/V3 unaffected)",
                "v1_only": True,
            }
        ],
    },
    {
        "protocol_id": "frax",
        "name": "Frax Finance (FraxLend)",
        "tier": "T2",
        "tvl_usd": 800_000_000.0,
        "launch_date": "2020-11-01",
        "chain": "ethereum",
        "category": "lending",
        "risk_score": 0.45,
        "audits": [
            {"firm": "Trail of Bits",  "date": "2022-06-01", "scope": "FraxLend V1"},
            {"firm": "Certik",         "date": "2021-12-01", "scope": "FRAX stablecoin"},
        ],
        "hacks": [],
    },
    {
        "protocol_id": "sdai",
        "name": "Savings DAI (sDAI)",
        "tier": "T1",
        "tvl_usd": 1_500_000_000.0,
        "launch_date": "2023-08-01",
        "chain": "ethereum",
        "category": "savings_erc4626",
        "risk_score": 0.22,
        "audits": [
            {"firm": "Chainsecurity",  "date": "2023-07-10", "scope": "sDAI ERC-4626 wrapper"},
            {"firm": "Certik",         "date": "2023-07-15", "scope": "Pot / DSR interface"},
        ],
        "hacks": [],
    },
    {
        "protocol_id": "sfrax",
        "name": "Staked FRAX (sFRAX)",
        "tier": "T2",
        "tvl_usd": 600_000_000.0,
        "launch_date": "2023-10-01",
        "chain": "ethereum",
        "category": "savings_erc4626",
        "risk_score": 0.40,
        "audits": [
            {"firm": "Trail of Bits",  "date": "2022-06-01", "scope": "FRAX ecosystem"},
            {"firm": "Certik",         "date": "2023-10-10", "scope": "sFRAX ERC-4626"},
        ],
        "hacks": [],
    },
    {
        "protocol_id": "stusd",
        "name": "Angle Staked USDA (stUSD)",
        "tier": "T2",
        "tvl_usd": 100_000_000.0,
        "launch_date": "2023-06-01",
        "chain": "ethereum",
        "category": "savings_erc4626",
        "risk_score": 0.43,
        "audits": [
            {"firm": "Chainsecurity",  "date": "2023-05-20", "scope": "Angle Protocol V2"},
            {"firm": "OpenZeppelin",   "date": "2023-06-10", "scope": "stUSD ERC-4626"},
        ],
        "hacks": [
            {
                "date": "2023-04-16",
                "amount_usd": 1_600_000,
                "description": "Angle Protocol collateral damage from Euler V1 exploit (not a direct Angle contract exploit)",
                "indirect": True,
            }
        ],
    },
    {
        "protocol_id": "scrvusd",
        "name": "Curve Savings crvUSD (scrvUSD)",
        "tier": "T2",
        "tvl_usd": 200_000_000.0,
        "launch_date": "2023-11-01",
        "chain": "ethereum",
        "category": "savings_erc4626",
        "risk_score": 0.42,
        "audits": [
            {"firm": "Chainsecurity",  "date": "2023-10-01", "scope": "crvUSD stablecoin"},
            {"firm": "MixBytes",       "date": "2024-01-01", "scope": "scrvUSD ERC-4626"},
        ],
        "hacks": [
            {
                "date": "2023-07-30",
                "amount_usd": 47_300_000,
                "description": "Vyper reentrancy exploit affecting Curve stable-swap pools (scrvUSD vault not deployed yet at exploit date)",
                "indirect": True,
            }
        ],
    },
    {
        "protocol_id": "wusdm",
        "name": "Wrapped USDM (wUSDM) — Mountain Protocol",
        "tier": "T2",
        "tvl_usd": 300_000_000.0,
        "launch_date": "2023-09-01",
        "chain": "ethereum",
        "category": "savings_erc4626",
        "risk_score": 0.38,
        "audits": [
            {"firm": "Trail of Bits",  "date": "2023-08-15", "scope": "USDM / wUSDM core"},
            {"firm": "Certik",         "date": "2023-09-01", "scope": "wUSDM ERC-4626"},
        ],
        "hacks": [],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely coerce *value* to float; return *default* on failure."""
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_date(date_str: str) -> date:
    """Parse an ISO-8601 date string (YYYY-MM-DD).  Returns ``date.min`` on failure."""
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return date.min


def _tiered_score(value: float, breakpoints: Tuple) -> float:
    """Return the score from a descending breakpoint table.

    *breakpoints* is an iterable of ``(threshold, score)`` tuples sorted
    from *highest* threshold to *lowest*.  The first threshold that *value*
    is ≥ wins.
    """
    for threshold, score in breakpoints:
        if value >= threshold:
            return score
    return 0.0


def _audit_recency_factor(age_days: int) -> float:
    """Return the recency discount factor for an audit that is *age_days* old."""
    for threshold, factor in _AUDIT_RECENCY:
        if age_days < threshold:
            return factor
    return _AUDIT_RECENCY_FALLBACK


def _firm_tier_pts(firm_name: str) -> float:
    """Return base audit points for the given firm name (case-insensitive)."""
    name_lower = firm_name.strip().lower()
    if name_lower in _FIRMS_TOP:
        return _FIRM_PTS_TOP
    if name_lower in _FIRMS_MID:
        return _FIRM_PTS_MID
    return _FIRM_PTS_OTHER


# ─────────────────────────────────────────────────────────────────────────────
# ProtocolRegistry
# ─────────────────────────────────────────────────────────────────────────────

class ProtocolRegistry:
    """Centralised registry for DeFi protocol security metadata.

    The registry is pre-seeded on construction with 15 protocols.
    Additional protocols can be added via :meth:`register`.

    Parameters
    ----------
    data_dir:
        Directory used by :meth:`save_registry` / :meth:`load_registry`.
        Defaults to the repo-level ``data/`` folder.
    seed:
        If *True* (default), pre-populate from ``_SEED_PROTOCOLS``.
    reference_date:
        Date used as "today" for age and recency calculations.  Defaults
        to :func:`datetime.date.today`.  Pass an explicit value in tests.
    """

    def __init__(
        self,
        data_dir: str = _DEFAULT_DATA_DIR,
        seed: bool = True,
        reference_date: Optional[date] = None,
    ) -> None:
        self._data_dir = data_dir
        self._today: date = reference_date or date.today()
        self._registry: Dict[str, Dict[str, Any]] = {}

        if seed:
            for entry in _SEED_PROTOCOLS:
                pid = entry["protocol_id"]
                self._registry[pid] = dict(entry)

    # ── Public CRUD ──────────────────────────────────────────────────────────

    def register(self, protocol_id: str, metadata: Dict[str, Any]) -> None:
        """Add or fully overwrite the entry for *protocol_id*.

        Parameters
        ----------
        protocol_id:
            Unique identifier string (e.g. ``"aave"``).
        metadata:
            Arbitrary dict that should at minimum contain ``"name"`` and
            ``"audits"`` (list of dicts with ``"firm"`` and ``"date"``).

        Raises
        ------
        TypeError:
            If *protocol_id* is not a string or *metadata* is not a dict.
        ValueError:
            If *protocol_id* is empty.
        """
        if not isinstance(protocol_id, str):
            raise TypeError(f"protocol_id must be a str, got {type(protocol_id).__name__}")
        if not protocol_id.strip():
            raise ValueError("protocol_id must not be empty")
        if not isinstance(metadata, dict):
            raise TypeError(f"metadata must be a dict, got {type(metadata).__name__}")

        entry = dict(metadata)
        entry["protocol_id"] = protocol_id
        self._registry[protocol_id] = entry

    def get(self, protocol_id: str) -> Optional[Dict[str, Any]]:
        """Return a copy of the metadata dict for *protocol_id*, or ``None``."""
        entry = self._registry.get(protocol_id)
        if entry is None:
            return None
        return dict(entry)

    def list_all(self) -> List[str]:
        """Return sorted list of all registered protocol IDs."""
        return sorted(self._registry.keys())

    # ── Derived signals ──────────────────────────────────────────────────────

    def get_audit_score(self, protocol_id: str) -> float:
        """Compute audit quality score in [0..100] for *protocol_id*.

        Scoring formula
        ---------------
        For each audit in the protocol's ``"audits"`` list:
            points = firm_tier_pts(audit.firm) × recency_factor(audit.date)

        Total = min(100, sum(points)).

        Returns 0.0 for an unknown protocol or a protocol with no audits.
        """
        entry = self._registry.get(protocol_id)
        if entry is None:
            return 0.0

        audits = entry.get("audits", [])
        if not audits:
            return 0.0

        total: float = 0.0
        for audit in audits:
            if not isinstance(audit, dict):
                continue
            firm = str(audit.get("firm", ""))
            date_str = str(audit.get("date", ""))
            audit_date = _parse_date(date_str)
            age_days = max(0, (self._today - audit_date).days)
            pts = _firm_tier_pts(firm) * _audit_recency_factor(age_days)
            total += pts

        return min(100.0, total)

    def _get_age_score(self, protocol_id: str) -> float:
        """Return age score [0..100] based on protocol launch date."""
        entry = self._registry.get(protocol_id)
        if entry is None:
            return 0.0
        launch_str = str(entry.get("launch_date", ""))
        launch_dt = _parse_date(launch_str)
        if launch_dt == date.min:
            return 0.0
        age_days = max(0, (self._today - launch_dt).days)
        return _tiered_score(float(age_days), _AGE_BREAKPOINTS)

    def _get_tvl_score(self, protocol_id: str) -> float:
        """Return TVL score [0..100] based on ``tvl_usd``."""
        entry = self._registry.get(protocol_id)
        if entry is None:
            return 0.0
        tvl = _safe_float(entry.get("tvl_usd", 0.0), 0.0)
        return _tiered_score(tvl, _TVL_BREAKPOINTS)

    def get_hack_risk_flag(self, protocol_id: str) -> bool:
        """Return ``True`` if *protocol_id* suffered a hack in the last 2 years.

        A "hack" entry in metadata is a dict with at least a ``"date"`` key
        (ISO-8601).  Any entry whose date falls within the last
        :data:`_HACK_RISK_WINDOW_DAYS` days relative to the registry's
        ``reference_date`` is considered a current risk.

        Returns ``False`` for an unknown protocol or a protocol with no hacks.
        """
        entry = self._registry.get(protocol_id)
        if entry is None:
            return False

        hacks = entry.get("hacks", [])
        if not hacks:
            return False

        cutoff = self._today
        for hack in hacks:
            if not isinstance(hack, dict):
                continue
            hack_date = _parse_date(str(hack.get("date", "")))
            if hack_date == date.min:
                continue
            age_days = (cutoff - hack_date).days
            if 0 <= age_days < _HACK_RISK_WINDOW_DAYS:
                return True

        return False

    def compute_safety_score(self, protocol_id: str) -> float:
        """Compute composite safety score in [0..100].

        Formula::

            safety_score = audit_score × 0.60
                         + age_score   × 0.20
                         + tvl_score   × 0.20

        Returns 0.0 for an unknown protocol.
        """
        if protocol_id not in self._registry:
            return 0.0

        audit = self.get_audit_score(protocol_id)
        age   = self._get_age_score(protocol_id)
        tvl   = self._get_tvl_score(protocol_id)

        raw = audit * _W_AUDIT + age * _W_AGE + tvl * _W_TVL
        return round(min(100.0, max(0.0, raw)), 4)

    # ── Report ────────────────────────────────────────────────────────────────

    def get_registry_report(self) -> Dict[str, Any]:
        """Return a comprehensive report dict.

        Structure::

            {
              "generated_at": "<ISO-8601>",
              "reference_date": "<YYYY-MM-DD>",
              "protocol_count": int,
              "protocols": {
                  "<id>": {
                      "metadata": {...},
                      "audit_score": float,
                      "age_score":   float,
                      "tvl_score":   float,
                      "safety_score": float,
                      "hack_risk_flag": bool,
                  },
                  ...
              },
              "top5_by_safety": [
                  {"protocol_id": str, "safety_score": float},
                  ...   # up to 5 entries
              ],
              "hack_risk_protocols": [str, ...],
            }
        """
        protocols: Dict[str, Any] = {}
        scores: List[Tuple[str, float]] = []
        hack_risks: List[str] = []

        for pid in self._registry:
            audit  = self.get_audit_score(pid)
            age    = self._get_age_score(pid)
            tvl    = self._get_tvl_score(pid)
            safety = self.compute_safety_score(pid)
            flag   = self.get_hack_risk_flag(pid)

            protocols[pid] = {
                "metadata": dict(self._registry[pid]),
                "audit_score":    round(audit,  4),
                "age_score":      round(age,    4),
                "tvl_score":      round(tvl,    4),
                "safety_score":   round(safety, 4),
                "hack_risk_flag": flag,
            }
            scores.append((pid, safety))
            if flag:
                hack_risks.append(pid)

        top5 = sorted(scores, key=lambda x: x[1], reverse=True)[:5]

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "reference_date": self._today.isoformat(),
            "protocol_count": len(self._registry),
            "protocols": protocols,
            "top5_by_safety": [
                {"protocol_id": pid, "safety_score": score}
                for pid, score in top5
            ],
            "hack_risk_protocols": sorted(hack_risks),
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def save_registry(self, data_dir: Optional[str] = None) -> str:
        """Atomically save the registry to ``<data_dir>/protocol_registry.json``.

        Returns the absolute path of the written file.

        Raises :class:`OSError` on I/O failure (after cleaning up the temp file).
        """
        target_dir = Path(data_dir or self._data_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / REGISTRY_FILENAME

        payload: Dict[str, Any] = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "protocol_count": len(self._registry),
            "registry": {pid: dict(entry) for pid, entry in self._registry.items()},
        }

        atomic_save(payload, str(target))
        return str(target)

    def load_registry(self, data_dir: Optional[str] = None) -> int:
        """Load (merge) registry entries from ``<data_dir>/protocol_registry.json``.

        Existing in-memory entries are overwritten by the file's entries.
        Unknown entries from the file are added.

        Returns the number of protocols loaded.  Returns 0 if the file does
        not exist or is malformed (non-fatal; a warning is logged).
        """
        target_dir = Path(data_dir or self._data_dir)
        target = target_dir / REGISTRY_FILENAME

        if not target.exists():
            log.debug("protocol_registry.json not found at %s — skipping load", target)
            return 0

        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to read protocol_registry.json: %s", exc)
            return 0

        if not isinstance(raw, dict):
            log.warning("protocol_registry.json: expected dict at top level, got %s", type(raw).__name__)
            return 0

        registry_data = raw.get("registry", {})
        if not isinstance(registry_data, dict):
            log.warning("protocol_registry.json: 'registry' key missing or not a dict")
            return 0

        count = 0
        for pid, entry in registry_data.items():
            if not isinstance(entry, dict):
                continue
            entry["protocol_id"] = pid
            self._registry[pid] = entry
            count += 1

        log.info("Loaded %d protocols from protocol_registry.json", count)
        return count

    # ── Dunder ───────────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._registry)

    def __contains__(self, protocol_id: object) -> bool:
        return protocol_id in self._registry

    def __repr__(self) -> str:
        return f"ProtocolRegistry(protocols={len(self._registry)}, data_dir={self._data_dir!r})"


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _cli_main(argv: Optional[List[str]] = None) -> int:
    """Entry point for ``python3 -m spa_core.analytics.protocol_registry``."""
    parser = argparse.ArgumentParser(
        prog="protocol_registry",
        description="SPA Protocol Registry — security metadata store (MP-583)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and display report (default — no file written).",
    )
    mode.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute report and atomically write protocol_registry.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=_DEFAULT_DATA_DIR,
        help="Data directory for save/load (default: repo data/).",
    )
    args = parser.parse_args(argv)

    reg = ProtocolRegistry(data_dir=args.data_dir)
    report = reg.get_registry_report()

    print(f"=== SPA Protocol Registry (MP-583) ===")
    print(f"Reference date : {report['reference_date']}")
    print(f"Protocol count : {report['protocol_count']}")
    print()
    print("Top 5 by safety score:")
    for item in report["top5_by_safety"]:
        print(f"  {item['protocol_id']:12s}  safety={item['safety_score']:.1f}")
    print()
    print("Hack risk flags (recent 2y):")
    if report["hack_risk_protocols"]:
        for pid in report["hack_risk_protocols"]:
            print(f"  ⚠  {pid}")
    else:
        print("  (none)")
    print()

    for pid, data in sorted(report["protocols"].items()):
        flag_str = " [HACK RISK]" if data["hack_risk_flag"] else ""
        print(
            f"  {pid:12s}  audit={data['audit_score']:5.1f}"
            f"  age={data['age_score']:5.1f}"
            f"  tvl={data['tvl_score']:5.1f}"
            f"  safety={data['safety_score']:5.1f}"
            f"{flag_str}"
        )

    if args.run:
        path = reg.save_registry(data_dir=args.data_dir)
        print(f"\nRegistry saved → {path}")

    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
