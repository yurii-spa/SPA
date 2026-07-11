"""Tests for the Q2-8 pilot pipeline tracker (spa_core/pilot/pipeline.py).

Verifies the funnel state machine (legal transitions advance, illegal ones fail-closed), the DD-artifact
flag, the deterministic summary rollup, PII-minimal label enforcement (emails/free-form rejected), and
idempotent add. Uses a tmp store — no live data.
"""
import json

import pytest

from spa_core.pilot import pipeline as pp


@pytest.fixture()
def store(tmp_path):
    return tmp_path / "prospects.json"


def test_add_and_summary(store):
    pp.add_prospect("partner-A", now_iso="2026-07-11T00:00:00Z", store=store)
    s = pp.summary(store=store)
    assert s["n_prospects"] == 1
    assert s["by_stage"]["LEAD"] == 1
    assert s["pii_minimal"] is True and s["is_advisory"] is True


def test_idempotent_add(store):
    a = pp.add_prospect("partner-A", now_iso="t0", store=store)
    b = pp.add_prospect("partner-A", now_iso="t1", store=store)
    assert a["label"] == b["label"]
    assert pp.summary(store=store)["n_prospects"] == 1


def test_legal_transition_advances(store):
    pp.add_prospect("p", now_iso="t0", store=store)
    pp.advance_stage("p", "DD_SENT", now_iso="t1", store=store)
    pp.advance_stage("p", "DILIGENCE", now_iso="t2", store=store)
    pp.advance_stage("p", "COMMITTED", now_iso="t3", store=store)
    assert pp.summary(store=store)["by_stage"]["COMMITTED"] == 1


def test_illegal_transition_fail_closed(store):
    pp.add_prospect("p", now_iso="t0", store=store)
    # LEAD → COMMITTED skips the funnel → refused
    with pytest.raises(pp.PilotError):
        pp.advance_stage("p", "COMMITTED", now_iso="t1", store=store)
    # committed is terminal → cannot move on
    pp.advance_stage("p", "DD_SENT", now_iso="t1", store=store)
    pp.advance_stage("p", "DILIGENCE", now_iso="t2", store=store)
    pp.advance_stage("p", "COMMITTED", now_iso="t3", store=store)
    with pytest.raises(pp.PilotError):
        pp.advance_stage("p", "CONVERSATION", now_iso="t4", store=store)


def test_declined_can_revive_to_lead(store):
    pp.add_prospect("p", now_iso="t0", store=store)
    pp.advance_stage("p", "DECLINED", now_iso="t1", store=store)
    pp.advance_stage("p", "LEAD", now_iso="t2", store=store)   # revival allowed
    assert pp.list_prospects(store=store)[0]["stage"] == "LEAD"


def test_mark_dd_sent_sets_flag_and_stage(store):
    pp.add_prospect("p", now_iso="t0", store=store)
    r = pp.mark_dd_sent("p", now_iso="t1", store=store)
    assert r["dd_artifact_sent"] is True
    assert r["stage"] == "DD_SENT"
    assert pp.summary(store=store)["n_dd_sent"] == 1


def test_pii_labels_rejected(store):
    for bad in ("john@fund.com", "John Smith, Acme Capital!!!", "x" * 65):
        with pytest.raises(pp.PilotError):
            pp.add_prospect(bad, now_iso="t0", store=store)


def test_unknown_prospect_fail_closed(store):
    with pytest.raises(pp.PilotError):
        pp.advance_stage("ghost", "DD_SENT", now_iso="t0", store=store)


def test_malformed_store_loads_empty(store):
    store.write_text("{not json")
    assert pp.summary(store=store)["n_prospects"] == 0
