#!/usr/bin/env python3
"""D1 — END-TO-END validation of the TWO-TIER kill-switch INSIDE ``run_cycle``.

ADR-034 introduced a two-tier drawdown ladder:

  * SOFT de-risk  (drawdown ∈ [5%, 15%))  → ``apply_soft_derisk_gate`` caps every
    protocol target to ``min(target, currently-held USD)`` — NO new protocol, NO
    increase of a held one (hold / reduce only).
  * HARD kill     (drawdown ≥ 15%)         → ``apply_kill_switch_override`` forces
    the all-cash book; the soft gate is a no-op (``_derisk_active`` is False).

The unit tests for ``kill_switch.py`` / ``cycle_gates.py`` pass, but the
*composition* with ALLOC-002 (``_compliant_target``) and the rebalance diff was
UNVALIDATED. This module drives the real ``run_cycle`` end-to-end against a
per-test TEMP sandbox and asserts the INTEGRATED post-cycle book — not just the
gate's intermediate output.

THE HEADLINE BUG (D1-T1), now FIXED
===================================
Inside ``run_cycle`` the stage order is:
  (1) ``apply_kill_switch_override``      — HARD all-cash
  (2) ``apply_soft_derisk_gate``          — cap each target to held ("no increase")
  (3) ``_compliant_target`` (ALLOC-002)   — collapse to ≤8 protocols AND
                                            REDISTRIBUTE freed capital across the
                                            survivor book.

Stage (3) ran AFTER the soft cap and, when it collapsed an over-diversified book,
REDISTRIBUTED freed capital across the survivors via the rebalancer / safe
fallback — RE-GROWING a held protocol far above its held size and RE-OPENING
un-held protocols, silently UNDOING the soft "no-new / no-increase" guarantee.
Reproduced E2E: ``aave_v3`` $12,000 held → $23,250, and two brand-new protocols
opened — while in an 8% (SOFT) drawdown.

THE FIX (minimal, cap-preserving — NO stage reorder)
====================================================
After ``_compliant_target`` collapses the book, ``run_cycle`` RE-APPLIES
``apply_soft_derisk_gate`` (idempotent; a no-op when not de-risk-active, so the
non-derisk path is byte-unchanged). The redistribution can no longer push any
protocol above its held size nor open a new one while in the soft band.

CRITICAL GUARDRAIL — every cycle here runs ENTIRELY against a per-test TEMP
sandbox ``data_dir`` (explicit + NON-canonical → the write-interlock honours it
verbatim) AND ``allow_live_write=False``. The live repo ``data/`` (2026-06-25
track-corruption hazard) is NEVER read or written; a dedicated guard test fails
loudly if a resolved dir would ever be ``<repo>/data``.

Hermetic: orchestrator / allocator / risk-scorer / track-persister are
in-process network-free fakes; the timestamp is pinned; logging silenced.
stdlib-only, deterministic, fail-CLOSED, atomic.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from spa_core.paper_trading import cycle_runner as _cr
from spa_core.paper_trading._cycle_io import (
    EQUITY_FILENAME,
    POSITIONS_FILENAME,
    TRADES_FILENAME,
    _DEFAULT_DATA_DIR,
    resolve_data_dir,
)
from spa_core.governance.kill_switch import (
    DERISK_STATUS_FILENAME,
    DRAWDOWN_THRESHOLD_PCT,
    SOFT_DERISK_THRESHOLD_PCT,
    TIER_HARD_KILL,
    TIER_NONE,
    TIER_SOFT_DERISK,
)

CAP = 100_000.0
_ANCHOR = date(2026, 6, 10)  # PAPER_REAL_START — bars on/after this are evidenced
_NOW = datetime(2026, 6, 18, 8, 0, tzinfo=timezone.utc)


# ── Hermetic fakes ────────────────────────────────────────────────────────────


def _make_orch(universe):
    """Network-free orchestrator fake. ``universe`` = list[(proto, tier)]."""

    def _orch(_data_dir):  # noqa: ANN001 — matches orchestrator_fn signature
        adapters = [
            {
                "protocol": p,
                "id": p,
                "apy_pct": 4.0,
                "tvl_usd": 1e8,
                "tier": t,
                "status": "ok",
                "chain": f"chain_{p}",  # per-pool chain → no false single-chain cap
            }
            for p, t in universe
        ]
        return SimpleNamespace(adapters=adapters, status="ok", data_freshness="live")

    return _orch


def _make_alloc(target_usd):
    """Fake allocator returning a fixed target allocation."""

    class _Alloc:
        def allocate(self):  # noqa: D401 — fake
            return SimpleNamespace(
                target_usd=dict(target_usd),
                target_weights={p: v / CAP for p, v in target_usd.items()},
                expected_apy_pct=4.0,
                model_used="risk_adjusted",
                strategy_loop_active=False,
            )

    return _Alloc()


def _equity_curve(closes: list[float]) -> list[dict]:
    """Evidenced daily bars (dated >= anchor, no negative honesty label).

    A bar dated on/after ``PAPER_REAL_START`` with a ``close_equity`` and no
    explicit negative label counts as evidenced (``track_evidence`` backward-compat
    rule) — so the drawdown the kill-switch/de-risk computes is exactly
    ``(max(closes) - closes[-1]) / max(closes) * 100``.
    """
    return [
        {
            "date": date.fromordinal(_ANCHOR.toordinal() + i).isoformat(),
            "close_equity": float(v),
            "open_equity": float(v),
        }
        for i, v in enumerate(closes)
    ]


def _closes_for_drawdown(dd_pct: float, peak: float = 102_000.0) -> list[float]:
    """A SHORT evidenced series whose peak→current drawdown == ``dd_pct`` exactly.

    Used for classifier/trigger-level assertions (``drawdown_tier`` /
    ``KillSwitchChecker``) where the per-day step size is irrelevant.
    """
    current = peak * (1.0 - dd_pct / 100.0)
    return [100_000.0, peak, peak - 1_000.0, current]


def _gradual_closes_for_drawdown(dd_pct: float, peak: float = 102_000.0) -> list[float]:
    """A GRADUAL evidenced series reaching ``dd_pct`` peak→current drawdown in
    small (≤1.5%/day) steps.

    The integrated ``run_cycle`` runs the DailyLimits gate (DL-01 daily-loss ≤2%,
    DL-02 peak-drawdown ≤10%) BEFORE the de-risk / kill stages — a sharp single
    drop would HALT the cycle before the gate under test ever runs. A gradual
    decline keeps each daily step within DL-01 so the cycle reaches the de-risk
    composition we are validating.

    NOTE (finding): because DL-02 HALTs at >10% drawdown, the integrated cycle
    can only exercise the SOFT band up to ~10%. The 10–15% upper SOFT band and
    the ≥15% HARD-via-drawdown kill are PRE-EMPTED by DL-02 in the full cycle, so
    those boundaries are validated at the classifier level (see D1-T2).
    """
    current = peak * (1.0 - dd_pct / 100.0)
    closes = [100_000.0, peak]
    v = peak
    while v > current * 1.0001:
        v = max(current, v * 0.985)  # ≤1.5%/day → within DL-01's 2% limit
        closes.append(round(v, 2))
    return closes


def _seed_sandbox(td: Path, *, held: dict, closes: list[float]) -> None:
    td.mkdir(parents=True, exist_ok=True)
    (td / POSITIONS_FILENAME).write_text(
        json.dumps({"positions": held, "cash_usd": CAP - sum(held.values())}),
        encoding="utf-8",
    )
    (td / EQUITY_FILENAME).write_text(
        json.dumps({"source": "cycle_runner", "daily": _equity_curve(closes)}),
        encoding="utf-8",
    )


def _run(td: Path, *, universe, target, closes, held, now=_NOW):
    return _cr.run_cycle(
        data_dir=str(td),
        now=now,
        orchestrator_fn=_make_orch(universe),
        allocator=_make_alloc(target),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,
        write=True,
        allow_live_write=False,
    )


def _final_book(td: Path, result) -> dict:
    """The book the cycle actually committed this run.

    Prefer the recorded rebalance trade's ``to_allocation`` (the exact target the
    diff & ``effective_positions`` used). When no trade was recorded, fall back to
    the persisted ``current_positions.json`` book.
    """
    trades = []
    tp = td / TRADES_FILENAME
    if tp.exists():
        try:
            trades = json.loads(tp.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            trades = []
    if isinstance(trades, list) and trades and trades[-1].get("type") == "rebalance":
        return {k: float(v) for k, v in (trades[-1].get("to_allocation") or {}).items()}
    pos = json.loads((td / POSITIONS_FILENAME).read_text(encoding="utf-8"))
    return {k: float(v) for k, v in (pos.get("positions") or {}).items()}


def _no_increase_violations(book: dict, held: dict) -> list[str]:
    """Protocols in ``book`` that VIOLATE the de-risk no-new / no-increase rule."""
    out: list[str] = []
    for proto, usd in book.items():
        if usd <= 0:
            continue
        held_usd = float(held.get(proto, 0.0))
        if held_usd <= 0.0:
            out.append(f"NEW protocol opened under de-risk: {proto}=${usd:,.0f}")
        elif usd > held_usd + 0.01:
            out.append(
                f"increased above held: {proto} ${held_usd:,.0f} -> ${usd:,.0f}"
            )
    return out


# A 5×T1 + 4×T2 universe (9 protocols). A held book across all nine trips the
# enforcer's `max_protocols` (8) — so `_compliant_target` collapses + redistributes
# — while a T1-dominant (~58%) shape keeps the soft-capped book PASSING the
# RiskPolicy gate (NOT policy_blocked), which is what lets the buggy ALLOC-002
# redistribution actually run end-to-end.
_UNIVERSE_9 = [
    ("aave_v3", "T1"),
    ("aave_arb", "T1"),
    ("aave_op", "T1"),
    ("aave_base", "T1"),
    ("compound_v3", "T1"),
    ("yearn_v3", "T2"),
    ("euler_v2", "T2"),
    ("morpho_blue", "T2"),
    ("maple", "T2"),
]
_HELD_9 = {
    "aave_v3": 12_000.0,
    "aave_arb": 12_000.0,
    "aave_op": 12_000.0,
    "aave_base": 12_000.0,
    "compound_v3": 10_000.0,
    "yearn_v3": 8_000.0,
    "euler_v2": 8_000.0,
    "morpho_blue": 7_000.0,
    "maple": 7_000.0,
}  # T1=58k, T2=30k, cash=12k — 9 protocols (> max_protocols 8)


# ═══════════════════════════════════════════════════════════════════════════════
# SANDBOX GUARD — defense against the track-corruption hazard
# ═══════════════════════════════════════════════════════════════════════════════


def test_sandbox_guard_never_resolves_to_live_data(tmp_path):
    """Every dir this module uses MUST resolve to the tmp sandbox, NEVER the
    canonical repo ``data/``."""
    canon = _DEFAULT_DATA_DIR.resolve()

    resolved, redirected = resolve_data_dir(str(tmp_path), allow_live_write=True)
    assert resolved.resolve() == tmp_path.resolve()
    assert resolved.resolve() != canon, "sandbox resolved to LIVE data/ — abort!"
    assert redirected is False  # explicit non-canonical dir → honoured verbatim

    resolved2, redirected2 = resolve_data_dir(None, allow_live_write=False)
    assert resolved2.resolve() != canon, "default run targeted LIVE data/ — abort!"
    assert redirected2 is True


# ═══════════════════════════════════════════════════════════════════════════════
# D1-T1 — the HEADLINE: ALLOC-002 redistribution must NOT undo the soft cap
# ═══════════════════════════════════════════════════════════════════════════════


def test_d1t1_alloc002_redistribution_preserves_no_increase(tmp_path):
    """SOFT band + an allocator wanting NEW + INCREASED protocols + an
    over-diversified (>8) held book that forces the ALLOC-002 collapse +
    redistribution.

    Asserts the FINAL committed book (AFTER ALLOC-002 redistribution AND the
    rebalance diff — not merely after the soft gate): NO un-held protocol > 0,
    NO held protocol above its held USD. This is the regression guard for the
    re-grow bug the fix closes.
    """
    logging.disable(logging.CRITICAL)
    try:
        td = tmp_path / "d1t1"
        held = dict(_HELD_9)
        # 8% drawdown → SOFT band (gradual so DailyLimits does not HALT first).
        closes = _gradual_closes_for_drawdown(8.0)
        _seed_sandbox(td, held=held, closes=closes)
        # Allocator WANTS to increase every held protocol to $18k (an increase)
        # and the universe also offers protocols not yet held.
        target = {p: 18_000.0 for p, _ in _UNIVERSE_9}

        result = _run(td, universe=_UNIVERSE_9, target=target, closes=closes, held=held)

        # Preconditions that make this a meaningful exercise of the bug path:
        ds = json.loads((td / DERISK_STATUS_FILENAME).read_text(encoding="utf-8"))
        assert ds["tier"] == TIER_SOFT_DERISK, "must be in the SOFT band"
        assert not result.kill_switch_active, "HARD kill must NOT own this case"
        assert not any("blocked_by_policy" in n for n in result.notes), (
            "policy_blocked would SKIP _compliant_target → bug path not exercised"
        )
        assert any(
            "ALLOC-002: raw allocator" in n for n in result.notes
        ), "the ALLOC-002 collapse+redistribute must actually have run"

        book = _final_book(td, result)
        violations = _no_increase_violations(book, held)
        assert not violations, (
            "ALLOC-002 redistribution UNDID the soft de-risk no-increase guarantee:\n  "
            + "\n  ".join(violations)
            + f"\n  (held={held})\n  (final book={ {k: round(v) for k, v in book.items() if v > 0} })"
        )
    finally:
        logging.disable(logging.NOTSET)


def test_d1t1_no_new_protocol_opened_under_softderisk(tmp_path):
    """A held book SMALLER than the allocator's appetite: every held protocol is
    held + the allocator wants brand-new ones — assert NOT ONE un-held protocol
    appears in the final book while de-risked."""
    logging.disable(logging.CRITICAL)
    try:
        td = tmp_path / "d1t1_new"
        held = dict(_HELD_9)
        closes = _gradual_closes_for_drawdown(9.5)  # SOFT (≤10% so no DL-02 HALT)
        _seed_sandbox(td, held=held, closes=closes)
        # The allocator additionally wants two protocols NOT in the held book.
        target = {p: 18_000.0 for p, _ in _UNIVERSE_9}
        target["spark_susds"] = 15_000.0  # never held
        target["morpho_steakhouse"] = 12_000.0  # never held
        universe = _UNIVERSE_9 + [("spark_susds", "T2"), ("morpho_steakhouse", "T1")]

        result = _run(td, universe=universe, target=target, closes=closes, held=held)

        book = _final_book(td, result)
        opened_new = [
            p for p, v in book.items() if v > 0 and float(held.get(p, 0.0)) <= 0.0
        ]
        assert not opened_new, f"new protocols opened under de-risk: {opened_new}"
    finally:
        logging.disable(logging.NOTSET)


# ═══════════════════════════════════════════════════════════════════════════════
# D1-T2 — the tier ladder on the INTEGRATED cycle output
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "dd_pct, expect_tier, expect_kill_trigger",
    [
        (4.9, TIER_NONE, False),          # below soft → no action
        (5.0, TIER_SOFT_DERISK, False),   # exactly SOFT boundary (>=) → SOFT
        (9.99, TIER_SOFT_DERISK, False),  # high SOFT band → still SOFT, no kill
        (14.9, TIER_SOFT_DERISK, False),  # just below HARD → still SOFT
        (15.0, TIER_HARD_KILL, False),    # tier-boundary GAP: classifier says
        #                                   HARD_KILL (>=) but the kill TRIGGER
        #                                   needs strict >15% → does NOT fire.
        (16.0, TIER_HARD_KILL, True),     # above HARD → kill trigger fires.
    ],
)
def test_d1t2_tier_ladder_classifier_and_trigger(tmp_path, dd_pct, expect_tier, expect_kill_trigger):
    """The documented tier ladder + the kill-TRIGGER, asserted at the boundaries.

    ``drawdown_tier`` is the documented classifier (half-open intervals, all
    ``>=``); ``KillSwitchChecker.check_drawdown_trigger`` is the actual all-cash
    authority. They AGREE everywhere EXCEPT at exactly 15.0%, where the classifier
    says ``HARD_KILL`` (``>=``) but the trigger uses STRICT ``>`` (so 15.0% does
    NOT close the book). This is intentional (boundary preserved by the kill
    trigger) and is encoded explicitly here — see the owner heads-up in the report.

    These boundaries are validated at the classifier/trigger level (not via the
    full cycle) because the cycle's DailyLimits gate (DL-02, 10% drawdown) HALTs
    the cycle before any drawdown ≥10% reaches the de-risk/kill stages.
    """
    from spa_core.governance.kill_switch import drawdown_tier, KillSwitchChecker

    bars = _equity_curve(_closes_for_drawdown(dd_pct))
    tier, _ = drawdown_tier(bars)
    assert tier == expect_tier, f"dd={dd_pct}%: tier {tier} != {expect_tier}"

    checker = KillSwitchChecker(data_dir=str(tmp_path))
    triggered, _ = checker.check_drawdown_trigger(bars)
    assert triggered is expect_kill_trigger, (
        f"dd={dd_pct}%: kill trigger {triggered} != {expect_kill_trigger}"
    )

    # The SOFT de-risk signal fires EXACTLY in the band where the HARD kill does
    # NOT (mutually exclusive) — never both at once.
    derisk_active, _ = checker.is_derisk_active(bars)
    assert derisk_active is (expect_tier == TIER_SOFT_DERISK)
    assert not (derisk_active and triggered), "SOFT + HARD both active at once"


def test_d1t2_integrated_softband_active_and_no_kill(tmp_path):
    """Integrated cycle in the REACHABLE SOFT band (gradual ≤10% drawdown): the
    de-risk gate is active, the HARD kill is OFF, and the two never coincide."""
    logging.disable(logging.CRITICAL)
    try:
        td = tmp_path / "d1t2_soft"
        held = dict(_HELD_9)
        closes = _gradual_closes_for_drawdown(8.0)
        _seed_sandbox(td, held=held, closes=closes)
        target = {p: 18_000.0 for p, _ in _UNIVERSE_9}

        result = _run(td, universe=_UNIVERSE_9, target=target, closes=closes, held=held)

        ds = json.loads((td / DERISK_STATUS_FILENAME).read_text(encoding="utf-8"))
        assert ds["tier"] == TIER_SOFT_DERISK and ds["active"] is True
        assert result.kill_switch_active is False
        assert not (result.kill_switch_active and ds["active"])
    finally:
        logging.disable(logging.NOTSET)


def test_d1t2_hard_kill_makes_soft_gate_a_noop(tmp_path):
    """HARD kill (driven via the MANUAL trigger so DailyLimits' 10%-drawdown HALT
    does not preempt it) → the all-cash override runs FIRST; the subsequent soft
    gate sees an already-zeroed target and changes nothing. Assert the integrated
    book is all-cash, ``kill_switch_active`` owns it, and ``derisk active`` is
    False (the two never coincide)."""
    logging.disable(logging.CRITICAL)
    try:
        td = tmp_path / "d1t2_hard"
        held = dict(_HELD_9)
        # A healthy curve (no DL HALT); the HARD kill comes from the manual file.
        closes = _gradual_closes_for_drawdown(2.0)
        _seed_sandbox(td, held=held, closes=closes)
        (td / "kill_switch_active.json").write_text(
            json.dumps({"active": True, "reason": "D1-T2 manual HARD kill"}),
            encoding="utf-8",
        )
        target = {p: 18_000.0 for p, _ in _UNIVERSE_9}

        result = _run(td, universe=_UNIVERSE_9, target=target, closes=closes, held=held)

        assert result.kill_switch_active is True
        ds = json.loads((td / DERISK_STATUS_FILENAME).read_text(encoding="utf-8"))
        assert ds["active"] is False, "soft de-risk must be a no-op under HARD kill"
        book = _final_book(td, result)
        assert not {k: v for k, v in book.items() if v > 0}, "HARD kill must be all-cash"
    finally:
        logging.disable(logging.NOTSET)


# ═══════════════════════════════════════════════════════════════════════════════
# D1-T3 — write-interlock × de-risk + the edge-triggered alert
# ═══════════════════════════════════════════════════════════════════════════════


def test_d1t3_derisk_status_lands_in_redirected_dir_not_live(tmp_path, monkeypatch):
    """When the write-interlock REDIRECTS writes (canonical dir requested WITHOUT
    opt-in), the soft gate still computes and ``derisk_status.json`` is written to
    the REDIRECTED sandbox — NEVER the live track.

    We point the interlock's redirect target at our tmp sandbox via ``SPA_DATA_DIR``
    and request the canonical dir with ``allow_live_write=False``.
    """
    logging.disable(logging.CRITICAL)
    try:
        redir = tmp_path / "redirected"
        redir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("SPA_DATA_DIR", str(redir))
        monkeypatch.delenv("SPA_ALLOW_LIVE_WRITE", raising=False)

        # Sanity: a canonical request with no opt-in resolves to the redirected
        # sandbox, never the live data/ dir.
        resolved, redirected = resolve_data_dir(None, allow_live_write=False)
        assert redirected is True
        assert resolved.resolve() == redir.resolve()
        assert resolved.resolve() != _DEFAULT_DATA_DIR.resolve()

        held = dict(_HELD_9)
        closes = _gradual_closes_for_drawdown(8.0)  # SOFT (no DL HALT)
        _seed_sandbox(redir, held=held, closes=closes)
        target = {p: 18_000.0 for p, _ in _UNIVERSE_9}

        # Snapshot the live track's de-risk file mtime/existence so we can prove
        # this run never touched it.
        live_ds = _DEFAULT_DATA_DIR / DERISK_STATUS_FILENAME
        live_existed = live_ds.exists()
        live_mtime = live_ds.stat().st_mtime_ns if live_existed else None

        # data_dir=None → interlock reroutes to the redirected sandbox.
        result = _cr.run_cycle(
            data_dir=None,
            now=_NOW,
            orchestrator_fn=_make_orch(_UNIVERSE_9),
            allocator=_make_alloc(target),
            risk_scorer_fn=lambda d: None,
            track_persister_fn=lambda d: None,
            write=True,
            allow_live_write=False,
        )

        # The de-risk computation landed in the REDIRECTED dir.
        assert (redir / DERISK_STATUS_FILENAME).exists()
        ds = json.loads((redir / DERISK_STATUS_FILENAME).read_text(encoding="utf-8"))
        assert ds["tier"] == TIER_SOFT_DERISK and ds["active"] is True
        assert redir.resolve() != _DEFAULT_DATA_DIR.resolve()
        # The live track's de-risk file was NOT created or modified by this run.
        if live_existed:
            assert live_ds.stat().st_mtime_ns == live_mtime, (
                "redirected cycle modified the LIVE derisk_status.json — abort!"
            )
        else:
            assert not live_ds.exists(), (
                "redirected cycle created a LIVE derisk_status.json — abort!"
            )
        assert any("soft_derisk_active" in n for n in result.notes)
    finally:
        logging.disable(logging.NOTSET)


def test_d1t3_edge_alert_fires_exactly_once_then_clears(tmp_path, monkeypatch):
    """``should_alert`` fires EXACTLY ONCE on the inactive→active edge across two
    consecutive de-risk cycles (no flood), and the de-risk state CLEARS on
    recovery.

    We capture the cycle's edge-triggered alert dispatch by monkeypatching
    ``alert_manager.send_red_flag`` and counting the soft-derisk dispatches.
    """
    logging.disable(logging.CRITICAL)
    try:
        import spa_core.alerts.alert_manager as _am

        sent: list[dict] = []

        def _capture(flags):
            for f in flags or []:
                if isinstance(f, dict) and f.get("category") == "soft_derisk":
                    sent.append(f)
            return True

        monkeypatch.setattr(_am, "send_red_flag", _capture)

        td = tmp_path / "d1t3_edge"
        held = dict(_HELD_9)
        universe = _UNIVERSE_9
        target = {p: 18_000.0 for p, _ in universe}

        soft = _gradual_closes_for_drawdown(8.0)
        recover = _gradual_closes_for_drawdown(1.0)

        # Cycle 1: enter the SOFT band (inactive → active) → exactly one alert.
        _seed_sandbox(td, held=held, closes=soft)
        _run(td, universe=universe, target=target, closes=soft, held=held)
        ds1 = json.loads((td / DERISK_STATUS_FILENAME).read_text(encoding="utf-8"))
        assert ds1["active"] is True
        assert len(sent) == 1, f"expected exactly ONE edge alert, got {len(sent)}"

        # Cycle 2: STILL in the SOFT band (active → active) → NO new alert (no flood).
        # Re-seed the equity curve at the same drawdown (still SOFT); the prior
        # persisted derisk_status.active=True suppresses the edge.
        (td / EQUITY_FILENAME).write_text(
            json.dumps({"source": "cycle_runner", "daily": _equity_curve(soft)}),
            encoding="utf-8",
        )
        _run(td, universe=universe, target=target, closes=soft, held=held)
        assert len(sent) == 1, (
            f"edge alert FLOODED on a sustained de-risk window: {len(sent)} alerts"
        )

        # Cycle 3: RECOVER above the soft threshold → de-risk clears (active False).
        (td / EQUITY_FILENAME).write_text(
            json.dumps({"source": "cycle_runner", "daily": _equity_curve(recover)}),
            encoding="utf-8",
        )
        _run(td, universe=universe, target=target, closes=recover, held=held)
        ds3 = json.loads((td / DERISK_STATUS_FILENAME).read_text(encoding="utf-8"))
        assert ds3["active"] is False, "de-risk did not clear on recovery"
        assert ds3["tier"] == TIER_NONE
    finally:
        logging.disable(logging.NOTSET)


# ═══════════════════════════════════════════════════════════════════════════════
# D1-T4 — invariants the fix must PRESERVE for the non-derisk path
# ═══════════════════════════════════════════════════════════════════════════════


def test_d1t4_non_derisk_path_unchanged_by_fix(tmp_path):
    """With drawdown < 5% (NO de-risk), the re-applied soft gate is a strict no-op:
    the allocator's intended collapse may still increase / open protocols freely
    (the fix must not constrain the healthy path)."""
    logging.disable(logging.CRITICAL)
    try:
        td = tmp_path / "d1t4_healthy"
        held = dict(_HELD_9)
        closes = _gradual_closes_for_drawdown(2.0)  # below SOFT → no de-risk
        _seed_sandbox(td, held=held, closes=closes)
        target = {p: 18_000.0 for p, _ in _UNIVERSE_9}

        result = _run(td, universe=_UNIVERSE_9, target=target, closes=closes, held=held)

        ds = json.loads((td / DERISK_STATUS_FILENAME).read_text(encoding="utf-8"))
        assert ds["active"] is False and ds["tier"] == TIER_NONE
        assert not result.kill_switch_active
        # No soft-cap note should be present on the healthy path.
        assert not any("soft_derisk_gate" in n for n in result.notes)
    finally:
        logging.disable(logging.NOTSET)


def test_d1t4_softgate_idempotent_and_reduce_allowed(tmp_path):
    """The re-applied gate is IDEMPOTENT (clamping a held-subset book again leaves
    it unchanged) and REDUCTIONS remain allowed: an allocator wanting LESS than
    held keeps the reduced size."""
    logging.disable(logging.CRITICAL)
    try:
        from spa_core.paper_trading.cycle_gates import apply_soft_derisk_gate

        held = {"aave_v3": 10_000.0, "compound_v3": 8_000.0, "yearn_v3": 6_000.0}
        # want: aave reduce, compound hold, yearn increase, new open.
        target = {
            "aave_v3": 4_000.0,       # reduce → kept at 4_000
            "compound_v3": 8_000.0,   # hold → kept
            "yearn_v3": 20_000.0,     # increase → clamped to 6_000
            "newp": 5_000.0,          # new → zeroed
        }
        once = apply_soft_derisk_gate(
            dict(target), current_positions=held, derisk_active=True, notes=[]
        )
        assert once == {
            "aave_v3": 4_000.0,
            "compound_v3": 8_000.0,
            "yearn_v3": 6_000.0,
            "newp": 0.0,
        }
        # Idempotent: re-applying the gate to its own output is a no-op.
        twice = apply_soft_derisk_gate(
            dict(once), current_positions=held, derisk_active=True, notes=[]
        )
        assert twice == once
    finally:
        logging.disable(logging.NOTSET)


def test_d1t4_non_finite_and_evidenced_only_preserved(tmp_path):
    """The fix preserves the evidenced-bars-only + non-finite-safe contracts:
    a NaN/Inf close and a pre-anchor (non-evidenced) inflated bar must NOT
    fabricate a drawdown tier."""
    logging.disable(logging.CRITICAL)
    try:
        from spa_core.governance.kill_switch import drawdown_tier

        # (a) Non-finite close is dropped as no-data → cannot fabricate a tier.
        bars_nan = _equity_curve([100_000.0, 102_000.0])
        bars_nan.append(
            {"date": "2026-06-13", "close_equity": float("nan"), "open_equity": 1.0}
        )
        tier_nan, _ = drawdown_tier(bars_nan)
        # only the two finite bars remain; current==peak → no drawdown.
        assert tier_nan == TIER_NONE

        # (b) A pre-anchor inflated peak must NOT manufacture a drawdown: a
        # warmup bar dated BEFORE the anchor is excluded from the evidenced series.
        pre = [
            {"date": "2026-06-08", "close_equity": 200_000.0, "open_equity": 200_000.0,
             "is_warmup": True},
            {"date": "2026-06-10", "close_equity": 100_000.0, "open_equity": 100_000.0},
            {"date": "2026-06-11", "close_equity": 100_100.0, "open_equity": 100_000.0},
        ]
        tier_pre, _ = drawdown_tier(pre)
        # If the 200k warmup peak leaked in, current 100,100 would read as a ~50%
        # drawdown (HARD). Evidenced-only → it is excluded → TIER_NONE.
        assert tier_pre == TIER_NONE, "pre-anchor warmup peak fabricated a drawdown"
    finally:
        logging.disable(logging.NOTSET)
