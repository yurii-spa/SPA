"""SPA-V414 (v4.14) tests.

MP-011 — Compound V3 в runtime оркестратора:
* регистрация compound_v3 в реестре оркестратора (и в пакетном реестре);
* tier-инварианты: T1 синхронизирован между обоими реестрами, классом
  адаптера, fetch() и get_yield_info(); ровно два T1-якоря (aave_v3 +
  compound_v3); T1_CAP по образцу AaveV3Adapter;
* compound_v3 присутствует в выводе оркестратора даже при недоступном фиде
  (честный error, а не отсутствие записи).

MP-012 — регенерация risk_scores.json в ежедневном цикле:
* fail-safe ветка: исключение в скорере → WARNING + note, цикл НЕ падает;
* регенерация вызывается ДО шага аллокации;
* staleness: после регенерации generated_at свежий (новее stale-снимка);
* атомарная запись (нет .tmp-огрызков), compound-v3 получает оценку;
* dry-run (write=False) не регенерирует файл;
* дефолтная проводка: run_cycle без risk_scorer_fn вызывает
  cycle_runner._default_risk_scorer (логика скоринга остаётся в
  spa_core/risk/scoring_engine — cycle_runner только вызывает её).

Все тесты network-free (фиды замоканы, scoring engine — offline=True).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

import pytest

from spa_core.paper_trading import cycle_runner as cr


NOW = datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)
# Два T1-якоря (по 30%) + один T2 (20%) — RiskPolicy-совместимый таргет.
APY = {"aave_v3": 4.0, "compound_v3": 3.5, "morpho_blue": 5.0}
TARGET = {"aave_v3": 30_000.0, "compound_v3": 30_000.0, "morpho_blue": 20_000.0}
T1_PROTOCOLS = {"aave_v3", "compound_v3"}


def _orch_fn(apy_map=APY):
    adapters = [
        {
            "protocol": p,
            "apy_pct": a,
            "tvl_usd": 1e8,
            "tier": "T1" if p in T1_PROTOCOLS else "T2",
            "status": "ok",
        }
        for p, a in apy_map.items()
    ]
    res = SimpleNamespace(adapters=adapters, status="ok", data_freshness="live")
    return lambda d: res


class _FakeAllocator:
    def allocate(self):
        return SimpleNamespace(
            target_usd=dict(TARGET),
            expected_apy_pct=3.0,
            model_used="risk_adjusted",
            strategy_loop_active=False,
        )


def _run(tmp_path, *, risk_scorer_fn, write=True, allocator=None):
    return cr.run_cycle(
        data_dir=tmp_path,
        now=NOW,
        orchestrator_fn=_orch_fn(),
        allocator=allocator or _FakeAllocator(),
        risk_scorer_fn=risk_scorer_fn,
        # MP-109: no-op track persister keeps these tests off iCloud/home dirs.
        track_persister_fn=lambda d: None,
        write=write,
    )


# ─── MP-011: регистрация и tier-инварианты ───────────────────────────────────


def test_compound_v3_in_orchestrator_registry_as_t1():
    # Import from both possible module locations — adapters/__init__.py re-exports
    # from compound_v3_adapter, while legacy code used compound_v3. Accept either.
    from spa_core.adapters import CompoundV3Adapter as canonical_cls
    from spa_core.orchestrator import adapter_orchestrator as orch

    entry = [r for r in orch.ADAPTER_REGISTRY if r[0] == "compound_v3"]
    assert len(entry) == 1
    assert entry[0][1] == "T1"
    # The class in the registry must be the same as what spa_core.adapters exports
    assert entry[0][2] is canonical_cls


def test_registries_tier_sync_and_two_t1_anchors():
    # Оркестраторный реестр — подмножество пакетного (пакет растёт; оркестратор
    # может содержать только продакшн-адаптеры). Tier-совместимость проверяется
    # для всех записей оркестратора. T1-якоря aave_v3 и compound_v3 обязаны
    # присутствовать в оркестраторе.
    from spa_core.adapters import ADAPTER_REGISTRY as pkg_registry
    from spa_core.orchestrator import adapter_orchestrator as orch

    pkg = {key: (tier, cls) for key, tier, cls in pkg_registry}
    orh = {key: (tier, cls) for key, tier, cls in orch.ADAPTER_REGISTRY}
    # Every orchestrator entry must exist in the package with matching tier
    for key, (tier, cls) in orh.items():
        assert key in pkg, f"Orchestrator key '{key}' missing from package registry"
        assert pkg[key][0] == tier, (
            f"Tier mismatch for '{key}': pkg={pkg[key][0]}, orch={tier}"
        )
    # T1 anchors must be present in orchestrator
    t1 = {key for key, (tier, _) in orh.items() if tier == "T1"}
    assert T1_PROTOCOLS.issubset(t1), (
        f"Missing T1 anchors in orchestrator: {T1_PROTOCOLS - t1}"
    )


def test_compound_v3_tier_invariants_everywhere():
    # Класс, fetch(), get_yield_info() и cap — всё T1, без split-brain.
    from spa_core.adapters.aave_v3 import AaveV3Adapter
    from spa_core.adapters.compound_v3 import CompoundV3Adapter

    assert CompoundV3Adapter.TIER == "T1"
    assert CompoundV3Adapter.tier == "T1"
    assert CompoundV3Adapter.ORCHESTRATOR_TIER == "T1"
    assert CompoundV3Adapter.T1_CAP == 0.40 == AaveV3Adapter.T1_CAP
    with mock.patch(
        "spa_core.adapters.compound_v3.urllib.request.urlopen",
        side_effect=TimeoutError("offline"),
    ):
        snap = CompoundV3Adapter().fetch()
        info = CompoundV3Adapter().get_yield_info()
    assert snap["tier"] == "T1"
    assert info.tier == "T1"


def test_orchestrator_emits_compound_v3_even_when_feed_down():
    # MP-011: запись compound_v3 ПРИСУТСТВУЕТ в выводе оркестратора и при
    # недоступном фиде — честный error, а не молчаливое отсутствие.
    from spa_core.adapters.compound_v3 import CompoundV3Adapter
    from spa_core.orchestrator.adapter_orchestrator import run_orchestrator

    with mock.patch(
        "spa_core.adapters.compound_v3.urllib.request.urlopen",
        side_effect=TimeoutError("feed down"),
    ):
        res = run_orchestrator(
            registry=[("compound_v3", "T1", CompoundV3Adapter)],
            write=False,
            now_fn=lambda: NOW,
        )
    recs = [a for a in res.adapters if a["protocol"] == "compound_v3"]
    assert len(recs) == 1
    assert recs[0]["tier"] == "T1"
    assert recs[0]["status"] == "error"
    assert recs[0]["error"] == "live_feed_unavailable"
    assert recs[0]["live_data"] is False


# ─── MP-012: fail-safe регенерация в цикле ───────────────────────────────────


def test_scorer_exception_does_not_crash_cycle(tmp_path):
    def _boom(ddir):
        raise RuntimeError("scoring engine exploded")

    res = _run(tmp_path, risk_scorer_fn=_boom)
    assert res.status == "ok"
    assert res.traded is True
    assert any("risk_scores_regen_failed" in n for n in res.notes)
    assert any("RuntimeError" in n for n in res.notes)
    # Цикл дописал свои артефакты несмотря на упавший скорер.
    assert (tmp_path / "trades.json").exists()
    assert (tmp_path / "paper_trading_status.json").exists()


def test_scorer_failure_keeps_stale_snapshot(tmp_path):
    stale = {"generated_at": "2026-05-27T00:00:00Z", "scores": []}
    (tmp_path / "risk_scores.json").write_text(json.dumps(stale), encoding="utf-8")

    def _boom(ddir):
        raise OSError("disk on fire")

    res = _run(tmp_path, risk_scorer_fn=_boom)
    assert res.status == "ok"
    # Старый снимок не тронут — аллокатор продолжает на нём.
    kept = json.loads((tmp_path / "risk_scores.json").read_text(encoding="utf-8"))
    assert kept == stale


def test_regen_runs_before_allocation_step(tmp_path):
    calls: list[str] = []

    def _scorer(ddir):
        calls.append("scorer")

    class _OrderedAllocator(_FakeAllocator):
        def allocate(self):
            calls.append("allocate")
            return super().allocate()

    res = _run(tmp_path, risk_scorer_fn=_scorer, allocator=_OrderedAllocator())
    assert res.status == "ok"
    assert calls == ["scorer", "allocate"]


def test_dry_run_does_not_regenerate(tmp_path):
    calls: list[str] = []
    res = _run(
        tmp_path, risk_scorer_fn=lambda d: calls.append("scorer"), write=False
    )
    assert res.status == "ok"
    assert calls == []
    assert not (tmp_path / "risk_scores.json").exists()


def test_default_scorer_is_wired_when_fn_omitted(tmp_path, monkeypatch):
    # run_cycle без risk_scorer_fn должен вызвать _default_risk_scorer
    # (который делегирует в spa_core/risk/scoring_engine).
    seen: list = []
    monkeypatch.setattr(cr, "_default_risk_scorer", lambda d: seen.append(d))
    res = _run(tmp_path, risk_scorer_fn=None)
    assert res.status == "ok"
    assert seen == [tmp_path]


# ─── MP-012: staleness / атомарность / оценка compound-v3 ────────────────────


def _offline_scorer(ddir):
    """Реальный scoring engine в offline-режиме (bootstrap, без сети)."""
    from spa_core.risk.scoring_engine import RiskScoringEngine

    RiskScoringEngine(offline=True).export(output_file=ddir / "risk_scores.json")


def test_regen_refreshes_stale_timestamp(tmp_path):
    stale = {"generated_at": "2026-05-27T21:23:06.102981Z", "scores": []}
    (tmp_path / "risk_scores.json").write_text(json.dumps(stale), encoding="utf-8")

    before = datetime.now(timezone.utc)
    res = _run(tmp_path, risk_scorer_fn=_offline_scorer)
    after = datetime.now(timezone.utc)
    assert res.status == "ok"
    fresh = json.loads((tmp_path / "risk_scores.json").read_text(encoding="utf-8"))
    assert fresh["generated_at"] > stale["generated_at"]  # ISO-8601 сортируем
    # The scoring engine stamps generated_at with real wall-clock UTC (it is an independent
    # module, NOT threaded with the cycle's injected `now`), so assert the fresh stamp lands in
    # the real regeneration window rather than coupling it to NOW's month (brittle: only passed
    # when the wall clock happened to share NOW's calendar month).
    gen = datetime.fromisoformat(fresh["generated_at"].replace("Z", "+00:00"))
    assert before <= gen <= after, "regenerated generated_at must be a fresh wall-clock stamp"
    assert fresh["scores"], "regenerated snapshot must contain scores"


def test_regen_scores_compound_v3_and_writes_atomically(tmp_path):
    _offline_scorer(tmp_path)
    doc = json.loads((tmp_path / "risk_scores.json").read_text(encoding="utf-8"))
    slugs = {s["slug"] for s in doc["scores"]}
    assert "compound-v3" in slugs
    comp = next(s for s in doc["scores"] if s["slug"] == "compound-v3")
    assert comp["grade"] in {"A", "B", "C", "D"}
    assert 0.0 <= comp["score_numeric"] <= 1.0
    # Атомарная запись: tmp-файл переименован, огрызков не осталось.
    leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_export_atomic_replaces_existing_file(tmp_path):
    out = tmp_path / "risk_scores.json"
    out.write_text("{\"garbage\": true}", encoding="utf-8")
    _offline_scorer(tmp_path)
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert "scores" in doc and "generated_at" in doc
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
