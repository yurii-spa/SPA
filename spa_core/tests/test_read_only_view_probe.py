"""Контроль пробы `read_only_view_parses_the_ledger_once` (ADR-777, цикл #893).

Правило приёмки (`.claude/rules/acceptance.md`, п. 3) требует от НОВОЙ пробы контроля в обе
стороны: зелёная на целом контуре и красная на КАЖДОМ порванном звене — с названным звеном, —
и чтобы подстрокой она не проходила (ADR-333). Здесь это и проверяется.

Предмет, который проба сторожит: предписанный приёмочный прогон вставал на одном тесте
26 мин 54 с, потому что лекарство ADR-763 (stat-кэш чтения хеш-ленты) было вкручено в ОДНУ
точку входа (`mission_build.main()`), тогда как 4 958 разборов ленты 52 МБ делает ЧИТАЮЩАЯ
МОДЕЛЬ. Проба меряет ИСХОД — сколько раз файл реально разобран, — поэтому ни комментарий, ни
упоминание имени `read_cache` её не зеленят.
"""
from __future__ import annotations

import contextlib

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.research_factory import read as rf_read
from spa_core.utils import hash_ledger as hl

PROBE_NAME = "read_only_view_parses_the_ledger_once"


def _probe(**kw):
    return ca.PROBES[PROBE_NAME](None, **kw) if not kw else \
        ca._probe_read_only_view_parses_the_ledger_once(None, **kw)


def test_the_probe_is_registered_under_its_declared_name():
    assert PROBE_NAME in ca.PROBES


def test_green_on_the_whole_circuit():
    """Число в отчёте пробы — ОДИН разбор за зов (ADR-787, цикл #908): было два, и прежняя
    редакция ждала здесь «2 раз». Храповик ЗАТЯНУТ, а не ослаблен — прежнее поведение теперь
    красит пробу; почему это стало возможно без снятия проверок, меряет батарея
    `test_verify_seeds_the_read_cache.py`.

    Искомое — «1 раз(а)» со скобкой, а не «1 раз»: в той же строке стои́т «из 2 объявленных
    точек входа», и короткий образец совпал бы с ЧИСЛОМ ТОЧЕК. Прежняя редакция ровно так и
    совпадала двумя способами сразу, и это было видно только после смены числа.
    """
    state, why = _probe()
    assert state == ca.SATISFIED, why
    assert "1 раз(а)" in why and "кэш" in why


def test_red_when_the_scope_is_removed_from_the_read_model(monkeypatch):
    """Порванное звено №1 — область снята у ОБЕИХ точек входа сразу: проба обязана назвать
    каждую поимённо, а не сказать «что-то не так»."""
    state, why = ca._probe_read_only_view_parses_the_ledger_once(None, scope_removed=True)
    assert state == ca.NOT_SATISFIED
    assert "latest" in why and "cio_view" in why
    assert "разборов" in why


@pytest.mark.parametrize("victim", ["latest", "cio_view"])
def test_red_when_the_scope_is_removed_from_exactly_one_entry_point(monkeypatch, victim):
    """Порванное звено №2 — область снята у ОДНОЙ точки входа. Это сцена, в которой проба
    могла бы промолчать «большинство в порядке»; она обязана покраснеть и назвать жертву."""
    real = rf_read.read_cache
    other = {"latest": "cio_view", "cio_view": "latest"}[victim]

    def selective():
        # область работает только для НЕ-жертвы: смотрим, кто нас позвал
        import inspect
        caller = inspect.stack()[1].function
        return real() if caller != victim else contextlib.nullcontext()
    monkeypatch.setattr(rf_read, "read_cache", selective)
    state, why = _probe()
    assert state == ca.NOT_SATISFIED, why
    assert victim in why, f"жертва не названа: {why}"
    assert f"{other}:" not in why, f"оговорена здоровая точка входа: {why}"


def test_red_when_the_permanent_process_wide_switch_comes_back(monkeypatch):
    """Порванное звено №3 — возвращён вечный процессный выключатель. Он и был второй копией
    правила: пока он есть, «включил ли кто-то кэш» снова становится свойством точки входа."""
    monkeypatch.setattr(hl, "enable_read_cache", lambda: None, raising=False)
    state, why = _probe()
    assert state == ca.NOT_SATISFIED
    assert "enable_read_cache" in why


def test_unmeasured_when_the_declared_population_does_not_match(monkeypatch):
    """Порванное звено №4 — в читающую модель добавили вид, которого проба не проверяет.
    Третий исход (инв. #17): это НЕ «чисто» и НЕ «красно», это «НЕ ИЗМЕРЕНО» с причиной."""
    monkeypatch.setattr(rf_read, "VIEW_ENTRY_POINTS", ("latest", "cio_view", "brand_new_view"))
    state, why = _probe()
    assert state == ca.UNMEASURED
    assert "brand_new_view" in why and "НЕ ИЗМЕРЕНО" in why


def test_unmeasured_when_the_scene_cannot_be_built(monkeypatch):
    """Порванное звено №5 — сцену построить не удалось. Молчание тут было бы fail-OPEN."""
    def boom(*_a, **_k):
        raise OSError("ледж не создан")
    monkeypatch.setattr("spa_core.research_factory._common.ledger_for", boom)
    state, why = _probe()
    assert state == ca.UNMEASURED
    assert "НЕ ИЗМЕРЕНО" in why


def test_the_probe_does_not_pass_on_a_mention_of_the_name(monkeypatch):
    """ADR-333: подстрокой не проходит. Подменяем область на объект, который НАЗЫВАЕТСЯ
    `read_cache` и даже несёт это имя в `__name__`, но ничего не включает."""
    def read_cache():                                   # noqa: D401 — именно одноимённая пустышка
        return contextlib.nullcontext()
    monkeypatch.setattr(rf_read, "read_cache", read_cache)
    state, why = _probe()
    assert state == ca.NOT_SATISFIED, why


def test_the_probe_leaves_no_cache_behind_whatever_the_verdict():
    """Сама проба не имеет права оставить процесс в кэшированном состоянии — иначе она
    чинила бы предмет собственным побочным эффектом и мерила бы себя."""
    for kw in ({}, {"scope_removed": True}):
        ca._probe_read_only_view_parses_the_ledger_once(None, **kw)
        assert hl._READ_CACHE_ENABLED is False
        assert hl._READ_CACHE == {}
        assert hl.read_cache_depth() == 0


def test_red_when_a_view_leaves_the_cache_on_for_the_whole_process(monkeypatch):
    """Порванное звено №6 — дыру нашёл МУТАЦИОННЫЙ ПРИБОР, а не глаз автора: мутация
    «оставленный включённым кэш больше не считается провалом» ВЫЖИЛА, то есть эту ветку
    пробы не проверял никто.

    Сцена — ровно прежнее поведение `enable_read_cache()`: кэш включается и НЕ
    восстанавливается. Число разборов при этом верное (2), поэтому проба, смотрящая только
    на него, осталась бы зелёной — а процесс после одного чтения ленты поехал бы дальше с
    вечным кэшем, то есть с тем самым дефектом, ради которого всё это писалось."""
    import contextlib

    @contextlib.contextmanager
    def leaking_scope():
        hl._READ_CACHE_ENABLED = True
        yield                                            # и ничего не восстанавливает
    monkeypatch.setattr(rf_read, "read_cache", leaking_scope)
    try:
        state, why = _probe()
        assert state == ca.NOT_SATISFIED, why
        assert "кэш остался включён" in why
    finally:
        hl._READ_CACHE_ENABLED = False
        hl._READ_CACHE.clear()
