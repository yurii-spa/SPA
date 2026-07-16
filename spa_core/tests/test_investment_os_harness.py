"""spa_core/tests/test_investment_os_harness.py — AI Investment OS product-agent harness (AAA step 2).

Proves the universal analyst contract: feeds fail-CLOSED to UNKNOWN, evidence tags are honest, the
OPTIONAL LLM is gated (an unsourced number discards the LLM output), and emit writes an advisory-stamped
artifact + proof to a namespaced dir (never runtime state). PURE / no network / sandbox data dir only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone

from spa_core.investment_os import harness as H
from spa_core.investment_os.harness import ProductAgent, UNKNOWN


def _dt(day=1, h=12):
    return datetime(2026, 7, day, h, 0, tzinfo=timezone.utc)


# ── feeds (fail-closed) ──────────────────────────────────────────────────────
def test_read_feed_ok():
    assert ProductAgent.read_feed(lambda: {"apy": 3.3}) == {"apy": 3.3}


def test_read_feed_error_is_unknown():
    def boom():
        raise RuntimeError("feed down")
    assert ProductAgent.read_feed(boom) == UNKNOWN


def test_read_feed_none_is_unknown():
    assert ProductAgent.read_feed(lambda: None) == UNKNOWN


def test_read_feed_stale_is_unknown():
    now = _dt(day=10)
    old_mtime = _dt(day=1).timestamp()          # 9 days old
    val = ProductAgent.read_feed(lambda: {"x": 1}, max_age_s=86400, mtime=old_mtime, now=now)
    assert val == UNKNOWN


def test_read_feed_fresh_passes():
    now = _dt(day=10)
    fresh_mtime = _dt(day=10, h=11).timestamp()  # 1h old
    val = ProductAgent.read_feed(lambda: {"x": 1}, max_age_s=86400, mtime=fresh_mtime, now=now)
    assert val == {"x": 1}


# ── evidence tagging ─────────────────────────────────────────────────────────
def test_evidence_valid_level():
    e = ProductAgent.evidence(3.3, "L6", "live paper track", now=_dt())
    assert e["value"] == 3.3 and e["evidence_level"] == "L6" and e["source"]


def test_evidence_invalid_level_flagged_not_upgraded():
    e = ProductAgent.evidence(1.0, "L9", "x")
    assert e["evidence_level"] == "L9?"          # never silently accepted


def test_evidence_unknown_value_kept():
    e = ProductAgent.evidence(UNKNOWN, "L0", "missing feed")
    assert e["value"] == UNKNOWN


# ── optional LLM reasoning behind the number-gate ────────────────────────────
class _FakeLLM:
    def __init__(self, out):
        self._out = out
    def ask(self, prompt, context=None):
        return self._out


def _agent(tmp_path, allow_llm=True, key="stablecoin_yield"):
    a = ProductAgent(data_dir=tmp_path, allow_llm=allow_llm)
    a.agent_key = key
    return a


def test_reason_llm_off_returns_fallback(tmp_path):
    a = _agent(tmp_path, allow_llm=False)
    out = a.reason("say it", {"apy": 3.3}, deterministic_fallback="DRY")
    assert out == "DRY"


def test_reason_forbidden_key_returns_fallback(tmp_path):
    a = _agent(tmp_path, key="risk")  # risk is in LLM_FORBIDDEN_AGENTS
    a._llm = _FakeLLM("~3.3% realized")
    out = a.reason("x", {"apy": 3.3}, deterministic_fallback="DRY")
    assert out == "DRY"


def test_reason_unsourced_number_discards_llm(tmp_path):
    a = _agent(tmp_path)
    a._llm = _FakeLLM("A stellar ~9.9% return!")   # 9.9 not in facts
    out = a.reason("x", {"apy": 3.3, "band": 6}, deterministic_fallback="DRY ~3.3%")
    assert out == "DRY ~3.3%"                       # LLM discarded, fallback kept


def test_reason_sourced_numbers_pass(tmp_path):
    a = _agent(tmp_path)
    a._llm = _FakeLLM("Realized ~3.3% toward a 6% band.")
    out = a.reason("x", {"apy": 3.3, "band": 6}, deterministic_fallback="DRY")
    assert out == "Realized ~3.3% toward a 6% band."


# ── emit artifact + proof ────────────────────────────────────────────────────
def test_emit_writes_advisory_artifact_and_proof(tmp_path):
    a = _agent(tmp_path)
    path = a.emit({"headline_apy": {"value": 3.3, "evidence_level": "L6"}}, now=_dt())
    doc = json.loads(path.read_text())
    assert doc["is_advisory"] is True
    assert doc["agent"] == "stablecoin_yield"
    assert doc["consumer_contract"] and doc["generated_at"]
    assert doc["headline_apy"]["value"] == 3.3
    proof = tmp_path / "stablecoin_yield_proof.jsonl"
    assert proof.exists()
    lines = [l for l in proof.read_text().splitlines() if l.strip()]
    assert len(lines) == 1 and json.loads(lines[0])["hash"]


def test_emit_proof_idempotent_per_day(tmp_path):
    a = _agent(tmp_path)
    a.emit({"x": 1}, now=_dt(day=5, h=9))
    a.emit({"x": 2}, now=_dt(day=5, h=18))   # same UTC day → no second proof line
    proof = tmp_path / "stablecoin_yield_proof.jsonl"
    lines = [l for l in proof.read_text().splitlines() if l.strip()]
    assert len(lines) == 1


# ── run() cycle ──────────────────────────────────────────────────────────────
def test_run_analyze_exception_emits_unknown(tmp_path):
    class Broken(ProductAgent):
        agent_key = "broken"
        def analyze(self):
            raise ValueError("boom")
    b = Broken(data_dir=tmp_path)
    path = b.run(now=_dt())
    doc = json.loads(path.read_text())
    assert doc["status"] == UNKNOWN and doc["is_advisory"] is True


def test_run_happy_path(tmp_path):
    class Ok(ProductAgent):
        agent_key = "ok"
        def analyze(self):
            return {"status": "ok", "apy": self.evidence(3.3, "L6", "track")}
    path = Ok(data_dir=tmp_path).run(now=_dt())
    doc = json.loads(path.read_text())
    assert doc["status"] == "ok" and doc["apy"]["evidence_level"] == "L6"
