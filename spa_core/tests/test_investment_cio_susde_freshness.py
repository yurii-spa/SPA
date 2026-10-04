"""REWORK M6 (post-implementation review of ADR-560 WP-S07/WP-S08's market_neutral_basis repair).

Three genuine defects in the first pass, fixed here:

(a) susde_dn was forced STALE UNCONDITIONALLY — a repaired ``rates_desk/pendle_pt_history.json``
    would never clear it. Fixed: judged by the frozen date's AGE against the strand's own cadence
    (``sleeves.CADENCE_RESEARCH_STRAND_H``), via ``sleeves._susde_dn_effective_state``.
(b) The general input manifest (``build_sleeves(...)["inputs"]``) still showed
    ``susde_dn_realized_series`` as MEASURED (judged only by the wrapper file's own row-touch
    cadence) even when the sleeve itself correctly called the strand STALE. Fixed: the SAME
    verdict is applied to ``susde_input.state``/``.state_reason`` before the manifest is built.
(c) The new ``rates_desk_pendle_pt_history`` input had no cadence, so it was always MEASURED, and
    being in ``build_sleeves(...)["inputs"]`` dragged ``policy.recommend``'s ``evidence_cutoff``
    (``min(i["as_of"] for i in inputs)``) back to the FROZEN date (2026-07-05) instead of today.
    Fixed: the pendle file is read only to judge (a)/(b); it is never added to ``inputs``.

Every test here is red against the pre-fix code (verified by hand while writing this module: (a)
was `contract.STALE` unconditionally with `age_hours=None`; (b) read `.state` straight off
`susde_input` with no override; (c) had `pendle_history_input` in the `inputs` list).
"""
# FROZEN-DATE-OK: injected-clock — NOW/PENDLE dates are passed explicitly into build_sleeves/
# policy.recommend; nothing here reads the wall clock.
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.investment_cio import contract, policy, sleeves
from spa_core.tests.test_investment_cio_sleeves import NOW, _full_scene

PYTHON = sys.executable


def _write_susde(data_dir: Path, *, last_date: str) -> None:
    (data_dir / "aggressive_lab" / "susde_dn").mkdir(parents=True, exist_ok=True)
    rows = [{"as_of": last_date, "date": last_date, "equity_usd": 100500.0, "mtm_today_pct": 0.02,
            "net_apy_pct": 0.3}]
    (data_dir / "aggressive_lab" / "susde_dn" / "realized_series.jsonl").write_text(json.dumps(rows[0]))


def _write_pendle_history(data_dir: Path, *, generated_at: str) -> None:
    (data_dir / "rates_desk").mkdir(parents=True, exist_ok=True)
    (data_dir / "rates_desk" / "pendle_pt_history.json").write_text(json.dumps(
        {"generated_at": generated_at, "markets": {}, "window": {"end": generated_at[:10]}}))


# ── (a) age-based, never a hardcoded forever-STALE verdict ─────────────────────────────────────

def test_susde_dn_is_measured_when_pendle_history_is_fresh(tmp_path):
    """The whole point of judging by AGE: a repaired (fresh) pendle file clears the STALE verdict.
    Red against the pre-fix code, which forced contract.STALE unconditionally regardless of age."""
    data_dir = tmp_path / "data"
    _write_susde(data_dir, last_date=NOW.strftime("%Y-%m-%d"))
    _write_pendle_history(data_dir, generated_at=(NOW - timedelta(hours=2)).isoformat())
    out = sleeves.build_sleeves(data_dir, NOW)
    manifest = {i["name"]: i for i in out["inputs"]}
    assert manifest["susde_dn_realized_series"]["state"] == contract.MEASURED
    comp = {c["protocol"]: c for c in out["sleeves"]["market_neutral_basis"]["composition"]}
    assert comp["susde_dn (delta-neutral)"]["usd"]["state"] == contract.MEASURED


def test_susde_dn_is_stale_when_pendle_history_is_older_than_the_strand_cadence(tmp_path):
    data_dir = tmp_path / "data"
    _write_susde(data_dir, last_date=NOW.strftime("%Y-%m-%d"))
    old = NOW - timedelta(hours=sleeves.CADENCE_RESEARCH_STRAND_H + 1)
    _write_pendle_history(data_dir, generated_at=old.isoformat())
    out = sleeves.build_sleeves(data_dir, NOW)
    manifest = {i["name"]: i for i in out["inputs"]}
    assert manifest["susde_dn_realized_series"]["state"] == contract.STALE


def test_susde_dn_is_measured_at_exactly_the_cadence_boundary_minus_one_second(tmp_path):
    """Positive control at the boundary: age_h <= cadence must be MEASURED, not STALE."""
    data_dir = tmp_path / "data"
    _write_susde(data_dir, last_date=NOW.strftime("%Y-%m-%d"))
    boundary = NOW - timedelta(hours=sleeves.CADENCE_RESEARCH_STRAND_H) + timedelta(seconds=1)
    _write_pendle_history(data_dir, generated_at=boundary.isoformat())
    out = sleeves.build_sleeves(data_dir, NOW)
    manifest = {i["name"]: i for i in out["inputs"]}
    assert manifest["susde_dn_realized_series"]["state"] == contract.MEASURED


def test_susde_dn_stale_reason_names_the_frozen_date_and_its_age(tmp_path):
    data_dir = tmp_path / "data"
    _write_susde(data_dir, last_date=NOW.strftime("%Y-%m-%d"))
    _write_pendle_history(data_dir, generated_at="2026-07-05T22:43:58+00:00")
    out = sleeves.build_sleeves(data_dir, NOW)
    reason = out["sleeves"]["market_neutral_basis"]["data_freshness"]["reason"]
    assert "2026-07-05" in reason
    assert "h old >" in reason and f"{sleeves.CADENCE_RESEARCH_STRAND_H:.0f}h limit" in reason


def test_susde_dn_falls_back_to_its_own_cadence_when_pendle_history_is_unreadable(tmp_path):
    """No pendle file at all: judged by the strand's OWN file cadence, never a hardcoded verdict
    (and never silently MEASURED just because the pendle check couldn't run)."""
    data_dir = tmp_path / "data"
    _write_susde(data_dir, last_date=(NOW - timedelta(days=10)).strftime("%Y-%m-%d"))  # own file stale
    out = sleeves.build_sleeves(data_dir, NOW)
    manifest = {i["name"]: i for i in out["inputs"]}
    assert manifest["susde_dn_realized_series"]["state"] == contract.STALE
    reason = out["sleeves"]["market_neutral_basis"]["data_freshness"]["reason"]
    assert "2026-07-05" not in reason   # no pendle date to name; it fell back to the file's own age


# ── (b) the manifest entry reflects the judgement, not the file's own row-touch cadence ───────

def test_manifest_entry_reflects_the_stale_judgement_even_though_the_file_itself_is_fresh(tmp_path):
    """The susde_dn file is touched TODAY (fresh by its own cadence) but the pendle dataset behind
    it is frozen months ago — the manifest must say STALE, not MEASURED, and `.as_of`/`.age_hours`
    must stay the FILE's own true observation (never pulled back to the frozen date — that would
    reopen M6c through the back door)."""
    data_dir = tmp_path / "data"
    _write_susde(data_dir, last_date=NOW.strftime("%Y-%m-%d"))
    _write_pendle_history(data_dir, generated_at="2026-07-05T22:43:58+00:00")
    out = sleeves.build_sleeves(data_dir, NOW)
    entry = {i["name"]: i for i in out["inputs"]}["susde_dn_realized_series"]
    assert entry["state"] == contract.STALE
    assert entry["as_of"].startswith(NOW.strftime("%Y-%m-%d"))     # the FILE's own as_of, untouched
    assert entry["age_hours"] is not None and entry["age_hours"] < 24


def test_pendle_history_file_never_appears_in_the_general_input_manifest(tmp_path):
    data_dir = tmp_path / "data"
    _write_susde(data_dir, last_date=NOW.strftime("%Y-%m-%d"))
    _write_pendle_history(data_dir, generated_at="2026-07-05T22:43:58+00:00")
    out = sleeves.build_sleeves(data_dir, NOW)
    assert "rates_desk_pendle_pt_history" not in {i["name"] for i in out["inputs"]}


# ── (c) evidence_cutoff is never moved by the pendle file ──────────────────────────────────────

def test_evidence_cutoff_is_not_dragged_back_by_a_frozen_pendle_history(tmp_path):
    """Every OTHER input is as_of-TODAY; only the pendle file (read for judgement only) is frozen
    at 2026-07-05. Red against the pre-fix code, which put pendle_history_input in `inputs` and
    pulled evidence_cutoff back to July."""
    data_dir = tmp_path / "data"
    _write_susde(data_dir, last_date=NOW.strftime("%Y-%m-%d"))
    _write_pendle_history(data_dir, generated_at="2026-07-05T22:43:58+00:00")
    (data_dir / "strategy_lab_paper").mkdir(parents=True, exist_ok=True)
    (data_dir / "strategy_lab_paper" / "variant_n_series.json").write_text(json.dumps(
        {"id": "variant_n", "series": [{"date": NOW.strftime("%Y-%m-%d"), "ts": NOW.isoformat(),
                                        "equity_usd": 100000.0, "net_apy_pct": 0.1}],
         "generated_at": NOW.isoformat()}))
    out = sleeves.build_sleeves(data_dir, NOW)
    rec = policy.recommend(out, None, NOW)
    assert rec["evidence_cutoff"] is not None
    assert rec["evidence_cutoff"].startswith(NOW.strftime("%Y-%m-%d"))
    assert "2026-07-05" not in (rec["evidence_cutoff"] or "")
