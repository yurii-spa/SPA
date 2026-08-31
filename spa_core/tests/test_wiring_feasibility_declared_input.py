"""Список — это список ЧЕГО (цикл #440, исполнение варианта 3 владельца).

**Реальная авария, которую воспроизводят эти тесты.** 29.08 владельцу ушла
карточка «доизмерили те 82 модуля»: 71 подтверждён слепым, а у **11 вердикта
нет** — «5 падают с ошибкой, 4 не удалось позвать, 2 не возвращают числа».
Владелец выбрал вариант 3: не списывать ничего, сначала доизмерить эти 11.

Доизмерение вскрыло, что «падают с ошибкой» было НЕПРАВДОЙ про модуль и
правдой про инструмент. `call_shape` выводил форму по ГОЛОВЕ аннотации, и

    def analyze(spreads: List[float]) -> SpreadZReport      # yield_spread_zscore_analyzer
    def analyze(exposures: List[PositionExposure]) -> ...   # protocol_concentration_monitor

читались как «список записей». Инструмент клал туда профиль протокола, движок
честно падал (`TypeError: type RecordingProfile doesn't define __round__`), и
падение записывалось модулю как `RAISES`. Это дословно дефект цикла #133 — 268
ложных RAISES, — только на уровень глубже: тогда путали форму КОНТЕЙНЕРА,
теперь форму ЭЛЕМЕНТА. Замер по всей популяции: таких ложных обвинений **9**
(7 Tier-B + 2 Tier-C).

Вторая половина того же класса — вердикт `SHAPE_NOT_PROBED` у входа, который
движок ОБЪЯВИЛ: `analyze(feed: OracleFeed)` не «форма неизвестна», а прямой
ответ «мне нужен не профиль протокола». Отвечать на такое «не измерено» —
значит держать 81 модуль (58 Tier-B + 23 Tier-C) в очереди на замер, который
уже состоялся. Отсюда `DECLARED_INPUT_NOT_A_RECORD`: вызова нет, вердикт есть.

Третья — `measured`. Отчёт печатал плоский `counts`, и «не измерено» считалось
ГЛАЗОМ по списку статусов; так `RAISES` и `NO_SCORE`, которые ОТВЕЧАЮТ на
вопрос инструмента (отрицательно), попали к владельцу как «вердикта нет».

**Первое имя вердикта было ОПРОВЕРГНУТО и заменено — это часть находки.**
Сначала он назывался `NOT_PROTOCOL_INPUT` и его текст утверждал: «это не запись
протокола, `_protocol_facts` такому движку честного входа не даст». Замер по
эталону ADR-194 (115 работающих протокол-различающих модулей) показал **8
контрпримеров**: модули с объявленным доменным входом, которые протокол ЧИТАЮТ —
они берут факты сами на контекст-пути ADR-031, а прод кормит их не тем, чем
кормит этот инструмент. Вердикт переименован в `DECLARED_INPUT_NOT_A_RECORD` и
говорит теперь ровно о своей области: провести ЧЕРЕЗ ОБЪЯВЛЕННЫЙ ВХОД нельзя.
Про слепоту модуля он не говорит НИЧЕГО, и тест ниже держит именно это.

Обратные контроли обязательны и здесь: настоящий список записей по-прежнему
зовётся, честное «контракта нет» по-прежнему остаётся `SHAPE_NOT_PROBED` и
`measured=False`. Без них «краснеет всегда» сошло бы за доказательство.

Время в замере не участвует — литеральных дат нет, метка FROZEN-DATE-OK не
нужна.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def feas():
    return _load("_test_wiring_feasibility_not_protocol_input",
                 "scripts/audit_tier_c_wiring_feasibility.py")


PROBES = ("aave_v3", "maple", "pendle")
TABLE = {
    "aave_v3": {"utilization_rate_pct": 80.0},
    "maple": {"utilization_rate_pct": 40.0},
    "pendle": {"utilization_rate_pct": 10.0},
}


def _profile_source(table):
    def _get(protocol):
        raw = table.get(protocol)
        return dict(raw) if raw is not None else None
    return _get


class _FakeModule:
    def __init__(self, fn):
        self.analyze = fn


def _probe(feas, monkeypatch, fn):
    monkeypatch.setattr(feas._ModuleAdapter, "_import_callable",
                        lambda self: _FakeModule(fn))
    return feas.probe_module({"module": "fake_mod"}, protocols=PROBES,
                             profile_for=_profile_source(TABLE))


@dataclass
class PositionExposure:
    """Доменный тип движка — ровно форма `protocol_concentration_monitor`."""
    protocol: str
    value_usd: float


# ─── положительные контроли: ложное обвинение модуля снято ──────────────────

def test_list_of_scalars_is_not_a_record_list(feas, monkeypatch):
    """`yield_spread_zscore_analyzer` вживую: `analyze(spreads: List[float])`.

    На неисправленном инструменте здесь `RAISES` с текстом
    «type RecordingProfile doesn't define __round__» — то есть отчёт обвиняет
    модуль в падении, которое вызвал сам."""
    def analyze(spreads: List[float]) -> dict:
        return {"risk_score": round(spreads[0], 2)}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "DECLARED_INPUT_NOT_A_RECORD", (
        "движок объявил список ЧИСЕЛ — вызов `fn([profile])` выдуман "
        "инструментом, и падение от него нельзя записывать модулю")
    assert out["call_shape"] == "list_of_nonrecords"


def test_list_of_domain_dataclasses_is_not_a_record_list(feas, monkeypatch):
    """`protocol_concentration_monitor` вживую: `List[PositionExposure]`.

    На неисправленном инструменте — `AttributeError: 'RecordingProfile' object
    has no attribute 'value_usd'`, записанный модулю."""
    def analyze(exposures: List[PositionExposure]) -> dict:
        return {"risk_score": exposures[0].value_usd}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "DECLARED_INPUT_NOT_A_RECORD"
    assert out["call_shape"] == "list_of_nonrecords"


def test_declared_element_is_named_in_the_verdict(feas, monkeypatch):
    """Вердикт обязан назвать ЭЛЕМЕНТ, иначе его нечем перепроверить.

    У ЖИВОГО объекта `typing.List[PositionExposure]` короткое имя — «List»,
    и вердикт «вход объявлен как `List`» звучит как отказ по контейнеру, хотя
    вся улика лежит в элементе. Так выглядит настоящий
    `protocol_concentration_monitor`.

    **Аннотацию здесь ставим объектом, а не исходником.** В этом файле стоит
    `from __future__ import annotations`, поэтому написанная в сигнатуре
    `List[PositionExposure]` пришла бы СТРОКОЙ «List[PositionExposure]» — в
    ней имя элемента есть всегда, и мутация «показывать `__name__`» осталась
    бы зелёной. Проверено мутацией по координате: на строке-исходнике тест
    был украшением."""
    def analyze(exposures):
        return {"risk_score": 1.0}

    analyze.__annotations__ = {"exposures": List[PositionExposure],
                               "return": dict}
    assert getattr(List[PositionExposure], "__name__", None) == "List", (
        "предпосылка теста истекла: короткое имя перестало быть «List», "
        "и мутацию про `__name__` он больше не ловит")

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "DECLARED_INPUT_NOT_A_RECORD"
    assert "PositionExposure" in (out["annotation"] or ""), out["annotation"]
    assert "PositionExposure" in out["detail"]


def test_declared_domain_type_gets_a_verdict_not_a_shrug(feas, monkeypatch):
    """`OracleFeed` вживую: вход ОБЪЯВЛЕН, значит ответ есть.

    До #440 это был `SHAPE_NOT_PROBED` — «не измеряем», и 81 модуль стоял в
    очереди на замер, который уже состоялся."""
    class OracleFeed:  # noqa: D401 — доменный тип движка
        pass

    def analyze(feed: OracleFeed) -> dict:
        raise AssertionError("движок чужой формы не должен быть вызван")

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "DECLARED_INPUT_NOT_A_RECORD"
    assert out["call_shape"] == "typed"


def test_raises_and_no_score_count_as_measured(feas):
    """`RAISES` и `NO_SCORE` ОТВЕЧАЮТ на вопрос инструмента — отрицательно.

    Именно их прочтение как «вердикта нет» отправило владельцу 11 модулей
    вместо 6 (замер #440: у пяти из одиннадцати ответ был)."""
    for verdict in ("RAISES", "NO_SCORE", "DECLARED_INPUT_NOT_A_RECORD",
                    "BLIND", "UNCOVERED", "WIRABLE"):
        assert feas.is_measured(verdict), verdict


def test_report_counts_unmeasured_by_code_not_by_eye(feas, monkeypatch):
    """`measured_count` / `unmeasured` считаются кодом и попадают в отчёт."""
    def analyze(whatever=None):
        raise AssertionError("движок неизвестной формы не должен быть вызван")

    monkeypatch.setattr(feas._ModuleAdapter, "_import_callable",
                        lambda self: _FakeModule(analyze))
    monkeypatch.setattr(feas.registry, "get_tier_modules",
                        lambda tier: [{"module": "fake_mod"}])
    report = feas.run_audit(tier="B")
    assert report["unmeasured"] == ["fake_mod"]
    assert report["unmeasured_count"] == 1
    assert report["measured_count"] == 0
    assert report["results"][0]["measured"] is False


# ─── обратные контроли: граница не сдвинулась ───────────────────────────────

def test_list_of_records_is_still_probed(feas, monkeypatch):
    """`List[dict]` — настоящий список записей: зовётся как прежде."""
    seen: list[Any] = []

    def analyze(rows: List[dict]) -> dict:
        seen.append(rows)
        return {"risk_score": float(rows[0]["utilization_rate_pct"])}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] != "DECLARED_INPUT_NOT_A_RECORD", (
        "починка не имеет права переставать мерить настоящие списки записей")
    assert out["call_shape"] == "list"
    assert seen, "движок списка записей обязан быть вызван"


def test_bare_list_without_element_type_is_still_probed(feas, monkeypatch):
    """Элемент НЕ объявлен ⇒ судить не по чему ⇒ прежнее поведение.

    «Не объявлен» и «объявлен не записью» — разные утверждения; смешать их
    значило бы перестать мерить половину тира по отсутствию улики."""
    seen: list[Any] = []

    def analyze(rows: list) -> dict:
        seen.append(rows)
        return {"risk_score": float(rows[0]["utilization_rate_pct"])}

    out = _probe(feas, monkeypatch, analyze)
    assert out["call_shape"] == "list"
    assert seen, "список без объявленного элемента обязан по-прежнему звучать"


def test_sequence_of_records_is_still_probed(feas, monkeypatch):
    """`Sequence[dict]` — та же запись, другой контейнер."""
    def analyze(rows: Sequence[Dict[str, Any]]) -> dict:
        return {"risk_score": float(rows[0]["utilization_rate_pct"])}

    out = _probe(feas, monkeypatch, analyze)
    assert out["call_shape"] == "list"


def test_unannotated_input_stays_honestly_unmeasured(feas, monkeypatch):
    """Контракта нет вовсе ⇒ `SHAPE_NOT_PROBED` и `measured=False`.

    Красить это в `DECLARED_INPUT_NOT_A_RECORD` значило бы утверждать замер, которого
    не было, — ровно тот обмен немоты на враньё, против которого весь файл."""
    def analyze(whatever=None):
        raise AssertionError("движок неизвестной формы не должен быть вызван")

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "SHAPE_NOT_PROBED"
    assert out["call_shape"] == "unannotated"
    assert not feas.is_measured(out["verdict"])


def test_unmeasured_verdicts_are_named_and_stay_unmeasured(feas):
    """Обратный контроль к `test_raises_and_no_score_count_as_measured`."""
    for verdict in ("SHAPE_NOT_PROBED", "COVERAGE_UNMEASURED",
                    "NO_ENTRY", "IMPORT_ERR"):
        assert not feas.is_measured(verdict), verdict


def test_record_element_names_agree_with_the_aggregator(feas):
    """Сверка с ИСТОЧНИКОМ, а не с копией.

    «Что считается записью» решают два места: этот инструмент и
    `signal_aggregator._MAPPING_ANNOTATION_NAMES` (кого прод соглашается
    звать с dict-контекстом). Разойдись они молча — инструмент объявил бы
    «не запись» про вход, который прод кормит записью каждый цикл."""
    from spa_core.analytics.signal_aggregator import _MAPPING_ANNOTATION_NAMES
    assert ({n.lower() for n in _MAPPING_ANNOTATION_NAMES}
            == set(feas._RECORD_ELEMENT_NAMES)), (
        "набор «это запись» разошёлся с тем, что признаёт прод-адаптер")


# ─── граница вердикта: он НЕ про слепоту модуля (ADR-194 дал 8 контрпримеров) ─

def test_verdict_does_not_claim_the_module_is_blind(feas, monkeypatch):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ к переименованию.

    Первое имя (`NOT_PROTOCOL_INPUT`) и первый текст («`_protocol_facts` такому
    движку честного входа не даст») утверждали про МОДУЛЬ то, чего замер не
    даёт. Эталон ADR-194 назвал 8 работающих модулей, попадающих под этот же
    вердикт, — `governance_token_risk_analyzer`, `protocol_risk_scorer` и
    другие читают протокол на контекст-пути ADR-031.

    Поэтому вердикт обязан говорить про ВХОД, а не про модуль, и обязан сам
    отсылать к оговорке. Тест краснеет на любом возврате к прежней формулировке."""
    class OracleFeed:  # noqa: D401 — доменный тип движка
        pass

    def analyze(feed: OracleFeed) -> dict:
        raise AssertionError("движок чужой формы не должен быть вызван")

    out = _probe(feas, monkeypatch, analyze)
    detail = out["detail"]
    assert "ЧЕРЕЗ ЭТОТ ВХОД" in detail, (
        "вердикт обязан ограничить себя объявленным входом: " + detail)
    assert "cross_instrument_caveat" in detail, (
        "вердикт обязан отсылать к оговорке о цене ошибки — иначе его снова "
        "прочтут как улику для списания")
    assert "честного входа не даст" not in detail, (
        "вернулась формулировка, утверждающая про МОДУЛЬ то, что опровергнуто "
        "восемью контрпримерами эталона ADR-194")


def test_report_carries_the_cross_instrument_caveat(feas, monkeypatch):
    """Оговорка едет в ШАПКЕ отчёта, а не только в докстринге.

    Отчёт читают json'ом; оговорка, живущая в комментарии исходника, до
    читателя, решающего о списании, не доходит."""
    def analyze(rows: List[dict]) -> dict:
        return {"risk_score": float(rows[0]["utilization_rate_pct"])}

    monkeypatch.setattr(feas._ModuleAdapter, "_import_callable",
                        lambda self: _FakeModule(analyze))
    monkeypatch.setattr(feas.registry, "get_tier_modules",
                        lambda tier: [{"module": "fake_mod"}])
    report = feas.run_audit(tier="B")
    caveat = report["cross_instrument_caveat"]
    assert "ОДНОГО инструмента" in caveat and "ADR-194" in caveat, caveat
    assert "7,8" in caveat, (
        "оговорка обязана нести ЧИСЛО: «инструмент иногда ошибается» без "
        "величины — это та же неизмеренная сила улики, из-за которой "
        "списание 71 готовилось как при нулевой ошибке")
