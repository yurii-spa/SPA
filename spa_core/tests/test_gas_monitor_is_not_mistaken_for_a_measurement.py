"""`unified_gas_monitor` — калькулятор на константах, а не измеритель.

# LLM_FORBIDDEN

Замер 2026-08-29. Из трёх неподключённых «газовых мониторов» два
(`arbitrum_gas_monitor`, `optimism_gas_monitor`) действительно тянут живой фид
(Blocknative / Infura, таймаут, константа только как запасной вариант).
Третий — `unified_gas_monitor` — газ **не измеряет**: в его собственном коде
написано «fallback constant, no network call», цена газа 20 Gwei и цена ETH
3200 $ захардкожены.

Я собирался подключить его как «дешёвый и безопасный» и остановился, прочитав
резолвер. Подключение создало бы **видимость измерения**: модуль называется
монитором, пишет `data/unified_gas_estimates.json` с полем `cost_usd`, а внутри
две константы. Это ровно тот класс, который проект весь день чинит — метка
обещает больше, чем делает вещь.

Тест держит различие явным: пока модуль не научился спрашивать цену газа,
он не имеет права выглядеть источником измерения.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_UNIFIED = _ROOT / "spa_core" / "monitoring" / "unified_gas_monitor.py"
_LIVE = (
    _ROOT / "spa_core" / "monitoring" / "arbitrum_gas_monitor.py",
    _ROOT / "spa_core" / "monitoring" / "optimism_gas_monitor.py",
)

_NET_MARKERS = ("urlopen", "urllib.request", "requests.", "http://", "https://")


def _fetches_network(path: Path) -> bool:
    return any(m in path.read_text(encoding="utf-8") for m in _NET_MARKERS)


def test_the_two_l2_monitors_really_fetch():
    """Обратный контроль: если бы «сетевой» признак был выдуман, он бы молчал и тут."""
    for p in _LIVE:
        assert p.exists(), p
        assert _fetches_network(p), f"{p.name} перестал тянуть живой фид"


def test_unified_monitor_does_not_pretend_to_measure():
    """Пока внутри константа — модуль не должен обзаводиться сетью втихую.

    Если он НАУЧИЛСЯ спрашивать цену газа — это хорошая новость и повод
    обновить `docs/cost_model_provenance.md` и карточку одиннадцати сирот,
    а не молча оставить тест зелёным.
    """
    assert _UNIFIED.exists()
    text = _UNIFIED.read_text(encoding="utf-8")
    if _fetches_network(_UNIFIED):
        pytest.fail(
            "unified_gas_monitor начал ходить в сеть — перепроверь разбор: "
            "он был калькулятором на константах, и на этом стоят выводы "
            "в docs/cost_model_provenance.md")
    assert "no network call" in text, (
        "из кода исчезла честная пометка «no network call» — модуль либо начал "
        "измерять, либо перестал признаваться, что не измеряет")


def test_its_constants_are_named_out_loud():
    """Константы обязаны быть видимы: скрытая константа читается как замер."""
    tree = ast.parse(_UNIFIED.read_text(encoding="utf-8"))
    names = set()
    for n in ast.walk(tree):
        # Константы объявлены С АННОТАЦИЕЙ (`ETH_PRICE_USD: float = 3200.0`),
        # а это ast.AnnAssign, не ast.Assign — первая редакция теста собирала
        # только второе и краснела на верном коде.
        if isinstance(n, ast.Assign):
            names |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
    assert "_FALLBACK_GAS_PRICE_GWEI" in names
    assert "ETH_PRICE_USD" in names


def test_the_chain_our_book_sits_on_has_no_live_gas_source():
    """Главное следствие: измерения нет там, где газ стоит денег.

    Два живых монитора — L2 (Arbitrum, Optimism), где газ копеечный. Ethereum,
    на котором стоит книга и где нога стоит $12 по модели издержек, живого
    источника не имеет. Появится — тест краснеет, и это приглашение
    переписать §4 документа издержек, а не молчаливое улучшение.
    """
    eth_live = [p for p in _LIVE if "ethereum" in p.read_text(encoding="utf-8").lower()
                and _fetches_network(p)]
    assert not eth_live, (
        f"появился живой источник газа Ethereum ({[p.name for p in eth_live]}) — "
        "обнови docs/cost_model_provenance.md §4: дыра закрыта")
