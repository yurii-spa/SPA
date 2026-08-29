"""Покрытие доходит до артефакта, а знаменатель не берётся с ХОСТА (ADR-169).

# LLM_FORBIDDEN

Две дыры, найденные ПОСЛЕ принятия ADR-169 — обе в тексте самого решения:

1. ADR обещал, что состояние покрытия «доходит до дневного отчёта». Оно жило
   атрибутом в памяти объекта и дойти туда не могло физически. Обещание в
   принятом решении либо истинно, либо решение неверно; сделал истинным.
2. Знаменатель (`_observation_attempts`) читал живой `data/` репозитория ПОД
   pytest, тогда как загрузка числителя двумя блоками выше от этого защищена.
   Вердикт теста начинал зависеть от того, сколько адаптеров лежит в дереве
   разработчика — на CI и на Маке это разные числа.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

from spa_core.allocator import allocator as A
from spa_core.allocator.allocator import StrategyAllocator


def _write(p: Path, doc: dict) -> None:
    p.write_text(json.dumps(doc), encoding="utf-8")


def _allocator(tmp_path: Path, evidence=None) -> StrategyAllocator:
    _write(tmp_path / "registry.json", {"adapters": {
        "maple": {"status": "active", "tier": 2, "fallback_apy": 0.0482,
                  "chain": "ethereum"},
        "frax": {"status": "active", "tier": 2, "fallback_apy": 0.075,
                 "chain": "ethereum"},
        "aave_v3": {"status": "active", "tier": 1, "fallback_apy": 0.045,
                    "chain": "ethereum"},
        "compound_v3": {"status": "active", "tier": 1, "fallback_apy": 0.050,
                        "chain": "ethereum"},
    }})
    _write(tmp_path / "orch.json", {"generated_at": "2030-01-01T00:00:00Z",
                                    "adapters": []})
    _write(tmp_path / "scores.json", {})
    return StrategyAllocator(
        status_path=tmp_path / "orch.json",
        risk_scores_path=tmp_path / "scores.json",
        registry_path=tmp_path / "registry.json",
        allocation_model="optimized_yield",
        strategy_loop_enabled=False,
        live_apy_provider=evidence,
    )


def test_the_denominator_is_not_read_from_the_host_under_pytest(tmp_path):
    """Числитель под pytest пуст по построению — знаменатель обязан быть НЕ ИЗМЕРЕН.

    Положительный контроль к настоящей ошибке: без заслона здесь стояло бы
    число адаптеров живого дерева (на момент находки — 34), и порог покрытия
    в тестах зависел бы от машины.
    """
    alloc = _allocator(tmp_path, evidence=None)
    alloc.allocate()
    cov = getattr(alloc, "_evidence_coverage", {})
    assert cov, "состояние покрытия не записано вовсе"
    assert cov["attempted"] == 0, (
        f"знаменатель взят с хоста ({cov['attempted']}) — вердикт теста стал "
        f"зависеть от дерева разработчика")
    assert cov["required"] == A._EVIDENCE_MIN_COVERAGE, (
        "не измеренный знаменатель обязан отдавать управление абсолютному порогу")


def test_an_injected_provider_is_its_own_denominator(tmp_path):
    """Обратный контроль: провайдер САМ является доказательством.

    Производителя, который мог бы сломаться, там нет — знаменатель это то, что
    провайдер дал, и правило доли по построению молчит.
    """
    alloc = _allocator(tmp_path, evidence={"maple": 0.0482, "frax": 0.075,
                                           "aave_v3": 0.045, "compound_v3": 0.050})
    alloc.allocate()
    cov = alloc._evidence_coverage
    assert cov["attempted"] == 4 and cov["evidenced"] == 4
    assert cov["gate_applied"] is True


def test_the_coverage_reaches_the_written_artifact():
    """Атрибут в памяти до отчёта не доходит — поле обязано быть в полезной нагрузке."""
    src = Path(A.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_build_feed_coverage")
    keys = {k.value for n in ast.walk(fn) if isinstance(n, ast.Dict)
            for k in n.keys if isinstance(k, ast.Constant)}
    assert "evidence_coverage" in keys, (
        "ADR-169 обещает, что покрытие доходит до дневного отчёта — а в артефакт "
        "пишется только флаг `evidence_gate_applied`, который не отличает "
        "«мир затих» от «наш производитель сломался»")
    assert "evidence_gate_applied" in keys, "обратный контроль: флаг не должен исчезнуть"


def test_the_absolute_floor_outranks_a_perfect_fraction(tmp_path):
    """Два протокола из двух — доля 100 %, и всё равно НЕ достаточно.

    Правило доли может только УЖЕСТОЧАТЬ. Первая редакция этого теста
    утверждала обратное и покраснела на верном коде: при двух протоколах
    правит абсолютный минимум ADR-061, а не идеальное покрытие.
    """
    alloc = _allocator(tmp_path, evidence={"maple": 0.0482, "frax": 0.075})
    alloc.allocate()
    cov = alloc._evidence_coverage
    assert cov["evidenced"] == 2 and cov["required"] == A._EVIDENCE_MIN_COVERAGE
    assert cov["gate_applied"] is False
