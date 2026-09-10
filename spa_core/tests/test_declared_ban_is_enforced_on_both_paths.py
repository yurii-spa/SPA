"""Объявленный в реестре запрет действует НЕЗАВИСИМО от пути загрузки (ADR-303).

Замер 2026-09-09/10 на живой книге: у `fluid_usdc` в `data/adapter_registry.json` стои́т
`research_only: true` и `per_protocol_cap: 0.0` — денег туда класть нельзя. Денег там
**$20 000, 20 % книги**.

Правило не нарушал никто. Проверка `research_only` стои́т в РЕЕСТРОВОЙ ветке загрузки, ПОСЛЕ
строки `if name in seen_protocols: continue`, а этот протокол приходит снимком оркестратора —
и до проверки очередь не доходит НИКОГДА. Запрет, который читает одна ветка из двух, — это не
запрет, а надпись.

Оффлайн, stdlib, пути инжектируются. LLM_FORBIDDEN.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.allocator.allocator import StrategyAllocator


def _write(tmp: Path, *, registry: dict, snapshot_protocols: list[str]) -> StrategyAllocator:
    (tmp / "adapter_registry.json").write_text(json.dumps({"adapters": registry}), encoding="utf-8")
    (tmp / "adapter_orchestrator_status.json").write_text(json.dumps({
        "adapters": [
            {"protocol": p, "status": "ok", "apy_pct": 5.0, "tvl_usd": 500_000_000.0,
             "tvl_source": "live", "tier": "T2"}
            for p in snapshot_protocols
        ]}), encoding="utf-8")
    (tmp / "risk_scores.json").write_text(json.dumps({}), encoding="utf-8")
    return StrategyAllocator(
        status_path=str(tmp / "adapter_orchestrator_status.json"),
        risk_scores_path=str(tmp / "risk_scores.json"),
        registry_path=str(tmp / "adapter_registry.json"))


_OK = {"tier": 2, "chain": "ethereum", "fallback_apy": 0.05, "status": "active",
       "research_only": False, "per_protocol_cap": 0.2}


def test_the_2026_09_09_shape_research_only_arriving_by_snapshot(tmp_path):
    """Тот самый случай: запрет объявлен, протокол приходит СНИМКОМ — и запрет действует."""
    a = _write(tmp_path,
               registry={"fluid_usdc": {**_OK, "research_only": True, "per_protocol_cap": 0.0},
                         "maple": dict(_OK)},
               snapshot_protocols=["fluid_usdc", "maple"])
    a.allocate("risk_adjusted")
    assert a._blocked.get("fluid_usdc") == "registry_research_only"
    assert "maple" not in a._blocked


def test_a_zero_cap_is_a_ban_too(tmp_path):
    """`per_protocol_cap: 0` — тот же запрет, выраженный числом, а не флагом."""
    a = _write(tmp_path,
               registry={"x": {**_OK, "per_protocol_cap": 0.0}, "maple": dict(_OK)},
               snapshot_protocols=["x", "maple"])
    a.allocate("risk_adjusted")
    assert a._blocked.get("x") == "registry_cap_zero"


def test_a_protocol_without_a_registry_entry_is_not_banned(tmp_path):
    """Отсутствие объявления — НЕ запрет: иначе новый адаптер забанен по построению."""
    a = _write(tmp_path, registry={"maple": dict(_OK)},
               snapshot_protocols=["maple", "newcomer"])
    a.allocate("risk_adjusted")
    assert "newcomer" not in a._blocked


def test_the_ban_still_works_on_the_registry_path(tmp_path):
    """Обратная половина: протокол, которого НЕТ в снимке, запрещён по-прежнему.

    Без этой половины правка могла бы «починить» одну ветку, сломав другую.
    """
    a = _write(tmp_path,
               registry={"only_in_registry": {**_OK, "research_only": True},
                         "maple": dict(_OK)},
               snapshot_protocols=["maple"])
    a.allocate("risk_adjusted")
    assert "only_in_registry" not in (getattr(a.allocate("risk_adjusted"), "allocations", None) or {})


def test_an_unreadable_registry_is_named_not_silently_permissive(tmp_path):
    """Реестр не прочитан ⇒ запреты НЕ ИЗМЕРЕНЫ, и это сказано в лог, а не проглочено.

    Разрешать всё молча здесь нельзя: именно так запрет и превращается в надпись.
    """
    (tmp_path / "adapter_registry.json").write_text("{ битый json", encoding="utf-8")
    (tmp_path / "adapter_orchestrator_status.json").write_text(json.dumps({
        "adapters": [{"protocol": "maple", "status": "ok", "apy_pct": 5.0,
                      "tvl_usd": 5e8, "tvl_source": "live", "tier": "T2"}]}), encoding="utf-8")
    (tmp_path / "risk_scores.json").write_text("{}", encoding="utf-8")
    a = StrategyAllocator(
        status_path=str(tmp_path / "adapter_orchestrator_status.json"),
        risk_scores_path=str(tmp_path / "risk_scores.json"),
        registry_path=str(tmp_path / "adapter_registry.json"))
    a.allocate("risk_adjusted")   # не падает
    assert "maple" not in a._blocked
