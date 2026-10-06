"""Memory & Context Architecture v1 (ADR-527) — hermetic: every root is a synthetic tmp corpus.

Positive controls replay the defects the audit found: a superseded roadmap answering as current, a
shadow-worktree ADR (colliding number) read as canon, a journal line read as a decision, a credential
reaching the index, «recent decisions» returning the oldest, an agent «why» invented instead of UNKNOWN.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import tarfile
import time
from pathlib import Path

import pytest

from spa_core.studio_os.memory import assembler, benchmark, index, lineage, passports, sources, truth

REPO = Path(__file__).resolve().parents[2]
# credential shapes assembled at runtime — a literal token in a test file is itself a leak pattern
FAKE_PAT = "gh" + "p_" + "A1b2C3d4" * 4
FAKE_BOT = "1234567890" + ":" + "A" * 35


def _w(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture()
def corpus(tmp_path, monkeypatch):
    spa, shadow, claude = tmp_path / "spa", tmp_path / "shadow", tmp_path / "claude"
    for name in sources.DEFAULT_ROOTS:
        monkeypatch.setenv(f"SPA_MEMORY_ROOT_{name.upper()}", str(tmp_path / f"absent_{name}"))
    monkeypatch.setenv("SPA_MEMORY_ROOT_SPA", str(spa))
    monkeypatch.setenv("SPA_MEMORY_ROOT_SHADOW", str(shadow))
    monkeypatch.setenv("SPA_MEMORY_ROOT_CLAUDE", str(claude))
    monkeypatch.setenv("SPA_MEMORY_INDEX", str(tmp_path / "index.db"))
    monkeypatch.setenv("SPA_MEMORY_SYNC_STATUS", str(tmp_path / "no_sync_status.json"))
    _w(spa, "CLAUDE.md", "# Rules\n\nOwner-gated subjects: real money, public numbers, irreversible actions.\n"
       f"token = {FAKE_PAT}\nbot {FAKE_BOT}\n")
    _w(spa, "docs/decisions/ADR-001-old-drawdown-ladder.md",
       "# ADR-001 Old drawdown ladder\n\nStatus: Accepted\n\nThe kill-switch fires at 20% drawdown.\n")
    _w(spa, "docs/decisions/ADR-002-two-tier-kill-switch.md",
       "# ADR-002 Two-tier kill-switch\n\nStatus: Accepted\nSupersedes ADR-001\n\n"
       "The drawdown ladder of the kill-switch: SOFT at 5%, HARD at 10%.\n"
       "Стоп-кран: SOFT при просадке 5%, HARD при 10%.\n")
    _w(spa, "docs/decisions/ADR-003-proposed-thing.md", "# ADR-003 Telescope\n\nStatus: Proposed\n\nA telescope.\n")
    _w(spa, "docs/decisions/INDEX.md", "| ADR | t | s |\n|---|---|---|\n| ADR-001 | old | Superseded |\n"
       "| ADR-002 | ladder | Accepted |\n| ADR-003 | telescope | Proposed |\n")
    _w(spa, "docs/ROADMAP.md", "# Roadmap\n\n1. Memory architecture\n2. DeFi gap audit\n")
    _w(spa, "docs/OLD_ROADMAP.md", "# Old roadmap\n\n1. Launch the rocket roadmap first\n")
    _w(spa, "docs/journal/2026-W01.md", "# Journal\n\nIn chat someone said: let us raise leverage to 5x.\n")
    _w(spa, "architecture/manifest.json", json.dumps({"agents": [
        {"label": "com.spa.alpha", "role": "worker", "intent": "scheduled", "program": "alpha.sh",
         "passport": {"goal": "computes the alpha report", "why": "owner asked for alpha (ADR-002)",
                      "created_by": ["ADR-002"]}},
        {"label": "com.spa.beta", "role": "worker", "intent": "scheduled", "program": "beta.sh",
         "passport": {"goal": "computes beta"}}]}))
    _w(spa, "architecture/memory_truth.json", json.dumps({
        "overrides": [{"path": "spa:docs/OLD_ROADMAP.md", "status": "SUPERSEDED",
                       "superseded_by": "spa:docs/ROADMAP.md", "reason": "single canonical roadmap"}],
        "facts": [{"subject": "com.spa.beta", "status": "ACTIVE", "aliases": "бета beta pause",
                   "fact": "beta is paused by the owner", "evidence": ["spa:docs/ROADMAP.md"],
                   "unknown": "the rationale for the pause is not recorded"}],
        "agents": []}))
    _w(shadow, "docs/decisions/ADR-471-mission-tick-stop.md",
       "# ADR-471 Mission tick stop\n\nStatus: Accepted\n\nShadow branch decision.\n")
    _w(claude, "note.md", "# Note\n\nremember the telescope\n")
    return tmp_path


# ---------------------------------------------------------------- ingestion and security

def test_sanitizer_drops_credential_lines_and_keeps_prose():
    clean, dropped = sources.sanitize(f"keep me\nx {FAKE_PAT}\nmid {FAKE_BOT}\nrisk-portfolio-concentration-limits ok")
    assert dropped == 2
    assert FAKE_PAT not in clean and FAKE_BOT not in clean
    # positive control for the false positive found 2026-10-01: «risk-…» is not an «sk-» key
    assert "risk-portfolio-concentration-limits" in clean


def test_deny_list_blocks_runtime_state_and_key_material():
    for rel in ("data/x.md", "state/bridge.db", "a/.git/HEAD", "k.pem", "x.key", "nimbalyst-local/tracker/_BOARD.md"):
        assert sources.DENY.search(rel), rel
    assert not sources.DENY.search("docs/decisions/ADR-1-x.md")


def test_index_never_contains_a_credential(corpus):
    man = index.build()
    assert man["secret_lines_dropped"] == 2
    con = sqlite3.connect(str(corpus / "index.db"))
    blob = " ".join(r[0] for r in con.execute("SELECT body FROM chunks"))
    con.close()
    assert FAKE_PAT not in blob and FAKE_BOT not in blob


# ---------------------------------------------------------------- truth semantics

def _status(rows, path):
    return next(r["status"] for r in rows if r["path"] == path)


def test_truth_statuses_from_registry_canon_layer_and_shadow(corpus):
    index.build()
    rows = index.search("roadmap rocket", k=10)
    assert _status(rows, "docs/OLD_ROADMAP.md") == "SUPERSEDED"
    rows = index.search("kill-switch drawdown ladder", k=10)
    assert _status(rows, "docs/decisions/ADR-001-old-drawdown-ladder.md") == "SUPERSEDED"
    assert _status(rows, "docs/decisions/ADR-002-two-tier-kill-switch.md") == "ACCEPTED"
    # the current decision outranks the one it supersedes
    paths = [r["path"] for r in rows]
    assert paths.index("docs/decisions/ADR-002-two-tier-kill-switch.md") < paths.index(
        "docs/decisions/ADR-001-old-drawdown-ladder.md")
    assert _status(index.search("leverage", k=5), "docs/journal/2026-W01.md") == "OBSERVED"
    assert _status(index.search("telescope", k=5), "docs/decisions/ADR-003-proposed-thing.md") == "PROPOSED"
    shadow = next(r for r in index.search("mission tick stop", k=5) if r["repo"] == "shadow")
    assert shadow["status"] == "UNKNOWN"


def test_status_line_vocabulary():
    assert truth.classify_status_text("Принято") == "ACCEPTED"
    assert truth.classify_status_text("Superseded by ADR-9") == "SUPERSEDED"
    assert truth.classify_status_text("черновик") == "PROPOSED"
    assert truth.classify_status_text("") == "UNKNOWN"
    assert truth.superseded_ids("Supersedes ADR-1 and ADR-2") == ["ADR-1", "ADR-2"]


# ---------------------------------------------------------------- retrieval

def test_russian_query_finds_english_named_decision_via_stemming(corpus):
    index.build()
    top = index.search("при какой просадке срабатывает стоп-кран?", k=3)
    assert top and top[0]["path"] == "docs/decisions/ADR-002-two-tier-kill-switch.md"


def test_index_rebuild_is_atomic_and_reproducible(corpus):
    a = index.build()
    db = corpus / "index.db"
    db.unlink()                                  # recovery rehearsal: the index is disposable
    b = index.build()
    assert db.exists() and not db.with_suffix(".building").exists()
    assert a["sources_digest"] == b["sources_digest"] and a["chunks"] == b["chunks"]
    assert index.manifest()["files"] == b["files"]


def test_missing_index_answers_nothing_rather_than_guessing(corpus):
    assert index.search("anything") == []


def test_benchmark_harness_counts_hits_and_misses():
    qs = [{"id": "Q1", "q": ["a", "b"], "expect_any": ["spa:x.md"]}]
    r = benchmark.run_retrieval(lambda q, k: ["spa:x.md"] if q == "a" else ["spa:y.md"], questions=qs)
    assert (r["hits"], r["total"], r["hit_rate"]) == (1, 2, 0.5)


def test_committed_benchmark_is_well_formed():
    qs = benchmark.load(REPO)
    assert len(qs) == 12
    assert any(q.get("expect_unknown") for q in qs)
    assert all(len(q["q"]) >= 3 for q in qs)
    # at least one Russian phrasing per question
    assert all(any(any("а" <= ch <= "я" for ch in p.lower()) for p in q["q"]) for q in qs)


# ---------------------------------------------------------------- passports

def test_passport_explicit_why_and_unknown_when_absent(corpus):
    a = passports.passport("com.spa.alpha")
    assert a["why"]["origin"] == "EXPLICIT" and a["created_by"]["value"] == ["ADR-002"]
    b = passports.passport("com.spa.beta")
    assert b["why"]["origin"] == "UNKNOWN" and b["why"]["value"] is None
    assert b["facts"][0]["unknown"]
    text = passports.answer_why("com.spa.beta")
    assert "UNKNOWN" in text
    assert passports.passport("com.spa.nobody")["status"] == "UNKNOWN"


# ---------------------------------------------------------------- lineage

def _git(cwd, *a):
    subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True)


def test_lineage_links_decision_task_commit_test(corpus):
    spa = corpus / "spa"
    _w(spa, "nimbalyst-local/tracker/inbox-ladder.md", "# card\n\nimplement ADR-002\n")
    _w(spa, "spa_core/tests/test_ladder.py", "def test_x():\n    pass\n")
    _git(spa, "init", "-b", "main")
    _git(spa, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(spa, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "ADR-002: two-tier ladder")
    _git(spa, "update-ref", "refs/remotes/origin/main", "HEAD")
    ln = lineage.lineage("ADR-002")
    assert ln["found"] and ln["decision"]["status"] == "ACCEPTED"
    assert [t["ref"] for t in ln["tasks"]] == ["spa:nimbalyst-local/tracker/inbox-ladder.md"]
    assert len(ln["implementation"]) == 1 and "spa_core/tests/test_ladder.py" in ln["tests"]
    assert ln["release"]["delivered_to_origin_main"] is True
    assert ln["release"]["in_production_tree"] is None      # no sync record ⇒ not measured, not «no»
    assert lineage.lineage("ADR-999")["status"] == "UNKNOWN"


# ---------------------------------------------------------------- assembler

def test_assembler_holds_budget_and_flags_insufficient_evidence(corpus):
    index.build()
    pkg = assembler.assemble("какой текущий порог стоп-крана по просадке?", budget_chars=4000)
    assert pkg["size_chars"] <= 4000
    assert "UNKNOWN" in pkg["truth_policy"]
    assert pkg["sources"][0]["ref"] == "spa:docs/decisions/ADR-002-two-tier-kill-switch.md"
    none = assembler.assemble("what did we decide about Solana validator staking?", budget_chars=4000)
    assert none["evidence_sufficiency"]["verdict"] == "INSUFFICIENT"
    assert "Context package" in assembler.render_markdown(pkg)


def test_sufficiency_refuses_when_the_subject_is_uncovered(corpus):
    """Held-out Q1 (2026-10-01): 8 of 10 words covered scored SUFFICIENT while the two SUBJECT words
    were absent. A high ratio is not coverage of the question."""
    index.build()
    es = assembler.assemble("two tier kill switch drawdown ladder soft hard ресёрча солана")["evidence_sufficiency"]
    assert es["ratio"] >= 0.75 and len(es["uncovered"]) == 2
    assert es["verdict"] != "SUFFICIENT"


# ---------------------------------------------------------------- context pack (ADR-495) audit fixes

def test_context_pack_recent_decisions_are_the_newest(monkeypatch, tmp_path):
    from spa_core.studio_os import context
    _w(tmp_path, "docs/decisions/INDEX.md", "| ADR-001 | a | Accepted |\n| ADR-002 | b | Accepted |\n"
       "| ADR-003 | c | Accepted |\n")
    _w(tmp_path, "docs/ROADMAP.md", "# Roadmap\n1. memory\n")
    monkeypatch.setattr(context, "REPO", tmp_path)
    assert [d["id"] for d in context._recent_decisions(2)] == ["ADR-003", "ADR-002"]
    assert context._roadmap_snip()["provenance"] == "docs/ROADMAP.md"


# ---------------------------------------------------------------- backup

def _load_backup():
    spec = importlib.util.spec_from_file_location("memory_backup", REPO / "scripts" / "memory_backup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backup_bundles_verify_and_secrets_never_archived(tmp_path):
    mb = _load_backup()
    repo = tmp_path / "repo"
    _w(repo, "a.md", "hello\n")
    _git(repo, "init", "-b", "main")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c1")
    store = tmp_path / "out" / "bundles"
    store.mkdir(parents=True)
    b = mb.bundle_repo("r", repo, store)
    assert b["ok"] and b["verify"] == "ok" and not b["reused"]
    assert mb.bundle_repo("r", repo, store)["reused"]          # unchanged repo ⇒ no second upload
    state = tmp_path / "state"
    _w(state, "journal.jsonl", "{}\n")
    _w(state, "leak.json", f'{{"t": "{FAKE_BOT}"}}\n')
    _w(state, "activation_ipc/signer/owner.key", "PRIVATE\n")
    db = sqlite3.connect(str(state / "x.db"))
    db.execute("create table t(a)"); db.commit(); db.close()
    out = tmp_path / "out"
    s = mb.archive_state("st", state, ("activation_ipc/signer",), out)
    with tarfile.open(out / "state-st.tar.gz") as t:
        names = set(t.getnames())
    assert s["ok"] and names == {"journal.jsonl", "x.db"}
    assert [x["file"] for x in s["skipped"]] == ["leak.json"]
    assert mb.bundle_repo("nope", tmp_path / "missing", store)["ok"] is False


# ── index.build() tmp-file lifecycle (round-2 review, 2026-10-06) ──────────────────────────────
# Before this fix, `build()` wrote into the single FIXED name `<path>.building`, shared by every
# caller — the scheduled ensure-fresh step and an interactive `assembler.assemble()` auto-rebuild
# could run around the same time and clobber each other's half-written sqlite file. The fix makes
# the tmp name unique per process+call (pid + a random suffix); these tests do not actually race
# two real processes (pytest has no primitive for that), they check the PROPERTY that makes the
# race impossible — a unique name per call — plus the two concrete scenarios the review named:
# "two sequential builds sharing a dir" and "an interrupted one leaving a stale tmp".
def _empty_roots(tmp_path: Path, monkeypatch) -> None:
    """Every source root points at a directory that does not exist — `build()` indexes zero
    files, so the scene below runs in milliseconds and the test is about the tmp-file dance, not
    about memory content."""
    for name in ("spa", "bridge", "earndefi", "company", "claude", "shadow"):
        monkeypatch.setenv(f"SPA_MEMORY_ROOT_{name.upper()}", str(tmp_path / f"absent_{name}"))


def test_build_tmp_name_embeds_the_pid_not_the_old_shared_fixed_name(tmp_path, monkeypatch):
    _empty_roots(tmp_path, monkeypatch)
    path = tmp_path / "index.db"
    seen = []
    orig_connect = sqlite3.connect

    def spy(name, *a, **kw):
        seen.append(name)
        return orig_connect(name, *a, **kw)

    monkeypatch.setattr(sqlite3, "connect", spy)
    index.build(path)
    assert len(seen) == 1
    tmp_name = Path(seen[0]).name
    assert tmp_name.startswith("index.db.building.")
    assert str(os.getpid()) in tmp_name
    assert tmp_name != path.with_suffix(".building").name  # the OLD name every caller used to share


def test_two_sequential_builds_sharing_a_dir_do_not_corrupt_each_other(tmp_path, monkeypatch):
    """The round-2 review's own phrasing: "simulate with two sequential builds sharing a dir"."""
    _empty_roots(tmp_path, monkeypatch)
    path = tmp_path / "index.db"
    a = index.build(path)
    assert not list(path.parent.glob(f"{path.name}.building.*"))  # no leftover after a clean build
    b = index.build(path)
    assert path.is_file()
    assert a["sources_digest"] == b["sources_digest"] and a["chunks"] == b["chunks"] == 0
    assert not list(path.parent.glob(f"{path.name}.building.*"))


def test_interrupted_build_leaves_a_stale_tmp_the_next_build_ignores(tmp_path, monkeypatch):
    """A crashed process's tmp file (a half-written sqlite file, same shape as this one) has its
    OWN unique name — nothing else will ever claim it — so it must neither block nor be silently
    swept by a build that is itself still fresh enough to plausibly be in progress."""
    _empty_roots(tmp_path, monkeypatch)
    path = tmp_path / "index.db"
    stale = path.parent / f"{path.name}.building.999999.deadbeef"
    stale.write_bytes(b"not a real sqlite file")
    man = index.build(path)
    assert path.is_file() and man["chunks"] == 0
    assert stale.is_file()  # fresh enough to be left alone (see _ABANDONED_TMP_MIN_AGE_S)


def test_abandoned_stale_tmp_past_the_sweep_age_is_cleaned_up_not_accumulated(tmp_path, monkeypatch):
    _empty_roots(tmp_path, monkeypatch)
    path = tmp_path / "index.db"
    stale = path.parent / f"{path.name}.building.999999.deadbeef"
    stale.write_bytes(b"not a real sqlite file")
    old = time.time() - index._ABANDONED_TMP_MIN_AGE_S - 60
    os.utime(stale, (old, old))
    index.build(path)
    assert not stale.exists()


def test_a_build_that_raises_discards_its_own_tmp_file(tmp_path, monkeypatch):
    _empty_roots(tmp_path, monkeypatch)
    path = tmp_path / "index.db"

    def boom(*a, **kw):
        raise RuntimeError("synthetic failure mid-build")

    monkeypatch.setattr(index, "_build_into", boom)
    with pytest.raises(RuntimeError):
        index.build(path)
    assert not path.exists()
    assert not list(path.parent.glob(f"{path.name}.building.*"))
