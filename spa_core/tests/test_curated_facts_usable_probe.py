"""spa_core/tests/test_curated_facts_usable_probe.py — the `curated_facts_usable` acceptance probe.

Green on an intact copy of the curated-fact registry, red on every way a named fact can stop being evidence
(edited after review, review record removed, unknown id, prefix of a real id), and NOT MEASURED — never green —
when the registry itself cannot be loaded (.claude/rules/acceptance.md rule 3). Runs on a COPY of the registry;
the live file is never touched and its future state does not decide this test.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.research_factory import registry_loader

REAL_REGISTRY = Path(registry_loader.default_facts_path()).parent


@pytest.fixture
def registry_copy(tmp_path):
    dst = tmp_path / "registry"
    shutil.copytree(REAL_REGISTRY, dst)
    return dst


def _usable_ids(registry: Path) -> list:
    return [f["fact_id"] for f in registry_loader.load_facts(registry / "facts.jsonl",
                                                               origins=registry_loader.load_origins())]


def _probe(arg, registry: Path):
    return ca._probe_curated_facts_usable(arg, facts_path=str(registry / "facts.jsonl"))


def test_registered():
    assert ca.PROBES["curated_facts_usable"] is ca._probe_curated_facts_usable


def test_intact_named_facts_are_satisfied(registry_copy):
    ids = _usable_ids(registry_copy)[:3]
    assert len(ids) == 3, "premise: the copy must contain usable facts"
    verdict, detail = _probe("+".join(ids), registry_copy)
    assert verdict == ca.SATISFIED, detail


def test_a_fact_edited_after_review_is_named_not_usable(registry_copy):
    fid = _usable_ids(registry_copy)[0]
    path = registry_copy / "facts.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for row in rows:
        if row["fact_id"] == fid:
            row["quote"] = (row.get("quote") or "") + " (edited after review)"
    path.write_text("\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows) + "\n")
    verdict, detail = _probe(fid, registry_copy)
    assert verdict == ca.NOT_SATISFIED, detail
    assert f"{fid}: " in detail and "fact_sha256" in detail


def test_a_fact_whose_review_record_is_gone_is_not_usable(registry_copy):
    fid = _usable_ids(registry_copy)[0]
    for rec in (registry_copy / "fact_reviews").glob("*.json"):
        doc = json.loads(rec.read_text())
        doc["facts"] = [e for e in doc["facts"] if e["fact_id"] != fid]
        rec.write_text(json.dumps(doc))
    verdict, detail = _probe(fid, registry_copy)
    assert verdict == ca.NOT_SATISFIED, detail
    assert "no committed review record" in detail


@pytest.mark.parametrize("arg", ["fact-does-not-exist", "fact-00"])
def test_unknown_or_prefix_id_is_not_usable(arg, registry_copy):
    verdict, detail = _probe(arg, registry_copy)
    assert verdict == ca.NOT_SATISFIED, detail
    assert f"{arg}: нет в реестре" in detail


def test_one_bad_id_among_good_ones_fails_the_whole_criterion(registry_copy):
    good = _usable_ids(registry_copy)[0]
    verdict, detail = _probe(f"{good}+fact-does-not-exist", registry_copy)
    assert verdict == ca.NOT_SATISFIED, detail
    assert good not in detail


def test_no_ids_and_an_unloadable_registry_are_unmeasured(registry_copy):
    assert _probe(None, registry_copy)[0] == ca.UNMEASURED
    (registry_copy / "facts.jsonl").write_text("{not json\n")
    verdict, detail = _probe(_usable_ids(REAL_REGISTRY)[0], registry_copy)
    assert verdict == ca.UNMEASURED, detail


def test_range_form_requires_every_index(registry_copy):
    ids = _usable_ids(registry_copy)
    nums = sorted(int(i.split("-")[1]) for i in ids)
    lo = nums[0]
    hi = lo
    while hi + 1 in nums:
        hi += 1
    verdict, detail = _probe(f"fact-{lo:03d}..fact-{hi:03d}", registry_copy)
    assert verdict == ca.SATISFIED, detail
    verdict, detail = _probe(f"fact-{lo:03d}..fact-{hi + 1:03d}", registry_copy)  # one past the run
    assert verdict == ca.NOT_SATISFIED, detail
    assert f"fact-{hi + 1:03d}-" in detail

