"""Owner presentation policy (ADR-660): two-decimal ROUND_HALF_UP percentages + Madrid time.

Every rounding case is a TIE or a binary-float trap — the cases where a ``"%.2f"`` /
``round()`` / ``toFixed(2)`` implementation silently disagrees with the policy. Positive
control: the same inputs through Python's binary ``"%.2f"`` give a different answer on at
least one of them, so a regression back to it cannot pass here.
"""
# FROZEN-DATE-OK: the dates ARE the subject — EU DST transition instants and the owner's own examples
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from spa_core.utils.presentation import fmt_owner_time, fmt_pct, pct_half_up, to_owner_time

NBSP = " "

# (input, RU, EN) — the owner's examples first, then binary-float ties.
CASES = [
    (4.8943, "4,89" + NBSP + "%", "4.89%"),
    (4.8950, "4,90" + NBSP + "%", "4.90%"),
    (4.8999, "4,90" + NBSP + "%", "4.90%"),
    (6, "6,00" + NBSP + "%", "6.00%"),
    (-1.225, "-1,23" + NBSP + "%", "-1.23%"),
    (2.675, "2,68" + NBSP + "%", "2.68%"),       # float 2.67499999… — binary rounding says 2.67
    (-2.675, "-2,68" + NBSP + "%", "-2.68%"),
    (1.005, "1,01" + NBSP + "%", "1.01%"),       # float 1.00499999…
    (-0.005, "-0,01" + NBSP + "%", "-0.01%"),    # negative tie: half-up is away from zero
    (0.125, "0,13" + NBSP + "%", "0.13%"),
    (-0.125, "-0,13" + NBSP + "%", "-0.13%"),
]


@pytest.mark.parametrize("value,ru,en", CASES)
def test_two_decimals_round_half_up(value, ru, en):
    assert fmt_pct(value, "ru") == ru
    assert fmt_pct(value, "en") == en


def test_positive_control_binary_formatting_disagrees_on_the_ties():
    """If the canonical formatter were plain '%.2f', at least one case above would differ."""
    differing = [v for v, _, en in CASES if f"{v:.2f}%" != en]
    assert differing, "the tie cases no longer discriminate half-up from binary rounding"


def test_fraction_input_and_sign():
    assert fmt_pct(0.048943, "en", input="fraction") == "4.89%"
    assert fmt_pct(0.0004, "en", input="fraction", signed=True) == "+0.04%"
    assert fmt_pct(1.5, "en", signed=True) == "+1.50%"
    assert pct_half_up(0.01225, input="fraction") == Decimal("1.23")


def test_absence_is_never_zero():
    for absent in (None, "n/a", float("nan"), float("inf"), True, object()):
        assert fmt_pct(absent, "ru") is None
        assert fmt_pct(absent, "en", unknown="not measured") == "not measured"


def test_measured_zero_is_zero_but_tiny_nonzero_is_qualified():
    assert fmt_pct(0, "en") == "0.00%"
    assert fmt_pct(0.0, "ru") == "0,00" + NBSP + "%"
    assert fmt_pct(0.004, "en") == "<0.01%"
    assert fmt_pct(-0.004, "en") == ">-0.01%"
    assert fmt_pct(-0.004, "ru") == ">-0,01" + NBSP + "%"


def test_bad_input_kind_is_loud():
    with pytest.raises(ValueError):
        fmt_pct(1.0, "en", input="bps")


# ── Madrid time ─────────────────────────────────────────────────────────────

TIMES = [
    # owner's own examples
    ("2026-10-08T07:30:00Z", "2026-10-08 09:30", "CEST"),
    ("2026-12-08T07:30:00Z", "2026-12-08 08:30", "CET"),
    # spring forward: 2026-03-29 01:00 UTC
    ("2026-03-29T00:59:00Z", "2026-03-29 01:59", "CET"),
    ("2026-03-29T01:00:00Z", "2026-03-29 03:00", "CEST"),
    # fall back: 2026-10-25 01:00 UTC
    ("2026-10-25T00:59:00Z", "2026-10-25 02:59", "CEST"),
    ("2026-10-25T01:00:00Z", "2026-10-25 02:00", "CET"),
]


@pytest.mark.parametrize("use_tzdb", [True, False], ids=["zoneinfo", "eu-rule-fallback"])
@pytest.mark.parametrize("utc,local,abbr", TIMES)
def test_madrid_summer_and_winter(utc, local, abbr, use_tzdb):
    assert fmt_owner_time(utc, "ru", use_tzdb=use_tzdb) == f"{local} Мадрид ({abbr})"
    assert fmt_owner_time(utc, "en", use_tzdb=use_tzdb) == f"{local} Madrid ({abbr})"


def test_zoneinfo_and_fallback_agree_hour_by_hour_over_a_year():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
    for h in range(0, 24 * 366, 1):
        a = to_owner_time(t + h * 3600)
        b = to_owner_time(t + h * 3600, use_tzdb=False)
        assert a.utcoffset() == b.utcoffset(), a


def test_time_inputs_and_absence():
    assert fmt_owner_time(datetime(2026, 10, 8, 7, 30), "en", label=False) == "2026-10-08 09:30"  # naive = UTC
    assert fmt_owner_time("2026-10-08T09:30:00+02:00", "en", with_date=False) == "09:30 Madrid (CEST)"
    for bad in (None, "", "yesterday", True):
        assert fmt_owner_time(bad) is None
    assert fmt_owner_time(None, unknown="—") == "—"
