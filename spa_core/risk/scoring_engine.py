"""
Risk Scoring Engine — FEAT-RISK-001

Structured A/B/C/D risk grading for every whitelisted SPA protocol/pool.
Each protocol is graded on **15 deterministic subscores** in ``[0, 1]``
(higher = safer), combined with documented weights into a single numeric
score, then mapped to a letter grade:

* **A** — numeric_score >= 0.85   (full allocation cap)
* **B** — numeric_score >= 0.70   (full allocation cap)
* **C** — numeric_score >= 0.55   (allocation cap halved — see engine.py)
* **D** — numeric_score <  0.55   (allocation cap 5% max — see engine.py)

The 15 subscores
----------------
 1. ``tvl_magnitude``           — absolute TVL (>$1B = A, <$50M = D)
 2. ``tvl_trend``               — 30d % change in TVL (positive = better)
 3. ``protocol_age``            — years since launch (>=4y = A)
 4. ``hack_history``            — # incidents + losses (from data/incidents.json)
 5. ``audit_count``             — number of independent audits
 6. ``audit_findings_severity`` — weighted severity (from audit_findings.json)
 7. ``yield_source_type``       — real_cashflow > rwa > basis > emissions > points
 8. ``oracle_risk``             — Chainlink/Pyth = A, custom = D
 9. ``bridge_dependency``       — native vs bridged collateral
10. ``timelock_duration``       — governance timelock seconds
11. ``multisig_threshold``      — m-of-n threshold (>=4/7 multisig = A)
12. ``liquidity_depth``         — on-chain order-book / pool depth
13. ``cross_protocol_deps``     — # external integrations as critical deps
14. ``regulatory_surface``      — US-exposed / sanctioned chains = lower
15. ``chain_maturity``          — Ethereum=A, major L2=B, new L1=C/D

Design constraints
------------------
* **Stdlib only** — ``json``, ``math``, ``statistics``, ``urllib``,
  ``datetime``, ``logging`` — matches the rest of the SPA data pipeline.
* **Offline-tolerant** — any I/O failure (DefiLlama timeout, missing
  ``incidents.json``, missing ``audit_findings.json``) falls back to
  ``BOOTSTRAP_PROTOCOLS`` and a neutral 0.5 subscore. ``fallback_used`` flag
  on the output makes degradation observable.
* **Deterministic** — re-running on the same inputs produces a byte-identical
  output file (sorted keys, fixed float rounding, no random seeds).
* **Read-only consumer** — writes ``data/risk_scores.json`` only. The
  allocation engine (``spa_core/execution/engine.py``) will consume this file
  in a follow-up sprint to enforce grade-based allocation caps.

Output schema (``data/risk_scores.json``)
-----------------------------------------

::

    {
      "generated_at":   "<ISO-8601 UTC>",
      "engine_version": "1.0",
      "weights":        { "<subscore_key>": <weight 0..1>, ... },
      "scores": [
        {
          "protocol":           "Aave V3",
          "slug":               "aave-v3",
          "grade":              "A",
          "score_numeric":      0.92,
          "subscores":          { "tvl_magnitude": 1.0, ... },
          "explanation":        "<short human-readable summary>",
          "allocation_cap_pct": null,        # set by engine, null in scoring
          "fallback_used":      false,
          "generated_at":       "<ISO-8601 UTC>"
        },
        ...
      ],
      "summary_by_grade": { "A": 4, "B": 3, "C": 2, "D": 1 }
    }

CLI
---

::

    python -m spa_core.risk.scoring_engine                       # fetch + write
    python -m spa_core.risk.scoring_engine --offline             # bootstrap only
    python -m spa_core.risk.scoring_engine --dry-run             # no write
    python -m spa_core.risk.scoring_engine --protocol aave-v3    # single protocol

This module is consumed by FEAT-ALLOC-002 (allocation cap enforcement) and
the architect agent's protocol whitelist refresh.

ADR reference: docs/ADR_014_risk_scoring_engine.md
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.risk.scoring_engine")

# ─── Configuration ────────────────────────────────────────────────────────────

DEFILLAMA_PROTOCOLS_URL = "https://api.llama.fi/protocols"
FETCH_TIMEOUT_S = 30
FETCH_MAX_ATTEMPTS = 3
FETCH_BACKOFF_BASE = 2.0

ENGINE_VERSION = "1.0"

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PROTOCOLS_FILE = _REPO_ROOT / "data" / "protocols.json"
DEFAULT_INCIDENTS_FILE = _REPO_ROOT / "data" / "incidents.json"
DEFAULT_AUDIT_FILE = _REPO_ROOT / "data" / "audit_findings.json"
DEFAULT_OUTPUT_PATH = _REPO_ROOT / "data" / "risk_scores.json"

# FIX-P1 (AUDIT-011 — no live fetches from risk layer):
# Local cache file written by the adapter pipeline (read-only consumer here).
# When the cache exists the engine uses it as the protocols data source
# instead of making live HTTP requests to DeFiLlama.
DEFILLAMA_CACHE_FILE = _REPO_ROOT / "data" / "defi_llama_cache.json"

# Grade thresholds (boundary inclusive on the high side)
GRADE_THRESHOLDS = (
    ("A", 0.85),
    ("B", 0.70),
    ("C", 0.55),
)

# Allocation caps applied downstream by engine.py (documentation only, not enforced here)
GRADE_ALLOCATION_CAPS = {
    "A": None,       # no extra cap beyond per-strategy default
    "B": None,
    "C": 0.50,       # half of strategy default
    "D": 0.05,       # 5% absolute cap
}

# Whitelisted SPA protocols (canonical slugs)
SPA_WHITELIST: tuple[str, ...] = (
    "aave-v3",
    "compound-v3",
    "morpho",
    "yearn-v3",
    "sky",
    "maker",
    "curve",
    "uniswap-v3",
    "pendle",
    "euler-v2",
)


# ─── Subscore weights (sum = 1.0) ─────────────────────────────────────────────
# Default = equal weight; risk-critical subscores get 1.5x multiplier.
# The four boosted subscores are: oracle_risk, hack_history,
# audit_findings_severity, timelock_duration — these failure modes are
# disproportionately costly in DeFi.

_RAW_WEIGHTS: dict[str, float] = {
    "tvl_magnitude":           1.0,
    "tvl_trend":               1.0,
    "protocol_age":            1.0,
    "hack_history":            1.5,   # boosted
    "audit_count":             1.0,
    "audit_findings_severity": 1.5,   # boosted
    "yield_source_type":       1.0,
    "oracle_risk":             1.5,   # boosted
    "bridge_dependency":       1.0,
    "timelock_duration":       1.5,   # boosted
    "multisig_threshold":      1.0,
    "liquidity_depth":         1.0,
    "cross_protocol_deps":     1.0,
    "regulatory_surface":      1.0,
    "chain_maturity":          1.0,
    # ADR-031: aggregated advisory analytics signal (Tier-B). Boosted 1.5x like
    # the other failure-mode subscores — it summarises ~180 risk modules.
    "analytics_composite":     1.5,   # boosted
}

# ADR-031: advisory analytics signals consumed by the analytics_composite
# subscore. Written by spa_core.analytics.signal_aggregator (Tier-B).
ANALYTICS_ADVISORY_FILE = _REPO_ROOT / "data" / "analytics_signals_advisory.json"
ANALYTICS_TTL_S = 7200  # 2h — stale advisory data → neutral 0.5

# Map a protocol slug (scoring whitelist) to the aggregator's protocol key.
_ANALYTICS_SLUG_TO_KEY = {
    "aave-v3":     "aave_v3",
    "compound-v3": "compound_v3",
    "morpho":      "morpho_blue",
    "yearn-v3":    "yearn_v3",
    "euler-v2":    "euler_v2",
    "maple":       "maple",
    "pendle":      "pendle",
    "sky":         "spark_susds",
}


def _normalised_weights() -> dict[str, float]:
    """
    Normalise raw weights to sum exactly 1.0.

    We round each weight to 6 decimals for stable JSON output, then absorb
    the tiny rounding drift into the last key so the dict sums to exactly
    1.0 (asserted by tests; required by allocation math downstream).
    """
    total = sum(_RAW_WEIGHTS.values())
    out = {k: round(v / total, 6) for k, v in _RAW_WEIGHTS.items()}
    drift = round(1.0 - sum(out.values()), 6)
    if drift:
        last_key = list(out.keys())[-1]
        out[last_key] = round(out[last_key] + drift, 6)
    return out


WEIGHTS: dict[str, float] = _normalised_weights()


# ─── Bootstrap protocol metadata ─────────────────────────────────────────────
# Conservative public snapshot of each whitelisted protocol's key attributes,
# used when DefiLlama is unreachable. Numbers are rounded for stability; the
# scoring is robust to ~30% drift in TVL because subscores bucket into bands.

BOOTSTRAP_PROTOCOLS: dict[str, dict[str, Any]] = {
    "aave-v3": {
        "name":                "Aave V3",
        "tvl_usd":             16_000_000_000.0,
        "tvl_change_30d_pct":  5.0,
        "launched_year":       2022,
        "audit_count":         8,
        "yield_source":        "real_cashflow",
        "oracle":              "chainlink",
        "bridge_dependent":    False,
        "timelock_seconds":    7 * 24 * 3600,
        "multisig_m_of_n":     (5, 9),
        "liquidity_depth_usd": 2_500_000_000.0,
        "cross_protocol_deps": 1,
        "us_exposed":          False,
        "chain":               "ethereum",
    },
    "compound-v3": {
        "name":                "Compound V3",
        "tvl_usd":             3_200_000_000.0,
        "tvl_change_30d_pct":  3.0,
        "launched_year":       2022,
        "audit_count":         6,
        "yield_source":        "real_cashflow",
        "oracle":              "chainlink",
        "bridge_dependent":    False,
        "timelock_seconds":    2 * 24 * 3600,
        "multisig_m_of_n":     (4, 7),
        "liquidity_depth_usd": 800_000_000.0,
        "cross_protocol_deps": 1,
        "us_exposed":          True,
        "chain":               "ethereum",
    },
    "morpho": {
        "name":                "Morpho",
        "tvl_usd":             4_500_000_000.0,
        "tvl_change_30d_pct":  12.0,
        "launched_year":       2022,
        "audit_count":         5,
        "yield_source":        "real_cashflow",
        "oracle":              "chainlink",
        "bridge_dependent":    False,
        "timelock_seconds":    4 * 24 * 3600,
        "multisig_m_of_n":     (4, 7),
        "liquidity_depth_usd": 600_000_000.0,
        "cross_protocol_deps": 2,
        "us_exposed":          False,
        "chain":               "ethereum",
    },
    "yearn-v3": {
        "name":                "Yearn V3",
        "tvl_usd":             450_000_000.0,
        "tvl_change_30d_pct":  -2.0,
        "launched_year":       2020,
        "audit_count":         7,
        "yield_source":        "real_cashflow",
        "oracle":              "chainlink",
        "bridge_dependent":    False,
        "timelock_seconds":    2 * 24 * 3600,
        "multisig_m_of_n":     (4, 9),
        "liquidity_depth_usd": 100_000_000.0,
        "cross_protocol_deps": 4,
        "us_exposed":          False,
        "chain":               "ethereum",
    },
    "sky": {
        "name":                "Sky (sUSDS)",
        "tvl_usd":             7_000_000_000.0,
        "tvl_change_30d_pct":  8.0,
        "launched_year":       2024,
        "audit_count":         4,
        "yield_source":        "rwa",
        "oracle":              "chainlink",
        "bridge_dependent":    False,
        "timelock_seconds":    2 * 24 * 3600,
        "multisig_m_of_n":     (3, 5),
        "liquidity_depth_usd": 1_000_000_000.0,
        "cross_protocol_deps": 2,
        "us_exposed":          True,
        "chain":               "ethereum",
    },
    "maker": {
        "name":                "MakerDAO",
        "tvl_usd":             8_500_000_000.0,
        "tvl_change_30d_pct":  4.0,
        "launched_year":       2017,
        "audit_count":         10,
        "yield_source":        "rwa",
        "oracle":              "chainlink",
        "bridge_dependent":    False,
        "timelock_seconds":    2 * 24 * 3600,
        "multisig_m_of_n":     (5, 9),
        "liquidity_depth_usd": 1_200_000_000.0,
        "cross_protocol_deps": 2,
        "us_exposed":          True,
        "chain":               "ethereum",
    },
    "curve": {
        "name":                "Curve Finance",
        "tvl_usd":             2_300_000_000.0,
        "tvl_change_30d_pct":  -5.0,
        "launched_year":       2020,
        "audit_count":         6,
        "yield_source":        "real_cashflow",
        "oracle":              "chainlink",
        "bridge_dependent":    False,
        "timelock_seconds":    3 * 24 * 3600,
        "multisig_m_of_n":     (4, 7),
        "liquidity_depth_usd": 500_000_000.0,
        "cross_protocol_deps": 3,
        "us_exposed":          False,
        "chain":               "ethereum",
    },
    "uniswap-v3": {
        "name":                "Uniswap V3",
        "tvl_usd":             4_800_000_000.0,
        "tvl_change_30d_pct":  6.0,
        "launched_year":       2021,
        "audit_count":         9,
        "yield_source":        "real_cashflow",
        "oracle":              "chainlink",
        "bridge_dependent":    False,
        "timelock_seconds":    2 * 24 * 3600,
        "multisig_m_of_n":     (4, 7),
        "liquidity_depth_usd": 1_500_000_000.0,
        "cross_protocol_deps": 1,
        "us_exposed":          True,
        "chain":               "ethereum",
    },
    "pendle": {
        "name":                "Pendle",
        "tvl_usd":             5_500_000_000.0,
        "tvl_change_30d_pct":  18.0,
        "launched_year":       2021,
        "audit_count":         5,
        "yield_source":        "basis",
        "oracle":              "chainlink",
        "bridge_dependent":    False,
        "timelock_seconds":    2 * 24 * 3600,
        "multisig_m_of_n":     (3, 6),
        "liquidity_depth_usd": 350_000_000.0,
        "cross_protocol_deps": 4,
        "us_exposed":          False,
        "chain":               "ethereum",
    },
    "euler-v2": {
        "name":                "Euler V2",
        "tvl_usd":             900_000_000.0,
        "tvl_change_30d_pct":  10.0,
        "launched_year":       2024,
        "audit_count":         6,
        "yield_source":        "real_cashflow",
        "oracle":              "chainlink",
        "bridge_dependent":    False,
        "timelock_seconds":    4 * 24 * 3600,
        "multisig_m_of_n":     (4, 7),
        "liquidity_depth_usd": 200_000_000.0,
        "cross_protocol_deps": 2,
        "us_exposed":          False,
        "chain":               "ethereum",
    },
}


# ─── Dataclass ────────────────────────────────────────────────────────────────

@dataclass
class ProtocolRiskScore:
    """Risk-graded view of a single protocol."""
    protocol: str
    slug: str
    grade: str
    score_numeric: float
    subscores: dict[str, float]
    explanation: str
    generated_at: str
    fallback_used: bool = False
    allocation_cap_pct: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol":           self.protocol,
            "slug":               self.slug,
            "grade":              self.grade,
            "score_numeric":      self.score_numeric,
            "subscores":          dict(self.subscores),
            "explanation":        self.explanation,
            "allocation_cap_pct": self.allocation_cap_pct,
            "fallback_used":      self.fallback_used,
            "generated_at":       self.generated_at,
        }


# ─── Utility helpers ─────────────────────────────────────────────────────────

def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a numeric score into [lo, hi]."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return float(value)


def _score_round(value: float) -> float:
    """Round subscore to 4 decimals for deterministic output."""
    return round(float(value), 4)


def grade_for_score(score: float) -> str:
    """Map a numeric score in [0,1] to a letter grade (A/B/C/D)."""
    for letter, threshold in GRADE_THRESHOLDS:
        if score >= threshold:
            return letter
    return "D"


# ─── Engine ──────────────────────────────────────────────────────────────────

class RiskScoringEngine:
    """
    Deterministic risk scoring engine. See module docstring for full design.
    """

    def __init__(
        self,
        protocols_file: Path | str = DEFAULT_PROTOCOLS_FILE,
        incidents_file: Path | str = DEFAULT_INCIDENTS_FILE,
        audit_file: Path | str = DEFAULT_AUDIT_FILE,
        offline: bool = False,
        timeout: int = FETCH_TIMEOUT_S,
    ):
        self.protocols_file = Path(protocols_file)
        self.incidents_file = Path(incidents_file)
        self.audit_file = Path(audit_file)
        self.offline = offline
        self.timeout = timeout

        # Lazily loaded caches (filled by _ensure_loaded)
        self._protocols_data: Optional[dict[str, dict[str, Any]]] = None
        self._incidents_data: Optional[dict[str, Any]] = None
        self._audit_data: Optional[dict[str, Any]] = None
        # Per-call flag — set to True if any subscore had to use a default
        self._fallback_used_run: bool = False

    # ── Data loading ──────────────────────────────────────────────────────

    def _fetch_defillama_protocols(self, offline: bool = False) -> dict[str, dict[str, Any]]:
        """
        Return protocol data for risk scoring.

        FIX-P1 (AUDIT-011 — no live fetches from risk layer):
        The risk layer is deterministic and must not make live HTTP calls that
        could introduce non-determinism or be poisoned by network data.

        Priority order (no live network in any path):
        1. Local DeFiLlama cache (``data/defi_llama_cache.json``) written by
           the read-only adapter pipeline — most up-to-date offline source.
        2. ``--offline`` mode / missing cache → BOOTSTRAP_PROTOCOLS (hardcoded
           last-known-good values).

        If the cache is stale or missing, a WARNING is logged and the engine
        continues with bootstrap defaults.  ``fallback_used`` is set on output.
        NEVER raises.
        """
        if offline:
            log.info("offline=True — using BOOTSTRAP_PROTOCOLS")
            return self._materialise_bootstrap()

        # ── FIX-P1: try local cache first, NO live HTTP call ─────────────────
        try:
            if DEFILLAMA_CACHE_FILE.exists():
                raw = DEFILLAMA_CACHE_FILE.read_text(encoding="utf-8")
                payload = json.loads(raw)
                if isinstance(payload, list):
                    indexed: dict[str, dict[str, Any]] = {}
                    for entry in payload:
                        if not isinstance(entry, dict):
                            continue
                        slug = str(entry.get("slug", "")).strip().lower()
                        if not slug:
                            continue
                        indexed[slug] = entry
                    merged = self._materialise_bootstrap()
                    for slug, entry in indexed.items():
                        if slug not in merged:
                            merged[slug] = self._reshape_defillama_entry(entry)
                        else:
                            merged[slug].update(self._reshape_defillama_entry(entry))
                    log.info(
                        "risk scoring: loaded %d protocols from local cache %s",
                        len(indexed), DEFILLAMA_CACHE_FILE.name,
                    )
                    return merged
                else:
                    log.warning(
                        "risk scoring: cache %s has unexpected format (%s) "
                        "— using BOOTSTRAP_PROTOCOLS",
                        DEFILLAMA_CACHE_FILE.name, type(payload).__name__,
                    )
            else:
                log.warning(
                    "risk scoring: local cache %s not found "
                    "— using BOOTSTRAP_PROTOCOLS (last-known-good values). "
                    "Run the adapter pipeline to refresh the cache.",
                    DEFILLAMA_CACHE_FILE.name,
                )
        except (OSError, ValueError, json.JSONDecodeError) as e:
            log.warning(
                "risk scoring: failed to read local cache (%s) — using BOOTSTRAP_PROTOCOLS",
                e,
            )

        self._fallback_used_run = True
        return self._materialise_bootstrap()

    @staticmethod
    def _materialise_bootstrap() -> dict[str, dict[str, Any]]:
        """Deep copy of the bootstrap dict so callers can mutate freely."""
        return {slug: dict(meta) for slug, meta in BOOTSTRAP_PROTOCOLS.items()}

    @staticmethod
    def _reshape_defillama_entry(entry: dict[str, Any]) -> dict[str, Any]:
        """
        Pull the fields we care about from a raw DefiLlama protocol entry.
        Unknown fields are left to the bootstrap defaults.
        """
        chain = entry.get("chain") or (
            entry.get("chains", ["ethereum"])[0]
            if isinstance(entry.get("chains"), list) and entry.get("chains") else "ethereum"
        )
        return {
            "name":               str(entry.get("name", "")),
            "tvl_usd":            float(entry.get("tvl") or 0.0),
            "tvl_change_30d_pct": float(entry.get("change_30d") or 0.0),
            "audit_count":        int(entry.get("audits") or 0),
            "chain":              str(chain).lower(),
        }

    def _load_incidents(self) -> dict[str, Any]:
        """
        Read ``data/incidents.json`` produced by FEAT-RISK-002.

        Returns the parsed dict or ``{}`` if the file does not exist / is invalid.
        Sets ``_fallback_used_run`` in the latter case.
        """
        if not self.incidents_file.exists():
            log.info("incidents file %s missing — neutral hack-history score",
                     self.incidents_file)
            self._fallback_used_run = True
            return {}
        try:
            return json.loads(self.incidents_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("could not read %s: %s — neutral hack-history score",
                        self.incidents_file, e)
            self._fallback_used_run = True
            return {}

    def _load_audit_findings(self) -> dict[str, Any]:
        """
        Read ``data/audit_findings.json`` produced by FEAT-INT-001 (future).

        Returns the parsed dict or ``{}`` if the file does not exist / is invalid.
        Sets ``_fallback_used_run`` if the file is missing.
        """
        if not self.audit_file.exists():
            log.info("audit findings file %s missing — neutral audit-severity score",
                     self.audit_file)
            self._fallback_used_run = True
            return {}
        try:
            return json.loads(self.audit_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("could not read %s: %s — neutral audit-severity score",
                        self.audit_file, e)
            self._fallback_used_run = True
            return {}

    def _ensure_loaded(self) -> None:
        """Lazy-load shared data into instance caches."""
        if self._protocols_data is None:
            self._protocols_data = self._fetch_defillama_protocols(offline=self.offline)
        if self._incidents_data is None:
            self._incidents_data = self._load_incidents()
        if self._audit_data is None:
            self._audit_data = self._load_audit_findings()

    # ── 15 subscore methods ───────────────────────────────────────────────
    # Each method returns a float in [0,1]; higher = safer. None of these
    # raise — missing fields collapse to a neutral 0.5.

    def _score_tvl_magnitude(self, data: dict[str, Any]) -> float:
        """1.0 if TVL >= $1B, 0.0 if TVL <= $50M, linear log-ish in between."""
        tvl = float(data.get("tvl_usd") or 0.0)
        if tvl <= 50_000_000:
            return _score_round(0.0)
        if tvl >= 1_000_000_000:
            return _score_round(1.0)
        # log10 interpolation between 50M (=7.7) and 1B (=9.0)
        import math
        lo, hi = math.log10(50_000_000), math.log10(1_000_000_000)
        val = (math.log10(tvl) - lo) / (hi - lo)
        return _score_round(_clip(val))

    def _score_tvl_trend(self, data: dict[str, Any]) -> float:
        """Maps 30d TVL change pct to [0,1]: -50% = 0.0, 0% = 0.5, +50% = 1.0."""
        chg = float(data.get("tvl_change_30d_pct") or 0.0)
        val = 0.5 + (chg / 100.0)
        return _score_round(_clip(val))

    def _score_protocol_age(self, data: dict[str, Any]) -> float:
        """4+ years = 1.0, <0.5y = 0.0, linear between."""
        launched = int(data.get("launched_year") or datetime.now(timezone.utc).year)
        years = max(0.0, float(datetime.now(timezone.utc).year - launched))
        if years >= 4.0:
            return _score_round(1.0)
        if years <= 0.5:
            return _score_round(0.0)
        return _score_round(_clip((years - 0.5) / 3.5))

    def _score_hack_history(self, data: dict[str, Any], slug: str) -> float:
        """
        Uses ``data/incidents.json``. Score formula:

            base = 1.0
            per_incident_penalty = 0.20
            per_billion_lost_penalty = 0.15

        Neutral 0.5 if incidents.json missing (fallback).
        """
        if not self._incidents_data:
            self._fallback_used_run = True
            return _score_round(0.5)
        summary = self._incidents_data.get("by_protocol_summary") or {}
        # Try exact slug, then alt slugs (e.g. "yearn-v3" -> "yearn")
        entry = summary.get(slug)
        if entry is None:
            for k in (slug.split("-")[0], slug.replace("-v2", "").replace("-v3", "")):
                if k and k in summary:
                    entry = summary[k]
                    break
        if entry is None:
            return _score_round(1.0)
        incidents_n = int(entry.get("incidents") or 0)
        lost_usd = float(entry.get("total_lost_usd") or 0.0)
        score = 1.0 - 0.20 * incidents_n - 0.15 * (lost_usd / 1_000_000_000.0)
        return _score_round(_clip(score))

    def _score_audit_count(self, data: dict[str, Any]) -> float:
        """0 audits = 0.0, 6+ audits = 1.0, linear between."""
        n = int(data.get("audit_count") or 0)
        if n <= 0:
            return _score_round(0.0)
        if n >= 6:
            return _score_round(1.0)
        return _score_round(n / 6.0)

    def _score_audit_findings_severity(self, data: dict[str, Any], slug: str) -> float:
        """
        Uses ``data/audit_findings.json`` (FEAT-INT-001).

        Expected shape per protocol:
            {"<slug>": {"critical": n, "high": n, "medium": n, "low": n}}

        Score = 1.0 - 0.30*critical - 0.15*high - 0.05*medium - 0.01*low

        Neutral 0.5 if file missing (fallback).
        """
        if not self._audit_data:
            self._fallback_used_run = True
            return _score_round(0.5)
        findings_by_protocol = (
            self._audit_data.get("by_protocol")
            or self._audit_data.get("findings")
            or self._audit_data
        )
        if not isinstance(findings_by_protocol, dict):
            self._fallback_used_run = True
            return _score_round(0.5)
        entry = findings_by_protocol.get(slug)
        if entry is None:
            return _score_round(1.0)
        critical = int(entry.get("critical") or 0)
        high = int(entry.get("high") or 0)
        medium = int(entry.get("medium") or 0)
        low = int(entry.get("low") or 0)
        score = 1.0 - 0.30 * critical - 0.15 * high - 0.05 * medium - 0.01 * low
        return _score_round(_clip(score))

    def _score_yield_source_type(self, data: dict[str, Any]) -> float:
        """
        Yield-source quality ranking:
            real_cashflow = 1.0
            rwa           = 0.85
            basis         = 0.70
            emissions     = 0.40
            points        = 0.30
            unknown       = 0.50
        """
        mapping = {
            "real_cashflow": 1.0,
            "rwa":           0.85,
            "basis":         0.70,
            "emissions":     0.40,
            "points":        0.30,
            "unknown":       0.50,
        }
        raw = str(data.get("yield_source") or "unknown").strip().lower()
        return _score_round(mapping.get(raw, 0.50))

    def _score_oracle_risk(self, data: dict[str, Any]) -> float:
        """Chainlink/Pyth = 1.0, redstone/uma = 0.75, internal/custom = 0.30."""
        mapping = {
            "chainlink": 1.0,
            "pyth":      1.0,
            "redstone":  0.75,
            "uma":       0.75,
            "internal":  0.30,
            "custom":    0.30,
            "unknown":   0.40,
        }
        raw = str(data.get("oracle") or "unknown").strip().lower()
        return _score_round(mapping.get(raw, 0.40))

    def _score_bridge_dependency(self, data: dict[str, Any]) -> float:
        """Native assets = 1.0, bridged collateral = 0.30."""
        bridged = bool(data.get("bridge_dependent", False))
        return _score_round(0.30 if bridged else 1.0)

    def _score_timelock_duration(self, data: dict[str, Any]) -> float:
        """0s = 0.0, 7d+ = 1.0, linear between."""
        secs = float(data.get("timelock_seconds") or 0.0)
        max_secs = 7 * 24 * 3600
        if secs <= 0:
            return _score_round(0.0)
        if secs >= max_secs:
            return _score_round(1.0)
        return _score_round(secs / max_secs)

    def _score_multisig_threshold(self, data: dict[str, Any]) -> float:
        """
        Threshold ratio (m/n). 1/1 = 0.0 (single signer = highest risk),
        ratio 0.5 -> 0.7, ratio >=0.6 -> 1.0.
        """
        m_of_n = data.get("multisig_m_of_n")
        if not (isinstance(m_of_n, (list, tuple)) and len(m_of_n) == 2):
            return _score_round(0.5)
        try:
            m, n = int(m_of_n[0]), int(m_of_n[1])
        except (TypeError, ValueError):
            return _score_round(0.5)
        if n <= 0 or m <= 0:
            return _score_round(0.0)
        if n < 3:  # 1/1, 1/2 — too few signers
            return _score_round(0.20)
        ratio = m / n
        if ratio >= 0.60:
            return _score_round(1.0)
        if ratio <= 0.20:
            return _score_round(0.20)
        # Linear between 0.20 ratio → 0.40 and 0.60 ratio → 1.00
        return _score_round(_clip(0.40 + (ratio - 0.20) * 1.5))

    def _score_liquidity_depth(self, data: dict[str, Any]) -> float:
        """$1B+ depth = 1.0, $10M = 0.0, log-ish in between."""
        depth = float(data.get("liquidity_depth_usd") or 0.0)
        if depth <= 10_000_000:
            return _score_round(0.0)
        if depth >= 1_000_000_000:
            return _score_round(1.0)
        import math
        lo, hi = math.log10(10_000_000), math.log10(1_000_000_000)
        return _score_round(_clip((math.log10(depth) - lo) / (hi - lo)))

    def _score_cross_protocol_deps(self, data: dict[str, Any]) -> float:
        """0 deps = 1.0, 5+ deps = 0.0, linear between."""
        n = int(data.get("cross_protocol_deps") or 0)
        if n <= 0:
            return _score_round(1.0)
        if n >= 5:
            return _score_round(0.0)
        return _score_round(_clip(1.0 - (n / 5.0)))

    def _score_regulatory_surface(self, data: dict[str, Any]) -> float:
        """US-exposed = 0.50, sanctioned chain = 0.10, otherwise 1.0."""
        chain = str(data.get("chain") or "").strip().lower()
        if chain in {"tron", "tornado-cash"}:
            return _score_round(0.10)
        if bool(data.get("us_exposed", False)):
            return _score_round(0.50)
        return _score_round(1.0)

    def _score_analytics(self, slug: str) -> float:
        """ADR-031: aggregated advisory analytics subscore in [0,1] (higher=safer).

        Reads ``data/analytics_signals_advisory.json`` (Tier-B aggregator output)
        and converts the protocol's ``risk_multiplier`` (0.5..1.5) into a safety
        score. No data / stale (>2h) / low confidence → neutral 0.5.

        Mapping: multiplier 1.5 (lowest risk) → 1.0, 1.0 (neutral) → 0.5,
        0.5 (highest risk) → 0.0.  ``score = (mult - 0.5)``.
        """
        try:
            if not ANALYTICS_ADVISORY_FILE.exists():
                self._fallback_used_run = True
                return _score_round(0.5)
            payload = json.loads(ANALYTICS_ADVISORY_FILE.read_text(encoding="utf-8"))
            ts = (payload.get("_meta") or {}).get("timestamp")
            if ts:
                import time as _time
                age = _time.time() - datetime.fromisoformat(
                    str(ts).replace("Z", "+00:00")
                ).timestamp()
                if age > ANALYTICS_TTL_S:
                    self._fallback_used_run = True
                    return _score_round(0.5)
            protos = payload.get("protocols") or payload.get("signals") or {}
            key = _ANALYTICS_SLUG_TO_KEY.get(slug, slug)
            entry = protos.get(key) or protos.get(slug)
            if not isinstance(entry, dict):
                self._fallback_used_run = True
                return _score_round(0.5)
            mult = float(entry.get("risk_multiplier", 1.0))
            score = mult - 0.5  # 0.5..1.5 → 0.0..1.0
            return _score_round(_clip(score))
        except Exception:
            self._fallback_used_run = True
            return _score_round(0.5)

    def _score_chain_maturity(self, data: dict[str, Any]) -> float:
        """
        Chain maturity buckets:
            ethereum               = 1.00 (A)
            arbitrum/optimism/base = 0.80 (B)
            polygon/avalanche      = 0.65
            other established L1   = 0.55 (C)
            new L1                 = 0.30 (D)
        """
        mapping = {
            "ethereum":  1.00,
            "arbitrum":  0.80,
            "optimism":  0.80,
            "base":      0.80,
            "polygon":   0.65,
            "avalanche": 0.65,
            "bsc":       0.55,
            "solana":    0.55,
            "tron":      0.40,
            "fantom":    0.40,
            "sui":       0.30,
            "aptos":     0.30,
        }
        chain = str(data.get("chain") or "ethereum").strip().lower()
        return _score_round(mapping.get(chain, 0.40))

    # ── Aggregation & public API ──────────────────────────────────────────

    def _all_subscores(self, slug: str, data: dict[str, Any]) -> dict[str, float]:
        return {
            "tvl_magnitude":           self._score_tvl_magnitude(data),
            "tvl_trend":               self._score_tvl_trend(data),
            "protocol_age":            self._score_protocol_age(data),
            "hack_history":            self._score_hack_history(data, slug),
            "audit_count":             self._score_audit_count(data),
            "audit_findings_severity": self._score_audit_findings_severity(data, slug),
            "yield_source_type":       self._score_yield_source_type(data),
            "oracle_risk":             self._score_oracle_risk(data),
            "bridge_dependency":       self._score_bridge_dependency(data),
            "timelock_duration":       self._score_timelock_duration(data),
            "multisig_threshold":      self._score_multisig_threshold(data),
            "liquidity_depth":         self._score_liquidity_depth(data),
            "cross_protocol_deps":     self._score_cross_protocol_deps(data),
            "regulatory_surface":      self._score_regulatory_surface(data),
            "chain_maturity":          self._score_chain_maturity(data),
            "analytics_composite":     self._score_analytics(slug),
        }

    def _build_explanation(
        self,
        protocol_name: str,
        grade: str,
        score: float,
        subscores: dict[str, float],
    ) -> str:
        """Short human-readable explanation listing top-3 weak subscores."""
        weakest = sorted(subscores.items(), key=lambda kv: kv[1])[:3]
        weak_str = ", ".join(f"{k}={v:.2f}" for k, v in weakest)
        return (
            f"{protocol_name} graded {grade} (numeric {score:.3f}). "
            f"Lowest subscores: {weak_str}."
        )

    def compute_score(self, protocol_slug: str) -> ProtocolRiskScore:
        """
        Compute the risk score for a single protocol.

        NEVER raises — unknown slugs return a neutral-default record with
        ``fallback_used=True``.
        """
        # Save prior fallback flag to isolate this call
        prior_fallback = self._fallback_used_run
        self._fallback_used_run = False

        self._ensure_loaded()
        protocols = self._protocols_data or {}
        data = protocols.get(protocol_slug)

        if data is None:
            # unknown slug — try bootstrap as last resort
            data = BOOTSTRAP_PROTOCOLS.get(protocol_slug)
            if data is None:
                # totally unknown — fabricate neutral record
                self._fallback_used_run = True
                neutral_subscores = {k: 0.5 for k in _RAW_WEIGHTS}
                neutral_numeric = round(
                    sum(neutral_subscores[k] * WEIGHTS[k] for k in WEIGHTS), 4
                )
                rec = ProtocolRiskScore(
                    protocol=protocol_slug,
                    slug=protocol_slug,
                    grade=grade_for_score(neutral_numeric),
                    score_numeric=neutral_numeric,
                    subscores=neutral_subscores,
                    explanation=f"{protocol_slug}: no metadata available — neutral fallback.",
                    generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    fallback_used=True,
                    allocation_cap_pct=GRADE_ALLOCATION_CAPS.get(grade_for_score(neutral_numeric)),
                )
                self._fallback_used_run = prior_fallback or True
                return rec

        subscores = self._all_subscores(protocol_slug, data)
        numeric = round(sum(subscores[k] * WEIGHTS[k] for k in WEIGHTS), 4)
        grade = grade_for_score(numeric)
        name = str(data.get("name") or protocol_slug)
        fallback = self._fallback_used_run

        rec = ProtocolRiskScore(
            protocol=name,
            slug=protocol_slug,
            grade=grade,
            score_numeric=numeric,
            subscores=subscores,
            explanation=self._build_explanation(name, grade, numeric, subscores),
            generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            fallback_used=fallback,
            allocation_cap_pct=GRADE_ALLOCATION_CAPS.get(grade),
        )
        # Merge fallback into the overall run state
        self._fallback_used_run = prior_fallback or fallback
        return rec

    def compute_all(self, slugs: Optional[list[str]] = None) -> list[ProtocolRiskScore]:
        """Compute scores for the SPA whitelist (or a custom slug list)."""
        self._fallback_used_run = False
        target = list(slugs) if slugs else list(SPA_WHITELIST)
        results: list[ProtocolRiskScore] = []
        for slug in target:
            results.append(self.compute_score(slug))
        return results

    # ── Export ─────────────────────────────────────────────────────────────

    def export(
        self,
        output_file: Path | str = DEFAULT_OUTPUT_PATH,
        dry_run: bool = False,
        slugs: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """
        Compute all scores and (optionally) write the canonical JSON snapshot.

        Returns the snapshot dict regardless of ``dry_run``.
        """
        scores = self.compute_all(slugs=slugs)
        summary_by_grade: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0}
        for s in scores:
            summary_by_grade[s.grade] = summary_by_grade.get(s.grade, 0) + 1

        snapshot = {
            "generated_at":      datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "engine_version":    ENGINE_VERSION,
            "weights":           dict(WEIGHTS),
            "scores":            [s.to_dict() for s in scores],
            "summary_by_grade":  summary_by_grade,
            "fallback_used_any": any(s.fallback_used for s in scores),
        }

        if dry_run:
            log.info("--dry-run: not writing %s", output_file)
            return snapshot

        # SPA-V414 (MP-012): atomic write — tmpfile in the same dir +
        # os.replace (rename). Readers (allocator) always see either the old
        # or the new snapshot in full, never a partially written file.
        out = Path(output_file)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(snapshot, str(out))
        log.info("Wrote %d risk scores to %s", len(scores), out)
        return snapshot


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _cli(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Risk Scoring Engine (FEAT-RISK-001) — grade SPA protocols A/B/C/D",
    )
    parser.add_argument("--offline", action="store_true",
                        help="Skip network — use BOOTSTRAP_PROTOCOLS only.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute scores but do not write to disk.")
    parser.add_argument("--protocol", type=str, default=None,
                        help="Score a single protocol slug (e.g. aave-v3).")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH,
                        help=f"Output path (default: {DEFAULT_OUTPUT_PATH})")
    parser.add_argument("--timeout", type=int, default=FETCH_TIMEOUT_S,
                        help="HTTP timeout in seconds.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    engine = RiskScoringEngine(offline=args.offline, timeout=args.timeout)
    slugs = [args.protocol] if args.protocol else None

    snapshot = engine.export(
        output_file=args.output,
        dry_run=args.dry_run,
        slugs=slugs,
    )

    by_grade = snapshot["summary_by_grade"]
    log.info(
        "Scored %d protocols: A=%d B=%d C=%d D=%d (fallback_used_any=%s)",
        len(snapshot["scores"]),
        by_grade.get("A", 0), by_grade.get("B", 0),
        by_grade.get("C", 0), by_grade.get("D", 0),
        snapshot["fallback_used_any"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
