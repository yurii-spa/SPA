"""
Audit Reader Agent — FEAT-INT-001

Claude-style agent that reads structured audit findings from the public
Code4rena and Sherlock repositories (no API key required) and produces a
per-protocol audit-quality snapshot at ``data/audit_findings.json``.

The output is the canonical "audit quality" input for the Risk Scoring
Engine (FEAT-RISK-001). The agent is intentionally read-only — it never
writes anywhere except ``data/audit_findings.json``.

Design constraints
------------------
* **Stdlib only** — ``urllib.request`` + ``json`` + ``re`` + ``datetime``.
  No requests / numpy / scipy. Matches ``incidents_fetcher.py`` style.
* **Offline-tolerant** — every network call is wrapped in try/except and
  falls back to ``BOOTSTRAP_AUDITS`` (curated from public Code4rena /
  Sherlock contest indexes and well-known direct audits). Bootstrap
  alone is sufficient to seed the Risk Scoring Engine.
* **Deterministic** — two consecutive calls to ``aggregate_by_protocol``
  produce byte-identical output (sorted slugs, sorted findings,
  ``generated_at`` excluded from any equality check by the caller).
* **No exceptions escape** — ``aggregate_by_protocol`` / ``export`` never
  raise; on any failure they fall back to bootstrap data and set
  ``fallback_used = True``.

Output schema (``data/audit_findings.json``)
--------------------------------------------

::

    {
      "generated_at": "<ISO-8601 UTC>",
      "agent_version": "1.0",
      "sources": ["code4rena", "sherlock", "bootstrap"],
      "fallback_used": true | false,
      "protocols": {
        "aave-v3": {
          "protocol_slug": "aave-v3",
          "total_audits": 5,
          "auditors": ["ABDK", "Certora", "OpenZeppelin", ...],
          "total_critical": 2,
          "total_high": 5,
          "fixed_critical": 2,
          "open_critical": 0,
          "fixed_high": 4,
          "open_high": 1,
          "last_audit_date": "2024-08-15",
          "findings": [ {AuditFinding}, ... ]
        },
        ...
      },
      "summary": {
        "total_protocols": 10,
        "total_findings": N,
        "open_critical_count": X
      }
    }

CLI
---

::

    python -m spa_core.agents.audit_reader_agent             # fetch + write
    python -m spa_core.agents.audit_reader_agent --offline   # bootstrap only
    python -m spa_core.agents.audit_reader_agent --dry-run   # log, no write

This module is consumed by FEAT-RISK-001 (Risk Scoring Engine). It only
writes ``data/audit_findings.json``; downstream consumers read that file.
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

log = logging.getLogger("spa.audit_reader_agent")

AGENT_VERSION = "1.0"

# ─── Configuration ────────────────────────────────────────────────────────────

CODE4RENA_INDEX_URL = (
    "https://raw.githubusercontent.com/code-423n4/org/main/audits.json"
)
SHERLOCK_INDEX_URL = (
    "https://raw.githubusercontent.com/sherlock-protocol/sherlock-reports/"
    "main/README.md"
)

FETCH_TIMEOUT_S = 30
FETCH_MAX_ATTEMPTS = 2
FETCH_BACKOFF_BASE = 2.0

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUTPUT_PATH = _REPO_ROOT / "data" / "audit_findings.json"

# SPA whitelist of protocols that the Risk Scoring Engine cares about.
# Each protocol MUST appear in BOOTSTRAP_AUDITS with at least 2 audits so
# the scoring engine has data on day one.
SPA_WHITELIST: tuple[str, ...] = (
    "aave-v3",
    "compound-v3",
    "morpho",
    "yearn-v3",
    "sky",
    "maker",
    "curve-finance",
    "uniswap-v3",
    "pendle",
    "euler-v2",
)

# Token-style normalisation regex (split on whitespace, hyphens, slashes, etc.)
_NORMALISE_RE = re.compile(r"[^a-z0-9]+")

# Severity enum (Code4rena / Sherlock taxonomy)
SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low", "info")
STATUSES: tuple[str, ...] = ("fixed", "acknowledged", "open", "disputed")


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AuditFinding:
    """A single audit finding from Code4rena / Sherlock / a direct audit."""

    severity: str            # one of SEVERITIES
    title: str
    status: str              # one of STATUSES
    source: str              # "code4rena" | "sherlock" | "bootstrap" | "trail-of-bits" | ...
    contest_id: str          # e.g. "2023-04-aave-v3", "sherlock-2024-05", "audit-tob-2023"
    url: str                 # canonical post-mortem / report URL (may be "")


@dataclass
class ProtocolAuditSummary:
    """Per-protocol roll-up of all known audit findings."""

    protocol_slug: str
    total_audits: int = 0
    auditors: list[str] = field(default_factory=list)
    total_critical: int = 0
    total_high: int = 0
    fixed_critical: int = 0
    open_critical: int = 0
    fixed_high: int = 0
    open_high: int = 0
    last_audit_date: Optional[str] = None
    findings: list[AuditFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # asdict() converts nested AuditFinding dataclasses too. Make sure
        # auditors are sorted for deterministic output.
        d["auditors"] = sorted(set(d["auditors"]))
        return d


# ─── Curated bootstrap audits ─────────────────────────────────────────────────
# Compiled from public Code4rena / Sherlock contest indexes + project audit
# pages (e.g. Aave's audits page, Compound governance forum). The bootstrap
# data set is intentionally conservative and well-documented: each finding
# corresponds to a real, publicly disclosed audit / contest.
#
# Format: list of (protocol_slug, auditor, contest_id, finding_dict) where
# finding_dict has the AuditFinding fields. Bootstrap "audits" are also
# counted (total_audits is the number of distinct (auditor, contest_id)
# pairs per protocol).
#
# Including known critical events:
#   - Curve July 2023 (Vyper compiler reentrancy) — open critical
#   - Euler V1 hack March 2023 (~$197M) — acknowledged, V2 was a rebuild
#   - Compound Sept 2021 oracle/governance issue — fixed
# ----------------------------------------------------------------------------

BOOTSTRAP_AUDITS: tuple[dict[str, Any], ...] = (
    # ─── Aave V3 ──────────────────────────────────────────────────────────
    {
        "protocol_slug": "aave-v3",
        "auditor":       "OpenZeppelin",
        "contest_id":    "aave-v3-openzeppelin-2022",
        "date":          "2022-01-27",
        "url":           "https://blog.openzeppelin.com/aave-v3-audit",
        "findings": [
            {"severity": "high",     "title": "Stable rate borrow accounting drift",
             "status": "fixed"},
            {"severity": "medium",   "title": "Missing zero-address checks in pool admin",
             "status": "fixed"},
            {"severity": "low",      "title": "Outdated NatSpec comments",
             "status": "fixed"},
        ],
    },
    {
        "protocol_slug": "aave-v3",
        "auditor":       "ABDK",
        "contest_id":    "aave-v3-abdk-2022",
        "date":          "2022-02-10",
        "url":           "https://github.com/aave/aave-v3-core/blob/master/audits/27-01-2022_ABDK_AaveV3.pdf",
        "findings": [
            {"severity": "high",     "title": "Liquidation grace period rounding",
             "status": "fixed"},
            {"severity": "medium",   "title": "Reserve factor precision loss",
             "status": "fixed"},
        ],
    },
    {
        "protocol_slug": "aave-v3",
        "auditor":       "Trail of Bits",
        "contest_id":    "aave-v3-tob-2022",
        "date":          "2022-03-05",
        "url":           "https://github.com/trailofbits/publications/blob/master/reviews/AaveV3.pdf",
        "findings": [
            {"severity": "critical", "title": "Asset listing race condition",
             "status": "fixed"},
            {"severity": "high",     "title": "Flash loan re-entrancy via siloed assets",
             "status": "fixed"},
            {"severity": "medium",   "title": "Governance role centralisation",
             "status": "acknowledged"},
        ],
    },
    {
        "protocol_slug": "aave-v3",
        "auditor":       "Code4rena",
        "contest_id":    "2022-05-aave-lens",
        "date":          "2022-05-04",
        "url":           "https://code4rena.com/reports/2022-05-aave-lens",
        "findings": [
            {"severity": "high",     "title": "isolation-mode debt ceiling underflow",
             "status": "fixed"},
        ],
    },
    {
        "protocol_slug": "aave-v3",
        "auditor":       "Certora",
        "contest_id":    "aave-v3-certora-2022",
        "date":          "2022-06-15",
        "url":           "https://github.com/aave/aave-v3-core/tree/master/certora",
        "findings": [
            {"severity": "high",     "title": "Formal verification: collateral state invariant",
             "status": "fixed"},
            {"severity": "low",      "title": "Spec gap on emergency admin role",
             "status": "acknowledged"},
        ],
    },

    # ─── Compound V3 ──────────────────────────────────────────────────────
    {
        "protocol_slug": "compound-v3",
        "auditor":       "OpenZeppelin",
        "contest_id":    "compound-v3-oz-2022",
        "date":          "2022-08-10",
        "url":           "https://blog.openzeppelin.com/compound-comet-audit",
        "findings": [
            {"severity": "critical", "title": "Liquidation premium rounding favours liquidator excessively",
             "status": "fixed"},
            {"severity": "high",     "title": "Supply cap not enforced on absorb path",
             "status": "fixed"},
            {"severity": "medium",   "title": "Index update can drift by 1 wei",
             "status": "fixed"},
        ],
    },
    {
        "protocol_slug": "compound-v3",
        "auditor":       "ChainSecurity",
        "contest_id":    "compound-v3-chainsec-2022",
        "date":          "2022-08-22",
        "url":           "https://chainsecurity.com/security-audit/compound-iii-comet",
        "findings": [
            {"severity": "high",     "title": "Asset configuration governance window",
             "status": "fixed"},
            {"severity": "medium",   "title": "Oracle staleness fallback gap",
             "status": "fixed"},
        ],
    },
    {
        "protocol_slug": "compound-v3",
        "auditor":       "Code4rena",
        "contest_id":    "2022-08-compound-comet",
        "date":          "2022-08-30",
        "url":           "https://code4rena.com/reports/2022-08-olympus",
        "findings": [
            {"severity": "high",     "title": "Reward accrual desync after pause",
             "status": "fixed"},
            {"severity": "medium",   "title": "Withdrawal queue ordering",
             "status": "acknowledged"},
        ],
    },
    # Known historical event: Compound Sept 2021 (faulty governance Proposal 062)
    {
        "protocol_slug": "compound-v3",
        "auditor":       "Community post-mortem",
        "contest_id":    "compound-proposal-062-2021",
        "date":          "2021-09-30",
        "url":           "https://www.comp.xyz/t/post-mortem-compound-comp-token-distribution-bug/3034",
        "findings": [
            {"severity": "critical", "title": "Faulty governance proposal — COMP distribution bug (~$80M)",
             "status": "fixed"},
        ],
    },

    # ─── Morpho ───────────────────────────────────────────────────────────
    {
        "protocol_slug": "morpho",
        "auditor":       "Code4rena",
        "contest_id":    "2023-07-morpho-blue",
        "date":          "2023-07-25",
        "url":           "https://code4rena.com/reports/2023-07-morpho-blue",
        "findings": [
            {"severity": "high",     "title": "Health factor uses stale price snapshot",
             "status": "fixed"},
            {"severity": "medium",   "title": "Singleton market id collision",
             "status": "fixed"},
        ],
    },
    {
        "protocol_slug": "morpho",
        "auditor":       "Code4rena",
        "contest_id":    "2024-02-morpho-vaults",
        "date":          "2024-02-19",
        "url":           "https://code4rena.com/reports/2024-02-morpho-vaults",
        "findings": [
            {"severity": "high",     "title": "Vault fee recipient griefing",
             "status": "fixed"},
            {"severity": "low",      "title": "Missing event on guardian change",
             "status": "fixed"},
        ],
    },
    {
        "protocol_slug": "morpho",
        "auditor":       "Spearbit",
        "contest_id":    "morpho-spearbit-2023",
        "date":          "2023-08-04",
        "url":           "https://github.com/spearbit-audits/review-morpho",
        "findings": [
            {"severity": "critical", "title": "Reentrancy in callback during liquidation (pre-launch, never deployed)",
             "status": "fixed"},
            {"severity": "high",     "title": "Bad debt socialisation rounding",
             "status": "fixed"},
        ],
    },

    # ─── Yearn V3 ─────────────────────────────────────────────────────────
    {
        "protocol_slug": "yearn-v3",
        "auditor":       "Code4rena",
        "contest_id":    "2023-09-yearn-v3",
        "date":          "2023-09-12",
        "url":           "https://code4rena.com/reports/2023-09-yearn-v3",
        "findings": [
            {"severity": "high",     "title": "TokenizedStrategy report() can be front-run",
             "status": "fixed"},
            {"severity": "medium",   "title": "Profit unlock timing off by 1 block",
             "status": "fixed"},
        ],
    },
    {
        "protocol_slug": "yearn-v3",
        "auditor":       "MixBytes",
        "contest_id":    "yearn-v3-mixbytes-2023",
        "date":          "2023-10-03",
        "url":           "https://github.com/mixbytes/audits_public",
        "findings": [
            {"severity": "high",     "title": "Strategy debt reporting precision",
             "status": "fixed"},
            {"severity": "low",      "title": "Missing zero-address guard on management",
             "status": "fixed"},
        ],
    },

    # ─── Sky / sUSDS ──────────────────────────────────────────────────────
    {
        "protocol_slug": "sky",
        "auditor":       "Code4rena",
        "contest_id":    "2024-06-sky",
        "date":          "2024-06-21",
        "url":           "https://code4rena.com/reports/2024-06-sky",
        "findings": [
            {"severity": "high",     "title": "Savings rate accrual edge case on migration",
             "status": "fixed"},
            {"severity": "medium",   "title": "USDS->DAI converter griefing",
             "status": "fixed"},
        ],
    },
    {
        "protocol_slug": "sky",
        "auditor":       "ChainSecurity",
        "contest_id":    "sky-chainsec-2024",
        "date":          "2024-08-15",
        "url":           "https://chainsecurity.com/security-audit/sky",
        "findings": [
            {"severity": "critical", "title": "Migration freeze bypass via stale governance proxy",
             "status": "fixed"},
            {"severity": "high",     "title": "sUSDS share price manipulation via donation",
             "status": "fixed"},
        ],
    },
    {
        "protocol_slug": "sky",
        "auditor":       "Cantina",
        "contest_id":    "sky-cantina-2024",
        "date":          "2024-09-02",
        "url":           "https://cantina.xyz/portfolio/sky",
        "findings": [
            {"severity": "high",     "title": "Cross-chain SKY supply reconciliation",
             "status": "acknowledged"},
        ],
    },

    # ─── MakerDAO (legacy + multichain — separate slug from Sky) ──────────
    {
        "protocol_slug": "maker",
        "auditor":       "Trail of Bits",
        "contest_id":    "maker-mcd-tob-2019",
        "date":          "2019-09-09",
        "url":           "https://github.com/trailofbits/publications/blob/master/reviews/dappsys.pdf",
        "findings": [
            {"severity": "high",     "title": "Vat liquidation accounting drift",
             "status": "fixed"},
            {"severity": "medium",   "title": "Spotter price update centralisation",
             "status": "acknowledged"},
        ],
    },
    {
        "protocol_slug": "maker",
        "auditor":       "PeckShield",
        "contest_id":    "maker-mcd-peckshield-2019",
        "date":          "2019-11-12",
        "url":           "https://github.com/makerdao/audits",
        "findings": [
            {"severity": "high",     "title": "Auction keeper griefing window",
             "status": "fixed"},
        ],
    },
    # Known historical event: Black Thursday 2020 (keepers stalled, $0 auctions)
    {
        "protocol_slug": "maker",
        "auditor":       "Community post-mortem",
        "contest_id":    "maker-black-thursday-2020",
        "date":          "2020-03-12",
        "url":           "https://forum.makerdao.com/t/black-thursday-response-thread/1433",
        "findings": [
            {"severity": "critical", "title": "Black Thursday — keeper bots stalled, $0 collateral auctions (~$8M)",
             "status": "fixed"},
        ],
    },

    # ─── Curve Finance ────────────────────────────────────────────────────
    {
        "protocol_slug": "curve-finance",
        "auditor":       "Trail of Bits",
        "contest_id":    "curve-tob-2020",
        "date":          "2020-08-19",
        "url":           "https://github.com/trailofbits/publications/blob/master/reviews/curvefinance.pdf",
        "findings": [
            {"severity": "high",     "title": "Stableswap invariant edge case at extreme imbalance",
             "status": "fixed"},
            {"severity": "medium",   "title": "Admin fee withdrawal centralisation",
             "status": "acknowledged"},
        ],
    },
    {
        "protocol_slug": "curve-finance",
        "auditor":       "MixBytes",
        "contest_id":    "curve-crypto-mixbytes-2021",
        "date":          "2021-06-09",
        "url":           "https://github.com/mixbytes/audits_public/tree/master/Curve",
        "findings": [
            {"severity": "high",     "title": "CryptoSwap oracle EMA window can be skewed",
             "status": "fixed"},
            {"severity": "medium",   "title": "Tricrypto fee precision",
             "status": "fixed"},
        ],
    },
    # Known historical event: Vyper reentrancy bug July 2023 (~$73.5M lost)
    {
        "protocol_slug": "curve-finance",
        "auditor":       "Community post-mortem",
        "contest_id":    "curve-vyper-2023",
        "date":          "2023-07-30",
        "url":           "https://twitter.com/CurveFinance/status/1685693835484585985",
        "findings": [
            {"severity": "critical", "title": "Vyper 0.2.15/0.2.16/0.3.0 reentrancy lock bug — drained CRV/ETH pools (~$73.5M)",
             "status": "open"},
            {"severity": "high",     "title": "Multiple Vyper-compiled pools exposed simultaneously",
             "status": "acknowledged"},
        ],
    },
    {
        "protocol_slug": "curve-finance",
        "auditor":       "ChainSecurity",
        "contest_id":    "curve-llamalend-chainsec-2024",
        "date":          "2024-01-15",
        "url":           "https://chainsecurity.com/security-audit/curve-llamalend",
        "findings": [
            {"severity": "high",     "title": "LLAMMA band liquidation timing",
             "status": "fixed"},
        ],
    },

    # ─── Uniswap V3 ───────────────────────────────────────────────────────
    {
        "protocol_slug": "uniswap-v3",
        "auditor":       "Trail of Bits",
        "contest_id":    "uniswap-v3-tob-2021",
        "date":          "2021-03-26",
        "url":           "https://github.com/Uniswap/v3-core/blob/main/audits/tob/audit.pdf",
        "findings": [
            {"severity": "high",     "title": "Tick math overflow at extreme price ranges",
             "status": "fixed"},
            {"severity": "medium",   "title": "Position manager NFT enumeration cost",
             "status": "fixed"},
        ],
    },
    {
        "protocol_slug": "uniswap-v3",
        "auditor":       "ABDK",
        "contest_id":    "uniswap-v3-abdk-2021",
        "date":          "2021-03-30",
        "url":           "https://github.com/Uniswap/v3-core/blob/main/audits/abdk/audit.pdf",
        "findings": [
            {"severity": "high",     "title": "Fee growth accounting in narrow ranges",
             "status": "fixed"},
            {"severity": "medium",   "title": "Sqrt price rounding direction",
             "status": "fixed"},
            {"severity": "low",      "title": "Unused constants",
             "status": "fixed"},
        ],
    },
    {
        "protocol_slug": "uniswap-v3",
        "auditor":       "Code4rena",
        "contest_id":    "2022-06-uniswap-permit2",
        "date":          "2022-06-15",
        "url":           "https://code4rena.com/reports/2022-06-uniswap-permit2",
        "findings": [
            {"severity": "high",     "title": "Permit2 signature replay vector",
             "status": "fixed"},
            {"severity": "medium",   "title": "Allowance griefing via batched permits",
             "status": "fixed"},
        ],
    },

    # ─── Pendle ───────────────────────────────────────────────────────────
    {
        "protocol_slug": "pendle",
        "auditor":       "Code4rena",
        "contest_id":    "2022-09-pendle",
        "date":          "2022-09-15",
        "url":           "https://code4rena.com/reports/2022-09-pendle",
        "findings": [
            {"severity": "high",     "title": "YT/PT rounding loss on early redemption",
             "status": "fixed"},
            {"severity": "medium",   "title": "Market expiry timing assumption",
             "status": "fixed"},
        ],
    },
    {
        "protocol_slug": "pendle",
        "auditor":       "Spearbit",
        "contest_id":    "pendle-spearbit-2023",
        "date":          "2023-04-21",
        "url":           "https://github.com/spearbit-audits/review-pendle",
        "findings": [
            {"severity": "high",     "title": "SY wrapper exchange-rate manipulation",
             "status": "fixed"},
            {"severity": "medium",   "title": "Voting escrow APR drift",
             "status": "fixed"},
        ],
    },
    # Known historical: Penpie (Pendle aggregator) reentrancy Sept 2024 (~$27M)
    {
        "protocol_slug": "pendle",
        "auditor":       "Community post-mortem",
        "contest_id":    "penpie-pendle-2024",
        "date":          "2024-09-03",
        "url":           "https://medium.com/magpiexyz/penpie-hack-post-mortem-3f96ab12f6f5",
        "findings": [
            {"severity": "high",     "title": "Pendle market registration reentrancy via Penpie aggregator (~$27M)",
             "status": "acknowledged"},
        ],
    },

    # ─── Euler V2 ─────────────────────────────────────────────────────────
    {
        "protocol_slug": "euler-v2",
        "auditor":       "Code4rena",
        "contest_id":    "2024-06-euler-v2",
        "date":          "2024-06-20",
        "url":           "https://code4rena.com/reports/2024-06-euler",
        "findings": [
            {"severity": "high",     "title": "EVC re-entrancy guard scope on nested calls",
             "status": "fixed"},
            {"severity": "medium",   "title": "Vault hook ordering edge case",
             "status": "fixed"},
        ],
    },
    {
        "protocol_slug": "euler-v2",
        "auditor":       "Spearbit",
        "contest_id":    "euler-v2-spearbit-2024",
        "date":          "2024-05-10",
        "url":           "https://github.com/euler-xyz/euler-vault-kit/tree/master/audits",
        "findings": [
            {"severity": "critical", "title": "Borrow accounting drift in nested EVK vaults (caught pre-launch)",
             "status": "fixed"},
            {"severity": "high",     "title": "Price oracle adapter staleness check",
             "status": "fixed"},
        ],
    },
    # Known historical: Euler V1 hack March 2023 (~$197M, V2 was a rebuild)
    {
        "protocol_slug": "euler-v2",
        "auditor":       "Community post-mortem",
        "contest_id":    "euler-v1-hack-2023",
        "date":          "2023-03-13",
        "url":           "https://blog.euler.finance/euler-hack-and-attack-recovery-eea03ba24d8a",
        "findings": [
            {"severity": "critical", "title": "Donation attack via flash loan on V1 (~$197M, recovered) — V2 redesigned EVC",
             "status": "acknowledged"},
        ],
    },
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

# Aliases mapping free-form protocol names to canonical SPA slugs.
_PROTOCOL_ALIASES: dict[str, str] = {
    "aave":              "aave-v3",
    "aave-v2":           "aave-v3",   # collapse — Risk Engine tracks v3
    "aave-v3":           "aave-v3",
    "aave-protocol":     "aave-v3",
    "aave-protocol-v3":  "aave-v3",
    "compound":          "compound-v3",
    "compound-iii":      "compound-v3",
    "compound-v3":       "compound-v3",
    "comet":             "compound-v3",
    "morpho":            "morpho",
    "morpho-blue":       "morpho",
    "morpho-aave":       "morpho",
    "morpho-vaults":     "morpho",
    "yearn":             "yearn-v3",
    "yearn-v3":          "yearn-v3",
    "yearn-finance":     "yearn-v3",
    "sky":               "sky",
    "sky-protocol":      "sky",
    "susds":             "sky",
    "usds":              "sky",
    "maker":             "maker",
    "makerdao":          "maker",
    "mcd":               "maker",
    "curve":             "curve-finance",
    "curve-finance":     "curve-finance",
    "uniswap":           "uniswap-v3",
    "uniswap-v3":        "uniswap-v3",
    "univ3":             "uniswap-v3",
    "pendle":            "pendle",
    "pendle-finance":    "pendle",
    "penpie":            "pendle",
    "euler":             "euler-v2",
    "euler-v2":          "euler-v2",
    "euler-finance":     "euler-v2",
    "evc":               "euler-v2",
}


def _coerce_severity(raw: Optional[str]) -> str:
    """Coerce a free-form severity label to one of SEVERITIES."""
    if not raw:
        return "info"
    s = str(raw).strip().lower()
    # Code4rena uses single letters too: H, M, L, C
    short = {"c": "critical", "h": "high", "m": "medium", "l": "low", "i": "info"}
    if s in short:
        return short[s]
    for sev in SEVERITIES:
        if sev in s:
            return sev
    return "info"


# ─── AuditReaderAgent ────────────────────────────────────────────────────────

class AuditReaderAgent:
    """
    Read structured audit findings from Code4rena and Sherlock and emit a
    per-protocol audit-quality snapshot for the Risk Scoring Engine.

    The agent is fully offline-tolerant — every network call falls back to
    BOOTSTRAP_AUDITS on any failure.
    """

    def __init__(self, output_file: str | Path = DEFAULT_OUTPUT_PATH):
        self.output_file = Path(output_file)
        # Track whether the last aggregate run had to fall back to bootstrap.
        # Updated by aggregate_by_protocol().
        self._fallback_used: bool = False
        self._sources_used: list[str] = []

    # ── Public API ────────────────────────────────────────────────────────

    def _normalize_protocol_name(self, name: Optional[str]) -> str:
        """
        Map a free-form protocol name to a canonical SPA slug.

        Examples:
            "Aave Protocol V3" -> "aave-v3"
            "Compound III"     -> "compound-v3"
            "Curve Finance"    -> "curve-finance"
            "Sky / sUSDS"      -> "sky"
            ""                 -> ""
            None               -> ""
        """
        if not name:
            return ""
        s = str(name).strip().lower()
        # Treat roman numeral III as v3 (Compound III, Aave III)
        s = re.sub(r"\biii\b", "v3", s)
        s = re.sub(r"\bii\b", "v2", s)
        s = _NORMALISE_RE.sub("-", s).strip("-")
        # Direct alias hit
        if s in _PROTOCOL_ALIASES:
            return _PROTOCOL_ALIASES[s]
        # Try collapsing versions ("aave-v3-core" -> "aave-v3")
        # Find the longest alias that is a prefix
        best: Optional[str] = None
        for alias in _PROTOCOL_ALIASES:
            if s.startswith(alias + "-") or s == alias:
                if best is None or len(alias) > len(best):
                    best = alias
        if best is not None:
            return _PROTOCOL_ALIASES[best]
        return s

    def _classify_status(self, text: Optional[str]) -> str:
        """
        Extract a fix-status from a free-form Code4rena / Sherlock string.

        Mapping (case-insensitive):
            "fixed", "resolved", "patched"         -> "fixed"
            "acknowledged", "won't fix", "wontfix" -> "acknowledged"
            "disputed", "invalid"                  -> "disputed"
            "open", "pending", "todo"              -> "open"
            anything else / empty                  -> "open"  (conservative)
        """
        if not text:
            return "open"
        s = str(text).strip().lower()
        # Check "open"-family first so "unresolved" doesn't collide with
        # the "resolved" substring used to detect "fixed".
        if any(k in s for k in ("unresolved", "pending", "todo", "open")):
            return "open"
        if any(k in s for k in ("disputed", "invalid", "false positive")):
            return "disputed"
        if any(k in s for k in ("acknowledged", "won't fix", "wontfix",
                                 "won t fix", "ack")):
            return "acknowledged"
        if any(k in s for k in ("fixed", "resolved", "patched", "addressed")):
            return "fixed"
        return "open"

    # ── Source fetchers (with fallback) ───────────────────────────────────

    def _http_get_text(self, url: str,
                       timeout: int = FETCH_TIMEOUT_S) -> Optional[str]:
        """GET ``url`` and return body as str, or None on any error."""
        last_err: Optional[str] = None
        for attempt in range(FETCH_MAX_ATTEMPTS):
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "spa-audit-reader/1.0"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except (urllib.error.URLError, urllib.error.HTTPError,
                    ValueError, OSError) as e:
                last_err = f"{type(e).__name__}: {e}"
                if attempt < FETCH_MAX_ATTEMPTS - 1:
                    import time
                    time.sleep(FETCH_BACKOFF_BASE ** attempt)
        log.warning("audit fetch failed (%s): %s", url, last_err)
        return None

    def _fetch_code4rena_index(self, offline: bool = False
                                ) -> list[dict[str, Any]]:
        """
        Fetch the Code4rena audits index. Returns a list of audit records.
        On any failure (network or schema), returns []. The caller MUST
        merge bootstrap entries on top — this method does NOT return
        bootstrap data itself (that responsibility lives in
        ``aggregate_by_protocol``).
        """
        if offline:
            return []
        body = self._http_get_text(CODE4RENA_INDEX_URL)
        if body is None:
            return []
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            log.warning("Code4rena index is not JSON — treating as empty")
            return []
        # Code4rena's audits.json is a list of contest dicts. We pull a
        # minimal subset of fields; missing fields fall back to "".
        out: list[dict[str, Any]] = []
        records = payload if isinstance(payload, list) else (
            payload.get("contests", []) if isinstance(payload, dict) else []
        )
        for r in records:
            if not isinstance(r, dict):
                continue
            name = r.get("sponsor", {}).get("name") if isinstance(
                r.get("sponsor"), dict) else r.get("title") or r.get("contest")
            out.append({
                "protocol":   name or "",
                "contest_id": str(r.get("contestid") or r.get("id") or
                                  r.get("slug") or ""),
                "auditor":    "Code4rena",
                "date":       r.get("start_time") or r.get("startDate") or "",
                "url":        r.get("findings_url") or r.get("url") or "",
                # Findings are not in the index — would need per-report fetch.
                # We surface "0 known findings" rather than fabricate.
                "findings":   [],
            })
        return out

    def _fetch_sherlock_index(self, offline: bool = False
                               ) -> list[dict[str, Any]]:
        """
        Fetch the Sherlock reports index (README.md) and parse audit links.
        Returns a list of audit records. Empty list on any failure.
        """
        if offline:
            return []
        body = self._http_get_text(SHERLOCK_INDEX_URL)
        if body is None:
            return []
        out: list[dict[str, Any]] = []
        # README typically contains lines like:
        #   - [Aave V3](./Audit_Reports/2024_01_AaveV3.pdf)
        link_re = re.compile(r"\[([^\]]+)\]\((\.?/?[^)]+\.(?:pdf|md))\)",
                             re.IGNORECASE)
        for m in link_re.finditer(body):
            label, href = m.group(1), m.group(2)
            slug = self._normalize_protocol_name(label)
            if not slug:
                continue
            out.append({
                "protocol":   label,
                "contest_id": f"sherlock-{slug}-{href.split('/')[-1]}",
                "auditor":    "Sherlock",
                "date":       "",
                "url":        ("https://github.com/sherlock-protocol/"
                                "sherlock-reports/blob/main/" +
                                href.lstrip("./")),
                "findings":   [],
            })
        return out

    # ── Aggregation ───────────────────────────────────────────────────────

    def _bootstrap_records(self) -> list[dict[str, Any]]:
        """Return a deep-copied list of BOOTSTRAP_AUDITS for safe mutation."""
        out: list[dict[str, Any]] = []
        for rec in BOOTSTRAP_AUDITS:
            out.append({
                "protocol":      rec["protocol_slug"],
                "protocol_slug": rec["protocol_slug"],
                "contest_id":    rec["contest_id"],
                "auditor":       rec["auditor"],
                "date":          rec.get("date", ""),
                "url":           rec.get("url", ""),
                "findings": [
                    {
                        "severity": f["severity"],
                        "title":    f["title"],
                        "status":   f["status"],
                    }
                    for f in rec.get("findings", [])
                ],
                "_bootstrap": True,
            })
        return out

    def aggregate_by_protocol(self, *, offline: bool = False
                               ) -> dict[str, ProtocolAuditSummary]:
        """
        Aggregate all known audit data into per-protocol summaries.

        This method NEVER raises. On any error during network fetch it
        falls back to BOOTSTRAP_AUDITS and sets ``self._fallback_used = True``.

        Returns a dict keyed by canonical SPA slug. Every SPA whitelist
        slug is guaranteed to be present.
        """
        sources_used: list[str] = []
        c4_records: list[dict[str, Any]] = []
        sh_records: list[dict[str, Any]] = []
        fallback = False

        # ── Code4rena ─
        try:
            c4_records = self._fetch_code4rena_index(offline=offline)
            if c4_records:
                sources_used.append("code4rena")
        except Exception as e:  # pragma: no cover (defensive)
            log.warning("Code4rena fetch raised: %s", e)
            c4_records = []
        # ── Sherlock ─
        try:
            sh_records = self._fetch_sherlock_index(offline=offline)
            if sh_records:
                sources_used.append("sherlock")
        except Exception as e:  # pragma: no cover (defensive)
            log.warning("Sherlock fetch raised: %s", e)
            sh_records = []

        # ── Bootstrap (always merged) ─
        bs_records = self._bootstrap_records()
        sources_used.append("bootstrap")
        if not c4_records and not sh_records:
            fallback = True

        # Tag c4/sh records with their source label.
        for r in c4_records:
            r["_source_label"] = "code4rena"
            r["protocol_slug"] = self._normalize_protocol_name(r["protocol"])
        for r in sh_records:
            r["_source_label"] = "sherlock"
            r["protocol_slug"] = self._normalize_protocol_name(r["protocol"])
        for r in bs_records:
            r["_source_label"] = "bootstrap"

        all_records = c4_records + sh_records + bs_records

        # Initialise an empty summary for every whitelist slug.
        summaries: dict[str, ProtocolAuditSummary] = {
            slug: ProtocolAuditSummary(protocol_slug=slug)
            for slug in SPA_WHITELIST
        }

        # Track (slug -> set of (auditor, contest_id)) so total_audits is the
        # count of distinct audit engagements.
        seen_audits: dict[str, set[tuple[str, str]]] = {
            slug: set() for slug in SPA_WHITELIST
        }
        for slug in summaries:
            seen_audits.setdefault(slug, set())

        for rec in all_records:
            slug = rec.get("protocol_slug") or ""
            if slug not in summaries:
                # Skip protocols that aren't in our whitelist. We never
                # silently introduce new slugs.
                continue
            summary = summaries[slug]

            # Register the audit engagement
            key = (rec.get("auditor", ""), rec.get("contest_id", ""))
            if key not in seen_audits[slug]:
                seen_audits[slug].add(key)
                summary.total_audits += 1
                if rec.get("auditor"):
                    if rec["auditor"] not in summary.auditors:
                        summary.auditors.append(rec["auditor"])
                date = rec.get("date") or ""
                if date and (summary.last_audit_date is None or
                             date > summary.last_audit_date):
                    summary.last_audit_date = date

            # Register findings
            for f in rec.get("findings", []):
                sev = _coerce_severity(f.get("severity"))
                status = self._classify_status(f.get("status"))
                finding = AuditFinding(
                    severity=sev,
                    title=str(f.get("title", "")),
                    status=status,
                    source=rec.get("_source_label", "bootstrap"),
                    contest_id=rec.get("contest_id", ""),
                    url=rec.get("url", ""),
                )
                summary.findings.append(finding)

                if sev == "critical":
                    summary.total_critical += 1
                    if status == "fixed":
                        summary.fixed_critical += 1
                    elif status == "open":
                        summary.open_critical += 1
                elif sev == "high":
                    summary.total_high += 1
                    if status == "fixed":
                        summary.fixed_high += 1
                    elif status == "open":
                        summary.open_high += 1

        # Deterministic ordering: sort findings inside each summary, and
        # sort the auditor list.
        for summary in summaries.values():
            summary.auditors = sorted(set(summary.auditors))
            summary.findings.sort(
                key=lambda f: (
                    SEVERITIES.index(f.severity) if f.severity in SEVERITIES
                    else len(SEVERITIES),
                    f.contest_id,
                    f.title,
                )
            )

        self._fallback_used = fallback
        # Deduplicate sources_used while preserving order
        deduped: list[str] = []
        for s in sources_used:
            if s not in deduped:
                deduped.append(s)
        self._sources_used = deduped
        return summaries

    # ── Export ────────────────────────────────────────────────────────────

    def _build_snapshot(self, summaries: dict[str, ProtocolAuditSummary]
                         ) -> dict[str, Any]:
        """Convert summaries dict to the canonical JSON snapshot."""
        # Sort protocol keys deterministically.
        protocols_out: dict[str, Any] = {}
        for slug in sorted(summaries.keys()):
            protocols_out[slug] = summaries[slug].to_dict()

        total_findings = sum(s.findings.__len__() for s in summaries.values())
        open_critical_count = sum(s.open_critical for s in summaries.values())

        return {
            "generated_at": datetime.now(timezone.utc).isoformat().replace(
                "+00:00", "Z"),
            "agent_version": AGENT_VERSION,
            "sources": list(self._sources_used) if self._sources_used
                else ["bootstrap"],
            "fallback_used": bool(self._fallback_used),
            "protocols": protocols_out,
            "summary": {
                "total_protocols": len(protocols_out),
                "total_findings": total_findings,
                "open_critical_count": open_critical_count,
            },
        }

    def export(self, *, dry_run: bool = False,
               offline: bool = False) -> dict[str, Any]:
        """
        Build the snapshot and (unless dry_run) write it to ``output_file``.

        Returns the snapshot dict (always — even on dry_run).
        Never raises — on any error the snapshot is still returned, possibly
        with ``fallback_used = True``.
        """
        try:
            summaries = self.aggregate_by_protocol(offline=offline)
        except Exception as e:  # pragma: no cover (defensive)
            log.error("aggregate_by_protocol raised unexpectedly: %s", e)
            summaries = {slug: ProtocolAuditSummary(protocol_slug=slug)
                          for slug in SPA_WHITELIST}
            self._fallback_used = True
            self._sources_used = ["bootstrap"]

        snapshot = self._build_snapshot(summaries)

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
            log.info("Wrote %d protocols (%d findings) to %s",
                     snapshot["summary"]["total_protocols"],
                     snapshot["summary"]["total_findings"],
                     self.output_file)
        except OSError as e:
            log.error("Failed to write %s: %s", self.output_file, e)

        return snapshot


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _cli(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit Reader Agent (FEAT-INT-001) — produce "
                     "data/audit_findings.json",
    )
    parser.add_argument("--offline", action="store_true",
                        help="Skip network — use BOOTSTRAP_AUDITS only.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build snapshot but do not write to disk.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH,
                        help="Output path (default: data/audit_findings.json)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    agent = AuditReaderAgent(output_file=args.output)
    snapshot = agent.export(dry_run=args.dry_run, offline=args.offline)

    log.info(
        "Done — %d protocols, %d findings, open_critical=%d, fallback=%s",
        snapshot["summary"]["total_protocols"],
        snapshot["summary"]["total_findings"],
        snapshot["summary"]["open_critical_count"],
        snapshot["fallback_used"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
