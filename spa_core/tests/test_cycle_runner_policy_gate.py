"""MP-1180 (APY) + ADR-053 (TVL): RiskPolicy gate fallback/verification contract.

MP-1180 (APY fallback — KEPT): when the live orchestrator returns apy=None
(network errors) the gate sees APY=0% → every pool fails min_apy=1% → 0 trades.
The gate fills missing APY from adapter_registry.json (``fallback_apy`` /
``live_apy``, decimal fraction → %). Live apy>0 is never overwritten.

ADR-053 (TVL fail-CLOSED — REPLACES the $20M fabrication): the $5M TVL floor is
only checked against a TVL the adapter snapshot DECLARED live
(``tvl_source == "live"``, finite, > 0). A pool whose TVL is missing, zero, or
a static constant can NOT verify the floor → it receives no fresh capital: its
target is capped at the currently-held amount (hold + reduce allowed) and it is
dropped from the target when not held. The registry is never a TVL source and
no TVL value is ever fabricated. Frozen pools are reported per-pool in
``tvl_unverified`` + warnings — they do NOT block the rest of the book.

Test contract:
- apy=None/0 + live TVL → registry APY fallback fills it (fraction → %)
- live apy>0  → fallback NOT applied (live takes priority)
- tvl missing/0/static → pool frozen: capped at held / dropped, flagged
- registry tvl_usd → IGNORED (never verifies the floor)
- live tvl below floor → blocking violation (the floor is real)
- frozen pools don't block verified pools (per-pool fail-closed)
- frozen held pools still count toward cumulative T2/concentration limits
- no registry file / corrupt registry → graceful, no crash
- tier/chain from registry when meta empty
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import spa_core.paper_trading.cycle_runner as cr
from spa_core.paper_trading.cycle_runner import _apply_risk_policy_gate


# ─── Helpers ─────────────────────────────────────────────────────────────────

_CAPITAL = 100_000.0
_NOW = datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)


def _write_registry(tmp_path: Path, adapters: dict) -> None:
    """Write a minimal adapter_registry.json understood by the gate."""
    (tmp_path / "adapter_registry.json").write_text(
        json.dumps({"version": "test", "adapters": adapters}),
        encoding="utf-8",
    )


def _reg_entry(
    *,
    tier: int = 1,
    fallback_apy: float = 0.04,
    chain: str = "ethereum",
    tvl_usd: float | None = None,
    live_apy: float | None = None,
) -> dict:
    entry: dict = {
        "tier": tier,
        "fallback_apy": fallback_apy,
        "chain": chain,
    }
    if tvl_usd is not None:
        entry["tvl_usd"] = tvl_usd
    if live_apy is not None:
        entry["live_apy"] = live_apy
    return entry


def _adapter_dict(
    protocol: str,
    *,
    apy_pct: float | None = 4.0,
    tvl_usd: float | None = 2e7,
    tvl_source: str | None = "live",
    tier: str = "T1",
    status: str = "ok",
    chain: str = "ethereum",
) -> dict:
    return {
        "protocol": protocol,
        "apy_pct": apy_pct,
        "tvl_usd": tvl_usd,
        "tvl_source": tvl_source,
        "tier": tier,
        "status": status,
        "chain": chain,
    }


def _gate(
    target_usd: dict,
    adapters: list[dict] | None = None,
    ddir: Path | None = None,
    capital: float = _CAPITAL,
    current_positions: dict | None = None,
) -> dict:
    return _apply_risk_policy_gate(
        target_usd,
        capital,
        adapters or [],
        ddir=ddir,
        current_positions=current_positions,
    )


# ─── Orch/cycle helpers for integration tests ─────────────────────────────────


class _FakeAllocator:
    def __init__(self, target_usd: dict):
        self._t = target_usd

    def allocate(self):
        return SimpleNamespace(
            target_usd=dict(self._t),
            expected_apy_pct=4.0,
            model_used="test",
            strategy_loop_active=False,
        )


def _orch_fn(adapters: list[dict], status: str = "ok"):
    def _inner(data_dir):
        return SimpleNamespace(adapters=adapters, status=status)

    return _inner


def _run_cycle(
    tmp_path: Path,
    target_usd: dict,
    adapters: list[dict],
    *,
    write: bool = True,
):
    return cr.run_cycle(
        data_dir=tmp_path,
        now=_NOW,
        orchestrator_fn=_orch_fn(adapters),
        allocator=_FakeAllocator(target_usd),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,
        write=write,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# UNIT TESTS — MP-1180 APY fallback (unchanged contract, live TVL in meta)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFallbackApyUsed:
    """apy=0 from live (with live TVL) → registry fallback fills the APY."""

    def test_fallback_apy_applied_when_live_zero(self, tmp_path):
        _write_registry(tmp_path, {"aave_v3": _reg_entry(fallback_apy=0.04)})
        # adapter returns apy=0 (simulates network error / None→0); TVL is live
        adapters = [_adapter_dict("aave_v3", apy_pct=0.0, tvl_usd=2e7)]
        result = _gate({"aave_v3": 40_000.0}, adapters=adapters, ddir=tmp_path)
        # 0.04 * 100 = 4.0% > 1.0% min → no APY violation
        apy_viols = [v for v in result["violations"] if "APY" in v and "aave_v3" in v]
        assert apy_viols == [], f"Unexpected APY violations: {apy_viols}"
        assert result["approved"] is True

    def test_live_apy_field_used_over_fallback_apy(self, tmp_path):
        """live_apy in registry takes precedence over fallback_apy."""
        _write_registry(
            tmp_path,
            {
                "compound_v3": _reg_entry(
                    fallback_apy=0.001,  # would fail 1% minimum
                    live_apy=0.052,      # should be used instead → 5.2%
                )
            },
        )
        adapters = [_adapter_dict("compound_v3", apy_pct=0.0, tvl_usd=1e8)]
        result = _gate({"compound_v3": 35_000.0}, adapters=adapters, ddir=tmp_path)
        apy_viols = [v for v in result["violations"] if "APY" in v and "compound_v3" in v]
        assert apy_viols == []

    def test_live_apy_not_overwritten(self, tmp_path):
        """If live apy>0, registry fallback must not touch it."""
        _write_registry(tmp_path, {"aave_v3": _reg_entry(fallback_apy=0.10)})
        adapters = [_adapter_dict("aave_v3", apy_pct=2.5, tvl_usd=2e8)]
        result = _gate({"aave_v3": 40_000.0}, adapters=adapters, ddir=tmp_path)
        # live 2.5% > 1% minimum → passes on its own
        apy_viols = [v for v in result["violations"] if "APY" in v and "aave_v3" in v]
        assert apy_viols == []

    def test_negative_fallback_apy_not_used(self, tmp_path):
        """Negative fallback_apy in registry is silently ignored."""
        _write_registry(tmp_path, {"bad_proto": _reg_entry(fallback_apy=-0.05)})
        adapters = [_adapter_dict("bad_proto", apy_pct=0.0, tvl_usd=2e7, tier="T2")]
        result = _gate({"bad_proto": 5_000.0}, adapters=adapters, ddir=tmp_path)
        # fallback apy=-0.05 not > 0 → stays at 0.0 → APY violation
        apy_viols = [v for v in result["violations"] if "APY" in v and "bad_proto" in v]
        assert len(apy_viols) >= 1

    def test_zero_fallback_apy_not_used(self, tmp_path):
        """Zero fallback_apy in registry is not applied (must be > 0)."""
        _write_registry(tmp_path, {"zero_proto": _reg_entry(fallback_apy=0.0)})
        adapters = [_adapter_dict("zero_proto", apy_pct=0.0, tvl_usd=2e7, tier="T2")]
        result = _gate({"zero_proto": 5_000.0}, adapters=adapters, ddir=tmp_path)
        apy_viols = [v for v in result["violations"] if "APY" in v and "zero_proto" in v]
        assert len(apy_viols) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# UNIT TESTS — ADR-053 TVL fail-CLOSED (replaces the $20M fabrication)
# ═══════════════════════════════════════════════════════════════════════════════


class TestTvlFailClosed:
    """Unverified TVL → no fresh capital: capped at held / dropped, never $20M."""

    def test_missing_tvl_not_held_pool_dropped(self, tmp_path):
        """tvl=0 (feed lost), nothing held → pool excluded from the target."""
        _write_registry(tmp_path, {"aave_v3": _reg_entry(fallback_apy=0.04)})
        adapters = [_adapter_dict("aave_v3", apy_pct=4.0, tvl_usd=0.0)]
        result = _gate({"aave_v3": 40_000.0}, adapters=adapters, ddir=tmp_path)
        assert "aave_v3" not in result["target_usd"]
        assert result["tvl_unverified"] == ["aave_v3"]
        # per-pool fail-closed: the (now empty) book itself is not blocked
        assert result["approved"] is True
        assert any("aave_v3" in w and "TVL unverified" in w for w in result["warnings"])

    def test_missing_tvl_held_pool_capped_at_held(self, tmp_path):
        """tvl=0 on a HELD pool → hold allowed, no fresh capital (no increase)."""
        adapters = [_adapter_dict("aave_v3", apy_pct=4.0, tvl_usd=0.0)]
        result = _gate(
            {"aave_v3": 40_000.0},
            adapters=adapters,
            ddir=tmp_path,
            current_positions={"aave_v3": 12_000.0},
        )
        assert result["target_usd"].get("aave_v3") == 12_000.0
        assert result["tvl_unverified"] == ["aave_v3"]

    def test_missing_tvl_reduction_still_allowed(self, tmp_path):
        """Frozen pool: a target BELOW held passes through (reduce is de-risk)."""
        adapters = [_adapter_dict("aave_v3", apy_pct=4.0, tvl_usd=0.0)]
        result = _gate(
            {"aave_v3": 5_000.0},
            adapters=adapters,
            ddir=tmp_path,
            current_positions={"aave_v3": 12_000.0},
        )
        assert result["target_usd"].get("aave_v3") == 5_000.0

    def test_static_tvl_constant_never_passes_floor(self, tmp_path):
        """tvl_source='static' with a huge committed constant → frozen anyway."""
        adapters = [
            _adapter_dict(
                "compound_v3", apy_pct=3.5, tvl_usd=1.5e9, tvl_source="static"
            )
        ]
        result = _gate({"compound_v3": 30_000.0}, adapters=adapters, ddir=tmp_path)
        assert "compound_v3" not in result["target_usd"]
        assert result["tvl_unverified"] == ["compound_v3"]

    def test_undeclared_tvl_source_treated_as_static(self, tmp_path):
        """A numeric TVL WITHOUT tvl_source='live' cannot verify the floor."""
        adapters = [
            _adapter_dict("mystery", apy_pct=4.0, tvl_usd=9e9, tvl_source=None,
                          tier="T2")
        ]
        result = _gate({"mystery": 10_000.0}, adapters=adapters, ddir=tmp_path)
        assert "mystery" not in result["target_usd"]
        assert result["tvl_unverified"] == ["mystery"]

    def test_registry_tvl_usd_is_never_a_tvl_source(self, tmp_path):
        """ADR-053: registry tvl_usd is a literal, not a live feed → frozen."""
        _write_registry(
            tmp_path,
            {"morpho_blue": _reg_entry(fallback_apy=0.041, tier=2, tvl_usd=50_000_000)},
        )
        adapters = [_adapter_dict("morpho_blue", apy_pct=4.1, tvl_usd=0.0, tier="T2")]
        result = _gate({"morpho_blue": 10_000.0}, adapters=adapters, ddir=tmp_path)
        assert "morpho_blue" not in result["target_usd"]
        assert result["tvl_unverified"] == ["morpho_blue"]

    def test_no_20m_fabrication_registry_without_tvl(self, tmp_path):
        """The pre-ADR-053 $20M substitute is gone: registry-only pool → frozen."""
        _write_registry(tmp_path, {"spark_susds": _reg_entry(fallback_apy=0.055)})
        result = _gate({"spark_susds": 15_000.0}, adapters=[], ddir=tmp_path)
        assert result["target_usd"] == {}
        assert result["tvl_unverified"] == ["spark_susds"]

    def test_live_tvl_below_floor_blocks(self, tmp_path):
        """A LIVE TVL below $5M is a real blocking violation (floor is real)."""
        adapters = [
            _adapter_dict("thin_pool", apy_pct=5.0, tvl_usd=400_000.0, tier="T2")
        ]
        result = _gate({"thin_pool": 10_000.0}, adapters=adapters, ddir=tmp_path)
        assert result["approved"] is False
        assert any("TVL" in v and "thin_pool" in v for v in result["violations"])

    def test_live_tvl_above_floor_allocates(self, tmp_path):
        """Verified live TVL above the floor → full fresh allocation."""
        adapters = [_adapter_dict("aave_v3", apy_pct=3.5, tvl_usd=1e9)]
        result = _gate({"aave_v3": 40_000.0}, adapters=adapters, ddir=tmp_path)
        assert result["approved"] is True
        assert result["target_usd"].get("aave_v3") == 40_000.0
        assert result["tvl_unverified"] == []

    def test_frozen_pool_does_not_block_verified_pools(self, tmp_path):
        """Per-pool fail-closed: one lost feed must not block the whole book."""
        adapters = [
            _adapter_dict("aave_v3", apy_pct=3.5, tvl_usd=2e9),            # live OK
            _adapter_dict("spark_susds", apy_pct=5.5, tvl_usd=0.0),        # feed lost
        ]
        result = _gate(
            {"aave_v3": 40_000.0, "spark_susds": 30_000.0},
            adapters=adapters,
            ddir=tmp_path,
        )
        assert result["approved"] is True
        assert result["target_usd"] == {"aave_v3": 40_000.0}
        assert result["tvl_unverified"] == ["spark_susds"]

    def test_frozen_held_pool_counts_toward_cumulative_caps(self, tmp_path):
        """A frozen HELD T2 pool still consumes the cumulative T2 budget."""
        _write_registry(tmp_path, {"frozen_t2": _reg_entry(fallback_apy=0.05, tier=2)})
        adapters = [
            _adapter_dict("live_t2_a", apy_pct=5.0, tvl_usd=1e8, tier="T2",
                          chain="chain_a"),
            _adapter_dict("live_t2_b", apy_pct=5.0, tvl_usd=1e8, tier="T2",
                          chain="chain_b"),
            _adapter_dict("frozen_t2", apy_pct=5.0, tvl_usd=0.0, tier="T2",
                          chain="chain_c"),
        ]
        # held frozen T2 = 20k; fresh T2 = 20k + 15k → cumulative T2 = 55% > 50%
        result = _gate(
            {"live_t2_a": 20_000.0, "live_t2_b": 15_000.0, "frozen_t2": 20_000.0},
            adapters=adapters,
            ddir=tmp_path,
            current_positions={"frozen_t2": 20_000.0},
        )
        assert result["approved"] is False
        assert any("T2" in v for v in result["violations"]), result["violations"]

    def test_non_finite_tvl_still_blocks(self, tmp_path):
        """A PRESENT non-finite TVL is corrupt-feed → blocking violation."""
        adapters = [
            _adapter_dict("corrupt", apy_pct=4.0, tvl_usd=float("nan"), tier="T2")
        ]
        result = _gate({"corrupt": 10_000.0}, adapters=adapters, ddir=tmp_path)
        assert result["approved"] is False
        assert any("non-finite" in v and "corrupt" in v for v in result["violations"])


# ═══════════════════════════════════════════════════════════════════════════════
# UNIT TESTS — graceful degradation + tier/chain fill (registry metadata)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGracefulDegradation:
    """Missing/corrupt registry → gate runs, never crashes, stays fail-closed."""

    def test_no_registry_file_graceful(self, tmp_path):
        result = _gate({"aave_v3": 40_000.0}, adapters=[], ddir=tmp_path)
        assert result["error"] is None
        # fail-closed: no meta, no registry → pool frozen out of the target
        assert result["target_usd"] == {}
        assert result["tvl_unverified"] == ["aave_v3"]

    def test_corrupt_registry_graceful(self, tmp_path):
        (tmp_path / "adapter_registry.json").write_text(
            "NOT VALID JSON {{{", encoding="utf-8"
        )
        result = _gate({"aave_v3": 40_000.0}, adapters=[], ddir=tmp_path)
        assert result["error"] is None
        assert result["target_usd"] == {}

    def test_empty_adapters_dict_in_registry(self, tmp_path):
        _write_registry(tmp_path, {})
        result = _gate({"aave_v3": 40_000.0}, adapters=[], ddir=tmp_path)
        assert result["error"] is None

    def test_ddir_none_fail_closed(self):
        """When ddir=None no registry is loaded — still frozen, never invented."""
        result = _gate({"aave_v3": 40_000.0}, adapters=[], ddir=None)
        assert result["error"] is None
        assert result["target_usd"] == {}
        assert result["tvl_unverified"] == ["aave_v3"]


class TestTierAndChainFromRegistry:
    """tier/chain fill from the registry still works for accounting purposes."""

    def test_tier_2_from_registry_counts_in_cumulative_cap(self, tmp_path):
        """Registry tier=2 on a frozen held pool feeds the cumulative T2 math."""
        _write_registry(tmp_path, {"reg_t2": _reg_entry(tier=2, fallback_apy=0.041)})
        adapters = [
            _adapter_dict("live_t2", apy_pct=5.0, tvl_usd=1e8, tier="T2",
                          chain="chain_x"),
        ]
        # frozen held reg_t2 (tier from registry) 40k + fresh live_t2 15k
        # → cumulative T2 = 55% > 50% total cap → violation on the live pool
        result = _gate(
            {"live_t2": 15_000.0, "reg_t2": 40_000.0},
            adapters=adapters,
            ddir=tmp_path,
            current_positions={"reg_t2": 40_000.0},
        )
        assert result["approved"] is False
        assert any("T2" in v for v in result["violations"]), result["violations"]

    def test_chain_from_registry_no_crash(self, tmp_path):
        _write_registry(
            tmp_path, {"aave_v3": _reg_entry(chain="ethereum", fallback_apy=0.04)}
        )
        result = _gate({"aave_v3": 40_000.0}, adapters=[], ddir=tmp_path)
        assert result["error"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — run_cycle wiring (ddir + current_positions)
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationRunCycle:
    """run_cycle wires ddir + current_positions into the gate (ADR-053)."""

    def test_run_cycle_no_fresh_capital_without_live_tvl(self, tmp_path):
        """apy fallback exists but TVL unverifiable → no trade, cycle continues."""
        _write_registry(
            tmp_path,
            {
                "aave_v3": _reg_entry(tier=1, fallback_apy=0.035),
                "compound_v3": _reg_entry(tier=1, fallback_apy=0.052),
            },
        )
        adapters = [
            _adapter_dict("aave_v3", apy_pct=0.0, tvl_usd=0.0, status="ok"),
            _adapter_dict("compound_v3", apy_pct=0.0, tvl_usd=0.0, status="ok"),
        ]
        res = _run_cycle(
            tmp_path,
            target_usd={"aave_v3": 40_000.0, "compound_v3": 30_000.0},
            adapters=adapters,
        )
        # per-pool fail-closed: nothing to block, nothing to trade
        assert res.policy_approved is True
        assert res.traded is False
        assert any("TVL unverified" in n for n in res.notes)

    def test_run_cycle_trades_on_verified_live_tvl(self, tmp_path):
        """Live APY + live TVL above floor → trade executes as before."""
        adapters = [
            _adapter_dict("aave_v3", apy_pct=3.5, tvl_usd=2e9, status="ok"),
        ]
        res = _run_cycle(
            tmp_path,
            target_usd={"aave_v3": 40_000.0},
            adapters=adapters,
        )
        assert res.policy_approved is True
        assert res.traded is True

    def test_run_cycle_policy_blocks_json_written_on_block(self, tmp_path):
        """A genuine violation (APY=0, live TVL) → risk_policy_blocks.json."""
        adapters = [_adapter_dict("aave_v3", apy_pct=0.0, tvl_usd=2e8)]
        _run_cycle(tmp_path, {"aave_v3": 40_000.0}, adapters=adapters)
        blocks_path = tmp_path / "risk_policy_blocks.json"
        assert blocks_path.exists()
        blocks = json.loads(blocks_path.read_text())
        recs = blocks if isinstance(blocks, list) else blocks.get("blocks", [])
        assert len(recs) >= 1

    def test_run_cycle_no_blocks_json_when_approved(self, tmp_path):
        """APY fallback + live TVL → approved → no block record written."""
        _write_registry(
            tmp_path, {"aave_v3": _reg_entry(tier=1, fallback_apy=0.035)}
        )
        adapters = [_adapter_dict("aave_v3", apy_pct=0.0, tvl_usd=2e8)]
        _run_cycle(tmp_path, {"aave_v3": 40_000.0}, adapters=adapters)
        blocks_path = tmp_path / "risk_policy_blocks.json"
        if blocks_path.exists():
            blocks = json.loads(blocks_path.read_text())
            recs = blocks if isinstance(blocks, list) else blocks.get("blocks", [])
            assert len(recs) == 0
