"""
spa_core/strategy_lab/rates_desk/books.py — the rates-desk BOOK REGISTRY (Lane A, W1: A1.1).

The strategic truth (Lane A): the desk's small-TVL carry edge DIES past ~$1M if you try to size ONE
book bigger — the §9 exit-capacity cap binds each market to a small depth-bound size (capacity.py /
portfolio.py proved this). The ONLY real way the refusal-gated PT carry SCALES toward the $10M/yr
target is by COUNT of independent gated books — each a distinct (underlying, maturity, chain) Pendle PT
market with its OWN pool depth → its OWN ~$250k exit-depth ceiling. Deploying into one does NOT consume
another's depth, so N independent books ADD their deployable AUM.

This module FORMALIZES each such market as an addressable, deterministic `Book`:

  • `book_id`  — a stable, deterministic, collision-resistant identifier for one
    (underlying, maturity, chain) market. The SAME market always hashes to the SAME id across runs /
    machines / years (no clock, no RNG, no enumeration order dependence), so a per-book artifact path
    (`data/rates_desk/books/<book_id>/realized_series.jsonl`, the frozen contract) is stable.
  • enumeration — `enumerate_books()` walks the deep Pendle PT universe and returns the SORTED list of
    harvestable books. LRT markets (ezETH / rsETH …) are EXCLUDED here: the rate gate refuses them on
    the depeg / nesting tail, so they are never a fundable carry book (they NEVER become an addressable
    Book — a toxic market is not a book). Only the STABLE_SYNTH / STABLE_RWA survivor universe (the
    same kinds capacity.py / portfolio.py validated) is enumerable.

CONVENTIONS (inherited, enforced): stdlib only; PURE — no clock, no IO in the id derivation, `as_of`
is never wall-clock; deterministic — `book_id` is a content hash, the registry is SORTED, no RNG;
fail-CLOSED — a market with a malformed/absent kind RAISES rather than silently registering a book;
LLM-FORBIDDEN. Advisory / research — this is the addressable spine, it moves no capital.

Run (offline, on the deep cached data):
    python3 -m spa_core.strategy_lab.rates_desk.books
"""
# LLM_FORBIDDEN
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional

from spa_core.strategy_lab.rates_desk.contracts import UnderlyingKind

# The harvestable carry kinds — the SAME survivor universe capacity.py / portfolio.py validated. LRT
# (ezETH / rsETH) is EXCLUDED: the refusal-first gate vetoes it on the structural depeg/nesting tail, so
# it is never a fundable carry book (a toxic market is NOT addressable as a Book). Held in lock-step with
# portfolio.HARVESTABLE_KINDS (single survivor-universe definition; if one changes the other must too).
HARVESTABLE_KINDS = frozenset({UnderlyingKind.STABLE_SYNTH, UnderlyingKind.STABLE_RWA})

# Excluded toxic kinds — recorded explicitly so the exclusion is auditable, not implicit. An LRT market
# is refusal-gated; it never becomes a Book.
EXCLUDED_KINDS = frozenset({UnderlyingKind.LRT})

# The chain every deep Pendle PT market in the cached universe lives on. The deep history pull is the
# Ethereum-mainnet Pendle markets; the per-market dicts carry no `chain` field, so we resolve it
# deterministically here (a documented constant, not a fabricated per-row value). A future multi-chain
# pull would carry an explicit per-market `chain` and this default would only be the fallback.
DEFAULT_CHAIN = "ethereum"

# book_id = a short, stable, collision-resistant content hash over the (underlying, maturity, chain)
# identity. We keep the FULL human-readable identity on the Book too; the id is the addressable key.
_BOOK_ID_LEN = 16  # 16 hex chars = 64 bits — ample to avoid collision across the few-dozen-market universe


def make_book_id(underlying: str, maturity: str, chain: str) -> str:
    """Deterministic, stable `book_id` for one (underlying, maturity, chain) PT market.

    PURE: a SHA-256 over the canonical, lower-cased, pipe-joined identity, truncated to _BOOK_ID_LEN hex
    chars and prefixed `bk_`. The same market identity ALWAYS yields the same id — across runs, machines,
    Python versions, and enumeration order — so the per-book artifact path is stable forever. No clock,
    no RNG, no float. fail-CLOSED: an empty underlying/maturity RAISES (a book with no identity is not a
    book)."""
    u = (underlying or "").strip().lower()
    m = (maturity or "").strip().lower()
    c = (chain or DEFAULT_CHAIN).strip().lower()
    if not u or not m:
        raise ValueError(f"make_book_id: empty identity (underlying={underlying!r}, maturity={maturity!r})")
    blob = f"{u}|{m}|{c}".encode("utf-8")
    return "bk_" + hashlib.sha256(blob).hexdigest()[:_BOOK_ID_LEN]


@dataclass(frozen=True)
class Book:
    """One addressable, capacity-limited rates-desk book = one distinct (underlying, maturity, chain)
    Pendle PT market. FROZEN + deterministic: the `book_id` is a content hash of the identity, so two
    Books with the same identity are byte-identical and sort/dedupe stably. Carries the market_key /
    kind for the capacity replay (A1.4) and the human-readable identity for the registry/UI."""
    book_id: str
    underlying: str
    maturity: str
    chain: str
    market_key: str          # the deep-universe market key (e.g. "PT-sUSDE-26SEP2024") — drives the replay
    kind: str                # UnderlyingKind value (always a harvestable kind for a real Book)

    def proof(self) -> Dict[str, str]:
        """String-exact view (for the per-book series schema / proof chain). Deterministic."""
        return {
            "book_id": self.book_id,
            "underlying": self.underlying,
            "maturity": self.maturity,
            "chain": self.chain,
            "market_key": self.market_key,
            "kind": self.kind,
        }


def _kind_of(market_key: str, market: dict) -> UnderlyingKind:
    """Resolve a market's UnderlyingKind, fail-CLOSED on a malformed/absent kind (a market whose kind we
    cannot confirm is NOT silently registered as a harvestable book)."""
    try:
        return UnderlyingKind(market.get("kind"))
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"books: market {market_key!r} has bad/absent kind {market.get('kind')!r} (fail-CLOSED)"
        ) from exc


def enumerate_books(deep: Optional[dict] = None) -> List[Book]:
    """Walk the deep Pendle PT universe and return the SORTED list of harvestable Books — one per
    distinct (underlying, maturity, chain) STABLE_SYNTH / STABLE_RWA market.

    LRT markets are EXCLUDED (refusal-gated — never a fundable carry book). Deterministic: SORTED by
    (underlying, maturity, market_key) so the registry is identical across runs. fail-CLOSED: a
    malformed deep dataset RAISES; a market with a bad kind RAISES (we never register a book we cannot
    classify). PURE — no clock, no network here (the caller supplies/loads `deep`)."""
    if deep is None:
        from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
        deep = pph.load()
    markets = deep.get("markets") if isinstance(deep, dict) else None
    if not isinstance(markets, dict) or not markets:
        raise ValueError("books: deep dataset has empty/invalid 'markets' (fail-CLOSED)")

    books: List[Book] = []
    seen_ids: Dict[str, str] = {}  # book_id -> market_key, to assert id uniqueness deterministically
    for market_key in sorted(markets):
        market = markets[market_key]
        kind = _kind_of(market_key, market)
        if kind in EXCLUDED_KINDS or kind not in HARVESTABLE_KINDS:
            continue  # LRT / non-harvestable → refusal-gated, never a Book
        underlying = str(market.get("underlying") or "").strip()
        maturity = str(market.get("maturity") or "").strip()
        chain = str(market.get("chain") or DEFAULT_CHAIN).strip()
        book_id = make_book_id(underlying, maturity, chain)
        # deterministic collision guard: two DISTINCT market_keys must never collapse to one book_id.
        prior = seen_ids.get(book_id)
        if prior is not None and prior != market_key:
            raise ValueError(
                f"books: book_id collision {book_id} for {prior!r} and {market_key!r} (fail-CLOSED)")
        seen_ids[book_id] = market_key
        books.append(Book(book_id=book_id, underlying=underlying, maturity=maturity, chain=chain,
                          market_key=market_key, kind=kind.value))
    books.sort(key=lambda b: (b.underlying.lower(), b.maturity, b.market_key))
    return books


def book_by_id(book_id: str, deep: Optional[dict] = None) -> Optional[Book]:
    """Look up a Book by its stable id (None if not in the harvestable universe). Deterministic."""
    for b in enumerate_books(deep):
        if b.book_id == book_id:
            return b
    return None


def main() -> int:
    """List the harvestable book registry (stable ids, LRT excluded)."""
    books = enumerate_books()
    print(f"Rates Desk — BOOK REGISTRY   (harvestable (underlying, maturity, chain) PT markets)")
    print(f"chain default: {DEFAULT_CHAIN}   ·   LRT EXCLUDED (refusal-gated)   ·   "
          f"{len(books)} addressable books\n")
    hdr = f"{'book_id':>19s}  {'underlying':>10s}  {'maturity':>12s}  {'chain':>9s}  {'market_key'}"
    print(hdr)
    print("-" * (len(hdr) + 8))
    for b in books:
        print(f"{b.book_id:>19s}  {b.underlying:>10s}  {b.maturity:>12s}  {b.chain:>9s}  {b.market_key}")
    print(f"\n{len(books)} harvestable books (ids unique, sorted, deterministic).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
