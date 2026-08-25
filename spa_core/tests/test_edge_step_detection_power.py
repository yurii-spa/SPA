"""
spa_core/tests/test_edge_step_detection_power.py — tests for ideas #77 (SDP) and #78 (VSD).

Every test here is a POSITIVE CONTROL in the sense `.claude/rules/deployment.md` demands: it
pins a property that the 2026-08-25 R&D run actually measured, and goes RED if that property is
removed. Where a test could pass for the wrong reason, the mutation that would fool it is
asserted from the OTHER side as well (`..._negative_control`), because a check that has never
seen the failure it claims to catch is decoration.

The four load-bearing claims of #77, each with its own test:
  1. the three kill lines are DERIVED from the roster and the study REFUSES if one moves;
  2. a causal MEDIAN passes a sustained step whole; a causal MEAN divides it by k — which is
     why the choice of median is not interchangeable on a daily-move trigger;
  3. repair (B) (persistence) is STRUCTURALLY BLIND to a permanent step on a daily-move
     trigger: such a step produces exactly ONE breaching day, so requiring two never fires;
  4. the free control (raise the threshold) resolves ties toward the LOWER threshold, i.e.
     toward firing more readily — fail-CLOSED.

And the two of #78:
  5. w=1.0 is the identity (so the sweep's anchor reproduces the published panel), w=0 freezes;
  6. the placebo control exists and the loud book is separated from every other book by it.

No network. Nothing under `data/` is written — the last test pins the panel's mtimes across a
full sweep. Advisory / OUTSIDE_RISKPOLICY throughout.
"""
# FROZEN-DATE-OK: дат в этом файле нет вовсе — все ряды синтетические и позиционные (индекс дня,
# не календарь). Ни один тест не читает часы, не сравнивает с `now` и не знает понятия «протухло»,
# поэтому инъекция часов (предпочтение #1 правила) здесь нечего инъектировать.
# LLM_FORBIDDEN
from __future__ import annotations

import statistics
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import edge_step_detection_power as S  # noqa: E402
import edge_rearm_rule as RARM         # noqa: E402
import edge_pde_real_panel as PRP      # noqa: E402
from spa_core.strategy_lab.aggressive_lab import roster as RST  # noqa: E402


# ───────────────────────────── 1. the triggers come from the roster ─────────────────────────────

def test_trigger_lines_are_derived_from_the_roster_defaults():
    """The 2026-08-25 run's headline correction: the 3x liquidation line is 0.5/3^2 = 5.56 %,
    not the 8.33 % #76 printed. Both levered books' lines follow from `liq_buffer_frac = -0.5/lev`
    and `levered_move = ratio_move * lev`, so they are computed, never restated."""
    t = S._trigger_thresholds()
    assert t["depeg_from_entry_pct"] == pytest.approx(5.0)
    assert t["liq_2x_daily_move"] == pytest.approx(-0.125)
    assert t["liq_3x_daily_move"] == pytest.approx(-0.5 / 9.0)
    # the number #76 printed for the 3x line is NOT the roster's line — this is the correction
    assert abs(t["liq_3x_daily_move"]) < 0.0833


def test_study_refuses_when_a_roster_default_moves(monkeypatch):
    """POSITIVE CONTROL for the fail-CLOSED guard: change the lab's depeg threshold and the
    study must refuse rather than quietly measure a trigger the lab no longer has."""
    original = RST.LrtNeutral.init

    def patched(self, capital, config):
        original(self, capital, dict(config or {}, depeg_kill_pct=7.5))

    monkeypatch.setattr(RST.LrtNeutral, "init", patched)
    with pytest.raises(RuntimeError, match="roster default moved"):
        S._trigger_thresholds()


# ───────────────────── 2. median vs mean — the distinction the study rests on ─────────────────────

def _clean_step(n_pre: int, n_post: int, step_pct: float) -> list:
    return [1.0] * n_pre + [1.0 - step_pct / 100.0] * n_post


def test_causal_median_passes_a_sustained_step_WHOLE_on_one_day():
    """With no noise, median-5 shows the full step as a single day-over-day move — delayed, not
    shrunk. This is why a daily-move liquidation trigger survives repair (A) at all."""
    vals = _clean_step(10, 10, 12.5)
    med = S.transform(vals, "median5")
    worst = S.max_daily_drop(med, 0, len(med) - 1)
    assert worst == pytest.approx(0.125, abs=1e-9)


def test_causal_mean_divides_the_same_step_by_k_negative_control():
    """The mutation that would make the median look interchangeable: swap it for a mean. The
    same step now appears as step/k per day and a 12.5 % line is never reached — which is
    exactly the 0.00 % true-positive column the mean scored on both levered triggers."""
    vals = _clean_step(10, 10, 12.5)
    mean = S.transform(vals, "mean5")
    worst = S.max_daily_drop(mean, 0, len(mean) - 1)
    # step/k, up to the small compounding of a FRACTIONAL move off a falling base
    assert worst == pytest.approx(0.125 / 5, rel=0.15)
    assert worst < 0.125 / 4


def test_causal_median_list_agrees_with_the_dict_form_used_by_76():
    """Parity with #76's own implementation. A second, silently different median would make
    every comparison in this entry to #76's numbers meaningless."""
    vals = [1.0, 0.9, 1.1, 0.8, 1.2, 1.0, 0.7, 1.3]
    dates = [f"2024-01-{i + 1:02d}" for i in range(len(vals))]
    dict_form = RARM.causal_median({d: v for d, v in zip(dates, vals)}, 5)
    list_form = S.causal_median_list(vals, 5)
    assert [dict_form[d] for d in dates] == pytest.approx(list_form)


def test_causal_median_is_causal_a_future_point_cannot_change_a_past_output():
    """A centred window is the standard way this repair is done wrong; it would be lookahead."""
    base = [1.0, 0.98, 1.02, 0.99, 1.01, 1.00, 0.97]
    out_a = S.causal_median_list(base, 5)
    out_b = S.causal_median_list(base[:-1] + [0.10], 5)
    assert out_a[:-1] == pytest.approx(out_b[:-1])


# ───────────────── 3. repair (B) is structurally blind on a daily-move trigger ─────────────────

def test_persistence_never_fires_on_a_permanent_step_on_a_daily_move_trigger():
    """POSITIVE CONTROL for #77's hardest finding. A permanent step produces exactly ONE
    breaching day-over-day move; the day after, the series is flat again at the new level. So a
    rule demanding two CONSECUTIVE breaches can never fire on a real depeg — it is fail-OPEN on
    the very event it guards, which is strictly worse than #76's 'treats the symptom'."""
    vals = _clean_step(10, 10, 20.0)
    assert S.fires_daily(vals, move_thr=-0.125, persist=1) is not None
    assert S.fires_daily(vals, move_thr=-0.125, persist=2) is None
    assert S.fires_daily(vals, move_thr=-0.125, persist=3) is None


def test_persistence_DOES_fire_on_a_level_trigger_negative_control():
    """The other side, and the reason the entry says the two trigger SHAPES need different
    repairs rather than 'persistence is bad': against a level-vs-entry test the same permanent
    step keeps breaching every day, so persistence works there and scored 96 % on the panel."""
    vals = _clean_step(10, 10, 20.0)
    assert S.fires_level(vals, thr_pct=5.0, persist=3) is not None


def test_persistence_kills_a_one_day_spike_which_is_what_it_is_for():
    vals = [1.0] * 10 + [0.70] + [1.0] * 10
    assert S.fires_daily(vals, move_thr=-0.125, persist=1) is not None
    assert S.fires_daily(vals, move_thr=-0.125, persist=2) is None


# ───────────────────────────── injection semantics ─────────────────────────────

def test_permanent_injection_holds_and_transient_recovers_exactly():
    vals = [1.0] * 20
    perm = S.inject_step(vals, 10, 8.0, None)
    assert perm[9] == pytest.approx(1.0) and perm[19] == pytest.approx(0.92)
    trans = S.inject_step(vals, 10, 8.0, 3)
    assert trans[10:13] == pytest.approx([0.92] * 3)
    assert trans[13] == pytest.approx(1.0)


def test_injection_is_multiplicative_so_the_event_is_the_same_size_anywhere():
    vals = [1.0, 2.0, 4.0] * 10
    inj = S.inject_step(vals, 5, 10.0, None)
    for i in range(5, len(vals)):
        assert inj[i] / vals[i] == pytest.approx(0.9)


def test_level_trigger_fires_on_a_one_day_dip_raw_and_not_under_repair_A():
    """POSITIVE CONTROL for the measured false-positive gap on the depeg trigger (raw 11.69 %
    against median5 1.30 %): the artifact is a ONE-DAY round trip, and repair (A) removes it
    from the level the trigger reads while leaving a genuine state change intact."""
    vals = [1.00] * 30
    dipped = S.inject_step(vals, 20, 10.0, 1)                  # one-day print, fully recovered
    assert S.fires_level(dipped, thr_pct=5.0) == 20            # raw kills on the artifact
    assert S.fires_level(S.transform(dipped, "median5"), thr_pct=5.0) is None
    # ...and a REAL (permanent) step of the same size still kills under repair (A), later
    stepped = S.inject_step(vals, 20, 10.0, None)
    fired = S.fires_level(S.transform(stepped, "median5"), thr_pct=5.0)
    assert fired is not None and fired > 20                    # detected, at a cost in days


def test_level_trigger_anchors_on_the_series_it_is_handed_at_start_idx():
    """A lab running repair (A) would anchor its entry on the repaired series too, so the
    trigger must read its anchor out of the values it is given — never out of a second source."""
    vals = [1.00] * 10 + [0.90] * 20
    assert S.fires_level(vals, thr_pct=5.0, start_idx=0) == 10   # anchored at 1.00: 10 % drop
    assert S.fires_level(vals, thr_pct=5.0, start_idx=15) is None  # anchored at 0.90: no drop


# ───────────────── 4. the free control resolves ties toward firing (fail-CLOSED) ─────────────────

def test_matched_threshold_control_picks_the_LOWEST_threshold_meeting_the_target():
    """A genuine tie is constructed: several thresholds in the grid reach the same FP rate. The
    rule must take the lowest of them (fire more readily), never the flattering highest."""
    n = 400
    ser = {f"2024-{1 + i // 300:02d}-{1 + i % 28:02d}-{i}": 1.0 for i in range(n)}
    series = {"ratio": {S.DEPEG_SYMBOL: ser}}
    res = S.matched_threshold_control(series, 0.0, stride=40)
    assert res["matched"] is not None
    tied = [r["thr_pct"] for r in res["sweep"] if r["fp_rate"] <= 1e-12]
    assert len(tied) > 1, "no tie was constructed — the test would pass vacuously"
    assert res["matched"]["thr_pct"] == min(tied)


def test_matched_threshold_control_returns_none_when_the_target_is_unreachable():
    ser = {f"d{i:04d}": 1.0 for i in range(400)}
    res = S.matched_threshold_control({"ratio": {S.DEPEG_SYMBOL: ser}}, -1.0, stride=40)
    assert res["matched"] is None


# ───────────────────────────── 5. #78 sweep anchors ─────────────────────────────

def _toy_panel():
    axis = [f"d{i:04d}" for i in range(200)]
    books = {}
    for b, amp in (("loud", 0.03), ("quiet_a", 0.002), ("quiet_b", 0.002)):
        eq = [PRP.INITIAL]
        for i in range(len(axis)):
            eq.append(eq[-1] * (1.0 + amp * (1 if i % 7 else -6)))
        books[b] = eq
    return axis, books


def test_scale_book_returns_w1_is_the_identity():
    """The sweep's anchor. A w=1.0 point that did not reproduce the published panel would mean
    the sweep was measuring its own arithmetic — which is why #78 reports that w=1.0 gives back
    #71's +21.43 and w=0 gives back #76's leave-one-out +7.21."""
    _, books = _toy_panel()
    out = S.scale_book_returns(books, "loud", 1.0)
    assert out["loud"] == pytest.approx(books["loud"])


def test_scale_book_returns_w0_freezes_the_book_at_flat():
    _, books = _toy_panel()
    out = S.scale_book_returns(books, "loud", 0.0)
    assert out["loud"] == pytest.approx([PRP.INITIAL] * len(books["loud"]))
    assert out["quiet_a"] == pytest.approx(books["quiet_a"])   # nothing else moved


def test_scale_book_returns_refuses_an_unknown_book():
    _, books = _toy_panel()
    with pytest.raises(KeyError):
        S.scale_book_returns(books, "not_a_book", 0.5)


def test_variance_shares_sum_to_one_and_name_the_loud_book():
    _, books = _toy_panel()
    sh = S.variance_shares(books)
    assert sum(sh.values()) == pytest.approx(1.0)
    assert max(sh, key=lambda k: sh[k]) == "loud"


def test_variance_share_falls_monotonically_as_the_book_is_de_levered():
    _, books = _toy_panel()
    prev = 1.1
    for w in (1.0, 0.5, 0.2, 0.0):
        sh = S.variance_shares(S.scale_book_returns(books, "loud", w))["loud"]
        assert sh < prev
        prev = sh


# ───────────────────────────── 6. the placebo control must stay ─────────────────────────────

def test_placebo_control_covers_every_book_and_reports_a_baseline():
    """#74 was killed by a FREE control that a later edit could have quietly dropped; the guard
    against that is a test which reddens if the control leaves the report. Same here: the #78
    sweep means nothing without the row that de-levers a book which should not matter."""
    axis, books = _toy_panel()
    pl = S.run_idea78_placebo(axis, books, split="d0100", w_low=0.1)
    assert set(pl["rows"]) == set(books)
    assert "baseline" in pl
    for r in pl["rows"].values():
        assert "delta_vs_baseline" in r


def test_placebo_separates_the_loud_book_from_the_quiet_ones():
    """POSITIVE CONTROL replaying the measured result: de-levering the loud book moves the
    overlay's edge, de-levering a quiet one barely does. On the real panel the gap was
    -20.30 against -8.77 for the next book and 0.00 for all four frozen ones."""
    axis, books = _toy_panel()
    pl = S.run_idea78_placebo(axis, books, split="d0100", w_low=0.1)
    loud = abs(pl["rows"]["loud"]["delta_vs_baseline"])
    quiet = max(abs(pl["rows"][b]["delta_vs_baseline"]) for b in ("quiet_a", "quiet_b"))
    assert loud > quiet


# ───────────────────────────── the panel stays read-only ─────────────────────────────

def test_the_study_writes_nothing_into_the_panel():
    """The panel on disk is the shared measuring stick of thirteen registry entries. #75 pinned
    this the same way after a run that could have rewritten it."""
    panel_dir = PRP.PANEL_DIR
    if not panel_dir.exists():
        pytest.skip(f"panel absent at {panel_dir} (worktree) — nothing to protect here")
    before = {p: p.stat().st_mtime_ns for p in sorted(panel_dir.rglob("*")) if p.is_file()}
    axis, books = PRP.load_books()
    S.run_idea78(axis, books, weights=(1.0, 0.5), splits=PRP.SPLITS[:1])
    S.run_idea78_placebo(axis, books, w_low=0.5)
    after = {p: p.stat().st_mtime_ns for p in sorted(panel_dir.rglob("*")) if p.is_file()}
    assert before == after, "the study touched data/aggressive_lab — it must be READ-ONLY"


def test_no_artifact_path_in_this_study_points_under_data():
    """The feed cache and the JSON report both live in /tmp by construction."""
    assert str(RARM.DEFAULT_FEED_CACHE).startswith("/tmp")
    assert not str(RARM.DEFAULT_FEED_CACHE).startswith(str(ROOT / "data"))


# ───────────── the survival conditioning, which decides every rate in the entry ─────────────

def _flat_series(n: int, *, dip_at: int | None = None, dip_pct: float = 30.0) -> dict:
    ser = {f"d{i:04d}": 1.0 for i in range(n)}
    if dip_at is not None:
        ser[f"d{dip_at:04d}"] = 1.0 - dip_pct / 100.0
    return ser


def test_an_onset_whose_book_was_already_killed_is_excluded_from_BOTH_rates():
    """POSITIVE CONTROL for the conditioning, and the reason it is not a denominator trick.

    The lab's kill is ABSORBING, so an onset at which the detector had already fired on
    pre-onset noise is not a missed detection — the book was not there to detect anything.
    Counting it as a miss would deflate the noisiest detector's TP while ALSO deflating its FP:
    it would flatter and punish `raw` at once and no reader could tell which. The excluded
    onsets are therefore published as `pre_onset_kill_rate` — on the real depeg trigger that
    rate is 41.56 % for `raw` against 6.49 % for median5, which IS the finding, not a footnote.
    """
    n = S.WARMUP + S.HORIZON + 20
    # a 30 % one-day dip 5 days BEFORE the only onset: raw dies there, median5 does not
    onset = S.WARMUP
    series = {"ratio": {S.DEPEG_SYMBOL: _flat_series(n, dip_at=onset - 5)}}
    res = S.run_idea77(series, stride=n, steps=(20.0,), durations=(None,))
    raw = res["cells"]["depeg"]["raw"]
    med = res["cells"]["depeg"]["median5"]
    assert raw["pre_onset_kill_rate"] == pytest.approx(1.0)   # every onset already dead
    assert raw["n_alive"] == 0
    assert raw["fp_rate"] == 0.0 and raw["tp"]["S20_Dperm"]["rate"] == 0.0
    assert med["pre_onset_kill_rate"] == pytest.approx(0.0)   # the median absorbed the dip
    assert med["n_alive"] == raw["n_onsets"]
    assert med["tp"]["S20_Dperm"]["rate"] == pytest.approx(1.0)


def test_liveness_is_decided_by_the_uninjected_run_so_both_arms_share_it():
    """The step starts AT the onset, so the pre-onset segment is identical with and without
    injection. If liveness were decided per-arm the injected arm could have a different
    denominator and TP/FP would no longer be comparable."""
    n = S.WARMUP + S.HORIZON + 20
    series = {"ratio": {S.DEPEG_SYMBOL: _flat_series(n)}}
    res = S.run_idea77(series, stride=n, steps=(30.0,), durations=(None,))
    for label, _, _ in S.DETECTORS:
        r = res["cells"]["depeg"][label]
        assert r["n_alive"] == r["n_onsets"], label


def test_rates_are_divided_by_the_SURVIVORS_not_by_every_onset():
    """POSITIVE CONTROL that separates the two ways of writing this down. A panel is built where
    some onsets are already dead and the survivors all fire in-window, so `fp/n_alive` (1.00)
    and `fp/n_onsets` (0.50) are numerically different. Dividing by every onset would report a
    noisy detector as half as noisy as it is — the flattering version of exactly the number
    this entry publishes."""
    stride = 60                                   # > warmup+horizon, so windows never overlap
    onsets = [S.WARMUP + k * stride for k in range(4)]
    n = onsets[-1] + S.HORIZON + 5
    ser = {f"d{i:04d}": 1.0 for i in range(n)}
    for o in onsets[:2]:
        ser[f"d{o - 5:04d}"] = 0.70               # dies BEFORE the event → excluded
    for o in onsets[2:]:
        ser[f"d{o + 3:04d}"] = 0.70               # fires INSIDE the window → a false positive
    res = S.run_idea77({"ratio": {S.DEPEG_SYMBOL: ser}}, stride=stride,
                       steps=(20.0,), durations=(None,))
    raw = res["cells"]["depeg"]["raw"]
    assert raw["n_onsets"] == 4 and raw["n_alive"] == 2, (raw["n_onsets"], raw["n_alive"])
    assert raw["fp"] == 2
    assert raw["fp_rate"] == pytest.approx(1.0)               # 2/2, the survivors
    assert raw["fp_rate"] != pytest.approx(raw["fp"] / raw["n_onsets"])   # not 2/4
    assert raw["pre_onset_kill_rate"] == pytest.approx(0.5)
