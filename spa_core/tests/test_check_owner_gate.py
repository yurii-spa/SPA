"""Regression coverage for ``scripts/check_owner_gate.py`` — the fail-CLOSED OWNER-GATE
interlock that blocks the autonomous orchestrator from auto-shipping OWNER-GATED site
changes to live (Cloudflare Pages builds ``landing/`` on every push to main).

The site is push==live, and the autonomous auto-ship path (ADR-OWN-2026-07-autoship,
``scripts/safe_site_push.py`` → ``push_to_github*.py`` interlock) trusts THIS module to
decide "safe to ship" vs "route to an owner card". A silent regression here is a
*fail-OPEN*: an owner-gated change (a baked yield number, a re-branded "SPA" expansion,
a solicitation line, an edited disclaimer, a removed honesty token) would auto-ship to
production without the owner ever seeing it — exactly the class of mistake invariant #8
and the site-copy rule exist to prevent. On origin the module had **0 dedicated tests**.

This file pins the detection substrate end to end:
  * ``_changed_paths_and_hunks`` — diff-hunk parsing (the +/- line-number bookkeeping).
  * ``_scan_free_text`` — Class A (solicitation) / B (baked yield number) / C ("SPA"
    expansion) / D (legal-path) / E (honesty-token removal), and crucially the **per-span
    dynamic-window fail-OPEN regression**: a distant ``{snap.x}`` / ``props.`` token must
    NOT suppress a baked ``30% net APY`` on the same line (an earlier line-level suppressor
    did — a fail-open that shipped a hardcoded number).
  * ``_tier_bands_violations`` / ``_track_snapshot_violations`` — structured JSON field-diff.
  * ``_snapshot_is_custodian_equivalent`` — the not-forgeable custodian exemption.
  * ``_approved_scope`` + ``check_owner_gate`` end to end — owner-approval bypass only via
    a real ``owner-done`` card whose ``approves:`` scope covers the violation.

The module is a script (``scripts/`` has no ``__init__.py``), so — exactly like
``test_orchestrator_queue_cli.py`` / ``test_build_agent_registry.py`` — we load it by file
path via ``importlib.util.spec_from_file_location``.

Hermetic & offline: the free-text / field-diff detectors are pure functions (no git); the
end-to-end cases build a throwaway ``git init`` repo under ``tmp_path`` and drive git-range
mode, so nothing touches the real repo, network, ``origin/main``, or ``data/``. The
owner-approval bypass monkeypatches ``spa_core.owner_queue.queue.list_cards`` so no card
store is read and no ``owner-done`` is ever written (invariant #14). Tests only — the module
is NOT modified (invariant #16).

# FROZEN-DATE-OK: historical-incident — the literal dates below (canon as_of 2026-07-04 vs
# committed snapshot as_of 2026-08-19) ARE the subject: they reproduce the measured 2026-08-19
# finding that origin's data/ canon is frozen far behind the live track, which is precisely why
# the custodian exemption is not computable in CI. Preference #3 of .claude/rules/deployment.md.
# These dates cannot rot with the calendar: NOTHING here compares them to the clock — there is no
# datetime.now() in this file. Every date is compared only against another date supplied by the
# same test (a lexical as_of ordering, or a bar date re-derived from the fixture's own bars), so
# both sides are pinned by construction. Injecting a clock (preference #1) would add a parameter
# that no code path under test reads.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[2]
_MOD = _REPO / "scripts" / "check_owner_gate.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_owner_gate_mod", _MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load()

_TIER_BANDS = "landing/src/lib/tier_bands.json"
_TRACK_SNAPSHOT = "landing/src/data/track_snapshot.json"


# ── _changed_paths_and_hunks ────────────────────────────────────────────────
def test_hunk_parse_tracks_add_and_remove_line_numbers():
    diff = (
        "diff --git a/landing/x.astro b/landing/x.astro\n"
        "--- a/landing/x.astro\n"
        "+++ b/landing/x.astro\n"
        "@@ -1,0 +2,1 @@\n"
        "+added line\n"
        "@@ -5,1 +6,0 @@\n"
        "-removed line\n"
    )
    paths, hunks = G._changed_paths_and_hunks(diff)
    assert paths == ["landing/x.astro"]
    assert hunks["landing/x.astro"] == [
        ("+", 2, "added line"),
        ("-", 5, "removed line"),
    ]


def test_hunk_parse_ignores_dev_null_target():
    # A pure deletion whose +++ target is /dev/null must not register a path.
    diff = (
        "diff --git a/landing/gone.astro b/landing/gone.astro\n"
        "--- a/landing/gone.astro\n"
        "+++ b//dev/null\n"
        "@@ -1,1 +0,0 @@\n"
        "-was here\n"
    )
    paths, hunks = G._changed_paths_and_hunks(diff)
    assert paths == []
    assert hunks == {}


# ── _scan_free_text: Class A (solicitation) ─────────────────────────────────
@pytest.mark.parametrize(
    "text",
    [
        "Minimum investment is $10,000 to start earning",
        "Withdrawals within 3 days, no lock-up",
        "guaranteed returns of course",
        "Минимальная сумма вклада — 10 000 USDC",
        "вывод в течение 5 дней без блокировки",
        "гарантированный доход каждый месяц",
    ],
)
def test_class_a_solicitation_added_gates_en_and_ru(text):
    v = G._scan_free_text("landing/src/pages/offer.astro", [("+", 3, text)])
    assert [x["klass"] for x in v] == ["A"]
    assert v[0]["rule"] == "solicitation"


def test_class_a_only_scans_added_lines():
    # Removing a solicitation phrase is a de-risking edit → must NOT gate.
    text = "Minimum investment is $10,000"
    assert G._scan_free_text("landing/src/pages/offer.astro", [("-", 3, text)]) == []


# ── _scan_free_text: Class B (baked yield number) + dynamic window ──────────
def test_class_b_baked_yield_number_gates():
    v = G._scan_free_text(
        "landing/src/pages/index.astro", [("+", 10, "Historically up to 30% net APY")]
    )
    assert [x["klass"] for x in v] == ["B"]
    assert v[0]["rule"] == "yield.number.literal"


def test_class_b_adjacent_dynamic_token_suppresses():
    # A dynamic read WITHIN the span window ({snap.x} right next to the literal) is exempt.
    text = "apy: 5%{snap.paper_apy_pct}"
    assert G._scan_free_text("landing/src/pages/index.astro", [("+", 10, text)]) == []


def test_class_b_distant_dynamic_token_does_not_suppress_failopen_regression():
    # THE fail-OPEN regression: a dynamic token far from the baked literal must NOT
    # suppress it. An earlier line-level suppressor let this ship a hardcoded number.
    text = "{snap.paper_apy_pct} shown above .................... marketed apy 30% here"
    v = G._scan_free_text("landing/src/pages/index.astro", [("+", 10, text)])
    assert [x["klass"] for x in v] == ["B"], "distant dynamic token wrongly suppressed a baked number"


def test_class_b_one_violation_per_line_even_with_two_numbers():
    text = "up to 12% net apy and also 30% net apy"
    v = G._scan_free_text("landing/src/pages/index.astro", [("+", 10, text)])
    assert len(v) == 1 and v[0]["klass"] == "B"


# ── _scan_free_text: Class C ("SPA" expansion) ──────────────────────────────
def test_class_c_noncanon_spa_expansion_gates():
    v = G._scan_free_text(
        "landing/src/pages/about.astro", [("+", 4, "SPA — Super Passive Automaton")]
    )
    assert [x["klass"] for x in v] == ["C"]
    assert v[0]["rule"] == "spa.expansion"


def test_class_c_canonical_spa_expansion_is_exempt():
    v = G._scan_free_text(
        "landing/src/pages/about.astro", [("+", 4, "SPA — Smart Passive Aggregator")]
    )
    assert v == []


# ── _scan_free_text: Class D (legal path) ───────────────────────────────────
def test_class_d_legal_path_gates_any_change_both_signs():
    legal = "landing/src/pages/disclaimer.astro"
    assert legal in G._LEGAL_PATHS
    v = G._scan_free_text(legal, [("+", 1, "This is not investment advice."),
                                  ("-", 2, "Old disclaimer wording.")])
    assert [x["klass"] for x in v] == ["D", "D"]
    assert {x["change"] for x in v} == {"added", "removed"}


def test_class_d_legal_path_short_circuits_other_classes():
    # A legal file that also contains a yield number → still exactly one D, no B.
    legal = "landing/src/pages/risk-disclosure.astro"
    v = G._scan_free_text(legal, [("+", 1, "Returns up to 30% net APY are not guaranteed")])
    assert [x["klass"] for x in v] == ["D"]


# ── _scan_free_text: Class E (honesty token removed) ────────────────────────
@pytest.mark.parametrize("text", ["L3 · verified", "refused for live", "для live отказано"])
def test_class_e_removing_honesty_token_gates(text):
    v = G._scan_free_text("landing/src/pages/tiers.astro", [("-", 7, text)])
    assert [x["klass"] for x in v] == ["E"]
    assert v[0]["change"] == "removed"


def test_class_e_adding_honesty_token_does_not_gate():
    # Only REMOVAL of an honesty token is gated; adding one is honest → no gate.
    assert G._scan_free_text("landing/src/pages/tiers.astro", [("+", 7, "L3 · verified")]) == []


# ── _tier_bands_violations (structured field-diff) ──────────────────────────
def test_tier_bands_number_change_gates_b():
    old = {"balanced": {"band_en": "up to 8%"}}
    new = {"balanced": {"band_en": "up to 12%"}}
    v = G._tier_bands_violations(old, new)
    assert [x["klass"] for x in v] == ["B"]
    assert v[0]["rule"] == "tier_bands.number"


def test_tier_bands_naming_change_gates_c():
    old = {"aggressive": {"en": "Aggressive"}}
    new = {"aggressive": {"en": "High Yield"}}
    v = G._tier_bands_violations(old, new)
    assert [x["klass"] for x in v] == ["C"]


def test_tier_bands_evidence_disappearing_gates_e_but_adding_does_not():
    # Removing/altering an existing evidence token gates; introducing one (old empty) is fine.
    removed = G._tier_bands_violations(
        {"conservative": {"evidence_en": "L4 · real"}},
        {"conservative": {"evidence_en": ""}},
    )
    assert [x["klass"] for x in removed] == ["E"]
    added = G._tier_bands_violations(
        {"conservative": {}}, {"conservative": {"evidence_en": "L4 · real"}}
    )
    assert added == []


def test_tier_bands_no_change_and_missing_tier_are_clean():
    same = {"balanced": {"band_en": "up to 8%", "en": "Balanced"}}
    assert G._tier_bands_violations(same, dict(same)) == []
    # A tier absent from NEW is skipped (no crash, no violation).
    assert G._tier_bands_violations({"balanced": {"band_en": "x"}}, {}) == []


# ── _track_snapshot_violations ──────────────────────────────────────────────
def test_track_snapshot_number_change_gates_when_not_exempt():
    v = G._track_snapshot_violations(
        {"paper_apy_pct": 3.3}, {"paper_apy_pct": 9.9}, exempt=False
    )
    assert [x["klass"] for x in v] == ["B"]


def test_track_snapshot_exempt_short_circuits():
    assert G._track_snapshot_violations(
        {"paper_apy_pct": 3.3}, {"paper_apy_pct": 9.9}, exempt=True
    ) == []


def test_track_snapshot_walks_nested_and_ignores_nonnumber_fields():
    old = {"meta": {"note": "a"}, "nested": {"nav_usd": 100}}
    new = {"meta": {"note": "b"}, "nested": {"nav_usd": 200}}
    v = G._track_snapshot_violations(old, new, exempt=False)
    # `note` is not a *_pct/_usd/number field → ignored; nested nav_usd → gated.
    assert [x["klass"] for x in v] == ["B"]
    assert "nested.nav_usd" in v[0]["matched_text"]


# ── _snapshot_is_custodian_equivalent (exemption is not forgeable) ──────────
def test_custodian_equivalence_false_without_data(tmp_path):
    # No generate_track_snapshot.py / data canon under the tmp repo → cannot regenerate.
    #
    # ИЗМЕНЁН НАМЕРЕННО 2026-08-19, цикл #299 (инв. #16 — обоснование здесь и в журнале W34).
    # Раньше тест утверждал ровно `is False`, то есть закреплял СХЛОПЫВАНИЕ «нечем измерить»
    # в «доказано нарушение» — тот самый дефект, из-за которого owner-gate краснел 106 раз
    # из 109 на собственной автоматике. Проверка не ослаблена, а УСИЛЕНА: теперь утверждаются
    # ОБА конца — трёхзначный вердикт стал `None` с НАЗВАННОЙ причиной, и при этом
    # освобождение по-прежнему НЕ выдаётся (fail-CLOSED сохранён дословно).
    verdict, reason = G._snapshot_custodian_equivalence(tmp_path)
    assert verdict is None, "«нечем измерить» обязано отличаться от «доказано нарушение»"
    assert reason and "нечем проверить" in reason
    # Поведение, ради которого тест писался, не изменилось ни на бит:
    assert G._snapshot_is_custodian_equivalent(tmp_path) is False


# ── tri-state custodian equivalence (цикл #299) ─────────────────────────────
def _fake_generator(repo: Path, snapshot: dict) -> None:
    """Put a stub generate_track_snapshot.py under `repo` whose build_snapshot() returns
    `snapshot`. Import-safe and write-free, exactly like the real one."""
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    (repo / "scripts" / "generate_track_snapshot.py").write_text(
        "import json\n"
        f"_SNAP = json.loads(r'''{json.dumps(snapshot)}''')\n"
        "def build_snapshot():\n"
        "    return dict(_SNAP)\n"
        "def _max_drawdown_pct(bars):\n"
        "    dds = [b['drawdown_pct'] for b in bars if b.get('drawdown_pct') is not None]\n"
        "    return round(min(dds), 4) if dds else None\n",
        encoding="utf-8",
    )


def _write_snapshot(repo: Path, snapshot: dict) -> None:
    p = repo / _TRACK_SNAPSHOT
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snapshot), encoding="utf-8")


def test_custodian_equivalence_proved_when_regeneration_matches(tmp_path):
    snap = {"as_of": "2026-08-19", "nav_usd": 100.0, "generated_at": "X"}
    _fake_generator(tmp_path, {**snap, "generated_at": "DIFFERENT-BUT-VOLATILE"})
    _write_snapshot(tmp_path, snap)
    verdict, reason = G._snapshot_custodian_equivalence(tmp_path)
    assert verdict is True, "volatile generated_at must not break the match"
    assert "совпала" in reason


def test_custodian_equivalence_disproved_when_regeneration_differs(tmp_path):
    # Same as_of (so the canon CAN describe the artifact) but a different number →
    # this is a real disproof, and it must stay distinguishable from "not measurable".
    _fake_generator(tmp_path, {"as_of": "2026-08-19", "nav_usd": 100.0})
    _write_snapshot(tmp_path, {"as_of": "2026-08-19", "nav_usd": 999.0})
    verdict, reason = G._snapshot_custodian_equivalence(tmp_path)
    assert verdict is False, "a hand-edited number must be PROVED not-custodian, not merely unmeasured"
    assert "nav_usd" in reason


def test_custodian_equivalence_unmeasured_when_canon_lags_the_snapshot(tmp_path):
    # The live CI case, measured 2026-08-19: origin's data/ canon is frozen at 2026-07-04
    # while the committed snapshot is 2026-08-19. Regeneration reproduces an OLDER track,
    # so the mismatch says nothing about who wrote the file → NOT MEASURABLE, not "guilty".
    _fake_generator(tmp_path, {"as_of": "2026-07-04", "nav_usd": 100.0})
    _write_snapshot(tmp_path, {"as_of": "2026-08-19", "nav_usd": 999.0})
    verdict, reason = G._snapshot_custodian_equivalence(tmp_path)
    assert verdict is None
    assert "2026-07-04" in reason and "2026-08-19" in reason, "обе стороны обязаны быть названы"
    # ...and it still grants no exemption.
    assert G._snapshot_is_custodian_equivalent(tmp_path) is False


# ── _snapshot_self_consistency — the route that IS measurable in CI ──────────
def _bars(n: int, start: float = 100000.0, step: float = 10.0) -> list[dict]:
    return [
        {"date": f"2026-06-{22 + i:02d}", "equity": start + step * i,
         "drawdown_pct": -0.01 * (i % 3), "evidenced": True}
        for i in range(n)
    ]


def _consistent_snapshot() -> dict:
    bars = _bars(5)
    end = 100500.0
    real_days = len(bars)
    apy = ((bars[-1]["equity"] / bars[0]["equity"]) ** (365.0 / real_days) - 1.0) * 100.0
    return {
        "as_of": bars[-1]["date"],
        "real_track_days": real_days,
        "paper_apy_pct": round(apy, 4),
        "max_drawdown_pct": round(min(b["drawdown_pct"] for b in bars), 4),
        "end_equity": end,
        "nav_usd": round(end, 2),
        "total_return_pct": round((end / 100000.0 - 1.0) * 100.0, 4),
        "bars": bars,
    }


def test_self_consistency_holds_for_a_custodian_shaped_snapshot():
    # Uses the REAL generator's arithmetic (repo_root=_REPO) against a synthetic snapshot —
    # no canon is read and nothing is written, so this stays hermetic.
    verdict, reason, mismatches = G._snapshot_self_consistency(_REPO, _consistent_snapshot())
    assert verdict is True, reason
    assert mismatches == []


@pytest.mark.parametrize("field,forged", [
    ("paper_apy_pct", 9.9),          # the headline yield number
    ("max_drawdown_pct", -0.001),    # the tail
    ("real_track_days", 900),        # the track length
    ("total_return_pct", 42.0),      # the return
])
def test_self_consistency_catches_a_hand_edited_number(field, forged):
    """Positive control, card step 4: a hand edit of a DISPLAYED number must be caught by
    the route that works where the canon does not (CI)."""
    snap = _consistent_snapshot()
    snap[field] = forged
    verdict, reason, mismatches = G._snapshot_self_consistency(_REPO, snap)
    assert verdict is False, f"forged {field} slipped through"
    assert [m["field"] for m in mismatches] == [field]
    assert field in reason and repr(forged) in reason


def test_self_consistency_unmeasured_without_bars():
    # "no bars" is NOT "numbers are wrong" — the same distinction, one level down.
    verdict, reason, mismatches = G._snapshot_self_consistency(_REPO, {"nav_usd": 1.0})
    assert verdict is None and "bars" in reason and mismatches == []


def test_self_consistency_unmeasured_without_a_generator(tmp_path):
    verdict, reason, _ = G._snapshot_self_consistency(tmp_path, _consistent_snapshot())
    assert verdict is None and "генератор" in reason


def test_self_consistency_does_not_claim_to_cover_packages_or_gates():
    """HONEST LIMIT, pinned so it cannot be quietly over-claimed later: packages.* and
    gates_* are NOT functions of `bars` (they come from tier1_packages.json /
    golive_status.json), so forging them is invisible here. This is exactly why the
    recommendation to the owner is 'self-consistent AND only bars-derivable fields moved',
    not 'self-consistent' alone — two of the three informative reds on origin moved
    packages.conservative.apy_pct."""
    snap = _consistent_snapshot()
    snap["packages"] = {"conservative": {"apy_pct": 99.0, "dd_pct": 0.0}}
    snap["gates_passed"] = 999
    verdict, _, mismatches = G._snapshot_self_consistency(_REPO, snap)
    assert verdict is True, "the check must not pretend to cover fields it cannot derive"
    assert mismatches == []


# ── end-to-end via a throwaway git repo (git-range mode) ────────────────────
def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "landing" / "src" / "pages").mkdir(parents=True)
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.email", "t@t.t")
    _run_git(repo, "config", "user.name", "t")
    page = repo / "landing" / "src" / "pages" / "index.astro"
    page.write_text("<h1>SPA</h1>\n<p>Automated DeFi yield.</p>\n", encoding="utf-8")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", "base")
    return repo


def test_end_to_end_clean_layout_change_is_shippable(tmp_path):
    repo = _init_repo(tmp_path)
    page = repo / "landing" / "src" / "pages" / "index.astro"
    page.write_text("<h1>SPA</h1>\n<p>Automated DeFi yield.</p>\n<style>.x{gap:8px}</style>\n",
                    encoding="utf-8")
    _run_git(repo, "commit", "-aqm", "layout: add spacing")
    rep = G.check_owner_gate(diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo)
    assert rep["ok"] is True
    assert rep["gated_count"] == 0


def test_end_to_end_baked_number_ships_via_standing_approval(tmp_path):
    """ADR-116 (решение владельца 2026-08-22, дословно «цифры и юр вопросы пока мы
    строим на сайте менялись без этого вопроса, я разрешаю»): класс B уезжает без
    карточки. НЕ молча: находка обязана лежать в standing_approved с именем ADR.
    До ADR-116 этот тест закреплял обратное (ok False) — изменение намеренное,
    обоснование в журнале W34."""
    repo = _init_repo(tmp_path)
    page = repo / "landing" / "src" / "pages" / "index.astro"
    page.write_text("<h1>SPA</h1>\n<p>Earn up to 30% net APY.</p>\n", encoding="utf-8")
    _run_git(repo, "commit", "-aqm", "copy: add number")
    rep = G.check_owner_gate(diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo)
    assert rep["ok"] is True
    assert rep["gated_count"] == 0
    assert any(v["klass"] == "B" for v in rep["standing_approved"]), \
        "находка не имеет права исчезнуть — только переехать в standing_approved"
    assert rep["standing_approved"][0]["standing_approved_by"] == "ADR-116"


def test_solicitation_still_gates_despite_standing_approval(tmp_path):
    """Обратный контроль границы ADR-116: класс A (solicitation) владелец НЕ называл —
    приглашение инвестировать до legal-clearance gated как прежде."""
    repo = _init_repo(tmp_path)
    page = repo / "landing" / "src" / "pages" / "index.astro"
    page.write_text("<h1>SPA</h1>\n<p>Minimum investment $1000, no lock-up.</p>\n",
                    encoding="utf-8")
    _run_git(repo, "commit", "-aqm", "copy: offer")
    rep = G.check_owner_gate(diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo)
    assert rep["ok"] is False
    assert any(v["klass"] == "A" for v in rep["violations"])
    assert not any(v["klass"] == "A" for v in rep["standing_approved"])


def test_legal_file_edit_ships_via_standing_approval(tmp_path):
    """Вторая половина решения владельца («юр вопросы»): класс D (legal-файлы)
    уезжает без карточки, находка видима в standing_approved."""
    repo = _init_repo(tmp_path)
    legal = repo / "landing" / "src" / "pages" / "disclaimer.astro"
    legal.parent.mkdir(parents=True, exist_ok=True)
    legal.write_text("<p>Not an offer.</p>\n", encoding="utf-8")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-qm", "legal: base")
    legal.write_text("<p>Not an offer. Research paper-track.</p>\n", encoding="utf-8")
    _run_git(repo, "commit", "-aqm", "legal: wording")
    rep = G.check_owner_gate(diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo)
    assert rep["ok"] is True
    assert any(v["klass"] == "D" for v in rep["standing_approved"])


def test_standing_approval_revocation_restores_old_gate(tmp_path, monkeypatch):
    """Мутация-якорь в обе стороны: пустой набор классов = одобрение отозвано,
    и класс B снова gated ровно как до ADR-116. Отзыв — одна константа."""
    repo = _init_repo(tmp_path)
    page = repo / "landing" / "src" / "pages" / "index.astro"
    page.write_text("<h1>SPA</h1>\n<p>Earn up to 30% net APY.</p>\n", encoding="utf-8")
    _run_git(repo, "commit", "-aqm", "copy: add number")
    monkeypatch.setattr(G, "_STANDING_APPROVED_KLASSES", frozenset())
    rep = G.check_owner_gate(diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo)
    assert rep["ok"] is False
    assert any(v["klass"] == "B" for v in rep["violations"])
    assert rep["standing_approved"] == []


def test_end_to_end_owner_approval_bypasses_matching_scope(tmp_path, monkeypatch):
    # Материал — класс A: после ADR-116 класс B уезжает по стоящему одобрению и
    # bypass-механизму нечего снимать; сам механизм по-прежнему проверяется здесь,
    # на классе, который остался запертым.
    repo = _init_repo(tmp_path)
    page = repo / "landing" / "src" / "pages" / "index.astro"
    page.write_text("<h1>SPA</h1>\n<p>Minimum investment $1000.</p>\n", encoding="utf-8")
    _run_git(repo, "commit", "-aqm", "copy: offer")

    fake_card = SimpleNamespace(
        name="own-99", id="own-99", status="owner-done",
        frontmatter={"approves": ["A"]},
    )
    from spa_core.owner_queue import queue as ownq
    monkeypatch.setattr(ownq, "list_cards", lambda **kw: [fake_card], raising=True)

    rep = G.check_owner_gate(
        diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo,
        commit_message="copy: offer\n\nOwner-Approved: own-99",
    )
    assert rep["ok"] is True, "class-A violation approved by own-99 must be bypassed"
    assert rep["gated_count"] == 0
    assert rep["approved_bypasses"] and rep["approved_bypasses"][0]["klass"] == "A"


def test_end_to_end_non_owner_done_card_does_not_bypass(tmp_path, monkeypatch):
    # A card that is NOT owner-done must never grant a bypass (owner-only, invariant #14).
    # Материал — класс A (B после ADR-116 не gated и bypass ему не нужен).
    repo = _init_repo(tmp_path)
    page = repo / "landing" / "src" / "pages" / "index.astro"
    page.write_text("<h1>SPA</h1>\n<p>Minimum investment $1000.</p>\n", encoding="utf-8")
    _run_git(repo, "commit", "-aqm", "copy: offer")

    pending = SimpleNamespace(
        name="own-99", id="own-99", status="needs-owner",
        frontmatter={"approves": ["A"]},
    )
    from spa_core.owner_queue import queue as ownq
    monkeypatch.setattr(ownq, "list_cards", lambda **kw: [pending], raising=True)

    rep = G.check_owner_gate(
        diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo,
        commit_message="copy: offer\n\nOwner-Approved: own-99",
    )
    assert rep["ok"] is False
    assert rep["approval"] is None


def test_end_to_end_no_trailer_no_bypass(tmp_path):
    # Материал — класс A (см. выше: B после ADR-116 не gated).
    repo = _init_repo(tmp_path)
    page = repo / "landing" / "src" / "pages" / "index.astro"
    page.write_text("<h1>SPA</h1>\n<p>Minimum investment $1000.</p>\n", encoding="utf-8")
    _run_git(repo, "commit", "-aqm", "copy: offer")
    rep = G.check_owner_gate(diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo,
                             commit_message="copy: offer")
    assert rep["ok"] is False
    assert rep["approval"] is None


# ── end-to-end: the unmeasured-exemption split (цикл #299) ──────────────────
def _repo_with_snapshot(tmp_path: Path, old: dict, new: dict) -> Path:
    """Throwaway repo whose HEAD~1..HEAD is exactly a track_snapshot.json number change."""
    repo = _init_repo(tmp_path)
    _write_snapshot(repo, old)
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-qm", "snapshot: base")
    _write_snapshot(repo, new)
    _run_git(repo, "commit", "-aqm",
             "chore(site-custodian): auto-deploy fresh track_snapshot after daily cycle")
    return repo


def test_unmeasured_exemption_is_named_but_the_exit_is_NOT_softened(tmp_path):
    """Pinned in both directions, обновлено ADR-116.

    A snapshot-number change whose custodian exemption cannot be proved here must be
    (a) MARKED as unmeasured — so "could not prove innocence" stops reading like
    "proved guilt" — and (b) since ADR-116 it SHIPS under the owner's standing
    approval (his 2026-08-22 decision), while remaining visible in standing_approved.
    A PROVED hand edit (disproved) still gates — see the neighbouring test.
    """
    old = {"as_of": "2026-08-18", "nav_usd": 100.0, "bars": []}
    new = {"as_of": "2026-08-19", "nav_usd": 200.0, "bars": []}
    # canon lags the artifact → the CI condition
    repo = _repo_with_snapshot(tmp_path, old, new)
    _fake_generator(repo, {"as_of": "2026-07-04", "nav_usd": 1.0, "bars": []})

    rep = G.check_owner_gate(diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo)

    # ADR-116: недоказуемое освобождение (канон отстал — штатный шум стройки) уезжает
    # по стоящему одобрению владельца, НО метка unmeasured и вердикт кастодиана обязаны
    # остаться видимыми в standing_approved — «не смогли доказать невиновность» не имеет
    # права превратиться в «невиновен» молча. До ADR-116 здесь был ok=False (ADR-078);
    # решение владельца 22.08 это сознательно меняет, обоснование в журнале W34.
    assert rep["ok"] is True
    assert rep["gated_count"] == 0
    assert rep["standing_approved"], "находка обязана быть видимой, не удалённой"
    assert all(v.get("exemption_unmeasured") for v in rep["standing_approved"])
    assert rep["custodian_exemption"]["state"] == "unmeasured"
    assert "2026-07-04" in rep["custodian_exemption"]["reason"]


def test_proved_custodian_output_is_exempt_and_clean(tmp_path):
    """Reverse control: where the canon CAN describe the artifact and matches, the change
    is exempt and ships — the behaviour that already worked on the owner's machine."""
    old = {"as_of": "2026-08-18", "nav_usd": 100.0, "bars": []}
    new = {"as_of": "2026-08-19", "nav_usd": 200.0, "bars": []}
    repo = _repo_with_snapshot(tmp_path, old, new)
    _fake_generator(repo, dict(new))

    rep = G.check_owner_gate(diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo)
    assert rep["ok"] is True
    assert rep["gated_count"] == 0
    assert rep["custodian_exemption"]["state"] == "proved"


def test_disproved_custodian_output_is_gated_and_not_marked_unmeasured(tmp_path):
    """A hand edit, provable as such, must be a PROVED violation — never diluted into the
    unmeasured bucket (that would be the fail-OPEN this change is careful to avoid)."""
    old = {"as_of": "2026-08-19", "nav_usd": 100.0, "bars": []}
    new = {"as_of": "2026-08-19", "nav_usd": 999.0, "bars": []}
    repo = _repo_with_snapshot(tmp_path, old, new)
    _fake_generator(repo, {"as_of": "2026-08-19", "nav_usd": 100.0, "bars": []})

    rep = G.check_owner_gate(diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo)
    assert rep["ok"] is False
    assert rep["unmeasured_count"] == 0
    assert not any(v.get("exemption_unmeasured") for v in rep["violations"])
    assert rep["custodian_exemption"]["state"] == "disproved"


def test_non_snapshot_violations_are_never_marked_unmeasured(tmp_path):
    """Reverse control: the unmeasured marking belongs to the snapshot path alone. A
    free-text baked number must stay an ordinary, fully-proved violation."""
    repo = _init_repo(tmp_path)
    page = repo / "landing" / "src" / "pages" / "index.astro"
    page.write_text("<h1>SPA</h1>\n<p>Minimum investment $1000.</p>\n", encoding="utf-8")
    _run_git(repo, "commit", "-aqm", "copy: offer")

    rep = G.check_owner_gate(diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo)
    assert rep["ok"] is False
    assert rep["unmeasured_count"] == 0
    assert rep["custodian_exemption"] is None, "снимок не менялся — блока о нём быть не должно"


def test_git_range_judges_the_COMMITTED_head_not_the_working_tree(tmp_path):
    """The subject of judgement in git-range mode is the commit, as it already is for
    tier_bands.json. Before this fix the snapshot branch read the working tree first, so a
    dirty tree could be judged against another commit's base."""
    old = {"as_of": "2026-08-19", "nav_usd": 100.0, "bars": []}
    new = {"as_of": "2026-08-19", "nav_usd": 200.0, "bars": []}   # what was actually COMMITTED
    repo = _repo_with_snapshot(tmp_path, old, new)
    _fake_generator(repo, {"as_of": "2026-08-19", "nav_usd": 1.0, "bars": []})
    # Dirty the working tree with a number that was never committed.
    _write_snapshot(repo, {"as_of": "2026-08-19", "nav_usd": 777777.0, "bars": []})

    rep = G.check_owner_gate(diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo)
    texts = " ".join(str(v.get("matched_text", "")) for v in rep["violations"])
    assert "777777" not in texts, "git-range обязан судить КОММИТ, а не рабочее дерево"
    assert "200.0" in texts, "судить обязан именно закоммиченное изменение"
