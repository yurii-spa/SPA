"""
MP-1204: DeFiProtocolVaultNetOfLossYieldRealizationAnalyzer
===========================================================
Advisory/read-only analytics module.

A vault advertises a headline "yield APY" computed ONLY from the POSITIVE income
stream — harvested reward emissions, trading fees collected, interest accrued —
annualised. But the depositor's TRUE realised return must NET that headline yield
against a SEPARATE stream of LOSS epochs that the headline OMITS: share-price
drawdowns from realised impermanent loss, slashing, bad-debt socialisation,
negative trading epochs. Those losses hit NAV directly but are NOT folded into the
advertised yield number, so the headline OVERSTATES the downside-inclusive realised
total APR.

This module subtracts the missed loss stream from the advertised yield stream and
measures the overstatement:

    headline_yield_apr_pct = mean(yield_samples) * periods_per_year
    loss_drag_apr_pct      = mean(loss_magnitudes) * periods_per_year   (0 if none)
    net_realized_apr_pct   = headline_yield_apr_pct - loss_drag_apr_pct
    overstatement_pct      = headline_yield_apr_pct - net_realized_apr_pct
                           = loss_drag_apr_pct
    realization_ratio      = clamp(net_realized / headline, 0, 1)   (headline > 0)
    loss_fraction          = clamp(loss_drag / headline, 0, 1)   (scale-free basis)

The headline says "24% trailing yield APY", but over the window there were realised
IL / bad-debt epochs of ~9% annualised that the headline never folds in → the
net-of-loss realised APR ≈ 15%. Discount the headline toward the downside-inclusive
return.

When the loss stream is EMPTY the loss drag is 0 → net == headline → realisation is
perfect (HIGHER score). When the loss stream rivals or exceeds the yield stream the
net realised collapses toward or below zero (LOWER score). The penalty is a FIRST-
moment subtraction of the missed loss stream: it vanishes when the loss stream is
empty EVEN IF the yield stream itself is volatile (that is a second-moment effect a
variance-drag analyser would price, not this one).

HIGHER score = losses are negligible (realised ≈ headline; the LP keeps the brochure
yield). LOWER score = a large loss stream the headline hides (realised far below the
headline, or net-negative).

Override path (when valid per-period yield samples < MIN_SAMPLES = 2): accept direct
position fields headline_yield_apr_pct + loss_drag_apr_pct and net them:

    net_realized_apr_pct = headline_yield_apr_pct - loss_drag_apr_pct
    overstatement_pct    = headline_yield_apr_pct - net_realized_apr_pct

(A non-positive override headline has no headline yield to net → INSUFFICIENT_DATA.)

Distinct from:
  * defi_protocol_vault_share_price_drawdown_analyzer — that scores the MAGNITUDE and
    RECOVERY of a SINGLE share-price drawdown EVENT. HERE we NET a RECURRING stream of
    loss epochs against the POSITIVE yield stream → a downside-inclusive realised APR
    and the headline overstatement, not the depth/recovery of one drawdown.
  * defi_protocol_vault_loss_socialization_exposure_analyzer — that scores forward
    EXPOSURE to socialised bad-debt as a RISK. HERE it is the honesty of the REALISED
    return: we subtract the already-realised loss stream from the advertised positive
    yield APR (a backward-looking realisation gap, not a forward risk).
  * defi_protocol_vault_yield_variance_drag_realization_analyzer — that converts the
    DISPERSION (second moment) of a SINGLE series into a geometric-vs-arithmetic
    compounding penalty. HERE it is an EXPLICIT TWO-STREAM net of a MISSED loss stream
    — a FIRST-moment subtraction that ZEROES OUT when the loss stream is empty even if
    the yield stream is volatile.
  * defi_protocol_vault_dollar_weighted_return_gap_analyzer — that prices the TIMING of
    cashflows (TWR vs DWR). HERE there is no flow timing — pure net-of-loss honesty of
    the income number.
  * defi_protocol_vault_price_return_contamination_analyzer — that SPLITS POSITIVE NAV
    growth into recurring-yield vs price-gain (both non-negative components). HERE we
    subtract a MISSED LOSS stream — a component of the OPPOSITE sign to the headline.
  * defi_protocol_real_yield_vs_incentive_yield_analyzer — that SPLITS a positive yield
    into real-fee vs incentive-token components (both POSITIVE). HERE it is the positive
    yield MINUS realised investment LOSSES.
  * defi_protocol_vault_performance_fee_volatility_tax_analyzer — that prices the
    asymmetric drag of a high-water-mark performance FEE. HERE it is realised investment
    LOSSES (IL / slashing / bad debt), not fees.

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
    "data", "vault_net_of_loss_yield_realization_log.json"
)
LOG_CAP = 100

# Minimum valid per-period yield samples required to use the sample path.
MIN_SAMPLES = 2

# Default annualisation factor (sub-periods per year).
DEFAULT_PERIODS_PER_YEAR = 365.0

# Classification thresholds on the scale-free loss_fraction in [0, 1]
# (= loss_drag_apr_pct / headline_yield_apr_pct).
CLEAN_FRACTION = 0.05        # at/below → clean yield (realised ≈ headline)
MILD_FRACTION = 0.20         # at/below → mild loss drag
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe loss drag

# Flag thresholds.
FREQUENT_LOSS_FRACTION = 0.5     # masked_epoch_fraction at/above → FREQUENT_LOSS_EPOCHS
SINGLE_LARGE_LOSS_FRACTION = 0.5  # worst_loss / loss_total at/above → SINGLE_LARGE_LOSS
FEW_SAMPLES_N = 4                # sample_count below this → FEW_SAMPLES

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
    Coerce a single sample to a finite float, or None if it is not interpretable
    (skipped). Accepts int/float/numeric-string; rejects bool, None, NaN, inf,
    and non-numeric values.
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


def _coerce_yield_samples(raw) -> List[float]:
    """
    Coerce a list of per-period POSITIVE YIELD contribution (% per period) samples to
    finite floats. The advertised yield stream is non-negative by construction; a
    stray negative income contribution is clamped to 0 (it is the headline POSITIVE
    stream, not a loss). Non-finite / non-numeric / bool entries are skipped. Order is
    preserved (newest LAST).
    """
    out: List[float] = []
    if not raw:
        return out
    for v in list(raw):
        cv = _coerce_num(v)
        if cv is None:
            continue
        out.append(cv if cv > 0.0 else 0.0)
    return out


def _coerce_loss_samples(raw) -> List[float]:
    """
    Coerce a list of per-period LOSS samples to finite NON-NEGATIVE magnitudes.
    Accepts both positive magnitudes (e.g. 2.0 = a 2% loss epoch) AND signed negative
    losses (e.g. -2.0) — either is coerced to a loss MAGNITUDE >= 0 (abs value). A
    zero entry is a no-loss epoch and is kept (it counts toward the epoch total but not
    a masked loss epoch). Non-finite / non-numeric / bool entries are skipped. Order is
    preserved.
    """
    out: List[float] = []
    if not raw:
        return out
    for v in list(raw):
        cv = _coerce_num(v)
        if cv is None:
            continue
        out.append(abs(cv))
    return out


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

class DeFiProtocolVaultNetOfLossYieldRealizationAnalyzer:
    """
    Nets a vault's advertised POSITIVE yield stream against a SEPARATE OMITTED stream
    of realised LOSS epochs (IL / slashing / bad-debt socialisation / negative trading
    epochs) to recover the depositor's downside-inclusive realised APR and the headline
    overstatement.

        headline_yield_apr_pct = mean(yield_samples) * ppy
        loss_drag_apr_pct      = mean(loss_magnitudes) * ppy   (0 if no losses)
        net_realized_apr_pct   = headline_yield_apr_pct - loss_drag_apr_pct
        overstatement_pct      = headline_yield_apr_pct - net_realized_apr_pct
        realization_ratio      = clamp(net_realized / headline, 0, 1)   (headline > 0)
        loss_fraction          = clamp(loss_drag / headline, 0, 1)   (scale-free basis)

    The headline folds in ONLY the positive income stream, so a recurring loss stream
    the brochure omits inflates the advertised APR above the downside-inclusive realised
    APR. With no losses the net coincides with the headline (CLEAN_YIELD). When the loss
    stream rivals the yield stream the realised APR collapses (SEVERE_LOSS_DRAG /
    net-negative).

    HIGHER score = realised ≈ headline (losses negligible — the LP keeps the brochure
    yield). LOWER score = a large omitted loss stream (realised far below the headline,
    or net-negative).

    Per-position input dict fields:
        vault / token        : str
        yield_samples        : list — per-period POSITIVE yield contributions (% per
                               period, e.g. 2.0 = +2%), the advertised stream, newest
                               LAST. Stray negatives are clamped to 0; non-finite /
                               non-numeric / bool entries are skipped. MIN_SAMPLES = 2.
        loss_samples         : list — per-period LOSS epochs. Positive magnitudes AND
                               signed negatives are both accepted and coerced to a loss
                               MAGNITUDE >= 0. May be empty (→ zero loss drag).
        net_return_samples   : list — OPTIONAL single signed stream; positive parts feed
                               the yield stream, negative parts feed the loss stream.
                               Only used when yield_samples is absent.
        periods_per_year     : float — annualisation factor (default 365).
        headline_yield_apr_pct : float — OPTIONAL direct override of the headline yield
                               APR. Override path REQUIRES a POSITIVE headline_yield_apr_pct
                               (else INSUFFICIENT_DATA).
        loss_drag_apr_pct    : float — OPTIONAL direct override of the annualised loss
                               drag (coerced to magnitude >= 0; defaults to 0).

    MIN_SAMPLES = 2 valid yield samples are required to use the sample path.
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

        ppy = _f(p.get("periods_per_year"), default=DEFAULT_PERIODS_PER_YEAR)
        if not math.isfinite(ppy) or ppy <= 0:
            ppy = DEFAULT_PERIODS_PER_YEAR

        yield_samples, loss_samples = self._resolve_streams(p)
        n = len(yield_samples)
        used_samples = n >= MIN_SAMPLES

        if used_samples:
            return self._analyze_samples(
                token, yield_samples, loss_samples, n, ppy)
        return self._analyze_override(token, p, n, ppy)

    def _resolve_streams(self, p: dict):
        """
        Resolve the (yield_stream, loss_stream) magnitude lists. Prefer explicit
        yield_samples / loss_samples. If yield_samples is absent but a single signed
        net_return_samples is supplied, split it: positive parts → yield stream,
        negative parts → loss magnitudes.
        """
        if p.get("yield_samples") is not None:
            yields = _coerce_yield_samples(p.get("yield_samples"))
            losses = _coerce_loss_samples(p.get("loss_samples"))
            return yields, losses

        net_raw = p.get("net_return_samples")
        if net_raw is not None:
            yields: List[float] = []
            losses: List[float] = []
            for v in list(net_raw):
                cv = _coerce_num(v)
                if cv is None:
                    continue
                if cv >= 0.0:
                    yields.append(cv)
                else:
                    losses.append(abs(cv))
            return yields, losses

        return [], _coerce_loss_samples(p.get("loss_samples"))

    # ── sample path ─────────────────────────────────────────────────────────────

    def _analyze_samples(
        self,
        token: str,
        yield_samples: List[float],
        loss_samples: List[float],
        n: int,
        ppy: float,
    ) -> dict:
        headline_yield_apr_pct = _mean(yield_samples) * ppy
        if not math.isfinite(headline_yield_apr_pct):
            return self._insufficient(token)

        if loss_samples:
            loss_drag_apr_pct = _mean(loss_samples) * ppy
        else:
            loss_drag_apr_pct = 0.0
        if not math.isfinite(loss_drag_apr_pct) or loss_drag_apr_pct < 0.0:
            loss_drag_apr_pct = 0.0

        # Loss-epoch geometry (sample path only).
        loss_epoch_count = sum(1 for x in loss_samples if x > 0.0)
        total_epochs = len(loss_samples)
        if total_epochs > 0:
            masked_epoch_fraction = loss_epoch_count / total_epochs
        else:
            masked_epoch_fraction = 0.0
        worst_loss_epoch_pct = max(loss_samples) if loss_samples else 0.0
        loss_total = sum(loss_samples)
        gross_yield_total = sum(yield_samples)

        return self._finish(
            token=token,
            headline_yield_apr_pct=headline_yield_apr_pct,
            loss_drag_apr_pct=loss_drag_apr_pct,
            masked_epoch_fraction=masked_epoch_fraction,
            worst_loss_epoch_pct=worst_loss_epoch_pct,
            loss_epoch_count=loss_epoch_count,
            gross_yield_total=gross_yield_total,
            loss_total=loss_total,
            ppy=ppy,
            n=n,
            used_samples=True,
            used_override=False,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(self, token: str, p: dict, n: int, ppy: float) -> dict:
        headline_o_raw = p.get("headline_yield_apr_pct")
        if headline_o_raw is None:
            return self._insufficient(token)
        headline_o = _coerce_num(headline_o_raw)
        if headline_o is None or not math.isfinite(headline_o) or headline_o <= 0.0:
            # No positive headline yield to net the loss stream against.
            return self._insufficient(token)

        loss_o = _coerce_num(p.get("loss_drag_apr_pct"))
        if loss_o is None or not math.isfinite(loss_o):
            loss_o = 0.0
        loss_o = abs(loss_o)

        return self._finish(
            token=token,
            headline_yield_apr_pct=headline_o,
            loss_drag_apr_pct=loss_o,
            masked_epoch_fraction=None,
            worst_loss_epoch_pct=None,
            loss_epoch_count=None,
            gross_yield_total=None,
            loss_total=None,
            ppy=ppy,
            n=n,
            used_samples=False,
            used_override=True,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        headline_yield_apr_pct: float,
        loss_drag_apr_pct: float,
        masked_epoch_fraction: Optional[float],
        worst_loss_epoch_pct: Optional[float],
        loss_epoch_count: Optional[int],
        gross_yield_total: Optional[float],
        loss_total: Optional[float],
        ppy: float,
        n: int,
        used_samples: bool,
        used_override: bool,
    ) -> dict:
        net_realized_apr_pct = headline_yield_apr_pct - loss_drag_apr_pct
        # overstatement = headline - net = loss_drag (computed as the difference for
        # override consistency).
        overstatement_pct = headline_yield_apr_pct - net_realized_apr_pct

        net_is_negative = net_realized_apr_pct <= 0.0

        # Scale-free realisation_ratio / loss_fraction against the headline yield.
        if headline_yield_apr_pct > EPS and math.isfinite(headline_yield_apr_pct):
            realization_ratio = _clamp(
                net_realized_apr_pct / headline_yield_apr_pct, 0.0, 1.0)
            loss_fraction = _clamp(
                loss_drag_apr_pct / headline_yield_apr_pct, 0.0, 1.0)
            insufficient_headline = False
        else:
            # Non-positive / non-finite headline: no positive yield stream to net
            # against → treated as insufficient.
            realization_ratio = None
            loss_fraction = None
            insufficient_headline = True

        if insufficient_headline:
            return self._insufficient(token)

        classification = self._classify(loss_fraction, net_is_negative)
        score = self._score(realization_ratio, loss_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            masked_epoch_fraction,
            worst_loss_epoch_pct,
            loss_total,
            loss_epoch_count,
            n,
            used_override,
        )

        return {
            "token": token,
            "headline_yield_apr_pct": round(headline_yield_apr_pct, 4),
            "loss_drag_apr_pct": round(loss_drag_apr_pct, 4),
            "net_realized_apr_pct": round(net_realized_apr_pct, 4),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "loss_fraction": round(loss_fraction, 4),
            "masked_epoch_fraction": (
                round(masked_epoch_fraction, 4)
                if masked_epoch_fraction is not None else None),
            "worst_loss_epoch_pct": (
                round(worst_loss_epoch_pct, 4)
                if worst_loss_epoch_pct is not None else None),
            "loss_epoch_count": loss_epoch_count,
            "gross_yield_total": (
                round(gross_yield_total, 4)
                if gross_yield_total is not None else None),
            "loss_total": (
                round(loss_total, 4) if loss_total is not None else None),
            "net_is_negative": net_is_negative,
            "periods_per_year": round(ppy, 4),
            "sample_count": n,
            "used_samples": used_samples,
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
        loss_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the net-of-loss realised APR is close to the headline yield
        (losses negligible → the LP keeps the brochure yield). Two components:
          * realisation = clamp(realization_ratio, 0, 1) — the fraction of the headline
            yield that survives the loss stream (1 → realised ≈ headline, 0 → realised
            ≤ 0),
          * loss penalty = clamp(1 − loss_fraction, 0, 1) — penalises a large omitted
            loss stream relative to the headline.
        Weighted 70/30 toward realisation (it directly maps to the net the LP keeps).
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        loss_penalty = _clamp(1.0 - loss_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * loss_penalty, 0.0, 100.0)

    def _classify(self, loss_fraction: float, net_is_negative: bool) -> str:
        if net_is_negative:
            # The loss stream has eaten the whole headline yield (or more) → worst case.
            return "SEVERE_LOSS_DRAG"
        if loss_fraction <= CLEAN_FRACTION:
            return "CLEAN_YIELD"
        if loss_fraction <= MILD_FRACTION:
            return "MILD_LOSS_DRAG"
        if loss_fraction <= MODERATE_FRACTION:
            return "MODERATE_LOSS_DRAG"
        return "SEVERE_LOSS_DRAG"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification == "CLEAN_YIELD":
            return "TRUST_HEADLINE"
        if classification == "MILD_LOSS_DRAG":
            return "DISCOUNT_HEADLINE_SLIGHTLY"
        if classification == "MODERATE_LOSS_DRAG":
            return "DISCOUNT_HEADLINE"
        # SEVERE_LOSS_DRAG
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        masked_epoch_fraction: Optional[float],
        worst_loss_epoch_pct: Optional[float],
        loss_total: Optional[float],
        loss_epoch_count: Optional[int],
        n: int,
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        # Classification flag.
        flags.append(classification)

        if net_is_negative:
            flags.append("NET_NEGATIVE_YIELD")

        if classification == "CLEAN_YIELD":
            flags.append("CLEAN_RECURRING")

        if used_override:
            flags.append("LOSS_FROM_OVERRIDE")
        else:
            # Sample-only flags are NOT meaningful on the override path.
            if (masked_epoch_fraction is not None
                    and masked_epoch_fraction >= FREQUENT_LOSS_FRACTION):
                flags.append("FREQUENT_LOSS_EPOCHS")
            if (loss_total is not None and worst_loss_epoch_pct is not None
                    and loss_epoch_count is not None and loss_epoch_count >= 1
                    and loss_total > 0.0
                    and (worst_loss_epoch_pct / loss_total)
                    >= SINGLE_LARGE_LOSS_FRACTION):
                flags.append("SINGLE_LARGE_LOSS")
            if n < FEW_SAMPLES_N:
                flags.append("FEW_SAMPLES")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_yield_apr_pct": None,
            "loss_drag_apr_pct": None,
            "net_realized_apr_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "loss_fraction": None,
            "masked_epoch_fraction": None,
            "worst_loss_epoch_pct": None,
            "loss_epoch_count": None,
            "gross_yield_total": None,
            "loss_total": None,
            "net_is_negative": False,
            "periods_per_year": None,
            "sample_count": 0,
            "used_samples": False,
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
                "cleanest_yield_vault": None,
                "worst_loss_drag_vault": None,
                "avg_score": 0.0,
                "net_negative_count": 0,
                "position_count": len(results),
            }
        # Higher score = realised ≈ headline → highest score is the cleanest yield.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_negative = sum(
            1 for r in results
            if "NET_NEGATIVE_YIELD" in r.get("flags", []))
        return {
            "cleanest_yield_vault": by_score[-1]["token"],
            "worst_loss_drag_vault": by_score[0]["token"],
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
            # CLEAN_YIELD: a positive yield stream with no loss epochs → net == headline.
            "vault": "USDC-Vault-CleanYield",
            "yield_samples": [2.0, 2.0, 2.0, 2.0, 2.0, 2.0],
            "loss_samples": [],
            "periods_per_year": 12.0,
        },
        {
            # MILD_LOSS_DRAG: a small recurring loss stream relative to the yield.
            "vault": "stETH-Vault-MildLoss",
            "yield_samples": [2.0, 2.0, 2.0, 2.0, 2.0, 2.0],
            "loss_samples": [0.0, 0.3, 0.0, 0.2, 0.0, 0.3],
            "periods_per_year": 12.0,
        },
        {
            # SEVERE_LOSS_DRAG: realised IL / bad-debt epochs near the yield magnitude
            # → net-of-loss realised APR collapses far below the headline.
            "vault": "GOV-Vault-SevereLoss",
            "yield_samples": [2.0, 2.0, 2.0, 2.0, 2.0, 2.0],
            "loss_samples": [1.8, 1.5, 1.9, 1.6, 1.7, 1.8],
            "periods_per_year": 12.0,
        },
        {
            # Override path: headline yield APR + annualised loss drag supplied directly.
            "vault": "LST-Vault-OverrideNet",
            "headline_yield_apr_pct": 24.0,
            "loss_drag_apr_pct": 9.0,
        },
        {
            # INSUFFICIENT_DATA: a single yield sample and no valid override headline.
            "vault": "MYSTERY-Vault-NoData",
            "yield_samples": [2.0],
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1204 Vault Net-of-Loss Yield Realization Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultNetOfLossYieldRealizationAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
