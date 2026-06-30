"""
spa_core/dfb/portfolio.py — WS-2.4 (LANE C): the READ-ONLY portfolio risk lens.

> *DeBank tells you WHAT you hold; DFB tells you HOW RISKY it is and whether the desk would hold it.*

Given a READ-ONLY address, resolve its positions in the FOLLOWED pool universe and attach, to each
position, the DFB risk overlay row (A/B/C/D class + exit-liquidity-by-size + the deterministic
would-the-desk-refuse-it verdict — all IMPORTED from `risk_overlay.overlay`, never re-derived here),
then roll the book up into a portfolio-level risk summary (% in each class, total exit-liquidity-at-
size, every REFUSE-grade / class-D holding flagged).

╔══════════════════════════════════════════════════════════════════════════════════════════════╗
║ THE HONEST DATA-SOURCE LIMIT (stated, never hidden)                                            ║
║                                                                                                ║
║ SPA is KEYLESS / READ-ONLY and carries NO multi-chain balance-reading infrastructure: there is ║
║ no funded archive-RPC, no balance-indexer API key, no `eth_call balanceOf` fan-out across 30+  ║
║ protocols × 6 chains. Reading an ARBITRARY address's full multi-chain DeFi position set keyless ║
║ is the genuinely hard part of a DeBank clone — and we do NOT fabricate it. So this lens ships   ║
║ as the FRAMEWORK + the part that IS feasible today:                                             ║
║                                                                                                ║
║   • A position SOURCE is pluggable (`PositionSource`). The only source wired today is           ║
║     `DeclaredHoldingsSource` — the caller DECLARES holdings as (pool_id, value_usd) against the ║
║     followed universe (e.g. "I hold $250k in aave-v3 USDC"). This needs no balance read and is  ║
║     100% honest: nothing is invented, the address is recorded read-only as a label.            ║
║   • Each declared position is mapped onto a real universe pool and graded with the SAME overlay ║
║     the screener uses — so the risk numbers are byte-identical to the desk's.                   ║
║   • If a balance ADAPTER ever lands (still read-only, still no signing), it implements          ║
║     `PositionSource` and drops in here unchanged — the overlay + summary code does not move.    ║
║                                                                                                ║
║ `data_source_limit` is stamped on EVERY response so the surface can NEVER imply it auto-read    ║
║ the chain. fail-CLOSED: an unreadable / malformed address or an unknown pool_id → an honest     ║
║ EMPTY position (skipped + flagged in `unresolved`), NEVER a fabricated position.                ║
╚══════════════════════════════════════════════════════════════════════════════════════════════╝

NO CUSTODY · NO SIGNING · NO PRIVATE KEY · NO WALLET-CONNECT — a read-only address STRING only. There
is no signer / transaction / key-import anywhere in this module's call graph (AST/grep-asserted by the
red-team test). It NEVER moves capital, NEVER touches the go-live track, writes nothing outside
`data/dfb/`. Behind the OWNER-GATED flag `SPA_DFB_PORTFOLIO_LENS` (default OFF) — the API surface is a
total 404 until the owner signs off on coverage honesty.

stdlib-only · deterministic · fail-CLOSED · LLM-FORBIDDEN · READ-ONLY · advisory · NO-FORK (all risk
math is `risk_overlay.overlay`, which itself imports the rates-desk engine; this module composes, it
does not grade).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

from spa_core.dfb import Pool, PoolOverlay, RiskClass
from spa_core.dfb import pool_universe
from spa_core.dfb.risk_overlay import overlay

# ── the owner-gated flag (default OFF — total 404 until the owner signs off on coverage honesty) ──
_FLAG_ENV = "SPA_DFB_PORTFOLIO_LENS"
_TRUTHY = ("1", "true", "yes", "on")


def lens_enabled() -> bool:
    """`SPA_DFB_PORTFOLIO_LENS` — the owner-gated portfolio-lens flag (default OFF). fail-CLOSED:
    anything but an explicit truthy value → OFF. When OFF the API endpoint is a total 404 (no leak)."""
    return os.environ.get(_FLAG_ENV, "").strip().lower() in _TRUTHY


# Read-only address shapes we accept as a LABEL (we validate the STRING only — we never derive a key,
# never sign, never resolve a balance from it). EVM 0x-address; permissive ENS-name; permissive other-
# chain account. Validation is purely defensive (reject path-traversal / control chars), NOT a balance
# lookup. fail-CLOSED: anything that does not look like an address → rejected (honest empty).
_EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_ENS_RE = re.compile(r"^[a-z0-9][a-z0-9\-\.]{1,251}\.eth$", re.IGNORECASE)
_GENERIC_ACCT_RE = re.compile(r"^[A-Za-z0-9:_\-\.]{8,128}$")  # other-chain accounts, bounded charset

DEFAULT_TICKETS_USD = (1_000_000, 5_000_000, 10_000_000)


def normalize_address(address: str) -> Optional[str]:
    """Validate + normalize a READ-ONLY address STRING (a label only — NEVER a key/signer). Returns
    the canonical string or None (fail-CLOSED). EVM addresses are lowercased; ENS / generic accounts
    are returned trimmed. This does NOT touch a chain — it only sanity-checks the label so a malformed
    / path-traversing string can never flow downstream."""
    if not isinstance(address, str):
        return None
    a = address.strip()
    if not a or len(a) > 256:
        return None
    if _EVM_RE.match(a):
        return a.lower()
    if _ENS_RE.match(a):
        return a.lower()
    if _GENERIC_ACCT_RE.match(a):  # other-chain account label (bounded charset, never a key)
        return a
    return None


# ── declared position (the caller's honest input — value only, NEVER read from a chain) ──
@dataclass(frozen=True)
class DeclaredHolding:
    """One holding the caller DECLARES against the followed universe — value only. NO balance read.
    `value_usd` is the caller's stated USD exposure to `pool_id`; fail-CLOSED if non-finite/negative."""
    pool_id: str
    value_usd: float


# ── a graded position (a holding × its DFB overlay row) ──
@dataclass(frozen=True)
class GradedPosition:
    pool_id: str
    protocol: str
    chain: str
    asset: str
    tier: str
    value_usd: float
    risk_class: str            # A/B/C/D/UNKNOWN — straight from the overlay, never softened
    risk_class_label: str
    refusal_verdict: str       # SAFE / REFUSE / UNKNOWN — verbatim
    refusal_reason: str
    tail_veto: bool            # the size-independent structural toxicity veto (the worst flag)
    structural_haircut: Optional[float]
    total_haircut: Optional[float]
    exit_liquidity: List[dict]  # the overlay's exit-by-size rows, served verbatim (holes flagged)
    engine_proof_hash: str
    row_hash: str
    flagged: bool
    flag_reason: Optional[str]
    as_of: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)


# ── pluggable position source (the seam a future read-only balance adapter implements unchanged) ──
class PositionSource:
    """The seam between "what does this address hold" and the risk overlay. A source returns a list of
    `DeclaredHolding` for an address. The ONLY source wired today is `DeclaredHoldingsSource` (caller-
    declared, no balance read). A future READ-ONLY balance adapter (still no signing) implements this
    same interface and drops in here without touching the overlay/summary code below."""

    name = "abstract"
    reads_chain = False  # honesty flag surfaced in the response: did this source touch a chain?

    def resolve(self, address: str) -> List[DeclaredHolding]:  # pragma: no cover - interface
        raise NotImplementedError


class DeclaredHoldingsSource(PositionSource):
    """The honest, feasible-today source: the caller DECLARES holdings (pool_id → value_usd). No
    chain read — the address is recorded read-only as a label; the holdings are the caller's input.
    fail-CLOSED: drops any holding with a malformed pool_id or a non-finite/negative value."""

    name = "declared_holdings"
    reads_chain = False

    def __init__(self, holdings: List[DeclaredHolding]):
        self._holdings = holdings

    @classmethod
    def from_raw(cls, raw_holdings) -> "DeclaredHoldingsSource":
        """Build from untrusted input (list of {pool_id, value_usd}). fail-CLOSED on every bad cell —
        a bad holding is DROPPED (never coerced to 0, never fabricated)."""
        import math
        out: List[DeclaredHolding] = []
        if isinstance(raw_holdings, list):
            for h in raw_holdings:
                if not isinstance(h, dict):
                    continue
                pid = h.get("pool_id")
                val = h.get("value_usd")
                if not isinstance(pid, str) or not pid.strip():
                    continue
                try:
                    v = float(val)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(v) or v < 0:
                    continue
                out.append(DeclaredHolding(pool_id=pid.strip(), value_usd=v))
        return cls(out)

    def resolve(self, address: str) -> List[DeclaredHolding]:
        # the address is a read-only LABEL here; the declared holdings are independent of it.
        return list(self._holdings)


def _grade_position(pool: Pool, holding: DeclaredHolding) -> GradedPosition:
    """Attach the DFB overlay (IMPORTED `risk_overlay.overlay`) to one resolved holding. The overlay
    is the SAME one the screener uses → byte-identical risk numbers. This module does NO grading."""
    ov: PoolOverlay = overlay(pool)
    return GradedPosition(
        pool_id=ov.pool_id, protocol=ov.protocol, chain=ov.chain, asset=ov.asset, tier=ov.tier,
        value_usd=holding.value_usd,
        risk_class=ov.risk_class.value,
        risk_class_label=ov.risk_class_label,
        refusal_verdict=ov.refusal.verdict,
        refusal_reason=ov.refusal.reason,
        tail_veto=ov.refusal.tail_veto,
        structural_haircut=ov.structural_haircut,
        total_haircut=ov.total_haircut,
        exit_liquidity=[
            {"ticket_usd": r.ticket_usd, "absorbable_usd": r.absorbable_usd,
             "dex_exit_frac": r.dex_exit_frac, "flagged": r.flagged}
            for r in ov.exit_liquidity
        ],
        engine_proof_hash=ov.engine_proof_hash,
        row_hash=ov.row_hash,
        flagged=ov.flagged,
        flag_reason=ov.flag_reason,
        as_of=ov.as_of,
    )


def _graded_from_overlay_dict(ov: dict, value_usd: float) -> Optional[GradedPosition]:
    """Build a GradedPosition from a PUBLISHED overlay row dict (data/dfb/pool/<id>.json), served
    VERBATIM — the SAME proof-hashed row the screener publishes (so the lens never re-runs the engine
    live and is byte-identical to the published board). fail-CLOSED: a malformed row → None."""
    if not isinstance(ov, dict):
        return None
    apy = ov.get("apy") if isinstance(ov.get("apy"), dict) else {}
    refusal = ov.get("refusal") if isinstance(ov.get("refusal"), dict) else {}
    exits = ov.get("exit_liquidity") if isinstance(ov.get("exit_liquidity"), list) else []
    pid = ov.get("pool_id")
    if not isinstance(pid, str) or not pid:
        return None
    rc = ov.get("risk_class")
    rc = rc if rc in ("A", "B", "C", "D", "UNKNOWN") else "UNKNOWN"
    return GradedPosition(
        pool_id=pid,
        protocol=str(ov.get("protocol") or ""),
        chain=str(ov.get("chain") or ""),
        asset=str(ov.get("asset") or ""),
        tier=str(ov.get("tier") or ""),
        value_usd=value_usd,
        risk_class=rc,
        risk_class_label=str(ov.get("risk_class_label") or ""),
        refusal_verdict=str(refusal.get("verdict") or "UNKNOWN"),
        refusal_reason=str(refusal.get("reason") or ""),
        tail_veto=bool(refusal.get("tail_veto")),
        structural_haircut=ov.get("structural_haircut"),
        total_haircut=ov.get("total_haircut"),
        exit_liquidity=[c for c in exits if isinstance(c, dict)],
        engine_proof_hash=str(ov.get("engine_proof_hash") or ""),
        row_hash=str(ov.get("row_hash") or ""),
        flagged=bool(ov.get("flagged")),
        flag_reason=ov.get("flag_reason"),
        as_of=ov.get("as_of"),
    )


def _summarize(positions: List[GradedPosition]) -> dict:
    """Portfolio-level risk summary — pure aggregation (NO risk math). % of value in each A/B/C/D/
    UNKNOWN class, the total declared value, the total exit-liquidity-at-size (summed absorbable per
    ticket, with holes counted as a flagged shortfall — NEVER filled), and every REFUSE / class-D /
    tail-veto holding surfaced (the risk is SURFACED, never hidden in the rollup)."""
    total_value = sum(p.value_usd for p in positions)
    by_class_value: Dict[str, float] = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0, "UNKNOWN": 0.0}
    for p in positions:
        key = p.risk_class if p.risk_class in by_class_value else "UNKNOWN"
        by_class_value[key] += p.value_usd

    by_class_pct = {
        k: (round(100.0 * v / total_value, 4) if total_value > 0 else 0.0)
        for k, v in by_class_value.items()
    }

    # exit-liquidity-at-size: per ticket, sum the concrete absorbable across positions; a flagged /
    # null cell is a HOLE — counted in `n_holes`, never summed as if it absorbed (fail-CLOSED).
    exit_at_size: Dict[int, dict] = {}
    for t in DEFAULT_TICKETS_USD:
        exit_at_size[t] = {"ticket_usd": t, "total_absorbable_usd": 0.0, "n_holes": 0,
                           "n_positions": 0}
    for p in positions:
        for cell in p.exit_liquidity:
            t = cell.get("ticket_usd")
            if t not in exit_at_size:
                continue
            slot = exit_at_size[t]
            slot["n_positions"] += 1
            absorb = cell.get("absorbable_usd")
            if cell.get("flagged") or not isinstance(absorb, (int, float)):
                slot["n_holes"] += 1
            else:
                slot["total_absorbable_usd"] += float(absorb)

    # the risk that must NEVER be hidden in a rollup: REFUSE-grade / class-D / tail-veto holdings.
    refuse_flagged = [
        {"pool_id": p.pool_id, "protocol": p.protocol, "asset": p.asset,
         "value_usd": p.value_usd, "risk_class": p.risk_class,
         "refusal_verdict": p.refusal_verdict, "refusal_reason": p.refusal_reason,
         "tail_veto": p.tail_veto}
        for p in positions
        if p.refusal_verdict == "REFUSE" or p.risk_class == "D" or p.tail_veto
    ]
    refuse_value = sum(r["value_usd"] for r in refuse_flagged)

    return {
        "total_value_usd": round(total_value, 6),
        "n_positions": len(positions),
        "value_by_risk_class": {k: round(v, 6) for k, v in by_class_value.items()},
        "pct_by_risk_class": by_class_pct,
        "exit_liquidity_at_size": [exit_at_size[t] for t in DEFAULT_TICKETS_USD],
        "n_refuse_grade_holdings": len(refuse_flagged),
        "value_in_refuse_grade_usd": round(refuse_value, 6),
        "pct_in_refuse_grade": (round(100.0 * refuse_value / total_value, 4)
                                if total_value > 0 else 0.0),
        # the loud flag: any held position the desk would REFUSE / grade D / tail-veto.
        "has_refuse_grade_holdings": bool(refuse_flagged),
        "refuse_grade_holdings": refuse_flagged,
    }


_DATA_SOURCE_LIMIT = (
    "SPA is keyless/read-only and carries NO multi-chain balance-reading infrastructure (no funded "
    "archive-RPC, no balance-indexer key). Arbitrary-address keyless balance discovery is NOT wired "
    "and is NOT fabricated. Positions here are resolved from the configured PositionSource (today: "
    "caller-DECLARED holdings against the followed universe) and graded with the same risk overlay "
    "the screener uses. The address is recorded READ-ONLY as a label — no signing, no key, no "
    "wallet-connect, no custody. A future read-only balance adapter implements PositionSource and "
    "drops in unchanged."
)

_DISCLAIMER = (
    "DFB portfolio lens — read-only risk analytics, advisory, NOT financial advice, NOT custody. "
    "Risk class / refusal / exit-liquidity come straight from the deterministic risk overlay (the "
    "same engine the desk runs); holes are flagged, never filled. No capital is moved; the go-live "
    "track is never touched."
)


def portfolio_view(
    address: str,
    source: Optional[PositionSource] = None,
    *,
    surface: Optional[dict] = None,
    universe: Optional[List[Pool]] = None,
) -> dict:
    """Build the risk-graded portfolio view for a READ-ONLY address. The single entrypoint Lane-2's
    API calls. Deterministic; fail-CLOSED everywhere; NEVER signs/moves anything.

    Steps:
      1. normalize the address STRING (a label; never a key) — bad string → honest empty view.
      2. resolve positions from `source` (default: an empty `DeclaredHoldingsSource` → empty book).
      3. map each holding to a real universe pool; unknown pool_id → `unresolved` (never fabricated).
      4. grade each resolved position with the IMPORTED overlay (no risk math here).
      5. roll up the portfolio risk summary (REFUSE/class-D holdings surfaced, never hidden).

    Returns a JSON-ready dict carrying `data_source_limit` + `address_validated` + the read-only/
    advisory stamps on EVERY response (the surface can never imply it auto-read the chain)."""
    src = source if source is not None else DeclaredHoldingsSource([])

    norm = normalize_address(address)
    if norm is None:
        # fail-CLOSED: a malformed/unsafe address → honest empty, never a crash, never a position.
        return {
            "model": "dfb_portfolio_lens",
            "is_advisory": True,
            "read_only": True,
            "no_custody": True,
            "address": None,
            "address_input": address if isinstance(address, str) else None,
            "address_validated": False,
            "position_source": src.name,
            "source_reads_chain": bool(src.reads_chain),
            "n_positions": 0,
            "positions": [],
            "unresolved": [],
            "summary": _summarize([]),
            "data_source_limit": _DATA_SOURCE_LIMIT,
            "note": "address did not validate as a read-only address label (fail-CLOSED empty view).",
            "disclaimer": _DISCLAIMER,
        }

    pools = universe if universe is not None else pool_universe.build_universe(surface=surface)
    by_id: Dict[str, Pool] = {p.pool_id: p for p in pools}

    holdings = src.resolve(norm)
    positions: List[GradedPosition] = []
    unresolved: List[dict] = []
    for h in holdings:
        pool = by_id.get(h.pool_id)
        if pool is None:
            # fail-CLOSED: a holding in a pool not in the followed universe → flagged unresolved,
            # never graded against a fabricated pool.
            unresolved.append({
                "pool_id": h.pool_id, "value_usd": h.value_usd,
                "reason": "pool_id not in the followed DFB universe (cannot risk-grade — not "
                          "fabricated).",
            })
            continue
        positions.append(_grade_position(pool, h))

    # deterministic order: by descending value then pool_id (stable, presentation-only).
    positions.sort(key=lambda p: (-p.value_usd, p.pool_id))

    return {
        "model": "dfb_portfolio_lens",
        "is_advisory": True,
        "read_only": True,
        "no_custody": True,
        "address": norm,
        "address_input": address,
        "address_validated": True,
        "position_source": src.name,
        "source_reads_chain": bool(src.reads_chain),
        "n_positions": len(positions),
        "positions": [p.to_dict() for p in positions],
        "unresolved": unresolved,
        "summary": _summarize(positions),
        "data_source_limit": _DATA_SOURCE_LIMIT,
        "note": (None if (positions or not holdings)
                 else "no declared holding resolved to a followed pool (see unresolved)."),
        "disclaimer": _DISCLAIMER,
    }


def _empty_view(address, src: PositionSource, note: str, validated: bool) -> dict:
    return {
        "model": "dfb_portfolio_lens",
        "is_advisory": True,
        "read_only": True,
        "no_custody": True,
        "address": address if validated else None,
        "address_input": address if isinstance(address, str) else None,
        "address_validated": validated,
        "position_source": src.name,
        "source_reads_chain": bool(src.reads_chain),
        "n_positions": 0,
        "positions": [],
        "unresolved": [],
        "summary": _summarize([]),
        "data_source_limit": _DATA_SOURCE_LIMIT,
        "note": note,
        "disclaimer": _DISCLAIMER,
    }


def portfolio_view_from_published(
    address: str,
    source: PositionSource,
    overlay_rows_by_id: Dict[str, dict],
) -> dict:
    """The API-path build: grade declared holdings against ALREADY-PUBLISHED overlay rows
    (data/dfb/pool/<id>.json), served VERBATIM — no live engine run, byte-identical to the published
    board. `overlay_rows_by_id` maps pool_id → the published overlay dict. Deterministic, fail-CLOSED,
    never signs/moves anything. Same honesty stamps + data-source limit as `portfolio_view`."""
    src = source

    norm = normalize_address(address)
    if norm is None:
        return _empty_view(
            address, src,
            "address did not validate as a read-only address label (fail-CLOSED empty view).",
            validated=False)

    holdings = src.resolve(norm)
    positions: List[GradedPosition] = []
    unresolved: List[dict] = []
    for h in holdings:
        ov = overlay_rows_by_id.get(h.pool_id)
        gp = _graded_from_overlay_dict(ov, h.value_usd) if ov is not None else None
        if gp is None:
            unresolved.append({
                "pool_id": h.pool_id, "value_usd": h.value_usd,
                "reason": ("pool_id not in the published DFB universe (cannot risk-grade — not "
                           "fabricated)." if ov is None
                           else "published overlay row for pool_id was malformed (fail-CLOSED)."),
            })
            continue
        positions.append(gp)

    positions.sort(key=lambda p: (-p.value_usd, p.pool_id))

    return {
        "model": "dfb_portfolio_lens",
        "is_advisory": True,
        "read_only": True,
        "no_custody": True,
        "address": norm,
        "address_input": address,
        "address_validated": True,
        "position_source": src.name,
        "source_reads_chain": bool(src.reads_chain),
        "n_positions": len(positions),
        "positions": [p.to_dict() for p in positions],
        "unresolved": unresolved,
        "summary": _summarize(positions),
        "data_source_limit": _DATA_SOURCE_LIMIT,
        "note": (None if (positions or not holdings)
                 else "no declared holding resolved to a published pool (see unresolved)."),
        "disclaimer": _DISCLAIMER,
    }


__all__ = [
    "lens_enabled",
    "normalize_address",
    "DeclaredHolding",
    "GradedPosition",
    "PositionSource",
    "DeclaredHoldingsSource",
    "portfolio_view",
    "portfolio_view_from_published",
]
