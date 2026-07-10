"""Tests for the Q2-5b avoided-loss refusal ledger (spa_core/strategy_lab/rates_desk/refusal_value.py).

Verifies the honest properties: avoided loss = real peg drawdown (conservative lower bound), advertised
implied yield is surfaced as tail-comp EVIDENCE (never netted into a misleading foregone-carry), missing
peg data is listed UNPRICED not fabricated, deterministic, advisory. Injected fixtures — no network.
"""
import json

import pytest

from spa_core.strategy_lab.rates_desk import refusal_value as rv


def _prices():
    # eth flat at 1.0; ezeth peg holds ~1.02 then breaks to 0.80 (−21.6%); rseth absent (→ unpriced).
    # >=30 points required by _peg_drawdown → daily over ~2.5 months.
    dates = [f"2025-{m:02d}-{d:02d}" for m in (1, 2, 3) for d in range(1, 29)]
    eth = {d: 1.0 for d in dates}
    half = len(dates) // 2
    ezeth = {d: (1.02 if i < half else 0.80) for i, d in enumerate(dates)}
    eeth = {d: (1.0 if i < half else 0.75) for i, d in enumerate(dates)}  # −25%
    return {"series": {"eth": eth, "ezeth": ezeth, "eeth": eeth}}


def _pt_hist():
    return {"markets": {
        "m1": {"underlying": "ezETH", "series": [
            {"date": "2025-01-01", "implied_yield": 0.20},
            {"date": "2025-02-15", "implied_yield": 0.60},   # tail-comp spike pre-depeg
            {"date": "2025-04-22", "implied_yield": 0.05}]},
        "m2": {"underlying": "eETH", "series": [
            {"date": "2025-01-01", "implied_yield": 0.45}]},
    }}


@pytest.fixture(autouse=True)
def _inject(monkeypatch):
    monkeypatch.setattr(rv, "_load", lambda path, what: _prices() if "prices" in what else _pt_hist())


def test_avoided_loss_is_real_peg_drawdown():
    rep = rv.build_report(write=False)
    ev = {e["underlying"]: e for e in rep["events"]}
    assert "ezETH" in ev and "eETH" in ev
    # avoided loss is a POSITIVE number equal to |peg drawdown|
    assert ev["ezETH"]["avoided_loss_usd_per_100k"] > 0
    assert ev["ezETH"]["avoided_loss_pct_lower_bound"] == pytest.approx(-ev["ezETH"]["peg_drawdown_pct"], abs=1e-6)
    # ≈ −21.6% → ~$21.6k avoided per $100k
    assert 20000 < ev["ezETH"]["avoided_loss_usd_per_100k"] < 23000


def test_advertised_yield_is_evidence_not_netted():
    rep = rv.build_report(write=False)
    ev = {e["underlying"]: e for e in rep["events"]}
    # the tail-comp spike is surfaced …
    assert ev["ezETH"]["peak_advertised_implied_yield_pct"] == pytest.approx(60.0, abs=1e-6)
    assert ev["ezETH"]["yield_was_tail_comp"] is True
    # … and NOT subtracted into a negative "net" (opportunity cost vs floor ≈ 0)
    assert ev["ezETH"]["opportunity_cost_vs_floor_pct"] == 0.0
    assert "net_refusal_value_usd_per_100k" not in ev["ezETH"]


def test_missing_peg_data_unpriced_not_fabricated():
    rep = rv.build_report(write=False)
    unp = {u["underlying"] for u in rep["unpriced"]}
    assert "rsETH" in unp                     # no series → honest gap
    assert all("reason" in u for u in rep["unpriced"])


def test_total_and_determinism():
    a = rv.build_report(write=False)
    b = rv.build_report(write=False)
    assert a == b
    assert a["total_avoided_loss_usd_per_100k"] == pytest.approx(
        sum(e["avoided_loss_usd_per_100k"] for e in a["events"]), abs=1e-6)
    assert a["is_advisory"] is True and a["llm_forbidden"] is True


def test_write_roundtrip(tmp_path, monkeypatch):
    out = tmp_path / "refusal_value.json"
    monkeypatch.setattr(rv, "_OUT", out)
    rep = rv.build_report(write=True)
    assert out.exists()
    assert json.loads(out.read_text())["events"] == rep["events"]
