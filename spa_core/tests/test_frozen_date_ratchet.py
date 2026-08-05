"""Ratchet: the "literal date in a fixture" class may shrink, never grow.

The trap. A test fixture holding ``"2026-08-02T06:00:00+00:00"`` is fine until
the system gains any notion of freshness — then it starts failing because the
calendar moved, not because anything broke. That happened on 2026-08-04 to three
files at once, one of them written the previous day by the same author.

Why not simply ban literal dates: 346 test files contain them, 3412 occurrences,
262 of those files also mention a freshness concept. A blanket ban would paint
half the suite red and teach everyone to disable the guard — the exact
cry-wolf failure this project keeps paying for.

So this is a RATCHET, not a ban:

* a committed baseline lists the files that already carry the risk;
* a NEW file joining the class fails this test;
* a file that gets fixed simply drops out — the baseline is allowed to shrink,
  and shrinking it is the point;
* a genuinely date-dependent test (parsing, golden file, a historical incident)
  declares ``# FROZEN-DATE-OK: <reason>`` and is excluded — a decision on record,
  not an oversight.

Safe patterns and helpers: ``spa_core/tests/_freshness.py``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_BASELINE = _TESTS_DIR / "frozen_date_baseline.json"

_DATE_RE = re.compile(r"""["']20\d\d-\d\d-\d\d""")
# A literal date only becomes a time bomb next to a freshness concept — that is
# what turns "a date" into "a date that must stay inside a window".
_FRESHNESS_RE = re.compile(
    r"\b(as_of|generated_at|last_updated|fresh|stale|age_h|age_hours|MAX_AGE|"
    r"window|expires?|ttl|cutoff)\b", re.IGNORECASE)
_OPT_OUT_RE = re.compile(r"#\s*FROZEN-DATE-OK", re.IGNORECASE)


def _at_risk_files() -> set:
    """Test files holding a literal date AND talking about freshness."""
    out = set()
    for f in sorted(_TESTS_DIR.glob("test_*.py")):
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if _OPT_OUT_RE.search(src):
            continue
        if _DATE_RE.search(src) and _FRESHNESS_RE.search(src):
            out.add(f.name)
    return out


def _baseline() -> set:
    try:
        return set(json.loads(_BASELINE.read_text(encoding="utf-8"))["files"])
    except Exception:  # noqa: BLE001 — a missing baseline must not pass silently
        return None


def test_baseline_exists_and_is_readable() -> None:
    """No baseline ⇒ the ratchet is not measuring anything. Fail-CLOSED."""
    assert _baseline() is not None, (
        f"{_BASELINE.name} missing or unreadable — the ratchet cannot tell new "
        f"offenders from old ones and must not pass quietly")


def test_no_new_file_joins_the_frozen_date_class() -> None:
    """The one assertion that matters: the class must not grow."""
    base, now = _baseline(), _at_risk_files()
    assert base is not None
    added = sorted(now - base)
    assert not added, (
        "New test file(s) pin a literal date next to a freshness concept:\n  "
        + "\n  ".join(added)
        + "\n\nSuch a test starts failing when the calendar moves, for a reason "
          "unrelated to the behaviour under test. Fix it with one of:\n"
          "  1. inject the clock — pass now= AND literal timestamps (best);\n"
          "  2. relative fixtures — spa_core.tests._freshness.ts(hours_ago=N);\n"
          "  3. if the date IS the subject (parsing / golden / historical), mark\n"
          "     the file '# FROZEN-DATE-OK: <reason>' so it is a decision on record.\n"
          "Do NOT add the file to the baseline: the baseline only ever shrinks.")


def test_baseline_does_not_list_files_that_no_longer_exist() -> None:
    """A baseline full of ghosts silently loosens the ratchet."""
    base = _baseline()
    assert base is not None
    ghosts = sorted(n for n in base if not (_TESTS_DIR / n).is_file())
    assert not ghosts, (
        "baseline lists files that no longer exist: " + ", ".join(ghosts)
        + " — remove them so the ratchet keeps measuring reality")


def test_ratchet_recognises_the_pattern_it_is_meant_to_catch(tmp_path: Path) -> None:
    """Positive control: the detector must actually fire on the 2026-08-04 shape."""
    sample = '''
        doc = {"generated_at": "2026-08-02T15:01:33+00:00",
               "adapters": {"maple": {"live_apy": 5.06}}}
    '''
    assert _DATE_RE.search(sample) and _FRESHNESS_RE.search(sample)
    assert not _OPT_OUT_RE.search(sample)
    # …and must NOT fire once the file declares the exemption.
    assert _OPT_OUT_RE.search(sample + "\n# FROZEN-DATE-OK: parser fixture\n")


def test_relative_helper_is_immune_to_the_calendar() -> None:
    """The recommended pattern must produce a timestamp inside any sane window."""
    from spa_core.tests._freshness import hours_between, ts
    assert 5.9 < hours_between(ts(0), ts(6)) < 6.1
