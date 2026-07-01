"""
spa_core/riskwire/facade.py — THE RISKWIRE FACADE (WS1.2, the NO-FORK unifier).

`measure(subject) -> RiskWireMeasurement` composes the three seeds' outputs into ONE coherent
measurement object per subject. It CALLS the seeds; it defines ZERO risk math (the NO-FORK rule,
AST-asserted by test_riskwire_no_fork.py). Every verdict field is COPIED from the seed that produced
it — so for any subject, RiskWire's verdict == the seed's verdict == the desk's verdict (byte-identical).

DISPATCH (by SubjectKind — each routes to exactly one seed):
  • POOL           → spa_core.dfb.risk_overlay.overlay(pool)          → PoolOverlay (A/B/C/D verbatim,
                     exit-by-size verbatim, refusal verbatim, engine_proof_hash verbatim).
  • RWA_COLLATERAL → rwa_backstop safety_board.classify + LiquidationNAVEngine  → LIQUID/THIN/
                     REDEMPTION_ONLY/UNSAFE verbatim + liquidation-NAV legs verbatim.
  • BOOK           → underwriting.report.build_report                 → the report head_hash (the book's
                     hash-anchored measurement) + the verbatim killer verdict.

THE UNIFIED A/B/C/D LETTER is a DETERMINISTIC PRESENTATION lookup on the seed's OWN verbatim verdict —
NOT a re-score. For POOL it is DFB's `RiskClass` verbatim (already the engine's verdict). For
RWA_COLLATERAL / BOOK the seed's native verdict string maps to the SAME letter by a documented pure
lookup, and the native verdict is ALWAYS preserved in `native_verdict` so nothing is laundered.

THE RED-TEAM INVARIANT (the size-down / softening exploit): a toxic subject surfaces class-D + REFUSE
because the facade READS the seed's verdict verbatim (the structural veto lives in the engine, surfaced
by DFB). The facade has NO code path that could relax a seed's REFUSE / D — it only re-presents it.
fail-CLOSED: a seed that cannot grade a subject → risk_class=UNKNOWN + flagged, NEVER a fabricated
unified grade.

stdlib-only · deterministic (`as_of` = the DATA date) · READ-ONLY · atomic (writes → data/riskwire/).
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Any, Dict, List, Optional

from spa_core.riskwire import (
    RISKWIRE_CLASS_LABELS,
    ExitLiquidityBySize,
    RiskWireClass,
    RiskWireMeasurement,
    RiskWireRefusal,
    Subject,
    SubjectKind,
)
from spa_core.riskwire import proof as rw_proof

# The seeds — IMPORTED, never forked. Every judgment is theirs.
from spa_core.dfb import Pool
from spa_core.dfb import risk_overlay as dfb_overlay
from spa_core.strategy_lab.rwa_backstop import safety_board as rwa_board
from spa_core.strategy_lab.rwa_backstop.liquidation_nav import LiquidationNAVEngine
from spa_core.strategy_lab.underwriting import report as uw_report


# ── the seed→unified A/B/C/D PRESENTATION maps (pure lookups on the seed's OWN verbatim verdict) ────
# For POOL the DFB RiskClass letter IS the unified letter (identity — the engine's own verdict).
# For RWA_COLLATERAL the Safety-Board verdict maps as follows (documented, deterministic, no arithmetic):
#   LIQUID          → A  (a real cash-like executable on-chain exit at the $1M reference)
#   THIN            → B  (a public exit exists but is shallow — own-the-floor-ish, present-but-thin)
#   REDEMPTION_ONLY → C  (no usable public on-chain exit; only the relationship-gated redemption queue)
#   UNSAFE          → D  (NO executable/documented exit — refuse, the worst class)
_RWA_VERDICT_TO_CLASS = {
    rwa_board.LIQUID: RiskWireClass.A,
    rwa_board.THIN: RiskWireClass.B,
    rwa_board.REDEMPTION_ONLY: RiskWireClass.C,
    rwa_board.UNSAFE: RiskWireClass.D,
}
# For BOOK the underwriting killer verdict maps (documented, deterministic):
#   SURVIVES_AT           → A  (the book's realized carry survives at the underwritten size)
#   DOES_NOT_SURVIVE_PAST → C  (it does not survive at size — a risk-comp/size refusal, not toxicity)
#   INSUFFICIENT_DATA     → UNKNOWN  (fail-CLOSED — never a fabricated grade on a thin track)
_BOOK_VERDICT_TO_CLASS = {
    "SURVIVES_AT": RiskWireClass.A,
    "DOES_NOT_SURVIVE_PAST": RiskWireClass.C,
    "INSUFFICIENT_DATA": RiskWireClass.UNKNOWN,
}

# The RWA reference ticket sizes the Safety Board measures at (verbatim from the seed's constants).
_RWA_SIZES = (rwa_board.SMALL_SIZE_USD, rwa_board.REFERENCE_SIZE_USD, 10_000_000.0)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# POOL subject — route to DFB overlay (the engine's own verdict), present verbatim
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _pool_from_subject(subject: Subject) -> Optional[Pool]:
    """Rebuild the DFB Pool from the subject's carried native_ref (the exact identity to hand DFB)."""
    raw = subject.native_ref.get("pool")
    if not isinstance(raw, dict):
        return None
    try:
        return Pool(**raw)
    except (TypeError, ValueError):
        return None


def _measure_pool(subject: Subject, *, prev_hash: str, risk_feed=None,
                  overlay_override=None) -> RiskWireMeasurement:
    """Measure a POOL by CALLING dfb.risk_overlay.overlay and PRESENTING its PoolOverlay verbatim.
    No risk math — every field is the overlay's own. `overlay_override` injects a PoolOverlay directly
    (tests / red-team) so the facade's presentation is exercised on a chosen seed verdict."""
    pool = _pool_from_subject(subject)
    if overlay_override is not None:
        ov = overlay_override
    elif pool is None:
        return _flagged(subject, prev_hash, seed="dfb", reason="malformed_pool_identity", as_of=None)
    else:
        ov = dfb_overlay.overlay(pool, prev_hash=rw_proof.RISKWIRE_GENESIS_PREV, risk_feed=risk_feed)

    # the unified A/B/C/D letter IS the DFB RiskClass letter — the engine's own verdict, verbatim.
    rc = RiskWireClass(ov.risk_class.value)
    exit_rows = [
        ExitLiquidityBySize(ticket_usd=r.ticket_usd, absorbable_usd=r.absorbable_usd,
                            exit_frac=r.dex_exit_frac, flagged=r.flagged)
        for r in ov.exit_liquidity
    ]
    m = RiskWireMeasurement(
        subject_id=subject.subject_id, kind=SubjectKind.POOL, display_name=subject.display_name,
        risk_class=rc, risk_class_label=RISKWIRE_CLASS_LABELS[rc],
        native_verdict=ov.risk_class.value,                     # DFB letter, verbatim
        refusal=RiskWireRefusal(verdict=ov.refusal.verdict, reason=ov.refusal.reason,
                                tail_veto=ov.refusal.tail_veto),
        exit_liquidity_by_size=exit_rows,
        liquidation_nav=None,
        structural_haircut=ov.structural_haircut, total_haircut=ov.total_haircut,
        seed="dfb", seed_proof_hash=ov.engine_proof_hash,       # the engine's OWN proof hash, verbatim
        as_of=ov.as_of, flagged=ov.flagged, flag_reason=ov.flag_reason,
        provenance=subject.provenance, prev_hash=prev_hash, row_hash="",
    )
    return rw_proof.finalize(m)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# RWA_COLLATERAL subject — route to the RWA Safety Board (its own verdict), present verbatim
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _measure_rwa(subject: Subject, *, prev_hash: str, fetcher=None, rpc_fetcher=None, onchain=False,
                 result_override=None) -> RiskWireMeasurement:
    """Measure an RWA_COLLATERAL by CALLING the LiquidationNAVEngine + safety_board.classify and
    PRESENTING the result verbatim. No risk math — the verdict and every leg are the board's own.
    `result_override` injects a LiquidationNAVResult (tests / red-team). fail-CLOSED throughout."""
    from spa_core.strategy_lab.rwa_backstop import collateral_registry as reg
    symbol = subject.native_ref.get("symbol") or subject.display_name
    asset = reg.get(symbol)
    if asset is None and result_override is None:
        return _flagged(subject, prev_hash, seed="rwa_backstop", reason="unknown_rwa_symbol", as_of=None)

    if result_override is not None:
        res = result_override
    else:
        engine = LiquidationNAVEngine(fetcher=fetcher)
        results = engine.measure_universe([asset])
        if not results:
            return _flagged(subject, prev_hash, seed="rwa_backstop",
                            reason="no_measurement", as_of=None)
        res = results[0]

    # the board's OWN verdict + the board's OWN per-asset record (both imported, never re-derived).
    verdict = rwa_board.classify(res)                        # LIQUID/THIN/REDEMPTION_ONLY/UNSAFE, verbatim
    record = rwa_board._asset_record(res)                    # the board's own row (verbatim numbers)
    rc = _RWA_VERDICT_TO_CLASS.get(verdict, RiskWireClass.UNKNOWN)

    # exit-by-size legs — copied VERBATIM from the board's measured sized exits (no recompute).
    exit_rows: List[ExitLiquidityBySize] = []
    for size in _RWA_SIZES:
        se = res.sized.get(size)
        frac = se.liq_nav_frac if se is not None else None
        absorb = (round(frac * res.marketing_nav_usd, 6) if frac is not None else None)
        exit_rows.append(ExitLiquidityBySize(
            ticket_usd=int(size), absorbable_usd=absorb, exit_frac=frac, flagged=(se is None)))

    # the liquidation-NAV block — the board's headline numbers, verbatim.
    liq_nav = {
        "verdict": verdict,
        "liq_nav_frac_100k": record.get("liq_nav_frac_100k"),
        "liq_nav_frac_1m": record.get("liq_nav_frac_1m"),
        "liq_nav_frac_10m": record.get("liq_nav_frac_10m"),
        "liq_nav_usd_1m": record.get("liq_nav_usd_1m"),
        "marketing_vs_liq_gap_pct_1m": record.get("marketing_vs_liq_gap_pct_1m"),
        "on_chain_dex_liquidity_usd": record.get("on_chain_dex_liquidity_usd"),
        "n_dex_pools": record.get("n_dex_pools"),
        "transfer_restricted": record.get("transfer_restricted"),
        "redemption_documented": record.get("redemption_documented"),
        "binding_leg_1m": record.get("binding_leg_1m"),
    }

    # a REFUSE-shaped refusal presentation from the board verdict (verbatim mapping, no re-derivation):
    #   UNSAFE → REFUSE + tail_veto (no executable/documented exit — the worst, size-independent).
    #   REDEMPTION_ONLY → REFUSE (no usable public on-chain exit; only the relationship-gated queue).
    #   THIN / LIQUID → SAFE.
    if verdict == rwa_board.UNSAFE:
        refusal = RiskWireRefusal(verdict="REFUSE", reason="unsafe_no_executable_exit", tail_veto=True)
    elif verdict == rwa_board.REDEMPTION_ONLY:
        refusal = RiskWireRefusal(verdict="REFUSE", reason="redemption_gated_no_onchain_exit",
                                  tail_veto=False)
    else:
        refusal = RiskWireRefusal(verdict="SAFE", reason=verdict.lower(), tail_veto=False)

    flagged = bool(res.data_gaps) or any(r.flagged for r in exit_rows)
    flag_reason = ("rwa_data_gaps: " + ",".join(res.data_gaps)) if res.data_gaps else (
        "partial_sized_exit_coverage" if flagged else None)

    m = RiskWireMeasurement(
        subject_id=subject.subject_id, kind=SubjectKind.RWA_COLLATERAL,
        display_name=subject.display_name,
        risk_class=rc, risk_class_label=RISKWIRE_CLASS_LABELS[rc],
        native_verdict=verdict,                                 # the board verdict, verbatim
        refusal=refusal, exit_liquidity_by_size=exit_rows, liquidation_nav=liq_nav,
        structural_haircut=None, total_haircut=None,
        seed="rwa_backstop", seed_proof_hash=_rwa_seed_hash(record),
        as_of=(res.generated_at or None), flagged=flagged, flag_reason=flag_reason,
        provenance=subject.provenance, prev_hash=prev_hash, row_hash="",
    )
    return rw_proof.finalize(m)


def _rwa_seed_hash(record: dict) -> str:
    """A per-asset anchor over the board's OWN verbatim record. RISKWIRE adds no risk math — this is a
    plain sha256 over the board's row so the RWA measurement carries a reproducible seed anchor
    (the Safety Board writes a whole-report file, not a per-row hash, so we anchor its verbatim row)."""
    import hashlib
    import json
    blob = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# BOOK subject — route to the underwriting report (its hash-anchored verdict), present verbatim
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _measure_book(subject: Subject, *, prev_hash: str, realized_path=None, depth_path=None,
                  refusal_path=None, generated_at=None) -> RiskWireMeasurement:
    """Measure a BOOK by CALLING underwriting.report.build_report and PRESENTING its head_hash + the
    verbatim killer verdict. No risk math — the report copies Lane B's verdict verbatim; RISKWIRE reads
    THAT verbatim again. fail-CLOSED: a missing/corrupt realized file → UNKNOWN + flagged (never a grade)."""
    report, err = uw_report.build_report(
        realized_path=realized_path, depth_path=depth_path, refusal_path=refusal_path,
        generated_at=generated_at)
    if err is not None or report is None:
        return _flagged(subject, prev_hash, seed="underwriting",
                        reason=f"report_unavailable:{err}", as_of=None)

    # pull the realized (killer verdict) section — the load-bearing verbatim verdict.
    realized_section = next((s for s in report.get("sections", [])
                             if s.get("section_id") == "realized"), {})
    native_verdict = realized_section.get("verdict") or "INSUFFICIENT_DATA"
    rc = _BOOK_VERDICT_TO_CLASS.get(native_verdict, RiskWireClass.UNKNOWN)
    as_of = realized_section.get("as_of")

    liq_nav = {
        "verdict": native_verdict,
        "survives_at_aum_usd": realized_section.get("survives_at_aum_usd"),
        "floor_plus_bps_at_5M": realized_section.get("floor_plus_bps_at_5M"),
        "report_head_hash": report.get("head_hash"),
        "n_sections": report.get("n_sections"),
        "published": report.get("published"),
    }
    flagged = (native_verdict == "INSUFFICIENT_DATA")
    m = RiskWireMeasurement(
        subject_id=subject.subject_id, kind=SubjectKind.BOOK, display_name=subject.display_name,
        risk_class=rc, risk_class_label=RISKWIRE_CLASS_LABELS[rc],
        native_verdict=native_verdict, refusal=None, exit_liquidity_by_size=[],
        liquidation_nav=liq_nav, structural_haircut=None, total_haircut=None,
        seed="underwriting", seed_proof_hash=report.get("head_hash", ""),  # the book's hash anchor
        as_of=as_of, flagged=flagged,
        flag_reason=("insufficient_realized_track" if flagged else None),
        provenance=subject.provenance, prev_hash=prev_hash, row_hash="",
    )
    return rw_proof.finalize(m)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# fail-CLOSED measurement — UNKNOWN grade, never a fabricated number (still proof-chained)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _flagged(subject: Subject, prev_hash: str, *, seed: str, reason: str,
             as_of: Optional[str]) -> RiskWireMeasurement:
    m = RiskWireMeasurement(
        subject_id=subject.subject_id, kind=subject.kind, display_name=subject.display_name,
        risk_class=RiskWireClass.UNKNOWN, risk_class_label=RISKWIRE_CLASS_LABELS[RiskWireClass.UNKNOWN],
        native_verdict="UNKNOWN",
        refusal=RiskWireRefusal(verdict="UNKNOWN", reason=reason, tail_veto=False),
        exit_liquidity_by_size=[], liquidation_nav=None,
        structural_haircut=None, total_haircut=None,
        seed=seed, seed_proof_hash="", as_of=as_of, flagged=True, flag_reason=reason,
        provenance=subject.provenance, prev_hash=prev_hash, row_hash="",
    )
    return rw_proof.finalize(m)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# the public entrypoint
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def measure(subject: Subject, *, prev_hash: str = rw_proof.RISKWIRE_GENESIS_PREV,
            **seed_kwargs) -> RiskWireMeasurement:
    """Measure ONE subject → a unified RiskWireMeasurement, by dispatching on `subject.kind` to the
    seed that grades it and PRESENTING the seed's verdict verbatim. Deterministic / fail-CLOSED.

    `seed_kwargs` pass-through to the seed (tests / red-team): POOL accepts `risk_feed` /
    `overlay_override`; RWA accepts `fetcher` / `rpc_fetcher` / `onchain` / `result_override`; BOOK
    accepts `realized_path` / `depth_path` / `refusal_path` / `generated_at`."""
    if subject.kind == SubjectKind.POOL:
        return _measure_pool(
            subject, prev_hash=prev_hash,
            risk_feed=seed_kwargs.get("risk_feed"),
            overlay_override=seed_kwargs.get("overlay_override"))
    if subject.kind == SubjectKind.RWA_COLLATERAL:
        return _measure_rwa(
            subject, prev_hash=prev_hash,
            fetcher=seed_kwargs.get("fetcher"), rpc_fetcher=seed_kwargs.get("rpc_fetcher"),
            onchain=seed_kwargs.get("onchain", False),
            result_override=seed_kwargs.get("result_override"))
    if subject.kind == SubjectKind.BOOK:
        return _measure_book(
            subject, prev_hash=prev_hash,
            realized_path=seed_kwargs.get("realized_path"),
            depth_path=seed_kwargs.get("depth_path"),
            refusal_path=seed_kwargs.get("refusal_path"),
            generated_at=seed_kwargs.get("generated_at"))
    # fail-CLOSED: an unknown kind is never fabricated a grade.
    return _flagged(subject, prev_hash, seed="unknown", reason="unknown_subject_kind", as_of=None)


def measure_all(subjects: List[Subject], *, risk_feed=None, onchain: bool = False,
                **seed_kwargs) -> List[RiskWireMeasurement]:
    """Measure every subject, proof-CHAINED (each row's prev_hash = the previous row's row_hash; genesis
    '0'*64). Deterministic order = the subject-registry order. The DFB risk_feed is built ONCE and shared
    across every POOL subject (the live X/ETH peg history is pulled a single time)."""
    feed = risk_feed if risk_feed is not None else dfb_overlay._default_risk_feed()
    raw: List[RiskWireMeasurement] = []
    for subject in subjects:
        # measured with genesis prev_hash; proof.chain() re-links the whole list into one chain below.
        m = measure(subject, prev_hash=rw_proof.RISKWIRE_GENESIS_PREV,
                    risk_feed=feed, onchain=onchain, **seed_kwargs)
        raw.append(m)
    return rw_proof.chain(raw)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# writer — data/riskwire/measurements.json (list) + data/riskwire/subject/<id>.json (detail)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def build_and_write(
    *, write: bool = True, data_dir=None, surface=None, include_breadth: Optional[bool] = None,
    subjects=None, risk_feed=None, onchain: bool = False, generated_at=None, **seed_kwargs,
) -> dict:
    """Build the subject registry, measure every subject, and produce the unified MEASUREMENTS snapshot
    artifact (proof-chained + artifact-anchored). WS1.2 owns the facade + measurement content; the proof
    plumbing / on-disk artifact (schema, hashing, atomic write, per-subject detail) is WS1.4's
    `proof` module — this delegates there so there is ONE coherent snapshot, not two competing writers.

    READ-ONLY everywhere except data/riskwire/. Deterministic; same inputs → byte-identical artifact.
    `generated_at` (ISO) is an explicit input for determinism; defaults to UTC now when writing."""
    import datetime

    from spa_core.riskwire import subjects as rw_subjects

    subs = subjects if subjects is not None else rw_subjects.build_registry(
        surface=surface, include_breadth=include_breadth)
    # measure every subject (measure_all proof-chains; build_measurements_artifact re-chains + seals).
    measurements = measure_all(subs, risk_feed=risk_feed, onchain=onchain, **seed_kwargs)
    as_of = next((m.as_of for m in measurements if m.as_of), None)
    gen_at = generated_at or datetime.datetime.now(datetime.timezone.utc).isoformat()

    if write:
        return rw_proof.write_measurements(measurements, generated_at=gen_at, as_of=as_of,
                                           data_dir=data_dir)
    return rw_proof.build_measurements_artifact(measurements, generated_at=gen_at, as_of=as_of)


# ── CLI ────────────────────────────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python3 -m spa_core.riskwire.facade",
        description="RISKWIRE facade — the unified NO-FORK measurement snapshot over all subjects.")
    ap.add_argument("--no-write", action="store_true", help="build in memory, write nothing")
    args = ap.parse_args(argv)
    res = build_and_write(write=not args.no_write)
    print(f"RISKWIRE snapshot — {res.get('n_measurements')} subjects  as_of={res.get('as_of')}")
    print(f"  flagged={res.get('n_flagged')}  refused={res.get('n_refused')}  "
          f"unknown={res.get('n_unknown')}")
    print(f"  head_hash={res.get('head_hash')}  artifact_hash={res.get('artifact_hash')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
