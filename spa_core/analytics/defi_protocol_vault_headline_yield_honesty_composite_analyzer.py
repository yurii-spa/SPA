"""
MP-1206: DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer
==============================================================
Advisory/read-only analytics module.

The SPA analytics suite ships a whole FAMILY of single-mechanism "headline
overstatement" analyzers — each isolates ONE reason the realised APR falls below
the advertised headline running APR:

    * entry/exit fee amortisation        (one-off round-trip fee over the hold)
    * management-fee accrual             (continuous AUM fee drag)
    * performance-fee volatility tax     (HWM fee asymmetry on a volatile path)
    * net-of-loss yield realisation      (IL / slashing / bad-debt loss stream)
    * dollar-weighted return gap         (adverse cashflow timing, TWR vs DWR)
    * reward auto-sell slippage          (self-inflicted market impact on harvest)
    * idle-cash / deployment-ramp drag   (un-deployed capital not earning)
    * emission decay / boost-tier revert (subsidised headline that mean-reverts)
    * ... and more.

Each of those answers ONE question and reports its own annualised APR drag. But a
portfolio optimiser does not want sixty separate drags — it wants ONE number: the
NET realised APR after ALL known drags, the TOTAL overstatement, a single honesty
score, and the SINGLE BIGGEST culprit so a human can go look. This module is that
COMPOSITE ROLL-UP. It does NOT model any mechanism itself: it consumes the
per-mechanism annualised drags (each already produced by its own analyzer) and
sums them BOTTOM-UP into a unified realised-APR / honesty decomposition:

    raw_total_drag_apr_pct = Σ component.drag_apr_pct          (each finite >= 0)
    net_realized_apr_pct   = headline_apr_pct - raw_total_drag_apr_pct
    overstatement_pct      = headline_apr_pct - net_realized_apr_pct
                           = raw_total_drag_apr_pct
    realization_ratio      = clamp(net_realized / headline, 0, 1)   (headline > 0)
    drag_fraction          = clamp(raw_total_drag / headline, 0, 1)
    dominant_source        = the component with the LARGEST drag
    dominant_share         = clamp(dominant_drag / raw_total_drag, 0, 1)

The headline says "18% running APR", but a 2% amortised entry/exit fee + a 1.5%
management fee + a 3% net-of-loss drag + a 1% auto-sell slippage stack to a 7.5%
total drag → the net realised APR is ~10.5%, the headline overstates by ~42%, and
the biggest single culprit is the loss stream (40% of the total drag). Discount the
headline toward the composite net realised APR and go look at the dominant culprit.

When the stacked drags are negligible relative to the headline the net coincides
with the headline (HIGHER score — the LP keeps the brochure APR). When the stacked
drags rival or exceed the headline the net collapses toward or below zero (LOWER
score — net-negative after all drags).

HIGHER score = the composite of all known drags is negligible relative to the
headline (realised ≈ headline). LOWER score = a large stacked drag (realised far
below the headline, or net-negative after drags).

Override path (when total_drag_apr_pct is supplied directly and finite — a signed
negative is taken as its magnitude — AND a valid POSITIVE headline_apr_pct is
present): take the supplied total verbatim and
skip component summation — net it out the same way. On the override path the
component decomposition is unknown → component_count = 0 and dominant_source /
dominant_share are reported as None.

Distinct from:
  * defi_protocol_vault_yield_realization_gap_analyzer (MP-1169) — that measures
    the realised-vs-promised gap TOP-DOWN and EMPIRICALLY from the actual share-
    price growth over a trailing window, and makes NO claim about WHY. THIS module
    is the BOTTOM-UP ATTRIBUTION: it sums the KNOWN per-mechanism drags and names
    the dominant culprit. (Empirical gap vs additive decomposition.)
  * the single-mechanism analyzers (entry_exit_fee_amortization,
    management_fee_accrual, net_of_loss_yield_realization, dollar_weighted_return_gap,
    reward_autosell_slippage, ...) — each isolates ONE drag. THIS module is the
    roll-up that CONSUMES their outputs into one net realised APR + honesty score.
  * defi_position_health_score_aggregator / integrated_risk_dashboard — those
    aggregate RISK signals into a health score. THIS aggregates YIELD-HONESTY
    drags into a realised-APR decomposition.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import List, Optional, Tuple

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_headline_yield_honesty_composite_log.json"
)
LOG_CAP = 100

# Classification thresholds on the scale-free drag_fraction in [0, 1]
# (= raw_total_drag_apr_pct / headline_apr_pct).
CLEAN_FRACTION = 0.05        # at/below → clean headline (realised ≈ headline)
MILD_FRACTION = 0.20         # at/below → mild erosion
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe erosion

# Flag thresholds.
DOMINANT_SHARE_THRESHOLD = 0.5   # a single drag at/above this share → dominant
MANY_SOURCES_THRESHOLD = 4       # component_count at/above → many drag sources

# Small epsilon to keep normalisers finite.
EPS = 1e-12


# ── helpers ───────────────────────────────────────────────────────────────────

def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _coerce_num(val) -> Optional[float]:
    """
    Coerce a single value to a finite float, or None if it is not interpretable.
    Accepts int/float/numeric-string; rejects bool, None, NaN, inf, and
    non-numeric values.
    """
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        try:
            fv = float(val)
        except (TypeError, ValueError):
            return None
        return fv if math.isfinite(fv) else None
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        try:
            fv = float(s)
        except (TypeError, ValueError):
            return None
        return fv if math.isfinite(fv) else None
    return None


def _coerce_drag(val) -> Optional[float]:
    """
    Coerce a per-mechanism annualised APR drag to a finite NON-NEGATIVE magnitude.
    A signed negative drag is taken as its magnitude (a drag is a cost); non-finite
    / non-numeric / bool / None → None (skipped, not summed).
    """
    cv = _coerce_num(val)
    if cv is None or not math.isfinite(cv):
        return None
    return abs(cv)


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

class DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer:
    """
    Rolls the FAMILY of per-mechanism headline-drag analyzers up into ONE composite:
    the net realised APR after ALL known drags, the total overstatement, a single
    honesty score, and the dominant culprit.

        raw_total_drag_apr_pct = Σ component.drag_apr_pct        (each finite >= 0)
        net_realized_apr_pct   = headline_apr_pct - raw_total_drag_apr_pct
        overstatement_pct      = headline_apr_pct - net_realized_apr_pct
        realization_ratio      = clamp(net_realized / headline, 0, 1)
        drag_fraction          = clamp(raw_total_drag / headline, 0, 1)
        dominant_source        = component with the LARGEST drag
        dominant_share         = clamp(dominant_drag / raw_total_drag, 0, 1)

    The module does NOT model any drag mechanism itself — it CONSUMES the annualised
    drags produced by the single-mechanism analyzers and decomposes the headline.

    HIGHER score = the stacked drags are negligible relative to the headline
    (realised ≈ headline — the LP keeps the brochure APR). LOWER score = a large
    stacked drag (realised far below the headline, or net-negative after drags).

    Per-position input dict fields:
        vault / token        : str
        headline_apr_pct     : float — advertised running APR before any drag.
                               REQUIRED, must be a finite POSITIVE number (else
                               INSUFFICIENT_DATA).
        drag_components      : list | dict — the per-mechanism annualised APR drags.
                               * list of {"source": str, "drag_apr_pct": float}
                                 (also accepts "drag"/"value"/"apr_pct" as the value
                                 key, and "name"/"label" as the source key), OR
                               * a plain {source: drag} mapping.
                               Each drag is coerced to a finite >= 0 magnitude;
                               invalid / non-finite entries are SKIPPED.
        total_drag_apr_pct   : float — OPTIONAL direct override of the summed drag.
                               When supplied (finite; a signed negative is taken as
                               its magnitude) AND a valid positive headline_apr_pct
                               is present, take this total verbatim
                               and skip component summation (override path;
                               component_count = 0, dominant_source / dominant_share
                               → None).
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

        # The headline running APR is required and must be finite & positive.
        headline = _coerce_num(p.get("headline_apr_pct"))
        if headline is None or not math.isfinite(headline) or headline <= 0.0:
            return self._insufficient(token)

        # Override path: a direct total drag supplied → use it verbatim. A signed
        # negative total is taken as its magnitude (a drag is a cost), consistent
        # with the per-component drag handling. NaN/inf fall through to components.
        total_o = _coerce_num(p.get("total_drag_apr_pct"))
        if total_o is not None and math.isfinite(total_o):
            return self._analyze_override(token, headline, abs(total_o))

        # Component path: sum the per-mechanism drags.
        return self._analyze_components(token, p, headline)

    # ── component path ─────────────────────────────────────────────────────────

    def _parse_components(self, raw) -> List[Tuple[str, float]]:
        """
        Normalise the drag_components input into a list of (source, drag) pairs with
        finite, non-negative drags. Accepts a list of dicts or a plain mapping.
        Invalid / non-finite drags are skipped. A drag of exactly 0 is KEPT (a known
        mechanism that happens to contribute nothing this period).
        """
        out: List[Tuple[str, float]] = []
        if isinstance(raw, dict):
            for k, v in raw.items():
                d = _coerce_drag(v)
                if d is None:
                    continue
                out.append((str(k), d))
            return out
        if isinstance(raw, (list, tuple)):
            for i, item in enumerate(raw):
                if isinstance(item, dict):
                    val = item.get("drag_apr_pct")
                    if val is None:
                        val = item.get("drag")
                    if val is None:
                        val = item.get("value")
                    if val is None:
                        val = item.get("apr_pct")
                    d = _coerce_drag(val)
                    if d is None:
                        continue
                    src = item.get("source")
                    if src is None:
                        src = item.get("name")
                    if src is None:
                        src = item.get("label")
                    src = str(src) if src is not None else "component_%d" % i
                    out.append((src, d))
                else:
                    # A bare number in the list is a drag with a positional name.
                    d = _coerce_drag(item)
                    if d is None:
                        continue
                    out.append(("component_%d" % i, d))
            return out
        return out

    def _analyze_components(self, token: str, p: dict, headline: float) -> dict:
        components = self._parse_components(p.get("drag_components"))

        # A composite needs at least one valid drag input to roll up. With no
        # override and no valid components there is no honesty signal.
        if not components:
            return self._insufficient(token)

        raw_total_drag = sum(d for _, d in components)
        if not math.isfinite(raw_total_drag) or raw_total_drag < 0.0:
            raw_total_drag = 0.0

        # Dominant culprit: the largest single drag.
        dominant_source, dominant_drag = max(components, key=lambda c: c[1])
        if raw_total_drag > EPS:
            dominant_share = _clamp(dominant_drag / raw_total_drag, 0.0, 1.0)
        else:
            # All components are zero → no meaningful dominant share.
            dominant_share = 0.0

        return self._finish(
            token=token,
            headline_apr_pct=headline,
            raw_total_drag_apr_pct=raw_total_drag,
            component_count=len(components),
            dominant_source=dominant_source,
            dominant_drag_apr_pct=dominant_drag,
            dominant_share=dominant_share,
            used_override=False,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(self, token: str, headline: float, total: float) -> dict:
        return self._finish(
            token=token,
            headline_apr_pct=headline,
            raw_total_drag_apr_pct=total,
            component_count=0,
            dominant_source=None,
            dominant_drag_apr_pct=None,
            dominant_share=None,
            used_override=True,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        headline_apr_pct: float,
        raw_total_drag_apr_pct: float,
        component_count: int,
        dominant_source: Optional[str],
        dominant_drag_apr_pct: Optional[float],
        dominant_share: Optional[float],
        used_override: bool,
    ) -> dict:
        net_realized_apr_pct = headline_apr_pct - raw_total_drag_apr_pct
        # overstatement = headline - net = raw_total_drag (computed as the
        # difference for override consistency).
        overstatement_pct = headline_apr_pct - net_realized_apr_pct

        net_is_negative = net_realized_apr_pct <= 0.0

        # Scale-free realisation_ratio / drag_fraction against the headline APR.
        if headline_apr_pct > EPS and math.isfinite(headline_apr_pct):
            realization_ratio = _clamp(
                net_realized_apr_pct / headline_apr_pct, 0.0, 1.0)
            drag_fraction = _clamp(
                raw_total_drag_apr_pct / headline_apr_pct, 0.0, 1.0)
        else:
            return self._insufficient(token)

        classification = self._classify(drag_fraction, net_is_negative)
        score = self._score(realization_ratio, drag_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            component_count,
            dominant_share,
            used_override,
        )

        return {
            "token": token,
            "headline_apr_pct": round(headline_apr_pct, 4),
            "raw_total_drag_apr_pct": round(raw_total_drag_apr_pct, 4),
            "net_realized_apr_pct": round(net_realized_apr_pct, 4),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "drag_fraction": round(drag_fraction, 4),
            "component_count": component_count,
            "dominant_source": dominant_source,
            "dominant_drag_apr_pct": (
                round(dominant_drag_apr_pct, 4)
                if dominant_drag_apr_pct is not None else None),
            "dominant_share": (
                round(dominant_share, 4) if dominant_share is not None else None),
            "net_is_negative": net_is_negative,
            "used_override": used_override,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags_out,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        realization_ratio: float,
        drag_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the net-of-all-drags realised APR is close to the headline
        running APR (stacked drags negligible → the LP keeps the brochure APR). Two
        components:
          * realisation = clamp(realization_ratio, 0, 1) — the fraction of the
            headline APR that survives all stacked drags,
          * drag penalty = clamp(1 − drag_fraction, 0, 1) — penalises a large
            stacked drag relative to the headline.
        Weighted 70/30 toward realisation (it directly maps to the net the LP keeps).
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        drag_penalty = _clamp(1.0 - drag_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * drag_penalty, 0.0, 100.0)

    def _classify(self, drag_fraction: float, net_is_negative: bool) -> str:
        if net_is_negative:
            # The stacked drags have eaten the whole headline APR (or more).
            return "SEVERE_EROSION"
        if drag_fraction <= CLEAN_FRACTION:
            return "CLEAN_HEADLINE"
        if drag_fraction <= MILD_FRACTION:
            return "MILD_EROSION"
        if drag_fraction <= MODERATE_FRACTION:
            return "MODERATE_EROSION"
        return "SEVERE_EROSION"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification == "CLEAN_HEADLINE":
            return "TRUST_HEADLINE"
        if classification == "MILD_EROSION":
            return "DISCOUNT_HEADLINE_SLIGHTLY"
        if classification == "MODERATE_EROSION":
            return "DISCOUNT_HEADLINE"
        # SEVERE_EROSION
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        component_count: int,
        dominant_share: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        # Classification flag.
        flags.append(classification)

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_DRAGS")

        if classification == "CLEAN_HEADLINE":
            flags.append("CLEAN_HEADLINE_CONFIRMED")

        if used_override:
            flags.append("DRAG_FROM_OVERRIDE")
        else:
            # Component-only flags are NOT meaningful on the override path.
            if (dominant_share is not None
                    and component_count >= 1
                    and dominant_share >= DOMINANT_SHARE_THRESHOLD):
                flags.append("SINGLE_DOMINANT_DRAG")
            if component_count >= MANY_SOURCES_THRESHOLD:
                flags.append("MANY_DRAG_SOURCES")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": None,
            "raw_total_drag_apr_pct": None,
            "net_realized_apr_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "drag_fraction": None,
            "component_count": 0,
            "dominant_source": None,
            "dominant_drag_apr_pct": None,
            "dominant_share": None,
            "net_is_negative": False,
            "used_override": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_OR_VERIFY",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [
            r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "cleanest_headline_vault": None,
                "worst_eroded_vault": None,
                "avg_score": 0.0,
                "net_negative_count": 0,
                "position_count": len(results),
            }
        # Higher score = realised ≈ headline → highest score is the cleanest.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_negative = sum(
            1 for r in results
            if "NET_NEGATIVE_AFTER_DRAGS" in r.get("flags", []))
        return {
            "cleanest_headline_vault": by_score[-1]["token"],
            "worst_eroded_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "net_negative_count": net_negative,
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
                    "score": r["score"],
                    "recommendation": r["recommendation"],
                    "dominant_source": r["dominant_source"],
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
            # CLEAN_HEADLINE: a couple of tiny drags relative to the headline.
            "vault": "USDC-Vault-CleanHeadline",
            "headline_apr_pct": 18.0,
            "drag_components": [
                {"source": "entry_exit_fee", "drag_apr_pct": 0.3},
                {"source": "management_fee", "drag_apr_pct": 0.2},
            ],
        },
        {
            # MILD_EROSION: a modest stack of drags.
            "vault": "stETH-Vault-MildErosion",
            "headline_apr_pct": 12.0,
            "drag_components": [
                {"source": "management_fee", "drag_apr_pct": 1.0},
                {"source": "autosell_slippage", "drag_apr_pct": 0.8},
                {"source": "idle_cash", "drag_apr_pct": 0.4},
            ],
        },
        {
            # SEVERE_EROSION: stacked drags exceed the headline → net negative,
            # loss stream is the dominant culprit.
            "vault": "GOV-Vault-SevereErosion",
            "headline_apr_pct": 10.0,
            "drag_components": [
                {"source": "net_of_loss", "drag_apr_pct": 7.0},
                {"source": "performance_fee_vol_tax", "drag_apr_pct": 3.0},
                {"source": "entry_exit_fee", "drag_apr_pct": 2.0},
            ],
        },
        {
            # Override path: a pre-summed total drag supplied directly.
            "vault": "LST-Vault-OverrideTotal",
            "headline_apr_pct": 24.0,
            "total_drag_apr_pct": 9.0,
        },
        {
            # INSUFFICIENT_DATA: no headline running APR supplied.
            "vault": "MYSTERY-Vault-NoData",
            "drag_components": [{"source": "fee", "drag_apr_pct": 1.0}],
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1206 Vault Headline Yield Honesty Composite Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
