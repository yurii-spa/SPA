"""
YieldSpreadAnalyzer (MP-664)
============================
Per-adapter yield-spread analyzer. Advisory / read-only.

Computes the spread between each adapter's APY and a benchmark / risk-free
baseline (e.g. a short-dated T-Bill proxy). The spread is expressed in basis
points (bps) and classified into a valuation band. This module answers "how
much excess yield does this adapter pay over the risk-free rate?" — it does
NOT forecast, move capital, or alter risk thresholds. Outputs are advisory.

spread_bps = (apy - benchmark_apy) * 10000  (rounded to 6dp to avoid drift)

Valuation classification by spread_bps:
    RICH      spread_bps >  +300        (well above benchmark)
    FAIR      +50 <= spread_bps <= +300
    THIN       0  <= spread_bps <  +50
    NEGATIVE  spread_bps <  0           (below the risk-free baseline)

Output ring-buffer (30 entries): data/yield_spread_report.json

Design constraints
------------------
* Pure stdlib — no numpy / scipy / requests / web3 / pandas.
* Advisory only — never modifies risk/, execution/, monitoring/, allocator/,
  cycle_runner. Advisory flags are informational, never move capital.
* Atomic writes: tmp + os.replace.
* Never raises on the happy path; load failures degrade gracefully.

CLI
---
``python3 -m spa_core.analytics.yield_spread_analyzer --check``
``python3 -m spa_core.analytics.yield_spread_analyzer --run``
``python3 -m spa_core.analytics.yield_spread_analyzer --data-dir PATH``

MP-664.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_OUTPUT_FILENAME = "yield_spread_report.json"
_RING_BUFFER_MAX = 30

# Default benchmark / risk-free baseline: ~4.5% T-Bill proxy.
_DEFAULT_BENCHMARK_APY = 0.045

# Valuation thresholds (in basis points over the benchmark)
_RICH_THRESHOLD = 300.0    # spread_bps > +300 → RICH
_FAIR_LOWER = 50.0         # +50 <= spread_bps <= +300 → FAIR
_THIN_LOWER = 0.0          # 0 <= spread_bps < +50 → THIN
#                            spread_bps < 0 → NEGATIVE

# Valuation labels
_VAL_RICH = "RICH"
_VAL_FAIR = "FAIR"
_VAL_THIN = "THIN"
_VAL_NEGATIVE = "NEGATIVE"

_ALL_VALUATIONS = [_VAL_RICH, _VAL_FAIR, _VAL_THIN, _VAL_NEGATIVE]

_ADVISORY_CLEAN = (
    "Yield spreads are descriptive only. No adapters yield below the "
    "benchmark. Advisory only — not financial advice."
)
_ADVISORY_PREFIX = (
    "Yield spreads are descriptive only. Below-benchmark (NEGATIVE) spread for: "
)
_ADVISORY_SUFFIX = " Advisory only — not financial advice."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val: object) -> Optional[float]:
    """Coerce to float; return None on failure or bool."""
    if isinstance(val, bool):
        return None
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classify_valuation(spread_bps: float) -> str:
    """Classify a spread (in bps) into a valuation band."""
    if spread_bps > _RICH_THRESHOLD:
        return _VAL_RICH
    if spread_bps >= _FAIR_LOWER:
        return _VAL_FAIR
    if spread_bps >= _THIN_LOWER:
        return _VAL_THIN
    return _VAL_NEGATIVE


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SpreadPoint:
    """Spread of one adapter's APY over the benchmark baseline."""
    adapter_id: str
    apy: float
    benchmark_apy: float
    spread_bps: float
    valuation: str
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "adapter_id": self.adapter_id,
            "apy": round(self.apy, 6),
            "benchmark_apy": round(self.benchmark_apy, 6),
            "spread_bps": round(self.spread_bps, 6),
            "valuation": self.valuation,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SpreadPoint":
        return cls(
            adapter_id=str(d.get("adapter_id", "")),
            apy=float(_safe_float(d.get("apy", 0.0)) or 0.0),
            benchmark_apy=float(_safe_float(d.get("benchmark_apy", 0.0)) or 0.0),
            spread_bps=float(_safe_float(d.get("spread_bps", 0.0)) or 0.0),
            valuation=str(d.get("valuation", _VAL_THIN)),
            timestamp=str(d.get("timestamp", "")),
        )


@dataclass
class SpreadReport:
    """Container for a full spread report (mirrors generate_report output)."""
    generated_at: str
    spreads: List[SpreadPoint]
    best_spread: Optional[float]
    worst_spread: Optional[float]
    mean_spread_bps: Optional[float]
    advisory: str

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "spreads": [s.to_dict() for s in self.spreads],
            "best_spread": (
                round(self.best_spread, 6) if self.best_spread is not None else None
            ),
            "worst_spread": (
                round(self.worst_spread, 6) if self.worst_spread is not None else None
            ),
            "mean_spread_bps": (
                round(self.mean_spread_bps, 6)
                if self.mean_spread_bps is not None
                else None
            ),
            "advisory": self.advisory,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SpreadReport":
        raw_spreads = d.get("spreads", [])
        if not isinstance(raw_spreads, list):
            raw_spreads = []
        best = d.get("best_spread", None)
        worst = d.get("worst_spread", None)
        mean = d.get("mean_spread_bps", None)
        return cls(
            generated_at=str(d.get("generated_at", "")),
            spreads=[SpreadPoint.from_dict(s) for s in raw_spreads if isinstance(s, dict)],
            best_spread=(None if best is None else float(_safe_float(best) or 0.0)),
            worst_spread=(None if worst is None else float(_safe_float(worst) or 0.0)),
            mean_spread_bps=(None if mean is None else float(_safe_float(mean) or 0.0)),
            advisory=str(d.get("advisory", "")),
        )


# ---------------------------------------------------------------------------
# YieldSpreadAnalyzer
# ---------------------------------------------------------------------------

class YieldSpreadAnalyzer:
    """Per-adapter yield-spread analyzer (advisory only)."""

    OUTPUT_FILE: str = _OUTPUT_FILENAME
    RING_BUFFER_SIZE: int = _RING_BUFFER_MAX

    def __init__(
        self,
        data_dir: Optional[str] = None,
        benchmark_apy: float = _DEFAULT_BENCHMARK_APY,
    ) -> None:
        if data_dir is None:
            data_dir = str(_DEFAULT_DATA_DIR)
        self._data_dir = Path(data_dir)
        self.benchmark_apy = benchmark_apy
        self._ensure_stub()

    # ------------------------------------------------------------------
    # Stub
    # ------------------------------------------------------------------

    def _ensure_stub(self) -> None:
        """Create an empty data/yield_spread_report.json stub ([]) if absent."""
        try:
            out_path = self._data_dir / self.OUTPUT_FILE
            if not out_path.exists():
                self._data_dir.mkdir(parents=True, exist_ok=True)
                _atomic_write(out_path, [])
        except Exception:
            # Never raise on construction; degrade gracefully.
            pass

    # ------------------------------------------------------------------
    # Spread computation
    # ------------------------------------------------------------------

    def compute_spread(self, apy: float, benchmark_apy: float) -> float:
        """
        Spread in basis points: (apy - benchmark_apy) * 10000.

        Rounded to 6 decimal places to avoid float drift.
        """
        a = _safe_float(apy)
        b = _safe_float(benchmark_apy)
        if a is None:
            a = 0.0
        if b is None:
            b = 0.0
        return round((a - b) * 10000.0, 6)

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def analyze(
        self,
        apy_map: Dict[str, float],
        benchmark_apy: Optional[float] = None,
    ) -> List[SpreadPoint]:
        """
        Compute a SpreadPoint for every adapter in ``apy_map``.

        Parameters
        ----------
        apy_map        : current APY (fractional) per adapter
        benchmark_apy  : override the instance benchmark for this call
        """
        bench = self.benchmark_apy if benchmark_apy is None else benchmark_apy
        bench_f = _safe_float(bench)
        if bench_f is None:
            bench_f = self.benchmark_apy

        spreads: List[SpreadPoint] = []
        if isinstance(apy_map, dict):
            now = _now_iso()
            for adapter_id in sorted(apy_map.keys()):
                raw_apy = apy_map.get(adapter_id, 0.0)
                apy = _safe_float(raw_apy)
                if apy is None:
                    apy = 0.0
                spread_bps = self.compute_spread(apy, bench_f)
                valuation = _classify_valuation(spread_bps)
                spreads.append(
                    SpreadPoint(
                        adapter_id=str(adapter_id),
                        apy=apy,
                        benchmark_apy=bench_f,
                        spread_bps=spread_bps,
                        valuation=valuation,
                        timestamp=now,
                    )
                )
        return spreads

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def generate_report(
        self,
        apy_map: Dict[str, float],
        benchmark_apy: Optional[float] = None,
    ) -> dict:
        """
        Generate a full yield-spread report for all adapters.

        Returns a dict with: spreads, best_spread (max), worst_spread (min),
        mean_spread_bps, valuation_counts, advisory, generated_at.
        """
        spreads = self.analyze(apy_map, benchmark_apy)
        generated_at = _now_iso()

        valuation_counts: Dict[str, int] = {v: 0 for v in _ALL_VALUATIONS}
        negative: List[str] = []
        for sp in spreads:
            valuation_counts[sp.valuation] = valuation_counts.get(sp.valuation, 0) + 1
            if sp.valuation == _VAL_NEGATIVE:
                negative.append(sp.adapter_id)

        if spreads:
            bps_values = [s.spread_bps for s in spreads]
            best = max(bps_values)
            worst = min(bps_values)
            mean = round(sum(bps_values) / len(bps_values), 6)
        else:
            best = None
            worst = None
            mean = None

        if negative:
            advisory = _ADVISORY_PREFIX + ", ".join(negative) + "." + _ADVISORY_SUFFIX
        else:
            advisory = _ADVISORY_CLEAN

        return {
            "generated_at": generated_at,
            "adapter_count": len(spreads),
            "benchmark_apy": round(
                self.benchmark_apy if benchmark_apy is None else benchmark_apy, 6
            ),
            "spreads": [s.to_dict() for s in spreads],
            "best_spread": best,
            "worst_spread": worst,
            "mean_spread_bps": mean,
            "valuation_counts": valuation_counts,
            "advisory": advisory,
        }

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_report(self, report: dict) -> str:
        """Atomic ring-buffer write to data/yield_spread_report.json."""
        out_path = self._data_dir / self.OUTPUT_FILE
        self._data_dir.mkdir(parents=True, exist_ok=True)

        existing: List[dict] = []
        if out_path.exists():
            try:
                with open(out_path, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError, ValueError):
                existing = []

        existing.append(report)
        if len(existing) > self.RING_BUFFER_SIZE:
            existing = existing[-self.RING_BUFFER_SIZE:]

        _atomic_write(out_path, existing)
        return str(out_path)


# ---------------------------------------------------------------------------
# Helpers (I/O)
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: object) -> None:
    """Write JSON atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(data, str(path))
# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_synthetic_inputs() -> Dict[str, float]:
    """Return minimal synthetic APY map for CLI demo (exercises each band)."""
    return {
        "aave_v3": 0.090,          # RICH   (+450 bps over 4.5%)
        "compound_v3": 0.060,      # FAIR   (+150 bps)
        "morpho_steakhouse": 0.047,  # THIN  (+20 bps)
        "lossy_vault": 0.030,      # NEGATIVE (-150 bps)
    }


def _load_live_data(data_dir: Path) -> Dict[str, float]:
    """Attempt to load APY data from existing data files; fall back to synthetic."""
    apy_map: Dict[str, float] = {}

    yf_path = data_dir / "yield_forecast.json"
    if yf_path.exists():
        try:
            with open(yf_path, "r", encoding="utf-8") as fh:
                ring = json.load(fh)
            if isinstance(ring, list) and ring:
                latest = ring[-1]
                adapters = latest.get("adapters", {}) if isinstance(latest, dict) else {}
                if isinstance(adapters, dict):
                    for adapter_id, info in adapters.items():
                        if isinstance(info, dict):
                            apy = info.get("current_apy")
                            if isinstance(apy, (int, float)):
                                apy_map[adapter_id] = float(apy)
        except (json.JSONDecodeError, OSError, TypeError):
            pass

    if not apy_map:
        apy_map = _build_synthetic_inputs()

    return apy_map


def main(argv: Optional[List[str]] = None) -> None:
    args = sys.argv[1:] if argv is None else argv

    data_dir: Optional[str] = None
    do_run = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--run":
            do_run = True
        elif arg == "--check":
            do_run = False
        elif arg == "--data-dir" and i + 1 < len(args):
            i += 1
            data_dir = args[i]
        i += 1

    analyzer = YieldSpreadAnalyzer(data_dir=data_dir)
    apy_map = _load_live_data(analyzer._data_dir)
    report = analyzer.generate_report(apy_map)

    print(json.dumps(report, indent=2))

    if do_run:
        path = analyzer.save_report(report)
        print(f"\n[yield_spread_analyzer] Saved -> {path}", file=sys.stderr)
    else:
        print("\n[yield_spread_analyzer] --check mode: no file written.", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()
