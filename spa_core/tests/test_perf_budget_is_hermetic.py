"""Гейт скорости обязан мерить НАШ код, а не чужую латентность.

Положительный контроль на аварию 15.08: первый честный прогон
`scripts/perf_budget.py` дал 3738 мс при бюджете 1500 и объявил дневной цикл
«медленным». Профиль показал, что 3.2 с из 3.7 — ДЕВЯТЬ живых HTTPS-запросов
(цена доли ERC-4626 по публичным RPC · агрегатор пулов · оракул газа), то есть
гейт мерил интернет.

Такой гейт краснеет от чужой сети и по построению учит себя игнорировать. Правило
репозитория на этот счёт однозначно: тесты не завязываются на живую сеть
(`.claude/rules/adapters.md`), а мешающая проверка чинится, а не отключается.
Бюджет при этом НЕ поднят: он остался 1500 мс и теперь относится к тому, чем мы
управляем (замер после починки — 860 мс).
"""
from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "scripts" / "perf_budget.py"


def _bench_cycle_source() -> str:
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_bench_cycle":
            return ast.get_source_segment(_SRC.read_text(encoding="utf-8"), node) or ""
    raise AssertionError("_bench_cycle исчез из scripts/perf_budget.py")


def test_cycle_benchmark_silences_every_known_network_door():
    """Все три двери в сеть заглушены поимённо — иначе гейт меряет не нас."""
    src = _bench_cycle_source()
    # Проверяется ПРИСВАИВАНИЕ заглушки, а не упоминание имени: строки
    # сохранения/восстановления содержат те же имена, поэтому поиск по имени
    # пропустил бы снятую заглушку (поймано мутацией на себе же).
    for door, stub in (("_RPC_ENDPOINTS", "_erc._RPC_ENDPOINTS = []"),
                       ("_fetch_pools", "_llama.DeFiLlamaFeed._fetch_pools = lambda"),
                       ("_fetch_gas_gwei", "_gas.BaseGasMonitor._fetch_gas_gwei = lambda")):
        assert stub in src, f"дверь в сеть {door} не заглушена в замере цикла"


def test_benchmark_restores_what_it_patched():
    """Замер не имеет права оставить продовый код заглушённым после себя."""
    src = _bench_cycle_source()
    assert "finally:" in src, "восстановление обязано быть в finally"
    for saved in ("_saved_endpoints", "_saved_fetch", "_saved_gas"):
        assert src.count(saved) >= 2, f"{saved} сохранён, но не возвращён обратно"


def test_the_budget_itself_was_not_raised():
    """Гейт починен ЗАМЕРОМ, а не смягчением: бюджет цикла остался 1500 мс."""
    text = _SRC.read_text(encoding="utf-8")
    tree = ast.parse(text)
    budgets = {}
    # Объявление аннотированное (`BUDGETS_MS: dict[str, float] = {...}`), поэтому
    # разбираем ОБЕ формы присваивания — иначе тест молча не найдёт таблицу и
    # начнёт «проверять» пустоту.
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for tgt in targets:
            if isinstance(tgt, ast.Name) and "BUDGET" in tgt.id.upper() and node.value:
                try:
                    budgets = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    pass
    assert isinstance(budgets, dict) and budgets, "таблица бюджетов не найдена"
    assert float(budgets.get("cycle")) == 1500.0, (
        "бюджет цикла изменён: {} вместо 1500. Гейт чинится замером, "
        "а не поднятием планки.".format(budgets.get("cycle")))
