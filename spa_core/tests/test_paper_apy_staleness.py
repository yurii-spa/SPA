"""spa_core/tests/test_paper_apy_staleness.py — ADR-580 C2/C3 failure-injection
test (RM-TRUTH-01 W5, task 3b): a stale snapshot reports stale/unknown rather than
silently serving yesterday's number under today's timestamp.

Also pins /api/health-public and /api/ssot/facts to the SAME canonical value
(invariant: one producer, two readers) and that both endpoints honor
``SPA_DATA_DIR`` (``get_ssot_facts`` used to call ``key_facts()`` with no
``data_dir``, silently reading the repo's real ``data/`` regardless of the test's
redirected dir — fixed alongside this task; a positive control for THAT fix lives
here too, since a passing staleness test over the WRONG directory would be a false
green).

# CHANGED (integration review F4, 2026-10-05 — journal 2026-W40): this file's
# assertions read `snap["paper_apy_pct"]` / `snap["max_drawdown_pct"]`, and the
# pin test compared `health["paper_apy_pct"] == facts["paper_apy_pct"]`. Those
# exact field names are READ by live landing pages (DashboardSPAApp.jsx reads
# facts.paper_apy_pct from /api/ssot/facts; index.astro/track-record.astro read
# d.max_drawdown_pct from /api/health-public) — so merging paper_apy_snapshot()'s
# dict under those names silently changed two public numbers without owner
# authorisation (ADR-285 subject #2). paper_apy_snapshot() now returns the value
# under NEW names only: `paper_apy_canonical` (a typed object) and
# `max_drawdown_track_pct` (+ sidecars). This file is updated to match the fixed
# contract — it tightens the pin (asserts the OLD public names are UNCHANGED by
# this producer) rather than relaxing anything.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.governance.ssot import PAPER_APY_STALE_AFTER_H, paper_apy_snapshot

# FROZEN-DATE-OK: injected-clock — every literal date in this file is handed to
# paper_apy_snapshot(..., now=...) or to the local `_seed` helper (a pure fixture
# builder, not a clock read). The one path that used to read the REAL wall clock —
# the HTTP round-trip in test_health_public_and_ssot_facts_serve_the_same_canonical_rate,
# which calls paper_apy_snapshot()/key_facts() with no `now=` at all — is patched to
# the same NOW anchor via `ssot.datetime` (see _FixedNow below), so that test is pinned
# too, not just the direct-call ones.


def _seed(ddir: Path, *, last_bar_date: str, n: int = 10) -> None:
    from datetime import date as _date

    d0 = _date.fromisoformat(last_bar_date) - timedelta(days=n - 1)
    bars = [
        {"date": (d0 + timedelta(days=i)).isoformat(), "equity": 100000.0 + i * 10,
         "evidenced": True, "drawdown_pct": -0.01 * i}
        for i in range(n)
    ]
    (ddir / "equity_curve_daily.json").write_text(json.dumps({"daily": bars}), encoding="utf-8")
    (ddir / "golive_status.json").write_text(
        json.dumps({"real_track_days": n, "evidenced_anchor": bars[0]["date"]}), encoding="utf-8"
    )


# ─── positive control: fresh snapshot serves a number ──────────────────────────


def test_fresh_snapshot_serves_the_canonical_rate(tmp_path):
    _seed(tmp_path, last_bar_date="2026-10-04")
    now = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)  # 1 day after the last bar
    snap = paper_apy_snapshot(tmp_path, now=now)
    canon = snap["paper_apy_canonical"]
    assert canon["value"] is not None
    assert canon["stale"] is False
    assert canon["reportable"] is True
    assert snap["max_drawdown_track_pct"] is not None


# ─── (b) negative control: a stale snapshot nulls the value, names itself stale ─


def test_stale_snapshot_reports_stale_not_a_silently_served_old_number(tmp_path):
    _seed(tmp_path, last_bar_date="2026-10-01")
    # PAPER_APY_STALE_AFTER_H + a margin — the cycle missed more than its 48h window.
    now = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(hours=PAPER_APY_STALE_AFTER_H + 24)
    snap = paper_apy_snapshot(tmp_path, now=now)
    canon = snap["paper_apy_canonical"]
    assert canon["value"] is None
    assert canon["stale"] is True
    assert canon["reportable"] is False
    # Drawdown is read from the SAME snapshot and is nulled too — not silently served.
    assert snap["max_drawdown_track_pct"] is None
    # as_of is STILL named — a reader can say HOW stale, not just "unknown".
    assert canon["as_of"] is not None


def test_boundary_just_inside_the_window_is_not_stale(tmp_path):
    """The threshold is an input, not a guess — one hour inside the window must
    still serve a number (else the 'window' would be fiction)."""
    _seed(tmp_path, last_bar_date="2026-10-01")
    now = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(hours=PAPER_APY_STALE_AFTER_H - 1)
    snap = paper_apy_snapshot(tmp_path, now=now)
    canon = snap["paper_apy_canonical"]
    assert canon["stale"] is False
    assert canon["value"] is not None


def test_missing_as_of_is_not_measured_not_stale_false(tmp_path):
    """No equity_curve_daily.json at all (no bars, no golive as_of) → the
    staleness question is genuinely unanswerable — ``stale`` stays ``None``
    (invariant #17: 'not measured' is a THIRD outcome, distinct from both
    'measured and fresh' and 'measured and stale')."""
    snap = paper_apy_snapshot(tmp_path, now=datetime(2026, 10, 5, tzinfo=timezone.utc))
    canon = snap["paper_apy_canonical"]
    assert canon["value"] is None
    assert canon["stale"] is None


# ─── pin: /api/health-public and /api/ssot/facts serve the SAME value, under the
#     NEW name only — and neither endpoint's OLD public field changes value ──────


class _FixedNow(datetime):
    """``datetime`` subclass whose ``.now()`` always returns the module's seeded
    anchor. Both ``/api/health-public`` and ``/api/ssot/facts`` call
    ``paper_apy_snapshot``/``key_facts`` with no ``now=`` at all (the HTTP layer has
    no such parameter), so they read ``spa_core.governance.ssot``'s own
    ``datetime.now(timezone.utc)`` at request time — a REAL wall-clock read that
    would otherwise start failing the day the seeded bar ("2026-10-04") falls more
    than ``PAPER_APY_STALE_AFTER_H`` behind the actual calendar. Patching
    ``ssot.datetime`` ties that read to the same anchor as the fixture, exactly
    like the direct ``now=`` calls above."""

    @classmethod
    def now(cls, tz=None):  # noqa: D102 - stdlib signature
        anchor = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)
        return anchor if tz is not None else anchor.replace(tzinfo=None)


def test_health_public_and_ssot_facts_serve_the_same_canonical_rate(tmp_path, monkeypatch):
    """Both endpoints must read ``SPA_DATA_DIR`` (not the repo's real ``data/``)
    and must agree on ``paper_apy_canonical`` — one producer (``paper_apy_snapshot``),
    two readers. A stale-directory false green is ruled out by seeding a document
    this test controls and asserting on ITS value, not "some number".

    F4: neither endpoint's response carries the canonical value under the bare
    name ``paper_apy_pct`` — that name is a LIVE PUBLIC FIELD two landing pages
    read from these exact endpoints, and this producer must never shadow it.
    """
    import importlib

    fastapi_testclient = __import__("pytest").importorskip("fastapi.testclient")
    _seed(tmp_path, last_bar_date="2026-10-04")
    (tmp_path / "paper_trading_status.json").write_text(json.dumps({
        "apy_today_pct": 4.22, "current_equity": 101000.0,
    }), encoding="utf-8")

    monkeypatch.setenv("SPA_DATA_DIR", str(tmp_path))
    import spa_core.governance.ssot as ssot_mod
    monkeypatch.setattr(ssot_mod, "datetime", _FixedNow)
    import spa_core.api.server as server
    importlib.reload(server)
    with fastapi_testclient.TestClient(server.app) as client:
        health = client.get("/api/health-public").json()
        facts = client.get("/api/ssot/facts").json()

    assert health["paper_apy_canonical"]["value"] is not None
    assert health["paper_apy_canonical"]["value"] == facts["paper_apy_canonical"]["value"]
    assert (health["paper_apy_canonical"]["metric_type"]
            == facts["paper_apy_canonical"]["metric_type"] == "REALIZED_PAPER")
    # The honestly-named day rate survives under its OLD field name too (landing
    # consumers read it by that exact name) — but now carries its real type.
    assert health["ytd_apy_pct"] == 4.22
    assert health["apy_today_pct_metric_type"] == facts["apy_today_pct_metric_type"] == "OBSERVED"
    # F4 positive control: the bare public names a landing page reads are NEVER
    # populated by this producer. /api/ssot/facts has no "paper_apy_pct" key at
    # all (DashboardSPAApp.jsx's `facts.paper_apy_pct ?? facts.apy_today_pct`
    # must keep falling back to apy_today_pct, exactly as before this feature).
    assert "paper_apy_pct" not in facts
    # /api/health-public's max_drawdown_pct stays on tear_sheet.json (None here,
    # no tear_sheet.json seeded) — NOT the live snapshot's drawdown, which is
    # available under max_drawdown_track_pct instead.
    assert health["max_drawdown_pct"] is None
    assert health["max_drawdown_track_pct"] is not None
