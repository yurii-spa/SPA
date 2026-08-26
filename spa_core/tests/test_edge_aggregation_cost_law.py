"""
Tests for scripts/edge_aggregation_cost_law.py (Ideas #73 ACL / #74 ACL-EX).

Every test here is a POSITIVE CONTROL in the sense .claude/rules/deployment.md requires: it
reproduces a failure that would actually change a published verdict, and it goes red when the
corresponding line of the harness is removed. The failures being guarded against are:

  • the ladder's two ENDS drifting away from #71's per-book / portfolio arms — the whole point
    of #73 is that it is #71's ladder with the middle filled in, and if the ends stop matching,
    the entry is a new measurement pretending to be a continuation of an old one;
  • a "partition" that is not one (overlapping, incomplete or ragged groups), which would
    silently re-weight the panel so every rung would describe a different portfolio while the
    column headers claimed otherwise;
  • `levels_for` quietly approximating the quartet #71 asked for on a 10-book panel, which
    would confound group SIZE with group-size DISPERSION under one heading;
  • `wedge_stats` counting band DAYS instead of band ENTRIES — #73's entire mechanism claim is
    about re-entry ("возвратность внутри полосы"), and a day-counter would be indistinguishable
    from an entry-counter on a monotone crash while disagreeing wildly on an oscillation;
  • `predictor_contest` losing its free control (basket size), which is the only reason #74 is
    a NEGATIVE: without that column the ex-ante statistic's ρ≈0.77 reads like a win;
  • `pick_threshold` breaking ties towards the permissive cut — a pre-flight check whose false
    negative is #71's −12.74%/yr cell must fail CLOSED;
  • `panel_liveness` missing that four of the panel's ten books were killed by the lab's own
    kill-switch in 2024 and frozen since. That single fact is the mechanical cause of the
    "закон одной книги" recorded as a property of RULES by #68, #69 and #71.

No external files, no network, no RiskPolicy, no spa_core.execution. IS_ADVISORY=True.
No literal dates in any assertion: the synthetic panels below use index-addressed dates built
at call time, so the calendar moving cannot turn one of these red
(`.claude/rules/deployment.md`, "время в тестах").
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[2]
_SCRIPT = _ROOT / "scripts" / "edge_aggregation_cost_law.py"

# The harness imports its sibling edge scripts by name, so scripts/ has to be importable.
sys.path.insert(0, str(_ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("edge_acl", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

_PANEL = _mod.PANEL_DIR
_CANON = _mod.CANON_GRID


# ── Helpers: synthetic books with deliberately different drawdown SHAPES ──────

def _drift(n: int = 200, d: float = 0.0004) -> list:
    """Never draws down at all — the wedge must be inert on this."""
    eq = [100_000.0]
    for _ in range(n - 1):
        eq.append(eq[-1] * (1.0 + d))
    return eq


def _sawtooth(n: int = 300, amp: float = 0.004) -> list:
    """Oscillates around its peak — drawdown keeps RE-ENTERING the ramp band."""
    eq = [100_000.0]
    for i in range(1, n):
        eq.append(eq[-1] * (1.0 + (amp if (i // 7) % 2 == 0 else -amp)))
    return eq


def _cliff(n: int = 300, at: int = 80, frac: float = 0.30, over: int = 6) -> list:
    """Falls hard once and stays down — crosses the band exactly once."""
    daily = 1.0 - (1.0 - frac) ** (1.0 / over)
    eq = [100_000.0]
    for i in range(1, n):
        eq.append(eq[-1] * ((1.0 - daily) if at <= i < at + over else 1.0002))
    return eq


def _slide_and_stall(n: int = 300, at: int = 40, depth: float = 0.03, over: int = 10) -> list:
    """Slides ~3% down into the wedge band, then goes FLAT and stays there.

    This shape is what separates an ENTRY counter from a DAY counter: the drawdown sits inside
    (2%, 6%) for ~250 days but crosses INTO it exactly once. A day counter reports ~250 here and
    ~1 on a cliff; an entry counter reports 1 on both. Without this series the two are
    indistinguishable and the test guarding #73's mechanism claim is decoration — it was,
    until a mutation run caught it.
    """
    daily = 1.0 - (1.0 - depth) ** (1.0 / over)
    eq = [100_000.0]
    for i in range(1, n):
        eq.append(eq[-1] * ((1.0 - daily) if at <= i < at + over else 1.0))
    return eq


def _wiggle(n: int = 300, d: float = 0.0004, amp: float = 0.0008) -> list:
    """A quiet book: shallow noise, small but non-zero drawdown."""
    eq = [100_000.0]
    for i in range(1, n):
        eq.append(eq[-1] * (1.0 + d + (amp if (i // 5) % 2 == 0 else -amp)))
    return eq


def _panel(n_books: int = 4, n: int = 300) -> dict:
    """A small panel whose books have deliberately different shapes."""
    shapes = [_sawtooth(n), _cliff(n), _wiggle(n), _drift(n),
              _sawtooth(n, amp=0.002), _cliff(n, at=120), _wiggle(n, amp=0.0004), _drift(n)]
    return {f"b{i}": list(shapes[i % len(shapes)]) for i in range(n_books)}


# ── The ladder's two ENDS must BE #71's arms, not resemble them ───────────────

@pytest.mark.parametrize("d_start,d_full", _mod.PDE_GRID)
def test_level_one_rung_is_bit_identical_to_idea71_per_book(d_start, d_full):
    """n=1 must reproduce #71's per-book arm exactly — equity path, cost and turnover.

    If this drifts, #73's lower anchor stops being #71's published number and the ladder is no
    longer "the same measurement with the middle filled in". That is the entry's whole claim.
    """
    books = _panel(4)
    fn = _mod._pde_fn(d_start, d_full, _mod.ROUNDTRIP)
    ref_eq, ref_cost, ref_turn = _mod.PRP.per_book_overlay(books, fn)
    got_eq, got_cost, got_turn = _mod.grouped_overlay(books, [[b] for b in sorted(books)], fn)
    assert got_cost == pytest.approx(ref_cost, abs=1e-9)
    assert got_turn == pytest.approx(ref_turn, abs=1e-9)
    assert len(got_eq) == len(ref_eq)
    for a, b in zip(ref_eq, got_eq):
        assert a == pytest.approx(b, abs=1e-6)


@pytest.mark.parametrize("d_start,d_full", _mod.PDE_GRID)
def test_full_panel_rung_is_bit_identical_to_idea71_portfolio(d_start, d_full):
    """n=len(panel) must reproduce #71's portfolio arm exactly — the ladder's upper anchor."""
    books = _panel(4)
    fn = _mod._pde_fn(d_start, d_full, _mod.ROUNDTRIP)
    panel_eq = _mod.PRP.equity_from_returns(_mod.PRP.portfolio_returns(books))
    ref_eq, ref_cost, ref_turn = fn(panel_eq)
    got_eq, got_cost, got_turn = _mod.grouped_overlay(books, [sorted(books)], fn)
    assert got_cost == pytest.approx(ref_cost, abs=1e-9)
    assert got_turn == pytest.approx(ref_turn, abs=1e-9)
    for a, b in zip(ref_eq, got_eq):
        assert a == pytest.approx(b, abs=1e-6)


def test_group_of_one_is_the_book_verbatim():
    """A singleton group must be the book itself, not an equal-weight average of one.

    Averaging one book is arithmetically the same only while `portfolio_returns` stays
    loss-free; routing n=1 through it anyway would make the lower anchor depend on a code path
    it has no business depending on.
    """
    books = _panel(3)
    for b in books:
        assert _mod.group_equity(books, [b]) == books[b]


# ── A partition that is not one would silently re-weight the panel ───────────

def test_grouped_overlay_refuses_overlapping_groups():
    books = _panel(4)
    fn = _mod._pde_fn(*_CANON, _mod.ROUNDTRIP)
    with pytest.raises(ValueError, match="partition"):
        _mod.grouped_overlay(books, [["b0", "b1"], ["b1", "b2"]], fn)


def test_grouped_overlay_refuses_an_incomplete_cover():
    books = _panel(4)
    fn = _mod._pde_fn(*_CANON, _mod.ROUNDTRIP)
    with pytest.raises(ValueError, match="partition"):
        _mod.grouped_overlay(books, [["b0", "b1"]], fn)


def test_grouped_overlay_refuses_ragged_groups():
    """Groups of unequal size are not a LEVEL — they confound size with size dispersion."""
    books = _panel(4)
    fn = _mod._pde_fn(*_CANON, _mod.ROUNDTRIP)
    with pytest.raises(ValueError, match="ragged"):
        _mod.grouped_overlay(books, [["b0", "b1", "b2"], ["b3"]], fn)


def test_group_equity_refuses_an_unknown_book():
    with pytest.raises(ValueError, match="absent"):
        _mod.group_equity(_panel(3), ["b0", "nope"])


# ── The quartet #71 asked for must be DROPPED loudly, not approximated ───────

def test_levels_for_drops_non_divisors_on_ten_books():
    """4 does not divide 10. #71's "квартет" must be absent from the 10-book ladder."""
    assert _mod.levels_for(10) == [1, 2, 5, 10]
    assert 4 not in _mod.levels_for(10)


def test_levels_for_admits_the_quartet_on_eight_books():
    """...and must be PRESENT on the 8-book sub-panels, which is how the order gets filled."""
    assert _mod.levels_for(8, (1, 2, 4, 8)) == [1, 2, 4, 8]


def test_random_partition_refuses_a_level_that_does_not_divide():
    with pytest.raises(ValueError, match="does not divide"):
        _mod.random_partition([f"b{i}" for i in range(10)], 3, seed=0)


def test_random_partition_is_a_partition_and_is_deterministic():
    names = [f"b{i}" for i in range(10)]
    for seed in range(5):
        groups = _mod.random_partition(names, 5, seed)
        flat = [b for g in groups for b in g]
        assert sorted(flat) == names, "a random partition must still cover every book once"
        assert {len(g) for g in groups} == {5}
        assert groups == _mod.random_partition(names, 5, seed), "same seed, same partition"


def test_random_partition_actually_varies_with_the_seed():
    """A seed that changed nothing would print twenty identical rows as a 'distribution'."""
    names = [f"b{i}" for i in range(10)]
    seen = {tuple(tuple(g) for g in _mod.random_partition(names, 2, s)) for s in range(20)}
    assert len(seen) > 1


def test_causal_partition_is_a_valid_partition_and_uses_train_only():
    """The causal arm must partition the panel, and must not be handed the TEST window."""
    train = _panel(4)
    groups = _mod.causal_partition(sorted(train), 2, train)
    assert sorted(b for g in groups for b in g) == sorted(train)
    assert {len(g) for g in groups} == {2}
    # Same TRAIN, same grouping — twice, so the ordering cannot depend on dict iteration luck.
    assert groups == _mod.causal_partition(sorted(train), 2, train)


def test_pearson_survives_a_flat_leg():
    """A killed (frozen) book has zero variance. Correlation is undefined, not a crash."""
    assert _mod._pearson([0.0] * 10, list(range(10))) == 0.0


# ── #73's mechanism claim: ENTRIES, not days ────────────────────────────────

def test_wedge_stats_is_inert_when_the_series_never_enters_the_band():
    ws = _mod.wedge_stats(_drift(), d_start=_CANON[0], d_full=_CANON[1])
    assert ws.band_frac == 0.0
    assert ws.entries_yr == 0.0
    assert ws.turn_yr == 0.0


def test_wedge_stats_counts_reentries_not_band_days():
    """THE mechanism claim of #73, and the one a day-counter would fake.

    A single cliff spends time inside the band but ENTERS it once; a sawtooth enters it many
    times. An implementation that counted days would report both as "high" and #73's whole
    explanation ("возвратность внутри полосы") would be unfalsifiable.
    """
    stall = _mod.wedge_stats(_slide_and_stall(), d_start=_CANON[0], d_full=_CANON[1])
    saw = _mod.wedge_stats(_sawtooth(), d_start=_CANON[0], d_full=_CANON[1])
    n_days = len(_slide_and_stall()) - 1

    # The decisive pair: `stall` spends MOST of its life inside the band and enters it ONCE.
    # A day counter cannot produce both of these numbers at the same time.
    assert stall.band_frac > 0.5, "the stalled series does live inside the band"
    assert round(stall.entries_yr * n_days / 365.0) == 1, "...but it crosses into it exactly once"

    assert round(saw.entries_yr * (len(_sawtooth()) - 1) / 365.0) >= 5, "an oscillation re-enters"
    assert saw.entries_yr > 5 * stall.entries_yr


def test_wedge_stats_turnover_tracks_the_wedge_and_not_the_drawdown_depth():
    """A deeper crash past d_full must not keep charging turnover — the ramp saturates at 0."""
    shallow = _mod.wedge_stats(_cliff(frac=0.08), d_start=_CANON[0], d_full=_CANON[1])
    deep = _mod.wedge_stats(_cliff(frac=0.60), d_start=_CANON[0], d_full=_CANON[1])
    assert deep.turn_yr == pytest.approx(shallow.turn_yr, rel=0.35)


def test_band_residency_rises_with_aggregation_on_a_panel_with_one_loud_book():
    """#73's headline shape, on a synthetic panel built to have exactly that structure.

    One loud book plus quiet ones: per book the loud one's drawdown is bimodal, but the
    equal-weight aggregate is smoothed into the wedge's interior and stays there.
    """
    books = {"loud": _sawtooth(400, amp=0.02)}
    for i in range(3):
        books[f"quiet{i}"] = _wiggle(400, amp=0.0002)
    per_book = _mod.panel_wedge_stats(books, [[b] for b in sorted(books)],
                                      d_start=_CANON[0], d_full=_CANON[1])
    whole = _mod.panel_wedge_stats(books, [sorted(books)], d_start=_CANON[0], d_full=_CANON[1])
    assert whole.band_frac > per_book.band_frac


# ── #74: the proxy's error has NO FIXED SIGN — that is the verdict ──────────

def test_ex_ante_proxy_error_changes_direction_with_the_series_shape():
    """#74's decisive property. A one-sided proxy could be corrected by a constant; this cannot.

    If someone "fixes" `wedge_stats` to track the guarded path, this test goes red — and it
    should, because then the statistic is no longer computable BEFORE the overlay is wired,
    which is the only thing that made #74 interesting.
    """
    ratios = {}
    for name, series in (("cliff", _cliff()), ("saw", _sawtooth())):
        ws = _mod.wedge_stats(series, d_start=_CANON[0], d_full=_CANON[1])
        _, _, turn = _mod.PRP.apply_pde_deadband(series, d_start=_CANON[0], d_full=_CANON[1],
                                                 band=0.0)
        years = (len(series) - 1) / 365.0
        ratios[name] = (turn / years) / ws.turn_yr
    assert ratios["cliff"] == pytest.approx(1.0, abs=0.05), "a single crash: proxy is exact"
    assert ratios["saw"] > 1.2, "an oscillation: a cut exposure lingers, so the proxy UNDER-reads"


def test_spearman_is_signed_and_survives_a_constant_leg():
    assert _mod.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert _mod.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    assert _mod.spearman([1, 1, 1, 1], [1, 2, 3, 4]) == 0.0


def test_spearman_averages_ties_rather_than_using_sort_order():
    """Ties broken by position would make ρ depend on how the caller happened to order rows."""
    a = [1, 1, 2, 2]
    assert _mod.spearman(a, [5, 5, 9, 9]) == pytest.approx(1.0)
    assert _mod.spearman(a, [9, 9, 5, 5]) == pytest.approx(-1.0)


def _obs(level, ex, cost, beats):
    return _mod.Observation("s", level, ex, ex, cost / 100.0, cost, 0.0, 0.0, beats)


def test_predictor_contest_still_reports_the_free_control():
    """WITHOUT this column #74 reads as a win. It is a negative only because `n` beat the proxy.

    A contest that silently dropped its own control is the exact shape of "positive control can
    be an ornament": every number would still print, and the verdict would invert.
    """
    obs = [_obs(1, 0.5, 40, True), _obs(2, 1.0, 90, True),
           _obs(5, 3.0, 270, False), _obs(10, 6.0, 600, False)]
    contest = _mod.predictor_contest(obs)
    assert "rho_level_cost" in contest
    assert contest["rho_level_cost"] == pytest.approx(1.0)
    assert contest["rho_exante_cost"] == pytest.approx(1.0)


def test_pick_threshold_breaks_ties_towards_refusing():
    """Fail-CLOSED. The false negative here is #71's −12.74%/yr cell; the false positive is a
    skipped rule. On a tie the cut must go LOW (refuse more), not high."""
    # Balanced accuracy TIES at cuts 1.0 and 3.0 (both 0.75); every other cut scores 0.50.
    # Without a genuine tie this test passes under either tie-break rule and proves nothing —
    # the first version had no tie and stayed green when the rule was inverted.
    obs = [_obs(1, 1.0, 40, True), _obs(2, 2.0, 90, False),
           _obs(5, 3.0, 270, True), _obs(10, 4.0, 600, False)]
    scores = {c: _mod.score_threshold(obs, c)["bal_acc"] for c in (1.0, 2.0, 3.0, 4.0)}
    assert scores[1.0] == pytest.approx(scores[3.0]), "the tie this test is about must exist"
    assert scores[1.0] > scores[2.0] and scores[1.0] > scores[4.0]
    assert _mod.pick_threshold(obs) == pytest.approx(1.0), "on a tie, refuse MORE, not less"


def test_pick_threshold_on_empty_input_refuses_everything():
    assert _mod.pick_threshold([]) == 0.0


def test_score_threshold_counts_the_confusion_matrix():
    obs = [_obs(1, 1.0, 40, True), _obs(2, 2.0, 90, True),
           _obs(5, 3.0, 270, False), _obs(10, 4.0, 600, False)]
    sc = _mod.score_threshold(obs, 2.0)
    assert (sc["tp"], sc["fp"], sc["fn"], sc["tn"]) == (2, 0, 0, 2)
    assert sc["bal_acc"] == pytest.approx(1.0)
    worthless = _mod.score_threshold(obs, 4.0)
    assert (worthless["tp"], worthless["fn"], worthless["tn"]) == (2, 0, 0)
    assert worthless["bal_acc"] == pytest.approx(0.5), "admitting everything is worth nothing"


def test_ratio_stats_ignores_cells_the_wedge_never_armed_on():
    """Ex-ante turnover 0 means the wedge never fired; dividing by it would fabricate a ratio."""
    obs = [_obs(1, 0.0, 0, False), _obs(2, 2.0, 200, True)]
    rs = _mod.ratio_stats(obs)
    assert rs["n"] == 1


def test_collect_observations_refuses_an_unknown_window():
    with pytest.raises(ValueError, match="train.*test"):
        _mod.collect_observations([], {}, window="both")


# ── The control arms must be EXHAUSTIVE, not sampled ────────────────────────

def test_subsets_are_exhaustive_distinct_and_ordered():
    got = _mod.subsets(list("abcde"), 3)
    assert len(got) == 10
    assert len({tuple(g) for g in got}) == 10
    assert all(g == sorted(g) for g in got)


def test_one_book_control_arms_partition_the_subset_space():
    """Arm A = every 8-subset containing the book (36); arm B = every one excluding it (9).

    Hard-coding these counts is the point: a control that quietly sampled would still print a
    table, and the "law of one book" would be re-confirmed or refuted on an arbitrary handful.
    """
    names = [f"b{i}" for i in range(10)]
    others = [b for b in names if b != "b0"]
    with_it = [sorted(s + ["b0"]) for s in _mod.subsets(others, 7)]
    without = _mod.subsets(others, 8)
    assert len(with_it) == 36 and all("b0" in s for s in with_it)
    assert len(without) == 9 and all("b0" not in s for s in without)


def test_one_book_control_refuses_a_culprit_that_is_not_on_the_panel():
    with pytest.raises(ValueError, match="refusing a control against nothing"):
        _mod.one_book_control(_panel(4), culprit="not_a_book")


def test_substitutability_scan_covers_every_book_once():
    """The scan's whole content is "is it THAT book or A book like it" — it must ask about all."""
    books = _panel(4, n=160)
    rows = _mod.substitutability_scan(books, d_start=_CANON[0], d_full=_CANON[1])
    assert sorted(r[0] for r in rows) == sorted(books)


# ── Panel liveness: the finding that reframes #68 / #69 / #71 ───────────────

def _synthetic_date(i: int) -> str:
    """An index-addressed date. Monotone in `i`, and no literal calendar date anywhere.

    The panel loader sorts and slices by this string, so it has to look like a date and it has
    to increase with the index — but WHICH date is irrelevant to every assertion here. Deriving
    it keeps this file out of the frozen-date class (`.claude/rules/deployment.md`, preference
    #2: relative fixtures), which is not hypothetical — the ratchet flagged this file on its
    first full run over a single quoted date in one forward-block row.
    """
    return f"{2000 + i // 365:04d}-{(i % 365) // 31 + 1:02d}-{(i % 31) + 1:02d}"


def _write_panel(
    tmp_path: Path,
    books: dict,
    killed_from: dict | None = None,
    killed_days: dict | None = None,
    feedless_from: dict | None = None,
    mtm_at_kill: dict | None = None,
) -> Path:
    """Write a synthetic panel in the real on-disk shape (phase=backtest jsonl rows).

    `killed_from` is the monotone "killed at index N and never again alive" case. `killed_days`
    (explicit index set) exists so a re-arm — the transition the real panel has ZERO of — can be
    written down at all; a helper that can only express monotone kills makes `rearms` untestable
    and the field would be an ornament.

    `feedless_from` / `mtm_at_kill` write the two row fields that separate "the feed stopped"
    from "the book actually fell": a repair aimed at feeds reaches only the former.
    """
    killed_from = killed_from or {}
    killed_days = killed_days or {}
    feedless_from = feedless_from or {}
    mtm_at_kill = mtm_at_kill or {}
    root = tmp_path / "panel"
    root.mkdir(exist_ok=True)
    for name, eq in books.items():
        d = root / name
        d.mkdir(exist_ok=True)
        explicit = killed_days.get(name)
        first_feedless = feedless_from.get(name)
        lines = []
        for i, v in enumerate(eq):
            killed = (i in explicit) if explicit is not None else i >= killed_from.get(name, len(eq) + 1)
            row = {
                "date": _synthetic_date(i), "equity_usd": v, "phase": "backtest",
                "killed": killed,
            }
            row["mtm_source"] = (
                None if first_feedless is not None and i >= first_feedless
                else "realized_backtest_series"
            )
            if name in mtm_at_kill and killed:
                row["mtm_today_pct"] = mtm_at_kill[name]
            lines.append(json.dumps(row))
        (d / "realized_series.jsonl").write_text("\n".join(lines) + "\n")
    return root


def test_panel_liveness_flags_a_book_killed_and_frozen(tmp_path):
    """The 2024 kills, replayed: a book frozen after its kill must be reported as such.

    Positive control for the finding itself. Without this, `panel_liveness` could report the
    frozen book as merely "quiet" and the 40%-dead-capital conclusion would rest on an
    ad-hoc command nobody re-runs.
    """
    frozen = _drift(200)[:60] + [_drift(200)[59]] * 140
    panel = _write_panel(tmp_path, {"live": _sawtooth(200), "dead": frozen},
                         killed_from={"dead": 60})
    rows = {l.book: l for l in _mod.panel_liveness(panel)}
    assert rows["dead"].killed_days == 140
    assert rows["dead"].moving_days < 60, "a frozen book stops moving after its kill"
    assert rows["live"].killed_days == 0
    assert rows["live"].sd_pct > rows["dead"].sd_pct


def test_liveness_separates_a_feedless_kill_from_a_drawdown_kill(tmp_path):
    """«Мертва» и «мертва ПОЧЕМУ» — разные замеры, и только второй говорит, достанет ли починка.

    Обе книги здесь одинаково мертвы по старым полям (`killed_days`), поэтому на них старый
    замер не различает НИЧЕГО. Различают новые: у одной после kill'а фида нет ни дня, у другой
    он приходил каждый день. Починка фидов достаёт до первой и не сдвигает вторую — и это
    ровно то различие, на котором стоит решение владельца own-54 (вариант 1).
    """
    flat = _drift(200)[:60] + [_drift(200)[59]] * 140
    panel = _write_panel(
        tmp_path,
        {"feedless": flat, "fell": flat, "live": _sawtooth(200)},
        killed_from={"feedless": 60, "fell": 60},
        feedless_from={"feedless": 60},
        mtm_at_kill={"fell": -19.58},
    )
    rows = {l.book: l for l in _mod.panel_liveness(panel)}

    assert rows["feedless"].killed_days == rows["fell"].killed_days, (
        "положительный контроль: по СТАРЫМ полям обе книги неразличимы"
    )
    assert rows["feedless"].fed_days_after_kill == 0
    assert rows["feedless"].feedless_days_after_kill == 140
    assert rows["fell"].feedless_days_after_kill == 0
    assert rows["fell"].fed_days_after_kill == 140
    assert rows["fell"].kill_mtm_pct == pytest.approx(-19.58)
    assert rows["live"].fed_days_after_kill == 0, "живая книга не имеет пост-kill окна вовсе"
    assert rows["live"].kill_mtm_pct is None


def test_liveness_counts_a_rearm_and_not_merely_the_kill(tmp_path):
    """Возврат в строй — отдельное событие, и панель обязана уметь его показать.

    На настоящей панели возвратов РОВНО НОЛЬ, поэтому поле, проверенное только на ней, было бы
    неотличимо от намертво зашитого нуля. Здесь книга убита дважды и дважды возвращается —
    считаются переходы killed→живая, а не дни и не число kill'ов.
    """
    eq = _drift(120)
    panel = _write_panel(
        tmp_path,
        {"comeback": eq, "never": eq},
        killed_days={"comeback": set(range(30, 40)) | set(range(70, 80)),
                     "never": set(range(30, 120))},
    )
    rows = {l.book: l for l in _mod.panel_liveness(panel)}
    assert rows["comeback"].rearms == 2
    assert rows["never"].rearms == 0
    assert rows["comeback"].killed_days == 20
    assert rows["never"].killed_days == 90, "контроль: убиты обе, различие ровно в возвратах"


def test_panel_liveness_sees_only_the_backtest_block(tmp_path):
    """The forward block re-anchors at ~$100k; counting it fabricates a jump (fixed 2026-08-02).

    Guards the same seam #71 named in its caveat (b), on the new code path.
    """
    panel = _write_panel(tmp_path, {"b": _drift(120)})
    f = panel / "b" / "realized_series.jsonl"
    rows = f.read_text().rstrip().split("\n")
    # The forward row's date is DERIVED from the same synthetic axis as the backtest rows
    # (index 500, past the 120 written above) rather than written as a literal. A quoted
    # calendar date here would be a time bomb of exactly the class
    # `test_frozen_date_ratchet.py` exists to keep from growing — it caught this one.
    rows.append(json.dumps({"date": _synthetic_date(500), "equity_usd": 100_000.0,
                            "phase": "forward", "killed": False}))
    f.write_text("\n".join(rows) + "\n")
    only_bt = _mod.panel_liveness(panel)
    assert len(only_bt) == 1
    assert only_bt[0].days == 119, "the forward row must not extend the backtest series"


def test_panel_liveness_reads_rows_through_the_loader_not_a_second_reader(tmp_path):
    """A liveness audit that parsed the file itself could disagree with what the ladder loaded.

    Comparing a COPY of the data to the data is green through any drift between them.
    """
    panel = _write_panel(tmp_path, {"b": _drift(120)})
    direct = _mod.PRP.RPE.backtest_block(_mod.PRP.RPE._read_rows(panel / "b" / "realized_series.jsonl"))
    assert _mod.RPE_backtest_rows(panel / "b" / "realized_series.jsonl") == direct


# ── Panel-gated: the ladder ends must match #71's PUBLISHED numbers ─────────

@pytest.mark.skipif(
    not (_PANEL / "susde_dn" / "realized_series.jsonl").exists(),
    reason=(
        "aggressive-lab panel is not git-tracked, so CI has no copy of it; "
        "set SPA_PANEL_DIR to the prod tree's data/aggressive_lab to run this locally"
    ),
)
def test_ladder_ends_reproduce_the_published_idea71_cells():
    """#73's ladder, at n=1 and n=10 on the canonical split, IS #71's published table.

    These four numbers are copied from registry entry #71 (canonical split 2025-06-30, wedge
    2%-6%, 96bp RT). If the ladder ever stops reproducing them, #73 is measuring something else
    and its "middle filled in" framing is false.
    """
    axis, books = _mod.PRP.load_books(_PANEL)
    _, train = _mod.PRP.slice_books(axis, books, None, _mod.SPLITS[0])
    _, test = _mod.PRP.slice_books(axis, books, _mod.SPLITS[0], None)
    names = sorted(test)

    per_book = _mod.run_rung(test, [[b] for b in names], d_start=0.02, d_full=0.06)
    assert per_book.apy * 100 == pytest.approx(11.15, abs=0.02)
    assert per_book.maxdd * 100 == pytest.approx(-0.35, abs=0.02)
    assert per_book.net_apy * 100 == pytest.approx(10.43, abs=0.02)

    whole = _mod.run_rung(test, [names], d_start=0.02, d_full=0.06)
    assert whole.apy * 100 == pytest.approx(5.34, abs=0.02)
    assert whole.net_apy * 100 == pytest.approx(-0.56, abs=0.02)
    assert whole.cost_bp_yr == pytest.approx(592, abs=2.0)
    assert train  # the causal arm's only input; asserted non-empty so a silent [] cannot pass


@pytest.mark.skipif(
    not (_PANEL / "susde_dn" / "realized_series.jsonl").exists(),
    reason="aggressive-lab panel is not git-tracked; set SPA_PANEL_DIR to run this locally",
)
def test_removing_the_loud_book_makes_the_aggregate_wedge_inert_not_cheaper():
    """#73's decisive control, pinned: without eth_directional the wedge never ARMS.

    "Cheaper" and "inert" are different verdicts. Cheaper would mean the ladder is a law about
    aggregation; inert means it is a statement about one book, and that is what goes in the
    registry.
    """
    axis, books = _mod.PRP.load_books(_PANEL)
    _, test = _mod.PRP.slice_books(axis, books, _mod.SPLITS[0], None)
    without = {b: eq for b, eq in test.items() if b != "eth_directional"}
    rung = _mod.run_rung(without, [sorted(without)], d_start=0.02, d_full=0.06)
    assert rung.band_frac == 0.0, "the aggregate never reaches the wedge's d_start at all"
    assert rung.cost_bp_yr == pytest.approx(0.0, abs=1e-9)

    with_it = _mod.run_rung(test, [sorted(test)], d_start=0.02, d_full=0.06)
    assert with_it.band_frac > 0.40, "with it, the aggregate lives INSIDE the wedge"


@pytest.mark.skipif(
    not (_PANEL / "susde_dn" / "realized_series.jsonl").exists(),
    reason="aggressive-lab panel is not git-tracked; set SPA_PANEL_DIR to run this locally",
)
def test_four_panel_books_are_killed_and_frozen():
    """The 40%-dead-capital finding, pinned against the real panel.

    Named books, not a count: if the lab ever respawns them, this goes red and the registry
    caveat on #68/#69/#71/#73 has to be revisited rather than silently outliving its cause.
    """
    rows = {l.book: l for l in _mod.panel_liveness(_PANEL)}
    dead = {b for b, l in rows.items() if l.killed_days > l.days * 0.5}
    assert dead == {"leverage_loop", "levered_restaking", "lp_eth_stable", "lrt_neutral"}
    for b in dead:
        assert rows[b].moving_days < rows[b].days * 0.2, f"{b} is carried as a frozen line"


@pytest.mark.skipif(
    not (_PANEL / "susde_dn" / "realized_series.jsonl").exists(),
    reason="aggressive-lab panel is not git-tracked; set SPA_PANEL_DIR to run this locally",
)
def test_the_accepted_feed_repair_reaches_exactly_one_of_the_four_dead_books():
    """Решение владельца own-54 (19.08, вариант 1 — «починить фиды») достаёт до ОДНОЙ книги.

    Карточка own-54 поставила диагноз «нет ключа фида» всем четырём, и порождённая задача
    `agent-ozhivit-chetyre-mertvye-knigi-paneli` чинит фиды всем четырём. Замер говорит иначе:
    трём книгам фид приходил КАЖДЫЙ день после kill'а, и убила их настоящая просадка
    (−29.7 %, −19.6 %, −5.4 % в день kill'а). Починка фидов не сдвинет их ни на день.

    Второе утверждение сильнее первого: возвратов в строй НОЛЬ у всех четырёх — у лабораторного
    kill-switch нет политики возврата, поэтому и `lp_eth_stable` с починенным фидом останется
    замороженной. То есть критерий приёмки own-54 («ноль замороженных книг») не достигается
    принятой починкой ВООБЩЕ НИ ДЛЯ ОДНОЙ книги, и это надо было сказать вслух, а не выяснить
    через полтора дня работы по фидам.

    Тест красный, если панель починят — и это правильно: тогда запись реестра и задача обязаны
    быть пересмотрены, а не тихо пережить свою причину.
    """
    rows = {l.book: l for l in _mod.panel_liveness(_PANEL)}
    dead = {b: l for b, l in rows.items() if l.killed_days > l.days * 0.5}

    feed_reachable = {b for b, l in dead.items() if l.fed_days_after_kill == 0}
    assert feed_reachable == {"lp_eth_stable"}, (
        "починка фидов достаёт ровно до тех книг, у которых после kill'а нет ни одной "
        "размеченной строки"
    )

    fell_with_a_live_feed = {b for b, l in dead.items() if l.feedless_days_after_kill == 0}
    assert fell_with_a_live_feed == {"leverage_loop", "levered_restaking", "lrt_neutral"}
    for b in fell_with_a_live_feed:
        assert dead[b].kill_mtm_pct is not None and dead[b].kill_mtm_pct < 0, (
            f"{b} убита движением вниз, а не отсутствием данных"
        )

    assert all(l.rearms == 0 for l in dead.values()), (
        "ни одна мёртвая книга ни разу не вернулась в строй — политики возврата нет"
    )
