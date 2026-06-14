"""
MP-1106: DeFiProtocolMEVProtectionEffectivenessAnalyzer
Analyzes how effectively DeFi protocols protect users against MEV extraction
(sandwich attacks, frontrunning, backrunning) and quantifies the impact on
effective net yield. Pure stdlib, read-only/advisory, atomic ring-buffer log.
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "mev_protection_log.json"
)
LOG_CAP = 100

# MEV mechanism weights for composite score
W_SANDWICH  = 0.35
W_FRONTRUN  = 0.25
W_BACKRUN   = 0.20
W_COMMIT    = 0.20   # commit-reveal / private mempool protection

# Score thresholds → label
_LABEL_THRESHOLDS = [
    (85.0, "STRONG_PROTECTION"),
    (65.0, "ADEQUATE_PROTECTION"),
    (40.0, "PARTIAL_PROTECTION"),
    (0.0,  "VULNERABLE"),
]

# Annual basis-point drag per score tier (estimated MEV extraction cost)
_MEV_DRAG_BPS: Dict[str, float] = {
    "STRONG_PROTECTION":   5.0,
    "ADEQUATE_PROTECTION": 20.0,
    "PARTIAL_PROTECTION":  55.0,
    "VULNERABLE":         120.0,
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _score_from_bool(has_feature: bool) -> float:
    return 100.0 if has_feature else 0.0


def _label_from_score(score: float) -> str:
    for threshold, label in _LABEL_THRESHOLDS:
        if score >= threshold:
            return label
    return "VULNERABLE"


def _mev_drag_bps(label: str) -> float:
    return _MEV_DRAG_BPS.get(label, 120.0)


def _effective_yield(gross_apy_pct: float, drag_bps: float) -> float:
    """Return net APY after MEV drag. drag_bps in annual basis points."""
    return max(0.0, gross_apy_pct - drag_bps / 100.0)


def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
    cfg = {
        "log_path": LOG_PATH,
        "log_cap": LOG_CAP,
    }
    if overrides:
        cfg.update(overrides)
    return cfg


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolMEVProtectionEffectivenessAnalyzer:
    """
    Scores each protocol's MEV protection posture and estimates the annual
    yield drag caused by unmitigated MEV extraction.

    Input protocol dict keys:
        name                    : str
        category                : str   ("dex", "lending", "yield_aggregator", …)
        uses_private_mempool    : bool  (e.g. Flashbots Protect / MEV Blocker)
        has_commit_reveal       : bool  (commit-reveal or TWAP for price)
        slippage_protection_pct : float (max slippage param enforced, 0–100)
        has_sandwich_guard      : bool  (built-in sandwich detection / revert)
        oracle_twap_window_sec  : float (0 → spot-only; >0 = TWAP duration)
        order_flow_auction      : bool  (OFA / auction-based trade routing)
        historical_mev_losses_usd: float (optional; total documented MEV losses)
        gross_apy_pct           : float (raw gross APY before any drag)
        tvl_usd                 : float (protocol TVL for severity weighting)
    """

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        protocols: List[dict],
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        results = [self._score_protocol(p, cfg) for p in protocols]
        agg = self._aggregate(results, cfg)
        if write_log:
            self._write_log(results, agg, cfg)
        return {"protocols": results, "aggregate": agg}

    # ── per-protocol scoring ──────────────────────────────────────────────────

    def _score_protocol(self, p: dict, cfg: dict) -> dict:
        name     = p.get("name", "unknown")
        category = p.get("category", "unknown")

        # sub-scores 0–100
        sandwich_score = self._sandwich_score(p)
        frontrun_score = self._frontrun_score(p)
        backrun_score  = self._backrun_score(p)
        commit_score   = self._commit_score(p)

        composite = (
            W_SANDWICH * sandwich_score
            + W_FRONTRUN * frontrun_score
            + W_BACKRUN  * backrun_score
            + W_COMMIT   * commit_score
        )
        composite = _clamp(composite, 0.0, 100.0)

        label     = _label_from_score(composite)
        drag_bps  = _mev_drag_bps(label)
        gross_apy = p.get("gross_apy_pct", 0.0)
        net_apy   = _effective_yield(gross_apy, drag_bps)

        flags = self._flags(p, composite, drag_bps, gross_apy)

        # Severity weighting by TVL
        tvl = p.get("tvl_usd", 0.0)
        estimated_annual_mev_loss = tvl * drag_bps / 10_000.0 if tvl > 0 else 0.0

        return {
            "name": name,
            "category": category,
            "sub_scores": {
                "sandwich_protection": round(sandwich_score, 2),
                "frontrun_protection": round(frontrun_score, 2),
                "backrun_protection":  round(backrun_score, 2),
                "commit_reveal":       round(commit_score, 2),
            },
            "composite_score":              round(composite, 2),
            "protection_label":             label,
            "estimated_mev_drag_bps":       round(drag_bps, 1),
            "gross_apy_pct":                round(gross_apy, 4),
            "net_apy_after_mev_pct":        round(net_apy, 4),
            "estimated_annual_mev_loss_usd": round(estimated_annual_mev_loss, 2),
            "flags": flags,
        }

    # ── sub-scores ────────────────────────────────────────────────────────────

    def _sandwich_score(self, p: dict) -> float:
        """Sandwich protection: slippage guard + built-in sandwich guard."""
        slippage_pct = _clamp(p.get("slippage_protection_pct", 0.0), 0.0, 100.0)
        # max slippage ≤1% = full score for this component
        slip_score = _clamp((1.0 - slippage_pct / 100.0) * 100.0, 0.0, 100.0)
        if slippage_pct == 0.0:
            slip_score = 0.0

        guard_score = _score_from_bool(p.get("has_sandwich_guard", False))
        return 0.6 * slip_score + 0.4 * guard_score

    def _frontrun_score(self, p: dict) -> float:
        """Frontrun protection: private mempool + order flow auction."""
        private = _score_from_bool(p.get("uses_private_mempool", False))
        ofa     = _score_from_bool(p.get("order_flow_auction", False))
        return 0.6 * private + 0.4 * ofa

    def _backrun_score(self, p: dict) -> float:
        """Backrun protection: mostly oracle quality (TWAP window)."""
        window = p.get("oracle_twap_window_sec", 0.0)
        # TWAP ≥ 1800s (30 min) → full score; spot-only → 0
        if window <= 0:
            return 0.0
        return _clamp(window / 1800.0 * 100.0, 0.0, 100.0)

    def _commit_score(self, p: dict) -> float:
        """Commit-reveal / time-lock protection."""
        cr  = _score_from_bool(p.get("has_commit_reveal", False))
        prv = _score_from_bool(p.get("uses_private_mempool", False))
        return 0.7 * cr + 0.3 * prv

    # ── flags ─────────────────────────────────────────────────────────────────

    def _flags(
        self, p: dict, score: float, drag_bps: float, gross_apy: float
    ) -> List[str]:
        flags: List[str] = []

        if score < 40.0:
            flags.append("HIGH_MEV_RISK")

        # MEV drag exceeds 10% of gross APY
        if gross_apy > 0 and drag_bps / 100.0 > gross_apy * 0.10:
            flags.append("MEV_DRAG_EXCEEDS_10PCT_APY")

        # No any protection mechanism
        no_private = not p.get("uses_private_mempool", False)
        no_guard   = not p.get("has_sandwich_guard", False)
        no_twap    = p.get("oracle_twap_window_sec", 0.0) <= 0
        if no_private and no_guard and no_twap:
            flags.append("NO_MEV_MITIGATION")

        # Documented losses exist
        if p.get("historical_mev_losses_usd", 0.0) > 0:
            flags.append("DOCUMENTED_MEV_LOSSES")

        # High TVL + high vulnerability
        tvl = p.get("tvl_usd", 0.0)
        if tvl >= 100_000_000 and score < 40.0:
            flags.append("LARGE_TVL_HIGH_MEV_EXPOSURE")

        return flags

    # ── aggregates ────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict], cfg: dict) -> dict:
        if not results:
            return {
                "best_protected": None,
                "most_vulnerable": None,
                "avg_composite_score": 0.0,
                "avg_mev_drag_bps": 0.0,
                "avg_net_apy_pct": 0.0,
                "total_estimated_annual_mev_loss_usd": 0.0,
                "vulnerable_count": 0,
                "strong_protection_count": 0,
            }

        by_score = sorted(results, key=lambda r: r["composite_score"], reverse=True)
        avg_score = sum(r["composite_score"] for r in results) / len(results)
        avg_drag  = sum(r["estimated_mev_drag_bps"] for r in results) / len(results)
        avg_net   = sum(r["net_apy_after_mev_pct"] for r in results) / len(results)
        total_loss = sum(r["estimated_annual_mev_loss_usd"] for r in results)

        return {
            "best_protected":    by_score[0]["name"] if by_score else None,
            "most_vulnerable":   by_score[-1]["name"] if by_score else None,
            "avg_composite_score": round(avg_score, 2),
            "avg_mev_drag_bps":    round(avg_drag, 1),
            "avg_net_apy_pct":     round(avg_net, 4),
            "total_estimated_annual_mev_loss_usd": round(total_loss, 2),
            "vulnerable_count":      sum(1 for r in results if r["protection_label"] == "VULNERABLE"),
            "strong_protection_count": sum(1 for r in results if r["protection_label"] == "STRONG_PROTECTION"),
        }

    # ── ring-buffer log ───────────────────────────────────────────────────────

    def _write_log(self, results: List[dict], agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        cap      = cfg["log_cap"]

        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "ts":              datetime.now(timezone.utc).isoformat(),
            "protocol_count":  len(results),
            "aggregates":      agg,
            "snapshots": [
                {
                    "name":             r["name"],
                    "composite_score":  r["composite_score"],
                    "protection_label": r["protection_label"],
                    "mev_drag_bps":     r["estimated_mev_drag_bps"],
                    "net_apy_pct":      r["net_apy_after_mev_pct"],
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

def _demo_protocols() -> List[dict]:
    return [
        {
            "name": "Uniswap V3",
            "category": "dex",
            "uses_private_mempool": False,
            "has_commit_reveal": False,
            "slippage_protection_pct": 0.5,
            "has_sandwich_guard": False,
            "oracle_twap_window_sec": 1800.0,
            "order_flow_auction": False,
            "historical_mev_losses_usd": 0.0,
            "gross_apy_pct": 8.0,
            "tvl_usd": 5_000_000_000,
        },
        {
            "name": "CoW Protocol",
            "category": "dex",
            "uses_private_mempool": True,
            "has_commit_reveal": True,
            "slippage_protection_pct": 0.3,
            "has_sandwich_guard": True,
            "oracle_twap_window_sec": 3600.0,
            "order_flow_auction": True,
            "historical_mev_losses_usd": 0.0,
            "gross_apy_pct": 6.5,
            "tvl_usd": 300_000_000,
        },
        {
            "name": "Aave V3",
            "category": "lending",
            "uses_private_mempool": False,
            "has_commit_reveal": False,
            "slippage_protection_pct": 0.0,
            "has_sandwich_guard": False,
            "oracle_twap_window_sec": 0.0,
            "order_flow_auction": False,
            "historical_mev_losses_usd": 0.0,
            "gross_apy_pct": 3.5,
            "tvl_usd": 12_000_000_000,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="MP-1106 MEV Protection Analyzer")
    parser.add_argument("--run",   action="store_true", help="Analyze and write log")
    parser.add_argument("--check", action="store_true", help="Analyze only, no write (default)")
    args = parser.parse_args()

    analyzer = DeFiProtocolMEVProtectionEffectivenessAnalyzer()
    protocols = _demo_protocols()
    result = analyzer.analyze(protocols, write_log=args.run)

    print(json.dumps(result, indent=2))
    sys.exit(0)
