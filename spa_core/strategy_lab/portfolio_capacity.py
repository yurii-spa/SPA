"""
spa_core/strategy_lab/portfolio_capacity.py — the COMBINED multi-sleeve portfolio-capacity model.

The single fundability question the rates desk could NOT answer on its own. capacity.py proved one
FixedCarry book caps out ~$250k; portfolio.py summed the whole rates-desk universe to ~$330k deployable /
~$65k/yr above the RWA floor. Both verdicts are honest but PARTIAL — the rates desk is only ONE of three
sleeve families SPA can run. The allocator's real question for fundability is the COMBINED book:

    "Forget one desk. Sum the WHOLE deployable book SPA can actually run today — the rates-desk carry
     PLUS the deep tokenized-T-bill RWA floor PLUS the stable engines — net of the fact that some of these
     share exit liquidity / venues (so their depth is NOT fully additive). How much does the combined real-
     market book absorb, what does it earn ABOVE the floor, and how close does THAT get to $10M/yr — and
     what is the BINDING constraint (rates-desk depth, RWA-yield-too-low, or correlation)?"

This module aggregates capacity across the THREE sleeve families and applies a CORRELATION HAIRCUT where
sleeves share exit-liquidity / venues, then states the honest $10M/yr verdict and the binding constraint.

THE THREE FAMILIES
══════════════════
  (1) RATES DESK — the PT-carry portfolio of gated books. We REUSE rates_desk.portfolio.build_report()
      verbatim (its per-book §9 exit-capacity sizing, idle-cash@floor, maturity-retire accounting). Its
      total_deployable_usd / aggregate_net_apy_pct / dollars_above_floor_per_yr ARE this family's numbers.
      Above-floor but THIN (~$330k deployable, ~$65k/yr above floor at today's depth).

  (2) RWA STABLE FLOOR — the realized tokenized-T-bill cash floor (RwaSleeve / rwa_feed). A DEEP market
      (~$15B tokenized T-bills, ~$6B in the qualifying issuer pools above the $5M TVL floor) but it yields
      AT the floor by construction — it banks the floor, it does not beat it. So its deployable is large
      but its ABOVE-floor contribution is ~0. The depth we credit is bounded by an underwriter's honest
      capacity to absorb a fraction of the qualifying-pool TVL (RWA_DEPTH_FRAC_OF_TVL) — not the whole
      $15B, which no single book could deploy/exit. This is the BASE-yield engine: it scales, but only at
      the floor (its above-floor value comes from REAL AUM banking the floor, not from an edge).

  (3) STABLE ENGINES — the production Engine A (stable base book), Engine B (HY/carry), Engine C (LP),
      each at its configured capacity (config strategy blocks). Bounded, modest above-floor (engine_a sits
      ~at the floor; engine_b/engine_c clip a HY/LP spread over their small books). The real, already-
      running stable book — small but above floor.

CORRELATION HAIRCUT (the honest non-additivity)
═══════════════════════════════════════════════
Naively summing the three families OVERSTATES the combined depth: the rates-desk PT carry and the RWA
floor BOTH exit through stablecoin venues (USDe/USDC pools, the same redemption/AMM rails). In a forced
unwind they compete for the SAME exit liquidity — they are not independent books. So we DO NOT just add
them. We apply a correlation haircut to the OVERLAPPING (shared-venue) deployable: the smaller of the two
correlated families' deployable is haircut by CORRELATION_HAIRCUT_FRAC (the part that, under stress,
cannot be assumed to exit alongside the other without doubling impact). The stable engines (Engine A/B/C)
run on distinct lending/LP venues and are treated as independent (no haircut). The haircut is conservative
and EXPLICIT — combined_deployable = naive_sum − haircut, and the report records both so the reduction is
auditable. This is the missing realism: real desks share rails, so the combined book is LESS than the sum.

THE HONEST $10M VERDICT (never inflated)
════════════════════════════════════════
The combined above-floor $/yr is dominated by the rates carry (the RWA floor and engine_a contribute ~0
above floor by construction; the RWA family's value is BASE yield AT the floor, which only becomes real
above-floor dollars if you run real AUM). So the combined book is STILL well short of $10M/yr above floor
at today's market depth — the model SAYS THAT, and names the BINDING CONSTRAINT:
  - RATES_DESK_DEPTH  — the above-floor edge is real but lives in thin PT pools (rates family is the only
                        meaningful above-floor source, and it caps at ~$65k/yr today).
  - RWA_YIELD_TOO_LOW — the deep family (RWA) yields at the floor, so its huge depth adds ~$0 above floor.
  - CORRELATION       — shared-venue exit liquidity caps how much of the deep + carry books can be summed.
What would CLOSE it: deeper PT markets (more per-book carry depth), MORE venues/chains (decorrelate the
exit rails → smaller haircut, more additive depth), and REAL AUM at the floor (the RWA base yield only
becomes above-floor dollars at scale once a spread over the floor is captured / real capital is deployed).

CONVENTIONS (inherited, enforced): stdlib only; deterministic — no RNG, sorted iteration, Decimal-exact
arithmetic on the aggregates; PURE — no wall-clock in the numbers (timestamps are metadata only); fail-
CLOSED — a missing rates-desk deep dataset / an unreadable config RAISES rather than fabricating a benign
combined book; atomic writes (tmp + shutil.move via rates_desk._io, repo rule #4); LLM-FORBIDDEN. Advisory
/ research — never touches the live track.

Run (offline, on the cached data):
    python3 -m spa_core.strategy_lab.portfolio_capacity
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from spa_core.strategy_lab import config as lab_config
from spa_core.strategy_lab.rates_desk import _io
from spa_core.strategy_lab.rates_desk import portfolio as rates_portfolio

_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
_OUT = _ROOT / "data" / "strategy_lab" / "portfolio_capacity.json"
_DOC = _ROOT / "docs" / "STRUCTURAL_DESK.md"

# Idempotent doc markers so the combined-capacity section can be (re)written into the Structural Desk
# overview without clobbering the surrounding narrative.
_DOC_BEGIN = "<!-- BEGIN combined portfolio-capacity (portfolio_capacity) -->"
_DOC_END = "<!-- END combined portfolio-capacity (portfolio_capacity) -->"

# The fundability target the whole exercise sizes against — $10M/yr of yield ABOVE the RWA floor.
TARGET_ABOVE_FLOOR_PER_YR = Decimal("10000000")  # $10,000,000/yr above floor

# RWA family depth credit: the fraction of the qualifying tokenized-T-bill issuer-pool TVL an underwriter
# can HONESTLY assume it could deploy into / exit out of as ONE book without unbounded impact. The market
# is ~$15B (~$6B in pools above the $5M TVL floor), but no single book deploys the whole market — we credit
# a conservative slice. Held separate / pinned; widening is a research change. (This is the DEEP-but-low-
# yield family: its above-floor contribution is ~0 regardless of the credited depth, because it yields AT
# the floor — the depth matters for the "base-yield engine" framing, not for the above-floor number.)
RWA_DEPTH_FRAC_OF_TVL = Decimal("0.10")  # 10% of qualifying issuer-pool TVL as one-book deployable

# Conservative fallback for the qualifying tokenized-T-bill pool TVL when the live rwa_feed cache is
# unavailable (network down / no cache). The qualifying issuer pools (BUIDL/USYC/USDY/OUSG/USTB/…) hold
# ~$6B above the $5M floor per the live feed; we fall back to a deliberately conservative literal so a
# deterministic offline run never crashes and never inflates the depth.
RWA_FALLBACK_QUALIFYING_TVL_USD = Decimal("6000000000")  # ~$6B qualifying-pool TVL (conservative)

# Correlation haircut: the fraction of the OVERLAPPING (shared-venue) deployable that, under a forced
# unwind, cannot be assumed to exit alongside the other correlated family without doubling exit impact.
# The rates-desk PT carry and the RWA floor BOTH redeem through stablecoin venues → correlated. We haircut
# the SMALLER of the two correlated families' deployable by this fraction (conservative: the constrained
# leg is the binding one). The stable engines run on distinct venues → not haircut. Pinned; auditable.
CORRELATION_HAIRCUT_FRAC = Decimal("0.50")  # 50% of the shared-venue overlap is non-additive under stress

# Binding-constraint labels (the honest verdict's single root cause).
BINDING_RATES_DEPTH = "RATES_DESK_DEPTH"
BINDING_RWA_YIELD = "RWA_YIELD_TOO_LOW"
BINDING_CORRELATION = "CORRELATION"

# Which families share exit-liquidity / venues (→ subject to the correlation haircut). The stable engines
# are deliberately NOT here (distinct lending/LP venues).
_SHARED_VENUE_FAMILIES = ("rates_desk", "rwa_floor")


def _atomic_write_json(path: Path, obj) -> None:
    _io.atomic_write_json(path, obj, indent=1)


def _fmt_usd(x) -> str:
    if x is None:
        return "—"
    return f"${float(x):,.0f}"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# per-family capacity rows
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _family_row(name: str, deployable_usd: Decimal, net_apy_pct: Decimal, floor_pct: Decimal,
                shares_venue: bool, books_or_venues, note: str,
                above_floor_override: Optional[Decimal] = None) -> dict:
    """One family capacity row. above_floor_usd_per_yr = deployable · max(0, net_apy − floor)/100, UNLESS
    `above_floor_override` is given (a family that publishes its OWN exact above-floor $/yr — e.g. the
    rates desk's Σ per-book carry — passes it through verbatim so the combined report is byte-consistent
    with the family's own report, not a re-derivation off rounded deployable/APY)."""
    if above_floor_override is not None:
        above = above_floor_override
    else:
        above = deployable_usd * max(Decimal("0"), net_apy_pct - floor_pct) / Decimal("100")
    return {
        "family": name,
        "deployable_usd": round(float(deployable_usd), 2),
        "net_apy_pct": round(float(net_apy_pct), 4),
        "above_floor_usd_per_yr": round(float(above), 2),
        "shares_exit_venue": bool(shares_venue),
        "books_or_venues": books_or_venues,
        "note": note,
    }


def _rates_desk_family(floor_pct: Decimal, rates_report: dict) -> dict:
    """Family (1): reuse the rates-desk portfolio-of-desks aggregate verbatim. Above-floor but thin."""
    deployable = Decimal(str(rates_report["total_deployable_usd"]))
    net_apy = Decimal(str(rates_report["aggregate_net_apy_pct"]))
    n_books = int(rates_report.get("n_fundable_books", 0))
    # use the rates-desk report's OWN exact Σ-per-book above-floor $/yr (the source of truth) so the
    # combined report's rates-desk row is consistent with the standalone rates-desk number, not a
    # re-derivation off the rounded deployable × (net_apy − floor) that drifts by a few dollars.
    above_override = None
    if rates_report.get("dollars_above_floor_per_yr") is not None:
        above_override = Decimal(str(rates_report["dollars_above_floor_per_yr"]))
    note = (f"PT-carry portfolio of {n_books} gated books (reused rates_desk.portfolio verbatim). "
            "Above-floor but capacity-limited: the §9 exit cap binds each book to a thin depth-bound size.")
    return _family_row("rates_desk", deployable, net_apy, floor_pct,
                       shares_venue=True, books_or_venues=n_books, note=note,
                       above_floor_override=above_override)


def _rwa_floor_family(floor_pct: Decimal) -> dict:
    """Family (2): the deep tokenized-T-bill RWA cash floor. Deep depth, yields AT the floor → ~0 above."""
    qualifying_tvl, src = _qualifying_rwa_tvl_usd()
    deployable = (qualifying_tvl * RWA_DEPTH_FRAC_OF_TVL).quantize(Decimal("0.01"))
    # The RWA sleeve banks the floor by construction → net_apy == floor (the realized floor, no spread).
    net_apy = floor_pct
    note = (f"Realized tokenized-T-bill cash floor (~$15B market; {_fmt_usd(qualifying_tvl)} qualifying "
            f"issuer-pool TVL via {src}). Credited depth = {RWA_DEPTH_FRAC_OF_TVL * 100:.0f}% of that TVL "
            "as one-book deployable. DEEP but yields AT the floor → ~$0 ABOVE floor: this is the BASE-yield "
            "engine, it banks the floor, it does not beat it.")
    return _family_row("rwa_floor", deployable, net_apy, floor_pct,
                       shares_venue=True, books_or_venues="tokenized_t_bill_issuer_pools", note=note)


def _stable_engines_family(floor_pct: Decimal) -> dict:
    """Family (3): the production stable engines A/B/C at configured capacity, deployable-weighted APY.

    Engine A sits ~at the floor (stable base book); Engine B/C clip a HY/LP spread over their small books.
    Deployable = Σ configured capital; net_apy = capital-weighted blend of each engine's representative
    APY. The HY/LP rates are read from the SAME producers the baselines use (sleeve_yield), fail-closed to
    their floors — so this matches what the real engines earn, never a fabricated rate."""
    from spa_core.paper_trading import sleeve_yield

    cfg = lab_config.load_config()
    blocks = cfg.get("strategies", {})

    def _cap(eid: str) -> Decimal:
        b = blocks.get(eid) or {}
        return Decimal(str(b.get("capital_usd", 0) or 0))

    cap_a, cap_b, cap_c = _cap("engine_a"), _cap("engine_b"), _cap("engine_c")

    # Engine A: stable base book → the floor (offline-safe; the live blended stable APY is the floor here).
    apy_a = floor_pct
    # Engine B (HY) / Engine C (LP): reuse the real producers; fail-closed to their floors.
    try:
        apy_b = Decimal(str(sleeve_yield.hy_target_apy_pct()))
    except Exception:  # noqa: BLE001 — fail-closed to the documented HY floor
        apy_b = Decimal(str(getattr(sleeve_yield, "HY_FLOOR", 6.0)))
    try:
        apy_c = Decimal(str(sleeve_yield.lp_target_apy_pct()))
    except Exception:  # noqa: BLE001 — fail-closed to the documented LP floor
        apy_c = Decimal(str(getattr(sleeve_yield, "LP_FLOOR", 5.0)))

    deployable = cap_a + cap_b + cap_c
    if deployable > 0:
        net_apy = (cap_a * apy_a + cap_b * apy_b + cap_c * apy_c) / deployable
    else:
        net_apy = floor_pct
    note = (f"Production stable engines: Engine A {_fmt_usd(cap_a)} @ ~floor (stable base book), "
            f"Engine B {_fmt_usd(cap_b)} @ {float(apy_b):.2f}% (HY/carry), "
            f"Engine C {_fmt_usd(cap_c)} @ {float(apy_c):.2f}% (LP). Already-running, distinct venues, "
            "modest above-floor on small books.")
    return _family_row("stable_engines", deployable, net_apy, floor_pct,
                       shares_venue=False, books_or_venues="engine_a,engine_b,engine_c", note=note)


def _surface_provenance() -> dict:
    """Deterministic provenance of the EXPANDED rate-surface coverage (C1) the desk follows: the count
    of lending-venue selectors, the distinct lending protocols/chains/quote-stables, and the PT
    underlying universe. Pure (reads pinned config + the static target set; no network). This is an
    audit trail for the honesty pass — it never feeds the above-floor arithmetic."""
    from spa_core.strategy_lab.rates_desk import config as rd_config
    from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph

    lending = rd_config.LENDING_TARGETS
    protocols = sorted({str(s["project"]) for s in lending})
    chains = sorted({str(s["chain"]) for s in lending})
    quote_stables = sorted({str(s["underlying"]).lower() for s in lending})
    # PT underlyings the LIVE surface can match = the validated history TARGETS ∪ the config-extended
    # clean stable/LST underlyings (feeds._match_pendle_underlying_extended), EXCLUDING the toxic LRTs
    # (which are matched but never harvested — they exist to confirm refusal).
    pt_targets = {k.lower() for k in pph.TARGETS}
    config_underlyings = {u for u, kind in rd_config.UNDERLYING_KINDS.items() if kind != "lrt"}
    pt_underlyings = sorted(pt_targets | config_underlyings)
    toxic_lrts = sorted({u for u, kind in rd_config.UNDERLYING_KINDS.items() if kind == "lrt"})
    return {
        "lending_venue_selectors": len(lending),
        "lending_protocols": protocols,
        "lending_chains": chains,
        "lending_quote_stables": quote_stables,
        "pt_underlyings_matchable": pt_underlyings,
        "n_pt_underlyings_matchable": len(pt_underlyings),
        "toxic_lrts_refusal_only": toxic_lrts,
        "note": ("Expanded live surface coverage (C1). Widening venues/underlyings adds DECORRELATION "
                 "POTENTIAL (more independent exit rails → a smaller correlation haircut at scale), NOT "
                 "above-floor edge today: the above-floor number is bound by deep PT-carry depth + the "
                 "at-floor RWA family. Audit trail only — never an input to the above-floor arithmetic."),
    }


def _qualifying_rwa_tvl_usd() -> tuple:
    """The qualifying tokenized-T-bill issuer-pool TVL (USD) + a short source label. Prefers the LIVE
    rwa_feed cache (total_tvl_usd across the qualifying issuer pools above the $5M floor); fail-CLOSED
    to the conservative committed literal when the feed/cache is unavailable. Never fabricates / inflates."""
    try:
        from spa_core.strategy_lab.data.rwa_feed import RWAFeed
        cached = RWAFeed().cached()
        if isinstance(cached, dict):
            tvl = cached.get("total_tvl_usd")
            if isinstance(tvl, (int, float)) and tvl > 0:
                return Decimal(str(tvl)), "live rwa_feed cache"
    except Exception:  # noqa: BLE001 — feed import/read failure → conservative literal
        pass
    return RWA_FALLBACK_QUALIFYING_TVL_USD, "conservative committed literal (feed unavailable)"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# correlation haircut
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _correlation_haircut_usd(families: List[dict]) -> Decimal:
    """The non-additive deployable removed for shared exit-liquidity / venues.

    The rates-desk PT carry and the RWA floor both redeem through stablecoin venues → correlated. Under a
    forced unwind they compete for the SAME exit liquidity, so the SMALLER of the two correlated families'
    deployable cannot be fully summed alongside the other. We haircut CORRELATION_HAIRCUT_FRAC of that
    smaller (constrained/binding) leg. Distinct-venue families (the stable engines) are not haircut.
    Returns the USD removed from the naive sum (≥ 0)."""
    shared = [f for f in families if f["family"] in _SHARED_VENUE_FAMILIES and f.get("shares_exit_venue")]
    if len(shared) < 2:
        return Decimal("0")
    deployables = sorted(Decimal(str(f["deployable_usd"])) for f in shared)
    overlap = deployables[0]  # the smaller (binding) correlated leg
    return (overlap * CORRELATION_HAIRCUT_FRAC).quantize(Decimal("0.01"))


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# build_report — the combined multi-sleeve capacity
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def build_report(
    write: bool = True,
    rates_report: Optional[dict] = None,
    floor_pct: Optional[float] = None,
    out_path: Optional[Path] = None,
) -> dict:
    """Build the deterministic COMBINED multi-sleeve portfolio-capacity report and (optionally) write
    data/strategy_lab/portfolio_capacity.json atomically. Same inputs → same result.

    Aggregates the three sleeve families (rates desk / RWA floor / stable engines), applies the
    correlation haircut to the shared-venue overlap, and states the honest $10M/yr verdict + binding
    constraint.

    Args:
        write:        write the JSON atomically when True (default).
        rates_report: inject the rates_desk.portfolio report (tests/hermetic). None → build it live
                      (which loads the deep PT dataset; fail-CLOSED if missing).
        floor_pct:    override the RWA floor % (tests). None → the live rwa_floor_apy_pct() (fail-safe
                      to the committed literal).
        out_path:     override the output path (tests).

    fail-CLOSED: a missing rates-desk deep dataset (when rates_report is None) RAISES via the reused
    rates_desk.portfolio.build_report — we never fabricate the combined book."""
    # (1) rates desk — reuse the validated portfolio-of-desks aggregate verbatim (fail-CLOSED inside)
    if rates_report is None:
        rates_report = rates_portfolio.build_report(write=False)

    # the floor: prefer the rates report's own floor (same source), else the live floor, else 3.4 literal
    if floor_pct is not None:
        floor = Decimal(str(floor_pct))
    else:
        rf = rates_report.get("rwa_floor_pct")
        if isinstance(rf, (int, float)):
            floor = Decimal(str(rf))
        else:
            try:
                floor = Decimal(str(lab_config.rwa_floor_apy_pct()))
            except Exception:  # noqa: BLE001 — last-resort conservative literal
                floor = Decimal("3.4")

    families = [
        _rates_desk_family(floor, rates_report),
        _rwa_floor_family(floor),
        _stable_engines_family(floor),
    ]
    families.sort(key=lambda f: f["family"])

    # SURFACE PROVENANCE (C4 honesty pass): record the EXPANDED rate-surface coverage the desk now
    # follows (more lending venues + more PT underlyings, from feeds/config). This is an AUDIT trail,
    # NOT an inflation lever: the above-floor number is driven by the deep PT-carry depth + the at-floor
    # RWA family, so widening the live surface adds DECORRELATION POTENTIAL (more independent exit rails)
    # without lifting today's above-floor edge. The honest reading stays "$10M is scale + decorrelation,
    # not reachable today" — the provenance shows exactly how many venues/underlyings were considered.
    surface_provenance = _surface_provenance()

    naive_deployable = sum((Decimal(str(f["deployable_usd"])) for f in families), Decimal("0"))
    haircut = _correlation_haircut_usd(families)
    combined_deployable = naive_deployable - haircut

    # COMBINED above-floor identity (the honest, audit-able one): Σ per-family above-floor MINUS the
    # above-floor dollars the correlation haircut removes. The haircut constrains the SMALLER (binding)
    # shared-venue leg, so the removed above-floor dollars are valued at THAT leg's above-floor RATE
    # (max(0, its net_apy − floor)). This keeps the carry premium intact on the un-haircut depth rather
    # than diluting it across the deep RWA book — the realizable above-floor of the combined desk.
    naive_above_floor = sum((Decimal(str(f["above_floor_usd_per_yr"])) for f in families), Decimal("0"))
    haircut_above_floor = _haircut_above_floor_loss(families, haircut, floor)
    combined_above_floor = max(Decimal("0"), naive_above_floor - haircut_above_floor)

    # blended net APY = floor + combined_above_floor / combined_deployable (consistent with the above-floor
    # identity: the realized rate the combined book earns, floor plus the realizable excess over the book).
    if combined_deployable > 0:
        blended_net_apy = floor + combined_above_floor / combined_deployable * Decimal("100")
    else:
        blended_net_apy = _floor_of(families)

    target = TARGET_ABOVE_FLOOR_PER_YR
    pct_of_target = (combined_above_floor / target * Decimal("100")) if target > 0 else Decimal("0")
    gap_to_10m = max(Decimal("0"), target - combined_above_floor)

    binding, binding_explanation = _binding_constraint(families, haircut, floor)
    note = _build_note(families=families, naive_deployable=naive_deployable, haircut=haircut,
                       combined_deployable=combined_deployable, blended_net_apy=blended_net_apy,
                       floor=floor, combined_above_floor=combined_above_floor,
                       pct_of_target=pct_of_target, gap_to_10m=gap_to_10m,
                       binding=binding, binding_explanation=binding_explanation)

    result = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "strategy_lab_combined_portfolio_capacity",
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "research_only": True,
        "rwa_floor_pct": round(float(floor), 4),
        "target_above_floor_per_yr_usd": float(target),
        "correlation_haircut_frac": float(CORRELATION_HAIRCUT_FRAC),
        "rwa_depth_frac_of_tvl": float(RWA_DEPTH_FRAC_OF_TVL),
        "surface_provenance": surface_provenance,
        "families": families,
        "combined": {
            "naive_sum_deployable_usd": round(float(naive_deployable), 2),
            "correlation_haircut_usd": round(float(haircut), 2),
            "correlation_haircut_applied": bool(haircut > 0),
            "total_deployable_usd": round(float(combined_deployable), 2),
            "blended_net_apy_pct": round(float(blended_net_apy), 4),
            "total_above_floor_usd_per_yr": round(float(combined_above_floor), 2),
            "books_or_venues": {f["family"]: f["books_or_venues"] for f in families},
            "pct_of_10m_target": round(float(pct_of_target), 4),
            "gap_to_10m_usd": round(float(gap_to_10m), 2),
            "binding_constraint": binding,
            "binding_constraint_explanation": binding_explanation,
        },
        "note": note,
    }
    if write:
        _atomic_write_json(out_path or _OUT, result)
    return result


def _haircut_above_floor_loss(families: List[dict], haircut: Decimal, floor: Decimal) -> Decimal:
    """The above-floor $/yr the correlation haircut removes from the naive sum.

    The haircut constrains the SMALLER (binding) shared-venue leg's deployable. The above-floor dollars
    lost are that removed depth valued at the BINDING leg's above-floor RATE (max(0, net_apy − floor)) —
    so a haircut on an at-floor leg (e.g. the RWA floor, if it were the smaller) removes ~$0 above floor,
    while a haircut on the above-floor rates leg removes carry dollars. Deterministic; 0 when no haircut."""
    if haircut <= 0:
        return Decimal("0")
    shared = [f for f in families if f["family"] in _SHARED_VENUE_FAMILIES and f.get("shares_exit_venue")]
    if len(shared) < 2:
        return Decimal("0")
    binding = min(shared, key=lambda f: Decimal(str(f["deployable_usd"])))
    rate = max(Decimal("0"), Decimal(str(binding["net_apy_pct"])) - floor)
    return (haircut * rate / Decimal("100")).quantize(Decimal("0.01"))


def _floor_of(families: List[dict]) -> Decimal:
    for f in families:
        if f["family"] == "rwa_floor":
            return Decimal(str(f["net_apy_pct"]))
    return Decimal("3.4")


def _binding_constraint(families: List[dict], haircut: Decimal, floor: Decimal) -> tuple:
    """The single honest root cause that keeps the combined book below $10M/yr above floor.

    Logic (deterministic):
      - The only meaningful above-floor source is the rates desk; the RWA floor adds ~$0 above floor by
        construction (it yields at the floor) and the engines are tiny. If the rates family's above-floor
        $/yr is the dominant term and it is far below the target → RATES_DESK_DEPTH is binding.
      - If the deep family (RWA) has the LARGEST deployable yet contributes ~$0 above floor → the deep
        depth is wasted because it yields at the floor → RWA_YIELD_TOO_LOW is the framing constraint.
      - If the correlation haircut removes more deployable than the rates desk's own deployable (i.e.
        shared-venue non-additivity is the dominant subtraction) → CORRELATION is binding.
    We pick the dominant one and return (label, explanation). The above-floor shortfall is ALWAYS driven
    by the fact that the only above-floor edge (rates) is thin — so RATES_DESK_DEPTH is the default root
    cause; the others are reported as the contributing structural reasons in the explanation."""
    by = {f["family"]: f for f in families}
    rates_above = Decimal(str(by.get("rates_desk", {}).get("above_floor_usd_per_yr", 0)))
    rwa_dep = Decimal(str(by.get("rwa_floor", {}).get("deployable_usd", 0)))
    rates_dep = Decimal(str(by.get("rates_desk", {}).get("deployable_usd", 0)))
    rwa_above = Decimal(str(by.get("rwa_floor", {}).get("above_floor_usd_per_yr", 0)))

    # correlation dominant only if the haircut removes more than the entire rates-desk deployable
    if haircut > rates_dep and rates_dep > 0:
        return (BINDING_CORRELATION,
                f"The correlation haircut ({_fmt_usd(haircut)}) exceeds the rates-desk deployable "
                f"({_fmt_usd(rates_dep)}): shared stablecoin-venue exit liquidity is the dominant "
                "subtraction — the deep + carry books cannot be summed because they exit through the same "
                "rails. Decorrelating the venues (more chains/protocols) would unlock the most depth.")
    # the deep family has the largest depth but ~0 above floor → its yield is the structural waste
    if rwa_dep > rates_dep and rwa_above <= Decimal("1"):
        return (BINDING_RWA_YIELD,
                f"The deep family (RWA, {_fmt_usd(rwa_dep)} deployable) yields AT the floor → it adds "
                f"~$0 above floor despite being by far the largest book. The only above-floor edge is the "
                f"thin rates desk ({_fmt_usd(rates_above)}/yr). Depth is not the problem — the deep book's "
                "yield is at the floor, and the above-floor edge (rates) is too thin to clear $10M.")
    return (BINDING_RATES_DEPTH,
            f"The only meaningful above-floor source is the rates-desk carry ({_fmt_usd(rates_above)}/yr), "
            "which lives in THIN PT pools (the §9 exit cap binds each book small). The deep RWA family "
            "yields at the floor (~$0 above), the engines are tiny, and the shared-venue haircut removes "
            f"{_fmt_usd(haircut)} of summable depth. Rates-desk depth is the binding constraint on the "
            "above-floor number.")


def _build_note(*, families, naive_deployable, haircut, combined_deployable, blended_net_apy, floor,
                combined_above_floor, pct_of_target, gap_to_10m, binding, binding_explanation) -> str:
    """The honest combined fundability verdict — never inflated."""
    by = {f["family"]: f for f in families}
    reach = (
        f"COMBINED book across 3 sleeve families: rates desk "
        f"{_fmt_usd(by.get('rates_desk', {}).get('deployable_usd'))} @ "
        f"{by.get('rates_desk', {}).get('net_apy_pct')}% (above-floor), RWA floor "
        f"{_fmt_usd(by.get('rwa_floor', {}).get('deployable_usd'))} @ "
        f"{by.get('rwa_floor', {}).get('net_apy_pct')}% (AT floor, deep), stable engines "
        f"{_fmt_usd(by.get('stable_engines', {}).get('deployable_usd'))} @ "
        f"{by.get('stable_engines', {}).get('net_apy_pct')}%. Naive sum "
        f"{_fmt_usd(naive_deployable)} − correlation haircut {_fmt_usd(haircut)} (shared stablecoin-venue "
        f"exit liquidity, {CORRELATION_HAIRCUT_FRAC * 100:.0f}% of the binding overlap) = "
        f"{_fmt_usd(combined_deployable)} combined deployable at a blended {float(blended_net_apy):.2f}%/yr "
        f"(RWA floor {float(floor):.2f}%/yr) → {_fmt_usd(combined_above_floor)}/yr ABOVE the floor.")
    if combined_above_floor >= TARGET_ABOVE_FLOOR_PER_YR:
        verdict = (f"That CLEARS the $10M/yr target ({float(pct_of_target):.1f}% of it) on today's combined "
                   "real-market book.")
    else:
        verdict = (
            f"That is only {float(pct_of_target):.2f}% of the $10M/yr target — a gap of "
            f"{_fmt_usd(gap_to_10m)}/yr. Honest verdict: even the COMBINED real-market book is well short of "
            f"$10M/yr above the floor at today's market depth. Binding constraint: {binding}. "
            f"{binding_explanation} What would CLOSE the gap: (1) DEEPER PT markets — more per-book carry "
            "depth lifts the only meaningful above-floor source; (2) MORE venues/chains — decorrelating the "
            "exit rails shrinks the correlation haircut so the deep + carry books become additive; and "
            "(3) REAL AUM at the floor — the deep RWA family banks the floor today (~$0 above), so its huge "
            "depth only becomes above-floor dollars once real capital is deployed AND a spread over the "
            "floor is captured. The honest truth: the combined book is a real, diversified, fail-closed "
            "research book, but $10M/yr above floor is a SCALE + DECORRELATION + real-AUM play, not "
            "reachable on the current thin above-floor edge.")
    return reach + " " + verdict


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# doc section + printing
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _render_doc_section(result: dict) -> str:
    floor = result.get("rwa_floor_pct")
    c = result.get("combined", {})
    lines: List[str] = [_DOC_BEGIN, ""]
    lines.append("## Combined multi-sleeve portfolio capacity — how much does the WHOLE book absorb?\n")
    lines.append(
        "_Deterministic COMBINED capacity model (`spa_core/strategy_lab/portfolio_capacity.py`): aggregates "
        "the THREE sleeve families — (1) rates-desk PT carry (reused verbatim from "
        "`rates_desk.portfolio`), (2) the deep tokenized-T-bill RWA cash floor, (3) the production stable "
        "engines A/B/C — and applies a CORRELATION HAIRCUT where families share exit liquidity / venues "
        "(rates carry + RWA both redeem through stablecoin rails → not fully additive). PURE / fail-CLOSED "
        "/ advisory. Re-runnable via `python3 -m spa_core.strategy_lab.portfolio_capacity`._\n")
    lines.append(f"RWA floor: **{floor}%/yr**. Target: **$10,000,000/yr ABOVE the floor**. "
                 f"Correlation haircut: **{result.get('correlation_haircut_frac', 0) * 100:.0f}%** of the "
                 "shared-venue overlap.\n")
    lines.append("| family | deployable AUM | net APY %/yr | above floor $/yr | shares exit venue |")
    lines.append("|---|---:|---:|---:|:--:|")
    for f in result.get("families", []):
        lines.append(
            f"| {f['family']} | {_fmt_usd(f['deployable_usd'])} | {f['net_apy_pct']:.4f} | "
            f"{_fmt_usd(f['above_floor_usd_per_yr'])} | {'yes' if f['shares_exit_venue'] else 'no'} |")
    lines.append("")
    lines.append(f"- **Naive sum deployable:** {_fmt_usd(c.get('naive_sum_deployable_usd'))}")
    lines.append(f"- **Correlation haircut:** −{_fmt_usd(c.get('correlation_haircut_usd'))} "
                 f"(applied: {c.get('correlation_haircut_applied')})")
    lines.append(f"- **Combined deployable AUM:** **{_fmt_usd(c.get('total_deployable_usd'))}**")
    lines.append(f"- **Blended net APY:** **{c.get('blended_net_apy_pct')}%/yr**")
    lines.append(f"- **Combined yield ABOVE the floor:** **{_fmt_usd(c.get('total_above_floor_usd_per_yr'))}"
                 f"/yr** ({c.get('pct_of_10m_target')}% of the $10M/yr target)")
    lines.append(f"- **Gap to $10M/yr:** {_fmt_usd(c.get('gap_to_10m_usd'))}/yr")
    lines.append(f"- **Binding constraint:** **{c.get('binding_constraint')}**\n")
    lines.append(f"> **Honest combined fundability verdict.** {result.get('note')}\n")
    lines.append(_DOC_END)
    return "\n".join(lines)


def write_doc_section(result: dict, doc_path: Optional[Path] = None) -> Path:
    """Idempotently (re)write the combined-capacity section into docs/STRUCTURAL_DESK.md between the
    markers, preserving the surrounding narrative. Atomic write (repo rule #4)."""
    path = doc_path or _DOC
    section = _render_doc_section(result)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if _DOC_BEGIN in existing and _DOC_END in existing:
        pre = existing[: existing.index(_DOC_BEGIN)].rstrip("\n")
        post = existing[existing.index(_DOC_END) + len(_DOC_END):].lstrip("\n")
        body = (pre + "\n\n" + section + ("\n\n" + post if post else "\n")).rstrip("\n") + "\n"
    else:
        body = (existing.rstrip("\n") + "\n\n" + section + "\n") if existing else (section + "\n")
    _io.atomic_write_text(path, body)
    return path


def _print_report(result: dict) -> None:
    floor = result.get("rwa_floor_pct")
    c = result.get("combined", {})
    print(f"Strategy Lab — COMBINED multi-sleeve capacity   RWA floor {floor}%/yr   "
          f"target $10M/yr above floor")
    hdr = f"{'family':>16s} {'deployable':>16s} {'netAPY%':>9s} {'aboveFloor$/yr':>16s} {'sharesVenue':>12s}"
    print(hdr)
    print("-" * len(hdr))
    for f in result.get("families", []):
        print(f"{f['family']:>16s} {_fmt_usd(f['deployable_usd']):>16s} {f['net_apy_pct']:9.4f} "
              f"{_fmt_usd(f['above_floor_usd_per_yr']):>16s} "
              f"{('yes' if f['shares_exit_venue'] else 'no'):>12s}")
    print()
    print(f"Naive sum deployable:        {_fmt_usd(c.get('naive_sum_deployable_usd'))}")
    print(f"Correlation haircut:        -{_fmt_usd(c.get('correlation_haircut_usd'))}")
    print(f"Combined deployable AUM:     {_fmt_usd(c.get('total_deployable_usd'))}")
    print(f"Blended net APY:             {c.get('blended_net_apy_pct')}%/yr")
    print(f"Combined above floor:        {_fmt_usd(c.get('total_above_floor_usd_per_yr'))}/yr "
          f"({c.get('pct_of_10m_target')}% of $10M)")
    print(f"Gap to $10M/yr:              {_fmt_usd(c.get('gap_to_10m_usd'))}/yr")
    print(f"Binding constraint:          {c.get('binding_constraint')}")
    print(f"\n{result.get('note')}")


def main() -> int:
    result = build_report(write=True)
    _print_report(result)
    print(f"\nWrote {_OUT}")
    try:
        write_doc_section(result)
        print(f"Updated {_DOC} (combined portfolio-capacity section)")
    except Exception as exc:  # noqa: BLE001 — doc enrichment must not fail the analysis
        print(f"(doc section skipped: {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
