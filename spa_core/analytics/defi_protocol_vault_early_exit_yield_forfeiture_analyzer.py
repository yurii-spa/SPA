"""
MP-1216: DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer
================================================================================
Advisory/read-only analytics module.

A vault accrues yield continuously but only CRYSTALLIZES it — makes it
withdrawable / claimable — at discrete points, or only after a cooldown / lock /
vesting window has elapsed. The slice of yield accrued SINCE the last
crystallization but NOT YET crystallized is "pending" yield. If capital exits
the vault BEFORE that pending slice vests, the pending slice is FORFEITED — it
stays in the vault for the remaining LPs and the exiting depositor never
receives it. For a yield optimizer that ROTATES capital between strategies
(SPA's tournament/promotion pipeline), this is a real, recurring drag on the
REALIZED APY of an early rotation: the headline APY is the accrued APY, but the
yield actually banked on exit is the accrued yield minus the forfeited pending
slice:

    pending_yield_pct        = clamp(pending_yield_pct, 0, total_accrued_yield)
    vesting_fraction         = clamp(vesting_progress_pct / 100, 0, 1)
    forfeited_yield_pct      = pending                      (CLIFF mode)
                             = pending * (1 - vesting_fraction)  (LINEAR mode)
    kept_yield_pct           = total_accrued_yield - forfeited_yield_pct
    forfeiture_fraction      = clamp(forfeited / total_accrued_yield, 0, 1)
    realization_ratio        = clamp(kept / total_accrued_yield, 0, 1)
    safe_fraction            = clamp(1 - pending / total_accrued_yield, 0, 1)
                               (= the share already crystallized / safe to
                                withdraw regardless of exit timing)

The headline says "you earned X% APY", but exiting before the pending slice
crystallizes banks only the kept slice — the pending slice (or, under LINEAR
vesting, its unvested part) is forfeited to the remaining LPs. The scale-free
forfeiture_fraction is the share of the TOTAL accrued yield lost on the early
exit; it is the basis of the classification. When nothing is pending (the whole
accrued yield is already crystallized) the exit forfeits nothing (HIGHER score).
When the entire accrued yield is still pending and unvested (CLIFF exit at the
start of the window) the exit forfeits all of it (LOWER score).

HIGHER score = little/no yield is forfeited on the planned exit (most of the
accrued yield is already crystallized, or LINEAR vesting is far along), the exit
is effectively free, nothing to fix.
LOWER score = a large share of the accrued yield is forfeited on the early exit
(a large unvested pending slice), so the realized APY of the rotation is far
below the headline accrued APY.

Override path (when forfeited_yield_pct is supplied directly, finite, AND a
valid POSITIVE total_accrued_yield_pct is present): take the forfeited yield
verbatim (negative → magnitude, clamped to [0, total]) and skip the
pending / vesting geometry — forfeiture_fraction and realization_ratio are
computed the same way:

    forfeiture_fraction = clamp(forfeited / total_accrued_yield, 0, 1)
    realization_ratio   = clamp(1 - forfeiture_fraction, 0, 1)

(On the override path the pending / vesting / mode geometry is not known → those
fields are reported as None, safe_fraction is anchored to realization_ratio, and
the geometry-only flags PENDING_YIELD_AT_RISK / FULL_FORFEITURE / CLIFF_VESTING /
LINEAR_VESTING are NOT raised.)

Distinct from (this is the FORFEITURE of accrued-but-not-yet-crystallized yield
on an early exit, NOT a fee and NOT a deployment/utilization drag):
  * defi_protocol_vault_exit_fee_* / withdrawal_fee modules — those price an EXIT
    / WITHDRAWAL FEE: a percentage of the PRINCIPAL (or of the withdrawal amount)
    charged ON exit and PAID OUT to the vault/protocol. HERE the depositor pays
    no fee; instead the unvested pending YIELD is forfeited (retained by the
    remaining LPs), and the loss scales with the pending-yield slice, not with
    principal. Distinct axis.
  * defi_protocol_vault_idle_cash_drag_analyzer — that prices the drag from
    UNINVESTED / idle cash sitting in the vault earning nothing. HERE the capital
    WAS deployed and DID accrue yield; the loss is the FORFEITURE of that accrued
    yield on early exit, not idle capital. Distinct axis.
  * defi_protocol_vault_deployment_ramp_drag_analyzer — that prices the drag while
    freshly deposited capital RAMPS into deployment at entry. HERE it is the EXIT
    side: accrued yield forfeited when leaving before crystallization. Distinct
    axis.
  * defi_protocol_yield_harvesting_frequency_optimizer / harvest_cycle_entry_timing
    — those price WHEN to harvest/compound to maximise yield. HERE the yield is
    already accrued; the axis is what is LOST by exiting before it crystallizes,
    independent of harvest cadence.
  * defi_protocol_vault_performance_fee_* modules — those price the performance
    FEE BASE (gross-of-cost / gross-of-reserve / management / HWM / hurdle /
    catch-up). HERE there is no performance fee; the loss is the forfeiture of the
    pending yield itself on exit. Distinct axis.
  * defi_protocol_vault_pending_harvest_premium_analyzer — that prices the
    PREMIUM a buyer of the vault share captures from un-harvested pending yield
    on ENTRY. HERE it is the mirror EXIT cost: the SELLER forfeiting the unvested
    pending yield on early exit. Distinct (entry-premium vs exit-forfeiture) axis.
  * defi_protocol_yield_reserve_buffer_analyzer — that assesses an internal
    reserve/insurance buffer's adequacy. HERE it is the per-exit forfeiture of
    pending yield, not a standing buffer.

The novel axis here: the FORFEITURE of accrued-but-not-yet-crystallized
("pending") yield when capital exits a vault BEFORE its crystallization /
cooldown / vesting window elapses — an early-rotation realized-APY drag distinct
from any fee, idle-cash drag, ramp drag, or harvest-timing axis.

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
    "data", "vault_early_exit_yield_forfeiture_log.json"
)
LOG_CAP = 100

# Classification thresholds on the scale-free forfeiture_fraction in
# [0, 1] (= forfeited_yield_pct / total_accrued_yield_pct).
CLEAN_FRACTION = 0.05        # at/below → effectively no forfeiture
MILD_FRACTION = 0.20         # at/below → mild forfeiture
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe forfeiture

# Long-cooldown informational flag threshold on cooldown_days.
HIGH_COOLDOWN_DAYS = 14.0

# Vesting modes.
MODE_CLIFF = "CLIFF"
MODE_LINEAR = "LINEAR"

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


def _safe_div(num: float, den: float, sentinel):
    if den <= 0:
        return sentinel
    return num / den


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


def _coerce_signed(val) -> Optional[float]:
    """
    Coerce a value to a finite SIGNED float (may be negative), or None if it is
    not interpretable. Identical to _coerce_num; kept as a named alias for the
    override field, which may legitimately arrive negative (→ magnitude).
    """
    return _coerce_num(val)


def _coerce_count(val) -> Optional[int]:
    """
    Coerce a value to a non-negative integer count, or None if not interpretable.
    """
    cv = _coerce_num(val)
    if cv is None or not math.isfinite(cv):
        return None
    iv = int(cv)
    return iv if iv >= 0 else None


def _coerce_mode(val) -> str:
    """
    Coerce the forfeit_mode field to MODE_CLIFF or MODE_LINEAR.
    Anything not recognisably LINEAR defaults to CLIFF (the conservative, most
    common crystallization mode).
    """
    if isinstance(val, str):
        s = val.strip().upper()
        if s == MODE_LINEAR:
            return MODE_LINEAR
    return MODE_CLIFF


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

class DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer:
    """
    Measures the share of a vault's accrued yield that is FORFEITED when capital
    exits BEFORE the accrued-but-not-yet-crystallized ("pending") yield vests —
    the realized-APY drag of an early rotation versus the headline accrued APY.

        pending_yield_pct   = clamp(pending_yield_pct, 0, total_accrued_yield)
        vesting_fraction    = clamp(vesting_progress_pct / 100, 0, 1)
        forfeited_yield_pct = pending                       (CLIFF mode)
                            = pending * (1 - vesting_fraction)   (LINEAR mode)
        kept_yield_pct      = total_accrued_yield - forfeited_yield_pct
        forfeiture_fraction = clamp(forfeited / total_accrued_yield, 0, 1)
        realization_ratio   = clamp(kept / total_accrued_yield, 0, 1)
        safe_fraction       = clamp(1 - pending / total_accrued_yield, 0, 1)

    When nothing is pending (the whole accrued yield is already crystallized) the
    early exit forfeits nothing (NO_FORFEITURE). When a large unvested pending
    slice remains, a large share of the accrued yield is forfeited
    (MODERATE / SEVERE forfeiture), and the realized APY of the rotation falls far
    below the headline accrued APY.

    HIGHER score = little/no yield forfeited on the planned exit, the exit is
    effectively free.
    LOWER score = a large share of the accrued yield is forfeited on the early
    exit (a large unvested pending slice).

    Per-position input dict fields:
        vault / token            : str
        total_accrued_yield_pct  : float — the TOTAL yield accrued at the planned
                                   exit (headline accrued yield). REQUIRED, must
                                   be a finite POSITIVE number (else
                                   INSUFFICIENT_DATA).
        pending_yield_pct        : float — the accrued-but-not-yet-crystallized
                                   (at-risk) slice (finite ≥ 0; clamped to
                                   [0, total]; default 0.0 = nothing at risk →
                                   nothing is forfeited).
        vesting_progress_pct     : float — how far through the vesting / cooldown
                                   window the exit occurs, 0..100 (coerced,
                                   clamped 0..100; default 0.0). Only applied in
                                   LINEAR mode.
        forfeit_mode             : str — "CLIFF" (default; the whole pending slice
                                   is forfeited until it crystallizes) or "LINEAR"
                                   (pro-rata: the unvested part of pending is
                                   forfeited).
        cooldown_days            : float — OPTIONAL informational cooldown / lock
                                   length in days; ≥ HIGH_COOLDOWN_DAYS raises
                                   LONG_COOLDOWN.
        forfeited_yield_pct      : float — OPTIONAL direct override of the
                                   forfeited yield. When supplied (finite;
                                   negative → magnitude) AND a valid POSITIVE
                                   total_accrued_yield_pct is present, take this
                                   verbatim (clamped to [0, total]) and skip the
                                   pending / vesting geometry (override path;
                                   geometry → None).
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

        # The total accrued yield is required and must be finite & positive.
        total_gain = _coerce_num(p.get("total_accrued_yield_pct"))
        if total_gain is None or not math.isfinite(total_gain) or total_gain <= 0.0:
            return self._insufficient(token)

        cooldown_days = _coerce_num(p.get("cooldown_days"))

        # Override path: a direct forfeited-yield amount.
        forfeited_o = _coerce_signed(p.get("forfeited_yield_pct"))
        if forfeited_o is not None and math.isfinite(forfeited_o):
            return self._analyze_override(
                token, total_gain, abs(forfeited_o), cooldown_days)

        return self._analyze_main(token, p, total_gain, cooldown_days)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, total_gain: float,
        cooldown_days: Optional[float],
    ) -> dict:
        mode = _coerce_mode(p.get("forfeit_mode"))

        # pending yield: accrued-but-not-yet-crystallized slice, clamped to
        # [0, total]. Default 0.0 = nothing at risk.
        pending = _coerce_num(p.get("pending_yield_pct"))
        if pending is None or not math.isfinite(pending):
            pending = 0.0
        pending = _clamp(pending, 0.0, total_gain)

        # vesting progress, only applied in LINEAR mode.
        vp = _coerce_num(p.get("vesting_progress_pct"))
        if vp is None or not math.isfinite(vp):
            vp = 0.0
        vesting_fraction = _clamp(vp / 100.0, 0.0, 1.0)

        if mode == MODE_LINEAR:
            forfeited = pending * (1.0 - vesting_fraction)
        else:  # MODE_CLIFF — whole pending slice forfeited until crystallization.
            forfeited = pending
        forfeited = _clamp(forfeited, 0.0, total_gain)

        return self._finish(
            token=token,
            total_accrued_yield_pct=total_gain,
            pending_yield_pct=pending,
            vesting_fraction=vesting_fraction,
            forfeited_yield_pct=forfeited,
            mode=mode,
            cooldown_days=cooldown_days,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, total_gain: float, forfeited: float,
        cooldown_days: Optional[float],
    ) -> dict:
        # The forfeited yield can not exceed the total accrued yield.
        forfeited = _clamp(forfeited, 0.0, total_gain)
        # pending / vesting / mode geometry is unknown on the override path →
        # report None; safe_fraction falls back to realization_ratio.
        return self._finish(
            token=token,
            total_accrued_yield_pct=total_gain,
            pending_yield_pct=None,
            vesting_fraction=None,
            forfeited_yield_pct=forfeited,
            mode=None,
            cooldown_days=cooldown_days,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        total_accrued_yield_pct: float,
        pending_yield_pct: Optional[float],
        vesting_fraction: Optional[float],
        forfeited_yield_pct: float,
        mode: Optional[str],
        cooldown_days: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        kept_yield_pct = max(0.0, total_accrued_yield_pct - forfeited_yield_pct)

        # Scale-free forfeiture fraction — the share of the TOTAL accrued yield
        # lost on the early exit. (total > 0 is guaranteed at this point.)
        if total_accrued_yield_pct > EPS:
            forfeiture_fraction = _clamp(
                forfeited_yield_pct / total_accrued_yield_pct, 0.0, 1.0)
        else:
            forfeiture_fraction = 0.0

        realization_ratio = _clamp(1.0 - forfeiture_fraction, 0.0, 1.0)

        # safe_fraction = the share already crystallized (safe regardless of
        # exit timing). Known only on the main path; on the override path the
        # pending slice is unknown → anchor to realization_ratio.
        if pending_yield_pct is not None:
            safe_fraction = _clamp(
                1.0 - pending_yield_pct / total_accrued_yield_pct, 0.0, 1.0)
        else:
            safe_fraction = realization_ratio

        full_forfeiture = forfeited_yield_pct >= (total_accrued_yield_pct - EPS)

        classification = self._classify(forfeiture_fraction)
        score = self._score(realization_ratio, safe_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            pending_yield_pct,
            full_forfeiture,
            mode,
            cooldown_days,
            used_override,
        )

        return {
            "token": token,
            "total_accrued_yield_pct": round(total_accrued_yield_pct, 4),
            "pending_yield_pct": (
                round(pending_yield_pct, 4)
                if pending_yield_pct is not None else None),
            "vesting_progress_pct": (
                round(vesting_fraction * 100.0, 4)
                if vesting_fraction is not None else None),
            "forfeited_yield_pct": round(forfeited_yield_pct, 4),
            "kept_yield_pct": round(kept_yield_pct, 4),
            "forfeiture_fraction": round(forfeiture_fraction, 4),
            "realization_ratio": round(realization_ratio, 4),
            "safe_fraction": round(safe_fraction, 4),
            "full_forfeiture": full_forfeiture,
            "forfeit_mode": mode,
            "cooldown_days": (
                round(cooldown_days, 4) if cooldown_days is not None else None),
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
        safe_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = little/no accrued yield is forfeited on the planned exit.
        Two components:
          * realisation = clamp(realization_ratio, 0, 1) — the fraction of the
            accrued yield actually banked on exit (the share NOT forfeited),
          * safety = clamp(safe_fraction, 0, 1) — the structural share already
            crystallized (safe to withdraw regardless of exit timing); on LINEAR
            vesting this differs from realisation (partial vesting saves part of
            the pending slice), on CLIFF / override it coincides with it.
        Weighted 70/30 toward realisation (it directly maps to the realized APY
        the rotation banks).
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        safety = _clamp(safe_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * safety, 0.0, 100.0)

    def _classify(self, forfeiture_fraction: float) -> str:
        if forfeiture_fraction <= CLEAN_FRACTION:
            return "NO_FORFEITURE"
        if forfeiture_fraction <= MILD_FRACTION:
            return "MILD_FORFEITURE"
        if forfeiture_fraction <= MODERATE_FRACTION:
            return "MODERATE_FORFEITURE"
        return "SEVERE_FORFEITURE"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_EARLY_EXIT"
        if classification == "NO_FORFEITURE":
            return "EXIT_ANYTIME"
        if classification == "MILD_FORFEITURE":
            return "MINOR_EXIT_COST"
        if classification == "MODERATE_FORFEITURE":
            return "DELAY_EXIT_TO_VEST"
        # SEVERE_FORFEITURE
        return "AVOID_EARLY_EXIT"

    def _flags(
        self,
        classification: str,
        pending_yield_pct: Optional[float],
        full_forfeiture: bool,
        mode: Optional[str],
        cooldown_days: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        # Classification flag.
        flags.append(classification)

        if classification == "NO_FORFEITURE":
            flags.append("FULLY_VESTED_EXIT")

        if (cooldown_days is not None
                and cooldown_days >= HIGH_COOLDOWN_DAYS):
            flags.append("LONG_COOLDOWN")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if pending_yield_pct is not None and pending_yield_pct > 0.0:
                flags.append("PENDING_YIELD_AT_RISK")
            if full_forfeiture:
                flags.append("FULL_FORFEITURE")
            if mode == MODE_CLIFF:
                flags.append("CLIFF_VESTING")
            elif mode == MODE_LINEAR:
                flags.append("LINEAR_VESTING")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "total_accrued_yield_pct": None,
            "pending_yield_pct": None,
            "vesting_progress_pct": None,
            "forfeited_yield_pct": None,
            "kept_yield_pct": None,
            "forfeiture_fraction": None,
            "realization_ratio": None,
            "safe_fraction": None,
            "full_forfeiture": False,
            "forfeit_mode": None,
            "cooldown_days": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_EARLY_EXIT",
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
                "worst_forfeiture_vault": None,
                "avg_score": 0.0,
                "full_forfeiture_count": 0,
                "position_count": len(results),
            }
        # Higher score = less forfeited on exit → highest score is the cleanest
        # vault to rotate out of.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        full_forfeiture = sum(
            1 for r in results
            if "FULL_FORFEITURE" in r.get("flags", []))
        return {
            "cleanest_vault": by_score[-1]["token"],
            "worst_forfeiture_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "full_forfeiture_count": full_forfeiture,
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
            # NO_FORFEITURE: nothing pending — the whole accrued yield is already
            # crystallized, so the early exit forfeits nothing.
            "vault": "USDC-Vault-FullyCrystallized",
            "total_accrued_yield_pct": 18.0,
            "pending_yield_pct": 0.0,
            "forfeit_mode": "CLIFF",
            "cooldown_days": 0.0,
        },
        {
            # MODERATE_FORFEITURE (CLIFF): ~40% of the accrued yield is pending
            # and forfeited entirely on exit before crystallization.
            "vault": "stETH-Vault-CliffExit",
            "total_accrued_yield_pct": 15.0,
            "pending_yield_pct": 6.0,
            "forfeit_mode": "CLIFF",
            "cooldown_days": 7.0,
        },
        {
            # SEVERE_FORFEITURE (CLIFF at window start): the whole accrued yield
            # is still pending and unvested → all of it forfeited on early exit.
            "vault": "GOV-Vault-FullForfeit",
            "total_accrued_yield_pct": 12.0,
            "pending_yield_pct": 12.0,
            "forfeit_mode": "CLIFF",
            "cooldown_days": 21.0,
        },
        {
            # MILD_FORFEITURE (LINEAR, far along): 8% pending but 80% vested →
            # only 1.6% forfeited of 20% accrued (fraction ~ 0.08).
            "vault": "LST-Vault-LinearVesting",
            "total_accrued_yield_pct": 20.0,
            "pending_yield_pct": 8.0,
            "vesting_progress_pct": 80.0,
            "forfeit_mode": "LINEAR",
            "cooldown_days": 10.0,
        },
        {
            # Override path: forfeited yield supplied directly → fraction = 3/24
            # = 0.125 → MILD.
            "vault": "RWA-Vault-OverrideForfeit",
            "total_accrued_yield_pct": 24.0,
            "forfeited_yield_pct": 3.0,
        },
        {
            # INSUFFICIENT_DATA: no total accrued yield supplied.
            "vault": "MYSTERY-Vault-NoData",
            "pending_yield_pct": 5.0,
            "forfeit_mode": "CLIFF",
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1216 Vault Early-Exit Yield-Forfeiture Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
