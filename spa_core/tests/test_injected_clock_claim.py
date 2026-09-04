#!/usr/bin/env python3
"""Пометка ``injected-clock`` перестаёт быть прозой: её претензию сверяют с кодом.

Карточка `inbox-pometka-injected-clock-neproveryaemaya-p` (цикл #468, закрыта #477).

Что здесь закреплено
------------------------------------------------------------------------------
Храповик литеральных дат выпускает файл из класса по ОДНОЙ строке-пометке
``FROZEN-DATE-OK: injected-clock — <как>`` (решётка перед ней здесь опущена
НАМЕРЕННО — см. последний абзац). Храповик проверяет, что пометка есть и
что у неё есть причина; **что причина ПРАВДА — не проверял никто**, а на ней держался
51 файл набора. Записка не есть инъекция: файл, который напишет эту причину и возьмёт
время у окружающих часов, выходил из класса молча — ровно та бомба, против которой
храповик написан.

Замер 04.09 (цикл #477) на живом наборе: пометку несут **51** файл, и у всех
пятидесяти одного инъекция подтверждена по AST. То есть сторож сегодня стоит **даром**
и закрывает дыру навсегда: следующая ЛОЖНАЯ пометка краснеет в момент написания.

Почему сторож не пуст (замерено, а не заявлено)
------------------------------------------------------------------------------
Мера, которая говорит «подтверждено» про всё подряд, — украшение. Тот же измеритель на
том же наборе: из 1693 файлов БЕЗ пометки подтверждёнными оказываются 275, а 1418 —
нет. Разделяющая способность держится тестом
:func:`test_the_measure_is_not_vacuous_on_the_live_suite`, чтобы «51 из 51» нельзя было
прочитать как «мера пропускает кого угодно».

Контроли в ОБЕ стороны (требование карточки, п. 4)
------------------------------------------------------------------------------
* честная инъекция (приём №1 правила ``.claude/rules/deployment.md``) остаётся зелёной;
* НАСТОЯЩИЙ файл набора, у которого инъекции нет, с приписанной пометкой — краснеет;
* форма аварии 2026-08-04 (литерал в словаре против стенных часов) не спасается
  пометкой;
* «не разобралось» — третий исход: сторож ПАДАЕТ, а не пропускает и не скипает.

Литеральные даты ниже — образцы детектора, каждая существует, чтобы быть узнанной или
отвергнутой. Поэтому файл освобождён честно и НЕ по проверяемой здесь причине:
# FROZEN-DATE-OK: detector-samples — все даты здесь фикстуры самого измерителя.

Строка-пометка ``injected-clock`` в фикстурах СОБИРАЕТСЯ из :data:`CLAIM`, а не
пишется дословно: дословная привела бы к тому, что файл выписал бы освобождение САМ
СЕБЕ и попал бы в собственный обход (ровно этот несчастный случай уже был у
``test_frozen_date_ratchet.py``, о чём в нём и написано).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from spa_core.tests import _injected_clock as ic
from spa_core.tests._injected_clock import (
    CLAIM, PROVEN, UNMEASURED, UNPROVEN, claiming_files, claims_injected_clock,
    measure_file, measure_source,
)

_TESTS_DIR = Path(__file__).resolve().parent

#: Пометка в собранном виде — см. докстринг о том, почему не дословно.
_MARKER = f"# FROZEN-DATE-OK: {CLAIM} — часы приходят входом"

#: Приём №1 правила: один якорь, все отметки от него, якорь отдан коду под проверкой.
_HONEST_INJECTION = (
    "NOW = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)\n"
    "_write_registry(tmp_path, (NOW - timedelta(hours=478.1)).isoformat())\n"
    "report = arr.refresh_if_stale(tmp_path, now=NOW, builder=builder)\n"
    "assert report['stale'] is True\n"
)

#: Форма аварии 2026-08-04: прибитая отметка сравнивается со СТЕННЫМИ часами. Литерал
#: лежит внутри словаря — контейнер происхождением не является, иначе бомба доказывала
#: бы претензию, которой у неё нет.
_REAL_BOMB = (
    'doc = {"generated_at": "2026-08-02T15:01:33+00:00"}\n'
    "assert age_hours(doc) < 24\n"
)


# --- сам измеритель: обе стороны ------------------------------------------

def test_the_honest_injection_is_proven() -> None:
    """Приём №1 правила распознан как инъекция — иначе сторож травил бы верный код."""
    v = measure_source(_MARKER + "\n" + _HONEST_INJECTION, "honest.py")
    assert v.verdict == PROVEN, v.reason
    assert v.injections, "инъекция не названа поимённо — отчёт нечем проверить"


def test_the_2026_08_04_bomb_is_not_rescued_by_the_marker() -> None:
    """Контроль в другую сторону: записка не превращает бомбу в инъекцию.

    Это и есть мутация, которую требует карточка: пометка есть, инъекции нет.
    """
    v = measure_source(_MARKER + "\n" + _REAL_BOMB, "bomb.py")
    assert v.verdict == UNPROVEN, (
        "файл с прибитой отметкой и стенными часами объявлен подтверждённым — "
        "сторож стал fail-OPEN, то есть ровно тем, против чего написан")
    assert "не передан аргументом" in v.reason


def test_a_container_holding_the_literal_is_not_a_binding() -> None:
    """Водораздел меры, названный отдельно: словарь с якорём — не значение-от-якоря.

    Стоит отдельным тестом, потому что смягчение ИМЕННО здесь снимает сторожа целиком
    (авария 2026-08-04 имеет ровно эту форму), а в общем тесте выше это утверждение
    выглядело бы деталью.
    """
    tree = ast.parse(_REAL_BOMB)
    assert "doc" not in ic._bound_names(tree)


def test_a_literal_passed_straight_into_a_call_counts() -> None:
    """`as_of="2026-08-08"` — настоящая инъекция со значением-ЛИТЕРАЛОМ.

    Инструмент цикла #468 искал подстроку ``\\s*=\\s*[A-Za-z_]`` и такие места пропускал,
    из-за чего назвал «неподтверждёнными» файлы, у которых инъекция была. Число «8» тем
    замером было отозвано; здесь закреплено, что новая мера этот вид ВИДИТ.
    """
    for src in ('gate.check(as_of="2026-08-08")\n',
                'build(now_iso="2026-08-08T00:00:00Z")\n'):
        assert measure_source(src, "kw.py").verdict == PROVEN, src


def test_building_the_anchor_is_not_injecting_it() -> None:
    """Якорь не доказывает сам себя — ни конструктором, ни разбором литерала."""
    for src in ("NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)\n",
                'NOW = datetime.fromisoformat("2026-08-08T00:00:00+00:00")\n',
                'STAMP = NOW.isoformat()\n'):
        assert measure_source(src, "ctor.py").verdict == UNPROVEN, src


def test_a_binding_declared_below_its_use_is_still_found() -> None:
    """Привязка ищется до неподвижной точки, а не по порядку строк.

    Однопроходный обход назвал бы такой файл неподтверждённым по причине, не имеющей
    отношения к делу, — то есть травил бы честный код за расстановку констант.
    """
    src = ("check(now=LATER)\n"
           "LATER = NOW + timedelta(hours=3)\n"
           "NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)\n")
    assert measure_source(src, "order.py").verdict == PROVEN


# --- третий исход: «не разобралось» ---------------------------------------

def test_unparseable_source_is_its_own_outcome() -> None:
    """Не число и не тихий пропуск: «не измерено» с названной причиной."""
    v = measure_source("def broken(:\n", "broken.py")
    assert v.verdict == UNMEASURED
    assert v.reason, "исход «не измерено» без причины неотличим от молчания"


def test_the_sweep_fails_loudly_on_an_unmeasured_file(tmp_path) -> None:
    """Контроль на сам отказ: «не измерено» обязано ПАДАТЬ, а не скипать.

    Ловится ``BaseException``: и ``pytest.skip``, и ``pytest.fail`` — его потомки, а не
    ``AssertionError``; ``pytest.raises(AssertionError)`` скип НЕ поймал бы, исход стал
    бы ``skipped``, и сторож замолчал бы ровно от того дефекта, против которого написан
    (урок #465).
    """
    bad = tmp_path / "test_broken.py"
    bad.write_text(_MARKER + "\ndef broken(:\n", encoding="utf-8")

    with pytest.raises(BaseException) as excinfo:  # noqa: PT011 — тип проверяем ниже
        _assert_population_proven(claiming_files(tmp_path))

    assert excinfo.type is not None
    assert "Skipped" not in excinfo.type.__name__, (
        "отказ обернулся скипом — «не измерено» стало неотличимо от «прошло»")
    assert UNMEASURED in str(excinfo.value) or "не измерено" in str(excinfo.value)


# --- сторож по живому набору ----------------------------------------------

def _assert_population_proven(files) -> None:
    """Общая проверка популяции. Отдельной функцией — её же зовёт контроль выше."""
    bad = []
    for f in files:
        v = measure_file(f)
        if v.verdict != PROVEN:
            bad.append(f"{f.name}: [{v.verdict}] {v.reason}")
    assert not bad, (
        "пометка injected-clock не подтверждается кодом (или файл не измерен) в:\n  "
        + "\n  ".join(bad)
        + "\n\nПометка означает приём №1 правила .claude/rules/deployment.md: часы "
          "приходят ВХОДОМ — якорь-литерал передаётся вызову аргументом, а не "
          "сравнивается со стенными часами. Либо сделай инъекцию настоящей, либо "
          "смени причину освобождения на ту, которая правда. Дописывать файл в "
          "какое-либо исключение ЗАПРЕЩЕНО — это и есть дефект, ради которого "
          "сторож написан."
    )


def test_every_injected_clock_claim_in_the_suite_is_true() -> None:
    """Сплошной обход живого набора: 51/51 подтверждены на 2026-09-04.

    Стоит даром сегодня и закрывает дыру навсегда — следующая ложная пометка краснеет
    в момент написания, а не через месяц на чужом хосте.
    """
    files = claiming_files(_TESTS_DIR)
    assert files, (
        "в наборе не найдено НИ ОДНОГО файла с пометкой injected-clock — либо каталог "
        "не тот, либо разбор пометки разошёлся с храповиком; пустая популяция делает "
        "этот сторож вакуумным, поэтому она сама является находкой")
    _assert_population_proven(files)


def test_the_measure_is_not_vacuous_on_the_live_suite() -> None:
    """«51 из 51» обязано значить «мера различает», а не «мера пропускает всех».

    Замер 04.09: среди файлов БЕЗ пометки подтверждённых 275, неподтверждённых 1418.
    Порог намеренно грубый (треть набора) — он ловит вырождение меры, а не колеблется
    вместе с набором.
    """
    claiming = {p.name for p in claiming_files(_TESTS_DIR)}
    unproven = proven = 0
    for f in sorted(_TESTS_DIR.glob("test_*.py")):
        if f.name in claiming:
            continue
        if measure_file(f).verdict == PROVEN:
            proven += 1
        else:
            unproven += 1
    total = proven + unproven
    assert total, "не с чем сравнивать: набор пуст"
    assert unproven > total // 3, (
        f"мера подтверждает почти всё подряд ({proven} из {total} файлов без пометки) "
        f"— «все претензии верны» тогда ничего не значит")


def test_a_real_unproven_file_of_the_suite_reddens_once_it_claims() -> None:
    """Мутация из карточки на НАСТОЯЩЕМ файле, а не на фикстуре.

    Берётся первый по алфавиту файл набора, у которого инъекции нет и пометки нет; ему
    дописывается пометка. Сторож обязан покраснеть — иначе сплошной обход выше зелен
    потому, что не умеет краснеть.
    """
    claiming = {p.name for p in claiming_files(_TESTS_DIR)}
    victim = None
    for f in sorted(_TESTS_DIR.glob("test_*.py")):
        if f.name in claiming or f.name == Path(__file__).name:
            continue
        if measure_file(f).verdict == UNPROVEN:
            victim = f
            break
    assert victim is not None, (
        "в наборе не нашлось файла без инъекции — мутацию ставить не на чем, и это "
        "само по себе находка о мере, а не повод пропустить контроль")

    mutated = _MARKER + "\n" + victim.read_text(encoding="utf-8")
    assert claims_injected_clock(mutated), "мутация не приписала претензию"
    assert measure_source(mutated, victim).verdict == UNPROVEN, (
        f"{victim.name} без единой инъекции объявлен подтверждённым, стоило приписать "
        f"пометку — сторож не отличает претензию от кода")


# --- одна строка на двух читателей ----------------------------------------

def test_marker_parsing_agrees_with_the_ratchet() -> None:
    """Пометку читают ДВА сторожа; разойдись они — один освободит, второй нет.

    Второй реализации разбора здесь нет намеренно (урок #47 «одно имя — один объект»):
    проверяется, что обе регулярки судят об одной и той же строке одинаково.
    """
    from spa_core.tests import test_frozen_date_ratchet as ratchet

    sample = _MARKER + "\n" + _HONEST_INJECTION
    assert ratchet._OPT_OUT_WITH_REASON_RE.search(sample), (
        "храповик не признаёт пометку, которую признаёт измеритель — файл был бы "
        "в классе и одновременно освобождён")
    assert claims_injected_clock(sample)

    bare = "# FROZEN-DATE-OK\n" + _HONEST_INJECTION
    assert not claims_injected_clock(bare), (
        "пометка без причины прочитана как претензия injected-clock — освобождение "
        "снова стало заклинанием")


def test_this_file_does_not_claim_the_reason_it_checks() -> None:
    """Собственная ловушка: сторож не имеет права освобождать сам себя проверяемой причиной.

    ``test_frozen_date_ratchet.py`` однажды выписал себе освобождение ИМЕННО так —
    дословной строкой в докстринге. Здесь это закреплено тестом, а не памятью автора.
    """
    src = Path(__file__).read_text(encoding="utf-8")
    assert not claims_injected_clock(src), (
        "файл выписал себе проверяемую претензию и попал в собственный обход — "
        "собирай строку-пометку из CLAIM, а не пиши её дословно")
