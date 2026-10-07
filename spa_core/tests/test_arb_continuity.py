"""ARB continuity generator + freshness gate (ADR-610, ARB-CONTINUITY-01 §4/§5/§12).

Hermetic: a disposable canonical root (the REAL curated contract and cited ADRs copied from this repo) and
a synthetic published Mission Control bundle. Every failure scenario is a positive control: the gate is
first shown FRESH on the intact scene, then the one named link is broken and the verdict must flip.
"""
# FROZEN-DATE-OK: injected-clock — every time is scene.at(h), derived from the anchor scene.AT and passed
# into continuity.build(generated_at=...) / continuity.check(now=...); no wall clock is read.
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.studio_os.memory import continuity as c
from spa_core.tests import _arb_continuity_scene as scene


@pytest.fixture()
def env(tmp_path):
    root = scene.make_root(tmp_path)
    scene.git_init(root)
    mission = scene.write_mission(tmp_path / "mission")
    receipt = scene.write_receipt(tmp_path / "receipt.json")
    out = tmp_path / "out"
    return dict(root=root, mission=mission, receipt=receipt, out=out, tmp=tmp_path)


def _build(e, at=None, **kw):
    st = c.build(e["root"], at or scene.AT, kw.get("receipt", e["receipt"]), kw.get("mission", e["mission"]))
    c.write(st, e["out"])
    return st


def _check(e, hours=0.5, **kw):
    return c.check(e["root"], e["out"], scene.at(hours), kw.get("receipt", e["receipt"]), kw.get("mission", e["mission"]))


def _files(d: Path) -> dict:
    return {p.name: p.read_bytes() for p in sorted(d.iterdir())}


# ── determinism / rebuild ────────────────────────────────────────────────────────────────────

def test_double_rebuild_is_byte_identical_and_survives_deletion(env):
    _build(env)
    first = _files(env["out"])
    for p in env["out"].iterdir():
        p.unlink()
    _build(env)
    assert _files(env["out"]) == first
    assert set(first) == set(c.OUTPUTS)


def test_intact_scene_is_fresh(env):
    _build(env)
    res = _check(env)
    assert res["verdict"] == "CONTEXT_FRESH", res


def test_changed_canonical_source_is_stale_then_rebuild_restores_fresh(env):
    _build(env)
    assert _check(env)["verdict"] == "CONTEXT_FRESH"
    p = env["root"] / "docs/ROADMAP.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n<!-- changed -->\n", encoding="utf-8")
    res = _check(env)
    assert res["verdict"] == "CONTEXT_STALE"
    assert any("docs/ROADMAP.md" in r for r in res["reasons"])
    _build(env, at=scene.at(1))
    assert _check(env, hours=1.5)["verdict"] == "CONTEXT_FRESH"


def test_latest_accepted_epic_change_is_named(env):
    _build(env)
    p = env["root"] / "docs/ROADMAP.md"
    t = p.read_text(encoding="utf-8").replace(
        "11. **ARB-CONTINUITY-01 · Architecture continuity + owner control & recovery hardening** — in progress",
        "11. ~~ARB-CONTINUITY-01 · Architecture continuity~~ — DONE 2026-10-08 (ADR-610): done")
    p.write_text(t, encoding="utf-8")
    res = _check(env)
    assert res["verdict"] == "CONTEXT_STALE"
    assert any("latest accepted epic changed" in r for r in res["reasons"])


# ── supersession ─────────────────────────────────────────────────────────────────────────────

def test_new_adr_superseding_a_cited_one_is_stale_and_flips_the_index(env):
    st = _build(env)
    assert next(r for r in st["decisions"] if r["topic"] == "oracle-cio")["cls"] == "CURRENT"
    (env["root"] / "docs/decisions/ADR-999-new-cio.md").write_text(
        "# ADR-999 · new CIO\n\n- **Status:** Accepted\n\nSupersedes ADR-554.\n", encoding="utf-8")
    res = _check(env)
    assert res["verdict"] == "CONTEXT_STALE"
    assert any("supersession" in r for r in res["reasons"])
    st2 = _build(env, at=scene.at(1))
    row = next(r for r in st2["decisions"] if r["topic"] == "oracle-cio")
    assert row["cls"] == "SUPERSEDED" and row["refs"][0]["superseded_by"] == "ADR-999"
    assert any("ADR-554 is SUPERSEDED" in f for i in st2["intents"] for f in i["flags"]) or \
        all("ADR-554" not in i["decisions"] for i in st2["intents"])


def test_any_new_adr_in_either_registry_is_stale(env):
    """Review P1-2: an ADR the index does not cite may still be a decision it lacks — never FRESH."""
    _build(env)
    (env["root"] / "docs/decisions/ADR-998-unrelated.md").write_text(
        "# ADR-998\n\n- **Status:** Accepted\n\nNothing about cited decisions.\n", encoding="utf-8")
    res = _check(env)
    assert res["verdict"] == "CONTEXT_STALE" and any("adr_registry_listing" in r for r in res["reasons"]), res
    _build(env, at=scene.at(1))
    (env["root"] / "docs/adr").mkdir(exist_ok=True)
    (env["root"] / "docs/adr/ADR-997-old-registry.md").write_text("# old\n", encoding="utf-8")
    assert _check(env, hours=1.5)["verdict"] == "CONTEXT_STALE"


def test_state_md_and_index_are_inputs(env):
    for rel in ("docs/STATE.md", "docs/decisions/INDEX.md"):
        _build(env)
        p = env["root"] / rel
        p.write_text(p.read_text(encoding="utf-8") + "\nx\n", encoding="utf-8")
        res = _check(env)
        assert res["verdict"] == "CONTEXT_STALE" and any(rel in r for r in res["reasons"]), (rel, res)


def test_cross_registry_number_is_marked_ambiguous(env):
    (env["root"] / "docs/adr").mkdir(exist_ok=True)
    (env["root"] / "docs/adr/ADR-554-something-else.md").write_text("# other 554\n", encoding="utf-8")
    st = _build(env)
    ref = next(r for r in st["decisions"] if r["topic"] == "oracle-cio")["refs"][0]
    assert ref["number_collision"] == ["docs/adr/ADR-554-something-else.md"]
    assert "AMBIGUOUS NUMBER" in (env["out"] / "ARCHITECT_DECISION_INDEX.md").read_text(encoding="utf-8")


def test_profile_effective_date_comes_from_the_adr_not_a_literal(env):
    st = _build(env)
    eff = {p["profile"]: p["effective"] for p in st["profiles"]}
    assert eff["Conservative"] == "2026-07-11"        # ADR-593 «Date of decision», not its backfill date
    assert eff["Balanced"] == "2026-10-01"            # ADR-533 status line
    assert c.adr_effective("- **Status:** Accepted (backfilled 2026-10-06)\n- **Date of decision:** 2026-07-11") \
        == "2026-07-11"


def test_runtime_measured_without_observation_time_is_partial(env):
    def drop(t):
        t["home"]["money_chip"]["as_of"] = None
    st = _build(env, mission=scene.write_mission(env["tmp"] / "m5", mutate=drop))
    assert st["sections"]["real_capital"]["status"] == "PARTIAL"
    assert _check(env, mission=scene.write_mission(env["tmp"] / "m5", mutate=drop))["verdict"] == "CONTEXT_PARTIAL"
    st["sections"]["real_capital"]["status"] = "MEASURED"
    with pytest.raises(c.ContinuityError, match="without an observation time"):
        c.validate(st, json.loads((env["root"] / c.SCHEMA_FILE).read_text()))


def test_origin_not_measured_at_check_is_never_fresh(env):
    _build(env)
    assert _check(env)["verdict"] == "CONTEXT_FRESH"
    scene.git(env["root"], "remote", "set-url", "origin", str(env["tmp"] / "gone.git"))
    res = _check(env)
    assert res["verdict"] == "CONTEXT_PARTIAL" and any("origin head not measured" in r for r in res["reasons"])


def test_check_names_the_judged_file_and_its_role(env, capsys):
    _build(env)
    assert c.main(["check", "--root", str(env["root"]), "--out", str(env["out"]), "--receipt", str(env["receipt"]),
                   "--mission", str(env["mission"]), "--at", scene.at(0.5)]) == 0
    out = capsys.readouterr().out
    assert f"judged: {env['out'] / 'state.json'}" in out and "copy role PRODUCTION" in out


def test_dirty_root_is_flagged_and_never_fresh_at_generation(env):
    p = env["root"] / c.CONTEXT_FILE
    p.write_text(p.read_text(encoding="utf-8") + "\nuncommitted\n", encoding="utf-8")
    st = _build(env)
    assert c.CONTEXT_FILE in st["header"]["root_dirty_inputs"]
    assert st["header"]["verdict_at_generation"] == "CONTEXT_PARTIAL"


def test_active_epic_drops_an_announcement_naming_a_done_epic(env):
    def done(t):
        t["studio"]["claude_work"]["epic"] = "RM-TRUTH-01 · Company truth reconciliation + Director OS recovery"
    st = _build(env, mission=scene.write_mission(env["tmp"] / "m6", mutate=done))
    assert "RM-TRUTH-01" not in st["sections"]["active_epic"]["display"]
    st = _build(env)
    assert "announced (as of" in st["sections"]["active_epic"]["display"]


def test_missing_cited_adr_cannot_stay_current(env):
    (env["root"] / "docs/decisions").joinpath(
        next(p.name for p in (env["root"] / "docs/decisions").glob("ADR-563-*.md"))).unlink()
    st = c.build(env["root"], scene.AT, env["receipt"], env["mission"])
    assert next(r for r in st["decisions"] if r["topic"] == "published-rate-rounds-down")["cls"] == "UNKNOWN"


# ── fail-closed build ────────────────────────────────────────────────────────────────────────

def test_missing_required_source_refuses_and_writes_nothing(env):
    (env["root"] / c.LEDGER_FILE).unlink()
    with pytest.raises(c.ContinuityError, match="required canonical source missing"):
        _build(env)
    assert not env["out"].exists()


def test_duplicate_intent_refuses(env):
    p = env["root"] / c.LEDGER_FILE
    t = p.read_text(encoding="utf-8")
    first = t[t.index("## INT-01"):t.index("## INT-02")]
    p.write_text(t + "\n" + first, encoding="utf-8")
    with pytest.raises(c.ContinuityError, match="duplicate intent"):
        _build(env)


def test_intent_missing_field_refuses(env):
    p = env["root"] / c.LEDGER_FILE
    t = p.read_text(encoding="utf-8")
    p.write_text(t.replace("- **why_it_matters:**", "- **why:**", 1), encoding="utf-8")
    with pytest.raises(c.ContinuityError, match="missing field"):
        _build(env)


def test_public_metric_crossing_type_boundary_refuses(env):
    def cross(t):
        t["product"]["profiles"]["conservative"]["metric_type"] = "BACKTEST"
    m = scene.write_mission(env["tmp"] / "m2", mutate=cross)
    with pytest.raises(c.ContinuityError, match="metric type crossing"):
        _build(env, mission=m)


def test_symlinked_source_refuses(env):
    p = env["root"] / "docs/ROADMAP.md"
    real = env["tmp"] / "elsewhere.md"
    real.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    p.unlink()
    p.symlink_to(real)
    with pytest.raises(c.ContinuityError, match="symlink"):
        _build(env)


def test_value_without_provenance_is_refused_by_validate(env):
    st = c.build(env["root"], scene.AT, env["receipt"], env["mission"])
    st["sections"]["oracle"]["source"] = ""
    with pytest.raises(c.ContinuityError, match="provenance"):
        c.validate(st, json.loads((env["root"] / c.SCHEMA_FILE).read_text()))


def test_build_does_not_mutate_sources(env):
    before = {p: p.read_bytes() for p in env["root"].rglob("*") if p.is_file()}
    _build(env)
    assert before == {p: p.read_bytes() for p in env["root"].rglob("*") if p.is_file()}


def test_secrets_and_absolute_paths_never_reach_outputs(env):
    fake = "ghp_" + "A" * 36
    p = env["root"] / c.LEDGER_FILE
    t = p.read_text(encoding="utf-8").replace(
        "- **current_status:** DELIVERED (ADR-592",
        f"- **current_status:** token {fake} at /Users/someone/secret.txt DELIVERED (ADR-592", 1)
    p.write_text(t, encoding="utf-8")
    _build(env)
    blob = b"".join(_files(env["out"]).values()).decode("utf-8")
    assert fake not in blob and "/Users/someone" not in blob


# ── tampering / outputs ──────────────────────────────────────────────────────────────────────

def test_missing_output_is_stale(env):
    _build(env)
    (env["out"] / "ARCHITECT_DECISION_INDEX.md").unlink()
    assert _check(env)["verdict"] == "CONTEXT_STALE"


def test_hand_edit_of_generated_markdown_is_stale(env):
    _build(env)
    p = env["out"] / "CURRENT_STATE.md"
    p.write_text(p.read_text(encoding="utf-8").replace("NOT ENABLED", "ENABLED"), encoding="utf-8")
    res = _check(env)
    assert res["verdict"] == "CONTEXT_STALE" and any("does not match" in r for r in res["reasons"])


@pytest.mark.parametrize("field,bad", [("repo_commit", "abc"), ("production_release", "zz" * 20),
                                       ("generated_at", "yesterday"), ("authority", "CANONICAL")])
def test_malformed_header_metadata_is_stale(env, field, bad):
    _build(env)
    p = env["out"] / "state.json"
    st = json.loads(p.read_text())
    st["header"][field] = bad
    p.write_text(json.dumps(st))
    res = _check(env)
    assert res["verdict"] == "CONTEXT_STALE" and "malformed" in res["reasons"][0]


def test_writes_are_refused_inside_the_root_except_the_contract_dir(env):
    st = c.build(env["root"], scene.AT, env["receipt"], env["mission"])
    with pytest.raises(c.ContinuityError, match="only output place"):
        c.write(st, env["root"] / "data", env["root"])
    with pytest.raises(c.ContinuityError, match="COMMITTED_SNAPSHOT"):
        c.write(st, env["root"] / c.CONTRACT_DIR, env["root"])
    snap = c.build(env["root"], scene.AT, env["receipt"], env["mission"], "COMMITTED_SNAPSHOT")
    c.write(snap, env["root"] / c.CONTRACT_DIR, env["root"])       # the committed location, with its role


# ── runtime identity / age ───────────────────────────────────────────────────────────────────

def test_runtime_absent_is_partial_and_never_guesses(env):
    st = c.build(env["root"], scene.AT, None, None)
    c.write(st, env["out"])
    for k in ("real_capital", "trading_lab", "oracle", "sherlock", "production_code"):
        assert st["sections"][k]["status"] == c.UNKNOWN, k
    assert st["sections"]["real_capital"]["value"] is None          # not a fabricated $0
    assert st["header"]["production_release"] == c.UNKNOWN
    assert c.check(env["root"], env["out"], scene.at(0.5), None, None)["verdict"] == "CONTEXT_PARTIAL"


def test_failed_sync_receipt_does_not_prove_production(env):
    r = scene.write_receipt(env["tmp"] / "bad.json", result="FAILED")
    st = c.build(env["root"], scene.AT, r, env["mission"])
    assert st["header"]["production_release"] == c.UNKNOWN
    assert st["sections"]["production_code"]["status"] == c.UNKNOWN


def test_production_identity_lost_after_build_is_stale(env):
    _build(env)
    r = scene.write_receipt(env["tmp"] / "bad.json", result="FAILED")
    res = _check(env, receipt=r)
    assert res["verdict"] == "CONTEXT_STALE" and any("can no longer be verified" in x for x in res["reasons"])


def test_production_moved_to_unknown_commit_is_stale(env):
    _build(env)
    r = scene.write_receipt(env["tmp"] / "moved.json", sha=scene.SHA_B)
    res = _check(env, receipt=r)
    assert res["verdict"] == "CONTEXT_STALE" and any("cannot be proven immaterial" in x for x in res["reasons"])


def test_production_moved_by_generated_outputs_only_is_fresh_but_code_change_is_stale(env):
    root = env["root"]
    c1 = scene.git(root, "rev-parse", "HEAD")
    r1 = scene.write_receipt(env["tmp"] / "r1.json", sha=c1)
    c.write(c.build(root, scene.AT, r1, env["mission"], "COMMITTED_SNAPSHOT"), root / c.CONTRACT_DIR, root)
    c.write(c.build(root, scene.AT, r1, env["mission"]), env["out"])
    scene.git(root, "add", "-A")
    scene.git(root, "commit", "-q", "-m", "generated outputs only")
    c2 = scene.publish(root)
    res = c.check(root, env["out"], scene.at(0.5), scene.write_receipt(env["tmp"] / "r2.json", sha=c2), env["mission"])
    assert res["verdict"] == "CONTEXT_FRESH", res
    assert any("generated outputs only" in n for n in res["notes"])
    (root / "spa_core").mkdir(exist_ok=True)
    (root / "spa_core" / "x.py").write_text("x = 1\n")
    scene.git(root, "add", "-A")
    scene.git(root, "commit", "-q", "-m", "code")
    c3 = scene.publish(root)
    res = c.check(root, env["out"], scene.at(0.5), scene.write_receipt(env["tmp"] / "r3.json", sha=c3), env["mission"])
    assert res["verdict"] == "CONTEXT_STALE" and any("spa_core/x.py" in x for x in res["reasons"])


def test_moved_origin_with_identical_inputs_is_a_note_but_changed_inputs_are_stale(env):
    root = env["root"]
    _build(env)
    (root / "README.md").write_text("unrelated\n")
    scene.git(root, "add", "-A")
    scene.git(root, "commit", "-q", "-m", "unrelated")
    scene.publish(root)
    res = _check(env)
    assert res["verdict"] == "CONTEXT_FRESH" and any("moved" in n for n in res["notes"]), res
    p = root / c.CONTEXT_FILE
    p.write_text(p.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")
    scene.git(root, "commit", "-qam", "context edit")
    scene.publish(root)
    assert _check(env)["verdict"] == "CONTEXT_STALE"


def test_root_behind_the_server_is_stale(env):
    """Stale origin: another clone moved the SERVER; the canonical root did not follow."""
    root = env["root"]
    _build(env)
    other = env["tmp"] / "other"
    scene.git(env["tmp"], "clone", "-q", str(root.parent / "origin.git"), str(other))
    p = other / c.CONTEXT_FILE
    p.write_text(p.read_text(encoding="utf-8") + "\nchanged elsewhere\n", encoding="utf-8")
    scene.git(other, "commit", "-qam", "elsewhere")
    scene.git(other, "push", "-q", "origin", "HEAD:refs/heads/main")
    res = _check(env)
    assert res["verdict"] == "CONTEXT_STALE" and any("behind origin" in r for r in res["reasons"]), res
    scene.git(root, "fetch", "-q", "origin")                      # the commit is now known locally …
    res = _check(env)
    assert res["verdict"] == "CONTEXT_STALE" and any("input change" in r for r in res["reasons"]), res


def test_no_network_never_reads_the_cached_tracking_ref(env):
    root = env["root"]
    scene.git(root, "remote", "set-url", "origin", str(env["tmp"] / "missing.git"))
    st = c.build(root, scene.AT, env["receipt"], env["mission"])
    assert st["header"]["origin_commit"] == c.UNKNOWN
    assert st["sections"]["current_origin"]["status"] == c.UNKNOWN


def test_runtime_older_than_24h_is_stale(env):
    _build(env)
    res = _check(env, hours=25)
    assert res["verdict"] == "CONTEXT_STALE" and any("h old" in r for r in res["reasons"])


def test_future_dated_context_is_stale(env):
    _build(env, at=scene.at(2))
    assert _check(env, hours=0)["verdict"] == "CONTEXT_STALE"


def test_stale_trading_lab_cell_is_not_reported_as_measured(env):
    def stale(t):
        t["capital"]["trading_lab"]["state"] = "STALE"
    m = scene.write_mission(env["tmp"] / "m3", mutate=stale)
    st = _build(env, mission=m)
    assert st["sections"]["trading_lab"]["status"] == "STALE"


def test_oracle_insufficient_evidence_is_shown_as_such(env):
    st = _build(env)
    assert "INSUFFICIENT_EVIDENCE" in st["sections"]["oracle"]["display"]
    assert "no execution authority" in st["sections"]["oracle"]["display"]


def test_sherlock_unknown_total_is_never_a_number(env):
    def boolean_total(t):
        t["capital"]["sherlock"]["total"] = True          # the historical bool-flag defect
    m = scene.write_mission(env["tmp"] / "m4", mutate=boolean_total)
    st = _build(env, mission=m)
    assert "total facts не измерено" in st["sections"]["sherlock"]["display"]


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────

def test_cli_exit_codes(env, capsys):
    base = ["--root", str(env["root"]), "--out", str(env["out"]), "--receipt", str(env["receipt"]),
            "--mission", str(env["mission"])]
    assert c.main(["build", *base, "--at", scene.AT]) == 0
    assert c.main(["check", *base, "--at", scene.at(0.5)]) == 0
    assert c.main(["check", *base, "--at", scene.at(30)]) == 2
    (env["root"] / c.LEDGER_FILE).unlink()
    assert c.main(["build", *base, "--at", scene.AT]) == 2
    assert "REFUSED" in capsys.readouterr().out


def test_memory_cli_dispatches_continuity(env):
    from spa_core.studio_os.memory.__main__ import main as memory_main
    assert memory_main(["continuity", "build", "--root", str(env["root"]), "--out", str(env["out"]),
                        "--receipt", str(env["receipt"]), "--mission", str(env["mission"]), "--at", scene.AT]) == 0
    assert (env["out"] / "state.json").is_file()


# ── the real repository contract ─────────────────────────────────────────────────────────────

def test_real_contract_resolves_every_cited_decision(env):
    """Guards the curated docs against the canon: every topic/intent ADR exists exactly once."""
    st = c.build(scene.REPO, scene.AT, env["receipt"], env["mission"])
    bad = [r["topic"] for r in st["decisions"] if r["cls"] == c.UNKNOWN]
    assert bad == [], bad
    assert all(i["decision_status"] != c.UNKNOWN for i in st["intents"]), st["intents"]
    assert st["sections"]["latest_accepted_epic"]["status"] == "MEASURED"


def test_committed_generated_copy_is_not_hand_edited():
    d = scene.REPO / c.CONTRACT_DIR
    assert (d / "state.json").is_file(), "the committed generated copy is part of the contract (ADR-610 §1)"
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    rendered = c.render(st)
    for name in ("CURRENT_STATE.md", "ARCHITECT_DECISION_INDEX.md"):
        assert (d / name).read_text(encoding="utf-8") == rendered[name], name


def test_generator_never_imports_company_truth():
    src = (scene.REPO / c.GENERATOR_FILE).read_text(encoding="utf-8")
    assert "company_truth" not in "".join(l for l in src.splitlines() if l.startswith(("import", "from")))


def test_root_ahead_of_origin_is_a_candidate_not_stale_not_fresh(env):
    root = env["root"]
    p = root / "docs/ROADMAP.md"
    p.write_text(p.read_text(encoding="utf-8") + "\nlocal\n", encoding="utf-8")
    scene.git(root, "commit", "-qam", "unpublished")
    _build(env)
    res = _check(env)
    assert res["verdict"] == "CONTEXT_PARTIAL" and any("ahead of origin" in r for r in res["reasons"]), res
    scene.publish(root)
    assert _check(env)["verdict"] == "CONTEXT_FRESH"


def test_diverged_root_judges_only_the_server_side_changes(env):
    """Root has unpublished commits AND the server moved: only the server's changes are material."""
    root = env["root"]
    other = env["tmp"] / "other2"
    scene.git(env["tmp"], "clone", "-q", str(root.parent / "origin.git"), str(other))
    (other / "README.md").write_text("server-side unrelated\n")
    scene.git(other, "add", "-A")
    scene.git(other, "commit", "-qm", "server")
    scene.git(other, "push", "-q", "origin", "HEAD:refs/heads/main")
    p = root / "docs/ROADMAP.md"
    p.write_text(p.read_text(encoding="utf-8") + "\nlocal\n", encoding="utf-8")
    scene.git(root, "commit", "-qam", "local unpublished")
    scene.git(root, "fetch", "-q", "origin")
    _build(env)
    res = _check(env)
    assert res["verdict"] != "CONTEXT_STALE", res          # our own ROADMAP edit is not «origin moved»
    q = other / c.CONTEXT_FILE
    q.write_text(q.read_text(encoding="utf-8") + "\nserver edit\n", encoding="utf-8")
    scene.git(other, "commit", "-qam", "server context edit")
    scene.git(other, "push", "-q", "origin", "HEAD:refs/heads/main")
    scene.git(root, "fetch", "-q", "origin")
    res = _check(env)
    assert res["verdict"] == "CONTEXT_STALE" and any(c.CONTEXT_FILE in r for r in res["reasons"]), res


# ── wave D: grader findings on fresh-session run #2 ─────────────────────────────────────────────

def test_current_state_blurb_defers_to_the_bootstrap_four_step_rule(env):
    """Finding 1: the generated header blurb stated the OLD no-machine rule («stale if origin_commit is
    not the current origin head»), contradicting BOOTSTRAP's four steps (a commit cannot contain its
    own hash). The blurb must point to BOOTSTRAP and carry none of the old wording."""
    _build(env)
    md = (env["out"] / "CURRENT_STATE.md").read_text(encoding="utf-8")
    assert "is not the current origin head" not in md
    assert "four-step no-machine rule in `docs/continuity/BOOTSTRAP.md`" in md
    boot = (scene.REPO / "docs/continuity/BOOTSTRAP.md").read_text(encoding="utf-8")
    assert "commit inequality alone is NOT staleness" in boot and "adr_max_considered" in boot


def test_committed_snapshot_refuses_a_dirty_root_and_writes_nothing(env):
    """Finding 2: «inputs not committed at generation» cannot be proven off the machine."""
    p = env["root"] / c.CONTEXT_FILE
    p.write_text(p.read_text(encoding="utf-8") + "\nuncommitted\n", encoding="utf-8")
    with pytest.raises(c.ContinuityError, match="clean canonical root"):
        c.build(env["root"], scene.AT, env["receipt"], env["mission"], "COMMITTED_SNAPSHOT")
    snap = env["root"] / c.CONTRACT_DIR
    before = {q.name for q in snap.iterdir()}
    rc = c.main(["build", "--root", str(env["root"]), "--out", str(snap), "--receipt", str(env["receipt"]),
                 "--mission", str(env["mission"]), "--at", scene.AT])
    assert rc == 2 and {q.name for q in snap.iterdir()} == before and not (snap / "state.json").exists()
    st = _build(env)                                  # a PRODUCTION build still works, flagged PARTIAL
    assert st["header"]["verdict_at_generation"] == "CONTEXT_PARTIAL"


def test_header_names_the_highest_adr_considered_and_the_listing_hash(env):
    """Finding 3: «newer than the newest CITED ADR» fired forever on uncited ADRs; the reader needs the
    highest ADR the generator SAW."""
    (env["root"] / "docs/decisions/ADR-777-uncited-but-present.md").write_text("# ADR-777 x\n", encoding="utf-8")
    scene.git(env["root"], "add", "-A")
    scene.git(env["root"], "commit", "-q", "-m", "adr 777")
    scene.publish(env["root"])
    st = _build(env)
    h = st["header"]
    assert h["adr_max_considered"] == 777
    assert h["adr_listing_sha256"] == st["inputs"]["derived:adr_registry_listing"]
    assert c.adr_max_considered(["docs/decisions/ADR-012-a.md", "docs/adr/ADR-31-b.md"]) == 31
    assert c.adr_max_considered([]) is None


def _record(d: Path, junit: str, commit: str = "c" * 40, as_of: str = scene.AT) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "junit.xml").write_text(junit, encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({"commit": commit, "as_of": as_of}), encoding="utf-8")
    return d


_SUITE = ('<testsuites><testsuite name="s" tests="{t}" failures="{f}" errors="0" skipped="0">{cases}'
          '</testsuite></testsuites>')


def test_origin_main_test_health_has_three_outcomes(env):
    """Finding 4: MEASURED (N + names) · MEASURED_ZERO · NOT_MEASURED (reason) — from a machine record
    only; no record ⇒ NOT_MEASURED with a POINTER to ADR-613, never a number taken from prose."""
    sec = c.test_health_section(None)
    assert sec["status"] == "NOT_MEASURED" and "ADR-613" in sec["display"] and sec["value"] is None
    sec = c.test_health_section(env["tmp"] / "absent")
    assert sec["status"] == "NOT_MEASURED" and "no machine record" in sec["display"]
    red = _record(env["tmp"] / "red", _SUITE.format(t=3, f=1, cases=(
        '<testcase classname="a.b" name="t_ok"/><testcase classname="a.b" name="t_bad"><failure/></testcase>'
        '<testcase classname="a.c" name="t_ok2"/>')))
    sec = c.test_health_section(red)
    assert sec["status"] == "MEASURED" and sec["value"]["failed"] == 1
    assert sec["value"]["names"] == ["a.b::t_bad"] and sec["as_of"] == scene.AT
    green = _record(env["tmp"] / "green", _SUITE.format(t=2, f=0, cases='<testcase classname="a" name="x"/>' * 2))
    sec = c.test_health_section(green)
    assert sec["status"] == "MEASURED_ZERO" and sec["value"]["failed"] == 0 and sec["as_of"] == scene.AT
    cut = _record(env["tmp"] / "cut", "<testsuites><testsuite name='s'")      # killed mid-write
    assert c.test_health_section(cut)["status"] == "NOT_MEASURED"
    nometa = _record(env["tmp"] / "nometa", _SUITE.format(t=1, f=0, cases='<testcase name="x"/>'), commit="HEAD")
    assert c.test_health_section(nometa)["status"] == "NOT_MEASURED"
    st = c.build(env["root"], scene.AT, env["receipt"], env["mission"], test_record=red)
    assert st["sections"]["test_health"]["status"] == "MEASURED"
