"""Track-integrity WRITE-INTERLOCK tests (Architect P3-2).

The ``PAPER_REAL_START_DATE`` constant is honest *labelling* — it stops an
ad-hoc run from inflating the real-track length, but it does NOT physically
stop a stray ``python3 -m spa_core.paper_trading.cycle_runner`` in a dev shell
from OVERWRITING the canonical live track (this corrupted the track on
2026-06-25). These tests pin the real, fail-CLOSED write-interlock:

  * default (no ``--live`` / ``SPA_ALLOW_LIVE_WRITE``) → canonical write DENIED,
    redirected to a sandbox; the canonical equity curve is UNTOUCHED.
  * explicit opt-in (flag OR env) → canonical write permitted.
  * an explicit non-canonical ``data_dir`` is always honoured verbatim.

Network-free: orchestrator / allocator / scorer / persister are in-process
fakes. The "canonical" dir is monkeypatched to a temp dir so the suite NEVER
touches the real ``data/``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from spa_core.paper_trading import _cycle_io
from spa_core.paper_trading import cycle_runner as cr
from spa_core.paper_trading._cycle_io import (
    DATA_DIR_ENV,
    EQUITY_FILENAME,
    LIVE_WRITE_ENV,
    resolve_data_dir,
)


# ─── Fixtures: make a TEMP dir act as the canonical dir ───────────────────────


@pytest.fixture
def fake_canonical(tmp_path, monkeypatch):
    """Point ``_DEFAULT_DATA_DIR`` at a temp dir so 'canonical' == ``canon``.

    Patches every module that captured the constant by value at import time so
    the interlock's identity check (``requested == _DEFAULT_DATA_DIR``) and all
    fallbacks resolve to this temp dir, never the real ``data/``.
    """
    canon = tmp_path / "data"
    canon.mkdir()
    monkeypatch.setattr(_cycle_io, "_DEFAULT_DATA_DIR", canon, raising=True)
    monkeypatch.setattr(cr, "_DEFAULT_DATA_DIR", canon, raising=True)
    # Ensure no ambient opt-in / sandbox override leaks in from the environment.
    monkeypatch.delenv(LIVE_WRITE_ENV, raising=False)
    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    return canon


# ─── Fakes (network-free) ─────────────────────────────────────────────────────


# A policy-compliant target: T1 ≤40% / T2 ≤20% each, ≥5% cash buffer.
_TARGET = {
    "aave_v3": 35_000.0,           # T1
    "compound_v3": 20_000.0,       # T2 (treated as T2 here)
    "morpho_steakhouse": 18_000.0, # T2
    "yearn_v3": 17_000.0,          # T2
}


def _orch_fn(data_dir):
    adapters = [
        {
            "protocol": p,
            "apy_pct": 4.0,
            "tvl_usd": 1e7,
            "tier": "T1" if p == "aave_v3" else "T2",
            "status": "ok",
        }
        for p in _TARGET
    ]
    return SimpleNamespace(adapters=adapters, status="ok", data_freshness="live")


class _FakeAllocator:
    def allocate(self):
        return SimpleNamespace(
            target_usd=dict(_TARGET),
            target_weights={p: v / 100_000 for p, v in _TARGET.items()},
            expected_apy_pct=3.0,
            model_used="risk_adjusted",
            strategy_loop_active=False,
        )


def _run(*, data_dir=None, allow_live_write=False):
    return cr.run_cycle(
        data_dir=data_dir,
        now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc),
        orchestrator_fn=_orch_fn,
        allocator=_FakeAllocator(),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,
        write=True,
        allow_live_write=allow_live_write,
    )


# ─── resolve_data_dir: the pure interlock decision ────────────────────────────


def test_default_deny_redirects_to_sandbox(fake_canonical, tmp_path, monkeypatch):
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "sbx"))
    eff, redirected = resolve_data_dir(None, allow_live_write=False)
    assert redirected is True
    assert eff.resolve() == (tmp_path / "sbx").resolve()
    assert eff.resolve() != fake_canonical.resolve()


def test_flag_opt_in_allows_canonical(fake_canonical):
    eff, redirected = resolve_data_dir(None, allow_live_write=True)
    assert redirected is False
    assert eff.resolve() == fake_canonical.resolve()


def test_env_opt_in_allows_canonical(fake_canonical, monkeypatch):
    monkeypatch.setenv(LIVE_WRITE_ENV, "1")
    eff, redirected = resolve_data_dir(None, allow_live_write=False)
    assert redirected is False
    assert eff.resolve() == fake_canonical.resolve()


def test_env_falsey_is_still_denied(fake_canonical, monkeypatch):
    monkeypatch.setenv(LIVE_WRITE_ENV, "0")
    eff, redirected = resolve_data_dir(None, allow_live_write=False)
    assert redirected is True
    assert eff.resolve() != fake_canonical.resolve()


def test_explicit_noncanonical_dir_honoured(fake_canonical, tmp_path):
    target = tmp_path / "my_sandbox"
    eff, redirected = resolve_data_dir(target, allow_live_write=False)
    assert redirected is False
    assert eff == target


# ─── End-to-end: a no-flag run must NOT mutate the canonical track ────────────


def test_default_run_does_not_write_canonical_equity(fake_canonical, tmp_path, monkeypatch):
    """A plain (no opt-in) cycle MUST leave the canonical equity curve untouched."""
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "sbx"))
    canon_equity = fake_canonical / EQUITY_FILENAME
    assert not canon_equity.exists()

    # The interlock contract is about the WRITE TARGET, not the cycle verdict —
    # a default run must not touch canonical regardless of policy outcome.
    _run(data_dir=None, allow_live_write=False)

    # Canonical curve never created; writes landed in the sandbox.
    assert not canon_equity.exists(), "default-deny run mutated the canonical track!"
    assert (tmp_path / "sbx" / EQUITY_FILENAME).exists()


def test_flagged_run_writes_canonical_equity(fake_canonical):
    """An opt-in cycle DOES advance the canonical equity curve."""
    canon_equity = fake_canonical / EQUITY_FILENAME
    assert not canon_equity.exists()

    _run(data_dir=None, allow_live_write=True)
    assert canon_equity.exists(), "opt-in run failed to write the canonical track!"
    doc = json.loads(canon_equity.read_text(encoding="utf-8"))
    assert doc  # non-empty equity document
