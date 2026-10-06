"""ADR-591 §Wave2 (RM-TRUTH-01 memory track, follow-up to §A2/§A5) — hermetic, every root a
synthetic tmp corpus (no mirror, no prod data/).

M3's §A2 (named-entity gate) and §A5 (alias layer) shipped in Wave 1, but a second rescore of
`questions.json` under the evidence-only rubric found two classes of defect still open:

1. `entities_missing` checked PLAIN SUBSTRING containment, so an entity like "PAT" was satisfied
   by "money-path" or the Python class name "Path" (the risk-engine's own vocabulary) — the gate
   never actually fired for several false-SUFFICIENT questions. A bare capitalised word ("ADR",
   "Director", "Telegram") is also common enough across the corpus that "present somewhere in the
   top-3 chunks' BODY text" is nearly always true, which made the gate close to a no-op for that
   class of entity.
2. The `kind=="roles"` ranking boost in `index.search()` was unconditional: a role's own passport
   (which legitimately names OTHER roles in its `may_not` list — e.g. Sherlock's "may not change
   Oracle policy") could win the ranking slot on a question that was not about that role at all.

Each test below is a positive control for one specific defect, on a fixed corpus — not a rerun of
the live `questions.json` benchmark (that lives in `docs/rm_truth/memory/`, outside pytest).
Invariant #16: every test here is new; nothing existing is loosened.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.studio_os.memory import assembler, index, sources


def _w(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- pure-function units (no corpus)

def test_word_boundary_entity_match_rejects_substring_inside_another_word():
    """The Wave-1 bug, reproduced directly: "PAT" must not be satisfied by "money-path" or "Path" —
    only by the whole word "pat"."""
    assert assembler._word_present("PAT", "the money-path moves slowly, see class Path") is False
    assert assembler._word_present("PAT", "rotate the PAT in Keychain") is True


def test_bare_adr_is_not_extracted_as_an_entity_but_a_numbered_one_is():
    """"ADR" alone names the whole registry (present in ~every canonical chunk's own title); a
    numbered reference is a real, specific identifier and must still be extracted."""
    ents = assembler._entities("Почему у нас два реестра ADR и какие номера сталкиваются?")
    assert "ADR" not in ents["generic"] and not any(e.upper() == "ADR" for e in ents["specific"])
    ents2 = assembler._entities("What does ADR-256 say about the registry?")
    assert "ADR-256" in ents2["specific"]


def test_entities_split_specific_vs_generic():
    ents = assembler._entities("Where did the Oracle CIO come from, see roles.json and ADR-554?")
    assert "ADR-554" in ents["specific"] and "roles.json" in ents["specific"]
    assert "Oracle" in ents["generic"]


# ---------------------------------------------------------------- end-to-end on a hermetic corpus

@pytest.fixture()
def w2corpus(tmp_path, monkeypatch):
    spa = tmp_path / "spa"
    for name in sources.DEFAULT_ROOTS:
        monkeypatch.setenv(f"SPA_MEMORY_ROOT_{name.upper()}", str(tmp_path / f"absent_{name}"))
    monkeypatch.setenv("SPA_MEMORY_ROOT_SPA", str(spa))
    monkeypatch.setenv("SPA_MEMORY_INDEX", str(tmp_path / "index.db"))
    _w(spa, "CLAUDE.md", "# Rules\n\nOwner-gated subjects: real money, public numbers, irreversible actions.\n")
    # a chunk that is NOT about PAT but contains the substring "pat" inside other words a lot —
    # the positive control for the word-boundary fix
    _w(spa, "docs/decisions/ADR-100-money-path-notes.md",
       "# ADR-100 Money path notes\n\nStatus: Accepted\n\n"
       "The money-path and the Path class move slowly today; nothing here rotates a credential.\n")
    # the chunk that is ACTUALLY about PAT rotation (title AND body both say it)
    _w(spa, "docs/decisions/ADR-200-pat-rotation.md",
       "# ADR-200 PAT rotation policy\n\nStatus: Accepted\n\nThe PAT rotates in Keychain regularly.\n")
    # "Director" mentioned only in passing, in BODY, by a chunk whose title/heading is unrelated
    _w(spa, "docs/decisions/ADR-300-unrelated.md",
       "# ADR-300 Unrelated billing cleanup\n\nStatus: Accepted\n\n"
       "This cleanup has nothing to do with the Director OS cockpit mentioned once here.\n")
    # the chunk that is ACTUALLY about Director OS (title says so)
    _w(spa, "docs/decisions/ADR-400-director-os.md",
       "# ADR-400 Director OS pilot\n\nStatus: Accepted\n\nDirector OS is a read-only cockpit.\n")
    # roles.json: two roles, Sherlock's own passport legitimately NAMES Oracle in `may_not`
    _w(spa, "architecture/roles.json", json.dumps({"roles": [
        {"role_id": "chief_investment_officer", "title": "Chief Investment Officer", "display_name": "Oracle",
         "domain": ["capital"], "implemented": True, "adr": ["ADR-900"], "authority": "NONE",
         "may": ["read evidence"], "may_not": ["move money"]},
        {"role_id": "head_of_research", "title": "Head of Research", "display_name": "Sherlock",
         "domain": ["research"], "implemented": True, "adr": ["ADR-901"], "authority": "NONE",
         "may": ["read evidence"], "may_not": ["change Oracle policy", "move money"]},
    ]}))
    _w(spa, "architecture/memory_aliases.json", json.dumps({"groups": [
        {"canonical": "chief_investment_officer", "names": [{"name": "Oracle"}, {"name": "Оракул"}, {"name": "CIO"}]},
        {"canonical": "head_of_research", "names": [{"name": "Sherlock"}, {"name": "Шерлок"}]},
    ]}))
    # the decision that is ACTUALLY what a generic "what did we decide about Oracle" should surface
    _w(spa, "docs/decisions/ADR-900-oracle-decision.md",
       "# ADR-900 Oracle capital allocation decision\n\nStatus: Accepted\n\n"
       "Oracle allocates capital advisory-only, never moves money.\n")
    # a decoy with NO mention of Oracle at all, but packed with the English auxiliary/preposition
    # words an EN phrasing of an origin/rename question uses ("did"/"was"/"from"/"come"/"called"/
    # "before") — under the old (un-stopped) weighting this decoy could out-rank the real Oracle
    # chunk for the EN query while the RU query (which never matches these English words) still
    # ranked the real chunk first, splitting RU/EN agreement. Purely a noise probe.
    _w(spa, "docs/decisions/ADR-950-unrelated-filler.md",
       "# ADR-950 Unrelated filler decision\n\nStatus: Accepted\n\n"
       "This was called that before, and it did come from somewhere, but was it called this before "
       "it came from there? It was. It did. Before it came, it was called something else.\n")
    _w(spa, "architecture/memory_truth.json", json.dumps({
        "overrides": [], "agents": [],
        "facts": [
            {"subject": "retired-thing", "status": "SUPERSEDED", "aliases": "retired old thing",
             "fact": "The old thing was retired and must never be cited as current.",
             "evidence": ["spa:docs/decisions/ADR-100-money-path-notes.md"]},
            {"subject": "current-thing", "status": "ACTIVE", "aliases": "current thing live",
             "fact": "The current thing is live and citable.",
             "evidence": ["spa:docs/decisions/ADR-200-pat-rotation.md"]},
        ]}))
    return tmp_path


def test_substring_entity_no_longer_satisfied_by_an_unrelated_chunk(w2corpus):
    """Wave-1 reproduction: a question naming "PAT" must not be marked SUFFICIENT off a chunk that
    only contains "money-path"/"Path" — those are different words, not evidence."""
    index.build()
    pkg = assembler.assemble("What PAT rotation policy do we have?")
    es = pkg["evidence_sufficiency"]
    # the real PAT chunk is in the corpus and small enough to be retrieved and cover the query —
    # entity gate must not demote a CORRECT match
    assert "PAT" not in es["entities_missing"]
    assert es["verdict"] == "SUFFICIENT"


@pytest.fixture()
def w2_body_only_corpus(tmp_path, monkeypatch):
    """Isolated positive control: the ONLY document in the corpus mentions "Director" in its BODY
    (not its title/heading) — the real Director OS decision does not exist here at all. This is
    what tells apart the Wave-1 bug from the fix: the old (body-wide, substring) check would mark
    this SUFFICIENT off the wrong chunk; the new (title/heading) check cannot."""
    spa = tmp_path / "spa"
    for name in sources.DEFAULT_ROOTS:
        monkeypatch.setenv(f"SPA_MEMORY_ROOT_{name.upper()}", str(tmp_path / f"absent_{name}"))
    monkeypatch.setenv("SPA_MEMORY_ROOT_SPA", str(spa))
    monkeypatch.setenv("SPA_MEMORY_INDEX", str(tmp_path / "index.db"))
    _w(spa, "CLAUDE.md", "# Rules\n\nOwner-gated subjects: real money, public numbers, irreversible actions.\n")
    _w(spa, "docs/decisions/ADR-300-unrelated.md",
       "# ADR-300 Unrelated billing cleanup\n\nStatus: Accepted\n\n"
       "This billing cleanup OS has nothing to do with the Director OS cockpit mentioned once here.\n")
    return tmp_path


def test_generic_proper_noun_in_body_only_is_not_enough(w2_body_only_corpus):
    """"Director" appearing only in the BODY of the one retrievable chunk must not satisfy the
    entity gate — the gate requires the TITLE/HEADING of a top-3 chunk to say so, and this corpus's
    only document's title ("Unrelated billing cleanup") does not."""
    index.build()
    pkg = assembler.assemble("What is Director OS?")
    es = pkg["evidence_sufficiency"]
    assert "Director" in es["entities_missing"]
    assert es["verdict"] != "SUFFICIENT"


def test_generic_proper_noun_in_the_title_is_enough(w2corpus):
    """Companion/contrast to the test above, on the full corpus where the REAL Director OS decision
    (ADR-400, title says so) exists and out-ranks the decoy: the gate must not over-trigger when
    the match is genuine."""
    index.build()
    pkg = assembler.assemble("What is Director OS?")
    es = pkg["evidence_sufficiency"]
    refs = {s["ref"] for s in pkg["sources"]}
    assert "spa:docs/decisions/ADR-400-director-os.md" in refs
    assert "Director" not in es["entities_missing"]


def test_role_boost_fires_only_when_the_question_names_a_role(w2corpus):
    """`index._query_names_role` must be true for a question naming the alias and false for a
    generic question that happens to share ordinary words with a role passport. Hermetic (the
    `w2corpus` fixture points every root away from the real mirror) — this reads `roles.json` and
    `memory_aliases.json`, not the index, so it needs no `index.build()`."""
    assert index._query_names_role("Who is Oracle and what may it not do?") is True
    assert index._query_names_role("Кто такой Шерлок?") is True
    assert index._query_names_role("What is the weather like today?") is False


def test_sherlocks_passing_mention_of_oracle_does_not_win_an_oracle_question(w2corpus):
    """End-to-end sanity check (not, on this small corpus, a discriminating positive control —
    Oracle's own chunk already wins here on word-coverage alone before any role boost is applied):
    a question that names "Oracle" must rank Oracle's OWN passport or the Oracle decision ahead of
    Sherlock's passport, even though Sherlock's `may_not` text also contains the word "Oracle"."""
    index.build()
    rows = index.search("Кто такой Oracle и что он не может?", k=5)
    top_paths = [r["path"] for r in rows[:2]]
    assert "architecture/roles.json" in top_paths or "docs/decisions/ADR-900-oracle-decision.md" in top_paths
    # Sherlock's passport must not be the #1 result for an Oracle question
    assert rows[0]["heading"].find("head_of_research") == -1


def test_ru_and_en_phrasing_of_an_alias_question_rank_the_same_top_result(w2corpus):
    """ADR-591 §Wave2 point 2: the alias layer was already OR-expanding "Oracle"/"Оракул" into the
    FTS query correctly (that was never the defect) — what broke RU/EN agreement was that the
    English phrasing carried several extra weight=1.0 function words ("did", "was", "from", "come",
    "called") that the Russian phrasing's STOP list already excluded, diluting the one real concept
    with noise the Russian twin never had. Fixed by extending STOP/WEAK, not by touching the alias
    file. Positive control: both phrasings must rank the SAME document first."""
    index.build()
    ru = index.search("Откуда взялся Oracle и как он раньше назывался?", k=1)
    en = index.search("Where did Oracle come from and what was it called before?", k=1)
    assert ru and en
    assert ru[0]["path"] == en[0]["path"]


def test_superseded_fact_excluded_from_semantic_facts(w2corpus):
    """ADR-591 §Wave2 point 4: a `memory_truth.json` fact whose OWN status is SUPERSEDED must never
    be handed to a caller inside `semantic_facts` — that section is the one `TRUTH_POLICY` tells a
    reader to trust outright."""
    index.build()
    pkg = assembler.assemble("Tell me about the retired old thing and the current thing")
    subjects = {f["subject"] for f in pkg["semantic_facts"]}
    assert "retired-thing" not in subjects
    assert "current-thing" in subjects
