"""Храповик: класс «где наблюдения нет, система говорит „всё хорошо"» может только сжиматься.

Решение владельца 2026-08-23 (вариант A, карточка
`owner-decision-shest-nahodok-za-den-okazalis-odnoi-bole`, ADR-129) после ШЕСТИ находок
за один день 18.08 — все шесть одной болезни. Инвариант #17 в `CLAUDE.md` дал правилу
опору, этот файл даёт ему сторожа.

Признак класса измеряется в `spa_core/tests/_absent_observation.py` — там же объяснено,
почему он УЗКИЙ (наивное «есть `or 0.0`» даёт 1445 совпадений; запрет такого размера
снимают раньше, чем чинят первого писателя, — за это проект уже платил храповиком дат).

Приёмка владельца требовала положительный контроль **в обе стороны**, и он здесь:

* новый писатель с `or 0.0` рядом с понятием наблюдения — **краснеет**
  (`test_new_writer_with_or_zero_is_caught`);
* законный ноль («измерено и равно нулю», три исхода различимы) — **проходит**
  (`test_measured_zero_passes`).

Дописывать в базу, чтобы погасить падение, ЗАПРЕЩЕНО (инвариант #16): чинить писателя.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):                      # прямой запуск без conftest
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.tests import _absent_observation as ao

#: Потолок в ЧЛЕНАХ класса (замер цикла #378 на `origin/main` 84fa23031).
#: Снижать вместе с базой; поднимать — НИКОГДА.
#:
#: 187 → 192 у `or_falsy` — это НЕ разрешение на пять новых мест, и проверяется это
#: отдельно (`test_ceiling_is_reanchoring_not_growth`). Пока ключом была координата
#: `файл:строка`, два члена, стоящие на ОДНОЙ строке (вложенные `or`), склеивались в
#: один и класс был недосчитан на 5. Кода не прибавилось: множество координат дерева
#: совпало со старой базой 187 в 187. Старое число не выброшено — оно живёт ниже
#: вторым потолком, в своей единице.
CEILINGS = {ao.SIGNAL_OR: 192, ao.SIGNAL_EXCEPT: 60}

#: Второй потолок, в КООРДИНАТАХ (`файл:строка`) — прежняя единица измерения, ровно
#: то число, что стояло здесь до #378. Держится рядом намеренно: настоящее новое место
#: на новой строке пробивает его, даже если бы кто-то поднял потолок в членах.
COORDINATE_CEILINGS = {ao.SIGNAL_OR: 187, ao.SIGNAL_EXCEPT: 60}


def _raw() -> dict:
    return ao.load_baseline()


# ---------------------------------------------------------------- база о себе

def test_baseline_exists_and_explains_itself():
    """База без объяснения — молчаливое разрешение размером с дерево.

    Пустой список мест допустим НАМЕРЕННО: это состояние «класс закрыт», то есть
    цель храповика. Проверка, требующая непустой базы, краснела бы в день победы.
    """
    raw = _raw()
    assert isinstance(raw.get("signals"), dict)
    assert len(raw.get("_comment", "")) > 200, "база обязана объяснять себя"
    for signal in ao.SIGNALS:
        assert signal in raw["signals"], signal
        assert isinstance(raw["signals"][signal].get("places"), list)
        assert len(raw["signals"][signal].get("_what", "")) > 40, signal


def test_baseline_is_sorted_deduped_and_repo_relative():
    """Дубль прячет размер класса, порядок делает diff читаемым, абсолютный путь —
    это разрешение, действующее только на одной машине."""
    for signal in ao.SIGNALS:
        places = ao.baseline_places(_raw(), signal)
        assert places == sorted(places, key=ao.place_sort_key), signal
        assert len(places) == len(ao.keys_of(places)), signal
        for place in places:
            assert not Path(ao.place_file(place)).is_absolute(), place


def test_baseline_may_only_shrink():
    """Главное утверждение храповика: класс не растёт."""
    for signal, ceiling in CEILINGS.items():
        places = ao.baseline_places(_raw(), signal)
        assert len(places) <= ceiling, (
            f"сигнал {signal}: в базе {len(places)} мест при потолке {ceiling}. "
            "Дописывать сюда, чтобы погасить падение, ЗАПРЕЩЕНО (инвариант #16) — "
            "чинить писателя: три исхода (измерено · измерено и равно нулю · "
            "не измерено) обязаны быть различимы."
        )


def test_baseline_covers_only_watched_area():
    """Разрешение шире области наблюдения — тихое расширение полномочий."""
    for signal in ao.SIGNALS:
        for place in ao.baseline_places(_raw(), signal):
            rel = ao.place_file(place)
            assert rel.startswith(ao.SEARCH_ROOTS), place
            assert not rel.startswith(ao.SKIP_PREFIXES), place


# ---------------------------------------------------------------- дерево vs база

def test_tree_introduces_no_new_member():
    """Новое место класса, которого нет в базе, роняет прогон.

    Место, ИСЧЕЗНУВШЕЕ из дерева (писателя починили), падением не считается —
    иначе починка ломала бы CI и её пришлось бы «чинить» возвратом бага. Но и
    молча не проглатывается: см. `test_baseline_has_no_stale_entries`.
    """
    found = ao.scan_tree(ao.REPO_ROOT)
    raw = _raw()
    for signal in ao.SIGNALS:
        base_keys = ao.keys_of(ao.baseline_places(raw, signal))
        fresh = {p for p in ao.places_of(found, signal)
                 if ao.place_key(p) not in base_keys}
        assert not fresh, (
            f"сигнал {signal}: НОВЫЕ места класса «отсутствие наблюдения = благополучие» "
            f"({len(fresh)}): {sorted(fresh)[:10]}. Инвариант #17: отсутствие наблюдения "
            "обязано быть представлено отдельным значением (None / unchecked / ненулевой "
            "код возврата), а не нулём, пустотой или успехом."
        )


def test_baseline_has_no_stale_entries():
    """База, отставшая от дерева, — разрешение на то, чего уже нет.

    Строки сдвигаются от любой правки соседа, поэтому просроченной считается только
    запись, у которой в дереве не осталось НИ ОДНОГО места этого сигнала в файле:
    иначе храповик краснел бы на каждой правке форматирования.
    """
    found = ao.scan_tree(ao.REPO_ROOT)
    raw = _raw()
    for signal in ao.SIGNALS:
        live_files = {ao.place_file(p) for p in ao.places_of(found, signal)}
        stale = sorted({ao.place_file(p) for p in ao.baseline_places(raw, signal)
                        if ao.place_file(p) not in live_files})
        assert not stale, (
            f"сигнал {signal}: в базе есть файлы, где класса больше нет ({len(stale)}): "
            f"{stale[:10]}. Это разрешение на несуществующее — пересобрать базу и "
            f"опустить потолок CEILINGS[{signal!r}]."
        )


# ---------------------------------- положительный контроль: обе стороны (приёмка)

_NEW_WRITER_WITH_OR_ZERO = '''
from spa_core.utils.atomic import atomic_save

def report(snapshot):
    """Писатель отчёта, подставляющий благополучие вместо отсутствующего наблюдения."""
    row = {"tvl_usd": snapshot.get("tvl_usd") or 0.0}
    atomic_save(row, "data/probe.json")
    return row
'''

_MEASURED_ZERO_IS_HONEST = '''
from spa_core.utils.atomic import atomic_save

def report(snapshot):
    """Три исхода различимы: измерено · измерено и равно нулю · не измерено."""
    tvl = snapshot.get("tvl_usd")
    row = {"tvl_usd": tvl, "tvl_measured": tvl is not None}
    atomic_save(row, "data/probe.json")
    return row
'''

_NEW_WRITER_SWALLOWS_FAILURE = '''
from spa_core.utils.atomic import atomic_save

def probe(feed):
    try:
        atomic_save({"delay_hours": feed.read()}, "data/probe.json")
        return {"ok": True}
    except OSError:
        return {"ok": True}
'''

_FAILURE_IS_NAMED = '''
from spa_core.utils.atomic import atomic_save

def probe(feed):
    try:
        atomic_save({"delay_hours": feed.read()}, "data/probe.json")
        return {"ok": True}
    except OSError:
        return {"ok": False, "unchecked": "фид не прочитан"}
'''


def test_new_writer_with_or_zero_is_caught():
    """Приёмка владельца, сторона «краснеет»: новый писатель с `or 0.0`."""
    hits = ao.scan_source(_NEW_WRITER_WITH_OR_ZERO, "spa_core/probe_writer.py")
    signals = {h["signal"] for h in hits}
    assert ao.SIGNAL_OR in signals, hits


def test_measured_zero_passes():
    """Приёмка владельца, сторона «проходит»: законный ноль ловиться не должен."""
    assert ao.scan_source(_MEASURED_ZERO_IS_HONEST, "spa_core/probe_writer.py") == []


def test_handler_reporting_success_is_caught():
    """Второй сигнал, сторона «краснеет»: провал измерения выходит как успех."""
    hits = ao.scan_source(_NEW_WRITER_SWALLOWS_FAILURE, "spa_core/probe_writer.py")
    assert ao.SIGNAL_EXCEPT in {h["signal"] for h in hits}, hits


def test_handler_naming_the_failure_passes():
    """Второй сигнал, сторона «проходит»: отказ назван — это и есть цель."""
    hits = ao.scan_source(_FAILURE_IS_NAMED, "spa_core/probe_writer.py")
    assert ao.SIGNAL_EXCEPT not in {h["signal"] for h in hits}, hits


def test_non_writer_is_out_of_scope():
    """Подстановка, которая никуда не уезжает, членом класса не считается.

    Обратный контроль сужения: тот же исходник БЕЗ записи артефакта обязан пройти,
    иначе «узость» признака держалась бы на словах, а не на поведении.
    """
    without_writer = _NEW_WRITER_WITH_OR_ZERO.replace(
        "from spa_core.utils.atomic import atomic_save\n", ""
    ).replace('    atomic_save(row, "data/probe.json")\n', "")
    assert ao.scan_source(without_writer, "spa_core/probe_pure.py") == []


def test_skipped_area_is_really_skipped():
    """Исключения области — часть признака, и они обязаны действовать."""
    found = ao.scan_tree(ao.REPO_ROOT)
    for item in found:
        rel = ao.place_file(item["where"])
        assert not rel.startswith(ao.SKIP_PREFIXES), item


def test_baseline_file_is_valid_json_with_trailing_newline():
    """База едет в git и правится руками — битый JSON выключил бы храповик молча."""
    text = ao.BASELINE_PATH.read_text(encoding="utf-8")
    assert text.endswith("\n")
    json.loads(text)


# ------------------------------- якорь по содержимому (карточка #378, обе стороны)

#: Реальный член класса, взятый из дерева, — стенд обязан мерить то же, что CI.
_MEMBER_FILE = "spa_core/monitoring/capital_efficiency.py"


def _member_source() -> str:
    return (ao.REPO_ROOT / _MEMBER_FILE).read_text(encoding="utf-8")


def test_baseline_places_all_carry_an_anchor():
    """Половинчатая база обязана краснеть, а не молча ничего не находить.

    Запись старой формы (`файл:НОМЕР`, без отпечатка) не совпадёт ни с одним ключом
    дерева — и вместо честного «база не переякорена» храповик объявил бы весь файл
    новым и одновременно просроченным. Форма проверяется прямо.
    """
    for signal in ao.SIGNALS:
        for place in ao.baseline_places(_raw(), signal):
            assert ao.has_anchor(place), (
                f"{place}: запись без отпечатка выражения — база не переякорена; "
                "пересобрать: python3 -m spa_core.tests._absent_observation --write"
            )


def test_line_shift_is_not_a_new_member():
    """Приёмка карточки, сторона «НЕ красит»: сдвиг строк — не новое место.

    Именно этим храповик и болел: цикл #374 вставил 14 строк в начало
    `agent_health_monitor.py`, и запись `:1156` уехала на `:1170` при побайтово том же
    коде — прогон покраснел сообщением «НОВЫЕ места класса».
    """
    source = _member_source()
    before = ao.scan_source(source, _MEMBER_FILE)
    after = ao.scan_source("\n\n\n" + source, _MEMBER_FILE)

    assert before, "стенд обязан стоять на файле, который РЕАЛЬНО состоит в классе"
    # сдвиг действительно произошёл — иначе тест был бы украшением
    assert {h["where"] for h in before} != {h["where"] for h in after}
    # ...а вот ключи сравнения не сдвинулись
    assert (ao.keys_of(h["where"] for h in before)
            == ao.keys_of(h["where"] for h in after))


def test_genuinely_new_member_is_still_caught():
    """Приёмка карточки, сторона «красит»: настоящее новое место ловится.

    Обратный контроль к предыдущему тесту: якорь по содержимому обязан оставаться
    сторожем, а не превратиться в разрешение «правь что хочешь, ключи те же».
    """
    source = _member_source()
    before = ao.keys_of(h["where"] for h in ao.scan_source(source, _MEMBER_FILE))
    injected = source + (
        '\n\ndef _probe(snapshot):\n'
        '    return {"apy_pct": snapshot.get("apy_pct") or 0.0}\n'
    )
    after = ao.keys_of(h["where"] for h in ao.scan_source(injected, _MEMBER_FILE))
    assert after - before, "новое место класса обязано давать НОВЫЙ ключ"


def test_second_copy_of_the_same_expression_is_a_separate_member():
    """Два одинаковых выражения в одном файле — ДВА члена, а не один.

    Без порядкового номера у них совпал бы отпечаток, второе место исчезло бы из
    учёта, и храповик молча разрешил бы дубль. Это не гипотеза: старый ключ
    `файл:строка` склеивал ровно так — на пяти строках дерева стоит по два члена.
    """
    twice = (
        "from spa_core.utils.atomic import atomic_save\n"
        "def a(d):\n"
        '    atomic_save({"tvl_usd": d.get("tvl_usd") or 0.0}, "data/a.json")\n'
        "def b(d):\n"
        '    atomic_save({"tvl_usd": d.get("tvl_usd") or 0.0}, "data/b.json")\n'
    )
    keys = ao.keys_of(h["where"] for h in ao.scan_source(twice, "spa_core/probe.py"))
    assert len(keys) == 2, keys


def test_reformatting_a_member_does_not_move_its_anchor():
    """Перенос длинного выражения на две строки — не новое место.

    `ast.unparse` приводит запись к канону, поэтому отпечаток держится за СМЫСЛ
    выражения, а не за его вёрстку. Иначе якорь лечил бы только вставку строк ВЫШЕ,
    а на правке самого члена болел бы по-прежнему.
    """
    one_line = (
        "from spa_core.utils.atomic import atomic_save\n"
        "def a(d):\n"
        '    atomic_save({"tvl_usd": d.get("tvl_usd") or 0.0}, "data/a.json")\n'
    )
    wrapped = (
        "from spa_core.utils.atomic import atomic_save\n"
        "def a(d):\n"
        "    atomic_save(\n"
        '        {"tvl_usd": (\n'
        '            d.get("tvl_usd")\n'
        "            or 0.0\n"
        "        )},\n"
        '        "data/a.json",\n'
        "    )\n"
    )
    assert (ao.keys_of(h["where"] for h in ao.scan_source(one_line, "spa_core/probe.py"))
            == ao.keys_of(h["where"] for h in ao.scan_source(wrapped, "spa_core/probe.py")))


def test_ceiling_is_reanchoring_not_growth():
    """Потолок 187 → 192 обязан быть ПЕРЕСЧЁТОМ, а не разрешением на пять мест.

    Прежняя единица (координата `файл:строка`) сохранена вторым потолком и НЕ поднята.
    Настоящее новое место на новой строке пробивает её, даже если потолок в членах
    кто-то поднимет; новое место на строке существующего члена пробивает потолок в
    членах. Обе двери заперты порознь.
    """
    found = ao.scan_tree(ao.REPO_ROOT)
    for signal, ceiling in COORDINATE_CEILINGS.items():
        coords = {f"{ao.place_file(p)}:{ao.place_parts(p)[1]}"
                  for p in ao.places_of(found, signal)}
        assert len(coords) <= ceiling, (
            f"сигнал {signal}: координат {len(coords)} при потолке {ceiling}. "
            "Это НОВОЕ место класса на новой строке, а не эффект переякорения — "
            "чинить писателя (инвариант #17), а не число здесь."
        )


def test_baseline_and_tree_agree_member_for_member():
    """База и дерево обязаны сходиться ровно, в обе стороны.

    `test_tree_introduces_no_new_member` и `test_baseline_has_no_stale_entries` вместе
    этого НЕ дают: первый молчит о лишнем в базе, второй смотрит на файлы целиком и
    пропускает исчезнувший член в живом файле. После перехода на якорь такая сверка
    наконец возможна — координаты для неё были слишком подвижны.
    """
    found = ao.scan_tree(ao.REPO_ROOT)
    raw = _raw()
    for signal in ao.SIGNALS:
        tree_keys = ao.keys_of(ao.places_of(found, signal))
        base_keys = ao.keys_of(ao.baseline_places(raw, signal))
        assert tree_keys == base_keys, (
            f"сигнал {signal}: в дереве {len(tree_keys)}, в базе {len(base_keys)}; "
            f"только в дереве: {sorted(tree_keys - base_keys)[:5]}; "
            f"только в базе: {sorted(base_keys - tree_keys)[:5]}"
        )
