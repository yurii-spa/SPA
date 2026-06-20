#!/usr/bin/env python3
"""Portfolio Risk Contribution & Risk-Budget Analyzer (SPA-V437 / MP-118) — read-only / advisory.

Complements the *capital-weight* concentration analyzer (MP-116, position-weight
HHI) and the *yield* attribution analyzer (MP-117, yield-source HHI) by
answering the distinct investor-DD question: **"where does the portfolio's
RISK actually come from?"**. A book can be weight-diversified and yield-
diversified yet have its *risk* (return variance) dominated by a single volatile
/ highly-correlated protocol. MP-116/MP-117 decompose CAPITAL and YIELD; this
module decomposes VARIANCE by combining the existing covariance matrix with the
current position weights — a strictly different lens.

Risk here = the variance / volatility of the portfolio's APY, using the
APY-volatility covariance matrix produced upstream
(``data/covariance_summary.json``). This is an **APY-volatility proxy** for
risk, not price/PnL risk — documented honestly (units: ``pp`` of APY).

Single source of position weights (reuse-by-import)
==================================================
Position weights are NOT recomputed here. We import :func:`build_exposure` from
:mod:`spa_core.reporting.tear_sheet` (MP-501 — single source of truth for the
weight / cash math) and consume its ``by_protocol[p]["share_pct"]`` (a PERCENT,
0..100, of the FULL AUM incl. cash). Cash (``__cash__``) carries zero variance
and zero covariance, so it contributes exactly 0 risk; the deployed weights are
renormalised over the *covered* sub-portfolio (see below). Zero duplicated
weight arithmetic.

Covariance source & key mapping (nothing invented)
=================================================
The covariance matrix Σ comes from ``covariance_summary.json``'s
``covariance_matrix`` (dict-of-dicts keyed by full instrument slugs like
``aave-v3-usdc-ethereum``), with per-instrument standalone volatility taken as
``sqrt(Σ_ii)`` (cross-checked against the file's ``volatility_pp`` for parity).
:func:`build_exposure` yields *normalised protocol* keys (``aave_v3``) while Σ
keys are full instrument slugs; we map each exposure protocol to its covariance
row by normalising both sides with the SAME convention used in
``whitelabel_api.normalize_protocol`` (``"Aave V3"``/``"aave-v3"`` → ``aave_v3``)
and matching the protocol prefix. When a protocol matches MULTIPLE instrument
rows (e.g. ``aave_v3`` → both ``aave-v3-usdc-ethereum`` and
``aave-v3-usdt-ethereum``) we deterministically prefer the ``usdc-ethereum``
instrument, else the first slug in sorted order, and record the chosen slug +
an ``ambiguous`` note — never an invented blend. A protocol weight with NO
covariance row is marked ``known: false``, EXCLUDED from the decomposition, its
weight added to an ``uncovered_risk_weight`` bucket + a note (variance is never
fabricated).

Risk decomposition math (over the COVERED sub-portfolio)
=======================================================
Let ``w`` be the covered protocol weights renormalised to sum to 1 over the
covered protocols (``covered_weight_share`` = covered fraction of deployed
weight, reported honestly), and Σ the covered covariance sub-matrix::

    portfolio_variance       = wᵀ Σ w
    portfolio_volatility_pp  = sqrt(variance)                 # units: pp of APY
    MCTR_i  (marginal)       = (Σ w)_i / sigma_p
    CCTR_i  (component)      = w_i * MCTR_i                    # Σ_i CCTR_i = sigma_p
    PRC_i   (percent risk)   = CCTR_i / sigma_p               # Σ_i PRC_i  = 1

``risk_hhi`` = ``sum(PRC_i²)`` (fraction in ``[0,1]`` + 0–10000 index);
``effective_num_risk_sources = 1/hhi_frac``. ``diversification_ratio`` =
``(Σ_i w_i·sigma_i) / sigma_p`` (weighted-average standalone vol ÷ portfolio
vol; ``≥ 1``; higher = more diversification benefit) using
``sigma_i = sqrt(Σ_ii)``. ``risk_vs_capital`` per protocol =
``risk_weight_ratio = PRC_i / capital_weight_i`` (``> 1`` ⇒ over-contributes
risk relative to its capital share); the biggest over-risk position is flagged.

Concentration class (reused thresholds)
=======================================
The DOJ/FTC index thresholds are the SAME as the capital concentration analyzer
(reused by import: :data:`HHI_MODERATE_FLOOR` 1500 /
:data:`HHI_CONCENTRATED_FLOOR` 2500): ``< 1500`` diversified, ``1500..2500``
moderate, ``> 2500`` concentrated.

Verdict (advisory only — never blocks anything)
==============================================
* ``fail`` — a single position contributes ``> 60%`` of portfolio risk (PRC),
  OR the risk is in the *concentrated* class;
* ``warn`` — *moderate* risk class, OR an uncovered-risk weight ``> 25%`` (too
  much of the book has no covariance row to assess);
* ``ok`` — otherwise.

Output / persistence
====================
:func:`build_risk_contribution` returns a stable-schema dict and NEVER raises.
:func:`write_status` atomically (tmp + ``os.replace``) writes
``data/risk_contribution.json`` with an in-file ``history`` of runs (rotation
≤ :data:`HISTORY_MAX`). Idempotency: a :func:`content_fingerprint` over the
whole doc EXCLUDING the volatile ``meta.generated_at`` / ``history`` means a
repeated ``--run`` on unchanged inputs is byte-identical and does not grow
history (``generated_at`` only changes when content changes).

CLI (offline, exit 0 always, no tracebacks; junk args → clear ERROR on stderr)::

    python3 -m spa_core.paper_trading.risk_contribution --check   # compute+print, no write (default)
    python3 -m spa_core.paper_trading.risk_contribution --run     # + atomic write
    python3 -m spa_core.paper_trading.risk_contribution --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/datetime/argparse/tempfile/logging/pathlib/re/typing) — no
requests/web3/LLM SDK/sockets/network. It only READS
``current_positions.json``, ``adapter_orchestrator_status.json`` and
``covariance_summary.json`` and writes its OWN status artifact; it never moves
capital and never touches risk/execution/allocator/cycle_runner.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# REUSE BY IMPORT — single source of truth for the position weight / cash math
# (MP-501). We do NOT recompute weights from raw positions here; we consume
# build_exposure's share_pct (percent of full AUM) directly.
from spa_core.reporting.tear_sheet import build_exposure

# REUSE BY IMPORT — same DOJ/FTC index thresholds as the capital concentration
# analyzer (MP-116), so the risk-concentration class is consistent with the
# weight-concentration / yield-concentration classes. (Imported, not redefined.)
from spa_core.paper_trading.concentration_analytics import (
    HHI_CONCENTRATED_FLOOR,
    HHI_MODERATE_FLOOR,
)
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.risk_contribution")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION = 1
SOURCE_NAME = "risk_contribution"
STATUS_FILENAME = "risk_contribution.json"
POSITIONS_FILENAME = "current_positions.json"
ORCHESTRATOR_FILENAME = "adapter_orchestrator_status.json"
COVARIANCE_FILENAME = "covariance_summary.json"
HISTORY_MAX = 500  # run-history rotation (pattern: concentration_analytics / tear_sheet)

# A single position contributing strictly more than this FRACTION of portfolio
# risk (PRC) is a "fail" (one bet drives the whole book's variance). 0.60 is OK.
MAX_SINGLE_RISK_SHARE = 0.60

# A book with strictly more than this FRACTION of its weight in protocols whose
# covariance row is unknown earns a "warn" — too much risk is unassessable.
UNCOVERED_RISK_WARN_SHARE = 0.25

# Deterministic instrument preference when a protocol maps to several Σ rows.
_PREFERRED_INSTRUMENT_SUFFIX = "usdc_ethereum"

DISCLAIMER = "NOT investment advice"

SOURCE_FILES = [POSITIONS_FILENAME, ORCHESTRATOR_FILENAME, COVARIANCE_FILENAME]

# Same normalization convention as whitelabel_api.normalize_protocol
# ("Aave V3"/"aave-v3" -> "aave_v3"). Reproduced (not imported) to keep this
# advisory module's dependency surface minimal & purely paper_trading/reporting.
_PROTO_NORM_RE = re.compile(r"[^a-z0-9]+")


# ─── Tolerant IO helpers (pattern: yield_attribution / concentration_analytics) ─


def _read_json(path: Path) -> Any:
    """Read JSON tolerantly: missing/broken file → None, never raises."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _num(value: Any) -> Optional[float]:
    """Finite float or None (bool is not a number; NaN/inf are not data)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return float(value)


def normalize_protocol(name: Any) -> str:
    """Canonical protocol/instrument key: "Aave V3"/"aave-v3" → "aave_v3".

    SAME convention as ``whitelabel_api.normalize_protocol`` (kept local to keep
    this advisory module's import surface minimal).
    """
    return _PROTO_NORM_RE.sub("_", str(name).strip().lower()).strip("_")


def _classify_risk(risk_hhi_index: Optional[int]) -> Optional[str]:
    """DOJ/FTC concentration class from the risk-PRC HHI index, or None.

    Uses the SAME thresholds as the capital concentration analyzer (reused by
    import): ``< 1500`` diversified, ``1500..2500`` moderate, ``> 2500``
    concentrated.
    """
    if risk_hhi_index is None:
        return None
    if risk_hhi_index < HHI_MODERATE_FLOOR:
        return "diversified"
    if risk_hhi_index <= HHI_CONCENTRATED_FLOOR:
        return "moderate"
    return "concentrated"


def _build_cov_index(cov_doc: Any) -> Tuple[Dict[str, str], Dict[str, Dict[str, float]]]:
    """Parse covariance_summary.json into (normalized_slug→raw_slug, raw Σ).

    Returns:
      * ``slug_index``: normalized instrument key → original raw slug (so we can
        look the protocol prefix up); and
      * ``cov``: the raw covariance matrix (dict-of-dicts) filtered to numeric
        entries only.
    Broken/missing input → ({}, {}). Nothing invented.
    """
    slug_index: Dict[str, str] = {}
    cov: Dict[str, Dict[str, float]] = {}
    if not isinstance(cov_doc, dict):
        return slug_index, cov
    matrix = cov_doc.get("covariance_matrix")
    if not isinstance(matrix, dict):
        return slug_index, cov
    for row_slug, row in matrix.items():
        if not isinstance(row, dict):
            continue
        clean_row: Dict[str, float] = {}
        for col_slug, val in row.items():
            num = _num(val)
            if num is not None:
                clean_row[str(col_slug)] = num
        if clean_row:
            cov[str(row_slug)] = clean_row
            slug_index.setdefault(normalize_protocol(row_slug), str(row_slug))
    # index every column slug too (defensive: a column may name a slug that
    # never appears as a row key in malformed inputs).
    for row in cov.values():
        for col_slug in row:
            slug_index.setdefault(normalize_protocol(col_slug), str(col_slug))
    return slug_index, cov


def _match_instrument(proto: str, slug_index: Dict[str, str]) -> Tuple[Optional[str], bool]:
    """Map a normalized protocol key to a single covariance instrument slug.

    Returns ``(raw_slug, ambiguous)``. Matching candidates are instruments
    whose normalized slug == ``proto`` or starts with ``proto + "_"`` (protocol
    prefix). When several candidates match we deterministically prefer the
    ``usdc_ethereum`` instrument, else the first in sorted order, and flag
    ``ambiguous=True``. No match → ``(None, False)``.
    """
    candidates = []
    for norm_slug, raw_slug in slug_index.items():
        if norm_slug == proto or norm_slug.startswith(proto + "_"):
            candidates.append((norm_slug, raw_slug))
    if not candidates:
        return None, False
    if len(candidates) == 1:
        return candidates[0][1], False
    # Deterministic disambiguation: prefer usdc_ethereum, else sorted-first.
    candidates.sort(key=lambda c: c[0])
    for norm_slug, raw_slug in candidates:
        if norm_slug.endswith(_PREFERRED_INSTRUMENT_SUFFIX):
            return raw_slug, True
    return candidates[0][1], True


# ─── Pure computation ─────────────────────────────────────────────────────────


def _empty_result(
    notes: List[str],
    *,
    is_demo: Optional[bool] = None,
    available: bool = False,
    window_days: Optional[int] = None,
    cov_source: Optional[str] = None,
) -> Dict[str, Any]:
    """A stable-schema, honest-empty risk-contribution result."""
    return {
        "available": available,
        "advisory_only": True,
        "execution_mode": "read_only",
        "is_demo": is_demo,
        "verdict": "warn",
        "portfolio_variance": 0.0,
        "portfolio_volatility_pp": 0.0,
        "risk_hhi": 0.0,
        "risk_hhi_index": 0,
        "effective_num_risk_sources": None,
        "top1_risk_protocol": None,
        "top1_risk_share": 0.0,
        "top3_risk_share": 0.0,
        "risk_concentration_class": None,
        "diversification_ratio": None,
        "covered_weight_share": 0.0,
        "uncovered_risk_weight": 0.0,
        "max_over_risk_protocol": None,
        "max_risk_weight_ratio": None,
        "num_risk_sources": 0,
        "num_covered": 0,
        "num_uncovered": 0,
        "max_single_risk_share": MAX_SINGLE_RISK_SHARE,
        "uncovered_risk_warn_share": UNCOVERED_RISK_WARN_SHARE,
        "counts": {"sources": 0, "covered": 0, "uncovered": 0},
        "breakdown": [],
        "window_days": window_days,
        "covariance_source": cov_source,
        "source_files": list(SOURCE_FILES),
        "disclaimer": DISCLAIMER,
        "notes": notes,
        "risk_units": "pp_apy_volatility",
    }


def build_risk_contribution(
    data_dir: Optional[str | os.PathLike] = None,
) -> Dict[str, Any]:
    """Build the portfolio risk-contribution dict. NEVER raises.

    Reads ``current_positions.json``, ``adapter_orchestrator_status.json`` and
    ``covariance_summary.json`` from *data_dir* (all tolerant/optional). Calls
    :func:`build_exposure` (single source of weight / cash math) for the per-
    protocol weights, maps each protocol to its covariance instrument row,
    renormalises the covered weights, and derives ``wᵀΣw``, the portfolio
    volatility, marginal/component/percent risk contributions, the risk-PRC
    HHI, the effective number of risk sources, top1/top3 risk shares, the
    diversification ratio, the per-protocol risk-vs-capital ratio, and an
    uncovered-risk bucket. Missing/broken input or an unavailable exposure /
    covariance → honest ``available: false`` empty result + note. Nothing is
    invented.
    """
    try:
        ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        positions_doc = _read_json(ddir / POSITIONS_FILENAME)
        orch_doc = _read_json(ddir / ORCHESTRATOR_FILENAME)
        cov_doc = _read_json(ddir / COVARIANCE_FILENAME)
        notes: List[str] = []

        # Echo window/source honestly from the covariance summary (or None).
        window_days: Optional[int] = None
        cov_source: Optional[str] = None
        if isinstance(cov_doc, dict):
            wd = _num(cov_doc.get("window_days"))
            window_days = int(wd) if wd is not None else None
            cs = cov_doc.get("source")
            cov_source = str(cs) if cs is not None else None

        # is_demo honestly from the source files (positions → orch → covariance);
        # null + note if no source declares a bool.
        is_demo: Optional[bool] = None
        for doc in (positions_doc, orch_doc, cov_doc):
            if isinstance(doc, dict) and isinstance(doc.get("is_demo"), bool):
                is_demo = doc["is_demo"]
                break
        if is_demo is None:
            notes.append(
                "is_demo: no source file declares a bool — reported as null"
            )

        if positions_doc is None:
            notes.append(
                f"{POSITIONS_FILENAME}: missing/unreadable — no risk decomposition"
            )
            return _empty_result(notes, is_demo=is_demo, available=False,
                                 window_days=window_days, cov_source=cov_source)
        if not isinstance(positions_doc, dict):
            notes.append(
                f"{POSITIONS_FILENAME}: unexpected top-level type — no analysis"
            )
            return _empty_result(notes, is_demo=is_demo, available=False,
                                 window_days=window_days, cov_source=cov_source)

        slug_index, cov = _build_cov_index(cov_doc)
        if not cov:
            notes.append(
                f"{COVARIANCE_FILENAME}: missing/broken/empty covariance_matrix "
                "— no risk decomposition (variance never fabricated)"
            )
            return _empty_result(notes, is_demo=is_demo, available=False,
                                 window_days=window_days, cov_source=cov_source)

        # ── REUSE BY IMPORT: build_exposure is the single source of weights. ───
        exposure = build_exposure(positions_doc, orch_doc)
        if not isinstance(exposure, dict) or not exposure.get("available"):
            notes.append(
                "build_exposure unavailable — empty/broken positions, no analysis"
            )
            return _empty_result(notes, is_demo=is_demo, available=False,
                                 window_days=window_days, cov_source=cov_source)

        by_protocol = exposure.get("by_protocol") or {}
        if not isinstance(by_protocol, dict) or not by_protocol:
            notes.append("no deployed protocols in exposure — honest empty result")
            return _empty_result(notes, is_demo=is_demo, available=False,
                                 window_days=window_days, cov_source=cov_source)

        # ── Map each deployed protocol to a covariance instrument row. ─────────
        # rows carry: protocol, capital_weight (the position's share of full
        # AUM, fraction), slug, sigma_i (sqrt Σ_ii), known.
        rows: List[Dict[str, Any]] = []
        for proto, info in by_protocol.items():
            if not isinstance(info, dict):
                continue
            norm_proto = normalize_protocol(proto)
            share_pct = _num(info.get("share_pct"))
            if share_pct is None:
                notes.append(f"{proto}: missing share in exposure — skipped")
                continue
            capital_weight = share_pct / 100.0  # ÷100 only — no duplicated math
            slug, ambiguous = _match_instrument(norm_proto, slug_index)
            if slug is None or slug not in cov or slug not in cov[slug]:
                rows.append({
                    "protocol": str(proto),
                    "capital_weight": capital_weight,
                    "slug": None,
                    "sigma_i": None,
                    "known": False,
                    "tier": info.get("tier", "unknown"),
                })
                notes.append(
                    f"{proto}: no covariance row matched — uncovered_risk_weight, "
                    "excluded from risk decomposition (variance not fabricated)"
                )
                continue
            var_ii = cov[slug][slug]
            sigma_i = math.sqrt(var_ii) if var_ii is not None and var_ii > 0 else 0.0
            if ambiguous:
                notes.append(
                    f"{proto}: multiple covariance instruments matched — "
                    f"deterministically using '{slug}'"
                )
            rows.append({
                "protocol": str(proto),
                "capital_weight": capital_weight,
                "slug": slug,
                "sigma_i": sigma_i,
                "known": True,
                "tier": info.get("tier", "unknown"),
            })

        if not rows:
            notes.append("no usable deployed positions — honest empty result")
            return _empty_result(notes, is_demo=is_demo, available=False,
                                 window_days=window_days, cov_source=cov_source)

        covered = [r for r in rows if r["known"]]
        uncovered = [r for r in rows if not r["known"]]
        uncovered_risk_weight = sum(r["capital_weight"] for r in uncovered)

        # Deployed weight = sum over all deployed protocols (covered+uncovered);
        # covered_weight_share = covered fraction of that deployed weight.
        deployed_weight = sum(r["capital_weight"] for r in rows)
        covered_deployed_weight = sum(r["capital_weight"] for r in covered)
        covered_weight_share = (
            covered_deployed_weight / deployed_weight if deployed_weight > 0 else 0.0
        )

        if not covered or covered_deployed_weight <= 0:
            notes.append(
                "no covered protocols with a covariance row — risk not "
                "decomposable; honest empty result"
            )
            res = _empty_result(notes, is_demo=is_demo, available=True,
                                window_days=window_days, cov_source=cov_source)
            res["uncovered_risk_weight"] = round(uncovered_risk_weight, 9)
            res["covered_weight_share"] = round(covered_weight_share, 9)
            res["num_risk_sources"] = len(rows)
            res["num_uncovered"] = len(uncovered)
            res["counts"] = {"sources": len(rows), "covered": 0,
                             "uncovered": len(uncovered)}
            res["verdict"] = "warn"
            return res

        # ── Renormalise covered weights to sum to 1 over the covered book. ─────
        slugs = [r["slug"] for r in covered]
        w = [r["capital_weight"] / covered_deployed_weight for r in covered]
        n = len(covered)

        # Σ w  (covered sub-matrix; missing cross terms → 0 honestly).
        sigma_w = [0.0] * n
        for i in range(n):
            si = slugs[i]
            row_i = cov.get(si, {})
            acc = 0.0
            for j in range(n):
                cij = row_i.get(slugs[j])
                if cij is None:
                    # try symmetric entry; else 0 (never invent a covariance).
                    cji = cov.get(slugs[j], {}).get(si)
                    cij = cji if cji is not None else 0.0
                acc += cij * w[j]
            sigma_w[i] = acc

        portfolio_variance = sum(w[i] * sigma_w[i] for i in range(n))
        if portfolio_variance < 0:
            # Numerically-negative variance (non-PSD sub-matrix) — honest note,
            # clamp to 0 so we never sqrt a negative.
            notes.append(
                "wᵀΣw < 0 on the covered sub-matrix (non-PSD) — clamped to 0; "
                "risk decomposition not meaningful"
            )
            portfolio_variance = 0.0
        portfolio_volatility_pp = math.sqrt(portfolio_variance)

        # ── Marginal / component / percent risk contributions. ────────────────
        if portfolio_volatility_pp > 0:
            mctr = [sigma_w[i] / portfolio_volatility_pp for i in range(n)]
            cctr = [w[i] * mctr[i] for i in range(n)]
            prc = [cctr[i] / portfolio_volatility_pp for i in range(n)]
        else:
            # Zero portfolio vol (e.g. fully-offsetting / single zero-vol asset):
            # contributions are undefined → 0; honest note.
            notes.append(
                "portfolio volatility is 0 — risk contributions undefined, "
                "reported as 0"
            )
            mctr = [0.0] * n
            cctr = [0.0] * n
            prc = [0.0] * n

        for i, r in enumerate(covered):
            r["weight"] = w[i]
            r["mctr"] = mctr[i]
            r["cctr"] = cctr[i]
            r["prc"] = prc[i]
            r["risk_weight_ratio"] = (
                prc[i] / r["capital_weight"] if r["capital_weight"] > 0 else None
            )

        # ── Risk-PRC HHI + effective number of risk sources. ──────────────────
        risk_hhi = sum(p * p for p in prc)
        risk_hhi_index = round(risk_hhi * 10000.0)
        effective_num_risk_sources = (1.0 / risk_hhi) if risk_hhi > 0 else None
        risk_concentration_class = _classify_risk(risk_hhi_index)

        # ── Top-1 / top-3 risk shares (by PRC). ───────────────────────────────
        ordered = sorted(covered, key=lambda r: r["prc"], reverse=True)
        if ordered and ordered[0]["prc"] > 0:
            top1_risk_protocol = ordered[0]["protocol"]
            top1_risk_share = ordered[0]["prc"]
            top3_risk_share = sum(r["prc"] for r in ordered[:3])
        else:
            top1_risk_protocol = None
            top1_risk_share = 0.0
            top3_risk_share = 0.0

        # ── Diversification ratio = (Σ w_i·sigma_i) / sigma_p. ────────────────
        weighted_standalone_vol = sum(w[i] * covered[i]["sigma_i"] for i in range(n))
        if portfolio_volatility_pp > 0:
            diversification_ratio = weighted_standalone_vol / portfolio_volatility_pp
        else:
            diversification_ratio = None

        # ── Risk-vs-capital: biggest over-risk position (max PRC/capital). ─────
        max_over = None
        max_ratio = None
        for r in covered:
            rr = r.get("risk_weight_ratio")
            if rr is None:
                continue
            if max_ratio is None or rr > max_ratio:
                max_ratio = rr
                max_over = r["protocol"]

        # ── Verdict (advisory only). ───────────────────────────────────────────
        if (
            top1_risk_share > MAX_SINGLE_RISK_SHARE
            or risk_concentration_class == "concentrated"
        ):
            verdict = "fail"
        elif (
            risk_concentration_class == "moderate"
            or uncovered_risk_weight > UNCOVERED_RISK_WARN_SHARE
        ):
            verdict = "warn"
        else:
            verdict = "ok"

        if uncovered:
            notes.append(
                f"{len(uncovered)} protocol(s) uncovered "
                f"({round(uncovered_risk_weight * 100.0, 4)}% of AUM weight) — "
                "excluded from the risk decomposition"
            )

        # ── Per-protocol breakdown (covered by PRC desc, then uncovered). ──────
        covered.sort(key=lambda r: r["prc"], reverse=True)
        uncovered.sort(key=lambda r: r["capital_weight"], reverse=True)
        breakdown: List[Dict[str, Any]] = []
        for r in covered:
            breakdown.append({
                "protocol": r["protocol"],
                "known": True,
                "slug": r["slug"],
                "capital_weight": round(r["capital_weight"], 9),
                "weight": round(r["weight"], 9),
                "standalone_vol_pp": round(r["sigma_i"], 9),
                "mctr": round(r["mctr"], 9),
                "cctr": round(r["cctr"], 9),
                "prc": round(r["prc"], 9),
                "risk_weight_ratio": (
                    None if r["risk_weight_ratio"] is None
                    else round(r["risk_weight_ratio"], 9)
                ),
                "tier": r["tier"],
            })
        for r in uncovered:
            breakdown.append({
                "protocol": r["protocol"],
                "known": False,
                "slug": None,
                "capital_weight": round(r["capital_weight"], 9),
                "weight": None,
                "standalone_vol_pp": None,
                "mctr": None,
                "cctr": None,
                "prc": None,
                "risk_weight_ratio": None,
                "tier": r["tier"],
            })

        return {
            "available": True,
            "advisory_only": True,
            "execution_mode": "read_only",
            "is_demo": is_demo,
            "verdict": verdict,
            "portfolio_variance": round(portfolio_variance, 9),
            "portfolio_volatility_pp": round(portfolio_volatility_pp, 9),
            "risk_hhi": round(risk_hhi, 9),
            "risk_hhi_index": int(risk_hhi_index),
            "effective_num_risk_sources": (
                None if effective_num_risk_sources is None
                else round(effective_num_risk_sources, 4)
            ),
            "top1_risk_protocol": top1_risk_protocol,
            "top1_risk_share": round(top1_risk_share, 9),
            "top3_risk_share": round(top3_risk_share, 9),
            "risk_concentration_class": risk_concentration_class,
            "diversification_ratio": (
                None if diversification_ratio is None
                else round(diversification_ratio, 9)
            ),
            "covered_weight_share": round(covered_weight_share, 9),
            "uncovered_risk_weight": round(uncovered_risk_weight, 9),
            "max_over_risk_protocol": max_over,
            "max_risk_weight_ratio": (
                None if max_ratio is None else round(max_ratio, 9)
            ),
            "num_risk_sources": len(rows),
            "num_covered": len(covered),
            "num_uncovered": len(uncovered),
            "max_single_risk_share": MAX_SINGLE_RISK_SHARE,
            "uncovered_risk_warn_share": UNCOVERED_RISK_WARN_SHARE,
            "counts": {
                "sources": len(rows),
                "covered": len(covered),
                "uncovered": len(uncovered),
            },
            "breakdown": breakdown,
            "window_days": window_days,
            "covariance_source": cov_source,
            "source_files": list(SOURCE_FILES),
            "disclaimer": DISCLAIMER,
            "notes": notes,
            "risk_units": "pp_apy_volatility",
        }
    except Exception as exc:  # last resort: even a junk data_dir never raises
        log.warning("build_risk_contribution degraded: %s", exc)
        return _empty_result(
            [f"internal error: {type(exc).__name__}: {exc} — honest empty result"],
        )


def build_status_doc(
    data_dir: Optional[str | os.PathLike] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Wrap :func:`build_risk_contribution` in a persistable status document.

    Adds a ``meta`` block ({generated_at, source_files}); ``history`` is added
    by :func:`write_status` on write.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    result = build_risk_contribution(data_dir)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "meta": {
            "generated_at": now.isoformat(),
            "source_files": result.get("source_files", list(SOURCE_FILES)),
        },
        **result,
    }


# ─── Persist (idempotent, pattern: yield_attribution / concentration_analytics) ─


def content_fingerprint(doc: Any) -> str:
    """Canonical fingerprint of the status CONTENT. Pure function.

    Volatile fields excluded: top-level ``history`` and ``meta.generated_at``
    (documented idempotency choice — ``generated_at`` only changes when content
    changes). Non-dict input → a fingerprint that never matches a valid doc.
    """
    if not isinstance(doc, dict):
        return "<invalid>"
    core = {k: v for k, v in doc.items() if k != "history"}
    meta = core.get("meta")
    if isinstance(meta, dict):
        core["meta"] = {k: v for k, v in meta.items() if k != "generated_at"}
    return json.dumps(core, sort_keys=True, ensure_ascii=False)


def _history_entry(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Short run-history record for risk_contribution.json."""
    meta = doc.get("meta") or {}
    return {
        "generated_at": meta.get("generated_at"),
        "verdict": doc.get("verdict"),
        "portfolio_volatility_pp": doc.get("portfolio_volatility_pp"),
        "risk_hhi_index": doc.get("risk_hhi_index"),
        "top1_risk_share": doc.get("top1_risk_share"),
        "diversification_ratio": doc.get("diversification_ratio"),
        "covered_weight_share": doc.get("covered_weight_share"),
        "counts": doc.get("counts"),
    }


def write_status(
    doc: Dict[str, Any], data_dir: Optional[str | os.PathLike] = None
) -> Dict[str, Any]:
    """Atomically write data/risk_contribution.json (tmp + os.replace).

    Idempotency: if :func:`content_fingerprint` is unchanged relative to the
    persisted status, the file is NOT rewritten (a repeated ``--run`` is
    byte-identical and history does not grow). On a content change a short
    record is appended to ``history`` (rotation ≤ :data:`HISTORY_MAX`). A
    broken/absent existing status file is tolerated as fresh. Returns
    {"path", "changed"}.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    path = ddir / STATUS_FILENAME
    prev = _read_json(path)
    if isinstance(prev, dict) and content_fingerprint(prev) == content_fingerprint(doc):
        log.info("risk contribution status unchanged: %s", path)
        return {"path": str(path), "changed": False}

    history: List[Dict[str, Any]] = []
    if isinstance(prev, dict) and isinstance(prev.get("history"), list):
        history = [h for h in prev["history"] if isinstance(h, dict)]
    history.append(_history_entry(doc))
    out = dict(doc)
    out["history"] = history[-HISTORY_MAX:]
    _atomic_write_json(path, out)
    log.info("risk contribution status written: %s", path)
    return {"path": str(path), "changed": True}


# ─── CLI (offline, advisory, exit 0, no tracebacks) ──────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.paper_trading.risk_contribution",
        description=(
            "Portfolio Risk Contribution & Risk-Budget Analyzer "
            "(SPA-V437 / MP-118): read-only / advisory variance decomposition — "
            "per-protocol marginal/component/percent risk contribution, risk "
            "HHI, effective risk sources, top-N risk share, diversification "
            "ratio, risk-vs-capital + uncovered-risk bucket. Offline."
        ),
        add_help=True,
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--check", action="store_true",
        help="compute and print the JSON analysis WITHOUT writing (default)",
    )
    group.add_argument(
        "--run", action="store_true",
        help="compute and atomically write data/risk_contribution.json",
    )
    p.add_argument("--data-dir", default=None, help="override data directory")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    # Custom error handling: argparse normally prints to stderr and exits 2 on a
    # junk arg; this advisory CLI must always exit 0 with a clear ERROR and no
    # traceback (pattern: yield_attribution.py / concentration_analytics.py).
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(
                "ERROR: invalid arguments — use --check | --run [--data-dir DIR]",
                file=sys.stderr,
            )
        return 0

    try:
        doc = build_status_doc(data_dir=args.data_dir)
        if args.run:
            outcome = write_status(doc, data_dir=args.data_dir)
            print(
                f"risk_contribution: verdict={doc['verdict']} "
                f"vol_pp={doc.get('portfolio_volatility_pp')} "
                f"risk_hhi_index={doc.get('risk_hhi_index')} "
                f"class={doc.get('risk_concentration_class')} "
                f"top1={doc.get('top1_risk_share')} "
                f"div_ratio={doc.get('diversification_ratio')} — "
                f"{'written' if outcome['changed'] else 'unchanged (idempotent)'} "
                f"{outcome['path']}"
            )
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
    except Exception as exc:  # advisory: no tracebacks, exit 0
        print(
            f"risk_contribution: ERROR — {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
