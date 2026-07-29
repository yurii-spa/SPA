"""Регресс: выключатель DEFILLAMA_ENABLED для live-APY пути аллокатора.

`_default_live_apy_provider()` документирует контракт: «когда DeFiLlama выключен,
дефолтный провайдер НЕ ходит в сеть — он возвращает {}, и аллокатор ранжирует на
помеченных stale-литералах» (fail-CLOSED). На origin эта ветка была МЁРТВОЙ:
модуль импортировался как ``from . import config``, а в пакете
``spa_core.allocator`` модуля ``config`` нет — настоящий дом флага
``spa_core/adapters/config.py`` (его же читают сами фиды). ImportError глотался
широким ``except`` ⇒ при DEFILLAMA_ENABLED=false аллокатор всё равно шёл
опрашивать адаптеры.

Тесты герметичны: реестр адаптеров подменяется фейком (никакой сети), кеш
провайдера сбрасывается, ``PYTEST_CURRENT_TEST`` снимается — иначе более ранний
offline-guard закоротил бы функцию раньше проверяемой ветки.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.allocator import allocator as alloc_mod


class _FakeYieldInfo:
    apy = 0.05  # decimal, внутри допустимой полосы


class _FakeAdapter:
    """Адаптер без сети: возвращает фиксированный live-APY."""

    IS_ADVISORY = False
    RESEARCH_ONLY = False

    def get_yield_info(self):
        return _FakeYieldInfo()


def _call_live(monkeypatch):
    """Зовёт провайдер на «живом» пути (без offline-guard'а).

    ``PYTEST_CURRENT_TEST`` снимается ЗДЕСЬ, а не в фикстуре: pytest выставляет
    эту переменную заново перед КАЖДОЙ фазой теста, поэтому снятие на setup'е
    не доживает до вызова — и проверка «выключенный флаг ⇒ {}» зеленела бы
    ложно, закоротившись на offline-guard'е вместо проверяемой ветки.
    """
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    return alloc_mod._default_live_apy_provider()


@pytest.fixture()
def live_path(monkeypatch):
    """Ставит функцию на «живой» путь: без кеша, с фейк-реестром (без сети)."""
    monkeypatch.setattr(alloc_mod, "_live_apy_cache", None, raising=False)
    monkeypatch.setattr(alloc_mod, "_live_apy_cache_ts", 0.0, raising=False)

    import spa_core.adapters as _adapters
    monkeypatch.setattr(
        _adapters, "ADAPTER_REGISTRY", [("fake_pool", "T1", _FakeAdapter)], raising=False
    )
    return _adapters


def test_flag_enabled_reaches_registry(live_path, monkeypatch):
    """Позитивный контроль: при включённом флаге фейк-реестр РЕАЛЬНО опрашивается.

    Без этого теста пустой результат в тесте ниже нельзя отличить от инертной
    фикстуры.
    """
    import spa_core.adapters.config as _cfg
    monkeypatch.setattr(_cfg, "DEFILLAMA_ENABLED", True, raising=False)

    assert _call_live(monkeypatch) == {"fake_pool": 0.05}


def test_flag_disabled_short_circuits_before_registry(live_path, monkeypatch):
    """Ключевой регресс: DEFILLAMA_ENABLED=false ⇒ пустая карта, реестр не трогается.

    На origin возвращалось {"fake_pool": 0.05} — выключатель не работал.
    """
    import spa_core.adapters.config as _cfg
    monkeypatch.setattr(_cfg, "DEFILLAMA_ENABLED", False, raising=False)

    assert _call_live(monkeypatch) == {}


def test_disabled_flag_does_not_poison_cache(live_path, monkeypatch):
    """Отказ по флагу не кешируется как «живой» ответ (следующий вызов честен)."""
    import spa_core.adapters.config as _cfg
    monkeypatch.setattr(_cfg, "DEFILLAMA_ENABLED", False, raising=False)
    assert _call_live(monkeypatch) == {}
    assert alloc_mod._live_apy_cache is None, "пустышка по флагу не должна оседать в кеше"

    monkeypatch.setattr(_cfg, "DEFILLAMA_ENABLED", True, raising=False)
    assert _call_live(monkeypatch) == {"fake_pool": 0.05}


def test_pytest_guard_still_short_circuits(monkeypatch):
    """Действующий offline-guard под pytest сохранён (сеть в сьюте не дёргается)."""
    monkeypatch.setattr(alloc_mod, "_live_apy_cache", None, raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_x (call)")

    import spa_core.adapters as _adapters
    monkeypatch.setattr(
        _adapters, "ADAPTER_REGISTRY", [("fake_pool", "T1", _FakeAdapter)], raising=False
    )
    assert alloc_mod._default_live_apy_provider() == {}
