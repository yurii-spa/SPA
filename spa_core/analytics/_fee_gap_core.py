"""
Shared engine for the DeFiProtocolVaultPerformanceFeeGrossOf<KIND>BaseGap
analyzer family (MP-12xx).

One vault-performance-fee "gross-of-<eroding-layer>" base-gap formula was
previously duplicated across 35 sibling modules (~800 lines each) that were
byte-identical modulo the noun of the eroding layer (bridge fee, borrow cost,
swap fee, ...). This module holds the engine ONCE; each sibling is now a thin
wrapper that supplies its vocabulary (result-dict key names, classification /
recommendation / flag labels, HIGH-rate threshold, ring-buffer log path) via
``build_module_api`` and re-exports the family-standard public names.

The engine is a faithful transcription of the reference implementation
(defi_protocol_vault_performance_fee_gross_of_bridge_fee_base_gap_analyzer);
behavior, rounding, sentinels, dict shapes and the atomic ring-buffer log
semantics are bit-identical. The pre-refactor equivalence of all 35 clones was
verified by normalized-AST comparison, and the per-module unit tests remain
unmodified as the behavioral proof.

Formula (per position; <k> = the module's eroding-layer noun):

    fee_frac                 = clamp(performance_fee_pct / 100, 0, 1)
    <k>_consumed_yield_pct   = max(0, gross_yield - net_of_<k>_yield)
    fee_charged_pct          = fee_frac * max(0, gross_yield)
    fair_fee_pct             = fee_frac * max(0, net_of_<k>_yield)
    fee_on_<k>_gap_pct       = max(0, fee_charged - fair_fee)
    net_return_after_fee_pct = net_of_<k>_yield - fee_charged
    net_return_fair_pct      = net_of_<k>_yield - fair_fee
    overstatement_pct        = fee_on_<k>_gap_pct
    fee_on_<k>_fraction      = clamp(gap / fee_charged, 0, 1)
    realization_ratio        = clamp(net_after_fee / net_fair, 0, 1)

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no
inf/NaN). LLM-free by construction (invariant #3).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import List, Optional

from spa_core.utils.live_paths import sandboxed_default

# ── family-wide constants ─────────────────────────────────────────────────────
LOG_CAP = 100

# Classification thresholds on the scale-free fee-on-<kind> fraction
# in [0, 1] (= fee_on_<kind>_gap_pct / fee_charged_pct).
CLEAN_FRACTION = 0.05        # at/below → cleanly on the net-of-<kind> base
MILD_FRACTION = 0.20         # at/below → mild fee-on-<kind> gap
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe gap

# Small epsilon to keep normalisers finite.
EPS = 1e-12


# ── helpers (family-standard; re-exported verbatim by every wrapper) ──────────

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
    net-of-<kind>-yield field, which may legitimately be negative.
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


# ── protocol-context branch (audit 2026-08-05, задача A2) ────────────────────
#
# Дифференциальный аудит: все 36 wrapper-модулей семейства (плюс 15 клонов в
# gross_of/) принимали контекст агрегатора {"protocol": ...} как position-dict,
# не находили в нём ни одного доменного ключа и возвращали КОНСТАНТУ
# INSUFFICIENT_DATA (score 0.0) для любого протокола → blind_constant.
# Ветка ниже строит position-вход честно:
#   * gross yield — РЕАЛЬНАЯ последняя точка ряда _apy_series (fallback —
#     структурный apy_pct профиля);
#   * performance_fee_pct — структурный факт (vault=10%, остальные 0);
#   * эрозия <kind> — ТОЛЬКО из реальных полей профиля (см. _erosion_pct);
#     нет perf fee → gap тривиально 0 при любой эрозии (арифметика движка);
#     fee > 0 и эрозия не измерена → None (громкий dormant, не фабрикация).
# Полярность: движок отдаёт score «выше = честнее» → risk = 100 - score.
# На контекст-пути НЕТ записей файлов (write_log не достигается).

_CTX_COMMON_KEYS = ("performance_fee_pct", "fee_charged_pct", "vault", "token")


def _erosion_pct(k_net: str, prof: dict) -> Optional[float]:
    """Эрозия <kind> в процентных пунктах доходности из РЕАЛЬНЫХ полей
    структурного профиля, или None (эрозия этого kind не измерена)."""
    k = k_net
    if "management_fee" in k:
        return float(prof["management_fee_pct"])
    if "withdrawal_fee" in k or "early_withdrawal_penalty" in k:
        return float(prof["withdrawal_fee_pct"])
    if "deposit_fee" in k:
        # whitelisted-universe: депозит-фи нет ни у одного протокола базы
        return 0.0
    if "exit_slippage" in k:
        return float(prof["exit_slippage_pct"])
    if "swap_fee" in k or "lp_amm_fee" in k:
        return float(prof["fee_pct"])
    if "bridge" in k:
        pos_usd = float(prof["position_usd"])
        if pos_usd <= 0:
            return None
        return float(prof["bridge_cost_usd"]) / pos_usd * 100.0
    if "net_of_il" in k or "impermanent" in k:
        return float(prof["il_change_pct"])
    if "borrow_cost" in k or "funding_cost" in k:
        # нет долга → нет стоимости заимствования (реальный факт cascade);
        # долг есть, а ставка не измерена → None
        return 0.0 if float(prof["debt_usd"]) <= 0.0 else None
    if "bad_debt" in k:
        tvl = float(prof["tvl_usd"])
        if tvl <= 0:
            return None
        return float(prof["bad_debt_usd"]) / tvl * 100.0
    if "reserve" in k:
        # vault-обёртки базы не скимят в резервный фактор
        return 0.0 if prof.get("kind") == "vault" else None
    if "basis_risk" in k:
        return float(prof["basis_spread_pp"])
    return None


def build_context_position(protocol, k_gross: str, k_net: str,
                           data_dir=None) -> Optional[dict]:
    """Собрать position-вход движка из протокол-контекста, или None."""
    from spa_core.analytics import _protocol_facts as _pf
    from spa_core.analytics import _apy_series as _apy
    prof = _pf.generic_profile_for(protocol)
    if prof is None:
        return None
    gross = None
    try:
        pt = _apy.latest(protocol, data_dir=data_dir)
        if pt is not None and float(pt[1]) > 0.0:
            gross = float(pt[1])
    except Exception:
        gross = None
    if gross is None:
        gross = float(prof["apy_pct"])
    fee_pct = float(prof.get("performance_fee_pct") or 0.0)
    pos = {"vault": prof["name"], k_gross: gross,
           "performance_fee_pct": fee_pct}
    if fee_pct > 0.0:
        erosion = _erosion_pct(k_net, prof)
        if erosion is None:
            return None
        pos[k_net] = gross - erosion
    else:
        # fee=0 → fee_charged=0 → gap=0 → score от базы НЕ зависит
        # (арифметика _finish); значение ниже — нейтральный плейсхолдер.
        pos[k_net] = gross
    return pos


def maybe_context_result(analyze_one, position, k_gross: str, k_net: str,
                         extra_keys=()):
    """(True, result) если *position* — контекст агрегатора, иначе (False, None).

    result — {"risk_score": 0-100 (выше=опаснее), ...} либо None (dormant).
    """
    from spa_core.analytics import _protocol_facts as _pf
    domain = (k_gross, k_net) + tuple(extra_keys) + _CTX_COMMON_KEYS
    if not _pf.is_context_only(position, domain):
        return False, None
    pos = build_context_position(position["protocol"], k_gross, k_net,
                                 data_dir=position.get("data_dir"))
    if pos is None:
        return True, None
    res = analyze_one(pos)
    if not isinstance(res, dict):
        return True, None
    if res.get("classification") == "INSUFFICIENT_DATA":
        return True, None
    score = res.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return True, None
    return True, {
        "protocol": pos["vault"],
        "risk_score": round(max(0.0, min(100.0, 100.0 - float(score))), 2),
        "engine_score_higher_better": round(float(score), 2),
        "classification": res.get("classification"),
        "facts_source": _pf.FACTS_SOURCE,
        "facts_as_of": _pf.FACTS_AS_OF,
    }


# ── parameterized engine ──────────────────────────────────────────────────────

class _FeeGapAnalyzerBase:
    """
    The shared gross-of-<kind> performance-fee base-gap engine.

    Subclasses (created by ``build_module_api``) carry the per-module
    vocabulary in ``_SPEC``:

        log_path        : str   — ring-buffer log file for this module
        high_threshold  : float — informational-rate threshold for the
                                  HIGH_<KIND> flag
        k_gross         : result/input key for the gross yield
        k_net           : result/input key for the net-of-<kind> yield
        k_consumed      : result key for the <kind>-consumed slice
        k_gap           : result/input key for the fee-on-<kind> gap
        k_fraction      : result key for the scale-free fee-on-<kind> fraction
        k_rate          : result/input key for the informational <kind> rate
        c_clean / c_mild / c_moderate / c_severe : classification labels
        r_trust / r_minor / r_demand / r_avoid   : recommendation labels
        f_high / f_fee_on / f_full_fee_on        : per-kind flag labels
        agg_worst       : aggregate key for the worst-gap vault
    """

    _SPEC: dict = {}

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        position: dict,
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        # Контекст агрегатора → честный position-вход из структурного
        # профиля + реального APY-ряда (см. maybe_context_result выше);
        # на контекст-пути записей файлов нет.
        s = self._SPEC
        is_ctx, ctx_res = maybe_context_result(
            self._analyze_one, position, s["k_gross"], s["k_net"],
            (s["k_gap"], s["k_rate"]))
        if is_ctx:
            return ctx_res
        cfg = self._build_default_cfg(cfg)
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
        cfg = self._build_default_cfg(cfg)
        results = [self._analyze_one(p) for p in positions]
        agg = self._aggregate(results)
        if write_log:
            self._write_log(results, agg, cfg)
        return {"positions": results, "aggregate": agg}

    @classmethod
    def _build_default_cfg(cls, overrides: Optional[dict] = None) -> dict:
        cfg = {"log_path": cls._SPEC["log_path"], "log_cap": LOG_CAP}
        if overrides:
            cfg.update(overrides)
        return cfg

    # ── per-position ──────────────────────────────────────────────────────────

    def _analyze_one(self, p: dict) -> dict:
        s = self._SPEC
        token = p.get("vault", p.get("token", "UNKNOWN"))

        # The gross yield is required and must be finite & positive.
        gross_gain = _coerce_num(p.get(s["k_gross"]))
        if gross_gain is None or not math.isfinite(gross_gain) or gross_gain <= 0.0:
            return self._insufficient(token)

        kind_rate = _coerce_num(p.get(s["k_rate"]))

        # Override path: a direct fee-on-<kind> gap + a positive fee_charged.
        gap_o = _coerce_num(p.get(s["k_gap"]))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross_gain, abs(gap_o), fee_charged_o, kind_rate)

        # Main path: the performance fee rate is required and must be finite.
        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(token, p, gross_gain, fee_pct, kind_rate)

    # ── main path ─────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross_gain: float, fee_pct: float,
        kind_rate: Optional[float],
    ) -> dict:
        s = self._SPEC
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        # net-of-<kind> yield may legitimately be negative (the <kind>
        # exceeds the gross yield, or the strategy lost).
        net_gain = _coerce_signed(p.get(s["k_net"]))
        if net_gain is None or not math.isfinite(net_gain):
            net_gain = 0.0

        consumed_yield_pct = max(0.0, gross_gain - net_gain)
        fee_charged_pct = fee_frac * max(0.0, gross_gain)
        fair_fee_pct = fee_frac * max(0.0, net_gain)
        gap_pct = max(0.0, fee_charged_pct - fair_fee_pct)

        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=fee_frac,
            net_yield_pct=net_gain,
            consumed_yield_pct=consumed_yield_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            gap_pct=gap_pct,
            kind_rate_pct=kind_rate,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_gain: float, gap: float, fee_charged: float,
        kind_rate: Optional[float],
    ) -> dict:
        # The gap can not exceed the fee charged (it is a SHARE of it).
        gap = min(gap, fee_charged)
        # net-of-<kind> / <kind>-slice / fair geometry is unknown on the
        # override path → report None; net return can not be derived without
        # the net-of-<kind> yield, so net-negative / full-fee-on-<kind>
        # flags / ratio fall back to the gap share.
        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=None,
            net_yield_pct=None,
            consumed_yield_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            gap_pct=gap,
            kind_rate_pct=kind_rate,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ───────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_yield_pct: float,
        fee_frac: Optional[float],
        net_yield_pct: Optional[float],
        consumed_yield_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        gap_pct: float,
        kind_rate_pct: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        s = self._SPEC
        # overstatement = the performance fee charged on the <kind> slice
        # (kept for family consistency with the headline-honesty family).
        overstatement_pct = gap_pct

        # Net return: only computable when net-of-<kind> geometry is known.
        if net_yield_pct is not None:
            net_return_after_fee_pct = net_yield_pct - fee_charged_pct
            net_return_fair_pct = net_yield_pct - fair_fee_pct
            net_is_negative = net_return_fair_pct < 0.0
            if net_return_fair_pct > EPS:
                realization_ratio = _clamp(
                    net_return_after_fee_pct / net_return_fair_pct, 0.0, 1.0)
            else:
                # Mirror the hurdle/clawback template edge: when the fair net is
                # non-positive, the ratio is 1.0 only if the charged net still
                # clears the fair net and is itself non-negative, else 0.0.
                realization_ratio = (
                    1.0 if (net_return_after_fee_pct >= net_return_fair_pct
                            and net_return_after_fee_pct >= 0.0) else 0.0)
        else:
            # Override path: net-of-<kind> geometry unknown. Treat realisation
            # via the fee-on-<kind> share as the proxy below; flag as not known.
            net_return_after_fee_pct = None
            net_return_fair_pct = None
            net_is_negative = False
            realization_ratio = None

        # Scale-free fee-on-<kind> fraction — the share of the charged
        # performance fee that landed on the <kind> slice.
        if fee_charged_pct > EPS:
            fraction = _clamp(gap_pct / fee_charged_pct, 0.0, 1.0)
        else:
            fraction = 0.0

        # On the override path, with no net-of-<kind> geometry, anchor the
        # realisation on (1 - fraction): the share of the fee that fell on the
        # net-of-<kind> yield is the share the depositor "paid fairly".
        if realization_ratio is None:
            realization_ratio = _clamp(1.0 - fraction, 0.0, 1.0)

        classification = self._classify(fraction, net_is_negative)
        score = self._score(realization_ratio, fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            net_yield_pct,
            consumed_yield_pct,
            gross_yield_pct,
            kind_rate_pct,
            used_override,
        )

        return {
            "token": token,
            s["k_gross"]: round(gross_yield_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            s["k_net"]: (
                round(net_yield_pct, 4)
                if net_yield_pct is not None else None),
            s["k_consumed"]: (
                round(consumed_yield_pct, 4)
                if consumed_yield_pct is not None else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            s["k_gap"]: round(gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            s["k_fraction"]: round(fraction, 4),
            "net_is_negative": net_is_negative,
            s["k_rate"]: (
                round(kind_rate_pct, 4)
                if kind_rate_pct is not None else None),
            "sample_count": 0,
            "used_override": used_override,
            "used_main": used_main,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags_out,
        }

    # ── scoring ───────────────────────────────────────────────────────────────

    def _score(
        self,
        realization_ratio: float,
        fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the performance fee was charged on the net-of-<kind>
        yield the depositor actually realized. Two components:
          * realisation = clamp(realization_ratio, 0, 1) — the fraction of the
            fair net return that survives the gross-based fee,
          * fee-base penalty = clamp(1 − fraction, 0, 1) — penalises a large
            share of the fee being charged on the <kind> slice.
        Weighted 70/30 toward realisation (it directly maps to the net return
        the depositor keeps).
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(self, fraction: float, net_is_negative: bool) -> str:
        s = self._SPEC
        if net_is_negative:
            # The fee has eaten the whole net-of-<kind> yield (or more).
            return s["c_severe"]
        if fraction <= CLEAN_FRACTION:
            return s["c_clean"]
        if fraction <= MILD_FRACTION:
            return s["c_mild"]
        if fraction <= MODERATE_FRACTION:
            return s["c_moderate"]
        return s["c_severe"]

    def _recommend(self, classification: str) -> str:
        s = self._SPEC
        if classification == "INSUFFICIENT_DATA":
            return s["r_avoid"]
        if classification == s["c_clean"]:
            return s["r_trust"]
        if classification == s["c_mild"]:
            return s["r_minor"]
        if classification == s["c_moderate"]:
            return s["r_demand"]
        # severe
        return s["r_avoid"]

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        net_yield_pct: Optional[float],
        consumed_yield_pct: Optional[float],
        gross_yield_pct: float,
        kind_rate_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        s = self._SPEC
        flags: List[str] = []

        # Classification flag.
        flags.append(classification)

        if classification == s["c_clean"]:
            flags.append("CLEAN_NET_BASE")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if (kind_rate_pct is not None
                and kind_rate_pct >= s["high_threshold"]):
            flags.append(s["f_high"])

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if (consumed_yield_pct is not None
                    and consumed_yield_pct > 0.0):
                flags.append(s["f_fee_on"])
            if (net_yield_pct is not None
                    and net_yield_pct <= 0.0
                    and gross_yield_pct > 0.0):
                flags.append(s["f_full_fee_on"])

        return flags

    def _insufficient(self, token: str) -> dict:
        s = self._SPEC
        return {
            "token": token,
            s["k_gross"]: None,
            "performance_fee_pct": None,
            s["k_net"]: None,
            s["k_consumed"]: None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            s["k_gap"]: None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            s["k_fraction"]: None,
            "net_is_negative": False,
            s["k_rate"]: None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": s["r_avoid"],
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ─────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        s = self._SPEC
        scored = [
            r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "cleanest_vault": None,
                s["agg_worst"]: None,
                "avg_score": 0.0,
                "net_negative_count": 0,
                "position_count": len(results),
            }
        # Higher score = charged on the net-of-<kind> base / fee fair
        # → highest score is the cleanest vault.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_negative = sum(
            1 for r in results
            if "NET_NEGATIVE_AFTER_FEE" in r.get("flags", []))
        return {
            "cleanest_vault": by_score[-1]["token"],
            s["agg_worst"]: by_score[0]["token"],
            "avg_score": round(avg, 2),
            "net_negative_count": net_negative,
            "position_count": len(results),
        }

    # ── ring-buffer log ───────────────────────────────────────────────────────

    def _write_log(self, results: List[dict], agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        # Умолчание модуля (git-tracked ``data/<...>_log.json``) уводится в
        # песочницу под тестами; путь, названный вызывающим, проходит насквозь.
        # Один этот писатель обслуживает всё семейство ``*_gross_of_*`` — 24
        # модуля объявляют только свой ``LOG_PATH`` и делят этот код.
        log_path = sandboxed_default(log_path, self._SPEC["log_path"])
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


# ── factory ───────────────────────────────────────────────────────────────────

def build_module_api(
    class_name: str,
    log_path: str,
    high_threshold: float,
    keys: dict,
    labels: dict,
) -> dict:
    """
    Build the per-module API for one gross-of-<kind> wrapper module.

    keys   : {"gross", "net", "consumed", "gap", "fraction", "rate"} — the
             module's result/input dict key names.
    labels : {"clean", "mild", "moderate", "severe",           (classification)
              "trust", "minor", "demand", "avoid",             (recommendation)
              "high_flag", "fee_on_flag", "full_fee_on_flag",  (flags)
              "agg_worst"}                                     (aggregate key)

    Returns {"analyzer_cls": <class named class_name>,
             "_build_default_cfg": <function>}.
    """
    spec = {
        "log_path": log_path,
        "high_threshold": high_threshold,
        "k_gross": keys["gross"],
        "k_net": keys["net"],
        "k_consumed": keys["consumed"],
        "k_gap": keys["gap"],
        "k_fraction": keys["fraction"],
        "k_rate": keys["rate"],
        "c_clean": labels["clean"],
        "c_mild": labels["mild"],
        "c_moderate": labels["moderate"],
        "c_severe": labels["severe"],
        "r_trust": labels["trust"],
        "r_minor": labels["minor"],
        "r_demand": labels["demand"],
        "r_avoid": labels["avoid"],
        "f_high": labels["high_flag"],
        "f_fee_on": labels["fee_on_flag"],
        "f_full_fee_on": labels["full_fee_on_flag"],
        "agg_worst": labels["agg_worst"],
    }
    analyzer_cls = type(class_name, (_FeeGapAnalyzerBase,), {"_SPEC": spec})
    analyzer_cls.__qualname__ = class_name

    def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
        cfg = {"log_path": log_path, "log_cap": LOG_CAP}
        if overrides:
            cfg.update(overrides)
        return cfg

    return {
        "analyzer_cls": analyzer_cls,
        "_build_default_cfg": _build_default_cfg,
    }
