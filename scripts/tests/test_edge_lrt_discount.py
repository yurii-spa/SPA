"""Controls for scripts/edge_lrt_discount.py (#121 LDR). Synthetic series only — no live data.

The file's whole claim is a refusal: on a level series dominated by white measurement noise the
naive discount rule 'earns' on the negative control too, so the verdict must be НЕ ИЗМЕРЕНО.
The controls therefore run both ways: noisy ⇒ refused, clean-with-real-discounts ⇒ measured.
"""
# FROZEN-DATE-OK: literal ISO dates are synthetic axis labels, compared to each other only
from __future__ import annotations

import datetime as dt
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import edge_lrt_discount as L  # noqa: E402


def _axis(n):
    d0 = dt.date(2024, 6, 1)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


def _noisy(seed, level=1.0, sd=0.03, n=400):
    rnd = random.Random(seed)
    return [(d, level * (1.0 + rnd.gauss(0.0, sd))) for d in _axis(n)]


def _clean_control(n=400):
    # slow, smooth wobble: differenced AC is strongly positive, nothing to trade
    return [(d, 1.0 + 0.0005 * math.sin(i / 20.0)) for i, d in enumerate(_axis(n))]


def _lrt_with_discounts(n=400):
    # accruing ratio + five 3 % discounts that open in one print and close over ten
    out = []
    for i, d in enumerate(_axis(n)):
        r = 1.0 * (1.0 + 0.03 / 365) ** i
        for start in (60, 130, 200, 270, 340):
            if start <= i < start + 10:
                r *= 1.0 - 0.03 * (1.0 - (i - start) / 10.0)
        out.append((d, r))
    return out


def test_white_noise_on_the_level_has_lag1_ac_near_minus_half():
    r = _noisy(1)
    ch = [math.log(r[i][1] / r[i - 1][1]) for i in range(1, len(r))]
    assert -0.6 < L.lag1_ac(ch) < -0.4


def test_noisy_control_is_refused_even_when_lrts_look_profitable():
    diag, edge = {}, {}
    for k, a in enumerate(L.CONTROLS + L.LRTS):
        r = _noisy(k)
        diag[a], edge[a] = L.diagnostics(r), L.naive_rule(r)
    assert all(edge[a]["gross_bp"] > 50 for a in L.CONTROLS)   # the fake edge is real-looking
    v, why = L.verdict(diag, edge)
    assert v == "НЕ ИЗМЕРЕНО" and "negative control" in why


def test_clean_control_and_real_discounts_are_measured():
    diag, edge = {}, {}
    for a in L.CONTROLS:
        r = _clean_control()
        diag[a], edge[a] = L.diagnostics(r), L.naive_rule(r)
    for a in L.LRTS:
        r = _lrt_with_discounts()
        diag[a], edge[a] = L.diagnostics(r), L.naive_rule(r)
    assert edge["ezeth"]["trades"] > 0 and edge["ezeth"]["gross_bp"] > 0
    assert L.verdict(diag, edge)[0] == "MEASURED"


def test_missing_diagnostic_is_a_refusal_not_a_pass():
    v, why = L.verdict({}, {})
    assert v == "НЕ ИЗМЕРЕНО"


def test_flat_control_is_a_refusal_not_a_pass():
    flat = [(d, 1.0) for d in _axis(100)]
    diag = {a: L.diagnostics(flat) for a in L.CONTROLS + L.LRTS}
    edge = {a: L.naive_rule(flat) for a in L.CONTROLS + L.LRTS}
    assert diag["steth"]["lag1_ac"] is None
    assert L.verdict(diag, edge)[0] == "НЕ ИЗМЕРЕНО"


def test_fair_value_reads_only_prior_prints():
    """Sixteen consecutive 2 % dips (prints 40…55). With the fair value read from the 30 PRIOR
    prints, the 16th dip still sees a median of 0.99 (15 dips + 15 par) and enters: 16 trades.
    A window that includes the current print sees 16 dips of 30 → median 0.98 → no entry: 15."""
    r = [(d, 0.98 if 40 <= i <= 55 else 1.0) for i, d in enumerate(_axis(70))]
    e = L.naive_rule(r, k_bp=50.0, roundtrip_bp=0.0)
    assert e["trades"] == 16


def test_absent_file_returns_not_measured(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(L, "RATES_DIR", tmp_path)
    assert L.main([]) == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


def test_ratio_uses_only_common_dates(tmp_path):
    (tmp_path / "prices_deep.json").write_text(json.dumps(
        {"series": {"eth": {"2024-06-01": 2.0, "2024-06-02": 2.0}, "steth": {"2024-06-02": 1.0}}}))
    p = L.load_prices(tmp_path)
    assert L.ratio(p, "steth") == [("2024-06-02", 0.5)]


def test_wired_through_the_116_command(tmp_path):
    """`python scripts/edge_lst_yield_persistence.py --discount` is the named command for #121."""
    import os
    import subprocess
    env = dict(os.environ, SPA_RATES_DIR=str(tmp_path))
    p = subprocess.run([sys.executable, str(Path(L.__file__).with_name("edge_lst_yield_persistence.py")),
                        "--discount"], capture_output=True, text=True, env=env, timeout=120)
    assert p.returncode == 2 and "НЕ ИЗМЕРЕНО" in p.stdout
