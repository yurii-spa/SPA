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

#: Потолки класса на 2026-08-23 (замер цикла #360 на чистом `origin/main` 07784b1af).
#: Снижать вместе с базой; поднимать — НИКОГДА.
CEILINGS = {ao.SIGNAL_OR: 187, ao.SIGNAL_EXCEPT: 60}


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
        assert places == sorted(places), signal
        assert len(places) == len(set(places)), signal
        for place in places:
            assert not Path(place.split(":")[0]).is_absolute(), place


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
            rel = place.split(":")[0]
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
        fresh = set(ao.places_of(found, signal)) - set(ao.baseline_places(raw, signal))
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
        live_files = {p.split(":")[0] for p in ao.places_of(found, signal)}
        stale = sorted({p.split(":")[0] for p in ao.baseline_places(raw, signal)
                        if p.split(":")[0] not in live_files})
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
        rel = item["where"].split(":")[0]
        assert not rel.startswith(ao.SKIP_PREFIXES), item


def test_baseline_file_is_valid_json_with_trailing_newline():
    """База едет в git и правится руками — битый JSON выключил бы храповик молча."""
    text = ao.BASELINE_PATH.read_text(encoding="utf-8")
    assert text.endswith("\n")
    json.loads(text)
