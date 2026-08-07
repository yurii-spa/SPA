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
* a file whose literal dates are provably harmless declares
  ``FROZEN-DATE-OK: <reason>`` in a comment and is excluded — a decision on
  record, not an oversight.

Two honest reasons, not one (recorded 2026-08-08). The marker used to be
described for exactly one case — "the date IS the subject" (parsing, golden
file, a historical incident). That left the rule's own *best* pattern with
nowhere to go: `.claude/rules/deployment.md` preference #1 says inject the
clock — pass ``now=`` together with fixed stamps, so both sides are pinned and
the test is immune to the calendar. A file written that way still holds a
literal date next to a freshness word, so the ratchet flagged it, and its
author's three options were: obey option 1 and be flagged anyway, downgrade to
option 2, or write a reason that is not true. Four files had already resolved
this on their own by marking themselves "часы инъектируются" — the practice
existed, the guard just refused to name it. It is named now: ``injected-clock``.

Why the detector was NOT widened instead (measured on 276 at-risk files):

* "the file mentions ``now=X`` somewhere" would exempt **64** files — 53 of them
  are not the pattern at all, and **28** demonstrably mix an injected anchor
  with bare literal dates. That signal is a fail-OPEN: it would blind the guard
  to real bombs sitting one line below a well-written test.
* the strictest mechanical reading (every literal-date line assigns an anchor
  AND every anchor is passed as ``now=``) matches **12** files, but still cannot
  prove immunity: whether the injected anchor actually reaches *every* freshness
  assertion is a semantic property, not a regex one. A guard claiming otherwise
  would be the same shape of failure this repo keeps paying for — answering its
  own question honestly while being read as answering the needed one.

So the detector stays exactly as sensitive as it was, and the *remediation text*
was fixed instead: it now offers the truthful marker first. The marker in turn
got stricter — a bare ``FROZEN-DATE-OK`` with no reason no longer counts, so an
exemption cannot be a silent mute (17/17 existing markers already carry one).

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
# An exemption is a decision on record, so it must carry a reason. Without this
# a bare `# FROZEN-DATE-OK` was a silent mute that read like a judgement.
_OPT_OUT_WITH_REASON_RE = re.compile(r"#\s*FROZEN-DATE-OK\s*:\s*(\S.*)", re.IGNORECASE)
# The reason for a test written per preference #1 of `.claude/rules/deployment.md`.
_INJECTED_CLOCK = "injected-clock"

# This file used to opt itself out BY ACCIDENT: the marker was spelled out in
# the docstring above, and containing it is all the scan looks for. The
# docstring now spells it without the leading `#`, and the exemption below is
# deliberate — every date in this file is a detector sample.
# FROZEN-DATE-OK: detector-samples — the dates here are the detector's own
# fixtures; each one exists to be matched or rejected by the regexes above.


def _at_risk_files() -> set:
    """Test files holding a literal date AND talking about freshness."""
    out = set()
    for f in sorted(_TESTS_DIR.glob("test_*.py")):
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if _is_at_risk(src):
            out.add(f.name)
    return out


def _is_at_risk(src: str) -> bool:
    """A literal date next to a freshness concept, with no reasoned exemption.

    The exemption requires a REASON: an unexplained ``# FROZEN-DATE-OK`` mutes
    the guard without saying anything, which is the one thing an opt-out on
    record must never be.
    """
    if _OPT_OUT_WITH_REASON_RE.search(src):
        return False
    return bool(_has_literal_date(src) and _FRESHNESS_RE.search(src))


def _has_literal_date(src: str) -> bool:
    """Both spellings of the same bomb: quoted ISO date, or date/datetime ctor."""
    return bool(_ISO_DATE_RE.search(src) or _CTOR_DATE_RE.search(src))


def _remediation_text() -> str:
    """What the author of a newly-flagged file is told to do.

    Order matters and used to be wrong. Preference #1 of the deployment rule —
    inject the clock — was listed first, yet following it is *what puts the file
    in this class*, so the advice terminated in a loop. The fix is not a
    different pattern but the missing second half of it: an injected-clock file
    says so in the marker, truthfully, and is out.
    """
    return (
        "Such a test starts failing when the calendar moves, for a reason "
        "unrelated to the behaviour under test. Fix it with one of:\n"
        f"  1. inject the clock (preference #1 of .claude/rules/deployment.md):\n"
        f"     pass now= AND fixed stamps derived from the same anchor, then say\n"
        f"     so — '# FROZEN-DATE-OK: {_INJECTED_CLOCK} — <how>'. Both sides are\n"
        f"     pinned, the test is immune to the calendar, and the marker is TRUE.\n"
        "  2. relative fixtures — spa_core.tests._freshness.ts(hours_ago=N);\n"
        "  3. if the date IS the subject (parsing / golden / historical), mark\n"
        "     the file '# FROZEN-DATE-OK: <reason>' so it is a decision on record.\n"
        "Every marker MUST carry a reason — a bare marker is a silent mute and "
        "is rejected.\n"
        "Do NOT add the file to the baseline: the baseline only ever shrinks.")


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
        + "\n\n" + _remediation_text())


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


# --- the injected-clock exemption: controls in BOTH directions -------------
#
# Widening the detector was measured and rejected (see module docstring). What
# changed is that the rule's best pattern now has a truthful way to say so. Each
# test below pins one half of that; without the second half of each pair the
# change would be a quieting of the guard, which `.claude/rules/deployment.md`
# forbids outright.

# Preference #1 written out: one anchor, every stamp derived from it, the anchor
# handed to the code under test. Lifted from test_agent_registry_refresh.py.
_PREFERENCE_1_SAMPLE = (
    "NOW = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)\n"
    "_write_registry(tmp_path, (NOW - timedelta(hours=478.1)).isoformat())\n"
    "report = arr.refresh_if_stale(tmp_path, now=NOW, builder=builder)\n"
    "assert report['stale'] is True\n")


def test_preference_1_file_is_flagged_until_it_says_why() -> None:
    """The finding itself: obeying the rule's best advice trips the guard.

    Kept as a test rather than a comment so the day someone widens the detector
    this states out loud what that would silently change.
    """
    assert _is_at_risk(_PREFERENCE_1_SAMPLE), (
        "sample no longer reproduces the finding — it must land in the at-risk "
        "class, otherwise the exemption below is exempting nothing")


def test_injected_clock_marker_lets_the_best_pattern_through() -> None:
    """…and with the truthful marker it is out — no lie, no downgrade."""
    marked = (f"# FROZEN-DATE-OK: {_INJECTED_CLOCK} — now= is injected, every "
              f"stamp derives from NOW\n" + _PREFERENCE_1_SAMPLE)
    assert not _is_at_risk(marked)


def test_a_marker_without_a_reason_does_not_exempt() -> None:
    """Control the other way: the exemption is the reason, not the incantation."""
    bare = "# FROZEN-DATE-OK\n" + _PREFERENCE_1_SAMPLE
    assert _is_at_risk(bare), (
        "a bare marker muted the guard — an exemption with nothing on record "
        "is exactly the silent opt-out this ratchet exists to prevent")


def test_a_real_bomb_still_reddens_marker_or_not() -> None:
    """The negative control that makes the change a fix and not a hole.

    The 2026-08-04 shape: a hardcoded stamp compared against the wall clock,
    nothing injected. It must stay in the class — and it must NOT be rescued by
    claiming the injected-clock reason it does not have.
    """
    bomb = ('doc = {"generated_at": "2026-08-02T15:01:33+00:00"}\n'
            'assert age_hours(doc) < 24\n')
    assert _is_at_risk(bomb)
    assert _is_at_risk("# FROZEN-DATE-OK\n" + bomb)


def test_a_now_kwarg_alone_is_not_accepted_as_proof() -> None:
    """The fail-OPEN that the rejected widening would have created.

    Measured on the live suite: 64 at-risk files mention ``now=X`` somewhere,
    and 28 of them pair an injected anchor with a bare literal date. Had the
    detector been taught to trust the kwarg, every one of those bombs would have
    gone dark. This sample is that exact mixture — it must still be at risk.
    """
    mixed = (_PREFERENCE_1_SAMPLE
             + 'other = {"generated_at": "2026-05-30T12:00:00Z"}\n')
    assert _is_at_risk(mixed), (
        "an injected anchor was accepted as proof for the whole file — that is "
        "the widening this change deliberately did not make")


def test_remediation_offers_the_truthful_marker_before_the_downgrade() -> None:
    """The text is the fix; hold it to what it promises.

    An author who followed preference #1 must be told to KEEP it and say so,
    not to fall back to option 2 or to write a reason that is untrue.
    """
    text = _remediation_text()
    assert _INJECTED_CLOCK in text
    assert text.index(_INJECTED_CLOCK) < text.index("relative fixtures"), (
        "the injected-clock marker must be offered before the fallback — "
        "otherwise the advice still terminates in a loop")
    assert "MUST carry a reason" in text


def test_every_opt_out_in_the_suite_carries_a_reason() -> None:
    """Swept across the real suite, not a fixture: 17/17 already comply.

    So this costs nothing today and closes the hole permanently: the next bare
    marker is caught at the moment it is written.
    """
    unexplained = []
    for f in sorted(_TESTS_DIR.glob("test_*.py")):
        src = f.read_text(encoding="utf-8", errors="replace")
        if _OPT_OUT_RE.search(src) and not _OPT_OUT_WITH_REASON_RE.search(src):
            unexplained.append(f.name)
    assert not unexplained, (
        "opt-out marker with no reason in: " + ", ".join(unexplained)
        + "\nWrite '# FROZEN-DATE-OK: <reason>' — an exemption is a decision on "
          "record, and a decision with no reason is a mute.")


def test_this_guard_can_see_itself() -> None:
    """The accidental self-exemption, made deliberate.

    Naming the marker in the docstring was enough to opt this file out, so for
    its whole life the ratchet's own file sat outside the ratchet by accident.
    The docstring now spells the marker without the leading '#', and the
    exemption is an explicit comment with a reason like everyone else's.
    """
    src = Path(__file__).read_text(encoding="utf-8")
    doc = __doc__ or ""
    assert not _OPT_OUT_RE.search(doc), (
        "the docstring spells the marker again — this file is opting itself "
        "out by accident once more")
    m = _OPT_OUT_WITH_REASON_RE.search(src)
    assert m and "detector-samples" in m.group(1), (
        "this file must carry its own exemption explicitly, with a reason")


def test_relative_helper_is_immune_to_the_calendar() -> None:
    """The recommended pattern must produce a timestamp inside any sane window."""
    from spa_core.tests._freshness import hours_between, ts
    assert 5.9 < hours_between(ts(0), ts(6)) < 6.1
