"""
Yield Classifier Agent — FEAT-RISK-003

Claude-style agent that classifies the *source* of yield for every protocol
in the SPA whitelist and emits ``data/yield_sources.json``. Knowing the
yield source is critical for the S2 (LP stable) and S3 (yield loop)
strategies — without it, the allocator can rotate capital into pools whose
APY is funded by token emissions that are about to expire (the #1 DeFi
yield trap for passive strategies).

Categories
----------
* ``real_cashflow``    — lending spread / fee revenue (Aave, Compound, Morpho
                        supply rates, Curve swap fees, etc.)
* ``token_emissions``  — protocol subsidy paid in the project's own token,
                        usually time-limited.
* ``points_farming``   — speculative pre-TGE point programs.
* ``basis_trade``      — perp funding-rate arbitrage (Ethena sUSDe) or fixed
                        yield carved from future emissions / funding (Pendle PT).
* ``rwa``              — real-world asset backed yield (Sky DSR via MakerDAO
                        RWA, Maple credit, Spark RWA).
* ``unknown``          — could not determine.

Design constraints
------------------
* **Stdlib only** — ``urllib.request`` + ``json`` + ``re`` + ``datetime``.
  Matches ``audit_reader_agent.py`` / ``incidents_fetcher.py`` style.
* **Offline-tolerant** — every network call is wrapped in try/except and
  falls back to ``BOOTSTRAP_CLASSIFICATIONS`` (curated from public
  protocol documentation). Bootstrap alone is sufficient to seed the Risk
  Scoring Engine.
* **Deterministic** — two consecutive calls to ``classify_all`` produce
  byte-identical output (sorted slugs, ``generated_at`` excluded from any
  equality check by the caller).
* **No exceptions escape** — ``classify_all`` / ``export`` /
  ``enrich_risk_scores`` never raise; on any failure they fall back to
  bootstrap data and set ``fallback_used = True``.

Output schema (``data/yield_sources.json``)
-------------------------------------------

::

    {
      "generated_at": "<ISO-8601 UTC>",
      "agent_version": "1.0",
      "sources": ["bootstrap"],
      "fallback_used": true,
      "protocols": {
        "aave-v3": {
          "protocol_slug":        "aave-v3",
          "primary_source":       "real_cashflow",
          "secondary_sources":    [],
          "confidence":           "HIGH",
          "emissions_share_pct":  0,
          "rationale":            "Standard lending protocol. ...",
          "data_sources":         ["bootstrap", "protocol_docs"],
          "classified_at":        "2026-05-28"
        },
        ...
      },
      "summary": {
        "total_protocols":         13,
        "by_primary_source":       {"real_cashflow": 9, "basis_trade": 2, ...},
        "high_emissions_count":    0,
        "unknown_count":           0
      }
    }

CLI
---

::

    python -m spa_core.agents.yield_classifier_agent             # write file
    python -m spa_core.agents.yield_classifier_agent --offline   # bootstrap only
    python -m spa_core.agents.yield_classifier_agent --dry-run   # log, no write

Optional enrichment: if ``data/risk_scores.json`` exists, the agent merges a
``yield_source`` field (= ``primary_source``) into every per-protocol entry.
If the file is missing or has an unexpected shape, the enrichment is a
no-op with a DEBUG log line.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("spa.yield_classifier_agent")

AGENT_VERSION = "1.0"

# ─── Configuration ────────────────────────────────────────────────────────────

FETCH_TIMEOUT_S = 30
FETCH_MAX_ATTEMPTS = 2
FETCH_BACKOFF_BASE = 2.0

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUTPUT_PATH = _REPO_ROOT / "data" / "yield_sources.json"
DEFAULT_RISK_SCORES_PATH = _REPO_ROOT / "data" / "risk_scores.json"

# Canonical taxonomy
YIELD_SOURCES: tuple[str, ...] = (
    "real_cashflow",
    "token_emissions",
    "points_farming",
    "basis_trade",
    "rwa",
    "unknown",
)
CONFIDENCE_LEVELS: tuple[str, ...] = ("HIGH", "MEDIUM", "LOW")

# SPA whitelist — every slug listed here MUST appear in BOOTSTRAP_CLASSIFICATIONS.
# This is a superset of the audit_reader / incidents_fetcher whitelist because
# the yield classifier also has to cover *pools* that span chains (curve USDC/USDT,
# uniswap v3 stable, etc.).
SPA_WHITELIST: tuple[str, ...] = (
    "aave-v3",
    "compound-v3",
    "morpho",
    "yearn-v3",
    "sky",
    "maple",
    "euler-v2",
    "pendle-pt",
    "curve-usdc-usdt",
    "uniswap-v3-stable",
    "ethena-susde",
    "spark-usdc",
    "fluid-usdc",
)

# Token-style normalisation regex (split on whitespace, hyphens, slashes, etc.)
_NORMALISE_RE = re.compile(r"[^a-z0-9]+")


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class YieldClassification:
    """A single per-protocol yield-source classification."""

    protocol_slug: str
    primary_source: str = "unknown"
    secondary_sources: list[str] = field(default_factory=list)
    confidence: str = "LOW"
    emissions_share_pct: int = 0
    rationale: str = ""
    data_sources: list[str] = field(default_factory=list)
    classified_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Sorted for deterministic output. Secondary sources are sorted but
        # de-duplicated.
        d["secondary_sources"] = sorted(set(d["secondary_sources"]))
        d["data_sources"] = sorted(set(d["data_sources"]))
        return d


# ─── Curated bootstrap classifications ────────────────────────────────────────
# Each entry is the canonical classification for one SPA whitelist protocol.
# Compiled from publicly available protocol documentation, reward-contract
# inspection, and well-known basis/perp programs (Ethena IPOR / Pendle SY etc.).
#
# Format: tuple of dicts; field semantics match the YieldClassification
# dataclass. ``classified_at`` is the date the bootstrap snapshot was authored.
# ----------------------------------------------------------------------------

_BOOTSTRAP_CLASSIFIED_AT = "2026-05-28"

BOOTSTRAP_CLASSIFICATIONS: tuple[dict[str, Any], ...] = (
    {
        "protocol_slug":       "aave-v3",
        "primary_source":      "real_cashflow",
        "secondary_sources":   [],
        "confidence":          "HIGH",
        "emissions_share_pct": 0,
        "rationale":           (
            "Standard lending protocol. APY = utilization * borrow_rate - "
            "reserve_factor. No active emissions program on the mainnet "
            "stablecoin markets — supply APY is 100% borrower-paid interest."
        ),
        "data_sources":        ["bootstrap", "protocol_docs"],
        "classified_at":       _BOOTSTRAP_CLASSIFIED_AT,
    },
    {
        "protocol_slug":       "compound-v3",
        "primary_source":      "real_cashflow",
        "secondary_sources":   ["token_emissions"],
        "confidence":          "HIGH",
        "emissions_share_pct": 15,
        "rationale":           (
            "Comet lending spread is the dominant yield source. COMP "
            "incentives are still active on most cUSDC/cUSDT markets but "
            "typically contribute under ~15% of headline APY."
        ),
        "data_sources":        ["bootstrap", "protocol_docs"],
        "classified_at":       _BOOTSTRAP_CLASSIFIED_AT,
    },
    {
        "protocol_slug":       "morpho",
        "primary_source":      "real_cashflow",
        "secondary_sources":   [],
        "confidence":          "HIGH",
        "emissions_share_pct": 0,
        "rationale":           (
            "Morpho Blue is intent-based lending — supply APY is pure "
            "borrower-paid interest matched at the singleton vault level. "
            "Vault curator can layer rewards but base APY is real cashflow."
        ),
        "data_sources":        ["bootstrap", "protocol_docs"],
        "classified_at":       _BOOTSTRAP_CLASSIFIED_AT,
    },
    {
        "protocol_slug":       "yearn-v3",
        "primary_source":      "real_cashflow",
        "secondary_sources":   [],
        "confidence":          "HIGH",
        "emissions_share_pct": 0,
        "rationale":           (
            "Yearn V3 vaults auto-compound supply yields from underlying "
            "lending strategies (Aave, Compound, Morpho). No vault-level "
            "token emissions on stablecoin vaults."
        ),
        "data_sources":        ["bootstrap", "protocol_docs"],
        "classified_at":       _BOOTSTRAP_CLASSIFIED_AT,
    },
    {
        "protocol_slug":       "sky",
        "primary_source":      "real_cashflow",
        "secondary_sources":   ["rwa"],
        "confidence":          "HIGH",
        "emissions_share_pct": 0,
        "rationale":           (
            "sUSDS pays the Sky Savings Rate which is backed by MakerDAO's "
            "PSM + RWA collateral (treasuries via Monetalis, Andromeda, "
            "BlockTower). Rate is governance-set, funded by real T-bill "
            "yields and stablecoin lending."
        ),
        "data_sources":        ["bootstrap", "protocol_docs"],
        "classified_at":       _BOOTSTRAP_CLASSIFIED_AT,
    },
    {
        "protocol_slug":       "maple",
        "primary_source":      "real_cashflow",
        "secondary_sources":   ["rwa"],
        "confidence":          "HIGH",
        "emissions_share_pct": 0,
        "rationale":           (
            "Institutional credit lending — APY is the borrower interest "
            "paid by KYC'd institutional borrowers (market makers, prop "
            "firms). Some pools take real-world receivables as collateral."
        ),
        "data_sources":        ["bootstrap", "protocol_docs"],
        "classified_at":       _BOOTSTRAP_CLASSIFIED_AT,
    },
    {
        "protocol_slug":       "euler-v2",
        "primary_source":      "real_cashflow",
        "secondary_sources":   [],
        "confidence":          "HIGH",
        "emissions_share_pct": 0,
        "rationale":           (
            "EVK vault lending spread. Supply APY = utilization * borrow "
            "APR - reserve. Post-relaunch the protocol does not subsidise "
            "stablecoin markets with token emissions."
        ),
        "data_sources":        ["bootstrap", "protocol_docs"],
        "classified_at":       _BOOTSTRAP_CLASSIFIED_AT,
    },
    {
        "protocol_slug":       "pendle-pt",
        "primary_source":      "basis_trade",
        "secondary_sources":   ["real_cashflow"],
        "confidence":          "HIGH",
        "emissions_share_pct": 0,
        "rationale":           (
            "Principal Tokens lock in a fixed yield by selling away the "
            "variable YT side. The fixed APY is the implied discount on "
            "the underlying SY's future yield (which itself can be "
            "real_cashflow, basis or emissions — but for the PT holder "
            "it is mechanical basis carry until expiry)."
        ),
        "data_sources":        ["bootstrap", "protocol_docs"],
        "classified_at":       _BOOTSTRAP_CLASSIFIED_AT,
    },
    {
        "protocol_slug":       "curve-usdc-usdt",
        "primary_source":      "real_cashflow",
        "secondary_sources":   ["token_emissions"],
        "confidence":          "HIGH",
        "emissions_share_pct": 40,
        "rationale":           (
            "Stableswap LP fees are real swap-volume revenue. Gauge "
            "rewards in CRV (and convex/yearn meta-wrappers) still "
            "account for roughly 40% of headline APY on the USDC/USDT "
            "pool — these are token emissions that can be cut by "
            "governance vote at any epoch."
        ),
        "data_sources":        ["bootstrap", "protocol_docs"],
        "classified_at":       _BOOTSTRAP_CLASSIFIED_AT,
    },
    {
        "protocol_slug":       "uniswap-v3-stable",
        "primary_source":      "real_cashflow",
        "secondary_sources":   [],
        "confidence":          "HIGH",
        "emissions_share_pct": 0,
        "rationale":           (
            "Concentrated-liquidity LP fees are pure swap volume revenue. "
            "No UNI emissions on the stable pools — APY is 100% trading "
            "fees minus impermanent-loss risk."
        ),
        "data_sources":        ["bootstrap", "protocol_docs"],
        "classified_at":       _BOOTSTRAP_CLASSIFIED_AT,
    },
    {
        "protocol_slug":       "ethena-susde",
        "primary_source":      "basis_trade",
        "secondary_sources":   [],
        "confidence":          "HIGH",
        "emissions_share_pct": 0,
        "rationale":           (
            "sUSDe yield is the funding-rate spread captured by Ethena's "
            "delta-neutral perp short against staked ETH/BTC collateral. "
            "APY tracks perp funding markets — can compress sharply (or "
            "turn negative) in bear regimes."
        ),
        "data_sources":        ["bootstrap", "protocol_docs"],
        "classified_at":       _BOOTSTRAP_CLASSIFIED_AT,
    },
    {
        "protocol_slug":       "spark-usdc",
        "primary_source":      "real_cashflow",
        "secondary_sources":   ["rwa"],
        "confidence":          "HIGH",
        "emissions_share_pct": 0,
        "rationale":           (
            "Spark USDC supply rate is the SparkLend lending spread plus "
            "the DAI Savings Rate inheritance (which is RWA-backed via "
            "Maker's allocator vaults). No SPK emissions on the supply "
            "side at the current sub-system."
        ),
        "data_sources":        ["bootstrap", "protocol_docs"],
        "classified_at":       _BOOTSTRAP_CLASSIFIED_AT,
    },
    {
        "protocol_slug":       "fluid-usdc",
        "primary_source":      "real_cashflow",
        "secondary_sources":   [],
        "confidence":          "MEDIUM",
        "emissions_share_pct": 10,
        "rationale":           (
            "Fluid (Instadapp) lending vault — APY is borrower-paid "
            "interest on the smart-collateral / smart-debt design. Small "
            "FLUID/INST incentives layered on top for top-up pools."
        ),
        "data_sources":        ["bootstrap", "protocol_docs"],
        "classified_at":       _BOOTSTRAP_CLASSIFIED_AT,
    },
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

# Aliases mapping free-form protocol names to canonical SPA slugs used by the
# yield classifier. Distinct from audit_reader's alias map because this set
# is pool-granular (curve-usdc-usdt vs curve-finance, pendle-pt vs pendle).
_PROTOCOL_ALIASES: dict[str, str] = {
    "aave":                "aave-v3",
    "aave-v2":             "aave-v3",
    "aave-v3":             "aave-v3",
    "aave-protocol":       "aave-v3",
    "aave-protocol-v3":    "aave-v3",
    "compound":            "compound-v3",
    "compound-iii":        "compound-v3",
    "compound-v3":         "compound-v3",
    "comet":               "compound-v3",
    "morpho":              "morpho",
    "morpho-blue":         "morpho",
    "morpho-aave":         "morpho",
    "morpho-vaults":       "morpho",
    "yearn":               "yearn-v3",
    "yearn-v3":            "yearn-v3",
    "yearn-finance":       "yearn-v3",
    "sky":                 "sky",
    "sky-protocol":        "sky",
    "susds":               "sky",
    "usds":                "sky",
    "maker":               "sky",
    "makerdao":            "sky",
    "mcd":                 "sky",
    "maple":               "maple",
    "maple-finance":       "maple",
    "syrup":               "maple",
    "euler":               "euler-v2",
    "euler-v2":            "euler-v2",
    "euler-finance":       "euler-v2",
    "evc":                 "euler-v2",
    "pendle":              "pendle-pt",
    "pendle-pt":           "pendle-pt",
    "pendle-finance":      "pendle-pt",
    "curve":               "curve-usdc-usdt",
    "curve-finance":       "curve-usdc-usdt",
    "curve-usdc-usdt":     "curve-usdc-usdt",
    "3pool":               "curve-usdc-usdt",
    "uniswap":             "uniswap-v3-stable",
    "uniswap-v3":          "uniswap-v3-stable",
    "uniswap-v3-stable":   "uniswap-v3-stable",
    "univ3":               "uniswap-v3-stable",
    "ethena":              "ethena-susde",
    "ethena-susde":        "ethena-susde",
    "susde":               "ethena-susde",
    "spark":               "spark-usdc",
    "spark-usdc":          "spark-usdc",
    "sparklend":           "spark-usdc",
    "fluid":               "fluid-usdc",
    "fluid-usdc":          "fluid-usdc",
    "instadapp":           "fluid-usdc",
}


# ─── YieldClassifierAgent ─────────────────────────────────────────────────────

class YieldClassifierAgent:
    """
    Classify the yield source of every SPA whitelist protocol and emit a
    per-protocol JSON snapshot for the Risk Scoring Engine + S2/S3
    strategies.

    The agent is fully offline-tolerant — every network call falls back to
    BOOTSTRAP_CLASSIFICATIONS on any failure. In v1.0 the agent has no
    active network fetcher: all classifications come from the curated
    bootstrap set. The fetch hook is wired in for future LLM-backed
    enrichment without changing callers.
    """

    def __init__(self,
                 output_file: str | Path = DEFAULT_OUTPUT_PATH,
                 risk_scores_file: str | Path = DEFAULT_RISK_SCORES_PATH):
        self.output_file = Path(output_file)
        self.risk_scores_file = Path(risk_scores_file)
        # Track whether the last classify run had to fall back to bootstrap.
        self._fallback_used: bool = False
        self._sources_used: list[str] = []

    # ── Public helpers ────────────────────────────────────────────────────

    def _normalize_protocol_name(self, name: Optional[str]) -> str:
        """
        Map a free-form protocol name to a canonical SPA slug.

        Examples:
            "Aave Protocol V3"   -> "aave-v3"
            "Compound III"       -> "compound-v3"
            "Curve USDC/USDT"    -> "curve-usdc-usdt"
            "sUSDe"              -> "ethena-susde"
            ""                   -> ""
            None                 -> ""
        """
        if not name:
            return ""
        s = str(name).strip().lower()
        s = re.sub(r"\biii\b", "v3", s)
        s = re.sub(r"\bii\b", "v2", s)
        s = _NORMALISE_RE.sub("-", s).strip("-")
        if s in _PROTOCOL_ALIASES:
            return _PROTOCOL_ALIASES[s]
        # Try the longest matching alias prefix
        best: Optional[str] = None
        for alias in _PROTOCOL_ALIASES:
            if s.startswith(alias + "-") or s == alias:
                if best is None or len(alias) > len(best):
                    best = alias
        if best is not None:
            return _PROTOCOL_ALIASES[best]
        return s

    @staticmethod
    def _coerce_primary_source(raw: Optional[str]) -> str:
        """Coerce a free-form yield-source label to a canonical one."""
        if not raw:
            return "unknown"
        s = str(raw).strip().lower().replace("-", "_")
        # Direct hits
        if s in YIELD_SOURCES:
            return s
        # Common synonyms
        synonyms = {
            "lending":             "real_cashflow",
            "cashflow":            "real_cashflow",
            "interest":            "real_cashflow",
            "spread":              "real_cashflow",
            "fees":                "real_cashflow",
            "swap_fees":           "real_cashflow",
            "emissions":           "token_emissions",
            "rewards":             "token_emissions",
            "incentives":          "token_emissions",
            "points":              "points_farming",
            "pre_tge":             "points_farming",
            "basis":               "basis_trade",
            "funding":             "basis_trade",
            "perp":                "basis_trade",
            "real_world":          "rwa",
            "real_world_asset":    "rwa",
            "treasury":            "rwa",
            "treasuries":          "rwa",
        }
        return synonyms.get(s, "unknown")

    @staticmethod
    def _coerce_confidence(raw: Optional[str]) -> str:
        """Coerce a free-form confidence label to HIGH / MEDIUM / LOW."""
        if not raw:
            return "LOW"
        s = str(raw).strip().upper()
        if s in CONFIDENCE_LEVELS:
            return s
        if s in ("H", "HI"):
            return "HIGH"
        if s in ("M", "MED"):
            return "MEDIUM"
        if s in ("L", "LO"):
            return "LOW"
        return "LOW"

    @staticmethod
    def _clamp_emissions_pct(raw: Any) -> int:
        """Clamp emissions share into the [0, 100] integer range."""
        try:
            v = int(round(float(raw)))
        except (TypeError, ValueError):
            return 0
        if v < 0:
            return 0
        if v > 100:
            return 100
        return v

    # ── Source fetchers (with fallback) ───────────────────────────────────

    def _http_get_text(self, url: str,
                       timeout: int = FETCH_TIMEOUT_S) -> Optional[str]:
        """GET ``url`` and return body as str, or None on any error."""
        last_err: Optional[str] = None
        for attempt in range(FETCH_MAX_ATTEMPTS):
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "spa-yield-classifier/1.0"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except (urllib.error.URLError, urllib.error.HTTPError,
                    ValueError, OSError) as e:
                last_err = f"{type(e).__name__}: {e}"
                if attempt < FETCH_MAX_ATTEMPTS - 1:
                    import time
                    time.sleep(FETCH_BACKOFF_BASE ** attempt)
        log.warning("yield fetch failed (%s): %s", url, last_err)
        return None

    def _fetch_remote_classifications(self, offline: bool = False
                                       ) -> list[dict[str, Any]]:
        """
        Hook for future LLM-/network-backed yield classification.

        In v1.0 there is no canonical machine-readable source for
        yield-source taxonomy across DeFi, so this method always returns
        an empty list and the agent ends up using BOOTSTRAP_CLASSIFICATIONS.
        Wired in early so that callers don't have to change when a real
        fetcher is added.
        """
        if offline:
            return []
        # Intentionally no remote fetch in v1.0 — keep stub for future.
        return []

    # ── Core classification ───────────────────────────────────────────────

    def _bootstrap_records(self) -> list[dict[str, Any]]:
        """Return a deep-copied list of BOOTSTRAP_CLASSIFICATIONS."""
        out: list[dict[str, Any]] = []
        for rec in BOOTSTRAP_CLASSIFICATIONS:
            out.append({
                "protocol_slug":       rec["protocol_slug"],
                "primary_source":      rec.get("primary_source", "unknown"),
                "secondary_sources":   list(rec.get("secondary_sources", []) or []),
                "confidence":          rec.get("confidence", "LOW"),
                "emissions_share_pct": rec.get("emissions_share_pct", 0),
                "rationale":           rec.get("rationale", ""),
                "data_sources":        list(rec.get("data_sources",
                                                    ["bootstrap"]) or []),
                "classified_at":       rec.get("classified_at",
                                               _BOOTSTRAP_CLASSIFIED_AT),
            })
        return out

    def classify_one(self, protocol_slug: str) -> YieldClassification:
        """
        Classify a single protocol slug. Returns an "unknown" classification
        (does not raise) for slugs absent from the bootstrap set.
        """
        if not protocol_slug:
            return YieldClassification(
                protocol_slug="",
                primary_source="unknown",
                confidence="LOW",
                rationale="empty slug",
                data_sources=["bootstrap"],
                classified_at=_BOOTSTRAP_CLASSIFIED_AT,
            )
        for rec in self._bootstrap_records():
            if rec["protocol_slug"] == protocol_slug:
                return YieldClassification(
                    protocol_slug=protocol_slug,
                    primary_source=self._coerce_primary_source(
                        rec["primary_source"]),
                    secondary_sources=[
                        self._coerce_primary_source(s)
                        for s in rec["secondary_sources"]
                    ],
                    confidence=self._coerce_confidence(rec["confidence"]),
                    emissions_share_pct=self._clamp_emissions_pct(
                        rec["emissions_share_pct"]),
                    rationale=str(rec.get("rationale", "")),
                    data_sources=list(rec.get("data_sources", ["bootstrap"])),
                    classified_at=str(rec.get("classified_at",
                                              _BOOTSTRAP_CLASSIFIED_AT)),
                )
        # Not in bootstrap — return unknown, never raise.
        return YieldClassification(
            protocol_slug=protocol_slug,
            primary_source="unknown",
            confidence="LOW",
            rationale=(
                f"No bootstrap classification for {protocol_slug!r}. "
                "Add an entry to BOOTSTRAP_CLASSIFICATIONS."
            ),
            data_sources=["bootstrap"],
            classified_at=_BOOTSTRAP_CLASSIFIED_AT,
        )

    def classify_all(self, *, offline: bool = False
                      ) -> dict[str, YieldClassification]:
        """
        Classify every SPA whitelist protocol.

        This method NEVER raises. On any error during the (currently stub)
        remote fetch it falls back to BOOTSTRAP_CLASSIFICATIONS and sets
        ``self._fallback_used = True``.

        Returns a dict keyed by canonical SPA slug. Every SPA whitelist
        slug is guaranteed to be present.
        """
        sources_used: list[str] = []
        remote_records: list[dict[str, Any]] = []
        fallback = False

        try:
            remote_records = self._fetch_remote_classifications(offline=offline)
            if remote_records:
                sources_used.append("remote")
        except Exception as e:  # pragma: no cover (defensive)
            log.warning("remote classification fetch raised: %s", e)
            remote_records = []

        bs_records = self._bootstrap_records()
        sources_used.append("bootstrap")
        if not remote_records:
            fallback = True

        # Build a slug -> dict map. Bootstrap is the authoritative baseline;
        # remote records (if any) can override individual fields.
        merged: dict[str, dict[str, Any]] = {
            rec["protocol_slug"]: rec for rec in bs_records
        }
        for rec in remote_records:
            slug = self._normalize_protocol_name(rec.get("protocol_slug")
                                                 or rec.get("protocol"))
            if not slug or slug not in merged:
                # Skip non-whitelist remote rows — never silently add slugs.
                continue
            for k, v in rec.items():
                if k in ("protocol_slug", "protocol"):
                    continue
                merged[slug][k] = v

        # Build classification dataclasses for every whitelist slug.
        classifications: dict[str, YieldClassification] = {}
        for slug in SPA_WHITELIST:
            rec = merged.get(slug)
            if rec is None:
                classifications[slug] = YieldClassification(
                    protocol_slug=slug,
                    primary_source="unknown",
                    confidence="LOW",
                    rationale=(
                        f"No bootstrap entry for {slug!r} — bug in "
                        "BOOTSTRAP_CLASSIFICATIONS."
                    ),
                    data_sources=["bootstrap"],
                    classified_at=_BOOTSTRAP_CLASSIFIED_AT,
                )
                continue
            classifications[slug] = YieldClassification(
                protocol_slug=slug,
                primary_source=self._coerce_primary_source(
                    rec.get("primary_source")),
                secondary_sources=[
                    self._coerce_primary_source(s)
                    for s in (rec.get("secondary_sources") or [])
                ],
                confidence=self._coerce_confidence(rec.get("confidence")),
                emissions_share_pct=self._clamp_emissions_pct(
                    rec.get("emissions_share_pct", 0)),
                rationale=str(rec.get("rationale", "")),
                data_sources=list(rec.get("data_sources", ["bootstrap"]) or
                                  ["bootstrap"]),
                classified_at=str(rec.get("classified_at",
                                          _BOOTSTRAP_CLASSIFIED_AT)),
            )

        self._fallback_used = fallback
        # Deduplicate sources_used while preserving order
        deduped: list[str] = []
        for s in sources_used:
            if s not in deduped:
                deduped.append(s)
        self._sources_used = deduped
        return classifications

    # ── Snapshot construction ─────────────────────────────────────────────

    def _build_snapshot(self, classifications: dict[str, YieldClassification]
                         ) -> dict[str, Any]:
        """Convert classifications dict to the canonical JSON snapshot."""
        # Sort protocol keys deterministically.
        protocols_out: dict[str, Any] = {}
        for slug in sorted(classifications.keys()):
            protocols_out[slug] = classifications[slug].to_dict()

        # Summary counters
        by_primary: dict[str, int] = {src: 0 for src in YIELD_SOURCES}
        high_emissions = 0
        unknown = 0
        for c in classifications.values():
            by_primary[c.primary_source] = by_primary.get(c.primary_source, 0) + 1
            if c.emissions_share_pct > 50:
                high_emissions += 1
            if c.primary_source == "unknown":
                unknown += 1

        return {
            "generated_at": datetime.now(timezone.utc).isoformat().replace(
                "+00:00", "Z"),
            "agent_version": AGENT_VERSION,
            "sources": list(self._sources_used) if self._sources_used
                else ["bootstrap"],
            "fallback_used": bool(self._fallback_used),
            "protocols": protocols_out,
            "summary": {
                "total_protocols":      len(protocols_out),
                "by_primary_source":    {k: by_primary[k]
                                          for k in sorted(by_primary.keys())},
                "high_emissions_count": high_emissions,
                "unknown_count":        unknown,
            },
        }

    # ── Export ────────────────────────────────────────────────────────────

    def export(self, *, dry_run: bool = False,
               offline: bool = False) -> dict[str, Any]:
        """
        Build the snapshot and (unless dry_run) write it to ``output_file``.

        Returns the snapshot dict (always — even on dry_run).
        Never raises — on any error the snapshot is still returned, possibly
        with ``fallback_used = True``.
        """
        try:
            classifications = self.classify_all(offline=offline)
        except Exception as e:  # pragma: no cover (defensive)
            log.error("classify_all raised unexpectedly: %s", e)
            classifications = {slug: YieldClassification(protocol_slug=slug)
                                for slug in SPA_WHITELIST}
            self._fallback_used = True
            self._sources_used = ["bootstrap"]

        snapshot = self._build_snapshot(classifications)

        if dry_run:
            log.info("--dry-run: not writing %s", self.output_file)
            return snapshot

        try:
            self.output_file.parent.mkdir(parents=True, exist_ok=True)
            self.output_file.write_text(
                json.dumps(snapshot, indent=2, sort_keys=False,
                            ensure_ascii=False),
                encoding="utf-8",
            )
            log.info("Wrote %d protocols to %s",
                     snapshot["summary"]["total_protocols"], self.output_file)
        except OSError as e:
            log.error("Failed to write %s: %s", self.output_file, e)

        return snapshot

    # ── Optional risk_scores.json enrichment ──────────────────────────────

    def enrich_risk_scores(self, snapshot: Optional[dict[str, Any]] = None,
                            *, dry_run: bool = False) -> bool:
        """
        If ``data/risk_scores.json`` exists, merge ``yield_source`` (set to
        ``primary_source``) into every per-protocol entry.

        Supports both schemas:
          * ``{"protocols": {slug: {...}}}``  (canonical Risk Engine snapshot)
          * ``{"scores": [{"slug": ..., ...}, ...]}``  (legacy list form)

        Returns True on a successful (non-dry-run) write or successful
        dry_run merge, False if the file is missing / unreadable / had no
        applicable entries. NEVER raises.
        """
        path = self.risk_scores_file
        if not path.exists():
            log.debug("risk_scores.json not found at %s — skipping enrichment",
                      path)
            return False

        try:
            text = path.read_text(encoding="utf-8")
            doc = json.loads(text)
        except (OSError, ValueError) as e:
            log.debug("risk_scores.json unreadable (%s) — skipping enrichment",
                      e)
            return False

        if not isinstance(doc, dict):
            log.debug("risk_scores.json is not a JSON object — skipping")
            return False

        if snapshot is None:
            try:
                snapshot = self._build_snapshot(self.classify_all(offline=True))
            except Exception as e:  # pragma: no cover (defensive)
                log.warning("classify_all raised during enrichment: %s", e)
                return False

        protocols_block = snapshot.get("protocols") or {}
        slug_to_source: dict[str, str] = {
            slug: rec.get("primary_source", "unknown")
            for slug, rec in protocols_block.items()
        }
        if not slug_to_source:
            return False

        merged_any = False

        # Schema A: { "protocols": { slug: {...} } }
        if isinstance(doc.get("protocols"), dict):
            for slug, entry in doc["protocols"].items():
                src = slug_to_source.get(slug)
                if src and isinstance(entry, dict):
                    entry["yield_source"] = src
                    merged_any = True

        # Schema B: { "scores": [ {"slug": ...}, ... ] }
        if isinstance(doc.get("scores"), list):
            for entry in doc["scores"]:
                if not isinstance(entry, dict):
                    continue
                slug = entry.get("slug") or entry.get("protocol_slug")
                src = slug_to_source.get(slug) if slug else None
                if src:
                    entry["yield_source"] = src
                    merged_any = True

        if not merged_any:
            log.debug("risk_scores.json had no slugs matching yield set")
            return False

        if dry_run:
            log.info("--dry-run: would enrich %s", path)
            return True

        try:
            path.write_text(
                json.dumps(doc, indent=2, sort_keys=False, ensure_ascii=False),
                encoding="utf-8",
            )
            log.info("Enriched %s with yield_source field", path)
            return True
        except OSError as e:
            log.warning("Failed to write %s: %s", path, e)
            return False


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _cli(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Yield Classifier Agent (FEAT-RISK-003) — produce "
                    "data/yield_sources.json",
    )
    parser.add_argument("--offline", action="store_true",
                        help="Skip network — use BOOTSTRAP_CLASSIFICATIONS only.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build snapshot but do not write to disk.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH,
                        help="Output path (default: data/yield_sources.json)")
    parser.add_argument("--risk-scores", type=Path,
                        default=DEFAULT_RISK_SCORES_PATH,
                        help="Path to risk_scores.json for optional enrichment.")
    parser.add_argument("--no-enrich", action="store_true",
                        help="Skip optional risk_scores.json enrichment.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    agent = YieldClassifierAgent(
        output_file=args.output,
        risk_scores_file=args.risk_scores,
    )
    snapshot = agent.export(dry_run=args.dry_run, offline=args.offline)

    if not args.no_enrich:
        agent.enrich_risk_scores(snapshot=snapshot, dry_run=args.dry_run)

    log.info(
        "Done — %d protocols, by_primary=%s, high_emissions=%d, unknown=%d, "
        "fallback=%s",
        snapshot["summary"]["total_protocols"],
        snapshot["summary"]["by_primary_source"],
        snapshot["summary"]["high_emissions_count"],
        snapshot["summary"]["unknown_count"],
        snapshot["fallback_used"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
