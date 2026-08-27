"""
Tests for scripts/edge_cost_internalised_timing.py (registry ideas CSSR / CIT).

Every test here is a POSITIVE CONTROL in the sense .claude/rules/deployment.md requires: it
reproduces a failure that would actually change a published verdict, and it goes red when the
corresponding line of the harness is broken. The failures being guarded against are:

  • THE ANCHOR BREAKING. Both entries claim "same instrument, different data". That claim is
    worth nothing unless the fixture path still reproduces #80's published table cell for
    cell. An earlier version of this harness re-implemented the train/test split with its own
    boundary and moved h60's test cell from #80's +0.11 to +0.12 — one cell of disagreement,
    and the word "same" stops being true. The splitter is now imported; this test says so.

  • THE lambda=inf LIMIT DRIFTING AWAY FROM TODAY'S ARM. CIT's whole framing is that the
    arms already published are its own lambda=inf endpoint. If that stops holding, the
    lambda ladder is measuring a different family and the comparison is fiction.

  • A SILENT FIXTURE FALLBACK. #70, #79 and #80 all ran from worktrees, where the panel is
    simply absent (it is not git-tracked) — and all three published FIXTURE numbers. The
    loader must RAISE, never substitute. This is the single most consequential defect in the
    recent history of this registry, and it is invisible in the output.

  • THE SIGN GATE BEING MISREAD AS COST-AWARENESS. Section 6 attributes most of the h60 gain
    to a plain "do not move to an expected-worse vector" gate that contains no cost at all.
    That decomposition is only valid if the c_assumed=0 arm really is lambda-free.

  • THE CONTROL LOSING ITS MATCH. The verdict is "inside the random band" — a statement about
    schedules of THE SAME switch count. If the control's count silently drifts, an arm that
    trades less would be compared against controls that trade more and would look good for
    the wrong reason.

  • A REJECTION SAMPLER ASKED FOR MORE PERMUTATIONS THAN EXIST. The first version of the
    relabel sampler asked for 200 distinct permutations of 5 books, of which 119 exist, and
    hung forever. A hang in a backtest reads as "slow", not as "broken".

No network, no RiskPolicy, no spa_core.execution, no capital. IS_ADVISORY=True.
No literal dates: every synthetic series here is index-addressed, and the only calendar
values used are inherited from the harness under test (`.claude/rules/deployment.md`,
"время в тестах"). The published-number literals ARE the subject — they are the registry
values #80 shipped, and a test that stopped checking them would stop being an anchor.
"""
from __future__ import annotations

import datetime
import importlib.util
import math
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[2]
_SCRIPT = _ROOT / "scripts" / "edge_cost_internalised_timing.py"

# The harness imports its sibling edge scripts by name, so scripts/ has to be importable.
sys.path.insert(0, str(_ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("edge_cit_under_test", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

import edge_cost_signal_separation as css  # noqa: E402
import edge_mhfc_backtest as mh  # noqa: E402

_PANEL = _mod.PANEL_DIR
_HAS_PANEL = (_PANEL / "susde_dn" / "realized_series.jsonl").exists()
_SKIP_PANEL = pytest.mark.skipif(
    not _HAS_PANEL,
    reason=(
        f"real aggressive-lab panel absent at {_PANEL} (it is not git-tracked, so a worktree "
        f"and CI both lack it) — set SPA_PANEL_DIR to the prod tree's data/aggressive_lab. "
        f"This SKIP is deliberate and explicit: silently running the fixture instead is the "
        f"defect this file exists to prevent."
    ),
)

MODES = [m for m, _ in _mod.ARMS]


# ── fixtures ──────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def fx():
    dates, books = _mod.load_fixture_panel()
    return dates, books


def _toy(n: int = 120):
    """Deterministic index-addressed panel: three books with different sign patterns."""
    books = {
        "a": [0.001 * ((i % 7) - 3) for i in range(n)],
        "b": [0.002 if i % 11 < 5 else -0.001 for i in range(n)],
        "c": [0.0005 for _ in range(n)],
    }
    base = datetime.date(2024, 1, 1)  # FROZEN-DATE-OK: an index origin, never compared to now
    dates = [base + datetime.timedelta(days=i) for i in range(n)]
    return dates, books


# ── 1. THE ANCHOR ─────────────────────────────────────────────────────────────────
#: #80's published table, verbatim from docs/DYNAMIC_LEVERAGE_GUARDIAN.md.
#: dCalmar(0), dAPY(0) in pp, dCalmar(96), break-even string.
_PUBLISHED_80 = {
    "h5": (+0.0032, +0.05, -0.20, "1 bps"),
    "h20": (+0.1635, +2.40, -0.23, "28 bps"),
    "h60": (+0.5561, +4.96, -0.05, "82 bps"),
    "mhfc": (+0.0032, +0.06, -0.28, "0 bps"),
}


def test_anchor_reproduces_idea80_published_table(fx):
    """The fixture path must still be #80's instrument, cell for cell."""
    dates, books = fx
    eq = _mod.score(_mod.candidates_for(books, len(dates), "eq").weights, books)
    eq_cal, eq_apy = mh._calmar(eq.net(0.0)), mh._apy(eq.net(0.0))
    for mode in MODES:
        s = _mod.score(_mod.candidates_for(books, len(dates), mode).weights, books)
        d0 = mh._calmar(s.net(0.0)) - eq_cal
        dapy0 = (mh._apy(s.net(0.0)) - eq_apy) * 100
        d96 = mh._calmar(s.net(_mod.CONVENTION_COST)) - eq_cal
        be, _ = css._breakeven_cost(s.gross, s.turns, eq_cal)
        want = _PUBLISHED_80[mode]
        assert d0 == pytest.approx(want[0], abs=5e-4), f"{mode} dCal(0) drifted from #80"
        assert dapy0 == pytest.approx(want[1], abs=5e-3), f"{mode} dAPY(0) drifted from #80"
        assert d96 == pytest.approx(want[2], abs=5e-3), f"{mode} dCal(96) drifted from #80"
        assert be == want[3], f"{mode} break-even drifted from #80"


def test_anchor_reproduces_idea80_mhfc_headline(fx):
    """#79's headline row, which #80 reproduced byte-for-byte and so must this."""
    dates, books = fx
    s = _mod.score(_mod.candidates_for(books, len(dates), "mhfc").weights, books)
    net = s.net(_mod.CONVENTION_COST)
    assert mh._apy(net) * 100 == pytest.approx(-14.73, abs=5e-3)
    assert mh._mdd(net) * 100 == pytest.approx(-31.95, abs=5e-3)
    assert mh._calmar(net) == pytest.approx(-0.46, abs=5e-3)
    assert s.turnover_per_year(len(dates) - 1) == pytest.approx(13.84, abs=5e-3)


def test_split_net_is_the_inherited_splitter_not_a_new_one(fx):
    """#80's train/test boundary, imported rather than re-derived.

    The bug this replaces: a home-grown slicer that put the boundary day in BOTH halves and
    forgave the first day's toll, which moved h60's published test cell +0.11 -> +0.12.
    """
    dates, books = fx
    ret_dates = list(dates[1:])
    s = _mod.score(_mod.candidates_for(books, len(dates), "h60").weights, books)
    net = s.net(_mod.CONVENTION_COST)
    tr, te = _mod.split_net(net, ret_dates)
    assert (tr, te) == mh._split(list(net), ret_dates, mh.SPLIT_DATE)
    assert len(tr) + len(te) == len(net), "a day was dropped or double-counted by the split"

    eq = _mod.score(_mod.candidates_for(books, len(dates), "eq").weights, books)
    etr, ete = _mod.split_net(eq.net(_mod.CONVENTION_COST), ret_dates)
    assert mh._calmar(te) - mh._calmar(ete) == pytest.approx(+0.11, abs=5e-3)


# ── 2. THE lambda LIMITS ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("mode", MODES)
def test_lambda_inf_is_exactly_todays_arm(fx, mode):
    """CIT's upper limit must BE the already-published arm, not merely resemble it."""
    dates, books = fx
    hist, _ = _mod.cit_history(books, len(dates), mode, float("inf"), _mod.CONVENTION_COST)
    assert hist == css._weight_history(books, dates, mode)


@pytest.mark.parametrize("mode", MODES)
def test_lambda_zero_freezes_the_first_vector(fx, mode):
    """The lower limit must be a genuine zero-turnover arm, not 'nearly zero'."""
    dates, books = fx
    hist, switches = _mod.cit_history(books, len(dates), mode, 0.0, _mod.CONVENTION_COST)
    assert switches == 0
    assert all(day == hist[0] for day in hist)
    s = _mod.score(hist, books)
    assert sum(s.turns) == pytest.approx(0.0, abs=1e-12)
    # zero turnover => the net series cannot depend on the toll at all
    assert s.net(0.0) == s.net(10_000.0)


@pytest.mark.parametrize("mode", MODES)
def test_switch_count_is_monotone_in_lambda(fx, mode):
    """A longer assumed holding horizon can only make a move MORE affordable, never less."""
    dates, books = fx
    counts = [
        _mod.cit_history(books, len(dates), mode, lam, _mod.CONVENTION_COST)[1]
        for lam in _mod.LAMBDA_GRID
    ]
    assert counts == sorted(counts), f"{mode}: switch counts not monotone in lambda: {counts}"


def test_higher_assumed_toll_never_increases_switching(fx):
    """The toll enters the rule with the right SIGN.

    Flip the inequality in cit_history and this reverses, which is the whole mechanism.
    """
    dates, books = fx
    for mode in MODES:
        counts = [
            _mod.cit_history(books, len(dates), mode, 20.0, c)[1] for c in (0, 24, 96, 384)
        ]
        assert counts == sorted(counts, reverse=True), f"{mode}: toll has the wrong sign"


def test_sign_gate_is_lambda_free(fx):
    """Section 6's decomposition is only meaningful if c_assumed=0 removes lambda entirely."""
    dates, books = fx
    for mode in MODES:
        base, base_n = _mod.cit_history(books, len(dates), mode, 1.0, 0.0)
        for lam in (5.0, 20.0, 1e6):
            other, other_n = _mod.cit_history(books, len(dates), mode, lam, 0.0)
            assert other == base and other_n == base_n, f"{mode}: sign gate depends on lambda"


# ── 3. NO LOOK-AHEAD ──────────────────────────────────────────────────────────────
def test_no_lookahead_future_returns_cannot_move_the_past():
    """Perturb the tail of every book; the head of the weight history must not move."""
    dates, books = _toy()
    cut = 80
    hist_a, _ = _mod.cit_history(books, len(dates), "h20", 20.0, 96.0)
    # Drive ONE book's signal decisively negative after `cut`. A uniform shift would not do:
    # lifting every book leaves every signal positive, the include-set is unchanged, and the
    # test passes while measuring nothing (that was this test's first, ornamental version).
    perturbed = dict(books)
    perturbed["a"] = books["a"][:cut] + [-0.05] * (len(books["a"]) - cut)
    hist_b, _ = _mod.cit_history(perturbed, len(dates), "h20", 20.0, 96.0)
    assert hist_a[: cut - 1] == hist_b[: cut - 1], "a future return moved a past weight"
    assert hist_a[cut:] != hist_b[cut:], "the perturbation did not reach the arm at all"


def test_candidate_cache_matches_a_from_scratch_arm():
    """The speed cache must be invisible in the numbers, or it is not a speed cache."""
    dates, books = _toy()
    cached = _mod.candidates_for(books, len(dates), "h20")
    fresh_w = [mh._weights(books, i, "h20") for i in range(1, len(dates))]
    fresh_s = [_mod._signals_at(books, i, "h20") for i in range(1, len(dates))]
    assert cached.weights == fresh_w
    assert cached.signals == fresh_s


# ── 4. THE CONTROLS ───────────────────────────────────────────────────────────────
def test_scheduled_history_moves_only_on_the_given_days():
    dates, books = _toy()
    days = [10, 40, 70]
    hist = _mod.scheduled_history(books, len(dates), "h20", days)
    moved = [k for k in range(1, len(hist)) if hist[k] != hist[k - 1]]
    assert set(moved) <= set(days), "the control traded on a day it was not allowed to"


def test_random_control_matches_the_switch_count_it_is_given():
    """'Inside the band' is a claim about EQUAL trade counts. If the match slips, so does it."""
    for n in (1, 5, 37):
        days = _mod.random_switch_days(200, n, seed=3)
        assert len(days) == n
        assert len(set(days)) == n
        assert min(days) >= 1 and max(days) < 200


def test_periodic_control_matches_the_switch_count_it_is_given():
    for n in (1, 5, 37):
        assert len(_mod.periodic_switch_days(200, n)) == n


def test_relabel_is_exhaustive_when_it_can_be_and_never_hangs():
    """The hang that ate the first run: 200 distinct permutations demanded out of 119."""
    five = ["a", "b", "c", "d", "e"]
    perms = _mod.relabel_permutations(five, _mod.RELABEL_SAMPLES)
    assert len(perms) == math.factorial(5) - 1
    assert len(set(map(tuple, perms))) == len(perms)
    assert five not in perms

    ten = [f"b{i}" for i in range(10)]
    sampled = _mod.relabel_permutations(ten, 50)
    assert len(sampled) == 50
    assert len(set(map(tuple, sampled))) == 50
    assert ten not in sampled
    assert _mod.relabel_permutations(ten, 50) == sampled, "sampler is not seeded"


def test_relabel_sampler_is_bounded_and_fails_loudly():
    """Guard the HANG itself, not just its symptom.

    Removing the exhaustive branch used to leave a rejection sampler spinning forever on a
    space smaller than its target. A test can only redden on a failure that TERMINATES, so
    the sampler carries a budget. Calling the sampling path with an impossible target must
    raise, not spin.
    """
    five = ["a", "b", "c", "d", "e"]
    with pytest.raises(RuntimeError) as exc:
        _mod._sample_relabel_permutations(five, math.factorial(5))
    assert "more than the space contains" in str(exc.value)


def test_relabel_preserves_turnover_exactly():
    """RELABEL is only a valid control because it is turnover-EXACT, not turnover-similar."""
    dates, books = _toy()
    ids = sorted(books)
    hist = _mod.candidates_for(books, len(dates), "h20").weights
    _, turns = css._gross_and_turnover(hist, books)
    for perm in _mod.relabel_permutations(ids, 5):
        _, t2 = css._gross_and_turnover(css._relabel(hist, perm, ids), books)
        assert sum(t2) == pytest.approx(sum(turns), abs=1e-12)


# ── 5. THE SILENT-FALLBACK DEFECT ─────────────────────────────────────────────────
def test_missing_panel_raises_instead_of_substituting_the_fixture(tmp_path):
    """#70, #79 and #80 published fixture numbers from a worktree because nothing raised."""
    with pytest.raises(FileNotFoundError) as exc:
        _mod.load_real_panel(tmp_path / "definitely-not-here")
    assert "refusing to substitute the fixture" in str(exc.value)


def test_short_panel_is_refused_rather_than_published(tmp_path):
    book = tmp_path / "only_book"
    book.mkdir()
    rows = [
        f'{{"date": "2024-01-{d:02d}", "phase": "backtest", "equity_usd": {100000 + d}}}'
        for d in range(1, 29)  # FROZEN-DATE-OK: a synthetic ledger, never compared to now
    ]
    (book / "realized_series.jsonl").write_text("\n".join(rows) + "\n")
    with pytest.raises((RuntimeError, ValueError)):
        _mod.load_real_panel(tmp_path)


# ── 6. THE REAL PANEL (skipped, loudly, where it does not exist) ──────────────────
@_SKIP_PANEL
def test_real_panel_loads_ten_books_on_a_shared_axis():
    dates, books = _mod.load_real_panel()
    assert len(books) >= 5
    assert len(dates) >= 800
    n = len(dates)
    assert all(len(v) == n for v in books.values()), "a book was carried over a missing date"


@_SKIP_PANEL
def test_real_panel_h60_clears_the_registry_cost_convention():
    """The headline of CSSR: on real data the slow arm's break-even is ABOVE 96 bps.

    Guarded because it is the one number in either entry that changes what is worth building.
    Asserted as an inequality, not a literal, so the panel growing cannot redden it falsely.
    """
    dates, books = _mod.load_real_panel()
    eq = _mod.score(_mod.candidates_for(books, len(dates), "eq").weights, books)
    eq_cal = mh._calmar(eq.net(0.0))
    s = _mod.score(_mod.candidates_for(books, len(dates), "h60").weights, books)
    be, d0 = css._breakeven_cost(s.gross, s.turns, eq_cal)
    assert d0 > 0, "h60 must have a break-even at all"
    assert float(be.split()[0]) > _mod.CONVENTION_COST


@_SKIP_PANEL
def test_real_panel_fast_arms_lose_even_when_execution_is_free():
    """CSSR's other half: on real data reading (B) STRUCTURAL is confirmed for h5 and MHFC.

    #80 could not confirm it on the fixture even once. If this ever stops being true, the
    entry's central correction to #80 stops being true with it.
    """
    dates, books = _mod.load_real_panel()
    eq = _mod.score(_mod.candidates_for(books, len(dates), "eq").weights, books)
    eq_cal = mh._calmar(eq.net(0.0))
    for mode in ("h5", "mhfc"):
        s = _mod.score(_mod.candidates_for(books, len(dates), mode).weights, books)
        assert mh._calmar(s.net(0.0)) - eq_cal < 0, f"{mode} no longer loses at zero cost"


def test_candidate_cache_cannot_serve_a_recycled_id():
    """`id()` is unique only among LIVE objects; CPython reuses the number after a collection.

    A cache keyed on a bare id would hand one panel's weights to a different panel that
    happened to land on the same address — silently, and only sometimes. The entry therefore
    holds the panel object itself and re-checks identity before serving.
    """
    dates, books_a = _toy()
    first = _mod.candidates_for(books_a, len(dates), "h20")
    key = (id(books_a), len(dates), "h20")
    assert _mod._CAND_CACHE[key][0] is books_a

    # forge the exact collision a recycled id would produce
    _, books_b = _toy()
    books_b["a"] = [-0.01 for _ in books_b["a"]]
    _mod._CAND_CACHE[key] = (books_b, _mod.Candidates(books_b, len(dates), "h20"))
    served = _mod.candidates_for(books_a, len(dates), "h20")
    assert served.weights == first.weights, "the cache served another panel's weights"


def test_candidate_cache_is_keyed_on_length_too():
    """A cached series of the wrong length would be silently SHORT, not loudly wrong."""
    dates, books = _toy()
    full = _mod.candidates_for(books, len(dates), "h20")
    short = _mod.candidates_for(books, 60, "h20")
    assert len(full.weights) == len(dates) - 1
    assert len(short.weights) == 59
