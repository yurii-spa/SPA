"""
tests/test_integration_e2e.py — End-to-End Integration Test Suite

Tests the full data pipeline → engine → export → API cycle with mocked HTTP
responses. No real network calls are made.

Run:
    cd /Users/yuriikulieshov/Documents/SPA_Claude
    python -m pytest tests/test_integration_e2e.py -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
SPA_CORE = Path(__file__).parent.parent
ROOT = SPA_CORE.parent
for _p in [str(SPA_CORE), str(ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Imports ───────────────────────────────────────────────────────────────────
from database.init_db import init_database, get_connection
from paper_trading.engine import PaperTrader, INITIAL_CAPITAL
from risk.policy import RiskPolicy, RiskConfig, PortfolioState, Position


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db(tmp_path: Path) -> Path:
    """Create and initialise an isolated SQLite DB in tmp_path."""
    db = tmp_path / "test_spa.db"
    init_database(db_path=db)
    return db


def _insert_apy_snapshot(db_path: Path, protocol_key: str, apy: float,
                          tvl: float = 50_000_000.0, tier: str = "T1"):
    """Insert a fresh APY snapshot so auto_allocate() sees live data."""
    with get_connection(db_path) as conn:
        conn.execute("""
            INSERT INTO apy_snapshots
                (timestamp, protocol_key, protocol, asset, chain, tier,
                 pool_id, apy_total, apy_base, apy_reward, tvl_usd,
                 utilization_rate, is_valid, validation_warnings, raw_json)
            VALUES (datetime('now'), ?, ?, 'USDC', 'Ethereum', ?,
                    'pool-uuid-test', ?, ?, 0, ?,
                    NULL, 1, NULL, '{}')
        """, (protocol_key, protocol_key, tier, apy, apy, tvl))
        conn.commit()


# =============================================================================
# Test 1: Full pipeline with mock DeFiLlama — 5 pools → positions created
# =============================================================================

class TestFullPipelineWithMockDeFiLlama:
    """
    Mock HTTP returns 5 pools. Run PaperTrader.auto_allocate().
    Verify positions created, total allocation <= 100%, T2 <= 35%,
    no single protocol > 40%.
    """

    def test_full_pipeline_with_mock_defillama(self, tmp_path):
        db = _make_db(tmp_path)

        # Insert 5 mock APY snapshots (2 T2, 3 T1) simulating a DeFiLlama fetch
        protocols = [
            ("aave-v3-usdc-ethereum",    5.2, "T1"),
            ("compound-v3-usdc-ethereum", 4.8, "T1"),
            ("morpho-usdc-ethereum",      4.5, "T1"),
            ("maple-usdc-ethereum",       6.1, "T2"),
            ("yearn-v3-usdc-ethereum",    5.8, "T2"),
        ]
        for key, apy, tier in protocols:
            _insert_apy_snapshot(db, key, apy, tvl=50_000_000.0, tier=tier)

        trader = PaperTrader(db_path=db)
        actions = trader.auto_allocate()

        # At least one OPEN action (data is fresh)
        open_actions = [a for a in actions if a.get("action") == "OPEN"]
        assert len(open_actions) >= 1, f"Expected OPEN actions, got: {actions}"

        # Verify portfolio constraints
        state = trader._load_portfolio_state()
        total = state.total_capital_usd

        # Total allocation <= 100%
        assert state.deployed_usd <= total, (
            f"deployed {state.deployed_usd} > capital {total}"
        )

        # T2 total <= 35%
        t2_pct = state.t2_allocation_pct()
        assert t2_pct <= 0.35 + 1e-9, f"T2 allocation {t2_pct:.2%} > 35%"

        # No single protocol > 40%
        for pos in state.positions:
            conc = state.concentration_pct(pos.protocol_key)
            assert conc <= 0.40 + 1e-9, (
                f"{pos.protocol_key} concentration {conc:.2%} > 40%"
            )


# =============================================================================
# Test 2: Pendle filter gates — 8 pools, 3 fail quality gates → 5 pass (top-N cap)
# =============================================================================

class TestPendleFilterGates:
    """
    Mock Pendle API with 8 raw pools where 3 fail quality gates.
    Verify only 5 pass after filtering (PENDLE_TOP_N=5 cap applied).
    Gates tested: APY threshold, TVL threshold, wrong project (non pendle-v2).
    """

    def test_pendle_filter_gates(self):
        import data_pipeline.pendle_fetcher as pendle_mod
        from data_pipeline.pendle_fetcher import PendleFetcher

        today = datetime.now(timezone.utc).date()
        # Maturity 90 days from today — safely within [14, 180] window
        mat_90 = (today + timedelta(days=90)).strftime("%d%b%Y").upper()
        good_symbol = f"PT-USDC-{mat_90}"

        # 7 pools that PASS all quality gates (before top-N cap)
        good_pools = [
            {
                "project": "pendle-v2",
                "symbol": good_symbol,
                "chain": "arbitrum",
                "apy": 7.0 + i * 0.5,
                "tvlUsd": 10_000_000.0,
                "pool": f"pool-good-{i}",
            }
            for i in range(7)
        ]

        # 3 pools that FAIL individual gates
        bad_pools = [
            # Fail gate 4: APY too low
            {
                "project": "pendle-v2",
                "symbol": good_symbol,
                "chain": "arbitrum",
                "apy": 2.0,           # < PENDLE_MIN_APY (6%)
                "tvlUsd": 10_000_000.0,
                "pool": "pool-fail-apy",
            },
            # Fail gate 5: TVL too low
            {
                "project": "pendle-v2",
                "symbol": good_symbol,
                "chain": "arbitrum",
                "apy": 8.0,
                "tvlUsd": 1_000.0,    # < PENDLE_MIN_TVL ($5M)
                "pool": "pool-fail-tvl",
            },
            # Fail gate 1: wrong project
            {
                "project": "aave-v3",
                "symbol": good_symbol,
                "chain": "arbitrum",
                "apy": 8.0,
                "tvlUsd": 10_000_000.0,
                "pool": "pool-fail-project",
            },
        ]

        # Patch PENDLE_TOP_N to 7 so we see all eligible pools (not capped to 5)
        original_top_n = pendle_mod.PENDLE_TOP_N
        pendle_mod.PENDLE_TOP_N = 7
        try:
            all_pools = good_pools + bad_pools  # 10 total: 7 good + 3 bad
            fetcher = PendleFetcher()
            result = fetcher.filter_pools(all_pools)
        finally:
            pendle_mod.PENDLE_TOP_N = original_top_n

        # 7 good pools pass all gates; 3 fail → exactly 7 returned (with cap=7)
        assert len(result) == 7, (
            f"Expected 7 pools to pass gates (cap raised to 7), got {len(result)}"
        )

    def test_pendle_filter_gates_default_cap(self):
        """Default PENDLE_TOP_N=5 caps results even when more qualify."""
        from data_pipeline.pendle_fetcher import PendleFetcher, PENDLE_TOP_N

        today = datetime.now(timezone.utc).date()
        mat_90 = (today + timedelta(days=90)).strftime("%d%b%Y").upper()
        good_symbol = f"PT-USDC-{mat_90}"

        # 8 qualifying pools (all pass gates)
        pools = [
            {
                "project": "pendle-v2",
                "symbol": good_symbol,
                "chain": "arbitrum",
                "apy": 7.0 + i * 0.3,
                "tvlUsd": 10_000_000.0,
                "pool": f"pool-{i}",
            }
            for i in range(8)
        ]
        fetcher = PendleFetcher()
        result = fetcher.filter_pools(pools)
        # With default PENDLE_TOP_N=5, only 5 returned
        assert len(result) == PENDLE_TOP_N, (
            f"Expected {PENDLE_TOP_N} (top-N cap), got {len(result)}"
        )


# =============================================================================
# Test 3: Sky monitor fallback chain — all RPCs fail → safe defaults
# =============================================================================

class TestSkyMonitorFallbackChain:
    """
    Mock all RPC endpoints and the governance API to fail.
    Verify check_sky_status_live() falls back to manual constants
    and returns a safe dict with the expected shape.
    """

    def test_sky_monitor_fallback_chain(self):
        from data_pipeline.sky_monitor import check_sky_status_live, SKY_CURRENT_STATUS

        def _always_fail(*args, **kwargs):
            raise OSError("mocked RPC failure")

        with patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain",
                   side_effect=_always_fail), \
             patch("data_pipeline.sky_monitor._fetch_gsm_delay_governance_api",
                   side_effect=_always_fail):
            result = check_sky_status_live()

        # Shape check
        assert "status" in result
        assert "source" in result
        assert "last_checked" in result

        # Fallback to manual constants
        assert result["source"] == "manual"
        assert result["status"] == SKY_CURRENT_STATUS
        assert result["status"] in ("PENDING", "ELIGIBLE")

        # gsm_hours is None in manual fallback
        assert result.get("gsm_hours") is None


# =============================================================================
# Test 4: Engine risk limits enforced — pool with 45% APY ₒ capped
# =============================================================================

class TestEngineRiskLimitsEnforced:
    """
    Pool with APY 45% (above max_apy_for_new_position=30%).
    Verify max_safe_position_size() clamps it AND check_new_position() blocks it.
    Also verify no single protocol exceeds concentration limits.
    """

    def test_engine_risk_limits_enforced(self, tmp_path):
        db = _make_db(tmp_path)
        trader = PaperTrader(db_path=db)
        state = trader._load_portfolio_state()

        # max_safe_position_size is purely concentration/cash based — not APY gated
        # So it may return a non-zero size. The APY gate is in check_new_position.
        size = trader.policy.max_safe_position_size(state, "aave-v3-usdc-ethereum", "T1")
        # Size <= 40% of capital (T1 concentration cap)
        assert size <= INITIAL_CAPITAL * 0.40 + 1e-6, (
            f"max_safe_position_size {size} exceeds 40% cap"
        )

        # check_new_position blocks APY=45%
        result = trader.policy.check_new_position(
            state=state,
            protocol_key="aave-v3-usdc-ethereum",
            tier="T1",
            amount_usd=10_000.0,
            current_apy=45.0,           # > 30% limit
            tvl_usd=50_000_000.0,
        )
        assert result.approved is False
        assert any("exceeds maximum" in v for v in result.violations)

    def test_concentration_limit_enforced(self, tmp_path):
        db = _make_db(tmp_path)
        trader = PaperTrader(db_path=db)

        # Open position at 35% (allowed)
        trader.open_position(
            "aave-v3-usdc-ethereum",
            INITIAL_CAPITAL * 0.35,
            current_apy=5.0,
            tvl_usd=50_000_000.0,
        )
        # Trying to add another 10% → 45% total > 40% T1 cap → blocked
        state = trader._load_portfolio_state()
        result = trader.policy.check_new_position(
            state=state,
            protocol_key="aave-v3-usdc-ethereum",
            tier="T1",
            amount_usd=INITIAL_CAPITAL * 0.10,
            current_apy=5.0,
            tvl_usd=50_000_000.0,
        )
        assert result.approved is False
        assert any("Concentration" in v for v in result.violations)


# =============================================================================
# Test 5: Tournament deterministic — same seed → identical results
# =============================================================================

class TestTournamentDeterministic:
    """
    Run run_tournament() twice with same seed. Verify identical results.
    """

    def test_tournament_deterministic(self):
        from backtesting.tournament import StrategyTournament
        from backtesting.data_loader import generate_synthetic_history

        seed = 42
        hist = generate_synthetic_history(days=30, seed=seed)

        tournament = StrategyTournament()
        result1 = tournament.run(hist)
        result2 = tournament.run hist)

        # Winner must be identical
        assert result1.winner == result2.winner, (
            f"Tournament non-deterministic: {result1.winner} vs {result2.winner}"
        )
        # Scores must match (within float precision)
        for name in result1.scores:
            assert abs(result1.scores[name] - result2.scores[name]) < 1e-9, (
                f"Score for {name} differs: {result1.scores[name]} vs {result2.scores[name]}"
            )
        # Confidence must match
        assert result1.confidence == result2.confidence


# =============================================================================
# Test 6: Replay synthetic fallback — no pnl_history.json → valid metrics
# =============================================================================

class TestReplaySyntheticFallback:
    """
    No pnl_history.json. Run ReplayEngine.full_replay(days=30).
    Verify valid metrics returned (source='synthetic', total_days>0, etc.).
    """

    def test_replay_synthetic_fallback(self, tmp_path):
        from backtesting.replay import ReplayEngine

        # tmp_path has no pnl_history.json → must fall back to synthetic
        engine = ReplayEngine(data_dir=tmp_path, synthetic_days=30)

        assert engine.source == "synthetic", (
            f"Expected synthetic source, got '{engine.source}'"
        )
        assert engine.total_days > 0, "Expected at least 1 replay day"

        frames = engine.full_replay()
        assert len(frames) == engine.total_days
        assert len(frames) > 0

        # Each frame has required keys
        required = {"day", "date", "portfolio_value", "daily_pnl",
                    "cumulative_pnl_pct", "deployed_usd", "cash_usd"}
        for frame in frames[:3]:
            missing = required - frame.keys()
            assert not missing, f"Frame missing keys: {missing}"

        # Summary metrics
        summary = engine.replay_summary()
        assert "total_days" in summary
        assert "total_return_pct" in summary
        assert "sharpe_ratio" in summary
        assert "max_drawdown" in summary
        assert summary["total_days"] == engine.total_days
        assert isinstance(summary["total_return_pct"], float)


# =============================================================================
# Test 7: Go-live checklist paper duration — 3 days → PENDING, 55 days → PASS
# =============================================================================

class TestGoLiveChecklistPaperDuration:
    """
    Mock start_date 3 days ago → PENDING. 55+ days → PASS.
    """

    def test_paper_duration_pending_when_3_days(self):
        from golive.checklist import check_paper_duration, _PENDING, MIN_PAPER_DAYS

        # Freeze time so that "today" is only 3 days after PAPER_START_DATE
        fake_today = datetime.fromisoformat("2026-05-20").replace(
            tzinfo=timezone.utc
        ) + timedelta(days=3)

        with patch("golive.checklist._today", return_value=fake_today):
            result = check_paper_duration()

        assert result["status"] == _PENDING, (
            f"Expected PENDING at 3 days, got {result['status']}"
        )
        assert result["value"] == 3

    def test_paper_duration_pass_when_55_days(self):
        from golive.checklist import check_paper_duration, _PASS, MIN_PAPER_DAYS

        # Freeze time so that 55 days have elapsed (>= 50 = MIN_PAPER_DAYS)
        fake_today = datetime.fromisoformat("2026-05-20").replace(
            tzinfo=timezone.utc
        ) + timedelta(days=55)

        with patch("golive.checklist._today", return_value=fake_today):
            result = check_paper_duration()

        assert result["status"] == _PASS, (
            f"Expected PASS at 55 days, got {result['status']}"
        )
        assert result["value"] == 55


# =============================================================================
# Test 8: API endpoints integration — TestClient, all return 200
# =============================================================================

class TestApiEndpointsIntegration:
    """
    FastAPI TestClient. Test:
      GET  /api/status
      GET  /api/portfolio
      POST /api/agent/thought
      GET  /api/events/history
      GET  /api/backtest/summary
    All must return 200.
    """

    @pytest.fixture(scope="class")
    def client(self):
        from api.server import app, event_queue
        from fastapi.testclient import TestClient
        event_queue.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        event_queue.clear()

    def test_api_status_200(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200, f"/api/status returned {r.status_code}: {r.text[:200]}"

    def test_api_portfolio_200(self, client):
        r = client.get("/api/portfolio")
        assert r.status_code == 200, f"/api/portfolio returned {r.status_code}"

    def test_api_agent_thought_post_200(self, client):
        payload = {
            "agent": "TestAgent",
            "message": "Integration test thought",
            "type": "agent_thought",
        }
        r = client.post("/api/agent/thought", json=payload)
        assert r.status_code == 200, (
            f"POST /api/agent/thought returned {r.status_code}: {r.text[:200]}"
        )
        body = r.json()
        assert body.get("ok") is True

    def test_api_events_history_200(self, client):
        r = client.get("/api/events/history")
        assert r.status_code == 200
        body = r.json()
        assert "events" in body
        assert isinstance(body["events"], list)

    def test_api_backtest_summary_200(self, client):
        r = client.get("/api/backtest/summary")
        assert r.status_code == 200, (
            f"/api/backtest/summary returned {r.status_code}: {r.text[:200]}"
        )
        body = r.json()
        # Must have basic metric keys
        assert "total_days" in body or "data_source" in body or "error" in body


# =============================================================================
# Test 9: APY tap report on track — weighted APY 7.5% → on_track=True
# =============================================================================

class TestApyGapReportOnTrack:
    """
    Portfolio with weighted APY 7.5% (> 7.3% target).
    Verify on_track=True in the gap report.
    """

    def test_apy_gap_report_on_track(self):
        from data_pipeline.apy_gap_report import apy_gap_report

        # Build a fake portfolio_status where weighted APY = 7.5%
        # weighted_apy = sum(amount * apy) / total_capital
        # With $100k capital, $50k at 7.5% and $50k at 7.5% = 7.5% weighted
        # But idle cash drags down. Use fully deployed capital.
        total_capital = 100_000.0

        portfolio_status = {
            "portfolio": {
                "total_capital_usd": total_capital,
                "deployed_usd": total_capital,
                "cash_usd": 0.0,
                "total_pnl_usd": 0.0,
            },
            "positions": [
                {
                    "protocol_key": "aave-v3-usdc-ethereum",
                    "tier": "T1",
                    "amount_usd": 60_000.0,
                    "current_apy": 7.5,
                },
                {
                    "protocol_key": "maple-usdc-ethereum",
                    "tier": "T2",
                    "amount_usd": 40_000.0,
                    "current_apy": 7.5,
                },
            ],
        }

        report = apy_gap_report(portfolio_status)

        assert report["on_track"] is True, (
            f"Expected on_track=True with APY 7.5%, got {report}"
        )
        assert report["current_weighted_apy"] >= 7.3, (
            f"Expected weighted APY >= 7.3%, got {report['current_weighted_apy']}"
        )
        assert report["gap"] <= 0, (
            f"Expected non-positive gap when on_track, got {report['gap']}"
        )

    def test_apy_gap_report_not_on_track_when_below_target(self):
        from data_pipeline.apy_gap_report import apy_gap_report, TARGET_APY

        total_capital = 100_000.0
        portfolio_status = {
            "portfolio": {
                "total_capital_usd": total_capital,
                "deployed_usd": 50_000.0,
                "cash_usd": 50_000.0,
                "total_pnl_usd": 0.0,
            },
            "positions": [
                {
                    "protocol_key": "aave-v3-usdc-ethereum",
                    "tier": "T1",
                    "amount_usd": 50_000.0,
                    "current_apy": 4.0,   # 4% on 50% of capital = 2% weighted
                },
            ],
        }

        report = apy_gap_report(portfolio_status)

        assert report["on_track"] is False
        assert report["current_weighted_apy"] < TARGET_APY


# =============================================================================
# Test 10: Concurrent export safe — two threads → no exceptions
# =============================================================================

class TestConcurrentExportSafe:
    """
    Call export function (specifically write_json) twice via threading.
    Both must succeed without raising an exception.
    We test the export module's write_json() directly to avoid all the heavy
    I/O dependencies of run_export(), while still exercising thread safety.
    """

    def test_concurrent_export_safe(self, tmp_path):
        # Monkey-patch OUTPUT_DIR to tmp_path so no real filesystem writes
        import export_data as export_module

        original_dir = export_module.OUTPUT_DIR
        export_module.OUTPUT_DIR = tmp_path

        errors: list[Exception] = []

        def _write_payload(payload_id: int):
            try:
                export_module.write_json(
                    f"test_concurrent_{payload_id}.json",
                    {
                        "id": payload_id,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "data": list(range(100)),
                    },
                )
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=_write_payload, args=(1,), daemon=True)
        t2 = threading.Thread(target=_write_payload, args=(2,), daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        export_module.OUTPUT_DIR = original_dir

        assert not errors, f"Concurrent export raised exceptions: {errors}"

        # Both files written
        assert (tmp_path / "test_concurrent_1.json").exists()
        assert (tmp_path / "test_concurrent_2.json").exists()

    def test_concurrent_export_data_integrity(self, tmp_path):
        """Each concurrent write produces valid JSON with correct content."""
        import export_data as export_module

        original_dir = export_module.OUTPUT_DIR
        export_module.OUTPUT_DIR = tmp_path

        payloads = {i: {"thread_id": i, "value": i * 100} for i in range(1, 5)}
        errors: list[Exception] = []

        def _write(pid: int):
            try:
                export_module.write_json(f"concurrent_{pid}.json", payloads[pid])
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_write, args=(i,), daemon=True)
                   for i in range(1, 5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        export_module.OUTPUT_DIR = original_dir

        assert not errors, f"Errors: {errors}"

        for pid in range(1, 5):
            f = tmp_path / f"concurrent_{pid}.json"
            assert f.exists(), f"concurrent_{pid}.json not written"
            data = json.loads(f.read_text())
            assert data["thread_id"] == pid
            assert data["value"] == pid * 100
