"""
MP-716: APYNormalizationEngine
Normalizes APY figures from different sources to a comparable basis —
handling compounding frequency differences, outlier removal, and data quality checks.

Advisory/read-only. Pure stdlib. Atomic JSON writes via tmp+os.replace.
Ring-buffer cap 100 entries.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from spa_core.utils.atomic import atomic_save

# ── Default paths ──────────────────────────────────────────────────────────
_DEFAULT_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "apy_normalization_log.json"
)
_RING_CAP = 100


# ── Dataclasses ────────────────────────────────────────────────────────────

@dataclass
class RawAPY:
    source: str
    protocol: str
    pool: str
    raw_apy: float
    compounding: str      # "continuous"|"daily"|"weekly"|"monthly"|"annual"|"simple"
    data_quality: str     # "HIGH"|"MEDIUM"|"LOW"


@dataclass
class NormalizedAPY:
    source: str
    protocol: str
    pool: str
    raw_apy: float
    compounding: str

    # Normalized to annual effective rate (EAR)
    ear: float               # Effective Annual Rate, continuously-compounded basis
    apr: float               # Simple APR (same numeric value as EAR for this model)

    # Quality
    is_outlier: bool
    data_quality: str
    quality_score: float     # 0–100  (HIGH=90, MEDIUM=60, LOW=30)

    # Adjusted
    quality_adjusted_apy: float  # ear * quality_score / 100


@dataclass
class NormalizationReport:
    entries: List[NormalizedAPY]

    # Stats on normalized (non-outlier) entries
    mean_ear: float
    median_ear: float
    std_ear: float

    # Outlier analysis
    outlier_count: int
    outlier_threshold_high: float   # mean + 2*std
    outlier_threshold_low: float    # max(0, mean - 2*std)

    # Best data
    highest_quality_adjusted: Optional[NormalizedAPY]
    highest_ear: Optional[NormalizedAPY]

    saved_to: str = ""
    timestamp: float = field(default_factory=time.time)


# ── Core conversion helpers ────────────────────────────────────────────────

def to_ear(raw_apy: float, compounding: str) -> float:
    """
    Convert raw_apy (expressed as %) with a given compounding frequency
    to the Effective Annual Rate (also expressed as %).

    "simple"     → raw_apy (no compounding effect modeled)
    "annual"     → raw_apy (compounded once per year = no change)
    "monthly"    → EAR = ((1 + raw_apy/100/12)^12 - 1) * 100
    "weekly"     → EAR = ((1 + raw_apy/100/52)^52 - 1) * 100
    "daily"      → EAR = ((1 + raw_apy/100/365)^365 - 1) * 100
    "continuous" → EAR = (e^(raw_apy/100) - 1) * 100
    Unknown      → raw_apy unchanged
    """
    c = compounding.lower().strip()
    if c in ("simple", "annual"):
        return raw_apy
    if c == "monthly":
        return ((1 + raw_apy / 100 / 12) ** 12 - 1) * 100
    if c == "weekly":
        return ((1 + raw_apy / 100 / 52) ** 52 - 1) * 100
    if c == "daily":
        return ((1 + raw_apy / 100 / 365) ** 365 - 1) * 100
    if c == "continuous":
        return (math.exp(raw_apy / 100) - 1) * 100
    # Unknown compounding → return raw unchanged
    return raw_apy


def quality_score(data_quality: str) -> float:
    """Map data_quality string to numeric score 0–100."""
    mapping = {"HIGH": 90.0, "MEDIUM": 60.0, "LOW": 30.0}
    return mapping.get(data_quality.upper().strip(), 30.0)


# ── Normalization & outlier detection ─────────────────────────────────────

def normalize(raw_entries: List[RawAPY]) -> List[NormalizedAPY]:
    """
    Convert list of RawAPY to NormalizedAPY.
    is_outlier is set to False here; call detect_outliers afterwards.
    """
    result: List[NormalizedAPY] = []
    for r in raw_entries:
        ear = to_ear(r.raw_apy, r.compounding)
        apr = ear  # EAR expressed as % is the comparable APR for this model
        qs = quality_score(r.data_quality)
        qa = ear * qs / 100.0
        result.append(NormalizedAPY(
            source=r.source,
            protocol=r.protocol,
            pool=r.pool,
            raw_apy=r.raw_apy,
            compounding=r.compounding,
            ear=ear,
            apr=apr,
            is_outlier=False,
            data_quality=r.data_quality,
            quality_score=qs,
            quality_adjusted_apy=qa,
        ))
    return result


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: List[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def detect_outliers(normalized: List[NormalizedAPY]) -> List[NormalizedAPY]:
    """
    Flag outliers by ±2σ rule on EAR values.
    If fewer than 3 entries → no outliers flagged.
    Returns a new list with is_outlier set appropriately.
    """
    if len(normalized) < 3:
        return [_replace_outlier(e, False) for e in normalized]

    ears = [e.ear for e in normalized]
    mu = _mean(ears)
    sigma = _std(ears, mu)
    hi = mu + 2 * sigma
    lo = max(0.0, mu - 2 * sigma)

    result = []
    for e in normalized:
        is_out = (e.ear > hi) or (e.ear < lo and mu - 2 * sigma > 0)
        result.append(_replace_outlier(e, is_out))
    return result


def _replace_outlier(e: NormalizedAPY, is_outlier: bool) -> NormalizedAPY:
    return NormalizedAPY(
        source=e.source,
        protocol=e.protocol,
        pool=e.pool,
        raw_apy=e.raw_apy,
        compounding=e.compounding,
        ear=e.ear,
        apr=e.apr,
        is_outlier=is_outlier,
        data_quality=e.data_quality,
        quality_score=e.quality_score,
        quality_adjusted_apy=e.quality_adjusted_apy,
    )


# ── Report builder ─────────────────────────────────────────────────────────

def build_report(
    raw_entries: List[RawAPY],
    log_path: str = _DEFAULT_LOG,
) -> NormalizationReport:
    """
    Normalize raw entries, detect outliers, compute statistics, build report.
    """
    normed = normalize(raw_entries)
    normed = detect_outliers(normed)

    non_outliers = [e for e in normed if not e.is_outlier]
    outlier_count = sum(1 for e in normed if e.is_outlier)

    if non_outliers:
        ears_clean = [e.ear for e in non_outliers]
        mu = _mean(ears_clean)
        med = _median(ears_clean)
        sigma = _std(ears_clean, mu)
    else:
        # All entries are outliers (edge case); still compute on all
        ears_all = [e.ear for e in normed]
        mu = _mean(ears_all)
        med = _median(ears_all)
        sigma = _std(ears_all, mu)

    hi_thresh = mu + 2 * sigma
    lo_thresh = max(0.0, mu - 2 * sigma)

    highest_qa: Optional[NormalizedAPY] = None
    highest_ear_entry: Optional[NormalizedAPY] = None

    if normed:
        highest_qa = max(normed, key=lambda e: e.quality_adjusted_apy)
        highest_ear_entry = max(normed, key=lambda e: e.ear)

    return NormalizationReport(
        entries=normed,
        mean_ear=mu,
        median_ear=med,
        std_ear=sigma,
        outlier_count=outlier_count,
        outlier_threshold_high=hi_thresh,
        outlier_threshold_low=lo_thresh,
        highest_quality_adjusted=highest_qa,
        highest_ear=highest_ear_entry,
        saved_to="",
        timestamp=time.time(),
    )


# ── Source comparison ──────────────────────────────────────────────────────

def compare_sources(report: NormalizationReport) -> dict:
    """
    Return dict mapping source name → avg EAR of that source's entries.
    """
    from collections import defaultdict
    sums: dict = defaultdict(float)
    counts: dict = defaultdict(int)
    for e in report.entries:
        sums[e.source] += e.ear
        counts[e.source] += 1
    return {src: sums[src] / counts[src] for src in sums}


# ── Persistence: ring-buffer 100 ───────────────────────────────────────────

def _report_to_dict(report: NormalizationReport) -> dict:
    def entry_to_dict(e: NormalizedAPY) -> dict:
        return {
            "source": e.source,
            "protocol": e.protocol,
            "pool": e.pool,
            "raw_apy": e.raw_apy,
            "compounding": e.compounding,
            "ear": e.ear,
            "apr": e.apr,
            "is_outlier": e.is_outlier,
            "data_quality": e.data_quality,
            "quality_score": e.quality_score,
            "quality_adjusted_apy": e.quality_adjusted_apy,
        }

    def maybe(e: Optional[NormalizedAPY]):
        return entry_to_dict(e) if e is not None else None

    return {
        "entries": [entry_to_dict(e) for e in report.entries],
        "mean_ear": report.mean_ear,
        "median_ear": report.median_ear,
        "std_ear": report.std_ear,
        "outlier_count": report.outlier_count,
        "outlier_threshold_high": report.outlier_threshold_high,
        "outlier_threshold_low": report.outlier_threshold_low,
        "highest_quality_adjusted": maybe(report.highest_quality_adjusted),
        "highest_ear": maybe(report.highest_ear),
        "saved_to": report.saved_to,
        "timestamp": report.timestamp,
    }


def save_results(
    report: NormalizationReport,
    log_path: str = _DEFAULT_LOG,
) -> NormalizationReport:
    """
    Append report to ring-buffer log (cap 100). Atomic write. Returns report with saved_to set.
    """
    log_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    history = load_history(log_path)
    report = NormalizationReport(
        entries=report.entries,
        mean_ear=report.mean_ear,
        median_ear=report.median_ear,
        std_ear=report.std_ear,
        outlier_count=report.outlier_count,
        outlier_threshold_high=report.outlier_threshold_high,
        outlier_threshold_low=report.outlier_threshold_low,
        highest_quality_adjusted=report.highest_quality_adjusted,
        highest_ear=report.highest_ear,
        saved_to=log_path,
        timestamp=report.timestamp,
    )

    history.append(_report_to_dict(report))
    # Ring-buffer: keep last 100
    if len(history) > _RING_CAP:
        history = history[-_RING_CAP:]

    _atomic_write(log_path, history)
    return report


def load_history(log_path: str = _DEFAULT_LOG) -> list:
    """Load ring-buffer history list. Returns [] if file missing or malformed."""
    log_path = os.path.abspath(log_path)
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _atomic_write(path: str, data: object) -> None:
    """Write JSON atomically via tmp file + os.replace."""
    dir_ = os.path.dirname(path)
    atomic_save(data, str(path))
# ── CLI entry ──────────────────────────────────────────────────────────────

def _demo() -> None:
    """Quick smoke-test with synthetic data."""
    samples = [
        RawAPY("DeFiLlama", "Aave", "USDC-v3", 3.5, "daily", "HIGH"),
        RawAPY("DeFiLlama", "Compound", "USDC", 4.8, "monthly", "HIGH"),
        RawAPY("OnChain", "Morpho", "Steakhouse", 6.5, "continuous", "MEDIUM"),
        RawAPY("OnChain", "Pendle", "PT-USDe", 18.0, "weekly", "LOW"),
        RawAPY("DeFiLlama", "Yearn", "yvUSDC", 5.2, "daily", "MEDIUM"),
    ]
    report = build_report(samples)
    print(f"Entries: {len(report.entries)}")
    print(f"mean_ear={report.mean_ear:.4f}%  std={report.std_ear:.4f}%")
    print(f"Outliers: {report.outlier_count}")
    if report.highest_quality_adjusted:
        print(f"Best QA: {report.highest_quality_adjusted.pool} "
              f"(qa={report.highest_quality_adjusted.quality_adjusted_apy:.2f}%)")
    src_avgs = compare_sources(report)
    print("Source averages:", src_avgs)
    saved = save_results(report)
    print(f"Saved to: {saved.saved_to}")


if __name__ == "__main__":
    _demo()
