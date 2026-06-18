"""
MP-1232: DeFiProtocolVaultFailedHarvestGasDragAnalyzer
================================================================================
Advisory/read-only analytics module.

Auto-compounding vaults rely on periodic ``harvest()`` / ``compound()``
transactions (keeper bots, or anyone) to realise rewards and re-stake them.
A non-trivial share of those attempts REVERT — the slippage guard trips, the
tx runs out of gas, an MEV bot wins the race, or the price/oracle moves
mid-block — yet the failed transaction STILL BURNS GAS. The gas spent on
reverted harvest attempts is pure drag on the depositor's net yield, and a
high failure rate is itself a reliability red flag for the strategy's keeper
infrastructure.

Economically, over a measurement window the realised net yield is:

    failed_gas_drag_pct = gas_per_attempt_pct * failed_harvests
    net_yield_after_failed_gas_pct = gross_yield_pct - failed_gas_drag_pct

where ``gas_per_attempt_pct`` is the gas cost of a single harvest transaction
expressed as a percentage of the position size. The headline APY a vault
advertises is computed off the SUCCESSFUL harvests; it silently ignores the
gas burned on the reverted attempts that produced no compounding. Two axes
matter and are combined:

    failure_rate            = failed_harvests / harvest_attempts        (0..1)
    gas_per_attempt_pct     = avg_gas_cost_per_attempt_usd / position_size_usd * 100
    failed_gas_drag_pct     = gas_per_attempt_pct * failed_harvests
    total_gas_drag_pct      = gas_per_attempt_pct * harvest_attempts
    wasted_gas_fraction     = clamp(failed_gas_drag / total_gas_drag, 0, 1)
                              (= failure_rate under a uniform per-attempt cost)
    net_yield_after_failed_gas_pct = gross_yield - failed_gas_drag
    realization_ratio       = clamp(net_after_failed_gas / gross_yield, 0, 1)

HIGHER score = the keeper reliably lands its harvests (low failure_rate) and
the gas burned on reverts is a tiny share of the yield — nothing to fix.
LOWER score = a large share of harvest attempts revert (wasting gas and
skipping compounding), or the failed-harvest gas drag drives the net yield
negative.

Override path (when ``failed_gas_drag_pct`` is supplied directly, finite, AND
a valid POSITIVE ``gross_yield_pct`` and a POSITIVE ``gas_drag_basis_pct``
(total harvest-gas drag) are present): take the failed-gas drag verbatim
(negative → magnitude, capped at the basis) and skip the per-attempt geometry
— ``wasted_gas_fraction`` is computed as::

    wasted_gas_fraction = clamp(failed_gas_drag_pct / gas_drag_basis_pct, 0, 1)

On the override path the per-attempt / failure-rate geometry is unknown → the
``failure_rate`` / ``harvest_attempts`` / ``failed_harvests`` fields are
reported as None, the classification is driven by ``wasted_gas_fraction``
instead of the failure rate, the geometry-only flags
(FAILED_HARVEST_GAS_DRAG / FULL_GAS_WASTED_ON_FAILURES) are NOT raised, and
``realization_ratio`` is anchored to ``(1 - wasted_gas_fraction)``.

Distinct from (this is WASTED gas burned on REVERTED harvest attempts — a
reliability/drag axis, not a fee, not successful-harvest gas, and not harvest
timing/frequency):
  * defi_protocol_vault_performance_fee_gross_of_cost_base_gap_analyzer and the
    other gross_of_* perf-fee modules — those price a PERFORMANCE FEE charged
    on a gross-of-some-cost base. HERE there is no performance fee; the drag is
    GAS literally burned by the EVM on transactions that REVERTED and produced
    no compounding.
  * defi_protocol_vault_gas_cost / defi_protocol_gas_cost_breakeven_analyzer and
    similar gas modules — those price the gas of SUCCESSFUL harvests (and the
    yield needed to break even on it). HERE it is the gas of the FAILED
    attempts specifically — gas spent for zero compounding benefit.
  * defi_protocol_yield_harvesting_frequency_optimizer /
    defi_protocol_vault_harvest_timing_analyzer / defi_reward_harvesting_optimizer
    — those decide WHEN / HOW OFTEN to harvest to maximise net yield. HERE the
    axis is the RELIABILITY of the attempts that are made: what share of them
    revert and how much gas that wastes, independent of the chosen cadence.
  * defi_protocol_vault_pending_harvest_premium_analyzer — that prices unrealised
    pending-but-unharvested rewards. HERE it is gas burned on attempts that
    actively FAILED, not the opportunity cost of not harvesting.

The novel axis here: FAILED-HARVEST GAS DRAG — the gas burned on REVERTED
auto-compounder transactions, and the keeper's harvest FAILURE RATE, as a drag
on realised net yield that the headline APY (computed off successful harvests)
omits.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_failed_harvest_gas_drag_log.json"
)
LOG_CAP = 100

# Classification thresholds on the failure signal in [0, 1]
# (failure_rate on the main path, wasted_gas_fraction on the override path).
CLEAN_FRACTION = 0.05        # at/below → reliable harvesting, negligible waste
MILD_FRACTION = 0.20         # at/below → mild failure drag
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe

# Flag threshold: failed-harvest gas drag that eats a large share of the gross
# yield is materially significant even when the failure rate looks modest.
HIGH_GAS_DRAG_PCT_OF_YIELD = 0.25   # failed_gas_drag >= 25% of gross yield

# Small epsilon to keep normalisers finite.
EPS = 1e-12


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


def _coerce_count(val) -> Optional[int]:
    """
    Coerce a value to a non-negative integer count, or None if not interpretable.
    """
    cv = _coerce_num(val)
    if cv is None or not math.isfinite(cv):
        return None
    iv = int(cv)
    return iv if iv >= 0 else None


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

class DeFiProtocolVaultFailedHarvestGasDragAnalyzer:
    """
    Measures the drag a vault's depositor suffers from gas burned on REVERTED
    auto-compounder harvest transactions, and the keeper's harvest FAILURE
    RATE, relative to the gross yield the headline APY is computed from.

        failure_rate                   = failed_harvests / harvest_attempts
        gas_per_attempt_pct            = avg_gas_cost_per_attempt_usd / position_size_usd * 100
        failed_gas_drag_pct            = gas_per_attempt_pct * failed_harvests
        total_gas_drag_pct             = gas_per_attempt_pct * harvest_attempts
        wasted_gas_fraction            = clamp(failed_gas_drag / total_gas_drag, 0, 1)
        net_yield_after_failed_gas_pct = gross_yield - failed_gas_drag
        realization_ratio              = clamp(net_after_failed_gas / gross_yield, 0, 1)

    A small failure_rate with negligible failed-gas drag means the keeper lands
    its harvests reliably and the headline APY is honest about gas
    (RELIABLE_HARVESTING). A large failure_rate wastes gas and skips
    compounding (MODERATE / SEVERE failure drag); if the failed-harvest gas
    drives the net yield negative the position is bleeding gas faster than it
    earns.

    HIGHER score = reliable harvesting, negligible wasted gas. LOWER score = a
    large share of harvest attempts revert, or the failed-gas drag drives the
    net yield negative.

    Per-position input dict fields:
        vault / token                  : str
        gross_yield_pct                : float — the GROSS yield (before gas) the
                                         headline APY is computed from. REQUIRED,
                                         must be finite POSITIVE (else
                                         INSUFFICIENT_DATA).
        harvest_attempts               : int — total harvest txs attempted over
                                         the window. REQUIRED on the main path,
                                         must be finite > 0.
        failed_harvests                : int — number that reverted (clamped to
                                         0..harvest_attempts; default 0).
        avg_gas_cost_per_attempt_usd   : float — gas burned per harvest tx
                                         (success or revert). OPTIONAL; combined
                                         with position_size_usd to derive the
                                         per-attempt %; missing/≤0 → 0 drag.
        position_size_usd              : float — position size to convert gas to
                                         %-of-position (finite > 0 required for a
                                         non-zero gas drag).
        failed_gas_drag_pct            : float — OPTIONAL direct override of the
                                         failed-harvest gas drag as %-of-position.
                                         When supplied (finite; negative →
                                         magnitude) AND a valid POSITIVE
                                         gross_yield_pct and POSITIVE
                                         gas_drag_basis_pct are present, take this
                                         drag directly and skip the per-attempt
                                         geometry (override path; geometry → None).
        gas_drag_basis_pct             : float — OPTIONAL, only used on the
                                         override path as the denominator for
                                         wasted_gas_fraction (total harvest-gas
                                         drag; finite > 0 required to take the
                                         override path).
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

        # The gross yield is required and must be finite & positive.
        gross_gain = _coerce_num(p.get("gross_yield_pct"))
        if gross_gain is None or not math.isfinite(gross_gain) or gross_gain <= 0.0:
            return self._insufficient(token)

        # Override path: a direct failed-gas drag + a positive basis.
        drag_o = _coerce_num(p.get("failed_gas_drag_pct"))
        basis_o = _coerce_num(p.get("gas_drag_basis_pct"))
        if (drag_o is not None and math.isfinite(drag_o)
                and basis_o is not None and math.isfinite(basis_o)
                and basis_o > 0.0):
            return self._analyze_override(
                token, gross_gain, abs(drag_o), basis_o)

        # Main path: harvest_attempts is required and must be > 0.
        attempts = _coerce_count(p.get("harvest_attempts"))
        if attempts is None or attempts <= 0:
            return self._insufficient(token)

        return self._analyze_main(token, p, gross_gain, attempts)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross_gain: float, attempts: int,
    ) -> dict:
        failed = _coerce_count(p.get("failed_harvests"))
        if failed is None:
            failed = 0
        failed = min(failed, attempts)
        failure_rate = _clamp(failed / attempts, 0.0, 1.0) if attempts > 0 else 0.0

        # Per-attempt gas as a percentage of position size.
        gas_usd = _coerce_num(p.get("avg_gas_cost_per_attempt_usd"))
        pos_usd = _coerce_num(p.get("position_size_usd"))
        if (gas_usd is not None and gas_usd > 0.0
                and pos_usd is not None and pos_usd > 0.0):
            gas_per_attempt_pct = gas_usd / pos_usd * 100.0
        else:
            gas_per_attempt_pct = 0.0

        failed_gas_drag_pct = gas_per_attempt_pct * failed
        total_gas_drag_pct = gas_per_attempt_pct * attempts

        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            harvest_attempts=attempts,
            failed_harvests=failed,
            failure_rate=failure_rate,
            gas_per_attempt_pct=gas_per_attempt_pct,
            failed_gas_drag_pct=failed_gas_drag_pct,
            total_gas_drag_pct=total_gas_drag_pct,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_gain: float, drag: float, basis: float,
    ) -> dict:
        # The failed-gas drag cannot exceed the total harvest-gas drag.
        drag = min(drag, basis)
        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            harvest_attempts=None,
            failed_harvests=None,
            failure_rate=None,
            gas_per_attempt_pct=None,
            failed_gas_drag_pct=drag,
            total_gas_drag_pct=basis,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_yield_pct: float,
        harvest_attempts: Optional[int],
        failed_harvests: Optional[int],
        failure_rate: Optional[float],
        gas_per_attempt_pct: Optional[float],
        failed_gas_drag_pct: float,
        total_gas_drag_pct: float,
        used_override: bool,
        used_main: bool,
    ) -> dict:
        # Net yield after the failed-harvest gas drag.
        net_yield_after_failed_gas_pct = gross_yield_pct - failed_gas_drag_pct
        net_is_negative = net_yield_after_failed_gas_pct < 0.0

        if gross_yield_pct > EPS:
            realization_ratio = _clamp(
                net_yield_after_failed_gas_pct / gross_yield_pct, 0.0, 1.0)
        else:
            realization_ratio = 0.0

        # Scale-free wasted-gas fraction — share of harvest-gas burned on reverts.
        if total_gas_drag_pct > EPS:
            wasted_gas_fraction = _clamp(
                failed_gas_drag_pct / total_gas_drag_pct, 0.0, 1.0)
        else:
            wasted_gas_fraction = 0.0

        # Failure signal driving the classification: failure_rate on the main
        # path, wasted_gas_fraction on the override path (failure_rate unknown).
        failure_signal = (
            failure_rate if failure_rate is not None else wasted_gas_fraction)

        # gas drag as a share of the gross yield (drives the HIGH_GAS_DRAG flag).
        if gross_yield_pct > EPS:
            gas_drag_yield_fraction = _clamp(
                failed_gas_drag_pct / gross_yield_pct, 0.0, 1.0)
        else:
            gas_drag_yield_fraction = 0.0

        classification = self._classify(failure_signal, net_is_negative)
        score = self._score(realization_ratio, failure_signal, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            failed_harvests,
            gas_drag_yield_fraction,
            used_override,
        )

        return {
            "token": token,
            "gross_yield_pct": round(gross_yield_pct, 4),
            "harvest_attempts": harvest_attempts,
            "failed_harvests": failed_harvests,
            "failure_rate": (
                round(failure_rate, 4) if failure_rate is not None else None),
            "gas_per_attempt_pct": (
                round(gas_per_attempt_pct, 6)
                if gas_per_attempt_pct is not None else None),
            "failed_gas_drag_pct": round(failed_gas_drag_pct, 4),
            "total_gas_drag_pct": round(total_gas_drag_pct, 4),
            "net_yield_after_failed_gas_pct": round(
                net_yield_after_failed_gas_pct, 4),
            "overstatement_pct": round(failed_gas_drag_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "wasted_gas_fraction": round(wasted_gas_fraction, 4),
            "gas_drag_yield_fraction": round(gas_drag_yield_fraction, 4),
            "net_is_negative": net_is_negative,
            "sample_count": 0,
            "used_override": used_override,
            "used_main": used_main,
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
        failure_signal: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the keeper lands its harvests reliably and the gas
        burned on reverts is a tiny share of the yield. Two components:
          * realisation = clamp(realization_ratio, 0, 1)
          * reliability penalty = clamp(1 − failure_signal, 0, 1)
        Weighted 70/30 toward realisation.
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        reliability = _clamp(1.0 - failure_signal, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * reliability, 0.0, 100.0)

    def _classify(self, failure_signal: float, net_is_negative: bool) -> str:
        if net_is_negative:
            return "SEVERE_HARVEST_FAILURE_DRAG"
        if failure_signal <= CLEAN_FRACTION:
            return "RELIABLE_HARVESTING"
        if failure_signal <= MILD_FRACTION:
            return "MILD_HARVEST_FAILURE_DRAG"
        if failure_signal <= MODERATE_FRACTION:
            return "MODERATE_HARVEST_FAILURE_DRAG"
        return "SEVERE_HARVEST_FAILURE_DRAG"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_FAILED_HARVEST_DRAG"
        if classification == "RELIABLE_HARVESTING":
            return "TRUST_KEEPER_RELIABILITY"
        if classification == "MILD_HARVEST_FAILURE_DRAG":
            return "MINOR_FAILED_HARVEST_DRAG"
        if classification == "MODERATE_HARVEST_FAILURE_DRAG":
            return "DEMAND_KEEPER_FIX"
        # SEVERE_HARVEST_FAILURE_DRAG
        return "AVOID_FAILED_HARVEST_DRAG"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        failed_harvests: Optional[int],
        gas_drag_yield_fraction: float,
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        flags.append(classification)

        if classification == "RELIABLE_HARVESTING":
            flags.append("RELIABLE_KEEPER")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_GAS")

        if gas_drag_yield_fraction >= HIGH_GAS_DRAG_PCT_OF_YIELD:
            flags.append("HIGH_GAS_DRAG")

        if used_override:
            flags.append("DRAG_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if failed_harvests is not None and failed_harvests > 0:
                flags.append("FAILED_HARVEST_GAS_DRAG")
            if net_is_negative:
                flags.append("FULL_GAS_WASTED_ON_FAILURES")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_yield_pct": None,
            "harvest_attempts": None,
            "failed_harvests": None,
            "failure_rate": None,
            "gas_per_attempt_pct": None,
            "failed_gas_drag_pct": None,
            "total_gas_drag_pct": None,
            "net_yield_after_failed_gas_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "wasted_gas_fraction": None,
            "gas_drag_yield_fraction": None,
            "net_is_negative": False,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_FAILED_HARVEST_DRAG",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [
            r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "cleanest_vault": None,
                "worst_failed_harvest_drag_vault": None,
                "avg_score": 0.0,
                "net_negative_count": 0,
                "position_count": len(results),
            }
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_negative = sum(
            1 for r in results
            if "NET_NEGATIVE_AFTER_GAS" in r.get("flags", []))
        return {
            "cleanest_vault": by_score[-1]["token"],
            "worst_failed_harvest_drag_vault": by_score[0]["token"],
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
            # RELIABLE_HARVESTING: 1 revert in 50 attempts, trivial gas.
            "vault": "USDC-Vault-ReliableKeeper",
            "gross_yield_pct": 15.0,
            "harvest_attempts": 50,
            "failed_harvests": 1,
            "avg_gas_cost_per_attempt_usd": 2.0,
            "position_size_usd": 250000.0,
        },
        {
            # MODERATE_HARVEST_FAILURE_DRAG: ~40% of harvest attempts revert.
            "vault": "CRV-Vault-FlakyKeeper",
            "gross_yield_pct": 14.0,
            "harvest_attempts": 40,
            "failed_harvests": 16,
            "avg_gas_cost_per_attempt_usd": 8.0,
            "position_size_usd": 120000.0,
        },
        {
            # SEVERE (net negative): tiny position, many reverts, fat gas →
            # failed-harvest gas exceeds the gross yield.
            "vault": "BAL-Vault-GasBleed",
            "gross_yield_pct": 6.0,
            "harvest_attempts": 60,
            "failed_harvests": 45,
            "avg_gas_cost_per_attempt_usd": 25.0,
            "position_size_usd": 9000.0,
        },
        {
            # Override path: failed-gas drag supplied directly.
            # drag 4.0, basis 10.0 → wasted_gas_fraction 0.4 → MODERATE.
            "vault": "UNI-Vault-OverrideDrag",
            "gross_yield_pct": 20.0,
            "failed_gas_drag_pct": 4.0,
            "gas_drag_basis_pct": 10.0,
        },
        {
            # INSUFFICIENT_DATA: no harvest attempts supplied.
            "vault": "MYSTERY-Vault-NoData",
            "gross_yield_pct": 12.0,
            "failed_harvests": 3,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1232 Vault Failed-Harvest Gas-Drag Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultFailedHarvestGasDragAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
