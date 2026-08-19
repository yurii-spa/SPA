#!/usr/bin/env python3
"""Приёмка: объявленный `MODULE_TIMEOUT` обязан ОГРАНИЧИВАТЬ стену, а не только логироваться.

Авария, которую воспроизводят эти тесты (замер цикла #296, `signal_aggregator`).
Граница на модуль ставилась так::

    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(adapter.run, protocol, context)
        try:
            score, status, detail = fut.result(timeout=self.module_timeout)
        except FuturesTimeout:
            self._record(adapter.module_name, "timeout")
            return None, False

`FuturesTimeout` действительно приходил вовремя — и в health-лог честно уезжал статус
"timeout". Но выход из `with` зовёт `shutdown(wait=True)`, то есть ЖДЁТ ровно тот
зависший модуль, ради ограничения которого таймаут и ставился. Живой замер до починки
(`module_timeout=0.3с`, модуль спит 3с): исключение — на 0.39с, возврат управления —
на **3.04с**. Обещание «модуль не задержит цикл дольше MODULE_TIMEOUT» не выполнялось
НИ РАЗУ, при этом каждый артефакт о нём говорил, что выполнено.

Это тот самый класс, что тянется по журналу с #146: сторож отвечает на СВОЙ вопрос
(«записан ли статус timeout?» — да) и читается как ответ на нужный («ограничен ли цикл
по времени?» — нет). Цена в проде: дневной цикл держит ~479 Tier-B модулей, и любой
из них может стоять сколько захочет.

Каждый тест здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ либо ОБРАТНЫЙ:
  * `test_hung_module_returns_within_timeout`, `test_silent_hung_module_returns_within_timeout`,
    `test_tier_a_wall_is_bounded_by_module_timeout`, `test_hung_worker_thread_is_daemon`
    — краснеют на неисправленном `origin/main` (проверено прогоном в контрольном дереве);
  * остальные — обратные контроли: они обязаны быть зелёными и ДО, и ПОСЛЕ починки.
    Их работа — поймать, если починка заодно поменяла вердикты (статусы, тексты,
    проброс исключений). Ослабление тут было бы видно сразу (инв. #16).

Время — ВХОД (`module_timeout` передаётся явно, литеральных дат нет), поэтому тесты
не протухают от сдвига календаря.
"""
from __future__ import annotations

import threading
import time

import pytest

from spa_core.analytics import signal_aggregator as sa


# Запас на планировщик: измеряем ПОРЯДОК величины (0.3с против 3с), а не микросекунды.
_TIMEOUT = 0.3
_HANG_S = 3.0
_SLACK_S = 1.0          # возврат обязан уложиться в _TIMEOUT + _SLACK_S
_MODULE = {"module": "fake_module", "class": None, "weight": 1.0}


class _FakeAdapter:
    """Подставной модуль-адаптер: ведёт себя ровно так, как задал тест.

    Подменяем именно `_ModuleAdapter`, а не реестр модулей: настоящий адаптер
    импортирует `spa_core.analytics.<имя>`, а нам нужен модуль с УПРАВЛЯЕМЫМ
    поведением (зависание / исключение / кривая форма ответа), которого в
    репозитории нет и заводить его ради теста нельзя.
    """

    behaviour = "ok"
    started = threading.Event()
    finished = threading.Event()
    threads: list[threading.Thread] = []

    def __init__(self, module_info):
        self.module_name = module_info.get("module", "")

    def run(self, protocol, context):
        type(self).threads.append(threading.current_thread())
        type(self).started.set()
        try:
            if self.behaviour == "hang":
                time.sleep(_HANG_S)
                return 10.0, "ok", "проснулся ПОСЛЕ таймаута"
            if self.behaviour == "raise":
                raise ValueError("модуль упал")
            if self.behaviour == "base_exc":
                raise KeyboardInterrupt("не Exception")
            if self.behaviour == "bad_shape":
                return (1.0, "ok")        # два элемента вместо трёх
            return 42.0, "ok", "штатный ответ"
        finally:
            type(self).finished.set()


@pytest.fixture
def fake_adapter(monkeypatch):
    _FakeAdapter.behaviour = "ok"
    _FakeAdapter.started = threading.Event()
    _FakeAdapter.finished = threading.Event()
    _FakeAdapter.threads = []
    monkeypatch.setattr(sa, "_ModuleAdapter", _FakeAdapter)
    return _FakeAdapter


def _agg(tmp_path):
    return sa.SignalAggregator(data_dir=tmp_path, module_timeout=_TIMEOUT, max_workers=8)


# ── положительные контроли: стена реально ограничена ─────────────────────────

def test_hung_module_returns_within_timeout(tmp_path, fake_adapter):
    """Зависший модуль возвращает управление по таймауту, а не по своему окончанию.

    На неисправленном коде тест краснеет: возврат приходит на ~3.0с (модуль доспал),
    а не на ~0.3с (объявленный `module_timeout`).
    """
    fake_adapter.behaviour = "hang"
    agg = _agg(tmp_path)

    t0 = time.perf_counter()
    score, ok = agg._run_module(_MODULE, "aave_v3", {})
    elapsed = time.perf_counter() - t0

    assert (score, ok) == (None, False)
    assert elapsed < _TIMEOUT + _SLACK_S, (
        f"_run_module вернулся через {elapsed:.2f}с при module_timeout={_TIMEOUT}с — "
        f"граница по стене НЕ держит (модуль спал {_HANG_S}с)"
    )
    # Вердикт не изменился: статус тот же самый, что был до починки.
    assert agg._module_status["fake_module"] == "timeout"


def test_silent_hung_module_returns_within_timeout(tmp_path, fake_adapter):
    """То же для `_run_module_silent` (контрольный прогон Tier-C) — вторая копия дефекта."""
    fake_adapter.behaviour = "hang"
    agg = _agg(tmp_path)

    t0 = time.perf_counter()
    score, ok = agg._run_module_silent(_MODULE, "aave_v3", {})
    elapsed = time.perf_counter() - t0

    assert (score, ok) == (None, False)
    assert elapsed < _TIMEOUT + _SLACK_S, (
        f"_run_module_silent вернулся через {elapsed:.2f}с при "
        f"module_timeout={_TIMEOUT}с — граница по стене НЕ держит"
    )
    # Тихий прогон обязан остаться тихим: в health-лог он не пишет НИЧЕГО.
    assert "fake_module" not in agg._module_status


def test_tier_a_wall_is_bounded_by_module_timeout(tmp_path, fake_adapter, monkeypatch):
    """Стена целого тира ограничена таймаутом — это и есть обещание вызывающему.

    Внешний пул зовёт `fut.result()` БЕЗ таймаута: он ограничен ровно настолько,
    насколько ограничен `_run_module`. До починки один зависший модуль растягивал
    весь тир на своё собственное время.
    """
    fake_adapter.behaviour = "hang"
    monkeypatch.setattr(sa.registry, "get_tier_modules", lambda tier: [dict(_MODULE)])
    agg = _agg(tmp_path)

    t0 = time.perf_counter()
    signals = agg.run_tier_a(["aave_v3"], {})
    elapsed = time.perf_counter() - t0

    assert elapsed < _TIMEOUT + _SLACK_S, (
        f"run_tier_a занял {elapsed:.2f}с при module_timeout={_TIMEOUT}с"
    )
    # Fail-open сохранён: модуль не ответил → сигнала нет, не BLOCK.
    assert signals["protocols"]["aave_v3"]["signal"] == "OK"
    assert signals["_meta"]["module_status"]["not_ok"] == {"timeout": ["fake_module"]}


def test_hung_worker_thread_is_daemon(tmp_path, fake_adapter):
    """Поток зависшего модуля — daemon: он не держит выход интерпретатора.

    У `ThreadPoolExecutor` рабочие потоки не daemon, и `_python_exit` join'ит их на
    выходе — то есть зависший модуль после починки таймаута просто перенёс бы
    зависание на завершение процесса.
    """
    fake_adapter.behaviour = "hang"
    agg = _agg(tmp_path)
    agg._run_module(_MODULE, "aave_v3", {})

    assert fake_adapter.threads, "модуль не был вызван вовсе — тест ничего не проверил"
    worker = fake_adapter.threads[0]
    assert worker.daemon, "поток зависшего модуля не daemon — он задержит выход процесса"
    assert worker is not threading.current_thread()


# ── обратные контроли: вердикты и контракт НЕ изменились ─────────────────────

def test_normal_module_result_passes_through(tmp_path, fake_adapter):
    agg = _agg(tmp_path)
    score, ok = agg._run_module(_MODULE, "aave_v3", {})
    assert (score, ok) == (42.0, True)
    assert agg._module_status["fake_module"] == "ok"
    assert agg._log[-1]["detail"] == "штатный ответ"


def test_module_exception_is_recorded_as_failed(tmp_path, fake_adapter):
    fake_adapter.behaviour = "raise"
    agg = _agg(tmp_path)
    score, ok = agg._run_module(_MODULE, "aave_v3", {})
    assert (score, ok) == (None, False)
    assert agg._module_status["fake_module"] == "failed"
    assert agg._log[-1]["detail"] == "ValueError: модуль упал"


def test_bad_result_shape_is_recorded_as_failed(tmp_path, fake_adapter):
    """Кривая форма ответа модуля — по-прежнему `failed`, а не падение цикла."""
    fake_adapter.behaviour = "bad_shape"
    agg = _agg(tmp_path)
    score, ok = agg._run_module(_MODULE, "aave_v3", {})
    assert (score, ok) == (None, False)
    assert agg._module_status["fake_module"] == "failed"
    assert "ValueError" in agg._log[-1]["detail"]


def test_silent_run_returns_score_without_logging(tmp_path, fake_adapter):
    agg = _agg(tmp_path)
    score, ok = agg._run_module_silent(_MODULE, "not_a_real_protocol", {})
    assert (score, ok) == (42.0, True)
    assert agg._module_status == {}
    assert len(agg._log) == 0


# ── контракт самого ограничителя ─────────────────────────────────────────────

def test_run_bounded_returns_value_and_reraises_original_exception():
    """`_run_bounded` — тот же контракт, что у `Future.result`: значение или ИСХОДНОЕ исключение."""
    assert sa._run_bounded(lambda: "значение", 1.0) == "значение"

    with pytest.raises(ValueError, match="ровно это"):
        sa._run_bounded(lambda: (_ for _ in ()).throw(ValueError("ровно это")), 1.0)


def test_run_bounded_reraises_base_exception_too():
    """BaseException модуля не проглатывается: `Future.result` вёл себя так же."""
    def _boom():
        raise KeyboardInterrupt("не Exception")

    with pytest.raises(KeyboardInterrupt):
        sa._run_bounded(_boom, 1.0)


def test_run_bounded_raises_futures_timeout_with_the_declared_budget():
    """Таймаут приходит тем же типом, что и раньше, и называет свой бюджет."""
    from concurrent.futures import TimeoutError as FuturesTimeout

    t0 = time.perf_counter()
    with pytest.raises(FuturesTimeout) as exc:
        sa._run_bounded(lambda: time.sleep(_HANG_S), _TIMEOUT)
    elapsed = time.perf_counter() - t0

    assert str(_TIMEOUT) in str(exc.value)
    assert elapsed < _TIMEOUT + _SLACK_S
