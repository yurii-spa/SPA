"""Батарея прибора «незнакомый класс в артефакте недостижимого раскола».

Заказ **G98 п. 1** (хвост `ADR-517`). Каждый тест здесь — либо контроль
правила в ОДНУ сторону, либо контроль в ОБРАТНУЮ; тест, никогда не видевший
настоящей поломки, есть украшение (`.claude/rules/deployment.md`).

Две поломки, которые батарея воспроизводит дословно, — МОИ, и обе найдены
замером, а не рассуждением:

* **189 выдуманных падений.** Значение `place` вне перечня лежит в 189
  записях `unresolved_path_census`, и первая редакция правила объявила бы их
  наблюдением «прибор упал бы 189 раз». Счётчик их не видел — это показала
  арифметика (`49 == 49`). Контроль:
  :func:`test_records_outside_the_enumeration_are_not_crashes`.
* **потерянная дорога записи.** Укладка класса в запись живёт во ВНУТРЕННЕМ
  цикле, а добавление записи в список — во внешнем; правило, искавшее оба в
  одном цикле, молча теряло раскол, на котором и нашлась та выдумка.
  Контроль: :func:`test_stored_field_across_two_loops_resolves`.

Часы здесь ВХОД, а не окружение: якорь :data:`_ANCHOR` передаётся аргументом
`now` в КАЖДЫЙ зов прибора, а отметки артефактов сцены считаются ОТ него же —
обе стороны сравнения закреплены, и календарь машины на вердикт не влияет.
"""
# FROZEN-DATE-OK: injected-clock — якорь `_ANCHOR` уходит аргументом `now` в
# `U.measure`/`U.run` и в `_tree`, который от него же считает отметки
# артефактов сцены; стенных часов в файле нет ни одного вызова.

from __future__ import annotations

import ast
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import rule_second_copy_census as census  # noqa: E402
from spa_core.monitoring import unknown_class_in_the_artifact as U  # noqa: E402

PRODUCER_REL = "spa_core/monitoring/scene.py"

#: Сцена, у которой `_reach_sites` соседа находит РОВНО один недостижимый
#: раскол. Форма взята у соседского контроля (`REACH_CONTROL_SOURCE`): строгий
#: накопитель `{v: 0 for v in _VERDICTS}` + `+=`, читатель спрашивает
#: объявленный класс. Публикация НАМЕРЕННО названа не как переменная
#: (`counts` → ключ `loud`, `entries` → ключ `pairs`): правило, угадывающее
#: ключ по имени переменной, обязано на этой сцене покраснеть.
SCENE = '''
VERDICT_CLEAN = "clean"
VERDICT_DIRTY = "dirty"
_VERDICTS = (VERDICT_CLEAN, VERDICT_DIRTY)

ARTIFACT = "scene_ledger.json"
PRODUCER = "spa_core/monitoring/scene.py"


def measure(rows):
    entries = list(rows)
    counts = {v: 0 for v in _VERDICTS}
    for entry in entries:
        counts[entry.get("verdict", VERDICT_CLEAN)] += 1
    return {"generated_by": PRODUCER, "loud": counts, "pairs": entries}


def caller(rows):
    doc = measure(rows)
    return len(doc)


def reader(doc):
    c = doc["loud"]
    return c[VERDICT_DIRTY] > 0
'''


#: Якорь часов. Передаётся аргументом `now` — то есть ИНЪЕКЦИЕЙ, а не
#: подпиской на календарь машины; отметки артефактов сцены считаются от него,
#: поэтому закреплены ОБЕ стороны сравнения возраста.
_ANCHOR = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)


def _tree(tmp_path: Path, *, source: str = SCENE,
          artifact: dict | str | None = "default",
          artifact_name: str = "spa_core/monitoring/scene_ledger.json",
          extra: dict | None = None, age_hours: float = 1.0) -> Path:
    """Одноразовое дерево со сценой и её артефактом."""
    (tmp_path / "spa_core" / "monitoring").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / PRODUCER_REL).write_text(source, encoding="utf-8")
    if artifact == "default":
        artifact = {
            "generated_by": PRODUCER_REL,
            "loud": {"clean": 1, "dirty": 1},
            "pairs": [{"verdict": "clean"}, {"verdict": "dirty"}],
        }
    if artifact is not None:
        stamp = (_ANCHOR - dt.timedelta(hours=age_hours)).isoformat()
        target = tmp_path / artifact_name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(artifact, str):
            target.write_text(artifact, encoding="utf-8")
        else:
            artifact.setdefault("generated_at", stamp)
            target.write_text(json.dumps(artifact), encoding="utf-8")
    for rel, doc in (extra or {}).items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(doc if isinstance(doc, str) else json.dumps(doc),
                        encoding="utf-8")
    return tmp_path


def _one(tmp_path: Path, **kw) -> dict:
    doc = U.measure(_tree(tmp_path, **kw), now=_ANCHOR, published=1)
    assert doc["population"] == 1, doc
    return doc["rows"][0]


# ===========================================================================
# Население: оно СОСЕДСКОЕ, и сверяется двумя дорогами
# ===========================================================================

def test_scene_really_carries_one_unreachable_split(tmp_path):
    """Предпосылка батареи ИЗМЕРЕНА, а не предположена.

    Сцена, в которой соседский шаг не находит недостижимого раскола, молча
    превратила бы каждый тест ниже в проверку пустого населения — и все они
    были бы зелёными, ничего не проверив.
    """
    rows = census._reach_sites(PRODUCER_REL, ast.parse(SCENE))
    unreachable = [r for r in rows
                   if r["reach"] == census.REACH_UNREACHABLE]
    assert len(unreachable) == 1, rows
    assert unreachable[0]["counter"] == "counts"
    assert unreachable[0]["accumulator"] == "strict"


def test_population_equals_the_published_number(tmp_path):
    doc = U.measure(_tree(tmp_path), now=_ANCHOR, published=1)
    assert doc["status"] == "MEASURED"
    assert doc["population"] == 1 == doc["published_population"]
    assert doc["applied"] is False


def test_population_disagreement_is_a_refusal_naming_both_numbers(tmp_path):
    with pytest.raises(U.NotMeasured) as exc:
        U.measure(_tree(tmp_path), now=_ANCHOR, published=2)
    assert "1" in str(exc.value) and "2" in str(exc.value)


def test_absent_neighbour_is_not_zero_unreachable(tmp_path):
    """Соседа не прочитали ⇒ ТРЕТИЙ ИСХОД, а не «недостижимых нет»."""
    out = U.run(_tree(tmp_path), write=False, now=_ANCHOR)
    assert out["measured"] is False
    assert out["doc"]["status"] == "UNMEASURED"
    assert U.NEIGHBOUR_STEP in out["doc"]["reason"] or \
        U.NEIGHBOUR_ARTIFACT in out["doc"]["reason"]
    assert out["doc"]["rows"] == []


def test_neighbour_step_present_but_unmeasured_is_a_refusal(tmp_path):
    tree = _tree(tmp_path, extra={U.NEIGHBOUR_ARTIFACT: {
        U.NEIGHBOUR_STEP: {"status": "UNMEASURED"}}})
    out = U.run(tree, write=False, now=_ANCHOR)
    assert out["doc"]["status"] == "UNMEASURED"
    assert "не измерен" in out["doc"]["reason"]


def test_neighbour_without_the_count_is_not_zero(tmp_path):
    """Отсутствие поля у соседа не есть ноль недостижимых (инв. #17)."""
    tree = _tree(tmp_path, extra={U.NEIGHBOUR_ARTIFACT: {
        U.NEIGHBOUR_STEP: {"status": "MEASURED", "reach_outcomes": {}}}})
    out = U.run(tree, write=False, now=_ANCHOR)
    assert out["doc"]["status"] == "UNMEASURED"
    assert "не есть ноль" in out["doc"]["reason"]


def test_published_number_is_read_from_the_neighbour_artifact(tmp_path):
    tree = _tree(tmp_path, extra={U.NEIGHBOUR_ARTIFACT: {
        U.NEIGHBOUR_STEP: {"status": "MEASURED", "reach_outcomes": {
            census.REACH_UNREACHABLE: 1}}}})
    doc = U.measure(tree, now=_ANCHOR)
    assert doc["published_population"] == 1


def test_unreadable_file_in_the_population_walk_refuses(tmp_path):
    tree = _tree(tmp_path)
    (tree / "scripts" / "broken.py").write_text("def (", encoding="utf-8")
    with pytest.raises(U.NotMeasured) as exc:
        U.measure(tree, now=_ANCHOR, published=1)
    assert "не прочитано" in str(exc.value)


# ===========================================================================
# ДОРОГА ПИСАТЕЛЯ: ключ карты вне перечня — положительный контроль
# ===========================================================================

def test_unknown_key_in_the_counter_map_is_seen(tmp_path):
    """Положительный контроль дороги ПИСАТЕЛЯ — и он поймал мою ошибку.

    Первая редакция сверяла арифметику с ПОЛНОЙ суммой карты, поэтому
    приращения незнакомого ключа объявлялись «спором двух дорог», и
    находка гасилась третьим исходом. Контроль обязан остаться: правило,
    гасящее собственную находку, зелено на любом чистом дереве.
    """
    row = _one(tmp_path, artifact={
        "generated_by": PRODUCER_REL,
        "loud": {"clean": 1, "dirty": 0, "renamed": 3},
        "pairs": [{"verdict": "clean"}],
    })
    assert row["outcome"] == U.SEEN
    assert row["unknown_keys"] == ["renamed"]
    assert row["would_raise_today"] == 3
    assert row["record_route"] == U.REC_CLEAN


def test_only_declared_classes_is_never(tmp_path):
    row = _one(tmp_path)
    assert row["outcome"] == U.NEVER
    assert row["would_raise_today"] == 0
    assert row["unknown_keys"] == []
    assert row["record_route"] == U.REC_CLEAN


def test_empty_enumeration_makes_every_key_unknown(tmp_path):
    """Писатель не объявил ни одного класса ⇒ незнаком КАЖДЫЙ ключ."""
    source = SCENE.replace("_VERDICTS = (VERDICT_CLEAN, VERDICT_DIRTY)",
                           "_VERDICTS = ()")
    row = _one(tmp_path, source=source)
    assert row["declared"] == []
    assert row["outcome"] == U.SEEN
    assert sorted(row["unknown_keys"]) == ["clean", "dirty"]


def test_published_key_is_not_guessed_from_the_variable_name(tmp_path):
    """Ключ берётся у `return`, а не у имени переменной.

    В артефакте лежат ДВА ключа: `counts` (имя переменной, с подложенным
    незнакомым классом) и `loud` (настоящая публикация, чистая). Правило,
    угадывающее ключ по имени, объявит `SEEN` — и покраснеет здесь.
    """
    row = _one(tmp_path, artifact={
        "generated_by": PRODUCER_REL,
        "counts": {"this_key_is_a_decoy": 9},
        "loud": {"clean": 1, "dirty": 0},
        "pairs": [{"verdict": "clean"}],
    })
    assert row["counter_key"] == "loud"
    assert row["outcome"] == U.NEVER
    assert row["would_raise_today"] == 0


def test_record_key_is_not_guessed_from_the_variable_name(tmp_path):
    row = _one(tmp_path)
    assert row["record_key"] == "pairs"
    assert row["record_field"] == "verdict"


# ===========================================================================
# ДОРОГА ЗАПИСИ и АРИФМЕТИКА — выдуманная находка в 189 падений
# ===========================================================================

def test_records_outside_the_enumeration_are_not_crashes(tmp_path):
    """Класс вне перечня ЕДЕТ в записи, но счётчик его НЕ ВИДЕЛ.

    Это дословный замер `unresolved_path_census` 05.10 (189 записей с
    `place = None` при сошедшейся арифметике `49 == 49`), уменьшенный до
    сцены. Правило, складывающее эти записи в «упал бы сегодня», печатает
    ЛОЖЬ — и покраснеет здесь.
    """
    row = _one(tmp_path, artifact={
        "generated_by": PRODUCER_REL,
        "loud": {"clean": 1, "dirty": 0},
        "pairs": [{"verdict": "clean"}] + [{"verdict": None}] * 5,
    })
    assert row["declared_total"] == 1
    assert row["records_accounted"] == 1
    assert row["records_outside"] == 5
    assert row["record_route"] == U.REC_RIDES
    # ГЛАВНОЕ: число заказа не выросло ни на единицу.
    assert row["would_raise_today"] == 0
    assert row["outcome"] == U.NEVER


def test_the_two_numbers_are_never_summed(tmp_path):
    doc = U.measure(_tree(tmp_path, artifact={
        "generated_by": PRODUCER_REL,
        "loud": {"clean": 1, "dirty": 0},
        "pairs": [{"verdict": "clean"}] + [{"verdict": None}] * 5,
    }), now=_ANCHOR, published=1)
    assert doc["would_raise_today"] == 0
    assert doc["rides_in_the_record_only"] == 5
    printed = "\n".join(U.report(doc))
    assert "ЧИСЛО ЗАКАЗА" in printed and "ДРУГОЕ УТВЕРЖДЕНИЕ" in printed


def test_arithmetic_disagreement_is_a_refusal_not_a_verdict(tmp_path):
    """Две дороги к одному событию спорят ⇒ вердикта нет."""
    row = _one(tmp_path, artifact={
        "generated_by": PRODUCER_REL,
        "loud": {"clean": 3, "dirty": 0},
        "pairs": [{"verdict": "clean"}],
    })
    assert row["record_route"] == U.REC_DISAGREES
    assert row["outcome"] == U.UNMEASURED
    assert row["gap"] == U.GAP_ARITHMETIC
    assert "3" in row["reason"] and "1" in row["reason"]


def test_stored_field_across_two_loops_resolves(tmp_path):
    """Укладка класса — во ВНУТРЕННЕМ цикле, добавление записи — во внешнем.

    Форма `unresolved_path_census`. Правило, искавшее добавление в том же
    цикле, что и укладку, объявляло дорогу записи неразобранной — и теряло
    единственную проверку, которая ловит выдуманные падения.
    """
    source = '''
PLACE_HERE = "here"
PLACE_THERE = "there"

ARTIFACT = "scene_ledger.json"
PRODUCER = "spa_core/monitoring/scene.py"


def measure(sites):
    rows = []
    by_place = {PLACE_HERE: 0, PLACE_THERE: 0}
    for site in sites:
        row = {"place": None}
        for cut in range(1, 3):
            place = site.get(str(cut))
            if place is None:
                continue
            row["place"] = place
            by_place[place] += 1
            break
        rows.append(row)
    return {"generated_by": PRODUCER, "where": by_place, "found": rows}


def caller(sites):
    doc = measure(sites)
    return len(doc)


def reader(doc):
    c = doc["where"]
    return c[PLACE_THERE] > 0
'''
    row = _one(tmp_path, source=source, artifact={
        "generated_by": PRODUCER_REL,
        "where": {"here": 1, "there": 0},
        "found": [{"place": "here"}] + [{"place": None}] * 4,
    })
    assert row["record_field"] == "place"
    assert row["record_key"] == "found"
    assert row["record_route"] == U.REC_RIDES
    assert row["records_outside"] == 4
    assert row["would_raise_today"] == 0


def test_unresolvable_record_route_still_answers_the_writer_road(tmp_path):
    """Дорога записи не разобралась — дорога ПИСАТЕЛЯ отвечает всё равно.

    Два утверждения, и одно не заложник другого: карта счётчика одна может
    доказать, что писатель незнакомый класс впустил.
    """
    source = SCENE.replace('return {"generated_by": PRODUCER, "loud": counts, '
                           '"pairs": entries}',
                           'return {"generated_by": PRODUCER, "loud": counts}')
    row = _one(tmp_path, source=source, artifact={
        "generated_by": PRODUCER_REL,
        "loud": {"clean": 1, "dirty": 0, "renamed": 2},
    })
    assert row["record_route"] == U.REC_UNRESOLVED
    assert row["record_gap"]
    assert row["outcome"] == U.SEEN
    assert row["would_raise_today"] == 2


# ===========================================================================
# АДРЕС артефакта: подтверждает сам артефакт, а не константа
# ===========================================================================

def test_no_file_claims_the_producer_is_the_third_outcome(tmp_path):
    """«Артефакта нет» ≠ «класс не встречался» — заказ требует развести."""
    row = _one(tmp_path, artifact={"generated_by": "somebody/else.py",
                                   "loud": {"clean": 1}})
    assert row["outcome"] == U.UNMEASURED
    assert row["gap"] == U.GAP_NO_ARTIFACT
    assert row["outcome"] != U.NEVER


def test_artifact_absent_entirely_is_the_same_third_outcome(tmp_path):
    row = _one(tmp_path, artifact=None)
    assert row["outcome"] == U.UNMEASURED
    assert row["gap"] == U.GAP_NO_ARTIFACT


def test_unreadable_artifact_is_named_apart_from_absent(tmp_path):
    """Нечитаемый файл и отсутствующий чинятся РАЗНЫМ, значит зовутся разно."""
    row = _one(tmp_path, artifact="{not json at all")
    assert row["outcome"] == U.UNMEASURED
    assert row["gap"] == U.GAP_ARTIFACT_UNREADABLE


def test_two_claimants_refuse_rather_than_pick_one(tmp_path):
    row = _one(tmp_path,
               artifact={"generated_by": "somebody/else.py", "loud": {}},
               extra={"data/one.json": {"generated_by": PRODUCER_REL,
                                        "loud": {"clean": 0, "dirty": 0}},
                      "data/two.json": {"generated_by": PRODUCER_REL,
                                        "loud": {"clean": 0, "dirty": 0}}})
    assert row["outcome"] == U.UNMEASURED
    assert row["gap"] == U.GAP_MANY_ARTIFACTS
    assert len(row["claimants"]) == 2


def test_constant_pointing_at_a_foreign_file_is_named_not_trusted(tmp_path):
    """Константа указывает на журнал СОСЕДА — судить по нему запрещено.

    Это та самая форма, которую я приписал `vacuous_guard_probe` по разбору
    глазами и в которой ОШИБСЯ (замер: константа есть адрес у 4 из 4).
    Проверка остаётся потому, что ровно она и опровергла догадку.
    """
    row = _one(tmp_path,
               artifact={"generated_by": "spa_core/monitoring/neighbour.py",
                         "loud": {"not_mine": 7}},
               extra={"data/mine.json": {"generated_by": PRODUCER_REL,
                                         "loud": {"clean": 1, "dirty": 0},
                                         "pairs": [{"verdict": "clean"}]}})
    assert row["artifact"] == "data/mine.json"
    assert row["artifact_constant_is_the_address"] is False
    assert row["outcome"] == U.NEVER
    assert row["would_raise_today"] == 0


def test_the_lying_constant_is_counted_in_the_head(tmp_path):
    doc = U.measure(_tree(
        tmp_path,
        artifact={"generated_by": "spa_core/monitoring/neighbour.py",
                  "loud": {"x": 1}},
        extra={"data/mine.json": {"generated_by": PRODUCER_REL,
                                  "loud": {"clean": 1, "dirty": 0},
                                  "pairs": [{"verdict": "clean"}]}}),
        now=_ANCHOR, published=1)
    assert doc["artifact_constant_is_not_the_address"] == 1
    assert "ИМЯ НЕ ЕСТЬ АДРЕС" in "\n".join(U.report(doc))


def test_search_set_is_declared_in_the_artifact(tmp_path):
    """«Не нашлось» есть утверждение о НАЗВАННОМ наборе, а не о дереве."""
    doc = U.measure(_tree(tmp_path), now=_ANCHOR, published=1)
    assert doc["search_globs"] == list(U.SEARCH_GLOBS)


# ===========================================================================
# ПЕРЕЧЕНЬ: разбор до неподвижной точки и его предел
# ===========================================================================

def test_enumeration_through_an_imported_constant_resolves(tmp_path):
    """Перечень собран из ВВЕЗЁННЫХ констант — форма 2 расколов из 4.

    `_VERDICTS = (VERDICT_A, VERDICT_B)`, где каждое имя само есть
    `other.X`. Один проход сверху вниз объявил бы перечень неразобранным и
    потерял половину населения — замер 05.10 поймал это на живом дереве.
    """
    source = '''
from spa_core.monitoring import other as other

VERDICT_A = other.A
VERDICT_B = other.B
_VERDICTS = (VERDICT_A, VERDICT_B)

ARTIFACT = "scene_ledger.json"
PRODUCER = "spa_core/monitoring/scene.py"


def measure(rows):
    entries = list(rows)
    counts = {v: 0 for v in _VERDICTS}
    for entry in entries:
        counts[entry.get("verdict", VERDICT_A)] += 1
    return {"generated_by": PRODUCER, "loud": counts, "pairs": entries}


def caller(rows):
    doc = measure(rows)
    return len(doc)


def reader(doc):
    c = doc["loud"]
    return c[VERDICT_B] > 0
'''
    tree = _tree(tmp_path, source=source, artifact={
        "generated_by": PRODUCER_REL,
        "loud": {"alpha": 1, "beta": 0},
        "pairs": [{"verdict": "alpha"}],
    })
    (tree / "spa_core" / "monitoring" / "other.py").write_text(
        'A = "alpha"\nB = "beta"\n', encoding="utf-8")
    doc = U.measure(tree, now=_ANCHOR, published=1)
    row = doc["rows"][0]
    assert row["declared"] == ["alpha", "beta"]
    assert row["outcome"] == U.NEVER


def test_unresolvable_enumeration_is_the_third_outcome(tmp_path):
    """Перечень собран ВЫЗОВОМ ⇒ третий исход, а не пустой перечень.

    Пустой перечень объявил бы НЕЗНАКОМЫМ каждый класс артефакта — то есть
    выдуманную находку на каждом ключе.
    """
    source = SCENE.replace("counts = {v: 0 for v in _VERDICTS}",
                           "counts = {v: 0 for v in make_classes()}")
    row = _one(tmp_path, source=source)
    assert row["outcome"] == U.UNMEASURED
    assert row["gap"] == U.GAP_ENUMERATION
    assert row["declared"] is None
    assert row["reason"]


def test_counter_absent_from_the_artifact_is_the_third_outcome(tmp_path):
    row = _one(tmp_path, artifact={"generated_by": PRODUCER_REL,
                                   "pairs": []})
    assert row["outcome"] == U.UNMEASURED
    assert row["gap"] == U.GAP_COUNTER_SHAPE


def test_counter_published_but_not_a_count_map(tmp_path):
    row = _one(tmp_path, artifact={"generated_by": PRODUCER_REL,
                                   "loud": {"clean": "many"},
                                   "pairs": []})
    assert row["outcome"] == U.UNMEASURED
    assert row["gap"] == U.GAP_COUNTER_SHAPE


# ===========================================================================
# ВОЗРАСТ: «не встречался» есть утверждение о возрасте артефакта
# ===========================================================================

def test_age_is_measured_from_the_injected_clock(tmp_path):
    doc = U.measure(_tree(tmp_path, age_hours=72.0), now=_ANCHOR, published=1)
    assert doc["rows"][0]["artifact_age_hours"] == pytest.approx(72.0)
    assert doc["oldest_artifact_hours"] == pytest.approx(72.0)
    assert "ВОЗРАСТ" in "\n".join(U.report(doc))


def test_artifact_without_a_stamp_has_no_age_and_not_zero(tmp_path):
    """Отметки нет ⇒ возраст `None`, а не ноль часов (инв. #17)."""
    row = _one(tmp_path, artifact={
        "generated_by": PRODUCER_REL,
        "generated_at": None,
        "loud": {"clean": 1, "dirty": 0},
        "pairs": [{"verdict": "clean"}],
    })
    assert row["artifact_age_hours"] is None
    assert row["outcome"] == U.NEVER


def test_unparsable_stamp_is_not_zero_either(tmp_path):
    row = _one(tmp_path, artifact={
        "generated_by": PRODUCER_REL,
        "generated_at": "позавчера",
        "loud": {"clean": 1, "dirty": 0},
        "pairs": [{"verdict": "clean"}],
    })
    assert row["artifact_age_hours"] is None


# ===========================================================================
# Форма ответа и доставка
# ===========================================================================

def test_outcomes_account_for_every_row(tmp_path):
    doc = U.measure(_tree(tmp_path), now=_ANCHOR, published=1)
    assert sum(doc["outcomes"].values()) == doc["population"]
    assert set(doc["outcomes"]) == set(U._OUTCOMES)
    assert set(doc["record_routes"]) == set(U._REC_OUTCOMES)
    assert set(doc["unmeasured_reasons"]) == set(U._GAPS)


def test_run_writes_the_artifact_and_reports_measured(tmp_path):
    dest = tmp_path / "out.json"
    out = U.run(_tree(tmp_path), dest=dest, write=True, now=_ANCHOR,
                published=1)
    assert out["measured"] is True
    doc = json.loads(dest.read_text(encoding="utf-8"))
    assert doc["status"] == "MEASURED"
    assert doc["generated_by"] == U.PRODUCER
    assert doc["applied"] is False


def test_refusal_is_an_outcome_not_a_traceback(tmp_path):
    dest = tmp_path / "out.json"
    out = U.run(_tree(tmp_path), dest=dest, write=True, now=_ANCHOR,
                published=99)
    assert out["measured"] is False
    doc = json.loads(dest.read_text(encoding="utf-8"))
    assert doc["status"] == "UNMEASURED"
    assert doc["reason"]
    assert U.report(doc)[0].startswith("НЕ ИЗМЕРЕНО")


def test_main_returns_two_when_not_measured(tmp_path):
    tree = _tree(tmp_path)
    code = U.main(["--root", str(tree), "--out", str(tmp_path / "o.json")])
    assert code == 2


def test_the_instrument_touches_nothing_it_measures(tmp_path):
    """ADVISORY: артефакты сцены не переписываются ни одним байтом."""
    tree = _tree(tmp_path)
    target = tree / "spa_core" / "monitoring" / "scene_ledger.json"
    before = target.read_bytes()
    source_before = (tree / PRODUCER_REL).read_bytes()
    U.measure(tree, now=_ANCHOR, published=1)
    assert target.read_bytes() == before
    assert (tree / PRODUCER_REL).read_bytes() == source_before


def test_blind_spots_are_declared(tmp_path):
    doc = U.measure(_tree(tmp_path), now=_ANCHOR, published=1)
    blind = doc["what_it_does_not_prove"]
    assert len(blind) >= 5
    assert any("ВОЗРАСТ" in line for line in blind)
    assert any("АРИФМЕТИКА" in line for line in blind)
