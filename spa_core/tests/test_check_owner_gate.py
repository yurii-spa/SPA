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
    # No generate_track_snapshot.py / data canon under the tmp repo → cannot regenerate
    # → returns False (fail-closed: no exemption granted) rather than raising.
    assert G._snapshot_is_custodian_equivalent(tmp_path) is False


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


def test_end_to_end_baked_number_is_gated(tmp_path):
    repo = _init_repo(tmp_path)
    page = repo / "landing" / "src" / "pages" / "index.astro"
    page.write_text("<h1>SPA</h1>\n<p>Earn up to 30% net APY.</p>\n", encoding="utf-8")
    _run_git(repo, "commit", "-aqm", "copy: add number")
    rep = G.check_owner_gate(diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo)
    assert rep["ok"] is False
    assert rep["gated_count"] >= 1
    assert any(v["klass"] == "B" for v in rep["violations"])


def test_end_to_end_owner_approval_bypasses_matching_scope(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    page = repo / "landing" / "src" / "pages" / "index.astro"
    page.write_text("<h1>SPA</h1>\n<p>Earn up to 30% net APY.</p>\n", encoding="utf-8")
    _run_git(repo, "commit", "-aqm", "copy: add number")

    fake_card = SimpleNamespace(
        name="own-99", id="own-99", status="owner-done",
        frontmatter={"approves": ["B"]},
    )
    from spa_core.owner_queue import queue as ownq
    monkeypatch.setattr(ownq, "list_cards", lambda **kw: [fake_card], raising=True)

    rep = G.check_owner_gate(
        diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo,
        commit_message="copy: add number\n\nOwner-Approved: own-99",
    )
    assert rep["ok"] is True, "class-B violation approved by own-99 must be bypassed"
    assert rep["gated_count"] == 0
    assert rep["approved_bypasses"] and rep["approved_bypasses"][0]["klass"] == "B"


def test_end_to_end_non_owner_done_card_does_not_bypass(tmp_path, monkeypatch):
    # A card that is NOT owner-done must never grant a bypass (owner-only, invariant #14).
    repo = _init_repo(tmp_path)
    page = repo / "landing" / "src" / "pages" / "index.astro"
    page.write_text("<h1>SPA</h1>\n<p>Earn up to 30% net APY.</p>\n", encoding="utf-8")
    _run_git(repo, "commit", "-aqm", "copy: add number")

    pending = SimpleNamespace(
        name="own-99", id="own-99", status="needs-owner",
        frontmatter={"approves": ["B"]},
    )
    from spa_core.owner_queue import queue as ownq
    monkeypatch.setattr(ownq, "list_cards", lambda **kw: [pending], raising=True)

    rep = G.check_owner_gate(
        diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo,
        commit_message="copy: add number\n\nOwner-Approved: own-99",
    )
    assert rep["ok"] is False
    assert rep["approval"] is None


def test_end_to_end_no_trailer_no_bypass(tmp_path):
    repo = _init_repo(tmp_path)
    page = repo / "landing" / "src" / "pages" / "index.astro"
    page.write_text("<h1>SPA</h1>\n<p>Earn up to 30% net APY.</p>\n", encoding="utf-8")
    _run_git(repo, "commit", "-aqm", "copy: add number")
    rep = G.check_owner_gate(diff_mode="git-range", base="HEAD~1", head="HEAD", repo_root=repo,
                             commit_message="copy: add number")
    assert rep["ok"] is False
    assert rep["approval"] is None
