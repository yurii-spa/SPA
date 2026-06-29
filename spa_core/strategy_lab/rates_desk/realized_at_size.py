"""
spa_core/strategy_lab/rates_desk/realized_at_size.py — Lane B B1.2-B1.4: the KILLER-TEST harness.

THE highest-value artifact of the whole measurement lane. It ingests Lane A's per-book REALIZED
forward series, caps each book at its §9 depth limit, sums the capped books WITH the cross-family
correlation haircut, scores the capacity-CAPPED combined book at $1M / $5M / $10M, and emits the
ONE verdict an allocator needs:

    {SURVIVES_AT, DOES_NOT_SURVIVE_PAST $X, INSUFFICIENT_DATA}  + survives_at_aum_usd
                                                                + floor_plus_bps_at_5M

╔══════════════════════════════════════════════════════════════════════════════════════════════════╗
║  THE HONESTY MANDATE (the success criterion is a TRUE answer, NOT a green number)                  ║
║                                                                                                    ║
║  This harness MUST be able to return "edge does NOT survive past $X" and "INSUFFICIENT_DATA". On   ║
║  the desk's CURRENT thin / capacity-bound data the honest answer is likely NO at scale (edge_at_   ║
║  scale.json: +1.08pp@$100k → NEGATIVE past ~$1M; capacity.py: one book caps ~$250k; portfolio_     ║
║  capacity: combined ~$330k deployable). The natural output on that data is therefore               ║
║  INSUFFICIENT_DATA (too few realized days) or DOES_NOT_SURVIVE_PAST — NEVER a fabricated YES.      ║
║  B1.3's hidden tests PROVE it can say NO (a synthetic below-floor book → DOES_NOT_SURVIVE_PAST).   ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════╝

THE SCORING MODEL (deterministic, fail-CLOSED, idle-cash@floor — B1.4)
══════════════════════════════════════════════════════════════════════
For a target combined AUM (a ticket: $1M/$5M/$10M):

  1. Each book's DEPLOYABLE is its own §9 depth cap (the last realized series row's `deployable_usd`),
     and its realized rate is that row's `net_carry_after_slippage_pct` (carry NET of slippage — Lane
     A already priced the depth cost in). A book whose latest row is REFUSED (`refusal_state` != a
     live/hold state) contributes 0 deployable.
  2. The capacity-CAPPED combined deployable = Σ per-book caps − correlation haircut. The haircut is
     a REAL venue-GROUP COLLAPSE (B2.2), not a flattering single-leg trim: books that exit through
     the SAME venue (Lane A's per-book `shares_exit_venue` / `exit_venue` contract) compete for ONE
     rail, so within each shared-venue group the DEEPEST leg stays additive and `CORRELATION_HAIRCUT_
     FRAC` of EVERY other leg is removed. Genuinely-independent books are fully additive. With N books
     on one rail the removed depth scales with N−1 → a maximally-correlated book plateaus near its
     deepest single leg (it does NOT sum to a flattering total — the honest non-additivity).
     B2.3 reports a haircut_sensitivity band (frac 0→1) so the load-bearing assumption is visible.
  3. IDLE-CASH @ FLOOR (B1.4, matches edge_at_scale / capacity convention EXACTLY): at a target AUM,
     `deployed = min(AUM, capped_combined_deployable)`, `idle = AUM − deployed`. The capped-out
     remainder earns the FLOOR (0 ABOVE the floor — never the carry). The deployed slice earns the
     deployable-weighted realized carry. So:
         capped_book_net_apy = deployed_frac · carry + idle_frac · floor
     This RECONCILES TO THE CENT (asserted): floor·AUM + Σ(deployed_i · (carry_i − floor)) annual $,
     divided by AUM, equals capped_book_net_apy.
  4. `floor_plus_bps = (capped_book_net_apy − floor) · 100` (bps above floor) at each ticket.

THE VERDICT (the killer)
════════════════════════
  • INSUFFICIENT_DATA   — too few realized days across the books (< MIN_REALIZED_DAYS), or NO book
                          carries a usable realized series. We do NOT guess. This is the honest
                          default on today's thin track.
  • SURVIVES_AT $X      — the book still clears floor+SURVIVE_BPS at AUM $X (the LARGEST ticket that
                          still clears). `survives_at_aum_usd` = that AUM.
  • DOES_NOT_SURVIVE_PAST $X — it clears the bar at some ticket but FALLS BELOW it past $X. `survives
                          _at_aum_usd` = the last AUM that cleared (None if it never cleared even the
                          smallest ticket → DOES_NOT_SURVIVE_PAST 0).

CONVENTIONS (inherited, enforced): stdlib only; deterministic — sorted iteration, Decimal-exact
arithmetic on the money path; PURE — `as_of` = the data date (the latest book series date), NEVER the
wall clock; fail-CLOSED — a malformed/empty series → INSUFFICIENT_DATA, never a fabricated survival;
atomic writes (repo rule #4); LLM-FORBIDDEN; NO execution/ import. Advisory — moves no capital, never
touches the go-live track. Run:
    python3 -m spa_core.strategy_lab.rates_desk.realized_at_size
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.strategy_lab.rates_desk import _io
from spa_core.strategy_lab.portfolio_capacity import CORRELATION_HAIRCUT_FRAC

_ROOT = Path(__file__).resolve().parents[3]
_BOOKS_DIR = _ROOT / "data" / "rates_desk" / "books"
_OUT = _ROOT / "data" / "rates_desk" / "realized_at_size.json"

# The AUM tickets the combined capped book is scored at — the killer ladder.
SCORE_TICKETS_USD: Tuple[int, ...] = (1_000_000, 5_000_000, 10_000_000)
SCORE_AT_USD = 5_000_000  # the headline `floor_plus_bps_at_5M`

# Minimum realized days (across the freshest book) before the harness will issue a non-INSUFFICIENT
# verdict. Below this we honestly REFUSE to call survival — too little forward track to trust.
MIN_REALIZED_DAYS = 30

# The "edge survives" bar: the capped combined book must clear floor + SURVIVE_BPS to count as
# surviving at a ticket. 200bps = floor+2pp (matches capacity.py's fundable-ceiling line). Pinned.
SURVIVE_BPS = Decimal("200")

# Live/hold/deployed refusal states a book may carry and still deploy. Anything else
# (REFUSE/UNKNOWN/empty) contributes ZERO deployable — a refused book is not in the deployable
# combined book. NB the LANE-A contract stamps the live/deployed state as "DEPLOYED" (uppercase) on
# its realized_series rows (confirmed against data/rates_desk/books/<id>/realized_series.jsonl); we
# lower-case + match it here so Lane A's deployed books are honestly counted as deployable. SAFE/
# WATCH/HOLD/LIVE are accepted too (forward-compatible with the refusal-engine state vocabulary).
_DEPLOYABLE_REFUSAL_STATES = frozenset(
    {"safe", "watch", "hold", "live", "open", "approved", "go", "deployed"})

_GENESIS_PREV = "0" * 64
FLAG_REASON_INSUFFICIENT = "insufficient_realized_data"

# The single conservative SHARED exit-venue bucket every book defaults into when it neither proves
# independence (`shares_exit_venue is False`) nor stamps its own `exit_venue` key. The honest worst
# case the brief demands: an unproven book shares the one stablecoin rail and collapses with every
# other unproven book — never quietly additive. (Today's 22 sUSDe/USDe PT books all land here.)
_DEFAULT_SHARED_VENUE = "shared_stablecoin_rails"
# Prefix for the synthetic UNIQUE venue key a genuinely-independent (shares_exit_venue=False) book
# gets when it does not stamp an explicit `exit_venue` — keeps it additive (its own bucket).
_INDEP_VENUE_PREFIX = "indep::"

# B2.3 — the haircut-fraction sensitivity sweep. The killer verdict's load-bearing assumption is the
# correlation haircut: at frac=0 the shared-venue books are FULLY additive (the flattering extreme);
# at frac=1 a shared venue collapses to its DEEPEST single leg (the conservative extreme — one rail
# absorbs ~one book, not N). We score survival across this band so a reviewer SEES how much the answer
# moves with the assumption. Pinned, version-controlled; widening is a research change.
HAIRCUT_SENSITIVITY_FRACS: Tuple[str, ...] = ("0.0", "0.25", "0.5", "0.75", "1.0")


def _to_dec(x) -> Optional[Decimal]:
    """Parse a numeric to a FINITE Decimal via str (no float binary noise), else None (fail-CLOSED)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        d = Decimal(str(x))
    except (ValueError, ArithmeticError):
        return None
    return d if d.is_finite() else None


def _proof_hash(obj: dict) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# ingest Lane A's per-book realized series (the FROZEN DATA CONTRACT)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _read_jsonl(path: Path) -> List[dict]:
    """Read a realized_series.jsonl (one JSON object per line). fail-CLOSED: a missing file → [];
    a malformed line is SKIPPED (never crashes the harness, never fabricates a row)."""
    out: List[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def load_book_series(books_dir: Optional[Path] = None) -> Dict[str, List[dict]]:
    """{book_id: [series rows sorted by as_of]} from data/rates_desk/books/<book_id>/realized_
    series.jsonl. Deterministic order. fail-CLOSED: a missing books dir → {} (→ INSUFFICIENT_DATA)."""
    bd = books_dir or _BOOKS_DIR
    out: Dict[str, List[dict]] = {}
    if not bd.exists() or not bd.is_dir():
        return out
    for sub in sorted(bd.iterdir(), key=lambda p: p.name):
        if not sub.is_dir():
            continue
        series = _read_jsonl(sub / "realized_series.jsonl")
        if not series:
            continue
        series.sort(key=lambda r: str(r.get("as_of") or ""))
        out[sub.name] = series
    return out


def _latest_row(series: List[dict]) -> Optional[dict]:
    return series[-1] if series else None


def _book_shares_venue(latest: dict) -> bool:
    """A book exits through shared stablecoin rails (→ subject to the correlation haircut) unless it
    explicitly declares an independent venue. Conservative DEFAULT True (over-haircut, never under)."""
    if latest.get("shares_exit_venue") is False:
        return False
    return True


def _book_exit_venue(latest: dict, shares: bool) -> str:
    """The book's exit-VENUE GROUP key (B2.2) — books that share a key compete for the SAME exit
    rails and so collapse together (not additive); distinct keys are independent and additive.

    Lane A's frozen venue-independence contract (W2): a book MAY stamp `exit_venue` (e.g.
    "usde_stable_eth", "usdc_aave_arb") to declare which exit rail it shares. We consume it
    VERBATIM. When Lane A does NOT stamp a key:
      • `shares_exit_venue is False` → a UNIQUE per-book key (genuinely independent → additive),
      • otherwise → the single conservative SHARED bucket `_DEFAULT_SHARED_VENUE` (the honest worst
        case the brief demands: if a book does not prove independence, it shares the one rail and
        collapses with every other unproven book — NEVER quietly additive).
    fail-CLOSED / conservative-by-default: an unproven book is shared, not independent."""
    v = latest.get("exit_venue")
    if isinstance(v, str) and v.strip():
        return v.strip().lower()
    if not shares:
        # genuinely-independent book with no explicit key → its own unique bucket (additive)
        bid = latest.get("book_id")
        return f"{_INDEP_VENUE_PREFIX}{bid}" if bid is not None else _INDEP_VENUE_PREFIX
    return _DEFAULT_SHARED_VENUE


def _book_deployable(
    series: List[dict],
) -> Tuple[Decimal, Decimal, bool, str, str, Optional[str]]:
    """A book's (deployable_usd, net_carry_after_slippage_pct, shares_venue, exit_venue, refusal_state, as_of).

    Deployable = the latest row's §9 `deployable_usd` (its depth cap) IF the book is in a deployable
    refusal_state; else 0 (a refused book is not in the deployable combined book). Carry = the latest
    row's `net_carry_after_slippage_pct` (carry NET of slippage — Lane A priced depth in). `exit_venue`
    is the venue-GROUP key (B2.2) the cross-family collapse haircut groups on. fail-CLOSED:
    a missing/malformed deployable or carry → 0 deployable (never a fabricated size)."""
    latest = _latest_row(series)
    if latest is None:
        return Decimal("0"), Decimal("0"), True, _DEFAULT_SHARED_VENUE, "", None
    state = str(latest.get("refusal_state") or "").strip().lower()
    as_of = latest.get("as_of")
    shares = _book_shares_venue(latest)
    venue = _book_exit_venue(latest, shares)
    if state not in _DEPLOYABLE_REFUSAL_STATES:
        return Decimal("0"), Decimal("0"), shares, venue, state, as_of  # refused → no deployable
    dep = _to_dec(latest.get("deployable_usd"))
    carry = _to_dec(latest.get("net_carry_after_slippage_pct"))
    if dep is None or dep <= 0 or carry is None:
        return Decimal("0"), Decimal("0"), shares, venue, state, as_of
    return dep, carry, shares, venue, state, as_of


def _realized_days(series_map: Dict[str, List[dict]]) -> int:
    """The realized track length = the MOST rows any single book carries (the freshest book's track).
    Conservative-honest: we judge survival on the deepest available forward track, not a sum."""
    return max((len(s) for s in series_map.values()), default=0)


def _book_floor_pct(series_map: Dict[str, List[dict]]) -> Optional[Decimal]:
    """The RWA floor (%) read from the books' OWN `floor_pct` (Lane A stamps the live floor on each
    row). Uses the latest row of the freshest book. None if no book carries a usable floor (→ then
    the caller fail-CLOSES to the committed literal floor, never fabricates)."""
    best: Optional[Decimal] = None
    best_len = -1
    for s in series_map.values():
        if len(s) > best_len:
            f = _to_dec(_latest_row(s).get("floor_pct")) if s else None
            if f is not None and f >= 0:
                best, best_len = f, len(s)
    return best


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# correlation haircut + capacity-capped combined deployable  (B2.2 — the REAL venue-group collapse)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _venue_groups(books: List[dict]) -> Dict[str, List[Decimal]]:
    """Group the deployable books by their exit-VENUE key → {venue: [deployable_usd, ...]}.

    Consumes Lane A's per-book venue-independence (B2.2 / the CRUX): books that share a venue key
    compete for the SAME exit rails and collapse together; distinct keys are independent. Only
    positive-deployable books participate. Deterministic (sorted)."""
    groups: Dict[str, List[Decimal]] = {}
    for b in books:
        dep = Decimal(str(b["deployable_usd"]))
        if dep <= 0:
            continue
        venue = str(b.get("exit_venue") or _DEFAULT_SHARED_VENUE)
        groups.setdefault(venue, []).append(dep)
    return groups


def _correlation_haircut(books: List[dict], frac: Optional[Decimal] = None) -> Decimal:
    """The non-additive deployable removed for shared exit-liquidity / venues — the REAL venue-GROUP
    collapse (B2.2), NOT a flattering single-leg haircut.

    The CRUX (coordinate with Lane A): books that share an exit venue do NOT exit additively under a
    forced unwind — one stablecoin rail absorbs roughly ONE book's depth, not the sum of every book
    queued behind it. So within each shared-venue group (members sorted DESCENDING by deployable) we
    keep the DEEPEST leg additive and haircut `frac` of EVERY OTHER leg in that group:

        removed(group) = frac · Σ(group members below the deepest)

    Genuinely-independent books (distinct `exit_venue` keys / `shares_exit_venue is False`) each form
    their own singleton group → removed 0 (fully additive). `frac` defaults to
    portfolio_capacity.CORRELATION_HAIRCUT_FRAC (0.50). Returns total USD removed (≥ 0).

    HONEST-by-construction: with N books in ONE shared bucket the removed depth scales with N−1 (the
    whole tail collapses), so a maximally-correlated book (today's 22 sUSDe/USDe PT books on one
    USDe rail) plateaus near its deepest single leg — it does NOT sum to a flattering total. At
    frac=1 the group collapses ENTIRELY to its deepest leg (the conservative extreme).

    PROPERTY (red-team): combined deployable ≤ Σ per-book caps − haircut (never exceeds the naive
    sum); haircut is NON-DECREASING in frac and in group cardinality."""
    f = CORRELATION_HAIRCUT_FRAC if frac is None else frac
    removed = Decimal("0")
    for venue, deps in sorted(_venue_groups(books).items()):
        if len(deps) < 2:
            continue  # a singleton venue is fully additive (the deepest leg IS the whole group)
        tail = sorted(deps, reverse=True)[1:]  # every leg below the deepest in this group
        removed += sum(tail, Decimal("0")) * f
    return removed.quantize(Decimal("0.01"))


def _capped_combined(
    books: List[dict], frac: Optional[Decimal] = None
) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    """(naive_sum_deployable, haircut, combined_deployable, deployable_weighted_carry_pct).

    naive_sum = Σ per-book §9 caps; combined = naive_sum − correlation haircut (clamped ≥ 0). The
    deployable-weighted carry is the rate the DEPLOYED slice earns (weighted by per-book deployable
    BEFORE the haircut — the haircut removes depth, not the per-dollar carry rate). `frac` overrides
    the haircut fraction (used by the B2.3 sensitivity sweep); None → CORRELATION_HAIRCUT_FRAC."""
    naive = sum((Decimal(str(b["deployable_usd"])) for b in books), Decimal("0"))
    haircut = _correlation_haircut(books, frac)
    combined = max(Decimal("0"), naive - haircut)
    if naive > 0:
        wcarry = sum(
            (Decimal(str(b["deployable_usd"])) * Decimal(str(b["net_carry_after_slippage_pct"]))
             for b in books), Decimal("0")
        ) / naive
    else:
        wcarry = Decimal("0")
    return naive, haircut, combined, wcarry


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# B1.4 — idle-cash@floor scoring at a target AUM (reconciles to the cent)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def score_at_aum(
    aum_usd: Decimal,
    combined_deployable: Decimal,
    deployed_weighted_carry_pct: Decimal,
    floor_pct: Decimal,
) -> dict:
    """Score the capped combined book at a target AUM under the idle-cash@floor convention (B1.4).

        deployed = min(AUM, combined_deployable)      # cannot deploy past the §9 depth caps
        idle     = AUM − deployed                      # capped-out remainder
        capped_book_net_apy = deployed_frac·carry + idle_frac·floor

    The idle slice earns the FLOOR (0 ABOVE floor — matches edge_at_scale / capacity convention). The
    result RECONCILES TO THE CENT (asserted): annual $ = floor·AUM + deployed·(carry − floor); divided
    by AUM that equals capped_book_net_apy. PURE, Decimal-exact."""
    if aum_usd <= 0:
        return {
            "aum_usd": 0.0, "deployed_usd": 0.0, "idle_usd": 0.0, "deployed_frac": 0.0,
            "idle_frac": 0.0, "capped_book_net_apy_pct": float(floor_pct),
            "floor_plus_bps": 0.0, "annual_income_usd": 0.0, "reconciled": True,
        }
    deployed = min(aum_usd, combined_deployable)
    if deployed < 0:
        deployed = Decimal("0")
    idle = aum_usd - deployed
    deployed_frac = deployed / aum_usd
    idle_frac = idle / aum_usd
    carry = deployed_weighted_carry_pct
    # book net APY = deployed_frac·carry + idle_frac·floor  (the idle@floor identity)
    capped_apy = deployed_frac * carry + idle_frac * floor_pct

    # annual $ both ways → reconcile to the cent
    annual_income = (deployed * carry / Decimal("100")) + (idle * floor_pct / Decimal("100"))
    apy_from_income = annual_income / aum_usd * Decimal("100")
    # identity check: floor·AUM + deployed·(carry−floor), per year
    annual_alt = (floor_pct * aum_usd / Decimal("100")) + (deployed * (carry - floor_pct) / Decimal("100"))
    reconciled = (
        abs(capped_apy - apy_from_income) <= Decimal("0.0000001")
        and abs(annual_income - annual_alt) <= Decimal("0.01")
    )
    floor_plus_bps = (capped_apy - floor_pct) * Decimal("100")
    return {
        "aum_usd": float(aum_usd),
        "deployed_usd": round(float(deployed), 2),
        "idle_usd": round(float(idle), 2),
        "deployed_frac": round(float(deployed_frac), 6),
        "idle_frac": round(float(idle_frac), 6),
        "capped_book_net_apy_pct": round(float(capped_apy), 6),
        "floor_plus_bps": round(float(floor_plus_bps), 4),
        "annual_income_usd": round(float(annual_income), 2),
        "reconciled": bool(reconciled),
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# the verdict (the killer)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _verdict_from_scores(
    scores: List[dict], floor_pct: Decimal, realized_days: int, n_books_deployable: int
) -> Tuple[str, Optional[float], Optional[float]]:
    """(verdict, survives_at_aum_usd, does_not_survive_past_aum_usd).

    INSUFFICIENT_DATA if too few realized days OR no deployable book. Otherwise walk the ascending
    ticket ladder: a ticket SURVIVES if its floor_plus_bps ≥ SURVIVE_BPS.
      • survives at every ticket → SURVIVES_AT (the largest ticket).
      • survives at some prefix then fails → DOES_NOT_SURVIVE_PAST (the last surviving AUM).
      • fails even the smallest ticket → DOES_NOT_SURVIVE_PAST 0 (never cleared)."""
    if realized_days < MIN_REALIZED_DAYS or n_books_deployable <= 0:
        return "INSUFFICIENT_DATA", None, None
    bar = float(SURVIVE_BPS)
    last_survive: Optional[float] = None
    first_fail: Optional[float] = None
    for s in scores:  # ascending AUM
        if s["floor_plus_bps"] >= bar:
            last_survive = s["aum_usd"]
        else:
            first_fail = s["aum_usd"]
            break
    if first_fail is None and last_survive is not None:
        return "SURVIVES_AT", last_survive, None
    # it failed at some point
    if last_survive is None:
        # never cleared even the smallest ticket
        return "DOES_NOT_SURVIVE_PAST", None, (scores[0]["aum_usd"] if scores else 0.0)
    return "DOES_NOT_SURVIVE_PAST", last_survive, first_fail


def run_killer_test(
    series_map: Dict[str, List[dict]],
    floor_pct: Optional[Decimal] = None,
    tickets_usd: Tuple[int, ...] = SCORE_TICKETS_USD,
) -> dict:
    """The KILLER TEST — PURE given the per-book series. Returns the full scored result + verdict.

    fail-CLOSED: an empty/insufficient series_map → INSUFFICIENT_DATA (the honest default). On the
    desk's current thin data this is the expected, correct answer."""
    # the floor: prefer the books' own stamped floor, else the committed literal (never fabricated)
    if floor_pct is None:
        floor_pct = _book_floor_pct(series_map)
    if floor_pct is None:
        floor_pct = Decimal("3.4")  # committed conservative literal (fail-CLOSED)

    # per-book deployable rows (refused books → 0 deployable, excluded from the combined book)
    book_rows: List[dict] = []
    for book_id in sorted(series_map):
        dep, carry, shares, venue, state, as_of = _book_deployable(series_map[book_id])
        book_rows.append({
            "book_id": book_id,
            "deployable_usd": round(float(dep), 2),
            "net_carry_after_slippage_pct": round(float(carry), 6),
            "shares_exit_venue": bool(shares),
            "exit_venue": venue,
            "refusal_state": state,
            "as_of": as_of,
            "in_combined_book": bool(dep > 0),
        })
    deployable_books = [b for b in book_rows if b["deployable_usd"] > 0]
    n_books_deployable = len(deployable_books)

    naive, haircut, combined, wcarry = _capped_combined(deployable_books)
    # PROPERTY (red-team B1.5): combined ≤ naive sum − haircut (never exceeds the capped sum)
    assert combined <= naive, "combined deployable exceeds the naive sum of per-book caps"
    assert combined <= max(Decimal("0"), naive - haircut) + Decimal("0.01"), (
        "combined deployable exceeds Σ caps − haircut")

    scores = [score_at_aum(Decimal(str(t)), combined, wcarry, floor_pct) for t in tickets_usd]
    # every score must reconcile to the cent (B1.4 invariant)
    for s in scores:
        assert s["reconciled"], f"idle@floor reconcile failed at AUM {s['aum_usd']}"

    realized_days = _realized_days(series_map)
    verdict, survives_at, dnsp = _verdict_from_scores(
        scores, floor_pct, realized_days, n_books_deployable)

    # the headline floor_plus_bps at $5M (the SCORE_AT_USD ticket)
    score_5m = next((s for s in scores if int(s["aum_usd"]) == SCORE_AT_USD), None)
    floor_plus_bps_at_5m = score_5m["floor_plus_bps"] if score_5m else None

    # B2.2 — the venue-GROUP exposure (which exit rails the deployable concentrates on). The number
    # of distinct exit venues vs deployable books is the honest decorrelation picture: 22 books on
    # ONE venue ≠ 22 independent legs. Sorted, deterministic.
    venue_groups = _venue_groups(deployable_books)
    venue_exposure = sorted(
        ({"exit_venue": v, "n_books": len(ds),
          "group_deployable_usd": round(float(sum(ds, Decimal("0"))), 2),
          "deepest_leg_usd": round(float(max(ds)), 2)}
         for v, ds in venue_groups.items()),
        key=lambda r: (-r["group_deployable_usd"], r["exit_venue"]),
    )

    # B2.3 — the HONESTY CRUX: how sensitive is the verdict to the haircut fraction? Re-score the
    # SAME books across the haircut band (0 = fully additive flattering extreme, 1 = full venue
    # collapse to the deepest leg). A reviewer SEES the load-bearing assumption's leverage on
    # survives_at_aum_usd / floor_plus_bps_at_5M / combined_deployable.
    sensitivity = _haircut_sensitivity_band(
        deployable_books, wcarry, floor_pct, realized_days, n_books_deployable, tickets_usd)

    as_of = max((b["as_of"] for b in book_rows if b.get("as_of")), default=None)

    payload = {
        "verdict": verdict,
        "survives_at_aum_usd": survives_at,
        "does_not_survive_past_aum_usd": dnsp,
        "floor_plus_bps_at_5M": floor_plus_bps_at_5m,
        "rwa_floor_pct": round(float(floor_pct), 6),
        "survive_bps_bar": float(SURVIVE_BPS),
        "min_realized_days_required": MIN_REALIZED_DAYS,
        "realized_days": realized_days,
        "n_books": len(book_rows),
        "n_books_deployable": n_books_deployable,
        "books": book_rows,
        "combined": {
            "naive_sum_deployable_usd": round(float(naive), 2),
            "correlation_haircut_usd": round(float(haircut), 2),
            "correlation_haircut_frac": float(CORRELATION_HAIRCUT_FRAC),
            "haircut_model": "venue_group_collapse",
            "combined_deployable_usd": round(float(combined), 2),
            "deployable_weighted_carry_pct": round(float(wcarry), 6),
            "n_exit_venues": len(venue_groups),
            "venue_exposure": venue_exposure,
        },
        "scores": scores,
        "haircut_sensitivity": sensitivity,
        "as_of": as_of,
    }
    return payload


def _haircut_sensitivity_band(
    deployable_books: List[dict],
    wcarry: Decimal,
    floor_pct: Decimal,
    realized_days: int,
    n_books_deployable: int,
    tickets_usd: Tuple[int, ...],
) -> dict:
    """B2.3 — the haircut-fraction SENSITIVITY band: the killer verdict's load-bearing assumption is
    the correlation haircut. A too-LOW haircut FLATTERS the answer (shared-venue books summed as if
    independent). We re-run the verdict across HAIRCUT_SENSITIVITY_FRACS so a reviewer sees exactly
    how much survives_at_aum_usd / floor_plus_bps_at_5M / combined_deployable move with the assumption.

    Returns the per-frac band + a `verdict_stable_across_band` flag (does the {SURVIVES_AT/DOES_NOT_
    SURVIVE_PAST/INSUFFICIENT_DATA} verdict change anywhere in the band?) + the headline `frac_used`."""
    band: List[dict] = []
    for fs in HAIRCUT_SENSITIVITY_FRACS:
        f = Decimal(fs)
        naive, haircut, combined, _ = _capped_combined(deployable_books, f)
        scores = [score_at_aum(Decimal(str(t)), combined, wcarry, floor_pct) for t in tickets_usd]
        verdict, survives_at, dnsp = _verdict_from_scores(
            scores, floor_pct, realized_days, n_books_deployable)
        s5 = next((s for s in scores if int(s["aum_usd"]) == SCORE_AT_USD), None)
        band.append({
            "haircut_frac": float(f),
            "correlation_haircut_usd": round(float(haircut), 2),
            "combined_deployable_usd": round(float(combined), 2),
            "verdict": verdict,
            "survives_at_aum_usd": survives_at,
            "does_not_survive_past_aum_usd": dnsp,
            "floor_plus_bps_at_5M": s5["floor_plus_bps"] if s5 else None,
        })
    verdicts = {b["verdict"] for b in band}
    survive_set = {b["survives_at_aum_usd"] for b in band}
    return {
        "fracs_swept": [float(Decimal(x)) for x in HAIRCUT_SENSITIVITY_FRACS],
        "frac_used": float(CORRELATION_HAIRCUT_FRAC),
        "band": band,
        "verdict_stable_across_band": len(verdicts) == 1,
        "survives_at_stable_across_band": len(survive_set) == 1,
        "note": ("How sensitive the killer verdict is to the correlation-haircut fraction (the load-"
                 "bearing assumption). frac=0 = shared-venue books FULLY additive (flattering); frac=1 "
                 "= each shared venue collapses to its DEEPEST single leg (conservative). If the "
                 "verdict is stable across the band the answer does NOT hinge on the haircut; if it "
                 "flips, the haircut is load-bearing and the honest read is the conservative end."),
    }


def build_realized_at_size(
    write: bool = True,
    series_map: Optional[Dict[str, List[dict]]] = None,
    books_dir: Optional[Path] = None,
    floor_pct: Optional[float] = None,
    out_path: Optional[Path] = None,
) -> dict:
    """Build the killer-test result and (optionally) write data/rates_desk/realized_at_size.json
    atomically. Reads Lane A's per-book series from `books_dir` unless `series_map` is injected.
    Same inputs → byte-identical JSON. fail-CLOSED → INSUFFICIENT_DATA on thin/absent data."""
    if series_map is None:
        series_map = load_book_series(books_dir)
    fp = Decimal(str(floor_pct)) if floor_pct is not None else None
    inner = run_killer_test(series_map, floor_pct=fp)

    result = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "rates_desk_realized_at_size_killer_test",
        "model_label": ("the realized-at-size killer test: capacity-capped combined book scored at "
                        "$1M/$5M/$10M with idle-cash@floor; emits SURVIVES_AT / DOES_NOT_SURVIVE_PAST "
                        "/ INSUFFICIENT_DATA"),
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "consumes": "data/rates_desk/books/<book_id>/realized_series.jsonl (Lane A frozen contract)",
        "honesty_mandate": ("the success criterion is a TRUE answer, not a green number; this harness "
                            "can and does return DOES_NOT_SURVIVE_PAST / INSUFFICIENT_DATA"),
        **inner,
        "basis": ("Σ per-book §9 depth caps − cross-family correlation haircut, scored at each ticket "
                  "under idle-cash@floor (capped-out capital earns the floor, 0 above)"),
        "disclaimer": ("Advisory / research — moves no capital, never touches the go-live track. The "
                       "verdict is the honest answer on the realized forward track, not a projection: "
                       "INSUFFICIENT_DATA is the correct, non-fabricated output on a thin track."),
    }
    # proof_hash over the verdict-bearing payload (forging the verdict/scores/haircut-band breaks it)
    result["proof_hash"] = _proof_hash({k: inner[k] for k in (
        "verdict", "survives_at_aum_usd", "does_not_survive_past_aum_usd", "floor_plus_bps_at_5M",
        "combined", "scores", "rwa_floor_pct", "haircut_sensitivity")})
    if write:
        _io.atomic_write_json(out_path or _OUT, result, indent=1, default=str)
    return result


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# printing
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _fmt_usd(x) -> str:
    return "—" if x is None else f"${float(x):,.0f}"


def _print(result: dict) -> None:
    print("Rates Desk — REALIZED-AT-SIZE KILLER TEST  (advisory; the honest verdict)")
    print(f"as_of: {result.get('as_of')}  ·  floor: {result.get('rwa_floor_pct')}%/yr  ·  "
          f"realized days: {result.get('realized_days')} (need {result.get('min_realized_days_required')})")
    c = result.get("combined", {})
    print(f"books: {result.get('n_books')} ({result.get('n_books_deployable')} deployable)  ·  "
          f"Σ caps {_fmt_usd(c.get('naive_sum_deployable_usd'))} − haircut "
          f"{_fmt_usd(c.get('correlation_haircut_usd'))} = combined "
          f"{_fmt_usd(c.get('combined_deployable_usd'))} @ "
          f"{c.get('deployable_weighted_carry_pct')}%/yr carry\n")
    hdr = f"{'AUM':>14s} {'deployed':>14s} {'idle':>14s} {'bookAPY%':>10s} {'floor+bps':>10s}"
    print(hdr)
    print("-" * len(hdr))
    for s in result.get("scores", []):
        print(f"{_fmt_usd(s['aum_usd']):>14s} {_fmt_usd(s['deployed_usd']):>14s} "
              f"{_fmt_usd(s['idle_usd']):>14s} {s['capped_book_net_apy_pct']:10.4f} "
              f"{s['floor_plus_bps']:10.2f}")
    # venue-group exposure (B2.2): the honest decorrelation picture
    ve = c.get("venue_exposure", [])
    if ve:
        print(f"\nexit-venue exposure ({c.get('n_exit_venues')} distinct venue(s) across "
              f"{result.get('n_books_deployable')} deployable books):")
        for g in ve[:6]:
            print(f"    {g['exit_venue'][:34]:>34s}  {g['n_books']:>2d} books  "
                  f"group {_fmt_usd(g['group_deployable_usd'])}  deepest leg "
                  f"{_fmt_usd(g['deepest_leg_usd'])}")
    print()
    print(f"VERDICT: {result.get('verdict')}")
    print(f"  survives_at_aum_usd:          {_fmt_usd(result.get('survives_at_aum_usd'))}")
    print(f"  does_not_survive_past_aum_usd:{_fmt_usd(result.get('does_not_survive_past_aum_usd'))}")
    print(f"  floor_plus_bps_at_5M:         {result.get('floor_plus_bps_at_5M')}")

    # B2.3 — the haircut sensitivity band (the honesty crux)
    hs = result.get("haircut_sensitivity", {})
    band = hs.get("band", [])
    if band:
        print(f"\nHAIRCUT SENSITIVITY (frac_used={hs.get('frac_used')}, "
              f"verdict stable across band: {hs.get('verdict_stable_across_band')}):")
        bh = (f"{'haircut_frac':>13s} {'haircut$':>14s} {'combined$':>14s} "
              f"{'floor+bps@5M':>13s}  verdict")
        print(bh)
        print("-" * len(bh))
        for b in band:
            print(f"{b['haircut_frac']:>13.2f} {_fmt_usd(b['correlation_haircut_usd']):>14s} "
                  f"{_fmt_usd(b['combined_deployable_usd']):>14s} "
                  f"{(b['floor_plus_bps_at_5M'] if b['floor_plus_bps_at_5M'] is not None else 0):>13.2f}  "
                  f"{b['verdict']}")


def main() -> int:
    result = build_realized_at_size(write=True)
    _print(result)
    print(f"\nWrote {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
