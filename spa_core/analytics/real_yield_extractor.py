"""
RealYieldExtractor (SPA-V593 / MP-712) — advisory / read-only.

Extracts "real yield" (protocol revenue shared with token holders) from total
reported APY, separating sustainable fee-based returns from inflationary token
emissions.

Design constraints
------------------
* Pure stdlib only — no numpy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace.
* Ring-buffer cap: 100 entries (data/real_yield_log.json).
* LLM_FORBIDDEN_AGENTS not applicable (analytics domain).

Yield sources
-------------
  trading_fees      → real yield (backed by protocol revenue)
  lending_interest  → real yield
  liquidation_fees  → real yield
  token_emissions   → emission yield (inflationary)
  bribe_rewards     → real yield IF token is stablecoin; else emission

CLI
---
  python3 -m spa_core.analytics.real_yield_extractor --check   (compute + print, no write)
  python3 -m spa_core.analytics.real_yield_extractor --run     (+ atomic save)
  python3 -m spa_core.analytics.real_yield_extractor --run --data-dir PATH
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_LOG_FILENAME = "real_yield_log.json"
_RING_BUFFER_MAX = 100

# Yield source literals
SOURCE_TRADING_FEES = "trading_fees"
SOURCE_LENDING_INTEREST = "lending_interest"
SOURCE_LIQUIDATION_FEES = "liquidation_fees"
SOURCE_TOKEN_EMISSIONS = "token_emissions"
SOURCE_BRIBE_REWARDS = "bribe_rewards"

# Quality classification literals
QUALITY_REAL_YIELD = "REAL_YIELD"
QUALITY_MIXED = "MIXED"
QUALITY_EMISSION_HEAVY = "EMISSION_HEAVY"
QUALITY_PONZI_RISK = "PONZI_RISK"

# Thresholds
_INFLATION_PRESSURE_CAP = 10.0
_REAL_DENOMINATOR_FLOOR = 0.001
_PONZI_APY_THRESHOLD = 5.0   # total APY > 5% with < 10% real → PONZI_RISK


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: object) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(payload, str(path))
def _load_json_file(path: Path) -> object:
    """Load JSON tolerantly. Returns None on any error."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _load_log(path: Path) -> list:
    """Load ring-buffer JSON list. Returns [] on any error."""
    data = _load_json_file(path)
    if isinstance(data, list):
        return data
    return []


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class YieldComponent:
    """One constituent of a pool's total APY."""
    source: str                 # "trading_fees" | "lending_interest" | "liquidation_fees"
                                #   | "token_emissions" | "bribe_rewards"
    apy_pct: float              # percentage points (e.g. 3.5 = 3.5%)
    is_real_yield: bool         # True → backed by protocol revenue
    token_symbol: str           # reward token (e.g. "USDC", "ARB", "CRV")
    token_is_stablecoin: bool   # True if token is a stablecoin

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "apy_pct": round(self.apy_pct, 6),
            "is_real_yield": self.is_real_yield,
            "token_symbol": self.token_symbol,
            "token_is_stablecoin": self.token_is_stablecoin,
        }


@dataclass
class RealYieldReport:
    """Full real/emission decomposition for one protocol pool."""
    protocol: str
    pool: str
    total_apy: float

    components: List[YieldComponent]

    # Decomposition
    real_yield_apy: float           # sum of is_real_yield=True components
    emission_yield_apy: float       # sum of is_real_yield=False components
    real_yield_ratio: float         # real_yield_apy / total_apy (0 if total=0)
    stablecoin_yield_apy: float     # portion paid in stablecoins

    # Sustainability
    inflation_pressure: float       # emission_yield / real_yield, capped at 10
    sustainability_score: float     # 0–100: real_yield_ratio*60 + stablecoin_ratio*40

    # Classification
    yield_quality: str              # REAL_YIELD | MIXED | EMISSION_HEAVY | PONZI_RISK
    emission_tokens: List[str]      # deduplicated list of emission token symbols

    warnings: List[str]
    saved_to: str

    def to_dict(self) -> dict:
        return {
            "protocol": self.protocol,
            "pool": self.pool,
            "total_apy": round(self.total_apy, 6),
            "components": [c.to_dict() for c in self.components],
            "real_yield_apy": round(self.real_yield_apy, 6),
            "emission_yield_apy": round(self.emission_yield_apy, 6),
            "real_yield_ratio": round(self.real_yield_ratio, 6),
            "stablecoin_yield_apy": round(self.stablecoin_yield_apy, 6),
            "inflation_pressure": round(self.inflation_pressure, 6),
            "sustainability_score": round(self.sustainability_score, 4),
            "yield_quality": self.yield_quality,
            "emission_tokens": self.emission_tokens,
            "warnings": self.warnings,
            "saved_to": self.saved_to,
            "generated_at": _now_iso(),
        }


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def classify_component(source: str, token_is_stablecoin: bool) -> bool:
    """Return True if this yield component is considered 'real yield'.

    Rules:
      trading_fees / lending_interest / liquidation_fees → True
      token_emissions → False
      bribe_rewards   → True iff token_is_stablecoin (stable bribes count as real)
    """
    if source in (SOURCE_TRADING_FEES, SOURCE_LENDING_INTEREST, SOURCE_LIQUIDATION_FEES):
        return True
    if source == SOURCE_TOKEN_EMISSIONS:
        return False
    if source == SOURCE_BRIBE_REWARDS:
        return token_is_stablecoin
    # unknown source → treat conservatively as not real
    return False


def extract(
    protocol: str,
    pool: str,
    components: List[YieldComponent],
    data_dir: Optional[Path] = None,
) -> RealYieldReport:
    """Decompose total APY into real yield vs emissions and compute quality metrics.

    Parameters
    ----------
    protocol : str
        Protocol name (e.g. "Aave V3").
    pool : str
        Pool identifier (e.g. "USDC-ETH").
    components : list[YieldComponent]
        Yield component list (may be empty → all-zero report).
    data_dir : Path, optional
        Override for data directory (used by save_results).

    Returns
    -------
    RealYieldReport
    """
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR

    # Re-classify components according to the canonical rule
    classified: List[YieldComponent] = []
    for c in components:
        real = classify_component(c.source, c.token_is_stablecoin)
        classified.append(YieldComponent(
            source=c.source,
            apy_pct=c.apy_pct,
            is_real_yield=real,
            token_symbol=c.token_symbol,
            token_is_stablecoin=c.token_is_stablecoin,
        ))

    total_apy = sum(c.apy_pct for c in classified)
    real_yield_apy = sum(c.apy_pct for c in classified if c.is_real_yield)
    emission_yield_apy = sum(c.apy_pct for c in classified if not c.is_real_yield)
    stablecoin_yield_apy = sum(c.apy_pct for c in classified if c.token_is_stablecoin)

    # Ratios (guard against total = 0)
    if total_apy != 0:
        real_yield_ratio = real_yield_apy / total_apy
        stablecoin_ratio = stablecoin_yield_apy / total_apy
    else:
        real_yield_ratio = 0.0
        stablecoin_ratio = 0.0

    # Inflation pressure: emission_yield / real_yield, capped at 10
    inflation_pressure = min(
        _INFLATION_PRESSURE_CAP,
        emission_yield_apy / max(real_yield_apy, _REAL_DENOMINATOR_FLOOR),
    )

    # Sustainability score: 0–100
    raw_score = real_yield_ratio * 60.0 + stablecoin_ratio * 40.0
    sustainability_score = max(0.0, min(100.0, raw_score))

    # Quality classification
    if real_yield_ratio >= 0.7:
        yield_quality = QUALITY_REAL_YIELD
    elif real_yield_ratio >= 0.4:
        yield_quality = QUALITY_MIXED
    elif real_yield_ratio >= 0.1:
        yield_quality = QUALITY_EMISSION_HEAVY
    elif total_apy > _PONZI_APY_THRESHOLD:
        yield_quality = QUALITY_PONZI_RISK
    else:
        # Low APY, mostly/all emissions
        yield_quality = QUALITY_EMISSION_HEAVY

    # Emission tokens (deduplicated, preserving first-seen order)
    seen: set = set()
    emission_tokens: List[str] = []
    for c in classified:
        if not c.is_real_yield and c.token_symbol not in seen:
            seen.add(c.token_symbol)
            emission_tokens.append(c.token_symbol)

    # Warnings
    warnings: List[str] = []
    if real_yield_ratio < 0.2:
        warnings.append("less than 20% real yield")
    if inflation_pressure > 5:
        warnings.append("emissions 5x real yield")
    # High non-stable emissions: any emission component with non-stable token and apy > 10%
    for c in classified:
        if not c.is_real_yield and not c.token_is_stablecoin and c.apy_pct > 10.0:
            warnings.append("high non-stable emissions")
            break

    saved_to = str(data_dir / _LOG_FILENAME)

    return RealYieldReport(
        protocol=protocol,
        pool=pool,
        total_apy=total_apy,
        components=classified,
        real_yield_apy=real_yield_apy,
        emission_yield_apy=emission_yield_apy,
        real_yield_ratio=real_yield_ratio,
        stablecoin_yield_apy=stablecoin_yield_apy,
        inflation_pressure=inflation_pressure,
        sustainability_score=sustainability_score,
        yield_quality=yield_quality,
        emission_tokens=emission_tokens,
        warnings=warnings,
        saved_to=saved_to,
    )


def compare_protocols(reports: List[RealYieldReport]) -> List[RealYieldReport]:
    """Sort reports by real_yield_ratio descending (best real yield first)."""
    return sorted(reports, key=lambda r: r.real_yield_ratio, reverse=True)


def filter_real_yield_only(
    reports: List[RealYieldReport],
    min_real_apy: float,
) -> List[RealYieldReport]:
    """Return only reports where real_yield_apy >= min_real_apy."""
    return [r for r in reports if r.real_yield_apy >= min_real_apy]


def save_results(report: RealYieldReport, data_dir: Optional[Path] = None) -> None:
    """Append report to ring-buffer log (cap 100 entries). Atomic write."""
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    log_path = Path(data_dir) / _LOG_FILENAME
    existing = _load_log(log_path)
    existing.append(report.to_dict())
    trimmed = existing[-_RING_BUFFER_MAX:]
    _atomic_write_json(log_path, trimmed)


def load_history(data_dir: Optional[Path] = None) -> list:
    """Load the full ring-buffer log. Returns [] on any error."""
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    return _load_log(Path(data_dir) / _LOG_FILENAME)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _demo_report(data_dir: Path) -> RealYieldReport:
    """Build a demo report for CLI --check / --run."""
    components = [
        YieldComponent(
            source=SOURCE_LENDING_INTEREST,
            apy_pct=3.5,
            is_real_yield=True,
            token_symbol="USDC",
            token_is_stablecoin=True,
        ),
        YieldComponent(
            source=SOURCE_TOKEN_EMISSIONS,
            apy_pct=1.2,
            is_real_yield=False,
            token_symbol="COMP",
            token_is_stablecoin=False,
        ),
        YieldComponent(
            source=SOURCE_BRIBE_REWARDS,
            apy_pct=0.8,
            is_real_yield=False,
            token_symbol="CRV",
            token_is_stablecoin=False,
        ),
    ]
    return extract("Compound V3", "USDC", components, data_dir=data_dir)


def main(argv: Optional[list] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="RealYieldExtractor (MP-712) — advisory/read-only"
    )
    parser.add_argument("--check", action="store_true", help="Compute and print (no write)")
    parser.add_argument("--run", action="store_true", help="Compute, print, and save")
    parser.add_argument("--data-dir", default=str(_DEFAULT_DATA_DIR),
                        help="Override data directory")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    report = _demo_report(data_dir)

    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))

    if args.run:
        save_results(report, data_dir=data_dir)
        print(f"\n✅ Saved to {report.saved_to}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
