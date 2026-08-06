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

Both spellings count (widened 2026-08-06). A quoted ``"2026-08-02T15:01:33"`` and
a ``dt.datetime(2030, 1, 15, tzinfo=dt.timezone.utc)`` are the same bomb; the
detector saw only the first for its first two days, which left 25 files inside
the class and outside the guard's field of view. Widening re-seeded the baseline
once (251 → 276, reason recorded in the baseline header); from there it shrinks
again, and ``test_baseline_holds_nothing_that_is_no_longer_at_risk`` now enforces
that direction instead of trusting it.

Safe patterns and helpers: ``spa_core/tests/_freshness.py``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_BASELINE = _TESTS_DIR / "frozen_date_baseline.json"

_ISO_DATE_RE = re.compile(r"""["']20\d\d-\d\d-\d\d""")
# The same bomb, written the other way. Until 2026-08-06 this guard looked only
# for a quoted ISO date, so `dt.datetime(2030, 1, 15, tzinfo=dt.timezone.utc)`
# — the identical hazard, one keystroke apart — passed it in silence. That is
# the recurring shape in this repo: a guard answers its own question honestly
# ("is there a quoted date?") while sounding like it answered the needed one
# ("is there a literal date?"). Measured radius of the widening: 25 files.
# The leading \b carries the prefixes on its own: `dt.datetime(`, `datetime.date(`
# and `_dt.date(` all break a word boundary at the dot, while `mydate(` does not.
_CTOR_DATE_RE = re.compile(r"\b(?:datetime|date)\s*\(\s*20\d\d\s*,")
# A literal date only becomes a time bomb next to a freshness concept — that is
# what turns "a date" into "a date that must stay inside a window".
_FRESHNESS_RE = re.compile(
    r"\b(as_of|generated_at|last_updated|fresh|stale|age_h|age_hours|MAX_AGE|"
    r"window|expires?|ttl|cutoff)\b", re.IGNORECASE)
_OPT_OUT_RE = re.compile(r"#\s*FROZEN-DATE-OK", re.IGNORECASE)
# Note this file can never appear in its own class: defining the marker means
# containing it, so the scan opts this file out by accident. That is harmless —
# every date here IS a detector sample, i.e. reason 3 on record — but it is an
# accident, and a guard that silently cannot see itself should say so.


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
        if _has_literal_date(src) and _FRESHNESS_RE.search(src):
            out.add(f.name)
    return out


def _has_literal_date(src: str) -> bool:
    """Both spellings of the same bomb: quoted ISO date, or date/datetime ctor."""
    return bool(_ISO_DATE_RE.search(src) or _CTOR_DATE_RE.search(src))


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


def test_baseline_holds_nothing_that_is_no_longer_at_risk() -> None:
    """The ratchet direction, enforced mechanically instead of on trust.

    Without this the "may only shrink" rule is a comment: a fixed file could sit
    in the baseline forever, and the day that same file re-acquires a literal
    date the ratchet would wave it through — it is on the list already. It also
    forecloses the abuse the 2026-08-06 re-seed would otherwise set a precedent
    for: pre-emptively listing a file that is not in the class yet.

    Fixing a file therefore means removing its name here, in the same change.
    """
    base, now = _baseline(), _at_risk_files()
    assert base is not None
    stale = sorted(base - now)
    assert not stale, (
        "baseline lists file(s) that are no longer in the at-risk class:\n  "
        + "\n  ".join(stale)
        + "\n\nEither they were fixed (then drop the name — the baseline shrinks, "
          "that is the point), or they were added pre-emptively, which the ratchet "
          "does not allow.")


def test_ratchet_recognises_the_pattern_it_is_meant_to_catch(tmp_path: Path) -> None:
    """Positive control: the detector must actually fire on the 2026-08-04 shape."""
    sample = '''
        doc = {"generated_at": "2026-08-02T15:01:33+00:00",
               "adapters": {"maple": {"live_apy": 5.06}}}
    '''
    assert _has_literal_date(sample) and _FRESHNESS_RE.search(sample)
    assert not _OPT_OUT_RE.search(sample)
    # …and must NOT fire once the file declares the exemption.
    assert _OPT_OUT_RE.search(sample + "\n# FROZEN-DATE-OK: parser fixture\n")


# The constructor spelling — the half of the class this ratchet could not see
# until 2026-08-06. Each sample below is a real shape lifted from the suite.
_CTOR_SAMPLES = (
    'now = dt.datetime(2030, 1, 15, 12, 0, tzinfo=dt.timezone.utc)',
    'NOW = datetime(2026, 7, 30, 20, 0, 0, tzinfo=timezone.utc)',
    'base = _dt.date(2024, 1, 1)',
    'cutoff = datetime.date(2026, 8, 4)',
)


@pytest.mark.parametrize("line", _CTOR_SAMPLES)
def test_constructor_dates_are_seen_by_the_detector(line: str) -> None:
    """Positive control for the widening: RED on the new detector…"""
    src = f"{line}\ndoc = {{'generated_at': stamp}}\n"
    assert _has_literal_date(src), f"constructor date not detected: {line}"
    assert _FRESHNESS_RE.search(src)


@pytest.mark.parametrize("line", _CTOR_SAMPLES)
def test_constructor_dates_were_invisible_to_the_quoted_only_detector(line: str) -> None:
    """…and GREEN on the old one — which is precisely why it had to be widened.

    Control in the other direction: without this the widening could be a no-op
    (a regex that fires on everything would pass the test above just as well).
    """
    assert not _ISO_DATE_RE.search(line), (
        f"sample is not a proof of the gap — the OLD detector already saw it: {line}")


def test_detector_does_not_fire_on_a_clockless_call_or_a_look_alike_name() -> None:
    """Negative control: `datetime.now()`, `date.today()` and `update(...)` are not dates."""
    for benign in ("dt.datetime.now(dt.timezone.utc)", "dt.date.today()",
                   "mydate(2026, 8, 4)", "self._update(2026, 8)"):
        assert not _CTOR_DATE_RE.search(benign), f"false positive on: {benign}"


def test_relative_helper_is_immune_to_the_calendar() -> None:
    """The recommended pattern must produce a timestamp inside any sane window."""
    from spa_core.tests._freshness import hours_between, ts
    assert 5.9 < hours_between(ts(0), ts(6)) < 6.1
