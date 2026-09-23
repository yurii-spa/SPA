"""Заказ G77 п. 1 — ВРЕД у читателя открытого счётчика, а не его поверхность.

ADR-460 померил поверхность: 158 счётчиков в ``spa_core/monitoring`` и
``scripts`` открыты классу, которого никто не объявлял. Вреда это не
доказывает, и шаг соседа сказал это вслух: у известного случая (ADR-459) вред
лежал НЕ в счётчике, а у его читателя — ``reaching`` считал только один
объявленный класс, и незнакомая строка молча оказывалась в другом исходе, а не
лишней строкой отчёта.

Каждый тест здесь — положительный контроль: он воспроизводит либо форму уже
случившейся аварии, либо дефект, который правило ОБЯЗАНО не совершить (принять
запись за чтение, принять убежавший счётчик за безвредный, принять связь по
неоднозначному имени поля за доказательство).

**Два третьих исхода, которые набор держит отдельно:** «читатель безвреден» и
«читатель не измерен» — это РАЗНЫЕ ответы, и слить их значило бы выдать НЕ
ИЗМЕРЕНО за измеренный исход (инв. #17).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from spa_core.monitoring import rule_second_copy_census as census
from spa_core.monitoring.rule_second_copy_census import (
    READER_GAP_DYNAMIC,
    READER_GAP_ESCAPES,
    READER_GAP_NO_READ,
    READER_HARM_CONTROL_CLEAN,
    READER_HARM_CONTROL_SOURCE,
    READER_SPLITS_DECLARED,
    READER_UNRESOLVED,
    READER_WHOLESALE_ONLY,
    SPLIT_AT_CLASS,
    SPLIT_AT_COUNTER,
    SPLIT_VIA_FIELD,
    UNMEASURED_READER_CENSUS,
    UNMEASURED_READER_CONTROL,
    UNMEASURED_READER_POPULATION,
    _reader_harm_control,
    _reader_sites,
    open_class_counter_census,
    open_counter_reader_harm,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def sites(source: str):
    return _reader_sites("<scene>", ast.parse(source))


def only(source: str) -> dict:
    found = sites(source)
    assert len(found) == 1, [s["counter"] for s in found]
    return found[0]


def scene(body: str) -> str:
    """Открытый счётчик + переданное тело читателя.

    Ключ приходит из артефакта и не сверен принадлежностью — иначе сосед не
    считал бы счётчик открытым и мерить читателя было бы НЕ У ЧЕГО.
    """
    return (
        "def probe(rows):\n"
        "    counts = {}\n"
        "    for row in rows:\n"
        "        cls = str(row.get('outcome'))\n"
        "        counts[cls] = counts.get(cls, 0) + 1\n"
        + body
    )


# ---------------------------------------------------------------------------
# 1. ИЗВЕСТНЫЙ СЛУЧАЙ — правило обязано найти вред ВСЕМИ ТРЕМЯ формами
# ---------------------------------------------------------------------------

def test_known_case_control_passes_both_halves():
    """Контроль — предпосылка шага. Не прошёл ⇒ шаг обязан ОТКАЗАТЬ целиком."""
    control = _reader_harm_control()
    assert control["passed"] is True, control
    assert control["known_case_split"] == 2
    assert sorted(control["split_forms"]) == sorted(
        (SPLIT_AT_COUNTER, SPLIT_AT_CLASS, SPLIT_VIA_FIELD))
    assert control["clean_false_harm"] == 0


def test_known_case_scene_proves_harm_at_both_counters():
    found = sites(READER_HARM_CONTROL_SOURCE)
    assert [s["verdict"] for s in found] == [READER_SPLITS_DECLARED] * 2


def test_known_case_reach_counter_is_proven_through_the_field_hop():
    """Класс уехал полем `reach` и сравнился ТАМ — ровно форма ADR-459."""
    reach = [s for s in sites(READER_HARM_CONTROL_SOURCE)
             if s["key"] == "reach"]
    assert len(reach) == 1
    assert SPLIT_VIA_FIELD in reach[0]["split_forms"]


def test_known_case_value_counter_is_proven_at_the_counter_itself():
    values = [s for s in sites(READER_HARM_CONTROL_SOURCE)
              if s["key"] == "outcome"]
    assert len(values) == 1
    assert SPLIT_AT_COUNTER in values[0]["split_forms"]
    assert SPLIT_AT_CLASS in values[0]["split_forms"]


# ---------------------------------------------------------------------------
# 2. ОТРИЦАТЕЛЬНАЯ ПОЛОВИНА — правило обязано ПРОМАХНУТЬСЯ там, где должно
# ---------------------------------------------------------------------------

def test_clean_scene_has_one_benign_reader_and_one_escaped_counter():
    found = sites(READER_HARM_CONTROL_CLEAN)
    assert sorted(s["verdict"] for s in found) == sorted(
        (READER_WHOLESALE_ONLY, READER_UNRESOLVED))
    gone = [s for s in found if s["verdict"] == READER_UNRESOLVED]
    assert gone[0]["gap"] == READER_GAP_ESCAPES


def test_iteration_into_a_report_is_an_extra_line_not_another_outcome():
    site = only(scene("    for name, hits in counts.items():\n"
                      "        print(name, hits)\n"))
    assert site["verdict"] == READER_WHOLESALE_ONLY
    assert site["splits"] == []


@pytest.mark.parametrize("body", [
    "    return sum(counts.values())\n",
    "    return len(counts)\n",
    "    return sorted(counts)\n",
    "    for name in counts:\n        print(name)\n",
    "    return ['x' for name in counts]\n",
    "    return 'a' in counts\n",
])
def test_whole_counter_reads_are_benign(body):
    assert only(scene(body))["verdict"] == READER_WHOLESALE_ONLY


def test_a_lowercase_local_name_is_not_a_declared_class():
    """Иначе «раскол» доказывался бы сравнением с любой переменной."""
    site = only(scene("    wanted = rows[0]\n"
                      "    if cls == wanted:\n"
                      "        print(cls)\n"
                      "    for name in counts:\n"
                      "        print(name)\n"))
    assert site["verdict"] == READER_WHOLESALE_ONLY


def test_ambiguous_field_name_does_not_prove_harm():
    """Связь идёт по ИМЕНИ ПОЛЯ: под неоднозначным именем доказывать нечего."""
    site = only(scene("    seen = [{'outcome': cls}, {'outcome': rows[0]}]\n"
                      "    hits = [s for s in seen if s['outcome'] == 'ok']\n"
                      "    for name in counts:\n"
                      "        print(name, hits)\n"))
    assert site["ambiguous_fields"] == ["outcome"]
    assert site["verdict"] == READER_WHOLESALE_ONLY


# ---------------------------------------------------------------------------
# 3. ЗАПИСЬ — НЕ ЧТЕНИЕ. Дефект, который правило обязано не совершить
# ---------------------------------------------------------------------------

def test_a_literal_counter_next_door_is_a_write_not_a_declared_read():
    """`counts['total'] = counts.get('total', 0) + 1` — писатель.

    Не исключив записи, шаг объявил бы расколотым ВСЯКИЙ словарь, у которого
    рядом есть хоть один литеральный счётчик: правая часть счётчика всегда
    читает тот же словарь объявленным ключом.
    """
    found = sites(scene("        counts['total'] = counts.get('total', 0) + 1\n"
                        "    for name in counts:\n"
                        "        print(name)\n"))
    open_site = [s for s in found if s["key"] == "cls"]
    assert len(open_site) == 1
    assert open_site[0]["verdict"] == READER_WHOLESALE_ONLY


def test_the_counters_own_get_is_not_counted_as_a_reader():
    site = only(scene("    for name in counts:\n        print(name)\n"))
    assert site["dynamic_reads"] == 0, site


# ---------------------------------------------------------------------------
# 4. ТРЕТИЙ ИСХОД — у каждого своё имя, и ни один не есть «вреда нет»
# ---------------------------------------------------------------------------

def test_escaping_counter_is_unmeasured_not_benign():
    site = only(scene("    return {'counts': counts}\n"))
    assert site["verdict"] == READER_UNRESOLVED
    assert site["gap"] == READER_GAP_ESCAPES


def test_counter_passed_to_a_call_escapes():
    site = only(scene("    publish(counts)\n"))
    assert site["gap"] == READER_GAP_ESCAPES


def test_dynamic_key_read_is_unmeasured_not_benign():
    site = only(scene("    wanted = rows[0]\n"
                      "    return counts.get(wanted, 0)\n"))
    assert site["verdict"] == READER_UNRESOLVED
    assert site["gap"] == READER_GAP_DYNAMIC


def test_no_read_at_all_is_unmeasured_not_benign():
    site = only(scene("    return len(rows)\n"))
    assert site["verdict"] == READER_UNRESOLVED
    assert site["gap"] == READER_GAP_NO_READ


def test_harm_outranks_a_gap_when_both_are_present():
    """Убежавший счётчик не отменяет уже ДОКАЗАННОГО раскола."""
    site = only(scene("    hits = counts.get('ok', 0)\n"
                      "    return {'counts': counts, 'ok': hits}\n"))
    assert site["verdict"] == READER_SPLITS_DECLARED
    assert site["escapes"] >= 1


# ---------------------------------------------------------------------------
# 5. ФОРМЫ ДОКАЗАТЕЛЬСТВА
# ---------------------------------------------------------------------------

def test_declared_key_read_of_the_counter_is_harm():
    site = only(scene("    return counts['ok'] + counts.get('bad', 0)\n"))
    assert site["split_forms"] == [SPLIT_AT_COUNTER]


def test_uppercase_name_counts_as_a_declared_class():
    """Константа, пришедшая импортом, иначе занижала бы вред молча."""
    site = only(scene("    if cls == REACH_LIVE:\n        print(cls)\n"))
    assert site["split_forms"] == [SPLIT_AT_CLASS]


def test_module_constant_counts_as_a_declared_class():
    source = ("LIVE = 'live'\n\n\n" + scene(
        "    if cls != LIVE:\n        print(cls)\n"))
    assert only(source)["split_forms"] == [SPLIT_AT_CLASS]


def test_field_hop_is_exactly_one_step():
    site = only(scene("    seen = [{'outcome': cls}]\n"
                      "    hits = [s for s in seen if s['outcome'] == 'ok']\n"
                      "    for name in counts:\n        print(name, hits)\n"))
    assert site["split_forms"] == [SPLIT_VIA_FIELD]


# ---------------------------------------------------------------------------
# 6. ПОТОЛОК СВЕРХУ — завышение населения соседом, найденное ЗАПУСКОМ
# ---------------------------------------------------------------------------

def test_key_unpacked_from_a_tuple_is_named_a_literal():
    """Сосед зовёт такой ключ артефактным; на деле это литерал (ADR-460 наизнанку)."""
    source = ("def probe(rows, doc):\n"
              "    buckets = {'a': 0, 'b': 0}\n"
              "    for row in rows:\n"
              "        if row:\n"
              "            bucket, why = 'a', f\"{doc.get('x')}\"\n"
              "        else:\n"
              "            bucket, why = 'b', ''\n"
              "        buckets[bucket] = buckets.get(bucket, 0) + 1\n"
              "    return buckets['a']\n")
    site = only(source)
    assert site["key_literal_by_unpacking"] == "literal_by_unpacking"


def test_a_mixed_binding_is_not_called_a_literal():
    source = ("def probe(rows, doc):\n"
              "    buckets = {}\n"
              "    for row in rows:\n"
              "        bucket, why = 'a', f\"{doc.get('x')}\"\n"
              "        if row:\n"
              "            bucket = str(row.get('cls'))\n"
              "        buckets[bucket] = buckets.get(bucket, 0) + 1\n"
              "    return buckets['a']\n")
    assert only(source)["key_literal_by_unpacking"] == "mixed"


def test_an_ordinary_artifact_key_carries_no_unpacking_flag():
    site = only(scene("    return counts['ok']\n"))
    assert site["key_literal_by_unpacking"] is None


# ---------------------------------------------------------------------------
# 7. ОТКАЗЫ ШАГА — три, и у каждого своё машинное имя
# ---------------------------------------------------------------------------

def test_step_refuses_when_the_census_is_absent(tmp_path):
    doc = open_counter_reader_harm(tmp_path, None)
    assert doc["status"] == "UNMEASURED"
    assert doc["unmeasured_class"] == UNMEASURED_READER_CENSUS


def test_step_refuses_when_the_census_itself_is_unmeasured(tmp_path):
    doc = open_counter_reader_harm(tmp_path, {"status": "UNMEASURED"})
    assert doc["unmeasured_class"] == UNMEASURED_READER_CENSUS


def test_step_refuses_when_the_census_named_no_population(tmp_path):
    doc = open_counter_reader_harm(tmp_path, {"status": "MEASURED"})
    assert doc["unmeasured_class"] == UNMEASURED_READER_CENSUS


def test_step_refuses_when_its_own_walk_disagrees_with_the_census(tmp_path):
    """Замер читателя по ДРУГОМУ населению отвечал бы на другой вопрос."""
    (tmp_path / "spa_core" / "monitoring").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "spa_core" / "monitoring" / "m.py").write_text(
        scene("    return counts['ok']\n"), encoding="utf-8")
    doc = open_counter_reader_harm(
        tmp_path, {"status": "MEASURED", "open_to_an_unnamed_class": 99})
    assert doc["status"] == "UNMEASURED"
    assert doc["unmeasured_class"] == UNMEASURED_READER_POPULATION
    assert doc["walked"] == 1 and doc["census"] == 99


def test_step_refuses_when_the_control_misses_the_known_case(tmp_path,
                                                             monkeypatch):
    """Число от правила, промахивающегося по известному случаю, есть свойство
    ПРАВИЛА. Сцена подменяется безвредной — шаг обязан отказать, а не мерить."""
    monkeypatch.setattr(census, "READER_HARM_CONTROL_SOURCE",
                        scene("    for name in counts:\n        print(name)\n"))
    doc = open_counter_reader_harm(
        tmp_path, {"status": "MEASURED", "open_to_an_unnamed_class": 0})
    assert doc["status"] == "UNMEASURED"
    assert doc["unmeasured_class"] == UNMEASURED_READER_CONTROL


def test_step_refuses_when_the_clean_half_starts_claiming_harm(tmp_path,
                                                               monkeypatch):
    """Вторая половина контроля не есть украшение первой."""
    monkeypatch.setattr(census, "READER_HARM_CONTROL_CLEAN",
                        READER_HARM_CONTROL_SOURCE)
    doc = open_counter_reader_harm(
        tmp_path, {"status": "MEASURED", "open_to_an_unnamed_class": 0})
    assert doc["unmeasured_class"] == UNMEASURED_READER_CONTROL


# ---------------------------------------------------------------------------
# 8. ЖИВОЕ ДЕРЕВО — замер обязан сходиться сам с собой
# ---------------------------------------------------------------------------

def test_live_tree_population_matches_the_census_exactly():
    opened = open_class_counter_census(REPO_ROOT)
    assert opened["status"] == "MEASURED"
    harm = open_counter_reader_harm(REPO_ROOT, opened)
    assert harm["status"] == "MEASURED", harm.get("reason")
    assert harm["population"] == opened["open_to_an_unnamed_class"]


def test_live_tree_verdicts_account_for_every_counter():
    opened = open_class_counter_census(REPO_ROOT)
    harm = open_counter_reader_harm(REPO_ROOT, opened)
    assert sum(harm["reader_verdicts"].values()) == harm["population"]
    gaps = harm["unmeasured_reader_reasons"]
    assert sum(gaps.values()) == harm["reader_verdicts"][READER_UNRESOLVED]


def test_live_tree_harm_is_not_the_whole_population():
    """Поверхность ≠ вред. Совпади числа — шаг мерил бы счётчик, не читателя."""
    opened = open_class_counter_census(REPO_ROOT)
    harm = open_counter_reader_harm(REPO_ROOT, opened)
    assert 0 < harm["reader_verdicts"][READER_SPLITS_DECLARED] < harm["population"]


def test_live_tree_step_is_advisory():
    opened = open_class_counter_census(REPO_ROOT)
    harm = open_counter_reader_harm(REPO_ROOT, opened)
    assert harm["applied"] is False
    assert harm["order"] == "G77.1"


def test_live_tree_names_its_blindness():
    opened = open_class_counter_census(REPO_ROOT)
    harm = open_counter_reader_harm(REPO_ROOT, opened)
    assert len(harm["blind"]) >= 5


# ---------------------------------------------------------------------------
# 9. ОТЧЁТ — НЕ ИЗМЕРЕНО обязано читаться как отказ, а не как чистота
# ---------------------------------------------------------------------------

def test_report_says_unmeasured_when_the_step_is_absent():
    lines = census.report({})
    said = [ln for ln in lines if "ЧИТАТЕЛЬ СЧЁТЧИКА" in ln]
    assert said and "НЕ ИЗМЕРЕНО" in said[0]


def test_report_names_the_refusal_class():
    doc = {"open_counter_reader_harm": {
        "status": "UNMEASURED", "unmeasured_class": UNMEASURED_READER_POPULATION,
        "reason": "своё число разошлось с соседним"}}
    said = [ln for ln in census.report(doc) if "ЧИТАТЕЛЬ СЧЁТЧИКА" in ln]
    assert UNMEASURED_READER_POPULATION in said[0]


def test_report_prints_the_harm_and_the_ceiling_separately():
    opened = open_class_counter_census(REPO_ROOT)
    doc = {"open_counter_reader_harm":
           open_counter_reader_harm(REPO_ROOT, opened)}
    lines = census.report(doc)
    assert any("ПОТОЛОК СВЕРХУ" in ln for ln in lines)
    assert any("ЧЕМ ДОКАЗАН" in ln for ln in lines)
    assert any("КОНТРОЛЬ" in ln and "ЧИТАТЕЛЬ" in ln for ln in lines)


# ---------------------------------------------------------------------------
# 10. ПЯТЬ ДЫР, НАЙДЕННЫХ БАТАРЕЕЙ МУТАЦИЙ (первый заход 19 из 24)
#     Каждая мутация ниже ВЫЖИЛА, и все пять были слабостью ЭТИХ тестов, а не
#     прибора: ни один тест не ослаблен, добавлены новые (инв. #16).
# ---------------------------------------------------------------------------

def test_a_field_carrying_someone_elses_value_proves_nothing():
    """Мутация «поле связывается с классом без проверки значения» выжила.

    Связь идёт по имени поля, и не спросив, ЛЕЖИТ ЛИ там наш класс, шаг
    доказывал бы вред всяким сравнением любого поля в той же области.
    """
    site = only(scene("    seen = [{'kind': rows[0]}]\n"
                      "    hits = [s for s in seen if s['kind'] == 'ok']\n"
                      "    for name in counts:\n        print(name, hits)\n"))
    assert site["verdict"] == READER_WHOLESALE_ONLY
    assert site["split_forms"] == []


def test_control_refuses_when_a_whole_form_of_harm_goes_unfound(tmp_path,
                                                                monkeypatch):
    """Мутация «контроль не требует всех трёх форм» выжила.

    Сцена ниже несёт вред у ОБОИХ счётчиков, но одной формой. Правило,
    разучившееся видеть перенос класса полем, прошло бы такой контроль молча —
    и ненайденная форма стала бы «вреда нет» на живом дереве.
    """
    monkeypatch.setattr(census, "READER_HARM_CONTROL_SOURCE",
                        "def one_form(rows):\n"
                        "    counts = {}\n"
                        "    other = {}\n"
                        "    for row in rows:\n"
                        "        cls = str(row.get('outcome'))\n"
                        "        counts[cls] = counts.get(cls, 0) + 1\n"
                        "        kind = str(row.get('kind'))\n"
                        "        other[kind] = other.get(kind, 0) + 1\n"
                        "    return counts['ok'] + other['ok']\n")
    doc = open_counter_reader_harm(
        tmp_path, {"status": "MEASURED", "open_to_an_unnamed_class": 0})
    assert doc["status"] == "UNMEASURED"
    assert doc["unmeasured_class"] == UNMEASURED_READER_CONTROL
    assert "формами" in doc["reason"]


def test_step_refuses_an_unmeasured_census_even_when_it_carries_a_number(
        tmp_path):
    """Мутация «перепись соседа не проверяется на измеренность» выжила.

    Прошлый тест подавал отказ БЕЗ числа, и шаг спотыкался о него по второй
    причине — то есть проверял не то, что утверждал. Отказ соседа с оставшимся
    числом есть НЕ ИЗМЕРЕНО, и мерить читателя по нему нельзя.
    """
    doc = open_counter_reader_harm(
        tmp_path, {"status": "UNMEASURED", "open_to_an_unnamed_class": 158})
    assert doc["status"] == "UNMEASURED"
    assert doc["unmeasured_class"] == UNMEASURED_READER_CENSUS


def test_subscript_read_by_an_unresolvable_key_is_not_a_declared_split():
    """Мутация «чтение по неразрешимому ключу зовётся объявленным» выжила.

    Прошлый тест брал только форму `.get(имя)`; форма `counts[имя]` идёт
    другой веткой, и её не проверял никто.
    """
    site = only(scene("    wanted = rows[0]\n"
                      "    return counts[wanted]\n"))
    assert site["verdict"] == READER_UNRESOLVED
    assert site["gap"] == READER_GAP_DYNAMIC


def test_pre_seeding_the_counter_is_a_write_not_a_declared_read():
    """Мутация «запись по индексу считается чтением счётчика» выжила.

    `counts['ok'] = 0` — предзаполнение, и счётчиком объявленной формы оно не
    является, поэтому исключение записей его не покрывает. Считать его
    чтением значило бы объявить расколотым всякий предзаполненный словарь —
    а предзаполнение перечнем, как показал ADR-460, не спасает и сторожем не
    является.
    """
    site = only("def probe(rows):\n"
                "    counts = {}\n"
                "    counts['ok'] = 0\n"
                "    for row in rows:\n"
                "        cls = str(row.get('outcome'))\n"
                "        counts[cls] = counts.get(cls, 0) + 1\n"
                "    for name in counts:\n"
                "        print(name)\n")
    assert site["verdict"] == READER_WHOLESALE_ONLY
    assert site["split_forms"] == []
