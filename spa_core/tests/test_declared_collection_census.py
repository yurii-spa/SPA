"""Пустой объявленный перечень, читаемый ТОЛЬКО циклом, — ложное усиление.

# LLM_FORBIDDEN

Сторож прибора `spa_core/monitoring/declared_collection_census.py` (ADR-940, заказ
G929 п. 3). Каждая проверка — ЗВЕНО контура, и красна она при РАЗРЫВЕ названного
звена, а не при любой правке: контур «объявление → чтение → род чтения → предмет»
собирается сценой на диске, и каждое звено рвётся отдельно.

**Положительный контроль — настоящая авария, а не придуманная.** Мутационная проба
цикла #1058 оставила живым мутанта ``AGGRAVATING = {}`` в
`spa_core/monitoring/child_env_census.py`: весь набор остался зелёным, потому что
единственный читатель перебирал перечень циклом. Контроль берёт ДВА НАСТОЯЩИХ файла
репозитория, снимает из них РОВНО противоядие, дописанное #1058, и требует, чтобы
вердикт прибора ПЕРЕВЕРНУЛСЯ. Проверка подстрокой здесь невозможна по построению:
сравниваются два ЗАМЕРА одной и той же сцены.
"""
from __future__ import annotations

import ast
import functools
from pathlib import Path

import pytest

from spa_core.monitoring import declared_collection_census as dcc

REPO = Path(__file__).resolve().parents[2]


@functools.lru_cache(maxsize=1)
def _real() -> dict:
    """Замер НАСТОЯЩЕГО дерева считается ОДИН раз: он стоит десятки секунд,
    а четыре звена ниже спрашивают у него РАЗНОЕ."""
    return dcc.census(REPO)


def _scene(base: Path, files: dict) -> Path:
    """Одноразовая сцена на диске. Прибор читает ТЕКСТ, ничего не импортируя."""
    for rel, text in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return base


def _row(result: dict, name: str) -> dict:
    rows = [r for r in result["rows"] if r["name"] == name]
    assert len(rows) == 1, f"ожидалось ровно одно объявление {name}, вышло {len(rows)}"
    return rows[0]


def _row_in(result: dict, module: str, name: str) -> dict:
    """Строка ОДНОГО объявления, названного ПАРОЙ «модуль + имя».

    Именно пара и есть предмет ADR-942: на сцене с одноимёнными перечнями
    обращение по одному имени не отличило бы их друг от друга — то есть контроль
    померил бы ту самую ошибку, против которой написан.
    """
    rows = [r for r in result["rows"] if r["name"] == name and r["module"] == module]
    assert len(rows) == 1, (
        f"ожидалось ровно одно объявление {module}:{name}, вышло {len(rows)}")
    return rows[0]


def _measure(base: Path, body: str, name: str = "COLL") -> dict:
    _scene(base, {"spa_core/m.py": body})
    result = dcc.census(base, declaration_roots=("spa_core",), reader_roots=("spa_core",))
    assert not result["unmeasured"], result["unparsable_declaration_files"]
    return _row(result, name)


# ───────────────────────── звено 1: предмет вообще находится ─────────────────────────

def test_a_loop_only_declaration_is_the_subject(tmp_path):
    """Контур целиком: объявлен перечень, прочитан ТОЛЬКО циклом ⇒ ПРЕДМЕТ."""
    row = _measure(tmp_path, "COLL = (1, 2)\n\n\ndef f():\n    for x in COLL:\n        yield x\n")
    assert row["subject"] is True, row["axes"]
    assert row["axes"] == {
        "reader": "has_reader", "iter": "iterated",
        "empty": "not_asked", "other": "only_loop",
    }


# ──────────── звено 2: ВОПРОС О НЕПУСТОТЕ снимает предмет (противоядие класса) ────────────

@pytest.mark.parametrize("antidote,link", [
    ("    if COLL:\n        pass\n", "if NAME"),
    ("    if not COLL:\n        pass\n", "not NAME"),
    ("    assert COLL\n", "assert NAME"),
    ("    n = len(COLL)\n", "len(NAME)"),
    ("    n = bool(COLL)\n", "bool(NAME)"),
    ("    n = any(COLL)\n", "any(NAME)"),
    ("    n = COLL == ()\n", "сравнение с пустым литералом"),
    ("    n = COLL or (1,)\n", "член and/or"),
    ("    while COLL:\n        break\n", "while NAME"),
])
def test_a_question_about_emptiness_removes_the_subject(tmp_path, antidote, link):
    """РАЗРЫВ звена «о непустоте не спросили» — предмет обязан исчезнуть.

    Каждая форма названа отдельно: пропусти прибор одну, и перечень с настоящим
    противоядием попал бы в население — то есть прибор выдумал бы находку.
    """
    body = "COLL = (1, 2)\n\n\ndef f():\n    for x in COLL:\n        pass\n" + antidote
    row = _measure(tmp_path, body)
    assert row["axes"]["empty"] == "asked", f"форма «{link}» прибором НЕ прочитана: {row['reads']}"
    assert row["subject"] is False, link


# ──────────── звено 3: чтение ИНОГО рода снимает предмет ────────────

@pytest.mark.parametrize("read,link", [
    ("    y = 1 in COLL\n", "x in NAME"),
    ("    y = COLL[0]\n", "NAME[k]"),
    ("    y = COLL.index(1)\n", "метод не из прозрачных"),
    ("    y = g(COLL)\n", "передача аргументом"),
])
def test_a_read_of_another_kind_removes_the_subject(tmp_path, read, link):
    body = ("COLL = (1, 2)\n\n\ndef g(a):\n    return a\n\n\n"
            "def f():\n    for x in COLL:\n        pass\n" + read)
    row = _measure(tmp_path, body)
    assert row["axes"]["other"] == "other_reads", f"чтение «{link}» прочитано как итерация: {row['reads']}"
    assert row["subject"] is False, link


# ──────────── звено 4: «не перебирают» и «не читают» — РАЗНЫЕ исходы ────────────

def test_a_declaration_nobody_iterates_is_not_the_subject(tmp_path):
    row = _measure(tmp_path, "COLL = (1, 2)\n\n\ndef f():\n    return 1 in COLL\n")
    assert row["axes"]["iter"] == "never_iterated"
    assert row["subject"] is False


def test_a_declaration_nobody_reads_is_a_DIFFERENT_class(tmp_path):
    """Мёртвое объявление — другой класс, и слить его с нашим нельзя.

    Если бы «читателя нет» попадало в предмет, число отвечало бы на вопрос
    «сколько у нас мёртвого кода», а не на вопрос заказа.
    """
    row = _measure(tmp_path, "COLL = (1, 2)\n\n\ndef f():\n    return 1\n")
    assert row["axes"]["reader"] == "no_reader"
    assert row["read_count"] == 0, row["reads"]
    assert row["subject"] is False


# ──────────── звено 5: ПРОЗРАЧНЫЕ ОБЁРТКИ. Разорви его — и известный предмет исчезнет ────────────

@pytest.mark.parametrize("reader,link", [
    ("    for x in COLL:\n        pass\n", "сам перечень"),
    ("    for x in COLL.items():\n        pass\n", "NAME.items()"),
    ("    for x in COLL.keys():\n        pass\n", "NAME.keys()"),
    ("    for x in sorted(COLL):\n        pass\n", "sorted(NAME)"),
    ("    for x in list(COLL):\n        pass\n", "list(NAME)"),
    ("    for x in {**COLL}.items():\n        pass\n", "{**NAME} — форма аварии #1058"),
    ("    for x in {'a': 1, **COLL}.items():\n        pass\n", "{**A, **NAME} — дословная форма #1058"),
    ("    y = any(v for v in COLL.items())\n", "генератор по NAME.items()"),
    ("    y = all(v for v in {'a': 1, **COLL}.items())\n", "генератор по объединённому словарю"),
])
def test_transparent_wrappers_do_not_hide_the_subject(tmp_path, reader, link):
    """Обёртка, СОХРАНЯЮЩАЯ пустоту, предмет не снимает.

    Звено несущее: остановись прибор у ``**``, и ЕДИНСТВЕННЫЙ известный член класса
    выпал бы из населения — прибор ответил бы «пусто» о том, чего не видел.
    """
    row = _measure(tmp_path, "COLL = {'k': 1}\n\n\ndef f():\n" + reader)
    assert row["axes"]["iter"] == "iterated", f"обёртка «{link}» оборвала путь: {row['reads']}"
    assert row["subject"] is True, link


def test_an_opaque_wrapper_is_NOT_called_iteration(tmp_path):
    """Обратная сторона: обёртка, пустоту НЕ сохраняющая, итерацией не считается.

    Без этой проверки «прозрачность» можно было бы покрасить зелёным, объявив
    прозрачным ВСЁ, — и предмет стал бы равен поверхности.
    """
    row = _measure(tmp_path, "COLL = (1, 2)\n\n\ndef f():\n    for x in str(COLL):\n        pass\n")
    assert row["axes"]["iter"] == "never_iterated", row["reads"]
    assert row["axes"]["other"] == "other_reads"
    assert row["subject"] is False


# ──────────── звено 6: ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на НАСТОЯЩЕЙ аварии #1058 ────────────

ANTIDOTE_1058 = "assert cec.AGGRAVATING"


def test_the_only_known_member_of_the_class_is_seen_differentially(tmp_path):
    """Авария #1058 воспроизводится на НАСТОЯЩИХ файлах репозитория.

    Сцена — два подлинных файла (`child_env_census.py` и его тест). Из копии
    снимается РОВНО то противоядие, которое дописал #1058, и вердикт прибора обязан
    ПЕРЕВЕРНУТЬСЯ. Это и есть «зелёный на целом контуре, красный на порванном
    звене», где звено — настоящее, а не выдуманное.
    """
    module = REPO / "spa_core/monitoring/child_env_census.py"
    test = REPO / "spa_core/tests/test_child_env_census.py"
    if not module.exists() or not test.exists():
        pytest.fail(
            "НЕ ИЗМЕРЕНО: сцены положительного контроля нет в дереве — "
            f"{module} / {test}. Это третий исход, а не успех")
    module_src, test_src = module.read_text(), test.read_text()
    if ANTIDOTE_1058 not in test_src:
        pytest.fail(
            f"НЕ ИЗМЕРЕНО: противоядие #1058 ({ANTIDOTE_1058!r}) в дереве не найдено — "
            "контроль судить нечем; если оно снято сознательно, звено надо переписать, "
            "а не гасить")

    files = {
        "spa_core/monitoring/child_env_census.py": module_src,
        "spa_core/tests/test_child_env_census.py": test_src,
    }
    with_antidote = dcc.census(
        _scene(tmp_path / "a", files), declaration_roots=("spa_core",), reader_roots=("spa_core",))
    row_a = _row(with_antidote, "AGGRAVATING")
    assert row_a["axes"]["empty"] == "asked", row_a["reads"]
    assert row_a["subject"] is False, "противоядие #1058 на месте, а прибор числит предмет"

    # Снимается ВСЁ УТВЕРЖДЕНИЕ, а не строка с подстрокой: у `assert` #1058 три
    # строки, и срезанная по первой сцена не разбирается вовсе — прибор честно
    # ответил бы `unmeasured`, и контроль померил бы свою собственную ошибку.
    tree = ast.parse(test_src)
    targets = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assert)
        and ANTIDOTE_1058 in (ast.get_source_segment(test_src, node) or "")
    ]
    assert len(targets) == 1, f"ожидался ровно один assert о непустоте, вышло {len(targets)}"
    lines = test_src.splitlines(keepends=True)
    del lines[targets[0].lineno - 1:targets[0].end_lineno]
    stripped = "".join(lines)
    scene_b = _scene(tmp_path / "b", {**files, "spa_core/tests/test_child_env_census.py": stripped})
    without = dcc.census(scene_b, declaration_roots=("spa_core",), reader_roots=("spa_core",))
    assert not without["unmeasured"], (
        "сцена без противоядия НЕ РАЗБИРАЕТСЯ — контроль померил бы свою ошибку, "
        f"а не класс: {without['unparsable_reader_files']}")
    row_b = _row(without, "AGGRAVATING")
    assert row_b["axes"]["empty"] == "not_asked", row_b["reads"]
    assert row_b["subject"] is True, (
        "авария #1058 прибором НЕ ВИДНА: противоядие снято, а предмет не появился")
    assert without["subject"] == with_antidote["subject"] + 1, (
        "перевернулся не ТОЛЬКО известный член класса — "
        f"{with_antidote['subject']} → {without['subject']}")


# ──────────── звено 7: третий исход. «Не измерено» нулём не считается ────────────

def test_an_unparsable_file_is_a_third_outcome_not_a_clean_pass(tmp_path):
    """Файл, который мог нести ``assert NAME``, но не разобран, запирает ОБЕ оси.

    Иначе пропущенный вопрос о непустоте превратил бы «противоядие есть» в
    «предмета нет» — ложное усиление в самом приборе против ложного усиления.
    """
    base = _scene(tmp_path, {
        "spa_core/m.py": "COLL = (1, 2)\n\n\ndef f():\n    for x in COLL:\n        pass\n",
        "spa_core/broken.py": "def f(:\n    pass\n",
    })
    result = dcc.census(base, declaration_roots=("spa_core",), reader_roots=("spa_core",))
    assert result["unmeasured"] is True
    assert result["unparsable_reader_files"], "файл не разобран, а прибор молчит"
    reason = result["unparsable_reader_files"][0]["reason"]
    assert "SyntaxError" in reason, reason
    row = _row(result, "COLL")
    assert set(row["axes"].values()) == {"unmeasured"}, row["axes"]
    assert row["subject"] is False, "«не измерено» выдано за находку"
    assert row["not_excluded"] is True, "«не измерено» выдано за чисто"


# ──────────── звено 8: ОБЪЯВЛЕНИЕ несёт СВОЙ контракт ────────────

def test_the_declaration_carries_its_own_contract():
    """Опасная сторона осей объявлена КОНСТАНТОЙ и сверяется с перечнями исходов.

    Урок ADR-932: мерка, живущая только в теле условия, расходится с объявлением
    молча. Поэтому `SUBJECT_AXES` обязан ссылаться на объявленные исходы.
    """
    outcomes = {
        "reader": dcc.READER_OUTCOMES, "iter": dcc.ITER_OUTCOMES,
        "empty": dcc.EMPTY_OUTCOMES, "other": dcc.OTHER_OUTCOMES,
    }
    assert set(dcc.SUBJECT_AXES) == set(outcomes), (
        "ось предмета без объявленных исходов (или наоборот)")
    for axis, dangerous in dcc.SUBJECT_AXES.items():
        assert dangerous in outcomes[axis], f"{axis}: {dangerous} вне {outcomes[axis]}"
        assert "unmeasured" in outcomes[axis], f"{axis}: нет третьего исхода"


def test_the_instruments_own_collections_are_not_empty():
    """Прибор обязан выдерживать СВОЮ меру: его перечни читаются циклом.

    Это дословное противоядие класса, применённое к самому прибору. Опустей любой
    из них — и прибор молча перестал бы видеть свою часть поверхности.
    """
    for name in ("DECLARATION_ROOTS", "READER_ROOTS", "SKIP_PARTS",
                 "TRANSPARENT_CALLS", "TRANSPARENT_METHODS", "EMPTINESS_CALLS",
                 "READ_KINDS", "SUBJECT_AXES", "READER_OUTCOMES", "ITER_OUTCOMES",
                 "EMPTY_OUTCOMES", "OTHER_OUTCOMES", "RESOLUTION_KINDS",
                 "SCOPE_TYPES"):
        assert getattr(dcc, name), f"{name} ПУСТ — цикл по нему истинен вхолостую"
    assert dcc.WRAPPER_DEPTH >= 1, "глубина 0 оборвала бы ВСЕ обёртки молча"
    assert dcc.SCOPE_DEPTH >= 1, "глубина 0 назвала бы ЛЮБОЕ имя не локальным"
    assert "unresolved" in dcc.RESOLUTION_KINDS, "у привязки нет третьего исхода"
    assert "module" in dcc.RESOLUTION_KINDS, "привязка не умеет назвать модуль"


# ──────────── звено 9: исходы на НАСТОЯЩЕМ дереве ЗАМКНУТЫ ────────────

def test_every_outcome_on_the_real_tree_is_declared():
    """Дверь, вернувшая имя вне своего списка, краснит сторожа, а не проезжает."""
    result = _real()
    assert result["surface"] > 0, "поверхность ПУСТА — замер не состоялся"
    outcomes = {
        "reader": dcc.READER_OUTCOMES, "iter": dcc.ITER_OUTCOMES,
        "empty": dcc.EMPTY_OUTCOMES, "other": dcc.OTHER_OUTCOMES,
    }
    for row in result["rows"]:
        for axis, value in row["axes"].items():
            assert value in outcomes[axis], f"{row['name']}: {axis}={value}"
    for row in result["rows"]:
        for kind in row["reads"]:
            assert kind in dcc.READ_KINDS, kind


def test_the_report_names_the_instruments_own_coverage():
    """Урок ADR-935: прибор, не назвавший свой охват, отвечает о том, чего не видел."""
    text = dcc.report(_real(), limit=1)
    for must in ("поверхность", "корни объявления", "корни читателей", "глубина обёрток",
                 "ПРЕДМЕТ", "НЕ ИСКЛЮЧЁН"):
        assert must in text, f"отчёт не называет «{must}»"


def test_the_subject_is_a_subset_of_the_surface():
    result = _real()
    counted = sum(1 for r in result["rows"] if r["subject"])
    assert result["subject"] == counted, "напечатанное число не сошлось с измеренным"
    assert result["subject"] <= result["surface"]
    assert len(result["rows"]) == result["surface"]


# ──────────── звено 10: ЧТЕНИЕ ПРИВЯЗАНО К МОДУЛЮ, а не к голому имени (ADR-942) ────────────
#
# Звено написано по замеру цикла #1060 (ADR-941): прибор ключевал чтения ОДНИМ
# именем, и `assert ПЕРЕЧЕНЬ`, дописанный для одного модуля, снимал с предмета ВСЕ
# одноимённые перечни дерева — ошибка в сторону ЛОЖНОГО УСИЛЕНИЯ, то есть ровно тот
# класс, который прибор написан измерять, жил в самом приборе. Разорви звено
# (верни слияние по имени) — и КАЖДАЯ проверка ниже краснеет.

_TWO_MODULES = {
    "spa_core/one.py": "COLL = (1, 2)\n",
    "spa_core/two.py": "COLL = (3, 4)\n",
}


def test_an_antidote_in_one_module_does_not_cover_its_namesake(tmp_path):
    """ДОСЛОВНАЯ сцена аварии: два одноимённых перечня, противоядие у ОДНОГО.

    Второй обязан ОСТАТЬСЯ в предмете. Вернись слияние по имени — `assert COLL`
    из `reader_one.py` зачтётся обоим, `two.COLL` выпадет из предмета, и эта
    проверка покраснеет. Другого способа поймать возврат слияния нет: число
    предмета на настоящем дереве — замер, а не константа.
    """
    base = _scene(tmp_path, {
        **_TWO_MODULES,
        "spa_core/reader_one.py": (
            "from spa_core.one import COLL\n\n\n"
            "def f():\n    for x in COLL:\n        pass\n    assert COLL\n"),
        "spa_core/reader_two.py": (
            "from spa_core.two import COLL\n\n\n"
            "def g():\n    for x in COLL:\n        pass\n"),
    })
    result = dcc.census(base, declaration_roots=("spa_core",), reader_roots=("spa_core",))
    assert not result["unmeasured"], result["unparsable_reader_files"]

    with_antidote = _row_in(result, "spa_core/one.py", "COLL")
    assert with_antidote["axes"]["empty"] == "asked", with_antidote["reads"]
    assert with_antidote["subject"] is False, "противоядие на месте, а прибор числит предмет"

    namesake = _row_in(result, "spa_core/two.py", "COLL")
    assert namesake["axes"]["empty"] == "not_asked", (
        "чужое противоядие зачтено одноимённому перечню — слияние по имени ВЕРНУЛОСЬ: "
        f"{namesake['reads']}")
    assert namesake["subject"] is True, namesake["axes"]
    assert result["subject"] == 1, (
        f"предметом обязан быть РОВНО один из двух, вышло {result['subject']}")
    assert result["colliding_names"] == 1, result["colliding_names"]
    assert result["declarations_in_collision"] == 2, result["declarations_in_collision"]


@pytest.mark.parametrize("reader,link", [
    ("from spa_core.two import COLL\n\n\ndef g():\n    for x in COLL:\n        pass\n",
     "from pkg.mod import NAME"),
    ("from spa_core.two import COLL as C\n\n\ndef g():\n    for x in C:\n        pass\n",
     "from pkg.mod import NAME as ALIAS"),
    ("import spa_core.two as m\n\n\ndef g():\n    for x in m.COLL:\n        pass\n",
     "import pkg.mod as m + m.NAME"),
    ("import spa_core.two\n\n\ndef g():\n    for x in spa_core.two.COLL:\n        pass\n",
     "import pkg.mod + pkg.mod.NAME"),
    ("from spa_core import two\n\n\ndef g():\n    for x in two.COLL:\n        pass\n",
     "from pkg import mod + mod.NAME"),
    ("from .two import COLL\n\n\ndef g():\n    for x in COLL:\n        pass\n",
     "относительный импорт"),
])
def test_every_declared_import_form_names_the_module(tmp_path, reader, link):
    """Каждая форма ввоза названа ОТДЕЛЬНО: не разбери прибор одну — чтение ушло бы
    в третий исход, и перечень с НАСТОЯЩИМ читателем попал бы в `not_excluded`.

    Сцена всегда одна и та же: читается `two.COLL`, а `one.COLL` не читает никто.
    Поэтому проверка отвечает сразу на два вопроса — привязано ли чтение к тому
    модулю, И не зачлось ли оно соседу.
    """
    base = _scene(tmp_path, {**_TWO_MODULES, "spa_core/reader.py": reader})
    result = dcc.census(base, declaration_roots=("spa_core",), reader_roots=("spa_core",))
    assert not result["unmeasured"], result["unparsable_reader_files"]
    read = _row_in(result, "spa_core/two.py", "COLL")
    assert read["axes"]["iter"] == "iterated", f"форма «{link}» не разобрана: {read}"
    assert read["subject"] is True, link
    silent = _row_in(result, "spa_core/one.py", "COLL")
    assert silent["axes"]["reader"] == "no_reader", (
        f"чтение формы «{link}» зачтено ОДНОИМЁННОМУ перечню: {silent['reads']}")


def test_a_local_binding_is_not_a_read_of_the_module_level_namesake(tmp_path):
    """Имя, СВЯЗАННОЕ внутри функции, — не чтение одноимённого объявления.

    Дословный случай из замера #1060: локальные `_TS_KEYS` внутри функций
    `daily_operations_report.py` попадали в список чтений обоих модульных
    `_TS_KEYS`. Такое чтение не принадлежит НИ ОДНОМУ объявлению уровня модуля, и
    это ответ, а не третий исход, — поэтому предмет обязан остаться предметом.
    """
    base = _scene(tmp_path, {
        "spa_core/m.py": "COLL = (1, 2)\n\n\ndef f():\n    for x in COLL:\n        pass\n",
        "spa_core/local.py": (
            "def g():\n    COLL = (7,)\n    assert COLL\n    return COLL[0]\n"),
    })
    result = dcc.census(base, declaration_roots=("spa_core",), reader_roots=("spa_core",))
    assert not result["unmeasured"], result["unparsable_reader_files"]
    row = _row_in(result, "spa_core/m.py", "COLL")
    assert row["axes"]["empty"] == "not_asked", (
        f"локальное `assert COLL` зачтено модульному перечню: {row['reads']}")
    assert row["unresolved_read_count"] == 0, (
        "локальное связывание выдано за НЕРАЗОБРАННУЮ форму — это ответ, а не "
        f"третий исход: {row['unresolved_reads']}")
    assert row["subject"] is True, row["axes"]
    # Локальных чтений на сцене РОВНО два — `assert COLL` и `COLL[0]`; присваивание
    # `COLL = (7,)` чтением не является. Число названо, чтобы «ни одно чтение не
    # разобрано» не могло пройти как успех.
    assert result["resolution"]["local"] == 2, result["resolution"]


def test_a_global_statement_keeps_the_read_at_module_level(tmp_path):
    """Обратная сторона: `global NAME` возвращает чтение на уровень модуля.

    Без этого прибор назвал бы локальным имя, которое функция объявила
    глобальным, — и НАСТОЯЩЕЕ противоядие перестало бы читаться.
    """
    base = _scene(tmp_path, {
        "spa_core/m.py": (
            "COLL = (1, 2)\n\n\ndef f():\n    for x in COLL:\n        pass\n\n\n"
            "def h():\n    global COLL\n    assert COLL\n    COLL = (3,)\n"),
    })
    result = dcc.census(base, declaration_roots=("spa_core",), reader_roots=("spa_core",))
    row = _row_in(result, "spa_core/m.py", "COLL")
    assert row["axes"]["empty"] == "asked", (
        f"`global COLL` + `assert COLL` прочитано как локальное: {row['reads']}")
    assert row["subject"] is False


@pytest.mark.parametrize("reader,link", [
    ("def g():\n    assert COLL\n", "голое имя без импорта и без связывания"),
    ("from spa_core.other import *\n\n\ndef g():\n    assert COLL\n", "звёздный импорт"),
    ("def g(obj):\n    assert obj.result().COLL\n", "атрибут выражения"),
])
def test_an_unresolvable_read_is_a_THIRD_OUTCOME_not_a_verdict(tmp_path, reader, link):
    """Форма, которую прибор не разобрал, запирает РОВНО свою ось.

    Зачесть такое чтение значило бы вернуть слияние по имени (ложное усиление);
    промолчать о нём — выдумать находку. Поэтому ось становится `unmeasured`,
    объявление уходит в `not_excluded`, и ни тем, ни другим оно не считается
    (инв. #17).
    """
    base = _scene(tmp_path, {
        "spa_core/m.py": "COLL = (1, 2)\n\n\ndef f():\n    for x in COLL:\n        pass\n",
        "spa_core/other.py": "ANOTHER = (1,)\n",
        "spa_core/murky.py": reader,
    })
    result = dcc.census(base, declaration_roots=("spa_core",), reader_roots=("spa_core",))
    assert not result["unmeasured"], (
        "сцена НЕ РАЗБИРАЕТСЯ — контроль померил бы свою ошибку: "
        f"{result['unparsable_reader_files']}")
    row = _row_in(result, "spa_core/m.py", "COLL")
    assert row["unresolved_read_count"] >= 1, f"форма «{link}» не попала в третий исход: {row}"
    assert row["axes"]["empty"] == "unmeasured", (
        f"форма «{link}»: {row['axes']} — «не измерено» выдано за вердикт")
    assert row["subject"] is False, "«не измерено» выдано за находку"
    assert row["not_excluded"] is True, "«не измерено» выдано за чисто"
    assert result["resolution"]["unresolved"] >= 1, result["resolution"]


def test_the_resolution_outcomes_on_the_real_tree_are_closed():
    """Исходы привязки на НАСТОЯЩЕМ дереве ЗАМКНУТЫ, и охват печатается.

    Привязка, вернувшая исход вне `RESOLUTION_KINDS`, краснит сторожа. И ни один
    исход не имеет права быть единственным: будь всё `unresolved`, прибор
    отвечал бы «не измерено» обо всём дереве и выглядел бы при этом рабочим.
    """
    result = _real()
    assert set(result["resolution"]) <= set(dcc.RESOLUTION_KINDS), result["resolution"]
    assert result["resolution"]["module"] > 0, "ни одно чтение не привязано к модулю"
    assert result["resolution"]["module"] > result["resolution"]["unresolved"], (
        "неразобранных чтений больше, чем привязанных — замер о дереве НЕ состоялся: "
        f"{result['resolution']}")
    assert result["colliding_names"] > 0, (
        "имён в коллизии НЕТ — либо дерево изменилось, либо счёт сломан; "
        "замер #1060 назвал 368")
    text = dcc.report(result, limit=1)
    assert "привязка чтений к МОДУЛЮ объявления" in text, (
        "отчёт не называет СВОЙ способ привязки (урок ADR-935)")
