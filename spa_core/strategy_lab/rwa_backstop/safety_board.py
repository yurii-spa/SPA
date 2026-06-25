"""
spa_core/strategy_lab/rwa_backstop/safety_board.py — the RWA Collateral Safety Board.

Turns the per-asset LiquidationNAVEngine measurement into the honest deliverable of the SPA-RRB
de-risk: a per-asset verdict on whether tokenized-RWA collateral has a REAL executable on-chain
exit, or is "marketing NAV only / redemption-gated", plus the quantified marketing-vs-Liquidation
gap %.

VERDICTS (per asset, from the measured legs — deterministic, fail-CLOSED):
  LIQUID          — a real PUBLIC on-chain DEX exit holds up at the $1M reference size
                    (on-chain LiqNAV/NAV ≥ ON_CHAIN_LIQUID_THRESHOLD). The asset is close to
                    cash-like on an executable exit. (Expected to be RARE in this universe.)
  THIN            — a public on-chain exit EXISTS but is shallow: it clears $100k but the price
                    impact is material by $1M / $10M (on-chain present but below the liquid bar).
  REDEMPTION_ONLY — NO usable public on-chain exit, BUT a DOCUMENTED redemption right exists. The
                    only path to cash is the issuer queue (relationship/whitelist-gated, T+n). Not
                    cash-like intraday; underwritable only if you can rely on the redemption leg.
  UNSAFE          — NO executable exit we can measure or document: no public DEX AND no documented
                    redemption. LiqNAV fail-closed to ~0. Do not underwrite read-only.

The board writes data/rwa_safety_board.json ATOMICALLY (tmp + shutil.move, repo rule #4).
RESEARCH ONLY — advisory; nothing here lends or trades.

stdlib only, deterministic, LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.strategy_lab.rwa_backstop import collateral_registry as reg
from spa_core.strategy_lab.rwa_backstop.liquidation_nav import (
    LiquidationNAVEngine,
    LiquidationNAVResult,
    ON_CHAIN_LIQUID_THRESHOLD,
    Fetcher,
)

_ROOT = Path(__file__).resolve().parents[3]  # …/SPA_Claude
DEFAULT_OUT = _ROOT / "data" / "rwa_safety_board.json"

# Reference size at which we judge "is there a real exit" (institutional ticket).
REFERENCE_SIZE_USD = 1_000_000.0
# Smallest size — a usable DEX must at least clear this to count as a thin (vs no) on-chain exit.
SMALL_SIZE_USD = 100_000.0
# A thin on-chain exit must still realise at least this fraction at $100k to be "THIN" not "UNSAFE".
THIN_MIN_SMALL_FRAC = 0.90

# 72h exit-capacity estimate: an underwriter assumes it can absorb at most this fraction of the
# discovered aggregate DEX TVL in a 3-day forced unwind without unbounded impact (conservative).
EXIT_CAPACITY_72H_FRAC_OF_TVL = 0.25

LIQUID = "LIQUID"
THIN = "THIN"
REDEMPTION_ONLY = "REDEMPTION_ONLY"
UNSAFE = "UNSAFE"


# ── atomic JSON write (repo rule #4) ──────────────────────────────────────────────────────────
def _atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.stem + "_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
        shutil.move(tmp, str(path))  # atomic, cross-device safe (repo rule #4)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ── verdict classification (deterministic, fail-CLOSED) ───────────────────────────────────────
def classify(res: LiquidationNAVResult) -> str:
    """Map a measured LiquidationNAVResult to LIQUID / THIN / REDEMPTION_ONLY / UNSAFE.

    Logic:
      - on-chain present & deep at the $1M reference → LIQUID
      - on-chain present (clears $100k) but not deep at $1M → THIN
      - no usable on-chain exit but a documented redemption right → REDEMPTION_ONLY
      - neither → UNSAFE (fail-closed)
    'on-chain present' means a qualifying public DEX pool was found AND it realises ≥
    THIN_MIN_SMALL_FRAC of NAV at $100k."""
    small = res.sized.get(SMALL_SIZE_USD)
    ref = res.sized.get(REFERENCE_SIZE_USD)

    on_chain_small = small.on_chain_value_frac if small else None
    on_chain_ref = ref.on_chain_value_frac if ref else None

    has_usable_on_chain = (
        res.n_dex_pools > 0
        and on_chain_small is not None
        and on_chain_small >= THIN_MIN_SMALL_FRAC
    )

    if has_usable_on_chain:
        if on_chain_ref is not None and on_chain_ref >= ON_CHAIN_LIQUID_THRESHOLD:
            return LIQUID
        return THIN

    # no usable public on-chain exit → can we at least redeem?
    if res.redemption_documented:
        return REDEMPTION_ONLY
    return UNSAFE


def _exit_capacity_72h_usd(res: LiquidationNAVResult) -> float:
    """Estimated USD that could be exited on-chain within 72h without unbounded impact. 0 for a
    token with no public DEX exit (the permissioned case)."""
    if res.transfer_restricted or res.n_dex_pools == 0:
        return 0.0
    return round(res.on_chain_dex_tvl_usd * EXIT_CAPACITY_72H_FRAC_OF_TVL, 2)


def _asset_record(res: LiquidationNAVResult) -> dict:
    """One Safety-Board row."""
    verdict = classify(res)
    liq_100k = res.liq_nav_frac(SMALL_SIZE_USD)
    liq_1m = res.liq_nav_frac(REFERENCE_SIZE_USD)
    liq_10m = res.liq_nav_frac(10_000_000.0)
    nav = res.marketing_nav_usd

    def usd(frac: Optional[float]) -> Optional[float]:
        return None if frac is None else round(frac * nav, 6)

    # marketing-vs-liq gap at the $1M reference (the headline thesis number).
    gap_pct_1m = None if liq_1m is None else round((1.0 - liq_1m) * 100.0, 4)

    return {
        "symbol": res.symbol,
        "issuer": res.issuer,
        "verdict": verdict,
        "marketing_nav_usd": round(nav, 6),
        "liq_nav_usd_100k": usd(liq_100k),
        "liq_nav_usd_1m": usd(liq_1m),
        "liq_nav_usd_10m": usd(liq_10m),
        "liq_nav_frac_100k": liq_100k,
        "liq_nav_frac_1m": liq_1m,
        "liq_nav_frac_10m": liq_10m,
        "marketing_vs_liq_gap_pct_1m": gap_pct_1m,
        "on_chain_dex_liquidity_usd": res.on_chain_dex_tvl_usd,
        "n_dex_pools": res.n_dex_pools,
        "exit_capacity_72h_usd": _exit_capacity_72h_usd(res),
        "transfer_restricted": res.transfer_restricted,
        "redemption_documented": res.redemption_documented,
        "redemption_delay_days": res.redemption_delay_days,
        "redemption_fee_bps": res.redemption_fee_bps,
        "binding_leg_1m": (res.sized.get(REFERENCE_SIZE_USD).binding_leg
                           if res.sized.get(REFERENCE_SIZE_USD) else "none"),
        "data_gaps": res.data_gaps,
    }


# ── report ────────────────────────────────────────────────────────────────────────────────────
def build_report(
    write: bool = True,
    fetcher: Optional[Fetcher] = None,
    out_path: Optional[Path] = None,
    assets=None,
) -> dict:
    """Measure the whole RWA collateral universe and produce the Safety Board.

    Args:
        write:   write data/rwa_safety_board.json atomically when True (default).
        fetcher: inject a url->json fetcher (tests/hermetic). None → keyless DeFiLlama /pools.
        out_path: override output path (tests).
        assets:  override the asset list (tests). None → the full collateral_registry.

    Returns the report dict. Deterministic + FAIL-CLOSED. RESEARCH / ADVISORY only."""
    asset_list = list(assets) if assets is not None else reg.registry()
    engine = LiquidationNAVEngine(fetcher=fetcher)
    results = engine.measure_universe(asset_list)

    rows = [_asset_record(r) for r in results]
    rows.sort(key=lambda r: r["symbol"])

    verdict_counts: Dict[str, int] = {LIQUID: 0, THIN: 0, REDEMPTION_ONLY: 0, UNSAFE: 0}
    gaps_list = []
    for row in rows:
        verdict_counts[row["verdict"]] = verdict_counts.get(row["verdict"], 0) + 1
        if row["marketing_vs_liq_gap_pct_1m"] is not None:
            gaps_list.append(row["marketing_vs_liq_gap_pct_1m"])

    universe = reg.universe_summary()
    # headline: how much of the universe is NOT cash-like on an executable on-chain exit.
    not_cash_like = verdict_counts[REDEMPTION_ONLY] + verdict_counts[UNSAFE] + verdict_counts[THIN]

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "rwa_backstop_liquidation_nav",
        "thesis": "SPA-RRB: lend against Liquidation NAV, not marketing NAV",
        "llm_forbidden": True,
        "advisory": True,           # research only — never lends/trades/touches go-live
        "research_only": True,
        "reference_size_usd": REFERENCE_SIZE_USD,
        "sizes_usd": [SMALL_SIZE_USD, REFERENCE_SIZE_USD, 10_000_000.0],
        "universe_summary": universe,
        "verdict_counts": verdict_counts,
        "n_not_cash_like": not_cash_like,
        "n_assets": len(rows),
        "max_marketing_vs_liq_gap_pct_1m": round(max(gaps_list), 4) if gaps_list else None,
        "thesis_confirmed": not_cash_like >= max(1, len(rows) // 2),
        "data_caveats": [
            "ON-CHAIN DEX leg is MEASURABLE read-only (DeFiLlama /pools depth + slippage model).",
            "REDEMPTION leg is DOCUMENTED-ONLY: actual settlement is whitelist/subscription-gated "
            "(relationship + legal access we do not have read-only). Encoded as a transparent "
            "documented assumption, not a measured exit.",
            "RFQ / OTC desk depth for permissioned RWA is NOT observable read-only.",
            "Transfer-restricted tokens have on-chain exit = 0 by construction (whitelist).",
            "Slippage uses a conservative constant-product depth proxy from aggregate DEX TVL.",
        ],
        "assets": rows,
    }

    if write:
        _atomic_write_json(Path(out_path) if out_path else DEFAULT_OUT, report)
    return report


# ── CLI ────────────────────────────────────────────────────────────────────────────────────────
def _print_board(report: dict) -> None:
    print("RWA Collateral Safety Board (RESEARCH / ADVISORY)  —  SPA-RRB de-risk")
    print(f"  thesis: {report['thesis']}")
    vc = report["verdict_counts"]
    print(f"  LIQUID={vc['LIQUID']}  THIN={vc['THIN']}  "
          f"REDEMPTION_ONLY={vc['REDEMPTION_ONLY']}  UNSAFE={vc['UNSAFE']}   "
          f"(not-cash-like: {report['n_not_cash_like']}/{report['n_assets']})")
    print(f"  thesis_confirmed (majority NOT cash-like on executable exit): {report['thesis_confirmed']}")
    print()
    hdr = (f"{'symbol':8s} {'verdict':16s} {'liqNAV$1M':>10s} {'gap%':>7s} "
           f"{'dexTVL$':>14s} {'pools':>5s} {'redeem':>7s}  issuer")
    print(hdr)
    print("-" * (len(hdr) + 12))
    for a in report["assets"]:
        ln = a["liq_nav_usd_1m"]
        ln_s = f"{ln:10.4f}" if isinstance(ln, (int, float)) else f"{'—':>10s}"
        gap = a["marketing_vs_liq_gap_pct_1m"]
        gap_s = f"{gap:7.2f}" if isinstance(gap, (int, float)) else f"{'—':>7s}"
        rd = f"T+{a['redemption_delay_days']:g}" if a["redemption_documented"] else "none"
        print(f"{a['symbol']:8s} {a['verdict']:16s} {ln_s} {gap_s} "
              f"{a['on_chain_dex_liquidity_usd']:14,.0f} {a['n_dex_pools']:5d} {rd:>7s}  {a['issuer']}")


def main() -> int:
    import socket
    socket.setdefaulttimeout(25)
    report = build_report(write=True)
    _print_board(report)
    print(f"\nWrote {DEFAULT_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
