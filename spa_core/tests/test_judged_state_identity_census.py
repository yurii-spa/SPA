"""Контроли переписи «кто спрашивает, та ли это книга» (заказ G97 п. 2).

Каждый тест ниже — положительный контроль: он воспроизводит ровно ту форму
слепоты, ради которой прибор написан, и КРАСНЕЕТ, если звено порвать
(`.claude/rules/deployment.md`, «проверка сторожа сторожей»). Три теста
воспроизводят ИЗМЕРЕННЫЕ ложные члены первой редакции правила — слияние
областей видимости, ввоз любого имени из читателя и забытое умолчание
параметра: проверка, никогда не видевшая настоящей ошибки, есть украшение.

Сцена — одноразовое дерево в `tmp_path`. Прибор не спрашивает ни часов, ни
номеров процессов, ни git-окружения: единственный его вход есть ПУТЬ, поэтому
три семейства бомб из правила доставки здесь отсутствуют по построению.
"""
from __future__ import annotations

import pathlib

import pytest

from spa_core.monitoring import judged_state_identity_census as jsi
from spa_core.monitoring.judged_state_identity_census import (
    ASKS_NOBODY,
    ASKS_PROBE,
    ASKS_SELF,
    JOURNAL_NAME,
    ROAD_DIRECT,
    ROAD_HELPER,
    ROAD_NAMES_ONLY,
    TENSE_HISTORY,
    TENSE_LOOP,
    TENSE_TAIL,
    TENSE_UNMEASURED,
    Unmeasured,
    format_report,
    main,
    measure,
    verdict,
)

#: Проба §49, которая за прибор СПРАШИВАЕТ: грузит его по имени и зовёт
#: помощника, читающего стоящую книгу. Форма взята у живого `card_acceptance`.
ACCEPTANCE_WITH_QUESTION = '''
import importlib

STANDING_BOOK_FILE = "current_positions.json"
WATCHED_MODULE = "spa_core.monitoring.watched"


def _watched_module():
    return importlib.import_module(WATCHED_MODULE)


def _standing_book_liveness(data):
    path = data / STANDING_BOOK_FILE
    return path.read_text(encoding="utf-8")


def _probe_watched(arg, *, data_dir=None):
    census = _watched_module()
    book = _standing_book_liveness(data_dir)
    return census.measure(), book
'''

#: Та же приёмка, но вопроса НЕТ: проба грузит прибор и книгу не трогает.
ACCEPTANCE_WITHOUT_QUESTION = '''
import importlib

STANDING_BOOK_FILE = "current_positions.json"
WATCHED_MODULE = "spa_core.monitoring.watched"


def _watched_module():
    return importlib.import_module(WATCHED_MODULE)


def _probe_watched(arg, *, data_dir=None):
    census = _watched_module()
    return census.measure()
'''


def _tree(tmp_path: pathlib.Path, *, acceptance: str,
          modules: dict[str, str]) -> pathlib.Path:
    """Одноразовое дерево: приёмка на своём каноническом месте + приборы."""
    root = tmp_path / "repo"
    (root / "spa_core" / "monitoring").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / jsi.STANDING_BOOK_SOURCE).write_text(acceptance, encoding="utf-8")
    for rel, body in modules.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


def _row(doc: dict, rel: str) -> dict | None:
    for row in doc["rows"]:
        if row["file"] == rel:
            return row
    return None


# ───────────────────────── ось дороги: три формы ──────────────────────────────

def test_language_read_is_a_road(tmp_path):
    """Форма 1 — чтение самим языком. Без неё населения нет вовсе."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path
JOURNAL = "{JOURNAL_NAME}"


def measure(data):
    path = Path(data) / JOURNAL
    return path.read_text(encoding="utf-8")
''',
    })
    doc = measure(root)
    row = _row(doc, "spa_core/monitoring/watched.py")
    assert row is not None and row["road"] == ROAD_DIRECT


def test_same_module_helper_is_a_carrying_step_not_completeness(tmp_path):
    """Форма 2 — `_load(d / "trades.json")`.

    Положительный контроль ИЗМЕРЕННОГО промаха: правило, знающее только
    `open`/`.read_text`, объявляло `scripts/book_second_record.py` — настоящего
    читателя журнала, нашедшего дыру записи T008, — «просто поминающим имя».
    """
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "scripts/second_record.py": f'''
from pathlib import Path


def _load(path):
    return path.read_text(encoding="utf-8")


def measure(d):
    return _load(Path(d) / "{JOURNAL_NAME}")
''',
    })
    doc = measure(root)
    row = _row(doc, "scripts/second_record.py")
    assert row is not None, "читатель через помощника того же модуля потерян"
    assert row["road"] == ROAD_DIRECT


def test_parameter_default_is_a_road(tmp_path):
    """Форма 3 — `trades_filename: str = TRADES_FILENAME`.

    Положительный контроль ИЗМЕРЕННОГО промаха: без неё `act_day_recovery`,
    весь предмет которого — восстановление ACT-дня ПО ЖУРНАЛУ, выпадал из
    населения молча.
    """
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/recovery.py": f'''
from pathlib import Path
TRADES_FILENAME = "{JOURNAL_NAME}"


def _read_json(path):
    return path.read_text(encoding="utf-8")


def marked_moves(data_dir, trades_filename=TRADES_FILENAME):
    return _read_json(Path(data_dir) / trades_filename)
''',
    })
    doc = measure(root)
    row = _row(doc, "spa_core/monitoring/recovery.py")
    assert row is not None, "умолчание параметра как дорога потеряно"
    assert row["road"] == ROAD_DIRECT


def test_token_without_a_read_is_not_a_reader(tmp_path):
    """Имя журнала в перечне носителей читателем НЕ делает (урок ADR-550)."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/catalogue.py": f'''
CARRIERS = ("equity_curve_daily.json", "{JOURNAL_NAME}")


def names():
    return CARRIERS
''',
    })
    doc = measure(root)
    assert _row(doc, "spa_core/monitoring/catalogue.py") is None
    assert doc["names_only"] == ["spa_core/monitoring/catalogue.py"]
    assert doc["road_counts"][ROAD_NAMES_ONLY] == 1


# ──────────────────── ось дороги: помощник ЧУЖОГО модуля ──────────────────────

def test_imported_reader_function_is_a_helper_road(tmp_path):
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def read_journal(data):
    return (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
''',
        "spa_core/monitoring/downstream.py": '''
from spa_core.monitoring.watched import read_journal


def measure(data):
    return read_journal(data)
''',
    })
    doc = measure(root)
    row = _row(doc, "spa_core/monitoring/downstream.py")
    assert row is not None and row["road"] == ROAD_HELPER
    assert row["via"] == "spa_core.monitoring.watched"


def test_importing_a_constant_from_a_reader_is_not_a_road(tmp_path):
    """Положительный контроль ИЗМЕРЕННОЙ ВЫДУМАННОЙ находки.

    Правило «ввезено из читателя» давало 42 читателя вместо 19 и называло
    `python_reader_clock_doors` судящим о книге по журналу, которого он не
    касается. Выдуманная находка хуже молчания: настоящую от неё не отличить.
    """
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path
VERSION = "v1"


def read_journal(data):
    return (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
''',
        "spa_core/monitoring/unrelated.py": '''
from spa_core.monitoring.watched import VERSION


def measure():
    return VERSION.upper()
''',
    })
    doc = measure(root)
    assert _row(doc, "spa_core/monitoring/unrelated.py") is None, (
        "ввоз константы объявлен дорогой — перепись выдумывает читателей")


# ───────────────────────────── ось времени ────────────────────────────────────

@pytest.mark.parametrize("body, expected", [
    ('''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{journal}").read_text(encoding="utf-8")
    last = rows[-1]
    return last
''', TENSE_TAIL),
    ('''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{journal}").read_text(encoding="utf-8")
    state = {{}}
    for row in rows:
        state = row
    return state
''', TENSE_LOOP),
    ('''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{journal}").read_text(encoding="utf-8")
    return len(rows)
''', TENSE_HISTORY),
])
def test_tense_is_read_from_the_subject(tmp_path, body, expected):
    """Опора на хвост — вердикт о настоящем; счёт по всем записям — об истории."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": body.format(journal=JOURNAL_NAME),
    })
    row = _row(measure(root), "spa_core/monitoring/watched.py")
    assert row is not None and row["tense"] == expected


def test_untraced_flow_is_the_third_outcome_not_history(tmp_path):
    """Непрослеженный поток — НЕ «вердикт обо всей истории» (инв. #17)."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return 0
''',
    })
    row = _row(measure(root), "spa_core/monitoring/watched.py")
    assert row is not None and row["tense"] == TENSE_UNMEASURED


# ───────────────────────────── ось вопроса ────────────────────────────────────

def test_reader_of_the_standing_book_asks_for_itself(tmp_path):
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    standing = (Path(data) / "current_positions.json").read_text(encoding="utf-8")
    return rows[-1], standing
''',
    })
    row = _row(measure(root), "spa_core/monitoring/watched.py")
    assert row is not None and row["asks"] == ASKS_SELF


def test_probe_that_loads_the_instrument_asks_for_it(tmp_path):
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITH_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return rows[-1]
''',
    })
    doc = measure(root)
    row = _row(doc, "spa_core/monitoring/watched.py")
    assert row is not None and row["asks"] == ASKS_PROBE
    assert doc["probe_asked_modules"] == ["spa_core.monitoring.watched"]
    assert not doc["findings"], "вопрос задан — находки быть не должно"


def test_present_verdict_with_nobody_asking_is_the_finding(tmp_path):
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return rows[-1]
''',
    })
    doc = measure(root)
    row = _row(doc, "spa_core/monitoring/watched.py")
    assert row is not None and row["asks"] == ASKS_NOBODY
    assert [f["file"] for f in doc["findings"]] == [
        "spa_core/monitoring/watched.py"]
    assert verdict(doc) == "present_verdicts_without_the_question"


def test_history_verdict_without_the_question_is_not_a_finding(tmp_path):
    """Вердикт об истории тождества не требует: находкой он быть не может."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return len(rows)
''',
    })
    doc = measure(root)
    assert _row(doc, "spa_core/monitoring/watched.py")["asks"] == ASKS_NOBODY
    assert doc["findings"] == []
    assert verdict(doc) == "every_present_verdict_is_asked"


def test_scope_isolation_keeps_a_neighbour_from_asking_for_you(tmp_path):
    """Положительный контроль ИЗМЕРЕННОГО ЗАНИЖЕНИЯ ответа.

    Поток по дереву целиком объявил помощниками тождества 21 функцию
    `card_acceptance` вместо одной: `path` соседней функции засчитывался этой.
    Здесь книгу читает функция, которой проба не зовёт, — и вопрос обязан
    остаться НЕзаданным.
    """
    acceptance = '''
import importlib

STANDING_BOOK_FILE = "current_positions.json"
WATCHED_MODULE = "spa_core.monitoring.watched"


def _watched_module():
    return importlib.import_module(WATCHED_MODULE)


def unrelated_neighbour(data):
    path = data / STANDING_BOOK_FILE
    return path.read_text(encoding="utf-8")


def _probe_watched(arg, *, data_dir=None):
    return _watched_module().measure()
'''
    root = _tree(tmp_path, acceptance=acceptance, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return rows[-1]
''',
    })
    doc = measure(root)
    assert doc["identity_helpers"] == ["unrelated_neighbour"]
    assert doc["probe_asked_modules"] == [], (
        "сосед, которого проба не зовёт, засчитан спрашивающим — ответ занижен")
    assert _row(doc, "spa_core/monitoring/watched.py")["asks"] == ASKS_NOBODY


# ─────────────────────── третий исход и отказы ────────────────────────────────

def test_standing_book_name_is_read_not_copied(tmp_path):
    """Константы нет ⇒ отказ. Вторая копия имени разошлась бы молча (ADR-220)."""
    root = _tree(tmp_path, acceptance="X = 1\n", modules={})
    with pytest.raises(Unmeasured) as exc:
        measure(root)
    assert jsi.STANDING_BOOK_CONST in str(exc.value)


def test_missing_acceptance_source_refuses(tmp_path):
    root = tmp_path / "repo"
    (root / "spa_core").mkdir(parents=True)
    with pytest.raises(Unmeasured):
        measure(root)


def test_unparsed_file_is_named_and_reddens(tmp_path, capsys):
    """Неразобранный исходник — находка с причиной, а не тишина."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return len(rows)
''',
        "spa_core/monitoring/broken.py": "def (:\n",
    })
    doc = measure(root)
    assert [u["file"] for u in doc["unparsed"]] == [
        "spa_core/monitoring/broken.py"]
    assert doc["unparsed"][0]["reason"]
    assert main(["--repo-root", str(root)]) == 2
    assert "НЕ РАЗОБРАНО" in capsys.readouterr().out


def test_empty_population_is_not_reported_as_clean():
    """Ноль исходов на пустом населении — НЕ «все спрашивают» (урок pyflakes)."""
    plain = format_report({"population": 0, "journal": JOURNAL_NAME})
    assert plain.startswith("НЕ ИЗМЕРЕНО")
    assert "это НЕ «все спрашивают»" in plain


# ─────────────────────────── код возврата и отчёт ─────────────────────────────

def test_exit_code_separates_clean_finding_and_unmeasured(tmp_path, capsys):
    clean = _tree(tmp_path / "a", acceptance=ACCEPTANCE_WITH_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return rows[-1]
''',
    })
    assert main(["--repo-root", str(clean)]) == 0
    found = _tree(tmp_path / "b", acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return rows[-1]
''',
    })
    assert main(["--repo-root", str(found)]) == 1
    missing = tmp_path / "c"
    (missing / "spa_core").mkdir(parents=True)
    assert main(["--repo-root", str(missing)]) == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


def test_report_states_the_answer_of_the_order(tmp_path):
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return rows[-1]
''',
    })
    plain = format_report(measure(root))
    assert "ОТВЕТ заказа: у 1 из 1" in plain
    assert "current_positions.json" in plain
    assert "ADVISORY" in plain


def test_instrument_only_reads(tmp_path):
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    return (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
''',
    })
    before = sorted(p.name for p in (root / "spa_core" / "monitoring").iterdir())
    doc = measure(root)
    assert doc["applied"] is False
    assert sorted(p.name for p in (root / "spa_core" / "monitoring").iterdir()) == before


# ──────────────────────── сверка с живым деревом ──────────────────────────────

def test_live_tree_identity_helper_is_the_one_card_acceptance_declares():
    """Ответ на живом дереве: помощник тождества ОДИН, и его зовут три пробы.

    `card_acceptance._standing_book_liveness` объявляет в докстроке «вопрос
    задают уже три пробы §49». Перепись обязана прийти к тому же числу своим
    путём — иначе она меряет не то, о чём говорит.
    """
    doc = measure()
    assert doc["identity_helpers"] == ["_standing_book_liveness"]
    assert len(doc["probe_asked_modules"]) == 3
    assert doc["population"] > len(doc["probe_asked_modules"])


# ─────────────────────────── проводка: ВЫЗОВ, не ввоз ─────────────────────────

def test_office_step_calls_the_census_by_call_form_not_by_name():
    """Читатель есть, и он ЗОВЁТ прибор.

    Ввоз вызовом не является (урок ADR-547: зелёный храповик непроведённых
    скриптов гасится одним `import` ради чужого правила). Поэтому зов ищется
    РАЗБОРОМ ФОРМЫ ВЫЗОВА, а не именем в тексте: имя поймало бы собственный
    комментарий этой секции (урок ADR-414).

    Артефакта и `slo_hours` у прибора нет НАМЕРЕННО — род вердикта есть
    свойство кода, у него нет такта и срока годности (та же развилка, что у
    ADR-559), — поэтому ступень моста здесь не проверяется: её не должно быть.
    """
    import ast as _ast

    office = (pathlib.Path(jsi.__file__).resolve().parents[2]
              / "scripts" / "consume_office_reports.py")
    tree = _ast.parse(office.read_text(encoding="utf-8"))

    imported: dict[str, str] = {}
    for node in _ast.walk(tree):
        if (isinstance(node, _ast.ImportFrom)
                and node.module == jsi.__name__):
            for alias in node.names:
                imported[alias.asname or alias.name] = alias.name
    assert {"measure", "format_report"} <= set(imported.values()), (
        "шаг 0-офис не ввозит прибор — находку не читает никто")

    local_measure = next(k for k, v in imported.items() if v == "measure")
    local_report = next(k for k, v in imported.items() if v == "format_report")

    called = {n.func.id for n in _ast.walk(tree)
              if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)}
    assert local_measure in called, "прибор ввезён, но НЕ позван — проводка холостая"
    assert local_report in called, "замер взят, но читателю не напечатан"

    #: Замер берётся у СВОЕГО дерева, а не у `--data-dir`-соседа (урок ADR-559).
    for node in _ast.walk(tree):
        if (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name)
                and node.func.id == local_measure):
            assert not node.args and not node.keywords, (
                "офис меряет чужое дерево: предмет — КОД, и у него свой адрес")


def test_census_declares_no_artifact_and_no_slo():
    """Контроль обратной стороны: артефакт прибору НЕ заводится.

    Если бы он появился, у него немедленно возник бы такт и срок годности — и
    сторож свежести начал бы судить о свойстве кода по часам.
    """
    source = pathlib.Path(jsi.__file__).read_text(encoding="utf-8")
    assert "ARTIFACT" not in source
    assert "slo_hours" not in source


# ──────────── формы, которых не было в первых сценах (дыры сцены) ─────────────
#
# Мутационный прогон #2 показал: правило читает больше форм, чем проверяли
# сцены, и выживший мутант почти всегда есть дыра СЦЕНЫ, а не прибора
# (урок #752–#754). Ниже — по контролю на каждую форму.

def _journal_reader(body: str) -> str:
    return body.format(journal=JOURNAL_NAME)


@pytest.mark.parametrize("tail_form", [
    "    last = rows[-1]\n    return last",
    "    last = rows[-1:]\n    return last",
    "    last = max(rows, key=len)\n    return last",
    "    last = min(rows, key=len)\n    return last",
    "    last = rows.pop()\n    return last",
])
def test_every_declared_tail_form_is_read(tmp_path, tail_form):
    """Пять объявленных форм выбора последней записи — каждая обязана читаться."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": _journal_reader('''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{journal}").read_text(encoding="utf-8")
''') + tail_form + "\n",
    })
    row = _row(measure(root), "spa_core/monitoring/watched.py")
    assert row is not None and row["tense"] == TENSE_TAIL


def test_index_minus_two_is_not_a_tail(tmp_path):
    """Отрицательный контроль формы: `[-2]` хвостом НЕ является."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return rows[-2]
''',
    })
    row = _row(measure(root), "spa_core/monitoring/watched.py")
    assert row is not None and row["tense"] == TENSE_HISTORY


@pytest.mark.parametrize("read_attr", ["read_text", "read_bytes", "open"])
def test_every_declared_read_receiver_is_a_road(tmp_path, read_attr):
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    return (Path(data) / "{JOURNAL_NAME}").{read_attr}()
''',
    })
    assert _row(measure(root), "spa_core/monitoring/watched.py") is not None


def test_builtin_open_is_a_road(tmp_path):
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
import os


def measure(data):
    return open(os.path.join(data, "{JOURNAL_NAME}")).read()
''',
    })
    assert _row(measure(root), "spa_core/monitoring/watched.py") is not None


@pytest.mark.parametrize("carrier", [
    '    name = "{journal}"\n    return (Path(data) / name).read_text()',
    '    names = ["{journal}"]\n    for name in names:\n'
    '        return (Path(data) / name).read_text()',
    '    with Path(data) as root:\n'
    '        return (root / "{journal}").read_text()',
    '    name = ""\n    name += "{journal}"\n'
    '    return (Path(data) / name).read_text()',
    '    return [ (Path(data) / n).read_text() for n in ["{journal}"] ]',
])
def test_every_carrier_of_the_value_is_followed(tmp_path, carrier):
    """Присваивание · цикл · `with` · `+=` · включение — все несут значение."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": "from pathlib import Path\n\n\n"
        "def measure(data):\n" + carrier.format(journal=JOURNAL_NAME) + "\n",
    })
    assert _row(measure(root), "spa_core/monitoring/watched.py") is not None, (
        "носитель значения потерян — читатель выпал из населения молча")


def test_tuple_unpacking_binds_every_name(tmp_path):
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    other, name = None, "{JOURNAL_NAME}"
    return (Path(data) / name).read_text(encoding="utf-8")
''',
    })
    assert _row(measure(root), "spa_core/monitoring/watched.py") is not None


@pytest.mark.parametrize("signature", [
    "def read(data, name=JOURNAL):",
    "def read(data, *, name=JOURNAL):",
])
def test_both_kinds_of_parameter_default_are_followed(tmp_path, signature):
    """Позиционное и только-именованное умолчание — обе формы несут имя."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path
JOURNAL = "{JOURNAL_NAME}"


''' + signature + '''
    return (Path(data) / name).read_text(encoding="utf-8")
''',
    })
    assert _row(measure(root), "spa_core/monitoring/watched.py") is not None


def test_helper_is_reached_through_an_attribute_call(tmp_path):
    """`import a.b` + `a.b.read_journal(...)` — дорога той же силы."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def read_journal(data):
    return (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
''',
        "spa_core/monitoring/downstream.py": '''
import spa_core.monitoring.watched as watched


def measure(data):
    return watched.read_journal(data)
''',
    })
    row = _row(measure(root), "spa_core/monitoring/downstream.py")
    assert row is not None and row["road"] == ROAD_HELPER


def test_helper_depth_is_a_declared_limit_not_a_property(tmp_path):
    """Предел глубины ОБЪЯВЛЕН: на 1 цепочка обрывается, на 2 — доходит."""
    modules = {
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def read_journal(data):
    return (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
''',
        "spa_core/monitoring/mid.py": '''
from spa_core.monitoring.watched import read_journal


def relay(data):
    return read_journal(data)
''',
        "spa_core/monitoring/far.py": '''
from spa_core.monitoring.mid import relay


def measure(data):
    return relay(data)
''',
    }
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules=modules)
    assert _row(measure(root, depth=2), "spa_core/monitoring/far.py") is not None
    assert _row(measure(root, depth=1), "spa_core/monitoring/far.py") is None


def test_loader_named_by_a_literal_is_read_too(tmp_path):
    """Прибор, названный в `import_module` ЛИТЕРАЛОМ, а не константой."""
    acceptance = '''
import importlib

STANDING_BOOK_FILE = "current_positions.json"


def _standing_book_liveness(data):
    return (data / STANDING_BOOK_FILE).read_text(encoding="utf-8")


def _probe_watched(arg, *, data_dir=None):
    census = importlib.import_module("spa_core.monitoring.watched")
    return census.measure(), _standing_book_liveness(data_dir)
'''
    root = _tree(tmp_path, acceptance=acceptance, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return rows[-1]
''',
    })
    assert _row(measure(root), "spa_core/monitoring/watched.py")["asks"] == ASKS_PROBE


def test_journal_name_is_an_input_of_the_measure(tmp_path):
    """Имя журнала — ВХОД: тем же прибором меряется соседний журнал (G128 п. 3)."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": '''
from pathlib import Path


def measure(data):
    return (Path(data) / "allocation_rationale_history.jsonl").read_text()
''',
    })
    assert _row(measure(root), "spa_core/monitoring/watched.py") is None
    other = measure(root, journal="allocation_rationale_history.jsonl")
    assert _row(other, "spa_core/monitoring/watched.py") is not None
    assert other["journal"] == "allocation_rationale_history.jsonl"


def test_json_output_carries_the_same_numbers(tmp_path, capsys):
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return rows[-1]
''',
    })
    import json as _json
    assert main(["--repo-root", str(root), "--json"]) == 1
    doc = _json.loads(capsys.readouterr().out)
    assert doc["population"] == 1 and doc["applied"] is False
    assert doc["findings"][0]["file"] == "spa_core/monitoring/watched.py"


def test_accumulator_filled_in_the_loop_is_a_present_verdict(tmp_path):
    """`moves.append(...)` — та же накопленная книга, что и присваивание."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    moves = []
    for row in rows:
        moves.append(row)
    return moves
''',
    })
    row = _row(measure(root), "spa_core/monitoring/watched.py")
    assert row is not None and row["tense"] == TENSE_LOOP


def test_name_read_only_inside_the_loop_is_not_carried(tmp_path):
    """Отрицательный контроль: имя, не пережившее цикл, итогом не является."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    for row in rows:
        seen = row
        print(seen)
    return 0
''',
    })
    row = _row(measure(root), "spa_core/monitoring/watched.py")
    assert row is not None and row["tense"] == TENSE_HISTORY


@pytest.mark.parametrize("rel", [
    "spa_core/tests/test_watched.py",
    "spa_core/monitoring/conftest.py",
])
def test_controls_are_not_instruments(tmp_path, rel):
    """Предмет — приборы, а не их контроли: тесты и `conftest` исключены."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        rel: f'''
from pathlib import Path


def measure(data):
    rows = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return rows[-1]
''',
    })
    doc = measure(root)
    assert _row(doc, rel) is None
    assert rel not in doc["names_only"]


def test_the_flow_runs_to_a_fixed_point_not_one_hop(tmp_path):
    """Цепочка из трёх связываний: один проход потерял бы читателя."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    third = Path(data) / second
    return third.read_text(encoding="utf-8")


first = "{JOURNAL_NAME}"
second = first
''',
    })
    assert _row(measure(root), "spa_core/monitoring/watched.py") is not None, (
        "поток оборван до неподвижной точки — дальний читатель потерян")


def test_unparsable_acceptance_is_the_third_outcome_not_a_crash(tmp_path):
    """Приёмку не разобрать ⇒ НЕ ИЗМЕРЕНО с причиной, а не обвал трассировкой."""
    root = _tree(tmp_path, acceptance="def (:\n", modules={})
    with pytest.raises(Unmeasured) as exc:
        measure(root)
    assert "не разобрана" in str(exc.value)
    assert main(["--repo-root", str(root)]) == 2


# ───────────── загрузчики: свои, чужие, методы и неразобранная дверь ──────────

def test_loader_imported_from_a_neighbour_is_a_road(tmp_path):
    """`from m import _read_json` + `_read_json(d / "trades.json")`.

    Положительный контроль ИЗМЕРЕННОГО промаха: правило, знавшее только СВОИ
    загрузчики, роняло в «поминает имя» `capital_shadow/readiness.py` — читателя,
    который берёт ХВОСТ журнала и судит о настоящем.
    """
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/io.py": '''
def _read_json(path):
    return path.read_text(encoding="utf-8")
''',
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path
from spa_core.monitoring.io import _read_json


def measure(data):
    doc = _read_json(Path(data) / "{JOURNAL_NAME}")
    return doc[-1]
''',
    })
    row = _row(measure(root), "spa_core/monitoring/watched.py")
    assert row is not None, "ввезённый загрузчик дорогой не признан"
    assert row["road"] == ROAD_DIRECT and row["tense"] == TENSE_TAIL


def test_an_imported_name_that_is_not_a_loader_is_not_a_road(tmp_path):
    """Отрицательный контроль к предыдущему: ввоз чего попало дорогой не делает."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/io.py": '''
def label(path):
    return str(path).upper()
''',
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path
from spa_core.monitoring.io import label


def measure(data):
    return label(Path(data) / "{JOURNAL_NAME}")
''',
    })
    assert _row(measure(root), "spa_core/monitoring/watched.py") is None


def test_a_method_of_the_same_class_is_a_loader(tmp_path):
    """`self._read_json(self.data_dir / "trades.json")` — та же дорога."""
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


class Validator:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)

    def _read_json(self, path):
        return path.read_text(encoding="utf-8")

    def measure(self):
        return self._read_json(self.data_dir / "{JOURNAL_NAME}")
''',
    })
    assert _row(measure(root), "spa_core/monitoring/watched.py") is not None


def test_loader_chain_is_followed_to_a_fixed_point(tmp_path):
    """Загрузчик, который сам не читает, а передаёт аргумент дальше.

    `book_digest_and_asof(data_dir, relpath)` диск не трогает — он зовёт
    `_read_json`. Правило глубиной в один шаг объявило бы
    `capital_shadow/reconcile` поминающим имя.
    """
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def _read_json(path):
    return path.read_text(encoding="utf-8")


def digest(data_dir, relpath):
    return _read_json(Path(data_dir) / relpath)


def measure(data):
    return digest(data, "{JOURNAL_NAME}")
''',
    })
    assert _row(measure(root), "spa_core/monitoring/watched.py") is not None


def test_a_door_behind_a_runtime_module_is_the_third_outcome(tmp_path, capsys):
    """`mod._load(d / "trades.json")` — НЕ «не читает», а НЕ ИЗМЕРЕНО.

    Смешать незнание с измеренным отсутствием значило бы спрятать читателя под
    словом «поминает имя» (инв. #17). Третий исход краснит код возврата.
    """
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
import importlib
from pathlib import Path


def measure(data):
    mod = importlib.import_module("spa_core.monitoring.other")
    return mod._load(Path(data) / "{JOURNAL_NAME}")
''',
    })
    doc = measure(root)
    assert _row(doc, "spa_core/monitoring/watched.py") is None
    assert doc["names_only"] == [], "неразобранная дверь спрятана в «не читает»"
    assert doc["unresolved_doors"][0]["file"] == "spa_core/monitoring/watched.py"
    assert doc["unresolved_doors"][0]["doors"] == ["mod._load"]
    assert doc["road_counts"][jsi.ROAD_UNMEASURED] == 1
    assert main(["--repo-root", str(root)]) == 2
    assert "ДВЕРЬ НЕ РАЗОБРАНА" in capsys.readouterr().out


# ───────── мутационный прогон #769: каждая дыра СЦЕНЫ названа по мутанту ──────
#
# Прогон на `/tmp/spa_c769m` дал 183 мутации, 145 убитых и 38 выживших. Каждый
# выживший разобран поимённо (урок: выживший мутант почти всегда есть дыра
# СЦЕНЫ, а не дефект прибора). Тесты ниже закрывают 29 из 38; остальные девять
# НАЗВАНЫ эквивалентными в журнале цикла, и ни один не погашен молча.


def test_declared_helper_depth_is_the_default_of_the_measure(tmp_path):
    """Мутант `HELPER_DEPTH = 3` выжил: предел ОБЪЯВЛЕН, но не ЗАКРЕПЛЁН.

    Соседний тест предел проверяет, передавая `depth=` аргументом, — то есть
    ровно в обход умолчания. Умолчание же и есть то число, которым прибор
    мерит живое дерево, и ответ заказа от него зависит прямо.
    """
    modules = {
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def read_journal(data):
    return (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
''',
        "spa_core/monitoring/mid.py": '''
from spa_core.monitoring.watched import read_journal


def relay(data):
    return read_journal(data)
''',
        "spa_core/monitoring/far.py": '''
from spa_core.monitoring.mid import relay


def forward(data):
    return relay(data)
''',
        "spa_core/monitoring/farther.py": '''
from spa_core.monitoring.far import forward


def measure(data):
    return forward(data)
''',
    }
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules=modules)
    doc = measure(root)
    assert jsi.HELPER_DEPTH == 2, "объявленный предел дороги через помощника"
    assert doc["depth"] == 2, "предел в докладе — это тот же объявленный предел"
    assert _row(doc, "spa_core/monitoring/far.py") is not None, "второй шаг входит"
    assert _row(doc, "spa_core/monitoring/farther.py") is None, (
        "третий шаг в предел НЕ входит — иначе объявленное число ничего не значит")


def test_module_level_flow_runs_to_a_fixed_point(tmp_path):
    """Мутант «один проход» на УРОВНЕ МОДУЛЯ выжил: цепочка шла по порядку.

    Соседний тест строит связывания в порядке объявления, и одного прохода ему
    хватает; обратный порядок требует трёх. Порядок строк в чужом файле — не
    свойство, на которое перепись имеет право опираться.
    """
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    return (Path(data) / third).read_text(encoding="utf-8")


third = second
second = first
first = "{JOURNAL_NAME}"
''',
    })
    assert _row(measure(root), "spa_core/monitoring/watched.py") is not None, (
        "поток уровня модуля оборван на первом проходе — читатель потерян")


def test_loader_chain_fixed_point_needs_a_second_pass(tmp_path):
    """Мутант «один проход» у реестра загрузчиков выжил по той же причине.

    `digest` объявлен ДО `_read_json`, которого он зовёт: один проход объявил бы
    загрузчиком только второго, и настоящий читатель журнала упал бы в
    «поминает имя».
    """
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def digest(data_dir, relpath):
    return _read_json(Path(data_dir) / relpath)


def _read_json(path):
    return path.read_text(encoding="utf-8")


def measure(data):
    return digest(data, "{JOURNAL_NAME}")
''',
    })
    assert _row(measure(root), "spa_core/monitoring/watched.py") is not None, (
        "цепочка загрузчиков посчитана одним проходом — порядок объявления решил")


def test_module_name_computed_at_runtime_is_not_a_loader(tmp_path):
    """Мутант у разбора `import_module(<имя>)` выжил: все сцены давали КОНСТАНТУ.

    Имя модуля, вычисленное в рантайме, прибором НЕ опознаётся — и это сказано
    вслух в «НЕ ДОКЛАДЫВАЕТ». Сцены же до сих пор давали только константу, и
    вторая ветка разбора не исполнялась ни разу.
    """
    acceptance = '''
import importlib

STANDING_BOOK_FILE = "current_positions.json"


def _standing_book_liveness(data):
    return (data / STANDING_BOOK_FILE).read_text(encoding="utf-8")


def _probe_watched(arg, *, data_dir=None, module_name="x"):
    census = importlib.import_module(module_name)
    book = _standing_book_liveness(data_dir)
    return census.measure(), book
'''
    root = _tree(tmp_path, acceptance=acceptance, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    moves = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return moves[-1]
''',
    })
    doc = measure(root)
    assert doc["identity_helpers"] == ["_standing_book_liveness"], (
        "помощник тождества ИЗМЕРЕН — он читает стоящую книгу")
    assert doc["probe_asked_modules"] == [], (
        "имя прибора вычислено в рантайме ⇒ «за него спрашивают» НЕ измерено")
    assert _row(doc, "spa_core/monitoring/watched.py")["asks"] == ASKS_NOBODY


def test_a_direct_reader_is_never_also_a_helper(tmp_path):
    """Выжили два мутанта у строки «уже прямой ⇒ пропустить».

    Прямой читатель, который ВДОБАВОК зовёт ввезённого читателя, под мутантом
    попадал и в помощники: дорога оставалась прямой, а в доклад приезжал
    `← соседний модуль` и глубина 1 — то есть читателю сообщали путь, которым
    он журнал не брал.
    """
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def read_journal(data):
    return (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
''',
        "spa_core/monitoring/both.py": f'''
from pathlib import Path

from spa_core.monitoring.watched import read_journal


def measure(data):
    own = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return read_journal(data), own
''',
    })
    row = _row(measure(root), "spa_core/monitoring/both.py")
    assert row is not None and row["road"] == ROAD_DIRECT
    assert row["via"] is None and row["through"] is None, (
        "прямому читателю приписана дорога через помощника")
    assert row["depth"] == 0, "у прямой дороги глубины помощника нет"


def test_counts_are_exact_and_start_from_zero(tmp_path):
    """Выжили шесть мутантов счётчиков: начальный ноль и шаг на единицу.

    Ни один тест не сверял сами числа осей — только состав строк. Сдвиг
    начального значения на единицу врёт в КАЖДОЙ строке доклада сразу, и это
    ровно тот класс, против которого написан инв. #17: число есть замер.
    """
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    moves = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return moves[-1]
''',
        "spa_core/monitoring/namer.py": f'''
TRADES = "{JOURNAL_NAME}"
''',
    })
    doc = measure(root)
    assert doc["road_counts"] == {ROAD_DIRECT: 1, ROAD_HELPER: 0,
                                 ROAD_NAMES_ONLY: 1, jsi.ROAD_UNMEASURED: 0}
    assert doc["tense_counts"] == {TENSE_TAIL: 1, jsi.TENSE_LOOP: 0,
                                  TENSE_HISTORY: 0, TENSE_UNMEASURED: 0}
    assert doc["asks_counts"] == {ASKS_SELF: 0, ASKS_PROBE: 0, ASKS_NOBODY: 1}
    assert doc["population"] == 1 and doc["present_population"] == 1


def test_measure_declares_itself_measured(tmp_path):
    """Мутант `"measured": False` выжил: поле не читал ни один контроль.

    Поле и есть отличие «замер состоялся» от третьего исхода (`Unmeasured`), и
    молчаливое `False` сделало бы успешный замер неотличимым от отказа.
    """
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    return (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
''',
    })
    assert measure(root)["measured"] is True


def test_seed_matching_reads_the_called_name_exactly(tmp_path):
    """Выжили три мутанта сверки имени вызова — ось ВРЕМЕНИ их и ловит.

    Соседний тест формы `import m as x` проверяет только, что дорога найдена;
    семена же решают ось времени, и при порванной сверке их либо нет вовсе
    (⇒ третий исход), либо в них попадает ЧУЖОЙ вызов (`log.fetch()`), чей
    хвост выдаётся за хвост журнала.
    """
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def read_journal(data):
    return (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
''',
        "spa_core/monitoring/downstream.py": '''
import spa_core.monitoring.watched as watched


def measure(data):
    moves = watched.read_journal(data)
    return len(moves)


def unrelated(log):
    rows = log.fetch()
    return rows[-1]
''',
    })
    row = _row(measure(root), "spa_core/monitoring/downstream.py")
    assert row is not None and row["road"] == ROAD_HELPER
    assert row["through"] == "watched.read_journal"
    assert row["tense"] == TENSE_HISTORY, (
        "вердикт о всей истории: хвост берёт ЧУЖОЙ вызов, не журнал")


def test_a_call_on_a_complex_target_names_nothing(tmp_path):
    """Мутант «любой вызов зовёт это имя» выжил: сцен со сложным вызовом не было.

    Под ним функция, которая читающего имени не зовёт вовсе (`o.a.b()`), входила
    в рубеж следующего шага — и модуль, ввёзший ЕЁ, объявлялся читателем журнала.
    Выдуманная находка хуже молчания: её нечем отличить от настоящей.
    """
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def read_journal(data):
    return (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
''',
        "spa_core/monitoring/mid.py": '''
from spa_core.monitoring.watched import read_journal


def relay(data):
    return read_journal(data)


def unrelated(o):
    return o.a.b()
''',
        "spa_core/monitoring/far.py": '''
from spa_core.monitoring.mid import unrelated


def measure(o):
    return unrelated(o)
''',
    })
    doc = measure(root)
    assert _row(doc, "spa_core/monitoring/mid.py") is not None, "настоящий шаг цел"
    assert _row(doc, "spa_core/monitoring/far.py") is None, (
        "модуль, ввёзший НЕчитающую функцию, объявлен читателем журнала")


def _reader_module(index: int) -> str:
    return f'''
from pathlib import Path


def measure_{index}(data):
    moves = (Path(data) / "{JOURNAL_NAME}").read_text(encoding="utf-8")
    return moves[-1]
'''


def test_report_lists_twelve_findings_and_names_the_remainder(tmp_path):
    """Выжили четыре мутанта предела перечня находок в докладе.

    Доклад — ЕДИНСТВЕННЫЙ читатель этой переписи (артефакта у неё нет
    намеренно), поэтому предел перечня и остаток «ещё N» суть его числа, а не
    украшение: сдвиг любого из них врёт читателю молча.
    """
    modules = {f"spa_core/monitoring/w{i}.py": _reader_module(i)
               for i in range(13)}
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules=modules)
    doc = measure(root)
    assert len(doc["findings"]) == 13
    report = format_report(doc)
    listed = [ln for ln in report.splitlines()
              if ln.strip().startswith(f"[{ASKS_NOBODY}]")]
    assert len(listed) == 12, "предел перечня находок в докладе"
    assert "ещё 1 находок(и) того же вида" in report, (
        "остаток перечня назван числом, а не умолчанием")


def test_report_caps_names_only_at_four_and_marks_the_tail(tmp_path):
    """Выжили три мутанта предела перечня «имя стои́т, а чтения нет»."""
    modules = {f"spa_core/monitoring/n{i}.py": f'TRADES = "{JOURNAL_NAME}"\n'
               for i in range(5)}
    #: Читатель нужен, чтобы доклад пошёл обычным путём: на пустом населении
    #: он честно отвечает «НЕ ИЗМЕРЕНО» и перечня не печатает вовсе.
    modules["spa_core/monitoring/watched.py"] = _reader_module(0)
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules=modules)
    doc = measure(root)
    assert len(doc["names_only"]) == 5
    line = next(ln for ln in format_report(doc).splitlines()
                if "имя журнала стои́т" in ln)
    assert line.count("spa_core/monitoring/n") == 4, "предел перечня — четыре"
    assert "…" in line, "хвост перечня назван, а не отброшен молча"


def test_report_caps_unresolved_doors_at_four_in_both_paths(tmp_path):
    """Выжили два мутанта предела перечня неразобранных дверей.

    Предел стои́т ДВАЖДЫ — на обычном пути и на пути пустого населения, — и
    второй до сих пор не исполнялся ни одним контролем.
    """
    door = f'''
import importlib
from pathlib import Path


def measure(data):
    mod = importlib.import_module("spa_core.monitoring.other")
    return mod._load(Path(data) / "{JOURNAL_NAME}")
'''
    doors = {f"spa_core/monitoring/d{i}.py": door for i in range(5)}

    #: Путь пустого населения: читателей нет вовсе, а двери есть.
    empty = _tree(tmp_path / "empty", acceptance=ACCEPTANCE_WITHOUT_QUESTION,
                  modules=dict(doors))
    doc_empty = measure(empty)
    assert doc_empty["population"] == 0 and len(doc_empty["unresolved_doors"]) == 5
    plain = format_report(doc_empty)
    assert "НЕ ИЗМЕРЕНО" in plain
    assert plain.count("spa_core/monitoring/d") == 4, "предел перечня дверей"

    #: Обычный путь: читатель есть, двери те же.
    mixed = dict(doors)
    mixed["spa_core/monitoring/watched.py"] = _reader_module(0)
    full = _tree(tmp_path / "full", acceptance=ACCEPTANCE_WITHOUT_QUESTION,
                 modules=mixed)
    line = next(ln for ln in format_report(measure(full)).splitlines()
                if "ДВЕРЬ НЕ РАЗОБРАНА" in ln)
    assert line.count("spa_core/monitoring/d") == 4, "предел перечня дверей"


def test_report_caps_unparsed_at_three(tmp_path):
    """Мутант предела перечня НЕ РАЗОБРАННЫХ файлов выжил."""
    modules = {f"spa_core/monitoring/b{i}.py": "def (:\n" for i in range(4)}
    modules["spa_core/monitoring/watched.py"] = _reader_module(0)
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules=modules)
    doc = measure(root)
    assert len(doc["unparsed"]) == 4
    line = next(ln for ln in format_report(doc).splitlines()
                if "НЕ РАЗОБРАНО" in ln)
    assert line.count("spa_core/monitoring/b") == 3, "предел перечня — три"


def test_report_says_a_dash_when_no_identity_helper_was_measured(tmp_path):
    """Мутант у «пусто ⇒ тире» выжил: пустой перечень печатался пустотой.

    Пустая строка на месте перечня читается как обрыв доклада, а не как
    измеренный ноль помощников (инв. #17).
    """
    reader = {"spa_core/monitoring/watched.py": _reader_module(0)}
    without = _tree(tmp_path / "without", acceptance=ACCEPTANCE_WITHOUT_QUESTION,
                    modules=dict(reader))
    doc = measure(without)
    assert doc["identity_helpers"] == []
    line = next(ln for ln in format_report(doc).splitlines()
                if "помощники тождества ИЗМЕРЕНЫ" in ln)
    assert "(0): —" in line, "измеренный ноль помощников назван тире"

    with_helper = _tree(tmp_path / "with", acceptance=ACCEPTANCE_WITH_QUESTION,
                        modules=dict(reader))
    line = next(ln for ln in format_report(measure(with_helper)).splitlines()
                if "помощники тождества ИЗМЕРЕНЫ" in ln)
    assert "_standing_book_liveness" in line and "—" not in line


def test_refusal_json_says_not_measured(tmp_path, capsys):
    """Мутант `"measured": True` в ОТКАЗНОМ JSON выжил.

    Отказ, назвавший себя замером, и есть «не измерено, выданное за ответ» —
    тот самый дефект, против которого прибор написан.
    """
    import json as _json

    root = tmp_path / "repo"
    (root / "spa_core" / "monitoring").mkdir(parents=True)
    assert main(["--repo-root", str(root), "--json"]) == 2
    doc = _json.loads(capsys.readouterr().out)
    assert doc["measured"] is False, "отказ объявил себя замером"
    assert doc["reason"]


def test_scope_flow_runs_to_a_fixed_point(tmp_path):
    """Мутант «один проход» у потока ОДНОЙ ОБЛАСТИ выжил и у #770.

    Первая правка закрыла неподвижную точку уровня МОДУЛЯ и реестра
    загрузчиков, а третья копия того же цикла живёт в потоке области: там
    связывания идут в порядке обхода, и обход заходит в тело цикла ПОСЛЕ
    верхних строк. Значение, переложенное внутри цикла, требует второго
    прохода — и ровно его мутант и отнимал, роняя настоящего читателя журнала
    в «поминает имя».
    """
    root = _tree(tmp_path, acceptance=ACCEPTANCE_WITHOUT_QUESTION, modules={
        "spa_core/monitoring/watched.py": f'''
from pathlib import Path


def measure(data):
    path = Path(data) / "{JOURNAL_NAME}"
    carrier = None
    for _ in range(2):
        later = carrier
        carrier = path
    return later.read_text(encoding="utf-8")
''',
    })
    assert _row(measure(root), "spa_core/monitoring/watched.py") is not None, (
        "поток области оборван на первом проходе — читатель потерян")
