"""
Deterministic unit tests for spa_core.execution.engine_bridge
(SPA-V41-001 / FEAT-004+005 Phase 4 — engine.py live execution wiring).

Scope:
  * _parse_protocol_key happy paths and malformed inputs
  * SKIPPED when SPA_EXECUTION_MODE != "live" (the default)
  * SKIPPED when PaperTrader.live_execution=False (the most important
    regression test — proves default behaviour is unchanged)
  * Live + flag-on path: bridge dispatches to a mocked adapter and writes
    an audit-log entry; SUCCESS, FAILED, BLOCKED variants
  * Adapter exception is swallowed (bridge never raises) AND log is written
  * Paper INSERT still happens when the live leg fails
  * Audit log file capping at LOG_MAX_ENTRIES

The bridge is exercised in isolation (no real RPC, no DB). Adapters are
monkey-patched into the bridge's lazy-import path so we don't accidentally
call out to a real chain.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from spa_core.execution import engine_bridge as eb
from spa_core.execution.engine_bridge import (
    LiveExecutionBridge,
    LOG_MAX_ENTRIES,
    _parse_protocol_key,
    _execution_mode_live,
)


# ─── Fakes ────────────────────────────────────────────────────────────────────

class _FakeAdapter:
    """Minimal adapter stub matching the structural contract used by the
    bridge. Records every call for assertions."""

    SUPPORTED_CHAINS = ["ethereum", "arbitrum", "base"]
    SUPPORTED_ASSETS = ["USDC", "USDT", "DAI"]

    def __init__(
        self,
        chain: str = "ethereum",
        dry_run: bool = False,
        supply_response: dict | None = None,
        withdraw_response: dict | None = None,
        supply_raises: BaseException | None = None,
        withdraw_raises: BaseException | None = None,
    ) -> None:
        if chain not in self.SUPPORTED_CHAINS:
            raise ValueError(f"unsupported chain {chain}")
        self.chain = chain
        self.dry_run = dry_run
        self.supply_calls: list[tuple[str, float]] = []
        self.withdraw_calls: list[tuple[str, float]] = []
        self._supply_response = supply_response or {
            "status": "SUCCESS",
            "supply_tx": "0xfeed",
            "approve_tx": "0xbeef",
            "block_number": 100,
        }
        self._withdraw_response = withdraw_response or {
            "status": "SUCCESS",
            "withdraw_tx": "0xdead",
            "block_number": 101,
        }
        self._supply_raises = supply_raises
        self._withdraw_raises = withdraw_raises

    def supply(self, asset: str, amount: float) -> dict:
        self.supply_calls.append((asset, amount))
        if self._supply_raises:
            raise self._supply_raises
        return dict(self._supply_response, asset=asset, amount=amount, chain=self.chain)

    def withdraw(self, asset: str, amount: float) -> dict:
        self.withdraw_calls.append((asset, amount))
        if self._withdraw_raises:
            raise self._withdraw_raises
        return dict(self._withdraw_response, asset=asset, amount=amount, chain=self.chain)


def _make_bridge(tmp_path: Path) -> LiveExecutionBridge:
    """Return a bridge whose audit log lives inside tmp_path."""
    return LiveExecutionBridge(log_path=tmp_path / "live_execution_log.json")


def _patch_adapters(monkeypatch, aave_cls=None, comp_cls=None):
    """Inject fake adapter classes into the bridge's lazy-import sites.

    The bridge imports the adapter classes inside _get_adapter(); we
    monkey-patch the *module-level* names in aave_v3_adapter /
    compound_v3_adapter so the bridge's `from X import Y` picks up the fake.
    """
    if aave_cls is not None:
        import spa_core.execution.aave_v3_adapter as aave_mod
        monkeypatch.setattr(aave_mod, "AaveV3Adapter", aave_cls)
    if comp_cls is not None:
        import spa_core.execution.compound_v3_adapter as comp_mod
        monkeypatch.setattr(comp_mod, "CompoundV3Adapter", comp_cls)


@pytest.fixture
def force_live(monkeypatch):
    """Set SPA_EXECUTION_MODE=live for the duration of the test."""
    monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
    yield
    # Cleanup handled by monkeypatch fixture.


@pytest.fixture
def force_paper(monkeypatch):
    """Force SPA_EXECUTION_MODE to be unset / non-live."""
    monkeypatch.delenv("SPA_EXECUTION_MODE", raising=False)
    yield


# ─── _parse_protocol_key ──────────────────────────────────────────────────────

class TestParseProtocolKey:
    def test_aave_v3_usdc_ethereum(self):
        assert _parse_protocol_key("aave-v3-usdc-ethereum") == {
            "family": "aave_v3", "asset": "USDC", "chain": "ethereum",
        }

    def test_aave_v3_dai_base(self):
        assert _parse_protocol_key("aave-v3-dai-base") == {
            "family": "aave_v3", "asset": "DAI", "chain": "base",
        }

    def test_aave_v3_usdt_arbitrum(self):
        assert _parse_protocol_key("aave-v3-usdt-arbitrum") == {
            "family": "aave_v3", "asset": "USDT", "chain": "arbitrum",
        }

    def test_compound_v3_usdc_ethereum(self):
        assert _parse_protocol_key("compound-v3-usdc-ethereum") == {
            "family": "compound_v3", "asset": "USDC", "chain": "ethereum",
        }

    def test_compound_v3_usdc_arbitrum(self):
        assert _parse_protocol_key("compound-v3-usdc-arbitrum") == {
            "family": "compound_v3", "asset": "USDC", "chain": "arbitrum",
        }

    def test_uppercase_input(self):
        # Caller might send protocol_key with mixed case; lowercased internally.
        out = _parse_protocol_key("AAVE-V3-USDC-ETHEREUM")
        assert out is not None
        assert out["family"] == "aave_v3"
        assert out["asset"] == "USDC"
        assert out["chain"] == "ethereum"

    @pytest.mark.parametrize("bad", [
        "",                              # empty
        "not-a-protocol",                # unknown prefix
        "aave-v3",                       # no tail
        "aave-v3-",                      # empty tail
        "aave-v3-usdc",                  # missing chain
        "compound-v3",                   # no tail
        "aave-v3usdc-ethereum",          # malformed (missing dash)
    ])
    def test_malformed_returns_none(self, bad):
        assert _parse_protocol_key(bad) is None

    def test_pendle_pt_key_parses(self):
        # SPA-V328: 'pendle-pt' is now a supported prefix → 'pendle_pt' family.
        assert _parse_protocol_key("pendle-pt-usdc-ethereum") == {
            "family": "pendle_pt", "asset": "USDC", "chain": "ethereum",
        }

    def test_morpho_blue_key_parses(self):
        # SPA-V348: 'morpho-blue' is a supported prefix (Morpho Blue) → 'morpho'
        # family via longest-prefix match (consistent with yield_classifier_agent
        # and audit_reader_agent which already map morpho-blue → morpho).
        assert _parse_protocol_key("morpho-blue-usdc-base") == {
            "family": "morpho", "asset": "USDC", "chain": "base",
        }

    def test_morpho_plain_key_still_parses(self):
        # Regression: adding the longer 'morpho-blue' prefix must not break the
        # plain 'morpho-' prefix.
        assert _parse_protocol_key("morpho-usdc-ethereum") == {
            "family": "morpho", "asset": "USDC", "chain": "ethereum",
        }

    def test_none_input(self):
        assert _parse_protocol_key(None) is None  # type: ignore[arg-type]

    def test_non_string_input(self):
        assert _parse_protocol_key(123) is None  # type: ignore[arg-type]


# ─── Execution mode gate ──────────────────────────────────────────────────────

class TestExecutionModeGate:
    def test_default_is_not_live(self, force_paper):
        assert _execution_mode_live() is False

    def test_live_lowercase(self, monkeypatch):
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
        assert _execution_mode_live() is True

    def test_live_uppercase(self, monkeypatch):
        monkeypatch.setenv("SPA_EXECUTION_MODE", "LIVE")
        assert _execution_mode_live() is True

    def test_paper_value_is_not_live(self, monkeypatch):
        monkeypatch.setenv("SPA_EXECUTION_MODE", "paper")
        assert _execution_mode_live() is False

    def test_arbitrary_value_is_not_live(self, monkeypatch):
        monkeypatch.setenv("SPA_EXECUTION_MODE", "production")
        assert _execution_mode_live() is False


# ─── Bridge SKIPPED branches ──────────────────────────────────────────────────

class TestBridgeSkipped:
    def test_skipped_when_execution_mode_not_live(self, tmp_path, force_paper):
        bridge = _make_bridge(tmp_path)
        result = bridge.execute_supply("aave-v3-usdc-ethereum", 1000.0)
        assert result["status"] == "SKIPPED"
        assert result["reason"] == "execution_mode_paper"
        # No log file written when execution mode hard-gates us out: the
        # skipped row is purely an in-process signal.
        assert not (tmp_path / "live_execution_log.json").exists()

    def test_skipped_unparseable_protocol_key(self, tmp_path, force_live):
        bridge = _make_bridge(tmp_path)
        result = bridge.execute_supply("not-a-protocol", 1000.0)
        assert result["status"] == "SKIPPED"
        assert result["reason"] == "unparseable_protocol_key"
        # SKIPPED-due-to-parse-failure SHOULD log so operators see bad keys.
        assert (tmp_path / "live_execution_log.json").exists()

    def test_skipped_unsupported_protocol(self, tmp_path, force_live, monkeypatch):
        # pendle-pt-* parses (SPA-V328), but STETH/arbitrum isn't a supported
        # PT market, so _get_adapter rejects it → unsupported_protocol SKIP.
        bridge = _make_bridge(tmp_path)
        result = bridge.execute_withdraw("pendle-pt-steth-arbitrum", 100.0)
        assert result["status"] == "SKIPPED"
        assert result["reason"] in ("unparseable_protocol_key", "unsupported_protocol")


# ─── Live SUCCESS path ────────────────────────────────────────────────────────

class TestLiveSuccess:
    def test_aave_supply_success_dispatches_and_logs(
        self, tmp_path, force_live, monkeypatch,
    ):
        fake = _FakeAdapter(chain="ethereum")
        cls = lambda chain, dry_run: fake  # noqa: E731
        _patch_adapters(monkeypatch, aave_cls=cls)

        bridge = _make_bridge(tmp_path)
        result = bridge.execute_supply("aave-v3-usdc-ethereum", 2500.0)

        assert result["status"] == "SUCCESS"
        assert result["supply_tx"] == "0xfeed"
        assert result["bridge_action"] == "supply"
        assert result["protocol_key"] == "aave-v3-usdc-ethereum"
        assert result["family"] == "aave_v3"
        assert fake.supply_calls == [("USDC", 2500.0)]

        log_path = tmp_path / "live_execution_log.json"
        assert log_path.exists()
        entries = json.loads(log_path.read_text())
        assert isinstance(entries, list)
        assert len(entries) == 1
        assert entries[0]["status"] == "SUCCESS"
        assert entries[0]["bridge_action"] == "supply"

    def test_compound_withdraw_success(
        self, tmp_path, force_live, monkeypatch,
    ):
        fake = _FakeAdapter(chain="arbitrum")
        cls = lambda chain, dry_run: fake  # noqa: E731
        _patch_adapters(monkeypatch, comp_cls=cls)

        bridge = _make_bridge(tmp_path)
        result = bridge.execute_withdraw("compound-v3-usdc-arbitrum", 500.0)

        assert result["status"] == "SUCCESS"
        assert result["withdraw_tx"] == "0xdead"
        assert result["bridge_action"] == "withdraw"
        assert fake.withdraw_calls == [("USDC", 500.0)]


# ─── FAILED / BLOCKED / ERROR are returned but do not raise ───────────────────

class TestLiveFailureSemantics:
    def test_adapter_returns_failed_logged_no_raise(
        self, tmp_path, force_live, monkeypatch,
    ):
        fake = _FakeAdapter(
            chain="ethereum",
            supply_response={"status": "FAILED", "reason": "rpc flake",
                             "phase": "approve"},
        )
        _patch_adapters(monkeypatch, aave_cls=lambda chain, dry_run: fake)

        bridge = _make_bridge(tmp_path)
        # MUST NOT RAISE
        result = bridge.execute_supply("aave-v3-usdc-ethereum", 1000.0)
        assert result["status"] == "FAILED"
        assert result["reason"] == "rpc flake"

        entries = json.loads(
            (tmp_path / "live_execution_log.json").read_text()
        )
        assert len(entries) == 1
        assert entries[0]["status"] == "FAILED"

    def test_adapter_returns_blocked(
        self, tmp_path, force_live, monkeypatch,
    ):
        fake = _FakeAdapter(
            chain="ethereum",
            supply_response={"status": "BLOCKED",
                             "reason": "SPA_EXECUTION_MODE!=live"},
        )
        _patch_adapters(monkeypatch, aave_cls=lambda chain, dry_run: fake)

        bridge = _make_bridge(tmp_path)
        result = bridge.execute_supply("aave-v3-usdc-ethereum", 1000.0)
        assert result["status"] == "BLOCKED"

    def test_adapter_raises_swallowed(
        self, tmp_path, force_live, monkeypatch,
    ):
        fake = _FakeAdapter(
            chain="ethereum",
            supply_raises=RuntimeError("simulated boom"),
        )
        _patch_adapters(monkeypatch, aave_cls=lambda chain, dry_run: fake)

        bridge = _make_bridge(tmp_path)
        # MUST NOT RAISE even though the fake raises internally.
        result = bridge.execute_supply("aave-v3-usdc-ethereum", 999.0)
        assert result["status"] == "ERROR"
        assert "simulated boom" in result.get("reason", "")

        entries = json.loads(
            (tmp_path / "live_execution_log.json").read_text()
        )
        assert any("simulated boom" in (e.get("reason") or "") for e in entries)


# ─── PaperTrader.live_execution=False is the regression gate ──────────────────

class TestPaperTraderDefaultBehaviour:
    """Regression: with the default `live_execution=False`, the engine MUST
    NOT touch the bridge — this is the contract that keeps 100+ existing
    call-sites unchanged. We assert by monkey-patching the bridge class to
    raise on instantiation; if the engine constructs it, the test fails."""

    def _make_default_trader(self, tmp_path):
        import tempfile as _t
        from database.init_db import init_database
        from paper_trading.engine import PaperTrader

        db_path = Path(_t.mktemp(suffix=".db"))
        init_database(db_path=db_path)
        return PaperTrader(db_path=db_path), db_path

    def _make_live_trader(self, tmp_path):
        import tempfile as _t
        from database.init_db import init_database
        from paper_trading.engine import PaperTrader

        db_path = Path(_t.mktemp(suffix=".db"))
        init_database(db_path=db_path)
        # AUD-04: the execution domain injects the bridge factory; paper code
        # never imports execution. Read the class at call time so monkeypatched
        # replacements (e.g. _Capturing) are honoured.
        def _factory():
            from spa_core.execution.engine_bridge import LiveExecutionBridge as _B
            return _B()
        return (
            PaperTrader(
                db_path=db_path,
                live_execution=True,
                live_bridge_factory=_factory,
            ),
            db_path,
        )

    def test_default_live_execution_flag_is_false(self):
        from paper_trading.engine import PaperTrader
        # Inspect signature default — must not have changed.
        import inspect
        sig = inspect.signature(PaperTrader.__init__)
        assert sig.parameters["live_execution"].default is False

    def test_default_trader_does_not_init_bridge_on_open(
        self, tmp_path, force_live, monkeypatch,
    ):
        """Even with SPA_EXECUTION_MODE=live, default trader must NOT touch
        the bridge — only the per-strategy flag enables it."""
        # Patch the bridge class on BOTH import paths the engine might use
        # (the engine.py sys.path manipulation can resolve either
        # spa_core.execution.engine_bridge or execution.engine_bridge).
        from spa_core.execution import engine_bridge as eb_qual
        try:
            from execution import engine_bridge as eb_short  # type: ignore
        except ImportError:
            eb_short = None

        class _Boom:
            def __init__(self, *a, **kw):
                raise AssertionError(
                    "LiveExecutionBridge instantiated despite live_execution=False"
                )

        monkeypatch.setattr(eb_qual, "LiveExecutionBridge", _Boom)
        if eb_short is not None:
            monkeypatch.setattr(eb_short, "LiveExecutionBridge", _Boom)

        trader, _db = self._make_default_trader(tmp_path)
        assert trader.live_execution is False
        # We don't actually call open_position here — the meaningful assertion
        # is that _get_live_bridge() short-circuits.
        assert trader._get_live_bridge() is None

    def test_live_flag_trader_invokes_bridge(
        self, tmp_path, force_live, monkeypatch,
    ):
        """Counterpart: with live_execution=True the engine WILL call the
        bridge. We capture the call without going to a real adapter."""
        from spa_core.execution import engine_bridge as eb_qual
        try:
            from execution import engine_bridge as eb_short  # type: ignore
        except ImportError:
            eb_short = None

        calls: list = []

        class _Capturing(LiveExecutionBridge):
            def execute_supply(self, pk, amt):
                calls.append(("supply", pk, amt))
                return {"status": "SUCCESS", "supply_tx": "0xcap"}

            def execute_withdraw(self, pk, amt):
                calls.append(("withdraw", pk, amt))
                return {"status": "SUCCESS", "withdraw_tx": "0xcap"}

        monkeypatch.setattr(eb_qual, "LiveExecutionBridge", _Capturing)
        if eb_short is not None:
            monkeypatch.setattr(eb_short, "LiveExecutionBridge", _Capturing)

        trader, _db = self._make_live_trader(tmp_path)
        assert trader.live_execution is True
        bridge = trader._get_live_bridge()
        # The engine resolves the bridge class via whichever import path
        # succeeds first in _get_live_bridge() — both routes now point at
        # _Capturing, so the instance must be a _Capturing.
        assert isinstance(bridge, _Capturing)


# ─── Audit log rotation ───────────────────────────────────────────────────────

class TestAuditLogRotation:
    def test_log_capped_at_max_entries(self, tmp_path, force_live, monkeypatch):
        fake = _FakeAdapter(chain="ethereum")
        _patch_adapters(monkeypatch, aave_cls=lambda chain, dry_run: fake)

        bridge = _make_bridge(tmp_path)

        # Pre-seed the log with LOG_MAX_ENTRIES entries.
        log_path = tmp_path / "live_execution_log.json"
        log_path.parent.mkdir(exist_ok=True)
        seeded = [{"seed": i} for i in range(LOG_MAX_ENTRIES)]
        log_path.write_text(json.dumps(seeded))

        # One more append should rotate exactly one entry out.
        result = bridge.execute_supply("aave-v3-usdc-ethereum", 1.0)
        assert result["status"] == "SUCCESS"

        entries = json.loads(log_path.read_text())
        assert len(entries) == LOG_MAX_ENTRIES
        # The first seeded entry (seed=0) should have been dropped.
        assert entries[0] != {"seed": 0}
        # And the newest entry sits at the tail.
        assert entries[-1]["status"] == "SUCCESS"

    def test_log_handles_missing_file_gracefully(
        self, tmp_path, force_live, monkeypatch,
    ):
        fake = _FakeAdapter(chain="ethereum")
        _patch_adapters(monkeypatch, aave_cls=lambda chain, dry_run: fake)

        bridge = _make_bridge(tmp_path)
        # No log file yet.
        assert not (tmp_path / "live_execution_log.json").exists()
        bridge.execute_supply("aave-v3-usdc-ethereum", 10.0)
        # Now created.
        assert (tmp_path / "live_execution_log.json").exists()
        entries = json.loads((tmp_path / "live_execution_log.json").read_text())
        assert len(entries) == 1

    def test_log_handles_corrupted_file_gracefully(
        self, tmp_path, force_live, monkeypatch,
    ):
        fake = _FakeAdapter(chain="ethereum")
        _patch_adapters(monkeypatch, aave_cls=lambda chain, dry_run: fake)

        log_path = tmp_path / "live_execution_log.json"
        log_path.write_text("not valid json {{{")

        bridge = _make_bridge(tmp_path)
        # Must not raise.
        result = bridge.execute_supply("aave-v3-usdc-ethereum", 1.0)
        assert result["status"] == "SUCCESS"
        # Log was reset and now has one entry.
        entries = json.loads(log_path.read_text())
        assert len(entries) == 1


# ─── Paper INSERT still happens when live leg fails ───────────────────────────

class TestPaperBookSurvivesLiveFailure:
    """Sanity check that the engine's paper INSERT is unconditional even
    when the live adapter returns FAILED — paper bookkeeping is the source
    of truth (engine contract from Phase 4 design notes)."""

    def test_paper_insert_when_live_fails(
        self, tmp_path, force_live, monkeypatch,
    ):
        import tempfile as _t
        from database.init_db import init_database, get_connection
        from paper_trading.engine import PaperTrader

        # Bridge that always returns FAILED for supply.
        from spa_core.execution import engine_bridge as eb_mod

        class _AlwaysFails(LiveExecutionBridge):
            def execute_supply(self, pk, amt):
                return {"status": "FAILED", "reason": "synthetic",
                        "phase": "supply"}

            def execute_withdraw(self, pk, amt):
                return {"status": "FAILED", "reason": "synthetic",
                        "phase": "withdraw"}

        monkeypatch.setattr(eb_mod, "LiveExecutionBridge", _AlwaysFails)

        db_path = Path(_t.mktemp(suffix=".db"))
        init_database(db_path=db_path)
        # AUD-04: inject the bridge factory (execution domain's responsibility);
        # reads the monkeypatched class at call time.
        trader = PaperTrader(
            db_path=db_path,
            live_execution=True,
            live_bridge_factory=lambda: eb_mod.LiveExecutionBridge(),
        )

        # Open a position on a real whitelisted protocol — Aave V3 USDC eth.
        result = trader.open_position(
            "aave-v3-usdc-ethereum",
            amount_usd=3000.0,
            current_apy=4.65,
            tvl_usd=138_000_000.0,
        )
        assert result.approved is True

        # paper_trades must contain the row regardless of live leg outcome.
        with get_connection(db_path) as conn:
            rows = conn.execute(
                "SELECT trade_id, protocol_key, amount_usd, action "
                "FROM paper_trades WHERE protocol_key = ?",
                ("aave-v3-usdc-ethereum",),
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["amount_usd"] == 3000.0
        assert rows[0]["action"] == "OPEN"
