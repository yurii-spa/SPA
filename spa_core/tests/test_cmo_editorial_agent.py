"""spa_core/tests/test_cmo_editorial_agent.py — CMO editorial DRAFT runner (the live agent).

The runner reads the live track facts (ledger + hash-chained refusal log) and delegates to the prior
CMO pipeline (template_rewriter → honesty_gate → draft_store). It NEVER reimplements the rewrite/gate and
NEVER publishes. Fail-CLOSED on no data. PURE / no network / no LLM / sandbox dirs only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone

from spa_core.cmo import editorial_agent as E
from spa_core.cmo.draft_store import DraftStore


def _dt(day=17):
    return datetime(2026, 7, day, 9, 0, tzinfo=timezone.utc)


def _seed(tmp_path, *, days=24, cum=0.46, dd=0.0, refusals=7, entries=41):
    ledger = tmp_path / "track_ledger.json"
    ledger.write_text(json.dumps({
        "n_evidenced_days": days, "days_needed": 30,
        "cumulative_return_pct": cum, "max_drawdown_from_peak_pct": dd,
    }), encoding="utf-8")
    dec = tmp_path / "decision_log.jsonl"
    lines = []
    for i in range(entries):
        lines.append(json.dumps({"approved": (i >= refusals)}))  # first `refusals` are declined
    dec.write_text("\n".join(lines), encoding="utf-8")
    return ledger, dec


def test_load_source_facts_from_track_and_refusals(tmp_path):
    ledger, dec = _seed(tmp_path)
    facts = E.load_source_facts(ledger_path=ledger, decisions_path=dec)
    assert facts["n_evidenced_days"] == 24
    assert facts["days_needed"] == 30
    assert facts["cumulative_return_pct"] == 0.46
    assert facts["refusal_count"] == 7 and facts["decision_count"] == 41


def test_no_source_data_fail_closed(tmp_path):
    missing_ledger = tmp_path / "none.json"
    missing_dec = tmp_path / "none.jsonl"
    assert E.load_source_facts(ledger_path=missing_ledger, decisions_path=missing_dec) is None
    res = E.run(now=_dt(), drafts_dir=tmp_path / "drafts",
                ledger_path=missing_ledger, decisions_path=missing_dec)
    assert res["created"] is False and "fail-closed" in res["reason"]


def test_run_creates_draft_via_pipeline(tmp_path):
    ledger, dec = _seed(tmp_path)
    ddir = tmp_path / "drafts"
    res = E.run(now=_dt(), drafts_dir=ddir, ledger_path=ledger, decisions_path=dec)
    assert res["created"] is True
    assert res["draft_id"]
    assert res["status"] == "draft"
    # a draft file was persisted by the prior DraftStore
    stored = list(ddir.glob("cmo_*.json"))
    assert stored, "pipeline should have stored a draft via DraftStore"


def test_stored_draft_is_gated_and_never_published(tmp_path):
    ledger, dec = _seed(tmp_path)
    ddir = tmp_path / "drafts"
    E.run(now=_dt(), drafts_dir=ddir, ledger_path=ledger, decisions_path=dec)
    store = DraftStore(ddir)
    drafts = store.list_drafts()
    assert drafts
    # flow B: a fresh draft is status "draft" — never auto "published"
    assert all(d.status == "draft" for d in drafts)


def test_check_dry_run_does_not_store(tmp_path):
    ledger, dec = _seed(tmp_path)
    ddir = tmp_path / "drafts"
    res = E.run(now=_dt(), write=False, drafts_dir=ddir, ledger_path=ledger, decisions_path=dec)
    assert res["created"] is False
    assert "gate_passed" in res
    assert not ddir.exists() or not list(ddir.glob("cmo_*.json"))  # nothing persisted


def test_refusal_only_data_still_builds(tmp_path):
    # ledger missing but refusal log present → refusal-only facts still produce a draft (fail-open on
    # partial real data, never fabricated).
    missing_ledger = tmp_path / "none.json"
    dec = tmp_path / "decision_log.jsonl"
    dec.write_text("\n".join(json.dumps({"approved": i >= 3}) for i in range(10)), encoding="utf-8")
    facts = E.load_source_facts(ledger_path=missing_ledger, decisions_path=dec)
    assert facts is not None and facts["refusal_count"] == 3 and "n_evidenced_days" not in facts
