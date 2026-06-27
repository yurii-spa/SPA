#!/usr/bin/env python3
"""Property test: NAV conservation + byte-level determinism of the cycle core.

Sprint T3. This is a *property* test (stdlib-only, seeded ``random.Random``,
~200 cases — NO hypothesis) over the REAL, LLM-forbidden paper-trading cycle
surface (``cycle_runner.run_cycle`` → ``equity.py`` accrual → the
``current_positions.json`` NAV reconciliation block). It asserts two invariants
the honest go-live track depends on:

1. **NAV CONSERVATION** — after every cycle the persisted reconciliation must
   close *exactly* (residual == 0, round-trip / Decimal-safe):

       current_equity_usd == deployed_usd + cash_usd + accrued_yield_usd

   and the component identities ``deployed + cash == capital`` and
   ``accrued_yield == current_equity - capital`` must each hold to the cent. A
   rounding/accrual bug that leaks a fraction of a cent into the track would be
   caught here.

2. **DETERMINISM** — the SAME seeded inputs run twice (two fresh temp dirs)
   produce **byte-identical** ``trades.json`` + ``equity_curve_daily.json``
   (modulo the injected timestamp, which is pinned). The risk/execution-adjacent
   cycle surface must be reproducible; a hidden source of non-determinism
   (dict ordering, unseeded RNG, wall-clock leakage) would tear this.

CRITICAL GUARDRAIL — the whole module runs ENTIRELY against a per-test TEMP
sandbox ``data_dir``. It NEVER reads or writes the live repo ``data/`` (the
2026-06-25 track-corruption hazard: ad-hoc cycle runs mutated the real track).
Every ``run_cycle`` call passes an explicit, NON-canonical ``tmp_path`` (which
the write-interlock honours verbatim) AND ``allow_live_write=False``; a dedicated
guard test (``test_sandbox_guard_never_resolves_to_live_data``) fails loudly if
the resolved dir would ever be the canonical ``<repo>/data``.

Hermetic: orchestrator / allocator / risk-scorer / track-persister are in-process
network-free fakes; timestamps are pinned; logging silenced. No live module side
effects, no network, deterministic.
"""
from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from spa_core.paper_trading import cycle_runner as _cr
from spa_core.paper_trading._cycle_io import (
    CAPITAL_USD,
    EQUITY_FILENAME,
    POSITIONS_FILENAME,
    TRADES_FILENAME,
    _DEFAULT_DATA_DIR,
    resolve_data_dir,
)

# ── A small, policy-compliant universe so the RiskPolicy gate APPROVES most
#    targets (T1 aave ≤40%, T2 each ≤20%, T2 total ≤50%, cash buffer ≥5%, TVL
#    ≥$5M, APY in [1,30]%). Mixing tiers + a few cash-heavy/degenerate shapes
#    lets the property sweep exercise traded / no-trade / all-cash / single /
#    empty allocations without tripping a BLOCK that would abort accrual.
_UNIVERSE = [
    ("aave_v3", "T1", 4.0),
    ("compound_v3", "T2", 4.2),
    ("morpho_blue", "T2", 4.8),
    ("yearn_v3", "T2", 5.0),
]


def _make_orch(apy_by_proto: dict[str, float]):
    """Build a network-free orchestrator fake exposing live adapter records."""

    def _orch(data_dir):  # noqa: ANN001 — matches orchestrator_fn signature
        adapters = [
            {
                "protocol": proto,
                "id": proto,
                "apy_pct": apy_by_proto[proto],
                "tvl_usd": 1e8,
                "tier": tier,
                "status": "ok",
            }
            for proto, tier, _ in _UNIVERSE
            if proto in apy_by_proto
        ]
        return SimpleNamespace(adapters=adapters, status="ok", data_freshness="live")

    return _orch


def _make_allocator(target_usd: dict[str, float]):
    """Build a fake allocator returning a fixed target allocation."""

    class _Alloc:
        def allocate(self):  # noqa: D401 — fake
            return SimpleNamespace(
                target_usd=dict(target_usd),
                target_weights={p: v / CAPITAL_USD for p, v in target_usd.items()},
                expected_apy_pct=4.0,
                model_used="risk_adjusted",
                strategy_loop_active=False,
            )

    return _Alloc()


def _gen_case(rng: random.Random) -> dict:
    """Generate one seeded cycle case.

    Returns a dict with the per-day APY map, the allocator target, and a
    ``shape`` tag so degenerate cases (empty / all-cash / single / kill-switch)
    are deliberately represented in the sweep.
    """
    shape = rng.choice(
        # Weight the "normal multi-protocol" shape but guarantee coverage of the
        # degenerate corners the task calls out.
        ["normal", "normal", "normal", "single", "all_cash", "empty", "kill_switch"]
    )
    # Per-day live APY for each protocol (kept inside the [1,30]% sane band).
    apy_by_proto = {
        proto: round(base + rng.uniform(-1.5, 1.5), 4)
        for proto, _tier, base in _UNIVERSE
    }

    if shape == "empty" or shape == "all_cash":
        target = {}
    elif shape == "single":
        # One T1 position, ≤40% of capital so the per-protocol cap holds.
        target = {"aave_v3": round(rng.uniform(5_000, 38_000), 2)}
    else:  # normal / kill_switch both start from a compliant multi-protocol book
        # aave (T1) ≤40%, each T2 ≤20%, T2 total ≤50%, leave ≥5% cash.
        target = {
            "aave_v3": round(rng.uniform(20_000, 38_000), 2),
            "compound_v3": round(rng.uniform(5_000, 18_000), 2),
            "morpho_blue": round(rng.uniform(5_000, 18_000), 2),
        }
    return {"apy_by_proto": apy_by_proto, "target": target, "shape": shape}


def _run_case(ddir: Path, case: dict, now: datetime, *, kill: bool = False):
    """Run ONE cycle for ``case`` against the explicit tmp ``ddir`` sandbox."""
    if kill:
        # Manual kill-switch trigger (a file the real KillSwitchChecker reads):
        # forces the all-cash override → deployed=0, cash=capital. Written into
        # the SANDBOX dir only.
        ddir.mkdir(parents=True, exist_ok=True)
        (ddir / "kill_switch_active.json").write_text(
            json.dumps({"active": True, "reason": "property-test manual kill"}),
            encoding="utf-8",
        )
    return _cr.run_cycle(
        data_dir=str(ddir),
        now=now,
        orchestrator_fn=_make_orch(case["apy_by_proto"]),
        allocator=_make_allocator(case["target"]),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,
        write=True,
        allow_live_write=False,
    )


# ── NAV conservation residual (exact, Decimal-safe) ──────────────────────────


def _assert_nav_conserves(ddir: Path, case_id: str) -> Decimal:
    """Assert the persisted NAV reconciliation closes EXACTLY (residual == 0).

    Reads back ``current_positions.json`` (the proof-of-reserves doc the cycle
    persists) and checks, in exact ``Decimal`` arithmetic on the round-tripped
    JSON cents:

        current_equity == deployed + cash + accrued_yield      (NAV identity)
        deployed + cash == capital                             (no capital leak)
        accrued_yield  == current_equity - capital             (accrual identity)
        sum(positions) == deployed                             (book footing)

    Returns the (zero) NAV residual for aggregate reporting.
    """
    doc = json.loads((ddir / POSITIONS_FILENAME).read_text(encoding="utf-8"))

    def D(key: str) -> Decimal:
        # str() round-trip: parse the persisted JSON number EXACTLY as written
        # (no binary-float drift), the way a downstream proof-of-reserves reader
        # would have to reconcile it.
        return Decimal(str(doc[key]))

    capital = D("capital_usd")
    equity = D("current_equity_usd")
    deployed = D("deployed_usd")
    cash = D("cash_usd")
    accrued = D("accrued_yield_usd")

    nav_residual = equity - (deployed + cash + accrued)
    assert nav_residual == Decimal("0"), (
        f"[{case_id}] NAV NOT conserved: "
        f"equity {equity} != deployed {deployed} + cash {cash} + accrued {accrued} "
        f"(residual {nav_residual})"
    )
    assert deployed + cash == capital, (
        f"[{case_id}] capital leak: deployed {deployed} + cash {cash} != "
        f"capital {capital}"
    )
    assert accrued == equity - capital, (
        f"[{case_id}] accrual identity broken: accrued {accrued} != "
        f"equity {equity} - capital {capital}"
    )

    positions = doc.get("positions") or {}
    pos_sum = sum((Decimal(str(v)) for v in positions.values()), Decimal("0"))
    assert pos_sum == deployed, (
        f"[{case_id}] book does not foot: sum(positions) {pos_sum} != "
        f"deployed {deployed}"
    )
    return nav_residual


# ═══════════════════════════════════════════════════════════════════════════════
# SANDBOX GUARD — defense against the track-corruption hazard
# ═══════════════════════════════════════════════════════════════════════════════


def test_sandbox_guard_never_resolves_to_live_data(tmp_path):
    """Hard guard: every dir this test family uses MUST resolve to the tmp
    sandbox, NEVER the canonical repo ``data/``.

    (a) An explicit tmp ``data_dir`` is honoured verbatim and is NOT the
        canonical dir, even with ``allow_live_write=True``.
    (b) Belt-and-braces: a DEFAULT (no data_dir) run with no opt-in is
        redirected AWAY from the canonical dir by the write-interlock.
    If either ever resolved to ``<repo>/data`` we would risk corrupting the real
    track — fail the whole module loudly.
    """
    canon = _DEFAULT_DATA_DIR.resolve()

    # (a) The explicit sandbox dir we run every case against.
    resolved, redirected = resolve_data_dir(str(tmp_path), allow_live_write=True)
    assert resolved.resolve() == tmp_path.resolve()
    assert resolved.resolve() != canon, "sandbox resolved to LIVE data/ — abort!"
    assert redirected is False  # explicit non-canonical dir → honoured verbatim

    # (b) Default + no opt-in → interlock reroutes away from canonical.
    resolved2, redirected2 = resolve_data_dir(None, allow_live_write=False)
    assert resolved2.resolve() != canon, "default run targeted LIVE data/ — abort!"
    assert redirected2 is True


# ═══════════════════════════════════════════════════════════════════════════════
# PROPERTY 1 — NAV CONSERVATION across ~200 seeded cases (incl. degenerates)
# ═══════════════════════════════════════════════════════════════════════════════


def test_nav_conservation_property(tmp_path):
    """~200 seeded inert cycles (varied portfolios + degenerate shapes) — each
    must persist a NAV reconciliation that closes EXACTLY (residual == 0).

    Every case runs against its OWN tmp sandbox dir; the live track is never
    touched (the dir is explicit + non-canonical → write-interlock honours it).
    """
    # Guard: the parametrising root is the tmp sandbox, not the repo.
    assert tmp_path.resolve() != _DEFAULT_DATA_DIR.resolve()

    logging.disable(logging.CRITICAL)
    n_cases = 200
    shapes_seen: dict[str, int] = {}
    max_abs_residual = Decimal("0")
    try:
        for seed in range(n_cases):
            rng = random.Random(seed)
            case = _gen_case(rng)
            shapes_seen[case["shape"]] = shapes_seen.get(case["shape"], 0) + 1
            ddir = tmp_path / f"case_{seed:03d}"
            # First a healthy day so a prior bar exists, then THIS case's day —
            # exercises accrual off a non-trivial prior close (cumulative NAV).
            _run_case(
                ddir,
                {"apy_by_proto": case["apy_by_proto"], "target": dict(_DEFAULT_DAY1)},
                datetime(2026, 6, 11, 8, tzinfo=timezone.utc),
            )
            _assert_nav_conserves(ddir, f"seed{seed}-day1")

            _run_case(
                ddir,
                case,
                datetime(2026, 6, 12, 8, tzinfo=timezone.utc),
                kill=(case["shape"] == "kill_switch"),
            )
            residual = _assert_nav_conserves(ddir, f"seed{seed}-{case['shape']}")
            max_abs_residual = max(max_abs_residual, abs(residual))
    finally:
        logging.disable(logging.NOTSET)

    # Every degenerate corner the task names must actually be represented.
    for required in ("empty", "all_cash", "single", "kill_switch", "normal"):
        assert shapes_seen.get(required, 0) > 0, (
            f"degenerate shape {required!r} never generated across {n_cases} seeds "
            f"(got {shapes_seen})"
        )
    # The whole point: zero NAV residual across every case.
    assert max_abs_residual == Decimal("0")


_DEFAULT_DAY1 = {"aave_v3": 30_000.0, "compound_v3": 15_000.0}


def test_kill_switch_case_is_all_cash_and_conserves(tmp_path):
    """Degenerate kill-switch case explicitly: an active manual kill forces the
    all-cash override → deployed == 0, cash == capital, accrued unchanged, and
    NAV still conserves exactly."""
    logging.disable(logging.CRITICAL)
    try:
        ddir = tmp_path / "kill"
        # Day 1 healthy (so there's accrued yield carried into day 2).
        _run_case(
            ddir,
            {"apy_by_proto": {p: b for p, _t, b in _UNIVERSE}, "target": dict(_DEFAULT_DAY1)},
            datetime(2026, 6, 11, 8, tzinfo=timezone.utc),
        )
        # Day 2 with the kill switch armed.
        r = _run_case(
            ddir,
            {"apy_by_proto": {p: b for p, _t, b in _UNIVERSE}, "target": dict(_DEFAULT_DAY1)},
            datetime(2026, 6, 12, 8, tzinfo=timezone.utc),
            kill=True,
        )
    finally:
        logging.disable(logging.NOTSET)

    assert r.kill_switch_active is True
    doc = json.loads((ddir / POSITIONS_FILENAME).read_text(encoding="utf-8"))
    assert Decimal(str(doc["deployed_usd"])) == Decimal("0"), "kill did not flatten book"
    assert Decimal(str(doc["cash_usd"])) == Decimal(str(doc["capital_usd"]))
    _assert_nav_conserves(ddir, "explicit-kill")


# ═══════════════════════════════════════════════════════════════════════════════
# PROPERTY 2 — DETERMINISM: same seeded input twice → byte-identical output
# ═══════════════════════════════════════════════════════════════════════════════


def _run_two_day_sequence(ddir: Path, case: dict) -> tuple[bytes, bytes]:
    """Run a fixed 2-day sequence for ``case`` and return the raw bytes of
    ``trades.json`` and ``equity_curve_daily.json`` (the LLM-forbidden cycle
    output surface). Timestamps are pinned so the only variation could come from
    the cycle's own (non-)determinism."""
    _run_case(ddir, {"apy_by_proto": case["apy_by_proto"], "target": dict(_DEFAULT_DAY1)},
              datetime(2026, 6, 11, 8, tzinfo=timezone.utc))
    _run_case(ddir, case, datetime(2026, 6, 12, 8, tzinfo=timezone.utc),
              kill=(case["shape"] == "kill_switch"))
    trades = (ddir / TRADES_FILENAME).read_bytes()
    equity = (ddir / EQUITY_FILENAME).read_bytes()
    return trades, equity


def test_determinism_byte_identical_output(tmp_path):
    """The SAME seeded input run twice (two FRESH tmp dirs) must produce
    BYTE-IDENTICAL ``trades.json`` + ``equity_curve_daily.json``.

    A representative spread of seeds (incl. degenerate shapes) is checked. Any
    non-determinism (unseeded RNG, dict-ordering leak, wall-clock contamination)
    tears the byte comparison.
    """
    logging.disable(logging.CRITICAL)
    checked_shapes: set[str] = set()
    try:
        # A spread that, with these seeds, covers normal/single/all_cash/empty/kill.
        for seed in range(40):
            rng = random.Random(seed)
            case = _gen_case(rng)
            checked_shapes.add(case["shape"])

            a_dir = tmp_path / f"a_{seed:03d}"
            b_dir = tmp_path / f"b_{seed:03d}"
            trades_a, equity_a = _run_two_day_sequence(a_dir, case)
            trades_b, equity_b = _run_two_day_sequence(b_dir, case)

            assert trades_a == trades_b, (
                f"[seed{seed}/{case['shape']}] trades.json NOT byte-identical "
                f"across two runs of the same seeded input"
            )
            assert equity_a == equity_b, (
                f"[seed{seed}/{case['shape']}] equity_curve_daily.json NOT "
                f"byte-identical across two runs of the same seeded input"
            )
    finally:
        logging.disable(logging.NOTSET)

    # Sanity: the determinism sweep actually exercised >1 shape.
    assert len(checked_shapes) >= 3, f"determinism sweep too narrow: {checked_shapes}"


def test_determinism_across_full_week_sequence(tmp_path):
    """Determinism over a longer multi-day track (cumulative accrual + ring
    buffers): a 6-day sequence run twice on fresh dirs is byte-identical."""
    logging.disable(logging.CRITICAL)
    try:
        rng = random.Random(12345)
        apy = {p: round(b + rng.uniform(-1, 1), 4) for p, _t, b in _UNIVERSE}
        target = dict(_DEFAULT_DAY1)
        base = datetime(2026, 6, 11, 8, tzinfo=timezone.utc)

        def _week(dir_: Path) -> tuple[bytes, bytes]:
            for i in range(6):
                _run_case(
                    dir_,
                    {"apy_by_proto": apy, "target": target, "shape": "normal"},
                    base + timedelta(days=i),
                )
            return (
                (dir_ / TRADES_FILENAME).read_bytes(),
                (dir_ / EQUITY_FILENAME).read_bytes(),
            )

        t1, e1 = _week(tmp_path / "wk_a")
        t2, e2 = _week(tmp_path / "wk_b")
    finally:
        logging.disable(logging.NOTSET)

    assert t1 == t2, "trades.json not deterministic over a 6-day track"
    assert e1 == e2, "equity_curve_daily.json not deterministic over a 6-day track"


# ═══════════════════════════════════════════════════════════════════════════════
# LIVE-DATA UNTOUCHED — prove the module never mutates the canonical track
# ═══════════════════════════════════════════════════════════════════════════════


# The exact set of canonical-track files a cycle writes. THESE are the files the
# 2026-06-25 corruption mutated and the ones we must prove are never touched. We
# scope the mtime guard to this set (NOT the whole data/ tree): on a live
# production host the launchd agent fleet (watchdog / self_heal / threat_reactor /
# analyzer *_log.json / monitor snapshots, ~51 agents) legitimately writes other
# files in data/ on its own cron cadence, independent of this test — asserting the
# whole tree is unchanged would be flaky for reasons that have nothing to do with
# the cycle. These cycle-output files have NO other writer during the test, so an
# mtime change on any of them would be a real corruption-hazard regression.
_CYCLE_OUTPUT_FILES = (
    TRADES_FILENAME,
    EQUITY_FILENAME,
    POSITIONS_FILENAME,
    "paper_trading_status.json",
    "golive_status.json",
    "risk_policy_blocks.json",
    "kill_switch_status.json",
    "kill_switch_active.json",
    "market_regime.json",
)


def test_module_never_writes_live_cycle_outputs(tmp_path):
    """Run a full cycle (incl. the manual-kill path) and assert NONE of the
    canonical-track CYCLE-OUTPUT files under the live repo ``data/`` were created
    or modified (mtime + content snapshot before/after).

    Defense-in-depth on top of the explicit-sandbox guard. Scoped to the exact
    files a cycle writes — the live launchd fleet mutates *other* data/ files on
    its own schedule, so a whole-tree snapshot would be flaky for reasons
    unrelated to the cycle. A change to ANY file here would be the real hazard.
    """
    live = _DEFAULT_DATA_DIR

    def _snapshot() -> dict[str, tuple]:
        snap: dict[str, tuple] = {}
        for name in _CYCLE_OUTPUT_FILES:
            p = live / name
            if p.is_file():
                try:
                    snap[name] = (p.stat().st_mtime_ns, p.read_bytes())
                except OSError:
                    pass
            else:
                snap[name] = ("absent", b"")
        return snap

    before = _snapshot()

    logging.disable(logging.CRITICAL)
    try:
        # Two days incl. the manual-kill path (writes kill_switch_active.json into
        # the SANDBOX) — exercises every cycle-output write against the sandbox.
        ddir = tmp_path / "untouched"
        _run_case(
            ddir,
            {"apy_by_proto": {p: b for p, _t, b in _UNIVERSE}, "target": dict(_DEFAULT_DAY1)},
            datetime(2026, 6, 11, 8, tzinfo=timezone.utc),
        )
        _run_case(
            ddir,
            {"apy_by_proto": {p: b for p, _t, b in _UNIVERSE}, "target": dict(_DEFAULT_DAY1)},
            datetime(2026, 6, 12, 8, tzinfo=timezone.utc),
            kill=True,
        )
    finally:
        logging.disable(logging.NOTSET)

    after = _snapshot()

    # Every canonical cycle-output file is byte-identical and same-mtime → the
    # cycle wrote ONLY the tmp sandbox, never the live track.
    changed = [name for name in _CYCLE_OUTPUT_FILES if before.get(name) != after.get(name)]
    assert not changed, (
        "cycle mutated LIVE canonical-track output file(s): "
        f"{changed} — TRACK-CORRUPTION HAZARD"
    )
    # The manual-kill file must NOT have been created under live data/ (it belongs
    # only in the sandbox).
    assert not (live / "kill_switch_active.json").exists() or before.get(
        "kill_switch_active.json"
    ) == after.get("kill_switch_active.json"), (
        "manual-kill file leaked into / changed under live data/"
    )
