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
from spa_core.strategy_lab.rwa_backstop.onchain_nav import (
    OnchainNAV,
    OnchainNAVReader,
    NAV_SOURCE_ONCHAIN,
    NAV_SOURCE_ESTIMATE,
    RpcFetcher,
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


def _asset_record(res: LiquidationNAVResult, onchain: Optional[OnchainNAV] = None) -> dict:
    """One Safety-Board row.

    `onchain` (when present and nav_source=onchain_4626) supplies the REAL intrinsic NAV/share read
    on-chain via keyless eth_call — a more authoritative redemption-value anchor than the uniform
    $1.00 marketing assumption. We still report liq_nav as a FRACTION of the marketing NAV (the
    thesis gap is measured vs marketing), but we surface the on-chain NAV + its divergence from the
    $1.00 marketing assumption as an additive risk signal. Fail-CLOSED: no on-chain read →
    nav_source=off_chain_estimate and the marketing value stands."""
    verdict = classify(res)
    liq_100k = res.liq_nav_frac(SMALL_SIZE_USD)
    liq_1m = res.liq_nav_frac(REFERENCE_SIZE_USD)
    liq_10m = res.liq_nav_frac(10_000_000.0)
    nav = res.marketing_nav_usd

    def usd(frac: Optional[float]) -> Optional[float]:
        return None if frac is None else round(frac * nav, 6)

    # marketing-vs-liq gap at the $1M reference (the headline thesis number).
    gap_pct_1m = None if liq_1m is None else round((1.0 - liq_1m) * 100.0, 4)

    # On-chain intrinsic-NAV layer (additive). nav_source flags whether we got a REAL read.
    if onchain is not None and onchain.nav_source == NAV_SOURCE_ONCHAIN \
            and onchain.onchain_nav_usd is not None:
        nav_source = NAV_SOURCE_ONCHAIN
        onchain_nav_usd = onchain.onchain_nav_usd
        # divergence of the REAL intrinsic NAV from the $1.00 marketing assumption (a risk signal).
        onchain_nav_divergence_pct = round((onchain_nav_usd - nav) / nav * 100.0, 6) if nav else None
        onchain_rpc = onchain.rpc_endpoint
    else:
        nav_source = NAV_SOURCE_ESTIMATE
        onchain_nav_usd = None
        onchain_nav_divergence_pct = None
        onchain_rpc = onchain.rpc_endpoint if onchain is not None else None

    return {
        "symbol": res.symbol,
        "issuer": res.issuer,
        "verdict": verdict,
        "marketing_nav_usd": round(nav, 6),
        "nav_source": nav_source,
        "onchain_nav_usd": onchain_nav_usd,
        "onchain_nav_divergence_pct": onchain_nav_divergence_pct,
        "onchain_rpc_endpoint": onchain_rpc,
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
    onchain: bool = True,
    rpc_fetcher: Optional[RpcFetcher] = None,
) -> dict:
    """Measure the whole RWA collateral universe and produce the Safety Board.

    Args:
        write:    write data/rwa_safety_board.json atomically when True (default).
        fetcher:  inject a url->json fetcher (tests/hermetic). None → keyless DeFiLlama /pools.
        out_path: override output path (tests).
        assets:   override the asset list (tests). None → the full collateral_registry.
        onchain:  attempt REAL on-chain intrinsic-NAV reads via keyless JSON-RPC eth_call (default
                  True). Fail-CLOSED: any RPC failure / non-4626 token → off_chain_estimate, the
                  board still produces every row on its estimate.
        rpc_fetcher: inject a (url, payload)->json JSON-RPC fetcher (tests/hermetic). None → the
                  keyless public mainnet RPC probe.

    Returns the report dict. Deterministic + FAIL-CLOSED. RESEARCH / ADVISORY only."""
    asset_list = list(assets) if assets is not None else reg.registry()
    engine = LiquidationNAVEngine(fetcher=fetcher)
    results = engine.measure_universe(asset_list)

    # On-chain intrinsic-NAV layer (additive, fail-CLOSED). One endpoint probe for the whole run.
    onchain_by_symbol: Dict[str, OnchainNAV] = {}
    if onchain:
        reader = OnchainNAVReader(rpc_fetcher=rpc_fetcher)
        try:
            onchain_by_symbol = reader.read_universe(asset_list)
        except Exception:  # noqa: BLE001 — fail-CLOSED: any reader failure → estimate everywhere
            onchain_by_symbol = {}

    rows = [_asset_record(r, onchain_by_symbol.get(r.symbol.upper())) for r in results]
    rows.sort(key=lambda r: r["symbol"])

    verdict_counts: Dict[str, int] = {LIQUID: 0, THIN: 0, REDEMPTION_ONLY: 0, UNSAFE: 0}
    gaps_list = []
    n_onchain_nav = 0
    n_estimate_nav = 0
    nav_divergences = []  # (symbol, divergence_pct) for assets with a REAL on-chain NAV
    assets_onchain = []   # symbols whose intrinsic NAV is read on-chain (real ERC-4626 coverage)
    for row in rows:
        verdict_counts[row["verdict"]] = verdict_counts.get(row["verdict"], 0) + 1
        if row["marketing_vs_liq_gap_pct_1m"] is not None:
            gaps_list.append(row["marketing_vs_liq_gap_pct_1m"])
        if row["nav_source"] == NAV_SOURCE_ONCHAIN:
            n_onchain_nav += 1
            assets_onchain.append(row["symbol"])
            if row["onchain_nav_divergence_pct"] is not None:
                nav_divergences.append((row["symbol"], row["onchain_nav_divergence_pct"]))
        else:
            n_estimate_nav += 1

    universe = reg.universe_summary()
    # headline: how much of the universe is NOT cash-like on an executable on-chain exit.
    not_cash_like = verdict_counts[REDEMPTION_ONLY] + verdict_counts[UNSAFE] + verdict_counts[THIN]
    # max absolute on-chain-vs-marketing NAV divergence (a real intrinsic-value risk signal).
    max_abs_div = (round(max(abs(d) for _, d in nav_divergences), 6)
                   if nav_divergences else None)

    # Transparent on-chain-NAV coverage note: how many assets have a REAL keyless-eth_call ERC-4626
    # intrinsic NAV vs how many fall back to an off-chain estimate. Partial/zero coverage is the
    # HONEST point — the permissioned RWA tokens' NAV is simply not on-chain-verifiable.
    total_cov = n_onchain_nav + n_estimate_nav
    if not onchain:
        coverage_note = ("on-chain intrinsic-NAV reads disabled for this run → all assets on "
                         "off-chain estimate.")
    elif n_onchain_nav == 0:
        coverage_note = (
            f"0/{total_cov} assets have a real on-chain ERC-4626 intrinsic NAV. The RWA "
            f"collateral universe is structurally permissioned/non-4626 (BUIDL, USYC, OUSG, "
            f"BENJI, VBILL…): their tokens do NOT expose totalAssets/convertToAssets, so their "
            f"NAV is not on-chain-verifiable → off-chain estimate. That non-verifiability is "
            f"itself the finding."
        )
    else:
        onchain_list = ", ".join(assets_onchain)
        coverage_note = (
            f"{n_onchain_nav}/{total_cov} assets have a REAL on-chain ERC-4626 intrinsic NAV via "
            f"keyless eth_call ({onchain_list}); the remaining {n_estimate_nav} are permissioned/"
            f"non-4626 tokens whose NAV is NOT on-chain-verifiable → off-chain estimate. Partial "
            f"coverage is the honest, transparent result — not a gap to hide."
        )

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
        "onchain_nav_coverage": {
            "enabled": bool(onchain),
            # canonical transparency block (task T6): N real on-chain ERC-4626 / M off-chain estimate.
            "onchain_4626": n_onchain_nav,
            "off_chain_estimate": n_estimate_nav,
            "total": total_cov,
            "assets_onchain": list(assets_onchain),
            "note": coverage_note,
            # legacy aliases kept for back-compat with existing consumers/tests.
            "n_onchain_4626": n_onchain_nav,
            "n_off_chain_estimate": n_estimate_nav,
            "rpc_endpoint": next((o.rpc_endpoint for o in onchain_by_symbol.values()
                                  if o.rpc_endpoint), None),
            "max_abs_nav_divergence_pct": max_abs_div,
            "divergences": sorted(
                [{"symbol": s, "onchain_vs_marketing_nav_divergence_pct": d}
                 for s, d in nav_divergences],
                key=lambda r: -abs(r["onchain_vs_marketing_nav_divergence_pct"]),
            ),
        },
        "data_caveats": [
            "ON-CHAIN INTRINSIC NAV (where shown, nav_source=onchain_4626) is a REAL keyless "
            "eth_call read of totalAssets/totalSupply or convertToAssets — the most authoritative "
            "redemption-value anchor. Most tokenized-RWA tokens are permissioned/non-4626 and do "
            "NOT expose it → nav_source=off_chain_estimate (marketing/$1.00 assumption stands). "
            "Partial on-chain coverage is the HONEST result, not a bug.",
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
    cov = report.get("onchain_nav_coverage", {})
    print(f"  on-chain intrinsic NAV coverage: {cov.get('onchain_4626', 0)} REAL (eth_call) / "
          f"{cov.get('total', 0)} total   "
          f"(RPC: {cov.get('rpc_endpoint') or 'none responded → all estimate'})")
    if cov.get("assets_onchain"):
        print(f"    on-chain assets: {', '.join(cov['assets_onchain'])}")
    if cov.get("note"):
        print(f"    note: {cov['note']}")
    if cov.get("divergences"):
        for dv in cov["divergences"]:
            print(f"    ! {dv['symbol']}: on-chain NAV diverges "
                  f"{dv['onchain_vs_marketing_nav_divergence_pct']:+.4f}% from $1.00 marketing")
    print()
    hdr = (f"{'symbol':8s} {'verdict':16s} {'liqNAV$1M':>10s} {'gap%':>7s} "
           f"{'navSrc':>16s} {'onchNAV':>9s} {'dexTVL$':>14s} {'pools':>5s} {'redeem':>7s}  issuer")
    print(hdr)
    print("-" * (len(hdr) + 12))
    for a in report["assets"]:
        ln = a["liq_nav_usd_1m"]
        ln_s = f"{ln:10.4f}" if isinstance(ln, (int, float)) else f"{'—':>10s}"
        gap = a["marketing_vs_liq_gap_pct_1m"]
        gap_s = f"{gap:7.2f}" if isinstance(gap, (int, float)) else f"{'—':>7s}"
        onav = a.get("onchain_nav_usd")
        onav_s = f"{onav:9.5f}" if isinstance(onav, (int, float)) else f"{'—':>9s}"
        rd = f"T+{a['redemption_delay_days']:g}" if a["redemption_documented"] else "none"
        print(f"{a['symbol']:8s} {a['verdict']:16s} {ln_s} {gap_s} "
              f"{a.get('nav_source', '?'):>16s} {onav_s} "
              f"{a['on_chain_dex_liquidity_usd']:14,.0f} {a['n_dex_pools']:5d} {rd:>7s}  {a['issuer']}")


def main() -> int:
    import socket
    socket.setdefaulttimeout(25)
    report = build_report(write=True)
    _print_board(report)
    print(f"\nWrote {DEFAULT_OUT}")

    # FORWARD RECORD: the daily agent also accrues ONE measured-NAV point per UTC day so the RWA
    # thesis has an evidenced forward series (data/rwa_nav_curve.json), parallel to the rates-desk
    # paper track. Idempotent per day, fail-CLOSED, atomic. Never crashes the board run.
    try:
        from spa_core.strategy_lab.rwa_backstop import nav_curve
        doc = nav_curve.record_forward_point(report)
        if doc is not None:
            print(f"Appended forward point {doc['latest']['date']} "
                  f"(n_points={doc['n_points']}) → {nav_curve.DEFAULT_CURVE_PATH}")
        else:
            print("Forward point SKIPPED (no usable measurement — fail-closed)")
    except Exception as exc:  # noqa: BLE001 — forward record must never break the safety board
        print(f"Forward-record append failed (board still written): {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
