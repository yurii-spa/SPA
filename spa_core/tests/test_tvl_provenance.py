"""ADR-053: TVL-provenance contract (``tvl_source``) — adapters + orchestrator.

The RiskPolicy TVL floor ($5M) may only be verified by a TVL the adapter
fetched from a LIVE feed in the same call (``YieldInfo.tvl_source == "live"``).
Anything else — a committed class constant, an undeclared numeric, a lost feed —
is static/unverified and the gate freezes the pool (no fresh capital).

Pinned here:
- live-feed adapters (aave_v3 family) stamp ``tvl_source="live"`` when the feed
  returned a TVL, and ``None`` when the feed is down (never "live" on nothing);
- compound_v3 honestly stamps its committed ``TVL_USD`` constant as "static";
- the orchestrator normalises provenance fail-closed: a numeric TVL WITHOUT a
  live declaration → "static"; no TVL → None (a fixture that "forgets" the
  field can never smuggle a constant through the floor as live).
"""
from __future__ import annotations

from spa_core.adapters.aave_v3 import AaveV3Adapter
from spa_core.adapters.base_adapter import YieldInfo
from spa_core.adapters.compound_v3_adapter import CompoundV3Adapter
from spa_core.orchestrator.adapter_orchestrator import run_orchestrator


# ─── Fake DeFiLlama feed ─────────────────────────────────────────────────────


class _FeedUp:
    def get_apy(self, *_a, **_k):
        return 0.042

    def get_tvl(self, *_a, **_k):
        return 250_000_000.0


class _FeedDown:
    def get_apy(self, *_a, **_k):
        return None

    def get_tvl(self, *_a, **_k):
        return None


# ─── Adapter-level provenance ────────────────────────────────────────────────


class TestAdapterProvenance:
    def test_aave_v3_stamps_live_when_feed_returns_tvl(self):
        info = AaveV3Adapter(feed=_FeedUp()).get_yield_info()
        assert info.tvl_usd == 250_000_000.0
        assert info.tvl_source == "live"

    def test_aave_v3_stamps_none_when_feed_down(self):
        info = AaveV3Adapter(feed=_FeedDown()).get_yield_info()
        assert info.tvl_usd is None
        assert info.tvl_source is None  # never "live" without a value

    def test_compound_v3_live_tvl_stamps_live(self, tmp_path):
        """ADR-053 follow-up: compound_v3 reports the feed's TVL as live."""
        info = CompoundV3Adapter(data_dir=tmp_path, feed=_FeedUp()).get_yield_info()
        assert info.tvl_usd == 250_000_000.0
        assert info.tvl_source == "live"

    def test_compound_v3_feed_down_falls_back_to_labeled_static(self, tmp_path):
        """Feed down → committed TVL_USD constant, honestly labeled static."""
        info = CompoundV3Adapter(data_dir=tmp_path, feed=_FeedDown()).get_yield_info()
        assert info.tvl_usd == float(CompoundV3Adapter.TVL_USD)
        assert info.tvl_source == "static"

    def test_compound_v3_health_and_dict_report_provenance(self, tmp_path):
        up = CompoundV3Adapter(data_dir=tmp_path, feed=_FeedUp())
        down = CompoundV3Adapter(data_dir=tmp_path, feed=_FeedDown())
        assert up.health_check()["tvl_source"] == "live"
        assert up.health_check()["tvl_usd"] == 250_000_000.0
        assert down.health_check()["tvl_source"] == "static"
        assert up.to_dict()["tvl_source"] == "live"
        assert down.to_dict()["tvl_usd"] == float(CompoundV3Adapter.TVL_USD)

    def test_yieldinfo_default_is_undeclared(self):
        """Adapters that never set the field default to None (→ unverified)."""
        info = YieldInfo(
            protocol="x", asset="USDC", apy=0.05, tvl_usd=1e9,
            tier="T2", risk_score=0.3,
        )
        assert info.tvl_source is None


# ─── Orchestrator normalisation (fail-closed) ────────────────────────────────


def _fake_adapter_cls(protocol: str, *, tvl, tvl_source):
    class _Fake:
        PROTOCOL = protocol

        def __init__(self, *_a, **_k):
            pass

        def get_yield_info(self):
            return YieldInfo(
                protocol=protocol, asset="USDC", apy=0.05, tvl_usd=tvl,
                tier="T2", risk_score=0.3, tvl_source=tvl_source,
            )

    _Fake.__name__ = f"Fake_{protocol}"
    return _Fake


class TestOrchestratorProvenance:
    def _record(self, tmp_path, *, tvl, tvl_source):
        res = run_orchestrator(
            registry=[("p1", "T2", _fake_adapter_cls("p1", tvl=tvl,
                                                     tvl_source=tvl_source))],
            write=False,
            data_dir=str(tmp_path),
        )
        return res.adapters[0]

    def test_declared_live_propagates(self, tmp_path):
        rec = self._record(tmp_path, tvl=9e7, tvl_source="live")
        assert rec["tvl_usd"] == 9e7
        assert rec["tvl_source"] == "live"

    def test_undeclared_numeric_normalised_to_static(self, tmp_path):
        """Fail-closed: a numeric TVL without a live declaration is static."""
        rec = self._record(tmp_path, tvl=9e7, tvl_source=None)
        assert rec["tvl_source"] == "static"

    def test_bogus_declaration_normalised_to_static(self, tmp_path):
        rec = self._record(tmp_path, tvl=9e7, tvl_source="totally-live-trust-me")
        assert rec["tvl_source"] == "static"

    def test_missing_tvl_has_no_source(self, tmp_path):
        rec = self._record(tmp_path, tvl=None, tvl_source=None)
        assert rec["tvl_usd"] is None
        assert rec["tvl_source"] is None
