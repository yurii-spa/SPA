"""ADR-055 · cash provenance — the idle capital was never "without a reason".

The finding (cycle #143, card `inbox-prostoi-kapitala-snova-ne-obyasnen-10-pr`).
`agent_health` had been publishing, for days,

    capital-efficiency LAZY: 10.0% of capital idle UNEXPLAINED after attribution

while the system's OWN audit trail carried the reason, verbatim, for the same
cycle (`data/audit_trail.jsonl`, 2026-08-06T06:00:30, event `risk_verdict`)::

    "tvl_unverified": ["morpho_blue_base"],
    "warnings": ["morpho_blue_base: TVL unverified (missing) — fail-closed:
                  excluded from fresh allocation (not held)"]

Measured on the live artifacts: the allocator's target for that cycle was 95 %
deployed (`aave_v3 40 · pendle 20 · maple 20 · morpho_blue_base 10 ·
morpho_steakhouse 5`); the ADR-053 TVL-evidence gate zeroed the 10 % leg AFTER
the allocator ran, and the optimizer path does not re-fill (by design —
`_fill_remainder` is skipped for `optimized_yield`). The freed 10 % stayed in
cash, and the attribution — which never sees the post-allocator gate — called it
"idle without a recorded reason".

Two things this file pins, and they pull in opposite directions on purpose:

1. the cause STOPS being anonymous (`caused_by` / `policy_refusals` /
   the `capital_efficiency` reason string);
2. the NUMBER does not move. `unexplained_pct` is byte-identical with and
   without the refusal. A fail-closed refusal must not be allowed to launder an
   allocation that was never re-filled — those dollars are still placeable
   today (morpho_steakhouse/compound_v3 headroom stood open), so they stay
   counted. Test 2 is the anti-laundering control and is the one that matters.

RiskPolicy is an INPUT here; nothing in this file or the code under test changes
a threshold, the kill-switch, or the live track.
"""
from __future__ import annotations

import json

import pytest

import spa_core.monitoring.capital_efficiency as ce
from spa_core.allocator.rebalance_economics import attribute_cash
from spa_core.tests._freshness import ts

CAP = 100_000.0

# ── The real pre-trade book of 2026-08-06 06:00 UTC ─────────────────────────
# Reconstructed from the artifacts of that run, not invented: the shadow verdict
# recorded legs `aave_v3 +35,000 / morpho_steakhouse -35,000`, which pins the
# book the attribution actually reasoned over. Cash 15k against a 5k floor.
BOOK = {"pendle": 20_000.0, "maple": 20_000.0,
        "morpho_steakhouse": 40_000.0, "aave_v3": 5_000.0}
APY = {"aave_v3": 4.9913, "compound_v3": 3.2969, "morpho_blue": 3.4961,
       "morpho_steakhouse": 3.4961, "euler_v2": 3.0549, "maple": 4.961,
       "pendle": 15.0957, "moonwell_base": 4.5042, "morpho_blue_base": 4.5539}
SRC = {k: "live" for k in APY}
TVL_LIVE = set(APY)
TIERS = {"aave_v3": "T1", "compound_v3": "T1", "morpho_steakhouse": "T1",
         "pendle": "T2", "maple": "T2", "euler_v2": "T2", "morpho_blue": "T2",
         "moonwell_base": "T2", "morpho_blue_base": "T2"}
CAPS = {p: (0.40 if t == "T1" else 0.20) for p, t in TIERS.items()}

# What the gate actually refused that cycle, in the shape the cycle records it.
REFUSAL = [{"protocol": "morpho_blue_base",
            "reason": "tvl_unverified_policy_gate",
            "usd_removed_from_target": 10_000.0}]


def _attr(**kw):
    kw.setdefault("positions", BOOK)
    kw.setdefault("capital_usd", CAP)
    kw.setdefault("min_cash_frac", 0.05)
    kw.setdefault("apy_pct", APY)
    kw.setdefault("apy_sources", SRC)
    kw.setdefault("tvl_live", TVL_LIVE)
    kw.setdefault("tier_caps", CAPS)
    kw.setdefault("tiers", TIERS)
    kw.setdefault("t2_total_cap", 0.50)
    kw.setdefault("t3_total_cap", 0.15)
    kw.setdefault("min_apy_pct", 1.0)
    return attribute_cash(**kw)


def _unexplained(res):
    return next(c for c in res["components"]
                if c["kind"] == "unexplained_deployable")


# ── 1. control: no refusal recorded → the old wording, and nothing invented ──

def test_without_refusals_the_component_stays_anonymous_and_field_is_empty():
    res = _attr()
    comp = _unexplained(res)
    assert res["policy_refusals"] == []
    assert "caused_by" not in comp
    assert "idle without a recorded reason" in comp["detail"]


# ── 2. THE anti-laundering control: the cause appears, the number does not move ──

def test_refusal_names_the_cause_without_moving_a_single_dollar():
    plain = _attr()
    named = _attr(policy_refusals=REFUSAL)

    # every number identical — component by component, not just the headline
    assert named["unexplained_pct"] == plain["unexplained_pct"] == 10.0
    assert named["explained_pct"] == plain["explained_pct"]
    assert named["status"] == plain["status"] == "UNEXPLAINED_CASH"
    assert ([(c["kind"], c["usd"], c["pct"]) for c in named["components"]]
            == [(c["kind"], c["usd"], c["pct"]) for c in plain["components"]])

    # …and the cause is now on record
    comp = _unexplained(named)
    assert comp["caused_by"] == [{
        "protocol": "morpho_blue_base",
        "reason": "tvl_unverified_policy_gate",
        "usd_removed_from_target": 10_000.0,
        "pct_of_capital": 10.0,
    }]
    assert "idle without a recorded reason" not in comp["detail"]
    assert "morpho_blue_base:tvl_unverified_policy_gate" in comp["detail"]
    assert "nothing re-filled the freed budget" in comp["detail"]


# ── 3. the refusal is echoed at the top level too (readers that skip components) ──

def test_policy_refusals_surface_at_the_top_level_with_pct_of_capital():
    res = _attr(policy_refusals=REFUSAL)
    assert res["policy_refusals"] == [{
        "protocol": "morpho_blue_base",
        "reason": "tvl_unverified_policy_gate",
        "usd_removed_from_target": 10_000.0,
        "pct_of_capital": 10.0,
    }]


# ── 4. fail-CLOSED / robustness: junk in the refusal list never breaks or lies ──

@pytest.mark.parametrize("junk", [
    [{"reason": "no_protocol_key"}],           # unnamed → dropped
    ["not-a-dict"],                            # wrong type → dropped
    [{"protocol": ""}],                        # empty name → dropped
])
def test_unusable_refusal_entries_are_dropped_not_guessed(junk):
    res = _attr(policy_refusals=junk)
    assert res["policy_refusals"] == []
    assert "caused_by" not in _unexplained(res)


def test_non_numeric_usd_becomes_zero_and_never_raises():
    res = _attr(policy_refusals=[{"protocol": "morpho_blue_base",
                                  "reason": "tvl_unverified_policy_gate",
                                  "usd_removed_from_target": "n/a"}])
    assert res["policy_refusals"][0]["usd_removed_from_target"] == 0.0
    assert res["unexplained_pct"] == 10.0  # still not laundered


def test_refusal_without_a_reason_is_named_unnamed_not_dropped_silently():
    res = _attr(policy_refusals=[{"protocol": "morpho_blue_base",
                                  "usd_removed_from_target": 10_000.0}])
    assert res["policy_refusals"][0]["reason"] == "unnamed_refusal"


# ── 5. the field exists on every exit path, so a reader never KeyErrors ──────

def test_field_present_when_cash_is_at_or_below_the_buffer():
    res = _attr(positions={"aave_v3": 40_000.0, "pendle": 20_000.0,
                           "maple": 20_000.0, "morpho_steakhouse": 15_000.0},
                policy_refusals=REFUSAL)
    assert res["status"] == "explained"
    assert res["policy_refusals"][0]["protocol"] == "morpho_blue_base"


def test_field_present_when_attribution_is_incomplete():
    res = _attr(tier_caps=None, policy_refusals=REFUSAL)
    assert res["status"] == "attribution_incomplete"
    assert res["unexplained_pct"] is None      # honestly unknown, still
    assert res["policy_refusals"][0]["protocol"] == "morpho_blue_base"


# ── 6. capital_efficiency: the owner-visible line stops being anonymous ──────

def _rationale(*, with_refusals: bool) -> dict:
    cash = _attr(policy_refusals=REFUSAL if with_refusals else None)
    return {"generated_at": ts(hours_ago=2.0), "cash": cash}


def _patch_ce(monkeypatch, *, with_refusals: bool):
    pos = {"capital_usd": CAP, "cash_usd": 15_000.0, "deployed_usd": 85_000.0,
           "positions": BOOK}
    apy = {"by_apy": [{"protocol": p, "apy_pct": a,
                       "tier": TIERS.get(p, "T2")} for p, a in APY.items()]}
    rat = _rationale(with_refusals=with_refusals)

    def _load(path):
        s = str(path)
        if s.endswith("current_positions.json"):
            return pos
        if s.endswith("apy_ranking.json"):
            return apy
        if s.endswith("allocation_rationale.json"):
            return rat
        return None

    monkeypatch.setattr(ce, "_load", _load)


def test_capital_efficiency_reason_is_anonymous_without_the_refusal(monkeypatch):
    _patch_ce(monkeypatch, with_refusals=False)
    res = ce.assess()
    assert res["verdict"] == "WARNING"
    assert res["cash_unexplained_pct"] == 10.0
    assert "caused by" not in res["reason"]
    assert res["cash_policy_refusals"] == []


def test_capital_efficiency_reason_names_the_pool_and_keeps_the_alarm(monkeypatch):
    _patch_ce(monkeypatch, with_refusals=True)
    res = ce.assess()
    # the alarm is NOT downgraded — same verdict, same number
    assert res["verdict"] == "WARNING"
    assert res["cash_unexplained_pct"] == 10.0
    # …and it now says why
    assert "caused by: morpho_blue_base:tvl_unverified_policy_gate" in res["reason"]
    assert "$10,000 removed from target" in res["reason"]
    assert "freed budget was not re-filled" in res["reason"]
    assert res["cash_policy_refusals"][0]["protocol"] == "morpho_blue_base"


# ── 7. the producer: what the gate removed, measured against the gate itself ──

def test_quantifier_reports_the_dropped_leg():
    from spa_core.paper_trading.cycle_gates import quantify_policy_refusals
    pre = {"aave_v3": 40_000.0, "morpho_blue_base": 10_000.0}
    post = {"aave_v3": 40_000.0}                      # dropped: not held
    assert quantify_policy_refusals(pre, post, ["morpho_blue_base"]) == [{
        "protocol": "morpho_blue_base",
        "reason": "tvl_unverified_policy_gate",
        "usd_removed_from_target": 10_000.0,
    }]


def test_quantifier_reports_only_the_part_capped_away_on_a_held_pool():
    from spa_core.paper_trading.cycle_gates import quantify_policy_refusals
    pre = {"morpho_steakhouse": 40_000.0}
    post = {"morpho_steakhouse": 12_000.0}            # capped at held
    got = quantify_policy_refusals(pre, post, ["morpho_steakhouse"])
    assert got[0]["usd_removed_from_target"] == 28_000.0


@pytest.mark.parametrize("pre,post,frozen", [
    ({"a": 10.0}, {"a": 10.0}, ["a"]),                # untouched → not a refusal
    ({"a": 10.0}, {"a": 25.0}, ["a"]),                # negative → never reported
    ({}, {}, ["a"]),                                  # absent both sides
    ({"a": 10.0}, {"a": 0.0}, []),                    # nothing frozen
    ({"a": 10.0}, {"a": 0.0}, None),                  # no list at all
])
def test_quantifier_reports_nothing_when_nothing_was_taken(pre, post, frozen):
    from spa_core.paper_trading.cycle_gates import quantify_policy_refusals
    assert quantify_policy_refusals(pre, post, frozen) == []


def test_quantifier_survives_a_non_numeric_target():
    from spa_core.paper_trading.cycle_gates import quantify_policy_refusals
    assert quantify_policy_refusals({"a": "junk"}, {"a": 0.0}, ["a"]) == []


def test_end_to_end_against_the_real_gate(tmp_path):
    """The 2026-08-06 shape, driven by the actual RiskPolicy gate.

    Not a hand-built pair of dicts: the gate decides what is frozen, and the
    quantifier is measured against ITS output. Pins the wiring contract that
    ``run_cycle`` relies on (pre-gate copy → gate → quantifier).
    """
    from spa_core.paper_trading.cycle_runner import _apply_risk_policy_gate
    from spa_core.paper_trading.cycle_gates import quantify_policy_refusals

    adapters = [
        {"protocol": "aave_v3", "apy_pct": 4.9913, "tvl_usd": 65_727_775.0,
         "tvl_source": "live", "tier": "T1", "chain": "ethereum"},
        # no live TVL → ADR-053 freeze; nothing held → dropped
        {"protocol": "morpho_blue_base", "apy_pct": 4.5539, "tvl_usd": None,
         "tier": "T2", "chain": "base"},
    ]
    pre = {"aave_v3": 40_000.0, "morpho_blue_base": 10_000.0}
    gate = _apply_risk_policy_gate(
        dict(pre), CAP, adapters, ddir=tmp_path, current_positions={},
    )
    assert gate["tvl_unverified"] == ["morpho_blue_base"]
    refusals = quantify_policy_refusals(
        pre, gate["target_usd"], gate["tvl_unverified"])
    assert refusals == [{"protocol": "morpho_blue_base",
                         "reason": "tvl_unverified_policy_gate",
                         "usd_removed_from_target": 10_000.0}]

    # …and that is exactly what stops the attribution from calling it anonymous
    assert "caused_by" in _unexplained(_attr(policy_refusals=refusals))


# ── 8. the writer carries it end-to-end into the artifact the owner reads ────

def test_write_shadow_rationale_persists_the_refusal(tmp_path):
    from spa_core.paper_trading.allocation_rationale import write_shadow_rationale

    doc = write_shadow_rationale(
        data_dir=tmp_path,
        current_positions=BOOK,
        target_positions={"aave_v3": 40_000.0, "pendle": 20_000.0,
                          "maple": 20_000.0, "morpho_steakhouse": 5_000.0},
        apy_pct=APY,
        apy_sources=SRC,
        tvl_sources={p: "live" for p in APY},
        capital_usd=CAP,
        cycle_date="2026-08-06",   # FROZEN-DATE-OK: replays a specific incident cycle
        run_ts=ts(hours_ago=0.0),
        policy_refusals=REFUSAL,
        write=True,
    )
    assert doc["cash"]["policy_refusals"][0]["protocol"] == "morpho_blue_base"
    on_disk = json.loads((tmp_path / "allocation_rationale.json").read_text())
    assert (on_disk["cash"]["policy_refusals"][0]["usd_removed_from_target"]
            == 10_000.0)
    # the artifact keeps the honest number alongside the cause
    assert on_disk["cash"]["unexplained_pct"] == 10.0


# ── 9. THE ASSEMBLY: run_cycle actually connects gate → quantifier → artifact ──
#
# Everything above tests the PARTS. Measured on 2026-08-07 (cycle #144): delete
# the single wiring line in ``run_cycle``
#
#     _policy_refusals = quantify_policy_refusals(
#         _pre_gate_target, target_usd, _tvl_frozen_pools)
#
# and the feature is dead in production — while all 22 tests above and 1342
# adjacent tests stay GREEN. That is the fail-OPEN shape this repo keeps paying
# for: each guard answers its own question honestly, and none answers "does the
# assembled thing work?". A part-tested, assembly-untested feature is not
# delivered — it is only pushed.
#
# So this test drives the REAL ``run_cycle`` against a temp sandbox and asserts
# the owner-visible artifact, in the manner of ``test_cycle_derisk_e2e.py``.
#
# Honest limit of this test, measured not assumed. Three wiring mutations were
# run against it; two are caught, one is EQUIVALENT and cannot be:
#   M5  drop the ``quantify_policy_refusals`` call  → CAUGHT
#   M6  pass ``policy_refusals=[]`` to the writer   → CAUGHT
#   M7  ``_pre_gate_target = target_usd`` (alias, not a copy) → NOT caught, and
#       correctly so: ``target_usd`` is REBOUND a few lines later
#       (``target_usd = dict(gate["target_usd"])``), never mutated in place, so
#       the alias still refers to the pre-gate book. The ``dict()`` stays as
#       defence in depth against a future in-place gate; it is not load-bearing
#       today and no test should pretend otherwise.
#
# Also honest: driving the real cycle produces 9 live-network REFUSALS (the guard
# holds, nothing goes out) — identical to every ``run_cycle`` test in
# ``test_cycle_derisk_e2e.py``. Structural to the cycle, not introduced here.


@pytest.fixture
def _no_live_telegram(monkeypatch):
    """Transport-only stub — a sandbox cycle must never reach the owner's chat.

    Same reasoning as ``test_cycle_derisk_e2e._capture_owner_pushes``: only the
    transport is replaced, every whitelist/ceiling/edge-trigger gate still runs,
    and no assertion below is relaxed (invariant #16).
    """
    from spa_core.telegram import push_policy
    monkeypatch.setattr(push_policy, "_send", lambda text: True)


def test_run_cycle_wires_the_refusal_into_the_owner_facing_artifact(
        tmp_path, _no_live_telegram):
    """End-to-end: an ADR-053 freeze inside a real cycle is NAMED in the artifact.

    The 2026-08-06 shape: the allocator asks for a leg the TVL-evidence gate then
    refuses, nothing re-fills the freed budget, and the cash attribution must
    report the cause instead of "idle without a recorded reason".

    Sandbox-only (explicit non-canonical ``data_dir`` + ``allow_live_write=False``):
    the live track is never read or written.
    """
    from types import SimpleNamespace

    from spa_core.paper_trading import cycle_runner as _cr

    universe = [
        {"protocol": "aave_v3", "id": "aave_v3", "apy_pct": 4.9913,
         "tvl_usd": 65_727_775.0, "tvl_source": "live", "tier": "T1",
         "status": "ok", "chain": "ethereum"},
        # no live TVL → ADR-053 freeze; not held → dropped from the target
        {"protocol": "morpho_blue_base", "id": "morpho_blue_base",
         "apy_pct": 4.5539, "tvl_usd": None, "tvl_source": None, "tier": "T2",
         "status": "ok", "chain": "base"},
    ]
    target = {"aave_v3": 40_000.0, "morpho_blue_base": 10_000.0}

    (tmp_path / "current_positions.json").write_text(
        json.dumps({"positions": {}, "cash_usd": CAP}), encoding="utf-8")

    class _Alloc:
        def allocate(self):
            return SimpleNamespace(
                target_usd=dict(target),
                target_weights={p: v / CAP for p, v in target.items()},
                expected_apy_pct=4.9, model_used="optimized_yield",
                strategy_loop_active=False)

    _cr.run_cycle(
        data_dir=str(tmp_path),
        orchestrator_fn=lambda _d: SimpleNamespace(
            adapters=universe, status="ok", data_freshness="live"),
        allocator=_Alloc(),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,
        write=True,
        allow_live_write=False,
    )

    art = tmp_path / "allocation_rationale.json"
    assert art.exists(), "the cycle wrote no rationale artifact at all"
    cash = json.loads(art.read_text())["cash"]

    # THE assertion M5 exists for: the refusal survived the whole assembly.
    assert cash.get("policy_refusals"), (
        "run_cycle did not carry the ADR-053 refusal into the artifact — the "
        "gate→quantifier→writer wiring is broken, and the idle cash is anonymous "
        "again exactly as on 2026-08-06")
    assert cash["policy_refusals"][0]["protocol"] == "morpho_blue_base"
    assert (cash["policy_refusals"][0]["reason"]
            == "tvl_unverified_policy_gate")
    assert cash["policy_refusals"][0]["usd_removed_from_target"] == 10_000.0
