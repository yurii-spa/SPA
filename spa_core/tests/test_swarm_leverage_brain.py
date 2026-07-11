"""Tests for spa_core/strategy_lab/swarm/leverage_brain.py (Swarm block 4 — L3 leverage brain)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.strategy_lab.swarm import leverage_brain as lb

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))


def _book(state="ARMED", ratio=0.5, risk_class="C", shape="funding_flip") -> dict:
    return {"state": state, "risk_class": risk_class, "risk_shape": shape,
            "signal": {"ratio": ratio} if ratio is not None else None}


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Point the brain at tmp artifacts; return helpers to write them."""
    monkeypatch.setattr(lb, "REGIME_PATH", tmp_path / "funding_regime.json")
    monkeypatch.setattr(lb, "GUARDIAN_PATH", tmp_path / "guardian_forward.json")
    monkeypatch.setattr(lb, "DEPTH_PATH", tmp_path / "depth_at_size.json")

    def regime(reg="GREEN", age_h=0.5):
        _write(tmp_path / "funding_regime.json",
               {"regime": reg, "as_of_utc": (NOW - timedelta(hours=age_h)).isoformat()})

    def guardian(books, age_h=0.5):
        _write(tmp_path / "guardian_forward.json",
               {"as_of_utc": (NOW - timedelta(hours=age_h)).isoformat(), "books": books})

    def depth(flagged=False, age_d=0.5):
        _write(tmp_path / "depth_at_size.json",
               {"flagged": flagged,
                "generated_at": (NOW - timedelta(days=age_d)).isoformat()})

    return tmp_path, regime, guardian, depth


# ── the formula, factor by factor ──────────────────────────────────────────────────────────────
def test_green_calm_carry_book_full_base(wired):
    tmp, regime, guardian, depth = wired
    regime("GREEN"); guardian({"susde_dn": _book()}); depth()
    doc = lb.run_leverage_brain(now=NOW, out_dir=tmp / "out")
    b = doc["books"]["susde_dn"]
    assert b["state"] == "RECOMMENDED" and b["leverage_reco"] == 1.5  # base C × 1 × 1 × 1


def test_red_regime_zeros_carry_halves_other(wired):
    tmp, regime, guardian, depth = wired
    regime("RED")
    guardian({"susde_dn": _book(shape="funding_flip"),
              "eth_directional": _book(risk_class="B", shape="depeg")})
    depth()
    doc = lb.run_leverage_brain(now=NOW, out_dir=tmp / "out")
    assert doc["books"]["susde_dn"]["leverage_reco"] == 0.0        # carry: RED → 0
    assert doc["books"]["susde_dn"]["state"] == "ZERO_EXPOSURE"
    assert doc["books"]["eth_directional"]["leverage_reco"] == 1.0  # other: 2.0 × 0.5


def test_unknown_regime_fail_closed_for_carry_only(wired):
    tmp, regime, guardian, depth = wired
    regime("UNKNOWN")
    guardian({"susde_dn": _book(), "lp_eth_stable": _book(shape="il")})
    depth()
    doc = lb.run_leverage_brain(now=NOW, out_dir=tmp / "out")
    assert doc["books"]["susde_dn"]["leverage_reco"] == 0.0   # broken barometer ≠ good weather
    assert doc["books"]["lp_eth_stable"]["leverage_reco"] == 1.5  # funding is not il's driver


def test_vol_ratio_linear_decay(wired):
    tmp, regime, guardian, depth = wired
    regime("GREEN"); guardian({"b": _book(ratio=1.5)}); depth()
    doc = lb.run_leverage_brain(now=NOW, out_dir=tmp / "out")
    # ratio 1.5 → factor 1 − 0.75·0.5 = 0.625 → 1.5 × 0.625
    assert doc["books"]["b"]["factors"]["guardian_factor"] == pytest.approx(0.625)
    assert doc["books"]["b"]["leverage_reco"] == pytest.approx(0.9375)


def test_derisked_guardian_zeroes(wired):
    tmp, regime, guardian, depth = wired
    regime("GREEN"); guardian({"b": _book(state="DERISKED")}); depth()
    doc = lb.run_leverage_brain(now=NOW, out_dir=tmp / "out")
    assert doc["books"]["b"]["leverage_reco"] == 0.0
    assert doc["books"]["b"]["state"] == "ZERO_EXPOSURE"


# ── refusal-first: nulls, never invented numbers ───────────────────────────────────────────────
def test_levered_book_refused_when_depth_flagged(wired):
    tmp, regime, guardian, depth = wired
    regime("GREEN")
    guardian({"leverage_loop": _book(shape="liquidation")})
    depth(flagged=True)  # today's real state: insufficient contemporaneous depth
    doc = lb.run_leverage_brain(now=NOW, out_dir=tmp / "out")
    b = doc["books"]["leverage_loop"]
    assert b["leverage_reco"] is None and b["state"] == "REFUSED_NO_DEPTH"
    assert any("refusal-first" in r for r in b["reasons"])


def test_levered_book_refused_when_depth_stale_or_missing(wired):
    tmp, regime, guardian, depth = wired
    regime("GREEN"); guardian({"pendle_pt_levered": _book(shape="liquidation")})
    depth(flagged=False, age_d=lb.DEPTH_MAX_AGE_DAYS + 1)
    doc = lb.run_leverage_brain(now=NOW, out_dir=tmp / "out")
    assert doc["books"]["pendle_pt_levered"]["state"] == "REFUSED_NO_DEPTH"

    (tmp / "depth_at_size.json").unlink()
    doc = lb.run_leverage_brain(now=NOW, out_dir=tmp / "out")
    assert doc["books"]["pendle_pt_levered"]["state"] == "REFUSED_NO_DEPTH"


def test_levered_book_recommended_when_depth_clean(wired):
    tmp, regime, guardian, depth = wired
    regime("GREEN"); guardian({"leverage_loop": _book(shape="liquidation")}); depth(flagged=False)
    doc = lb.run_leverage_brain(now=NOW, out_dir=tmp / "out")
    assert doc["books"]["leverage_loop"]["leverage_reco"] == 1.5


def test_stale_guardian_refuses_all(wired):
    tmp, regime, guardian, depth = wired
    regime("GREEN")
    guardian({"susde_dn": _book()}, age_h=lb.GUARDIAN_MAX_AGE_H + 1)
    depth()
    doc = lb.run_leverage_brain(now=NOW, out_dir=tmp / "out")
    assert doc["books"]["susde_dn"]["state"] == "REFUSED_NO_TELEMETRY"
    assert doc["books"]["susde_dn"]["leverage_reco"] is None


def test_warmup_guardian_refuses_book(wired):
    tmp, regime, guardian, depth = wired
    regime("GREEN"); guardian({"young": _book(state="NO_FORWARD", ratio=None)}); depth()
    doc = lb.run_leverage_brain(now=NOW, out_dir=tmp / "out")
    assert doc["books"]["young"]["state"] == "REFUSED_NO_TELEMETRY"


# ── status + proof ─────────────────────────────────────────────────────────────────────────────
def test_status_written_proof_idempotent(wired):
    tmp, regime, guardian, depth = wired
    regime("GREEN"); guardian({"susde_dn": _book()}); depth()
    out = tmp / "out"
    doc = lb.run_leverage_brain(now=NOW, out_dir=out)
    assert doc["proof_appended"] is True
    saved = json.loads((out / lb.STATUS_NAME).read_text())
    assert saved["is_advisory"] and "UNPROVABLE" in saved["honest_limits"]

    doc2 = lb.run_leverage_brain(now=NOW, out_dir=out)
    assert doc2["proof_appended"] is False
    lines = (out / lb.PROOF_NAME).read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["recos"] == {"susde_dn": 1.5}
