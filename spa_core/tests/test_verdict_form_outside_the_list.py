"""Заказ G102 п. 2 — население вердиктов ВНЕ закрытого перечня форм
(ADR-582, цикл #787).

Сосед `verdict_over_named_keys` (ADR-522) объявил односторонность дословно:
«вердикт, собранный словарём переходов или цепочкой `elif` длиннее двух
ветвей, в население НЕ попадает вовсе». Обещание это — промах В СТОРОНУ
ПУСТОТЫ, и проверить его отдельное утверждение: у цепочки `elif` есть ХВОСТ,
а хвост сам есть развилка из двух ветвей, то есть ровно то, что закрытый
перечень вердиктом и признаёт.

Каждый тест ниже — положительный контроль ОДНОЙ клаузы объявленного правила:
снимешь клаузу — тест краснеет, и краснеет С НАЗВАННЫМ ЗВЕНОМ.

Тесты с префиксом ``test_live_`` ходят по ЖИВОМУ дереву (556 файлов) и
существуют ради мутационного стенда отдельным именем: мутант способен сделать
обход патологически медленным, поэтому стенд гоняет батарею без них
(`-k "not test_live_"`). В CI они идут всегда — логика региона доказывается
синтетическими сценами, а живые тесты сторожат СВОДКИ и проводку.

Литеральных дат и литеральных номеров процессов в файле нет вовсе: предмет
разбирается статически, часов и ОС он не спрашивает ни одной дверью.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from spa_core.monitoring import rule_second_copy_census as C

_ROOT = Path(__file__).resolve().parents[2]


# ─────────────────────── сцены ───────────────────────

#: Цепочка из ПЯТИ ветвей, несущих класс, с хвостом формы «пара присваиваний»:
#: дословная форма `marginal_apy_at_size.run` и `rebalance_cost_evidence.run`.
_FIVE_BRANCH_CHAIN = '''
OK = "ok"
WARN = "warn"
BAD = "bad"
MUTE = "mute"
HARSH = "harsh"
SOFT = "soft"
CLEAN = "clean"


def classify(row):
    if row.get("harsh"):
        return HARSH
    if row.get("soft"):
        return SOFT
    return CLEAN


def judge(rows):
    counts = {}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    if counts.get(HARSH):
        status = BAD
    elif counts.get(SOFT):
        status = WARN
    elif counts.get(CLEAN):
        status = MUTE
    elif counts.get(MUTE):
        status = OK
    else:
        status = OK
    return status
'''

#: Та же цепочка, но хвост НЕ развилка: `orelse` у последнего звена пуст,
#: и закрытый перечень его не признаёт ничем. Рядом НАРОЧНО стоит обычная
#: развилка из двух ветвей (`judge_plain`): без неё файл не дал бы соседу ни
#: одной строки, доказательством входа стало бы «вклада нет вовсе», и
#: тождество узлов осталось бы непроверенным.
_CHAIN_WITH_A_BARE_TAIL = '''
OK = "ok"
WARN = "warn"
BAD = "bad"
HARSH = "harsh"
SOFT = "soft"
CLEAN = "clean"


def classify(row):
    if row.get("harsh"):
        return HARSH
    if row.get("soft"):
        return SOFT
    return CLEAN


def judge(rows):
    counts = {}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    status = OK
    if counts.get(HARSH):
        status = BAD
    elif counts.get(SOFT):
        status = WARN
    elif counts.get(CLEAN):
        status = BAD
    return status


def judge_plain(rows):
    counts = {}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    if counts.get(HARSH):
        return BAD
    else:
        return OK
'''

#: Развилка РОВНО из двух ветвей — собственная форма закрытого перечня, и в
#: это население она не входит по построению.
_TWO_BRANCH_VERDICT = '''
OK = "ok"
BAD = "bad"
HARSH = "harsh"
CLEAN = "clean"


def classify(row):
    if row.get("harsh"):
        return HARSH
    return CLEAN


def judge(rows):
    counts = {}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    if counts.get(HARSH):
        status = BAD
    else:
        status = OK
    return status
'''

#: Вложенный `if` внутри `else:` — звеном цепочки НЕ является. Выбор объявлен
#: в `blind` шага: у такой развилки свой `else`, и слить две развилки в одну
#: значило бы сосчитать ветви, которых цепочка не имеет.
_NESTED_IF_INSIDE_ELSE = '''
OK = "ok"
WARN = "warn"
BAD = "bad"
HARSH = "harsh"
SOFT = "soft"
CLEAN = "clean"


def classify(row):
    if row.get("harsh"):
        return HARSH
    if row.get("soft"):
        return SOFT
    return CLEAN


def judge(rows):
    counts = {}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    if counts.get(HARSH):
        status = BAD
    else:
        if counts.get(SOFT):
            status = WARN
        else:
            status = OK
    return status
'''

#: Цепочка, ни одно условие которой не читает счётчик ИМЕНОВАННЫМ ключом.
_CHAIN_WITHOUT_A_COUNTER = '''
OK = "ok"
WARN = "warn"
BAD = "bad"
HARSH = "harsh"
CLEAN = "clean"


def classify(row):
    if row.get("harsh"):
        return HARSH
    return CLEAN


def judge(rows):
    counts = {}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    if rows:
        status = BAD
    elif len(rows) > 1:
        status = WARN
    elif len(rows) > 2:
        status = OK
    else:
        status = OK
    return (status, counts)
'''

#: Цепочка, читающая счётчик НЕИМЕНОВАННЫМ ключом: отбор поверхности
#: дословно соседский, и ключ-переменная в него не входит.
_CHAIN_WITH_AN_UNNAMED_KEY = '''
OK = "ok"
WARN = "warn"
BAD = "bad"
HARSH = "harsh"
CLEAN = "clean"


def classify(row):
    if row.get("harsh"):
        return HARSH
    return CLEAN


def judge(rows, probe):
    counts = {}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    if counts.get(probe):
        status = BAD
    elif counts.get(probe, 0) > 1:
        status = WARN
    elif rows:
        status = OK
    else:
        status = OK
    return status
'''

#: Словарь переходов, прочитанный ВЫЧИСЛЕННЫМ ключом счётчика.
_TRANSITION_TABLE = '''
OK = "ok"
WARN = "warn"
BAD = "bad"
HARSH = "harsh"
SOFT = "soft"
CLEAN = "clean"
_TABLE = {HARSH: BAD, SOFT: WARN, CLEAN: OK}


def classify(row):
    if row.get("harsh"):
        return HARSH
    if row.get("soft"):
        return SOFT
    return CLEAN


def judge(rows):
    counts = {}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    return _TABLE[max(counts, key=counts.get)]
'''

#: Тот же словарь, но его значения классами НЕ являются — перехода он не
#: объявляет, и находкой быть не может.
_TABLE_OF_NUMBERS = '''
OK = "ok"
HARSH = "harsh"
SOFT = "soft"
CLEAN = "clean"
_TABLE = {HARSH: 1, SOFT: 2, CLEAN: 3}


def classify(row):
    if row.get("harsh"):
        return HARSH
    if row.get("soft"):
        return SOFT
    return CLEAN


def judge(rows):
    counts = {}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    return _TABLE[max(counts, key=counts.get)]
'''

#: `match` по счётчику — две ветви, несущие класс.
_MATCH_OVER_A_COUNTER = '''
OK = "ok"
WARN = "warn"
BAD = "bad"
HARSH = "harsh"
CLEAN = "clean"


def classify(row):
    if row.get("harsh"):
        return HARSH
    return CLEAN


def judge(rows):
    counts = {}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    status = OK
    match counts.get(HARSH):
        case 0:
            status = OK
        case 1:
            status = WARN
        case _:
            status = BAD
    return status
'''

#: `match` с ОДНОЙ ветвью, несущей класс: градуировки он не объявляет.
_MATCH_WITH_ONE_CASE = '''
OK = "ok"
BAD = "bad"
HARSH = "harsh"
CLEAN = "clean"


def classify(row):
    if row.get("harsh"):
        return HARSH
    return CLEAN


def judge(rows):
    counts = {}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    status = OK
    match counts.get(HARSH):
        case _:
            status = BAD
    return status
'''

#: Счётчик пишут в ДРУГОЙ области того же файла — исключение считается
#: ОТДЕЛЬНЫМ числом, а не теряется в населении.
_COUNTER_WRITTEN_ELSEWHERE = '''
OK = "ok"
WARN = "warn"
BAD = "bad"
HARSH = "harsh"
SOFT = "soft"
CLEAN = "clean"


def classify(row):
    if row.get("harsh"):
        return HARSH
    if row.get("soft"):
        return SOFT
    return CLEAN


def judge(counts):
    if counts.get(HARSH):
        status = BAD
    elif counts.get(SOFT):
        status = WARN
    elif counts.get(CLEAN):
        status = OK
    else:
        status = OK
    return status


def tally(rows):
    counts = {}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    return counts
'''


def _rows(source: str, label: str = "scene"):
    """Строки сцены тем же правилом и с тем же вопросом о входе, что у шага."""
    return C._outside_rows_of_scene(label, source)


# ─────────────────────── контроль ───────────────────────

def test_the_control_passes_and_shows_every_declared_form():
    """Правило доказано на своей сцене ОБЕИМИ половинами и ПОИМЁННО."""
    control = C._outside_control()
    assert control["passed"], control.get("reason")
    assert sorted(control["forms"]) == sorted(C._FORMS_OUTSIDE)
    assert sorted(control["proofs"]) == sorted(C._ENTRY_PROOFS)
    assert sorted(control["entries"]) == sorted(
        name for name in C._ENTRIES if name != C.ENTRY_UNMEASURED)
    assert control["negative_rows"] == 0
    assert control["negative_counter_elsewhere"] == 1


def test_a_control_scene_that_lost_a_form_refuses_the_whole_step(monkeypatch):
    """Форма, которую сцена не предъявила, обязана ОТМЕНИТЬ шаг.

    Иначе правило, разучившееся видеть словарь переходов, отвечало бы «таких
    форм в дереве нет» — ненайденное за ноль.
    """
    monkeypatch.setattr(C, "_OUT_SCENES",
                        (("positive", _FIVE_BRANCH_CHAIN),), raising=True)
    control = C._outside_control()
    assert not control["passed"]
    assert "не предъявил" in control["reason"] or "ожидалась" in control["reason"]


def test_the_discriminability_check_refuses_a_scene_whose_counts_tie():
    """У проверки различимости есть СВОЙ контроль — иначе она украшение.

    Урок ADR-581 (цикл #786): отчёт читает счёты ПО ИМЕНИ, и при равных
    счётах подмена имени ключа невидима ничем. Внутри `_outside_control`
    эта проверка стои́т ПОСЛЕ поимённых якорей и на живых сценах не
    исполняется ни разу, поэтому спрашивается здесь прямо.
    """
    tying = [{"form": C.FORM_OUT_ELIF_CHAIN, "entry": C.ENTRY_TRUNCATED,
              "entry_proof": C.PROOF_BY_NODE_IDENTITY},
             {"form": C.FORM_OUT_MATCH, "entry": C.ENTRY_ABSENT,
              "entry_proof": C.PROOF_NO_SUCH_FORM}]
    reason = C._scene_discriminates(tying)
    assert reason is not None and "by_form" in reason and "совпадают" in reason


def test_the_discriminability_check_accepts_a_scene_that_tells_names_apart():
    """Обратная сторона: различимая сцена отказа НЕ получает.

    Без этой половины проверка, отказывающая всегда, была бы «зелёной» в
    первом тесте и при этом бесполезной.
    """
    distinct = [{"form": C.FORM_OUT_ELIF_CHAIN, "entry": C.ENTRY_TRUNCATED,
                 "entry_proof": C.PROOF_BY_NODE_IDENTITY},
                {"form": C.FORM_OUT_ELIF_CHAIN, "entry": C.ENTRY_ABSENT,
                 "entry_proof": C.PROOF_BY_NODE_IDENTITY},
                {"form": C.FORM_OUT_ELIF_CHAIN, "entry": C.ENTRY_ABSENT,
                 "entry_proof": C.PROOF_BY_NODE_IDENTITY},
                {"form": C.FORM_OUT_MATCH, "entry": C.ENTRY_ABSENT,
                 "entry_proof": C.PROOF_NO_SUCH_FORM}]
    assert C._scene_discriminates(distinct) is None


def test_the_control_consults_the_discriminability_check(monkeypatch):
    """Проверка ДОХОДИТ до контроля, а не лежит рядом с ним.

    «Функция есть» и «контроль её зовёт» — два разных утверждения, и первое
    без второго есть половина проводки (урок #453).
    """
    monkeypatch.setattr(C, "_scene_discriminates",
                        lambda rows: "подстановка различимости")
    control = C._outside_control()
    assert not control["passed"]
    assert control["reason"] == "подстановка различимости"


# ─────────────────────── форма 1: цепочка `elif` ───────────────────────

def test_a_five_branch_chain_is_one_row_not_three():
    """Население считает ЦЕПОЧКИ, а не их звенья.

    Без вопроса о голове одна цепочка из пяти ветвей вошла бы трижды, и
    число отвечало бы на вопрос «сколько у цепочек звеньев». Замер на живом
    дереве: 13 звеньев против 7 цепочек.
    """
    rows, elsewhere = _rows(_FIVE_BRANCH_CHAIN)
    chains = [r for r in rows if r["form"] == C.FORM_OUT_ELIF_CHAIN]
    assert len(chains) == 1, [(r["line"], r["owner"]) for r in chains]
    assert chains[0]["branches_bearing_a_class"] == 5
    assert chains[0]["links"] == 4
    assert elsewhere == 0


def test_the_tail_of_a_chain_enters_the_closed_population_as_a_whole_verdict():
    """ОТВЕТ ЗАКАЗУ: «не попадает вовсе» неверно — хвост попадает УСЕЧЁННЫМ.

    Хвост `elif counts.get(MUTE): status = OK else: status = OK` есть развилка
    из двух ветвей, то есть ровно то, что закрытый перечень вердиктом
    признаёт. Сосед берёт его как ЦЕЛЫЙ вердикт и судит о полноте перечня
    ключей по двум ветвям из пяти.
    """
    rows, _ = _rows(_FIVE_BRANCH_CHAIN)
    chain = next(r for r in rows if r["form"] == C.FORM_OUT_ELIF_CHAIN)
    assert chain["entry"] == C.ENTRY_TRUNCATED
    assert chain["entry_proof"] == C.PROOF_BY_NODE_IDENTITY
    assert chain["branches_the_closed_list_sees"] == C.BRANCHES_THE_CLOSED_LIST_SEES
    assert chain["branches_bearing_a_class"] > chain["branches_the_closed_list_sees"]
    # Хвост действительно принят СОСЕДОМ — спрошено его же функцией.
    tree = ast.parse(_FIVE_BRANCH_CHAIN)
    accepted, _e = C._verdict_sites("<neighbour>", tree)
    assert [row["line"] for row in accepted] == [chain["tail_line"]]


def test_a_chain_whose_tail_is_not_a_fork_does_not_enter_the_population():
    """Хвост без `else` закрытый перечень не признаёт — и это ВТОРОЙ исход.

    Он отличается от первого доказательством, а не оттенком: тождество узлов
    спрошено и дало «нет», а не «спрашивать было не о чем».
    """
    rows, _ = _rows(_CHAIN_WITH_A_BARE_TAIL)
    chain = next(r for r in rows if r["form"] == C.FORM_OUT_ELIF_CHAIN)
    assert chain["entry"] == C.ENTRY_ABSENT
    assert chain["entry_proof"] == C.PROOF_BY_NODE_IDENTITY
    assert chain["gap"] is None


def test_a_two_branch_verdict_is_not_in_this_population():
    """Своя форма закрытого перечня в это население не входит.

    Иначе шаг отвечал бы на вопрос «сколько в дереве вердиктов», а заказ
    спросил «сколько их ВНЕ перечня».
    """
    rows, elsewhere = _rows(_TWO_BRANCH_VERDICT)
    assert rows == []
    assert elsewhere == 0
    # И при этом сосед эту развилку ПРИНИМАЕТ — иначе сцена доказывала бы
    # лишь то, что развилки в ней нет вовсе.
    accepted, _e = C._verdict_sites("<neighbour>", ast.parse(_TWO_BRANCH_VERDICT))
    assert len(accepted) == 1


def test_a_nested_if_inside_else_is_not_a_link_of_the_chain():
    """Вложенный `if` внутри `else:` звеном не признаётся — ВЫБОР объявлен.

    У такой развилки свой `else`, и считать её звеном значило бы сосчитать
    ветви, которых цепочка не имеет. Односторонность названа в `blind` шага.
    """
    rows, _ = _rows(_NESTED_IF_INSIDE_ELSE)
    assert [r["form"] for r in rows] == []


def test_elif_and_a_nested_if_have_the_SAME_tree_and_differ_only_by_column():
    """Предмет различия назван ПРЯМО: разбор у них ТОЖДЕСТВЕН.

    Первая редакция шага объявляла «звеном признаётся только `elif`» и
    проверяла форму `orelse` — то есть называла различием то, чего в разборе
    нет вовсе, и собственная сцена её уличила. Тест закрепляет ОБЕ стороны:
    формы `orelse` совпадают, а колонка — нет.
    """
    chain = ast.parse("def f(x):\n"
                      "    if x:\n"
                      "        y = 1\n"
                      "    elif x:\n"
                      "        y = 2\n").body[0].body[0]
    nested = ast.parse("def f(x):\n"
                       "    if x:\n"
                       "        y = 1\n"
                       "    else:\n"
                       "        if x:\n"
                       "            y = 2\n").body[0].body[0]
    for outer in (chain, nested):
        assert len(outer.orelse) == 1 and isinstance(outer.orelse[0], ast.If)
    assert C._is_elif_link(chain, chain.orelse[0])
    assert not C._is_elif_link(nested, nested.orelse[0])
    assert len(C._elif_chain_links(chain)) == 2
    assert len(C._elif_chain_links(nested)) == 1


def test_a_chain_that_reads_no_counter_is_refused():
    """Поверхность отбирается дословно соседскими требованиями."""
    rows, elsewhere = _rows(_CHAIN_WITHOUT_A_COUNTER)
    assert rows == []
    assert elsewhere == 0


def test_a_chain_whose_key_is_not_a_declared_class_is_refused():
    """Ключ-переменная ИМЕНОВАННЫМ не является — отбор тот же, что у соседа.

    Взять такую цепочку значило бы сравнивать два разных населения: сосед
    этот вердикт в своё население не берёт тоже.
    """
    rows, elsewhere = _rows(_CHAIN_WITH_AN_UNNAMED_KEY)
    assert rows == []
    assert elsewhere == 0


def test_a_counter_written_in_another_scope_is_counted_separately():
    """Исключение по области — ОТДЕЛЬНОЕ число, а не тихая потеря строки.

    Замер живого дерева: ровно одна цепочка из семи исключена так, и без
    этого числа население читалось бы как шесть из шести.
    """
    rows, elsewhere = _rows(_COUNTER_WRITTEN_ELSEWHERE)
    assert rows == []
    assert elsewhere == 1


# ─────────────────────── форма 2: словарь переходов ───────────────────────

def test_a_transition_table_read_by_a_computed_counter_key_is_found():
    """Ключ словаря ищется УПОМИНАНИЕМ счётчика, а не формой подписки.

    Односторонность объявлена В СТОРОНУ НАХОДКИ: `max(counts, key=counts.get)`
    формы подписки не имеет, и требовать её значило бы пропустить ровно те
    переходы, ради которых заказ и поставлен.
    """
    rows, _ = _rows(_TRANSITION_TABLE)
    table = next(r for r in rows if r["form"] == C.FORM_OUT_TRANSITION_TABLE)
    assert table["entry"] == C.ENTRY_ABSENT
    assert table["entry_proof"] == C.PROOF_NO_SUCH_FORM
    assert table["tail_line"] is None
    assert table["branches_the_closed_list_sees"] == 0
    assert table["classes"] == ["bad", "ok", "warn"]


def test_a_table_whose_values_are_not_classes_declares_no_transition():
    """Словарь чисел перехода не объявляет — находкой быть не может."""
    rows, elsewhere = _rows(_TABLE_OF_NUMBERS)
    assert rows == []
    assert elsewhere == 0


# ─────────────────────── форма 3: `match` ───────────────────────

def test_a_match_over_a_counter_is_found():
    """`match` градуирует исходы тем же способом и в перечень соседа не входит."""
    rows, _ = _rows(_MATCH_OVER_A_COUNTER)
    found = next(r for r in rows if r["form"] == C.FORM_OUT_MATCH)
    assert found["entry"] == C.ENTRY_ABSENT
    assert found["entry_proof"] == C.PROOF_NO_SUCH_FORM
    assert found["subject"] == "counts.get(HARSH)"


def test_a_match_with_a_single_class_bearing_case_is_refused():
    """Одна ветвь градуировки не объявляет."""
    rows, elsewhere = _rows(_MATCH_WITH_ONE_CASE)
    assert rows == []
    assert elsewhere == 0


# ─────────────────────── доказательства входа ───────────────────────

def test_a_file_that_gave_the_neighbour_no_row_is_proved_absent_by_construction():
    """Третье доказательство: тождество спрашивать НЕ О ЧЕМ.

    Файл, не давший соседу ни одной строки, не отдал ему ни одного узла — и
    звать это «измеренным тождеством» значило бы выдать отсутствие вклада за
    замер. Имена разведены затем, что чинятся они разным.
    """
    rows, _ = C._outside_sites(
        "<lonely>", ast.parse(_CHAIN_WITH_A_BARE_TAIL),
        accepted=set(), file_in_population=False, tree_is_the_neighbours=False)
    chain = next(r for r in rows if r["form"] == C.FORM_OUT_ELIF_CHAIN)
    assert chain["entry"] == C.ENTRY_ABSENT
    assert chain["entry_proof"] == C.PROOF_FILE_GAVE_NO_ROW


def test_without_the_neighbours_tree_the_entry_is_the_third_outcome():
    """ОХРАНА РАСШИРЕНИЯ, а не живой случай, и это сказано прямо.

    Шаг берёт дерево У СОСЕДА там, где сосед его читал, поэтому ветвь сегодня
    недостижима ни одним файлом дерева. Проверяется прямой подстановкой:
    снять её значило бы ответить на «тот же ли это узел» догадкой о
    совпадении файла и строки — ровно той, которую сосед запретил себе сам.
    """
    entry, proof, gap = C._entry_of_the_tail(
        ast.parse("if 1:\n    pass\n").body[0], accepted=set(),
        file_in_population=True, tree_is_the_neighbours=False)
    assert entry == C.ENTRY_UNMEASURED
    assert proof == C.PROOF_BY_NODE_IDENTITY
    assert gap == C.OUT_GAP_NEIGHBOUR_TREE


def test_a_class_that_is_not_a_value_is_counted_apart_from_the_values():
    """Имя значением не является ни в какую сторону.

    Ввезённая константа, выданная за значение, слила бы два разных класса в
    один; объявить её «отличной от всех» значило бы выдумать находку.
    """
    source = _FIVE_BRANCH_CHAIN.replace("status = MUTE", "status = IMPORTED_ELSEWHERE")
    rows, _ = _rows(source)
    chain = next(r for r in rows if r["form"] == C.FORM_OUT_ELIF_CHAIN)
    assert chain["classes_not_a_value"] == 1
    assert "IMPORTED_ELSEWHERE" not in chain["classes"]


# ─────────────────────── третий исход ШАГА ───────────────────────

def test_the_step_refuses_when_its_own_control_fails(monkeypatch, tmp_path):
    """Контроль не узнал известного случая ⇒ население не печатается вовсе."""
    monkeypatch.setattr(C, "_outside_control",
                        lambda: {"passed": False, "reason": "подстановка"})
    out = C.the_verdict_form_outside_the_closed_list(tmp_path)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_OUT_CONTROL
    assert "population" not in out


def test_the_step_propagates_the_neighbours_third_outcome(tmp_path):
    """Население соседа не измерено ⇒ своё число шаг не выдумывает.

    И имя отказа у него СВОЁ: «сосед не измерил» и «моё дерево прочитано не
    целиком» чинятся разным.
    """
    out = C.the_verdict_form_outside_the_closed_list(
        tmp_path, population={"status": "UNMEASURED", "control": {"passed": True},
                              "unmeasured_class": C.UNMEASURED_VERDICT_TREE,
                              "reason": "подстановка",
                              "files_unreadable": [{"file": "x", "reason": "y"}]})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_OUT_POPULATION
    assert out["files_unreadable"] == [{"file": "x", "reason": "y"}]


def test_a_tree_without_the_declared_directories_is_not_measured(tmp_path):
    """Каталога нет ⇒ «не измерено» с названной причиной, а не «форм нет»."""
    out = C.the_verdict_form_outside_the_closed_list(
        tmp_path, population={"status": "MEASURED", "control": {"passed": True},
                              "rows": [], "files_scanned": 0,
                              "files_unreadable": []})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_OUT_TREE
    assert [item["file"] for item in out["files_unreadable"]] == list(C.OPEN_COUNTER_DIRS)


def test_an_unreadable_file_is_not_a_clean_pass(tmp_path):
    """Файл, который не разобрался, обнуляет весь замер — не «в нём форм нет»."""
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "broken.py").write_text(
        "def judge(:\n", encoding="utf-8")
    out = C.the_verdict_form_outside_the_closed_list(
        tmp_path, population={"status": "MEASURED", "control": {"passed": True},
                              "rows": [], "files_scanned": 1,
                              "files_unreadable": []})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_OUT_TREE
    assert out["files_unreadable"][0]["reason"].startswith("SyntaxError")


# ─────────────────────── сборка отчёта ───────────────────────

def test_the_report_counts_each_declared_name_and_tells_them_apart(tmp_path):
    """Сборка отчёта проверяется САМА, а не через сумму исходов.

    Урок ADR-581: подмена `by_entry[ENTRY_TRUNCATED]` на `by_entry[ENTRY_ABSENT]`
    в главном числе шага на живом дереве была бы невидима, если бы счёты
    совпадали. Здесь население внесено ВНУТРЬ и счёты РАЗЛИЧИМЫ по
    построению: 2 усечённых против 1 не вошедшей.
    """
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "a.py").write_text(
        _FIVE_BRANCH_CHAIN, encoding="utf-8")
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "b.py").write_text(
        _FIVE_BRANCH_CHAIN.replace("def judge(", "def judge_two("), encoding="utf-8")
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "c.py").write_text(
        _CHAIN_WITH_A_BARE_TAIL, encoding="utf-8")
    out = C.the_verdict_form_outside_the_closed_list(tmp_path)
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["population"] == 3
    assert out["by_form"][C.FORM_OUT_ELIF_CHAIN] == 3
    assert out["by_entry"][C.ENTRY_TRUNCATED] == 2
    assert out["by_entry"][C.ENTRY_ABSENT] == 1
    assert out["by_entry"][C.ENTRY_UNMEASURED] == 0
    assert out["declared_absent_but_entered_truncated"] == 2
    assert len(out["truncated_sites"]) == 2
    assert {item["file"] for item in out["truncated_sites"]} == {
        f"{C.OPEN_COUNTER_DIRS[0]}/a.py", f"{C.OPEN_COUNTER_DIRS[0]}/b.py"}
    assert out["by_entry_proof"][C.PROOF_BY_NODE_IDENTITY] == 3


def test_the_harm_row_carries_both_branch_counts(tmp_path):
    """«Усечён» без счёта ветвей есть оборот речи, а не замер."""
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "a.py").write_text(
        _FIVE_BRANCH_CHAIN, encoding="utf-8")
    out = C.the_verdict_form_outside_the_closed_list(tmp_path)
    harm = out["truncated_sites"][0]
    assert harm["branches_bearing_a_class"] == 5
    assert harm["branches_the_closed_list_sees"] == 2
    assert harm["tail_line"] > harm["line"]
    assert harm["classes"] and harm["keys"]


def test_the_step_declares_its_one_sidedness_and_what_it_does_not_prove(tmp_path):
    """Закрытый перечень форм ВНЕ перечня обязан быть назван вслух.

    Иначе «форм вне перечня нет» нельзя отличить от «я искал одну форму» —
    ровно та подмена, которую заказ и чинит.
    """
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    out = C.the_verdict_form_outside_the_closed_list(tmp_path)
    assert out["status"] == "MEASURED"
    assert out["population"] == 0
    assert out["forms_outside"] == list(C._FORMS_OUTSIDE)
    assert out["closed_list"] == list(C._VERDICT_FORMS)
    assert any("ПЕРЕЧЕНЬ ФОРМ ВНЕ ПЕРЕЧНЯ ТОЖЕ ЗАКРЫТ" in line
               for line in out["blind"])
    assert len(out["what_it_does_not_prove"]) == 3


# ─────────────────────── проводка в отчёт шага 0-офис ───────────────────────

def test_the_office_line_names_the_answer_to_the_order():
    """Число, которого никто не печатает, читателю не достаётся."""
    doc = {"the_verdict_form_outside_the_closed_list": {
        "status": "MEASURED", "population": 6, "files_scanned": 556,
        "neighbour_population": 6, "counter_written_in_another_scope": 1,
        "by_form": {C.FORM_OUT_ELIF_CHAIN: 6, C.FORM_OUT_TRANSITION_TABLE: 0,
                    C.FORM_OUT_MATCH: 0},
        "by_entry": {C.ENTRY_TRUNCATED: 4, C.ENTRY_ABSENT: 2,
                     C.ENTRY_UNMEASURED: 0},
        "by_entry_proof": {C.PROOF_BY_NODE_IDENTITY: 4,
                           C.PROOF_FILE_GAVE_NO_ROW: 2,
                           C.PROOF_NO_SUCH_FORM: 0},
        "unmeasured_reasons": {C.OUT_GAP_NEIGHBOUR_TREE: 0},
        "control": {"passed": True, "scenes": ["positive", "lonely", "clean"],
                    "forms": {}, "entries": {}, "proofs": {}, "anchors": {},
                    "negative_rows": 0, "negative_counter_elsewhere": 1},
        "truncated_sites": [{"file": "x.py", "line": 1, "owner": "run",
                             "counter": "counts", "tail_line": 5,
                             "branches_bearing_a_class": 5,
                             "branches_the_closed_list_sees": 2,
                             "keys": ["'a'"], "classes": ["ok"]}],
        "blind": ["односторонность"]}}
    lines = C.format_report(doc)
    text = "\n".join(lines)
    assert "[ФОРМА ВНЕ ПЕРЕЧНЯ]" in text
    assert "ОТВЕТ ЗАКАЗУ G102 п. 2" in text
    assert "УСЕЧЁН" in text


def test_a_census_without_this_step_says_so_instead_of_printing_zero():
    """Шага нет в документе ⇒ «НЕ ИЗМЕРЕНО», а не «форм вне перечня нет»."""
    lines = C.format_report({})
    assert any("[ФОРМА ВНЕ ПЕРЕЧНЯ] НЕ ИЗМЕРЕНО" in line for line in lines)


def test_an_unmeasured_step_is_rendered_with_its_named_class():
    """Имя отказа доезжает до читателя — иначе чинить он пойдёт не то."""
    lines = C.format_report({"the_verdict_form_outside_the_closed_list": {
        "status": "UNMEASURED", "unmeasured_class": C.UNMEASURED_OUT_CONTROL,
        "reason": "контроль не прошёл"}})
    assert any(C.UNMEASURED_OUT_CONTROL in line for line in lines)


# ─────────────────────── живое дерево ───────────────────────

@pytest.fixture(scope="module")
def live_step():
    """ОДИН обход живого дерева на всю батарею.

    По разу на тест он стоил бы семь секунд на каждый, а на мутационном
    стенде та же небрежность умножилась бы на сотни.
    """
    pop = C._verdict_population(_ROOT)
    return C.the_verdict_form_outside_the_closed_list(_ROOT, population=pop), pop


def test_live_the_population_of_the_form_outside_the_list_is_measured(live_step):
    """Замер живого дерева есть, и он НЕ ноль — ровно то, чего не было."""
    out, _pop = live_step
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["population"] >= 1
    assert out["by_form"][C.FORM_OUT_ELIF_CHAIN] >= 1


def test_live_every_truncated_site_has_more_branches_than_the_list_sees(live_step):
    """Свойство, а не число: усечение обязано БЫТЬ усечением.

    Строка, у которой ветвей не больше, чем видит закрытый перечень, была бы
    ложной находкой — и поймать её можно только этим неравенством.
    """
    out, _pop = live_step
    for item in out["truncated_sites"]:
        assert item["branches_bearing_a_class"] > item["branches_the_closed_list_sees"]
        assert item["tail_line"] > item["line"]


def test_live_the_truncated_tails_are_rows_of_the_neighbours_population(live_step):
    """ВРЕД доказан у СОСЕДА, а не только у себя.

    Хвост, объявленный усечённым, обязан найтись строкой населения соседа —
    иначе «сосед берёт его как целый вердикт» было бы словом.
    """
    out, pop = live_step
    neighbour = {(row["file"], row["line"]) for row in pop["rows"]}
    for item in out["truncated_sites"]:
        assert (item["file"], item["tail_line"]) in neighbour
    assert out["by_entry"][C.ENTRY_TRUNCATED] <= out["neighbour_population"]
