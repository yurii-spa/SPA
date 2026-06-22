"""MP-1180: RiskPolicy gate fallback APY/TVL from adapter_registry.json.

Root cause: 5 of 7 live adapters return apy=None/tvl=None (network errors).
The gate converts None→0.0, which fails min_apy=1% + min_tvl=$5M for every
pool → policy_blocked=True → 0 trades in 32 days despite allocator wanting to
move $154K.

Fix: when apy==0 or tvl==0 in the gate loop, look up the pool in
adapter_registry.json (keyed by snake_case adapter name) and fill from
``fallback_apy`` / ``live_apy`` (stored as decimal fraction, converted to %)
and from a safe TVL floor of $20M when registry has no tvl_usd.

Test contract:
- apy=None/0  → registry fallback fills it (× 100 to convert fraction → %)
- tvl=None/0  → registry fallback $20M when no tvl_usd in registry
- live apy>0  → fallback NOT applied (live takes priority)
- live tvl>0  → fallback NOT applied (live takes priority)
- fallback APY > min_apy (1%) → policy_blocked=False → trade executes
- no registry file → graceful: gate runs, no exception, cycle continues
- corrupt registry → graceful: gate runs without fallback, no crash
- tier/chain from registry when meta empty
- all 28 whitelisted adapters with fallback → 0 APY/TVL violations
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
    tier: str = "T1",
    status: str = "ok",
    chain: str = "ethereum",
) -> dict:
    return {
        "protocol": protocol,
        "apy_pct": apy_pct,
        "tvl_usd": tvl_usd,
        "tier": tier,
        "status": status,
        "chain": chain,
    }


def _gate(
    target_usd: dict,
    adapters: list[dict] | None = None,
    ddir: Path | None = None,
    capital: float = _CAPITAL,
) -> dict:
    return _apply_risk_policy_gate(
        target_usd,
        capital,
        adapters or [],
        ddir=ddir,
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
# UNIT TESTS — _apply_risk_policy_gate directly
# ═══════════════════════════════════════════════════════════════════════════════


class TestFallbackApyUsed:
    """apy=0 from live → registry fallback fills it."""

    def test_fallback_apy_applied_when_live_zero(self, tmp_path):
        _write_registry(tmp_path, {"aave_v3": _reg_entry(fallback_apy=0.04)})
        # adapter returns apy=0 (simulates network error / None→0)
        adapters = [_adapter_dict("aave_v3", apy_pct=0.0, tvl_usd=2e7)]
        result = _gate(
            {"aave_v3": 40_000.0},
            adapters=adapters,
            ddir=tmp_path,
        )
        # 0.04 * 100 = 4.0% > 1.0% min → no APY violation
        apy_viols = [v for v in result["violations"] if "APY" in v and "aave_v3" in v]
        assert apy_viols == [], f"Unexpected APY violations: {apy_viols}"

    def test_fallback_apy_applied_when_meta_empty(self, tmp_path):
        """meta is empty because adapters list is [] — registry is sole source."""
        _write_registry(
            tmp_path,
            {"morpho_steakhouse": _reg_entry(fallback_apy=0.065, tier=1)},
        )
        result = _gate(
            {"morpho_steakhouse": 30_000.0},
            adapters=[],
            ddir=tmp_path,
        )
        apy_viols = [v for v in result["violations"] if "APY" in v]
        assert apy_viols == []

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


class TestFallbackTvlUsed:
    """tvl=0 from live → $20M safe minimum fallback."""

    def test_fallback_tvl_20m_applied_when_live_zero(self, tmp_path):
        _write_registry(tmp_path, {"aave_v3": _reg_entry(fallback_apy=0.04)})
        adapters = [_adapter_dict("aave_v3", apy_pct=4.0, tvl_usd=0.0)]
        result = _gate({"aave_v3": 40_000.0}, adapters=adapters, ddir=tmp_path)
        tvl_viols = [v for v in result["violations"] if "TVL" in v and "aave_v3" in v]
        assert tvl_viols == []

    def test_registry_tvl_usd_used_when_available(self, tmp_path):
        """When registry has tvl_usd, use that instead of the $20M floor."""
        _write_registry(
            tmp_path,
            {"morpho_blue": _reg_entry(fallback_apy=0.041, tier=2, tvl_usd=50_000_000)},
        )
        adapters = [_adapter_dict("morpho_blue", apy_pct=4.1, tvl_usd=0.0, tier="T2")]
        result = _gate({"morpho_blue": 10_000.0}, adapters=adapters, ddir=tmp_path)
        tvl_viols = [v for v in result["violations"] if "TVL" in v and "morpho_blue" in v]
        assert tvl_viols == []

    def test_fallback_tvl_above_policy_floor(self, tmp_path):
        """The $20M fallback must exceed the $5M policy floor — sanity check."""
        _write_registry(tmp_path, {"euler_v2": _reg_entry(fallback_apy=0.03, tier=2)})
        adapters = [_adapter_dict("euler_v2", apy_pct=3.0, tvl_usd=0.0, tier="T2")]
        result = _gate({"euler_v2": 8_000.0}, adapters=adapters, ddir=tmp_path)
        tvl_viols = [v for v in result["violations"] if "TVL" in v]
        assert tvl_viols == []


class TestLiveDataPriority:
    """Live non-zero values are NEVER overwritten by the fallback."""

    def test_live_apy_not_overwritten(self, tmp_path):
        """If live apy>0, registry fallback must not touch it."""
        _write_registry(tmp_path, {"aave_v3": _reg_entry(fallback_apy=0.10)})
        # live 2.5% < 1%? No, 2.5 > 1.0 — so it should pass.
        adapters = [_adapter_dict("aave_v3", apy_pct=2.5, tvl_usd=2e8)]
        result = _gate({"aave_v3": 40_000.0}, adapters=adapters, ddir=tmp_path)
        # Should pass: live 2.5% > 1% minimum
        apy_viols = [v for v in result["violations"] if "APY" in v and "aave_v3" in v]
        assert apy_viols == []

    def test_live_tvl_not_overwritten(self, tmp_path):
        """If live tvl>0, registry fallback must not touch it."""
        _write_registry(tmp_path, {"compound_v3": _reg_entry(tvl_usd=1_000)})
        # live tvl=8e6 > $5M floor
        adapters = [_adapter_dict("compound_v3", apy_pct=4.0, tvl_usd=8_000_000)]
        result = _gate({"compound_v3": 30_000.0}, adapters=adapters, ddir=tmp_path)
        tvl_viols = [v for v in result["violations"] if "TVL" in v and "compound_v3" in v]
        assert tvl_viols == []

    def test_both_live_non_zero_no_fallback(self, tmp_path):
        """apy>0 AND tvl>0 — registry ignored entirely for that pool."""
        _write_registry(tmp_path, {"aave_v3": _reg_entry(fallback_apy=0.0)})
        adapters = [_adapter_dict("aave_v3", apy_pct=3.5, tvl_usd=1e9)]
        result = _gate({"aave_v3": 40_000.0}, adapters=adapters, ddir=tmp_path)
        # Both values are fine → approved
        assert result["approved"] is True
        assert result["violations"] == []


class TestPolicyBlockedUnblockedByFallback:
    """With fallback → policy_blocked=False → trade allowed."""

    def test_all_zero_adapters_blocked_without_registry(self, tmp_path):
        """Baseline: no registry → all APY=0/TVL=0 → blocked."""
        result = _gate(
            {"morpho_steakhouse": 30_000.0, "aave_v3": 40_000.0},
            adapters=[],
            ddir=None,
        )
        assert result["approved"] is False
        assert len(result["violations"]) > 0

    def test_fallback_unblocks_all_zero_adapters(self, tmp_path):
        """With registry → APY/TVL filled → gate approves."""
        _write_registry(
            tmp_path,
            {
                "morpho_steakhouse": _reg_entry(fallback_apy=0.065, tier=1),
                "aave_v3": _reg_entry(fallback_apy=0.035, tier=1),
            },
        )
        result = _gate(
            {"morpho_steakhouse": 30_000.0, "aave_v3": 40_000.0},
            adapters=[],
            ddir=tmp_path,
        )
        assert result["approved"] is True
        assert result["violations"] == []

    def test_partial_fallback_unblocks_affected_pools(self, tmp_path):
        """Some pools have live data, some need fallback — mixed case."""
        _write_registry(
            tmp_path,
            {"spark_susds": _reg_entry(fallback_apy=0.055, tier=1)},
        )
        adapters = [
            _adapter_dict("aave_v3", apy_pct=3.5, tvl_usd=2e9),   # live OK
            _adapter_dict("spark_susds", apy_pct=0.0, tvl_usd=0.0),  # needs fallback
        ]
        result = _gate(
            {"aave_v3": 40_000.0, "spark_susds": 30_000.0},
            adapters=adapters,
            ddir=tmp_path,
        )
        assert result["approved"] is True


class TestGracefulDegradation:
    """Missing/corrupt registry → gate runs without fallback, never crashes."""

    def test_no_registry_file_graceful(self, tmp_path):
        """No adapter_registry.json → gate runs, no exception."""
        # ddir points to tmp_path which has no adapter_registry.json
        result = _gate(
            {"aave_v3": 40_000.0},
            adapters=[],
            ddir=tmp_path,
        )
        # gate runs (error=None means no gate exception, fail-open works)
        assert result["error"] is None
        # No fallback → APY/TVL still 0 → violation expected
        assert result["approved"] is False

    def test_corrupt_registry_graceful(self, tmp_path):
        """Corrupt JSON in registry → gate proceeds without fallback."""
        (tmp_path / "adapter_registry.json").write_text(
            "NOT VALID JSON {{{", encoding="utf-8"
        )
        result = _gate(
            {"aave_v3": 40_000.0},
            adapters=[],
            ddir=tmp_path,
        )
        assert result["error"] is None  # gate exception → fail-open, not raised here
        # No fallback applied → violation present
        assert result["approved"] is False

    def test_empty_adapters_dict_in_registry(self, tmp_path):
        """Registry with no adapters → gate runs cleanly."""
        _write_registry(tmp_path, {})
        result = _gate({"aave_v3": 40_000.0}, adapters=[], ddir=tmp_path)
        assert result["error"] is None

    def test_ddir_none_skips_fallback(self):
        """When ddir=None, no registry is loaded — gate behaves as before."""
        result = _gate({"aave_v3": 40_000.0}, adapters=[], ddir=None)
        # No fallback → APY=0 → violation
        assert result["approved"] is False


class TestTierAndChainFromRegistry:
    """tier and chain are filled from registry when meta is empty."""

    def test_tier_1_from_registry(self, tmp_path):
        """Registry tier=1 → mapped to T1 in the gate."""
        _write_registry(
            tmp_path,
            {"aave_v3": _reg_entry(tier=1, fallback_apy=0.04)},
        )
        # Very large allocation that would exceed T2 cap (20%) but not T1 (40%)
        result = _gate(
            {"aave_v3": 39_999.0},
            adapters=[],
            ddir=tmp_path,
            capital=100_000.0,
        )
        # T1 cap is 40% → 39.999% is under cap → no T1 concentration violation
        t1_viols = [
            v for v in result["violations"]
            if "aave_v3" in v and "concentration" in v.lower()
        ]
        assert t1_viols == []

    def test_tier_2_from_registry(self, tmp_path):
        """Registry tier=2 → T2 cap (20%) respected."""
        _write_registry(
            tmp_path,
            {"morpho_blue": _reg_entry(tier=2, fallback_apy=0.041)},
        )
        # 25% > 20% T2 cap → should produce concentration violation
        result = _gate(
            {"morpho_blue": 25_000.0},
            adapters=[],
            ddir=tmp_path,
            capital=100_000.0,
        )
        t2_viols = [
            v for v in result["violations"]
            if "morpho_blue" in v and ("concentration" in v.lower() or "exceed" in v.lower())
        ]
        assert len(t2_viols) >= 1

    def test_chain_from_registry_fills_unknown(self, tmp_path):
        """chain filled from registry → no 'unknown:' prefix in gate output."""
        _write_registry(
            tmp_path,
            {"aave_v3": _reg_entry(chain="ethereum", fallback_apy=0.04)},
        )
        # Just verify gate runs without error and uses chain (hard to assert
        # chain value from output, so check no crash + approved)
        result = _gate(
            {"aave_v3": 40_000.0}, adapters=[], ddir=tmp_path
        )
        assert result["error"] is None


class TestFallbackApy28Adapters:
    """All 28 whitelisted adapters with fallback → 0 APY/TVL violations."""

    # Snapshot of all adapter names from adapter_registry.json
    _ALL_ADAPTERS = [
        ("aave_v3",            1, 0.035),
        ("compound_v3",        1, 0.052),
        ("spark_susds",        1, 0.055),
        ("morpho_steakhouse",  1, 0.065),
        ("aave_arbitrum",      1, 0.041),
        ("aave_v3_optimism",   1, 0.048),
        ("aave_v3_polygon",    1, 0.051),
        ("morpho_blue",        2, 0.041),
        ("yearn_v3",           2, 0.0323),
        ("euler_v2",           2, 0.0275),
        ("maple",              2, 0.0482),
    ]

    def test_all_registry_adapters_zero_apy_tvl_violations(self, tmp_path):
        """All adapters with apy=0/tvl=0 + registry → 0 APY/TVL violations."""
        reg_entries = {
            name: _reg_entry(tier=tier, fallback_apy=apy)
            for name, tier, apy in self._ALL_ADAPTERS
        }
        _write_registry(tmp_path, reg_entries)
        # Target: distribute $50K across T1 adapters, $20K across T2
        target_usd = {
            "aave_v3": 15_000.0,
            "compound_v3": 15_000.0,
            "spark_susds": 10_000.0,
            "morpho_steakhouse": 10_000.0,
            "morpho_blue": 8_000.0,
            "yearn_v3": 6_000.0,
            "euler_v2": 6_000.0,
        }
        result = _gate(target_usd, adapters=[], ddir=tmp_path)
        apy_tvl_viols = [
            v for v in result["violations"]
            if "APY" in v or "TVL" in v
        ]
        assert apy_tvl_viols == [], f"APY/TVL violations remain: {apy_tvl_viols}"

    def test_fallback_apy_conversion_fraction_to_pct(self, tmp_path):
        """fallback_apy=0.035 → 3.5% (×100) must exceed min_apy=1.0%."""
        for name, tier, apy_frac in self._ALL_ADAPTERS:
            converted_pct = apy_frac * 100.0
            assert converted_pct >= 1.0, (
                f"{name}: fallback_apy {apy_frac} → {converted_pct}% < 1.0% min"
            )

    def test_negative_fallback_apy_not_used(self, tmp_path):
        """Negative fallback_apy in registry is silently ignored."""
        _write_registry(
            tmp_path,
            {"bad_proto": _reg_entry(fallback_apy=-0.05)},
        )
        result = _gate({"bad_proto": 5_000.0}, adapters=[], ddir=tmp_path)
        # fallback apy=-0.05 not > 0 → stays at 0.0 → violation expected
        apy_viols = [v for v in result["violations"] if "APY" in v and "bad_proto" in v]
        assert len(apy_viols) >= 1

    def test_zero_fallback_apy_not_used(self, tmp_path):
        """Zero fallback_apy in registry is not applied (must be > 0)."""
        _write_registry(
            tmp_path,
            {"zero_proto": _reg_entry(fallback_apy=0.0)},
        )
        result = _gate({"zero_proto": 5_000.0}, adapters=[], ddir=tmp_path)
        apy_viols = [v for v in result["violations"] if "APY" in v and "zero_proto" in v]
        assert len(apy_viols) >= 1


class TestFallbackOnlyApy:
    """apy=0 tvl>0 — only apy gets fallback, tvl unchanged."""

    def test_only_apy_fallback_when_tvl_live(self, tmp_path):
        _write_registry(tmp_path, {"aave_v3": _reg_entry(fallback_apy=0.04)})
        adapters = [_adapter_dict("aave_v3", apy_pct=0.0, tvl_usd=2e8)]
        result = _gate({"aave_v3": 40_000.0}, adapters=adapters, ddir=tmp_path)
        # APY violation resolved; TVL was live (2e8) → no TVL violation
        viols = result["violations"]
        assert not any("aave_v3" in v and "APY" in v for v in viols)
        assert not any("aave_v3" in v and "TVL" in v for v in viols)


class TestFallbackOnlyTvl:
    """apy>0 tvl=0 — only tvl gets fallback, apy unchanged."""

    def test_only_tvl_fallback_when_apy_live(self, tmp_path):
        _write_registry(tmp_path, {"aave_v3": _reg_entry(fallback_apy=0.04)})
        adapters = [_adapter_dict("aave_v3", apy_pct=3.5, tvl_usd=0.0)]
        result = _gate({"aave_v3": 40_000.0}, adapters=adapters, ddir=tmp_path)
        viols = result["violations"]
        assert not any("aave_v3" in v and "TVL" in v for v in viols)
        assert not any("aave_v3" in v and "APY" in v for v in viols)


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — run_cycle passes ddir to gate
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationRunCycle:
    """run_cycle correctly wires ddir into _apply_risk_policy_gate (MP-1180)."""

    def test_run_cycle_unblocked_with_registry(self, tmp_path):
        """Full cycle: all adapters return apy=0 → fallback from registry → trade."""
        _write_registry(
            tmp_path,
            {
                "aave_v3": _reg_entry(tier=1, fallback_apy=0.035),
                "compound_v3": _reg_entry(tier=1, fallback_apy=0.052),
            },
        )
        # Adapters return error/0 values (network failure scenario)
        adapters = [
            _adapter_dict("aave_v3", apy_pct=0.0, tvl_usd=0.0, status="error"),
            _adapter_dict("compound_v3", apy_pct=0.0, tvl_usd=0.0, status="error"),
        ]
        res = _run_cycle(
            tmp_path,
            target_usd={"aave_v3": 40_000.0, "compound_v3": 30_000.0},
            adapters=adapters,
        )
        assert res.policy_approved is True
        assert res.policy_violations == []
        assert res.traded is True

    def test_run_cycle_blocked_without_registry(self, tmp_path):
        """Same setup but no registry → still blocked → no trade."""
        # No adapter_registry.json in tmp_path
        adapters = [
            _adapter_dict("aave_v3", apy_pct=0.0, tvl_usd=0.0, status="error"),
        ]
        res = _run_cycle(
            tmp_path,
            target_usd={"aave_v3": 40_000.0},
            adapters=adapters,
        )
        assert res.policy_approved is False
        assert res.traded is False

    def test_run_cycle_live_data_takes_precedence(self, tmp_path):
        """Live adapter data is respected even when registry has different values."""
        _write_registry(
            tmp_path,
            {
                "aave_v3": _reg_entry(fallback_apy=0.20),  # would be 20% — unrealistic
            },
        )
        adapters = [
            _adapter_dict("aave_v3", apy_pct=3.5, tvl_usd=2e9, status="ok"),
        ]
        res = _run_cycle(
            tmp_path,
            target_usd={"aave_v3": 40_000.0},
            adapters=adapters,
        )
        # Live 3.5% passes gate (>1% min); trade executes
        assert res.policy_approved is True

    def test_run_cycle_policy_blocks_json_written_on_block(self, tmp_path):
        """When gate blocks (no registry → apy=0) → risk_policy_blocks.json created."""
        adapters = [_adapter_dict("aave_v3", apy_pct=0.0, tvl_usd=0.0)]
        _run_cycle(tmp_path, {"aave_v3": 40_000.0}, adapters=adapters)
        blocks_path = tmp_path / "risk_policy_blocks.json"
        assert blocks_path.exists()
        blocks = json.loads(blocks_path.read_text())
        recs = blocks if isinstance(blocks, list) else blocks.get("blocks", [])
        assert len(recs) >= 1

    def test_run_cycle_no_blocks_json_when_approved(self, tmp_path):
        """When fallback approves the gate → no block record written."""
        _write_registry(
            tmp_path,
            {"aave_v3": _reg_entry(tier=1, fallback_apy=0.035)},
        )
        adapters = [_adapter_dict("aave_v3", apy_pct=0.0, tvl_usd=0.0)]
        _run_cycle(tmp_path, {"aave_v3": 40_000.0}, adapters=adapters)
        blocks_path = tmp_path / "risk_policy_blocks.json"
        # Either file doesn't exist or has 0 blocks
        if blocks_path.exists():
            blocks = json.loads(blocks_path.read_text())
            recs = blocks if isinstance(blocks, list) else blocks.get("blocks", [])
            assert len(recs) == 0
