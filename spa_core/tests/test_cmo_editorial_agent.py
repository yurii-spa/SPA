"""spa_core/tests/test_cmo_editorial_agent.py — CMO editorial draft agent (AAA step 3).

Proves the first live product-layer agent: dry changelog facts → richer copy → honesty-gate → DRAFT
(never published). Fail-CLOSED on no data; every number sourced (gate passes); gate failure → HELD, not
published; idempotent per source. PURE / no network / no LLM / sandbox dirs only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from spa_core.cmo import editorial_agent as E
from spa_core.cmo import honesty_gate

_ENTRY = {
    "slug": "changelog-2026-07-16",
    "date": "2026-07-16",
    "title": "Track & refusal digest — 2026-07-16",
    "titleRu": "Дайджест трека и отказов — 2026-07-16",
    "summary": ("Evidenced paper track: 24/30 days (cumulative +0.46%, max drawdown 0.00%). "
                "Refusal log: 7 declined of 41 hash-chained decisions. Paper research, advisory."),
    "summaryRu": ("Evidenced paper-трек: 24/30 дней (кумулятивно +0.46%, макс. просадка 0.00%). "
                  "Журнал отказов: 7 отклонено из 41 hash-chained решений. Paper-исследование, advisory."),
    "evidence": "L4 · evidenced track + hash-chained refusal log",
    "_sig": {"last": "2026-07-16", "n_days": 24, "refusals": 7},
}


def _dt(day=17):
    return datetime(2026, 7, day, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def changelog(tmp_path, monkeypatch):
    p = tmp_path / "changelog.json"
    p.write_text(json.dumps([_ENTRY]), encoding="utf-8")
    monkeypatch.setattr(E, "_CHANGELOG", p)
    return p


def test_build_draft_passes_gate_and_is_draft(changelog):
    d = E.build_draft(now=_dt())
    assert d is not None
    assert d["honesty_gate_passed"] is True
    assert d["status"] == "draft"
    assert d["is_advisory"] is True
    assert d["rewrite"] == "deterministic-template"


def test_draft_body_only_has_sourced_numbers(changelog):
    d = E.build_draft(now=_dt())
    # every number in the rewritten body must appear in the source entry (honesty gate contract)
    for body in (d["body_en"], d["body_ru"]):
        r = honesty_gate.check(body, _ENTRY)
        assert r.unmatched_numbers == [], r.unmatched_numbers


def test_draft_carries_all_disclaimers(changelog):
    d = E.build_draft(now=_dt())
    r = honesty_gate.check(d["body_en"], _ENTRY)
    assert r.missing_disclaimers == []
    assert not r.promissory_hits and not r.solicitation_hits


def test_no_source_data_fail_closed(tmp_path, monkeypatch):
    empty = tmp_path / "none.json"
    monkeypatch.setattr(E, "_CHANGELOG", empty)   # file does not exist
    assert E.build_draft(now=_dt()) is None
    res = E.run(now=_dt(), drafts_dir=tmp_path / "drafts")
    assert res["created"] is False and "fail-closed" in res["reason"]


def test_run_writes_draft_and_proof(changelog, tmp_path):
    ddir = tmp_path / "drafts"
    res = E.run(now=_dt(), drafts_dir=ddir)
    assert res["created"] is True and res["status"] == "draft"
    out = ddir / "2026-07-17.json"
    assert out.exists()
    doc = json.loads(out.read_text())
    assert doc["is_advisory"] is True and doc["status"] == "draft"
    proof = ddir / "cmo_editorial_proof.jsonl"
    assert proof.exists() and json.loads(proof.read_text().splitlines()[0])["hash"]


def test_run_idempotent_per_source(changelog, tmp_path):
    ddir = tmp_path / "drafts"
    E.run(now=_dt(), drafts_dir=ddir)
    res2 = E.run(now=_dt(), drafts_dir=ddir)   # same source_slug → not recreated
    assert res2["created"] is False and "unchanged source" in res2["reason"]


def test_gate_failure_holds_not_publishes(changelog, monkeypatch):
    # Force the gate to fail on everything → draft must be HELD, never publish-eligible.
    from spa_core.cmo.honesty_gate import GateResult
    monkeypatch.setattr(E.honesty_gate, "check",
                        lambda *a, **k: GateResult(passed=False, reasons=["forced"]))
    d = E.build_draft(now=_dt())
    assert d["status"] == "held" and d["honesty_gate_passed"] is False


def test_check_cli_does_not_write(changelog, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(E, "_DRAFTS_DIR", tmp_path / "drafts")
    rc = E.main(["--check"])
    assert rc == 0
    assert not (tmp_path / "drafts").exists()   # --check never writes
    out = capsys.readouterr().out
    assert "honesty_gate_passed" in out
