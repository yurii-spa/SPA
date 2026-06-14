"""
MP-1156: DeFiProtocolVaultShareInflationAttackExposureAnalyzer
==============================================================
Advisory/read-only analytics module.

An ERC-4626 vault is vulnerable to the classic "first-depositor / donation
share-inflation" attack when total shares outstanding are tiny and the contract
lacks a virtual-shares / dead-shares offset. An attacker mints 1 wei of shares,
donates a large amount of the underlying directly to the vault to inflate the
share price, then later depositors' deposits round DOWN to 0 shares and are
effectively stolen. This module answers: "given this vault's current share
supply, its protections, and the size of my intended deposit, how exposed am I
to a share-inflation / rounding-loss attack?"

This isolates the *ERC-4626 share-price rounding / first-depositor inflation*
question — current share supply, virtual-shares / dead-shares / decimals-offset
mitigations, the attacker's donation cost to inflate the price, and how much of
my deposit could round to zero.

Distinct from:
  * oracle-manipulation analyzers   → they model price-feed manipulation.
  * depositor_concentration         → it models whale run-risk.
  * deposit_cap_headroom            → it models capacity to ENTER under a cap.
This module answers only the share-inflation / rounding-loss safety question.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_share_inflation_attack_log.json"
)
LOG_CAP = 100

PRICE_SENTINEL_MAX = 1e18    # shares<=0 → share price "infinite" → MAX vulnerability

# Share-supply bands (shares outstanding)
LARGE_SHARE_SUPPLY = 1e6     # supply >= 1e6 → effectively safe from inflation
TINY_SHARE_SUPPLY = 1e3      # supply <= 1e3 → tiny / vulnerable supply

# Effective-protection thresholds
MIN_DECIMALS_OFFSET = 3      # decimals_offset >= 3 → strong mitigation
MIN_DEAD_SHARES = 1000.0     # dead_shares_burned >= 1000 → buffer mitigation

# Protection down-scaling factor applied to rounding-loss when protected
PROTECTED_ROUNDING_SCALE = 0.05

# Rounding-loss threshold (%) above which we flag high rounding-loss risk
HIGH_ROUNDING_LOSS_PCT = 50.0


# ── helpers ───────────────────────────────────────────────────────────────────

def _f(val, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _safe_div(num: float, den: float, sentinel: float) -> float:
    if den <= 0:
        return sentinel
    return num / den


def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
    cfg = {"log_path": LOG_PATH, "log_cap": LOG_CAP}
    if overrides:
        cfg.update(overrides)
    return cfg


def _grade_from_score(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolVaultShareInflationAttackExposureAnalyzer:
    """
    Analyzes an ERC-4626 vault's exposure to the first-depositor / donation
    share-inflation attack and the rounding-loss risk to my intended deposit.

    HIGHER score = SAFER (large share supply and/or strong inflation protection).

    Per-position input dict fields:
        vault / token          : str
        total_shares           : float  (current shares outstanding; key signal)
        total_assets_usd       : float  (vault's underlying assets, USD)
        has_virtual_shares     : bool   (OZ virtual-shares mitigation, default F)
        dead_shares_burned     : float  (shares locked at deploy, default 0)
        decimals_offset        : float  (ERC-4626 decimals offset, default 0)
        intended_deposit_usd   : float  (my deposit, default 0)
    """

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        position: dict,
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        result = self._analyze_one(position)
        if write_log:
            self._write_log([result], self._aggregate([result]), cfg)
        return result

    def analyze_portfolio(
        self,
        positions: List[dict],
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        results = [self._analyze_one(p) for p in positions]
        agg = self._aggregate(results)
        if write_log:
            self._write_log(results, agg, cfg)
        return {"positions": results, "aggregate": agg}

    # ── per-position ───────────────────────────────────────────────────────────

    def _analyze_one(self, p: dict) -> dict:
        token = p.get("vault", p.get("token", "UNKNOWN"))
        total_shares = _f(p.get("total_shares"))
        total_assets = _f(p.get("total_assets_usd"))
        has_virtual = bool(p.get("has_virtual_shares", False))
        dead_shares = max(0.0, _f(p.get("dead_shares_burned")))
        decimals_offset = max(0.0, _f(p.get("decimals_offset")))
        intended_deposit = max(0.0, _f(p.get("intended_deposit_usd")))

        # Insufficient data: cannot reason about share price without assets.
        if total_assets <= 0:
            return self._insufficient(token)

        # Share price — shares<=0 treated as MAX vulnerability (sentinel price).
        share_price = _safe_div(total_assets, total_shares, PRICE_SENTINEL_MAX)

        # Effective protection if any strong mitigation is present.
        effective_protection = (
            has_virtual
            or decimals_offset >= MIN_DECIMALS_OFFSET
            or dead_shares >= MIN_DEAD_SHARES
        )

        # Attacker donation cost to roughly DOUBLE the share price ≈ current
        # underlying assets (advisory estimate).
        donation_to_inflate = total_assets

        # Rounding-loss exposure: how many shares would my deposit mint?
        shares_i_would_get = _safe_div(
            intended_deposit, share_price, 0.0
        )
        rounding_loss = self._rounding_loss_pct(
            shares_i_would_get, intended_deposit, effective_protection,
        )

        score = self._vulnerability_score(
            total_shares, effective_protection, rounding_loss,
        )
        classification = self._classify(
            total_shares, effective_protection,
        )
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            total_shares, has_virtual, dead_shares, decimals_offset,
            effective_protection, rounding_loss, classification,
        )

        return {
            "token": token,
            "total_shares": round(total_shares, 4),
            "total_assets_usd": round(total_assets, 2),
            "share_price_usd": (
                None if share_price >= PRICE_SENTINEL_MAX else round(share_price, 8)
            ),
            "has_virtual_shares": has_virtual,
            "dead_shares_burned": round(dead_shares, 4),
            "decimals_offset": round(decimals_offset, 2),
            "intended_deposit_usd": round(intended_deposit, 2),
            "effective_protection": effective_protection,
            "donation_to_inflate_usd": round(donation_to_inflate, 2),
            "shares_i_would_get": round(shares_i_would_get, 8),
            "rounding_loss_shares_pct": round(rounding_loss, 4),
            "vulnerability_score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── metrics ────────────────────────────────────────────────────────────────

    def _rounding_loss_pct(
        self,
        shares_i_would_get: float,
        intended_deposit: float,
        effective_protection: bool,
    ) -> float:
        """
        0–100 exposure: higher when my deposit would mint < 1 share (it can
        round down toward zero). If I have no intended deposit, no rounding-loss
        exposure to report. Scaled down sharply when the vault is protected.
        """
        if intended_deposit <= 0:
            return 0.0
        if shares_i_would_get >= 1.0:
            base = 0.0
        elif shares_i_would_get <= 0.0:
            base = 100.0
        else:
            # fewer shares than 1 → linearly more exposed as it approaches 0.
            base = 100.0 * (1.0 - shares_i_would_get)
        if effective_protection:
            base *= PROTECTED_ROUNDING_SCALE
        return _clamp(base, 0.0, 100.0)

    # ── scoring ────────────────────────────────────────────────────────────────

    def _vulnerability_score(
        self,
        total_shares: float,
        effective_protection: bool,
        rounding_loss: float,
    ) -> float:
        """
        0–100, HIGHER = SAFER. Weighted:
          large share supply (≈40, saturating at LARGE_SHARE_SUPPLY)
          + protection bonus (≈40 when effectively protected)
          + low rounding-loss component (≈20).
        """
        # Large-supply component — saturates at LARGE_SHARE_SUPPLY.
        supply_comp = 40.0 * _clamp(
            total_shares / LARGE_SHARE_SUPPLY, 0.0, 1.0,
        )

        # Protection bonus — full when an effective mitigation is present.
        protection_comp = 40.0 if effective_protection else 0.0

        # Low rounding-loss component — full when no rounding-loss exposure.
        rounding_comp = 20.0 * _clamp(1.0 - rounding_loss / 100.0, 0.0, 1.0)

        return _clamp(supply_comp + protection_comp + rounding_comp, 0.0, 100.0)

    def _classify(
        self,
        total_shares: float,
        effective_protection: bool,
    ) -> str:
        if effective_protection and total_shares >= LARGE_SHARE_SUPPLY:
            return "WELL_PROTECTED"
        if not effective_protection and total_shares <= TINY_SHARE_SUPPLY:
            return "HIGH_RISK"
        if effective_protection or total_shares >= LARGE_SHARE_SUPPLY:
            return "LOW_RISK"
        return "MODERATE_RISK"

    def _recommend(self, classification: str) -> str:
        if classification in ("WELL_PROTECTED", "LOW_RISK"):
            return "DEPLOY"
        if classification == "MODERATE_RISK":
            return "DEPLOY_CAUTIOUSLY"
        return "AVOID"

    def _flags(
        self,
        total_shares: float,
        has_virtual: bool,
        dead_shares: float,
        decimals_offset: float,
        effective_protection: bool,
        rounding_loss: float,
        classification: str,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "WELL_PROTECTED":
            flags.append("WELL_PROTECTED")

        if has_virtual:
            flags.append("HAS_VIRTUAL_SHARES")

        if dead_shares >= MIN_DEAD_SHARES:
            flags.append("DEAD_SHARES_BUFFER")

        if decimals_offset >= MIN_DECIMALS_OFFSET:
            flags.append("DECIMALS_OFFSET_PROTECTION")

        if total_shares <= TINY_SHARE_SUPPLY:
            flags.append("TINY_SHARE_SUPPLY")

        if not effective_protection:
            flags.append("NO_INFLATION_PROTECTION")

        if rounding_loss >= HIGH_ROUNDING_LOSS_PCT:
            flags.append("HIGH_ROUNDING_LOSS_RISK")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "total_shares": 0.0,
            "total_assets_usd": 0.0,
            "share_price_usd": None,
            "has_virtual_shares": False,
            "dead_shares_burned": 0.0,
            "decimals_offset": 0.0,
            "intended_deposit_usd": 0.0,
            "effective_protection": False,
            "donation_to_inflate_usd": 0.0,
            "shares_i_would_get": 0.0,
            "rounding_loss_shares_pct": 0.0,
            "vulnerability_score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_vulnerable_vault": None,
                "least_vulnerable_vault": None,
                "avg_vulnerability_score": 0.0,
                "high_risk_count": 0,
                "position_count": len(results),
            }
        # Higher score = safer → lowest score is MOST vulnerable.
        by_score = sorted(scored, key=lambda r: r["vulnerability_score"])
        avg = _mean([r["vulnerability_score"] for r in scored])
        high_risk = sum(1 for r in results if r["classification"] == "HIGH_RISK")
        return {
            "most_vulnerable_vault": by_score[0]["token"],
            "least_vulnerable_vault": by_score[-1]["token"],
            "avg_vulnerability_score": round(avg, 2),
            "high_risk_count": high_risk,
            "position_count": len(results),
        }

    # ── ring-buffer log ───────────────────────────────────────────────────────

    def _write_log(self, results: List[dict], agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        cap = cfg["log_cap"]
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "position_count": len(results),
            "aggregate": agg,
            "snapshots": [
                {
                    "token": r["token"],
                    "classification": r["classification"],
                    "vulnerability_score": r["vulnerability_score"],
                    "recommendation": r["recommendation"],
                    "flags": r["flags"],
                }
                for r in results
            ],
        }

        log: List[dict] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as fh:
                    log = json.load(fh)
                if not isinstance(log, list):
                    log = []
            except (json.JSONDecodeError, OSError):
                log = []

        log.append(entry)
        if len(log) > cap:
            log = log[-cap:]

        tmp = log_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp, log_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_positions() -> List[dict]:
    return [
        {
            "vault": "USDC-Vault-Mature",
            "total_shares": 5_000_000.0,
            "total_assets_usd": 5_000_000.0,
            "has_virtual_shares": True,
            "decimals_offset": 6,
            "dead_shares_burned": 1000.0,
            "intended_deposit_usd": 100_000.0,
        },
        {
            "vault": "ETH-Vault-Young",
            "total_shares": 50_000.0,
            "total_assets_usd": 250_000.0,
            "has_virtual_shares": False,
            "decimals_offset": 0,
            "dead_shares_burned": 0.0,
            "intended_deposit_usd": 10_000.0,
        },
        {
            "vault": "DAI-Vault-FreshDeploy",
            "total_shares": 1.0,
            "total_assets_usd": 500_000.0,
            "has_virtual_shares": False,
            "decimals_offset": 0,
            "dead_shares_burned": 0.0,
            "intended_deposit_usd": 50_000.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1156 Vault Share Inflation Attack Exposure Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultShareInflationAttackExposureAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
