"""Батарея §24 «Decision types» (ADR-967).

Каждая проба здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: зелена на целом контуре и красна
на ОДНОМ названном порванном звене. Ни одно утверждение не судит о структуре
ПОДСТРОКОЙ текста (ADR-333): проверяется форма отчёта и ПЕРЕХОД вердикта.

Три ошибки замера, которые эта батарея держит, чтобы они не вернулись:

* **пустое подавление, выглядевшее работающим.** Первая редакция глушила
  ``contextlib.redirect_stdout``, а двери пишут через ``logging`` (stderr) —
  отчёт выходил вперемешку с чужим логом, и «подавление» читалось как
  исполненное. Держит :func:`test_doors_log_is_silenced_and_restored`.
* **домен по ИМЕНИ константы вместо её ЗНАЧЕНИЯ.** Первая редакция брала все
  строковые константы модуля и объявила доменом двери допуска ИМЕНА ФАЙЛОВ
  (``current_positions.json``). Держит
  :func:`test_declared_domain_is_not_any_string_constant_of_the_module`.
* **форма результата по ПЕРВОЙ сцене.** Вторая дверь политики получала
  ``typed_only`` лишь потому, что в сцене ``KEEP`` список нарушений пуст —
  вердикт о ФОРМЕ зависел от порядка сцен. Держит
  :func:`test_result_form_is_measured_over_all_scenes_not_the_first`.
"""
# Литеральной даты в этом файле НЕТ ни одной, поэтому и претензии
# `FROZEN-DATE-OK` здесь нет: якорь сцены (`SCENE_NOW`) объявлен в §22 и
# ВВОЗИТСЯ, часы дверей получают момент входом `now`, а записка об инъекции
# без своего якоря была бы претензией без предмета.
from __future__ import annotations

import logging

import pytest

from spa_core.analytics import anti_churn_census as s22
from spa_core.analytics import decision_type_census as s24
from spa_core.analytics import new_capital_census as s20
from spa_core.analytics.decision_type_census import (
    DOORS_24, EXPECTATION_KINDS, EXPECTATION_SCENES, NEAR_MISS_NOT_A_DOOR,
    ORDER_G955_NAMED, OWNER_DECISION_TYPES, OWNER_TYPES_DECLARED,
    PRESENCE_KINDS, RESULT_FORM_KINDS, SCENE_GROUNDS, SURFACES_24,
    SURFACES_WITHOUT_A_TYPED_DOOR, UNMEASURED,
)


@pytest.fixture(scope="module")
def report():
    return s24.census()


# ───────────────────────── ввоз словарей и сцен ─────────────────────────────

def test_vocabularies_and_scenes_are_imported_not_copied():
    """Словари и сцены ВВЕЗЕНЫ. Своя копия — вторая шкала об одном предмете."""
    assert s24._VOCAB_ERRORS == [], s24._VOCAB_ERRORS
    # ТОЖДЕСТВО объекта, а не равенство текста: равный по значению список мог бы
    # быть набран руками и разойтись молча при первом изменении §22.
    assert s24.SCENE_NOW is s22.SCENE_NOW
    assert s24._books is s22._books
    assert s24._econ_move is s22._econ_move
    assert s24._damper_move is s22._damper_move
    assert s24._control is s22._control
    assert s24._scene_capital is s22._scene_capital
    assert s24.SLOT_KINDS is s20.SLOT_KINDS
    # Капитал сцены — ВВЕЗЁННЫЙ, а не своё число: равенство значений этого НЕ
    # доказывало бы (две константы совпадают до первого расхождения).
    assert s24._capital() == s22._scene_capital()


def test_every_import_has_a_reader_in_the_report(report):
    """Ввоз без читателя есть ЛОЖНОЕ УСИЛЕНИЕ, и это проверяется.

    `SLOT_KINDS` §20 ПЕЧАТАЕТСЯ отчётом (род журнальной ячейки делегирован, а не
    перемерен), `UNMEASURED` §13 стои́т во всех трёх шкалах, сцены §22 и дверь
    §41 зовутся пробами. Шкала §23 здесь НЕ ввозится намеренно: читателя у неё
    в §24 нет.
    """
    assert report["journal_slot_scale_delegated_to_20"] == list(s20.SLOT_KINDS)
    assert not hasattr(s24, "DECLARATION_KINDS")
    for scale in (PRESENCE_KINDS, EXPECTATION_KINDS, RESULT_FORM_KINDS):
        assert UNMEASURED in scale


def test_broken_import_is_unmeasured_not_a_clean_pass(monkeypatch):
    """Порванный ввоз ⇒ код 2 с названной причиной, а не зелёный отчёт."""
    monkeypatch.setattr(s24, "_VOCAB_ERRORS", ["§22 сцены: ImportError: сцена"])
    doc = s24.census()
    assert s24.verdict_code(doc) == 2
    assert doc["vocab_errors"]
    assert doc["control"]["passed"] is False


def test_surfaces_extend_the_imported_list_and_name_the_extension():
    """§24 РАСШИРЯЕТ ввезённый перечень поверхностей, а не заводит свой."""
    assert tuple(SURFACES_24[:len(s22.SURFACES_22)]) == tuple(s22.SURFACES_22)
    assert SURFACES_24[len(s22.SURFACES_22):] == ("kill", "owner")


# ───────────────── ШЕСТЬ типов, и пересчёт СОШЁЛСЯ (замер) ──────────────────

def test_six_types_declared_and_the_order_count_matches():
    """§24 называет ШЕСТЬ типов; заказ G955 назвал столько же — это ЗАМЕР."""
    assert OWNER_TYPES_DECLARED == 6
    assert len(OWNER_DECISION_TYPES) == OWNER_TYPES_DECLARED
    assert len(set(OWNER_DECISION_TYPES)) == OWNER_TYPES_DECLARED
    assert ORDER_G955_NAMED == OWNER_TYPES_DECLARED


def test_order_undercount_is_reported_even_when_it_is_zero(report):
    """НОЛЬ расхождения ПЕЧАТАЕТСЯ: иначе «проверяли» неотличимо от «нет»."""
    assert report["types_declared"] == 6
    assert report["order_g955_named"] == 6
    assert report["order_undercount"] == 0
    assert "order_undercount" in report


def test_every_owner_type_has_a_declared_scene_and_a_ground():
    """Тип без сцены — «не измерено», а не ноль; основание сцены ОБЪЯВЛЕНО."""
    assert set(EXPECTATION_SCENES) == set(OWNER_DECISION_TYPES)
    assert set(SCENE_GROUNDS) == set(OWNER_DECISION_TYPES)
    for owner_type in OWNER_DECISION_TYPES:
        assert SCENE_GROUNDS[owner_type].strip()


# ───────────────────────── шкалы ОБЪЯВЛЕНЫ, не выведены ─────────────────────

@pytest.mark.parametrize("scale", [PRESENCE_KINDS, EXPECTATION_KINDS,
                                   RESULT_FORM_KINDS])
def test_every_scale_declares_the_third_outcome(scale):
    """Инв. #17: у каждой шкалы есть род «НЕ ИЗМЕРЕНО»."""
    assert UNMEASURED in scale


def test_report_uses_only_declared_kinds(report):
    """Вердикт вне объявленной шкалы — выведенный родом `else`, он запрещён."""
    for row in report["types"]:
        assert row["presence"]["kind"] in PRESENCE_KINDS
        assert row["expectation"]["kind"] in EXPECTATION_KINDS
    for door, form in report["result_forms"].items():
        assert form["kind"] in RESULT_FORM_KINDS, door


# ─────────────────── главный замер: словарь владельца ───────────────────────

def test_owner_dictionary_is_implemented_on_no_door(report):
    """ОСЬ A: ни один из шести токенов владельца не объявлен и не выдан."""
    assert report["control"]["passed"] is True, report["control"]["reason"]
    assert report["tally"]["presence"]["absent_from_every_door"] == 6
    assert report["tally"]["presence"][UNMEASURED] == 0
    assert s24.verdict_code(report) == 1


def test_axis_b_prints_the_emitted_tokens_and_never_translates_them(report):
    """ОСЬ B: выданное печатается ДОСЛОВНО, перевода в слово владельца нет."""
    assert report["tally"]["expectation"]["expected_type_emitted"] == 0
    assert report["tally"]["expectation"]["foreign_token_emitted"] == 6
    for row in report["types"]:
        emitted = row["expectation"]["emitted"]
        assert emitted, row["type"]
        # Ни один выданный токен НЕ является словом владельца — иначе ось A
        # обязана была бы сказать `emitted_only`, и две оси разошлись бы.
        assert not (set(map(str, emitted.values())) & set(OWNER_DECISION_TYPES))


def test_a_door_that_did_emit_an_owner_token_is_reported_as_present(monkeypatch):
    """Контроль НАОБОРОТ: выдай дверь токен владельца — ось A это ВИДИТ.

    Без этой пробы «нет ни у одной двери» было бы верно и в мире, где ось A
    сломана и не умеет сказать ничего другого.
    """
    def _fake_kill(dd):
        return {"token": "EMERGENCY_EXIT", "text": ["сцена контроля"]}
    monkeypatch.setattr(s24, "_emit_kill", _fake_kill)
    doc = s24.census()
    row = next(r for r in doc["types"] if r["type"] == "EMERGENCY_EXIT")
    assert row["presence"]["kind"] == "emitted_only"
    assert "kill" in row["presence"]["doors"]
    assert row["expectation"]["kind"] == "expected_type_emitted"


def test_a_declared_but_never_emitted_owner_token_is_still_found(monkeypatch):
    """Контроль НАОБОРОТ: объявленный, но не выданный токен ⇒ `in_declared_domain`.

    Это и есть причина, по которой правило принадлежности домену складывает
    выданные токены со словарём ВЛАДЕЛЬЦА: иначе род был бы недостижим по
    построению — ровно находка §19 (`named_but_unreachable`, ADR-962).
    """
    from spa_core.governance import churn_damper
    monkeypatch.setattr(churn_damper, "KEEP_FOR_THE_CONTROL", "KEEP",
                        raising=False)
    doc = s24.census()
    row = next(r for r in doc["types"] if r["type"] == "KEEP")
    assert row["presence"]["kind"] == "in_declared_domain"
    assert "damper" in row["presence"]["doors"]


def test_declared_domain_is_not_any_string_constant_of_the_module(report):
    """Домен — по ЗНАЧЕНИЮ константы, а не по её имени.

    Положительный контроль ошибки замера: у двери допуска есть строковые
    константы с именами файлов, и ни одна из них вердиктом не является.
    """
    from spa_core.paper_trading import risk_gate
    filenames = {str(getattr(risk_gate, n)) for n in dir(risk_gate)
                 if n.isupper() and isinstance(getattr(risk_gate, n, None), str)
                 and str(getattr(risk_gate, n)).endswith(".json")}
    assert filenames, "у двери допуска нет строковых констант — контроль пуст"
    assert not (set(report["declared_domains"]["gate"]) & filenames)


def test_economics_door_declares_no_domain_at_all(report):
    """Замер, а не мнение: дверь цены не объявляет СВОЕГО домена ни одной константой."""
    assert report["declared_domains"]["economics"] == []
    assert set(report["emitted_on_scenes"]["economics"]) == {"ACT", "HOLD"}
    assert report["result_forms"]["economics"]["kind"] == "typed_but_domain_undeclared"


# ─────────────────────── ось C: форма результата ────────────────────────────

def test_result_form_is_measured_over_all_scenes_not_the_first(report):
    """Форма судится ПО ВСЕМ сценам: «иногда только текст» — не «только тип».

    Положительный контроль ошибки замера: в сцене ``KEEP`` у второй двери
    политики нарушений нет, а в сценах просадки есть. Ответ о форме обязан
    быть один и тот же независимо от порядка сцен в карте.
    """
    assert report["result_forms"]["book"]["kind"] == "typed_plus_text"
    reordered = dict(reversed(list(EXPECTATION_SCENES.items())))
    assert set(reordered) == set(EXPECTATION_SCENES)


def test_result_form_order_independence_is_measured(monkeypatch):
    """Тот же вердикт о форме при ОБРАТНОМ порядке сцен — замер, не рассуждение."""
    base = s24.census()["result_forms"]
    monkeypatch.setattr(s24, "EXPECTATION_SCENES",
                        dict(reversed(list(EXPECTATION_SCENES.items()))))
    flipped = s24.census()["result_forms"]
    assert {d: v["kind"] for d, v in base.items()} == \
           {d: v["kind"] for d, v in flipped.items()}


def test_gate_result_is_a_boolean_and_that_is_a_finding(report):
    """Дверь допуска отвечает ЛОГИЧЕСКИМ, и §24 этим не исполняется."""
    assert report["result_forms"]["gate"]["kind"] == "boolean_not_a_type"
    assert report["tally"]["result_form"]["boolean_not_a_type"] == 1


def test_a_door_without_a_sample_is_unmeasured_not_zero(monkeypatch):
    """Дверь, которой не коснулась ни одна сцена ⇒ `unmeasured`, а не «чисто»."""
    monkeypatch.setattr(s24, "EXPECTATION_SCENES",
                        {"KEEP": lambda: {"kill": s24._emit_kill(1.0)}})
    doc = s24.census()
    assert doc["result_forms"]["economics"]["kind"] == UNMEASURED
    assert s24.verdict_code(doc) == 2


# ────────────────── сцены: достижимость и изоляция ──────────────────────────

def test_control_requires_a_token_to_change_between_scenes(monkeypatch):
    """Контроль ловит сцену, отвечающую одно и то же на любой вход.

    Без этого условия «собранный домен» был бы артефактом сломанной сцены:
    дверь, не реагирующая ни на что, выглядит точно так же, как дверь,
    у которой домен из одного токена.
    """
    monkeypatch.setattr(s24, "_emit_kill",
                        lambda dd: {"token": "NONE", "text": []})
    monkeypatch.setattr(s24, "_scene_keep",
                        lambda: {"economics": {"token": "HOLD", "text": []}})
    monkeypatch.setattr(s24, "_scene_rebalance",
                        lambda: {"economics": {"token": "HOLD", "text": []}})
    ok, why, _ = s24._control_24()
    assert ok is False
    assert why


def test_owner_scale_scene_is_actually_refused_by_the_doors(report):
    """Сцена REQUIRE_OWNER_APPROVAL ДОСТИЖИМА: двери действительно отказывают.

    Иначе «токена нет» прочиталось бы на пустом месте — на сцене, которую
    двери пропускают, им и не нужно было бы говорить «решает владелец».
    """
    row = next(r for r in report["types"]
               if r["type"] == "REQUIRE_OWNER_APPROVAL")
    emitted = row["expectation"]["emitted"]
    assert emitted["economics"] == "HOLD"
    assert emitted["damper"] == "BLOCK"
    assert emitted["gate"].startswith("approved=False")


def test_risk_ladder_scenes_land_in_the_owner_declared_bands(report):
    """Сцены просадки попадают в полосы лестницы владельца, а не рядом с ними."""
    from spa_core.governance.kill_switch import (
        DRAWDOWN_THRESHOLD_PCT, SOFT_DERISK_THRESHOLD_PCT)
    assert s24._DD_CALM_PCT < SOFT_DERISK_THRESHOLD_PCT
    assert SOFT_DERISK_THRESHOLD_PCT <= s24._DD_SOFT_PCT < DRAWDOWN_THRESHOLD_PCT
    assert s24._DD_HARD_PCT >= DRAWDOWN_THRESHOLD_PCT
    soft = next(r for r in report["types"] if r["type"] == "REDUCE_RISK")
    hard = next(r for r in report["types"] if r["type"] == "EMERGENCY_EXIT")
    assert soft["expectation"]["emitted"]["kill"] == "SOFT_DERISK"
    assert hard["expectation"]["emitted"]["kill"] == "HARD_KILL"
    # И они РАЗНЫЕ — иначе сцена не различала бы полосы.
    assert soft["expectation"]["emitted"] != hard["expectation"]["emitted"]


def test_healthy_book_of_the_policy_door_is_actually_approved():
    """Книга сцены ЗДОРОВА у второй двери политики.

    Замер, а не вкус: при двух ногах по 50 % вердикт решала бы концентрация,
    при трёх на одной сети — потолок сети, и «здоровая сцена» не была бы
    здоровой ни в одном прогоне.
    """
    with s24._quiet():
        verdict = s24._book_verdict(s24._DD_CALM_PCT)
    assert verdict.approved is True, verdict.violations
    assert verdict.required_response == "NONE"
    assert verdict.drawdown_tier == "NONE"


def test_defer_scene_withholds_the_rate_rather_than_the_book(report):
    """Сцена DEFER строится через НЕПРЕДЪЯВЛЕННУЮ ставку, а не через равные книги.

    Иначе она совпала бы со сценой KEEP, и «DEFER и KEEP выдают одно и то же»
    было бы свойством сцены, а не дерева.
    """
    keep = next(r for r in report["types"] if r["type"] == "KEEP")
    defer = next(r for r in report["types"] if r["type"] == "DEFER")
    assert keep["expectation"]["emitted"] != defer["expectation"]["emitted"]
    assert set(s24._scene_defer()) == {"economics", "damper", "kill"}


# ──────────────────── подавление лога: пустое действие ──────────────────────

def test_doors_log_is_silenced_and_restored():
    """Глушитель ДЕЙСТВУЕТ и ВОЗВРАЩАЕТ состояние обратно.

    Положительный контроль ошибки замера: ``redirect_stdout`` на двери,
    пишущей через ``logging``, не делает ничего — и выглядит исполненным.
    """
    before = logging.root.manager.disable
    with s24._quiet():
        assert logging.getLogger("spa_core.risk.policy").isEnabledFor(
            logging.ERROR) is False
    assert logging.root.manager.disable == before
    assert logging.getLogger("spa_core.risk.policy").isEnabledFor(
        logging.ERROR) is True


def test_quiet_restores_even_when_the_scene_raises():
    """Исключение внутри сцены не оставляет журналирование выключенным."""
    before = logging.root.manager.disable
    with pytest.raises(RuntimeError):
        with s24._quiet():
            raise RuntimeError("сцена упала")
    assert logging.root.manager.disable == before


# ───────────── утверждения, которые ПЕЧАТАЮТСЯ, а не умалчиваются ───────────

def test_surfaces_without_a_typed_door_are_named_with_reasons(report):
    """Поверхность без двери — УТВЕРЖДЕНИЕ, и оно в отчёте с причиной."""
    assert set(SURFACES_WITHOUT_A_TYPED_DOOR) == {"allocator", "journal", "owner"}
    for surface, why in SURFACES_WITHOUT_A_TYPED_DOOR.items():
        assert why.strip(), surface
        assert surface not in DOORS_24
    assert report["surfaces_without_a_typed_door"] == \
        dict(SURFACES_WITHOUT_A_TYPED_DOOR)
    # Поверхности §24 = пробуемые двери ∪ поверхности без двери, без остатка:
    # поверхность, молча выпавшая из обоих списков, читалась бы как «не нашли».
    assert set(SURFACES_24) == set(DOORS_24) | set(SURFACES_WITHOUT_A_TYPED_DOOR)


def test_near_misses_are_named_and_are_not_counted_as_doors(report):
    """Близкое совпадение названо и дверью НЕ считается."""
    assert len(NEAR_MISS_NOT_A_DOOR) == 2
    for place, why in NEAR_MISS_NOT_A_DOOR.items():
        assert why.strip(), place
    assert report["near_miss_not_a_door"] == dict(NEAR_MISS_NOT_A_DOOR)
    # Журналист держит слово владельца — и это НЕ делает §24 исполненным.
    from spa_core.agents import decision_logger
    assert hasattr(decision_logger, "DecisionLogger")
    assert report["tally"]["presence"]["absent_from_every_door"] == 6


def test_what_is_not_claimed_is_written_down(report):
    """Чего прибор НЕ утверждает — в отчёте, а не в чьей-то голове."""
    assert len(report["not_claimed"]) >= 4
    assert report["advisory"].strip()


# ─────────────────────────── вердикт прибора ────────────────────────────────

def test_verdict_is_one_for_a_named_finding(report):
    assert s24.verdict_code(report) == 1


def test_verdict_is_two_when_a_domain_is_unreadable(monkeypatch):
    """Непрочитанный домен ⇒ НЕ ИЗМЕРЕНО, а не «домена нет»."""
    monkeypatch.setitem(s24._DOMAIN_MODULES, "kill",
                        "spa_core.governance.module_that_does_not_exist")
    doc = s24.census()
    assert doc["declared_domains_unreadable"]
    assert s24.verdict_code(doc) == 2


def test_verdict_is_zero_only_when_every_axis_is_clean():
    """Код 0 достижим — иначе «исполняется» было бы недостижимым по построению."""
    clean = {
        "vocab_errors": [],
        "control": {"passed": True, "reason": ""},
        "declared_domains_unreadable": [],
        "tally": {
            "presence": {"in_declared_domain": 6, UNMEASURED: 0,
                         "absent_from_every_door": 0},
            "expectation": {"expected_type_emitted": 6, UNMEASURED: 0,
                            "foreign_token_emitted": 0, "no_typed_answer": 0},
            "result_form": {"typed_plus_text": 5, UNMEASURED: 0,
                            "text_only": 0, "boolean_not_a_type": 0,
                            "typed_but_domain_undeclared": 0},
        },
    }
    assert s24.verdict_code(clean) == 0


def test_render_prints_every_type_and_every_door(report):
    """Отчёт НАЗЫВАЕТ каждый тип и каждую дверь — не подстрокой, а наличием."""
    text = s24.render(report)
    for owner_type in OWNER_DECISION_TYPES:
        assert text.count(owner_type) >= 1, owner_type
    for door in DOORS_24:
        assert door in text, door


def test_module_touches_no_live_data():
    """Прибор ADVISORY: живой `data/` не читается и не пишется этим модулем."""
    src = (s24.__file__ or "")
    assert src.endswith("decision_type_census.py")
    body = open(src, encoding="utf-8").read()
    # Предмет — ОБРАЩЕНИЕ к живому каталогу, а не слово в прозе: проверяется
    # форма вызова, которой у читающего живой трек кода не бывает иной.
    for forbidden in ('Path("data")', "Path('data')", 'data_dir=',
                      "atomic_save", "open(_DATA", "equity_curve_daily"):
        assert forbidden not in body, forbidden


# ───────── дыры батареи, найденные мутационным прогоном (ADR-967) ───────────
#
# Три мутации выжили первый прогон, и ни одна из них не была ЭКВИВАЛЕНТНОЙ:
# каждая меняет поведение прибора, но на СЕГОДНЯШНЕМ дереве её последствие
# перекрывалось соседней ветвью того же вердикта. То есть батарея отвечала
# «вердикт тот же» вместо «эта ветвь работает» — ровно подмена вопроса.
# Лечение — изолировать вклад каждой ветви синтетическим отчётом.

def _synthetic_report(**over):
    """Чистый отчёт, в котором ВСЕ оси зелены. Отдельные поля портятся входом.

    Синтетика нужна именно здесь: на живом дереве ось A и ось B грязны ОБЕ, и
    вклад каждой в вердикт по отдельности неизмерим по построению.
    """
    doc = {
        "vocab_errors": [],
        "control": {"passed": True, "reason": ""},
        "declared_domains_unreadable": [],
        "tally": {
            "presence": {"in_declared_domain": 6, UNMEASURED: 0,
                         "absent_from_every_door": 0},
            "expectation": {"expected_type_emitted": 6, UNMEASURED: 0,
                            "foreign_token_emitted": 0, "no_typed_answer": 0},
            "result_form": {"typed_plus_text": 5, UNMEASURED: 0,
                            "text_only": 0, "boolean_not_a_type": 0,
                            "typed_but_domain_undeclared": 0},
        },
    }
    doc.update(over)
    return doc


def test_axis_a_alone_turns_the_verdict_into_a_finding():
    """Мутация M6: ветвь «ось A пуста» обязана ОДНА давать код 1."""
    doc = _synthetic_report()
    assert s24.verdict_code(doc) == 0
    doc["tally"]["presence"] = {"in_declared_domain": 0, UNMEASURED: 0,
                                "absent_from_every_door": 6}
    assert s24.verdict_code(doc) == 1


def test_axis_b_alone_turns_the_verdict_into_a_finding():
    """Соседняя ветвь того же вердикта — тоже ОДНА, иначе M6 перекрывается ею."""
    doc = _synthetic_report()
    doc["tally"]["expectation"] = {"expected_type_emitted": 0, UNMEASURED: 0,
                                   "foreign_token_emitted": 6,
                                   "no_typed_answer": 0}
    assert s24.verdict_code(doc) == 1


def test_axis_c_alone_turns_the_verdict_into_a_finding():
    doc = _synthetic_report()
    doc["tally"]["result_form"] = {"typed_plus_text": 4, UNMEASURED: 0,
                                   "text_only": 0, "boolean_not_a_type": 1,
                                   "typed_but_domain_undeclared": 0}
    assert s24.verdict_code(doc) == 1


def test_vocab_errors_alone_make_the_verdict_unmeasured():
    """Мутация M7: ветвь «словари не ввезены» обязана ОДНА давать код 2.

    На живом дереве порванный ввоз роняет и контроль, и обе оси, поэтому код 2
    выходил из соседней ветви, а эта могла быть вырезана незаметно.
    """
    doc = _synthetic_report(vocab_errors=["§22 сцены: ImportError"])
    assert s24.verdict_code(doc) == 2


def test_failed_control_alone_makes_the_verdict_unmeasured():
    doc = _synthetic_report(control={"passed": False, "reason": "сцена мертва"})
    assert s24.verdict_code(doc) == 2


def test_defer_scene_actually_withholds_the_rate(report):
    """Мутация M8: сцена DEFER обязана ОТЛИЧАТЬСЯ от той же сцены со ставкой.

    Сравнение с KEEP этого не доказывало: наборы дверей у них разные, и
    «отличается» выходило из состава сцены, а не из непредъявленной ставки.
    Здесь возмущается РОВНО предъявленность ставки.
    """
    books = s24._books(s24._capital())
    withheld = s24._emit_economics(current=books["A"], target=books["B"],
                                   evidenced=set())
    presented = s24._emit_economics(current=books["A"], target=books["B"])
    assert withheld["token"] != presented["token"], (withheld, presented)
    # И сцена прибора берёт именно непредъявленный вариант.
    with s24._quiet():
        scene = s24._scene_defer()
    assert scene["economics"]["token"] == withheld["token"]
