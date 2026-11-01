"""Третья ось пина доставки: а эти байты вообще Python? (ADR-886)

**Авария, которую воспроизводит каждый тест этого файла** (цикл #1000, ADR-885).
Коммит `f4612d8e9` увёз на `main` `spa_core/monitoring/card_acceptance.py`,
СЛОМАННЫЙ СИНТАКСИЧЕСКИ — `unterminated string literal` на строке 10658. Файл
не импортируется ВОВСЕ, то есть вместе с ним на `main` умер весь реестр проб
приёмки. Байты этой копии лежат в истории репозитория под blob
``b65010a27dca7ee59713c2e9defc976cf9513c8b``, и положительный контроль здесь
идёт ДОСЛОВНО по ним, а не по выдуманному «похожему» файлу.

Три существующих сторожа доставки ответили ВЕРНО и мимо:

* окно мутационного прибора (`--window-check`, ADR-772) — «ОКНА НЕТ», код 0:
  запись `.mutation_window/window.json` есть только у `delta_mutation_run.py`,
  а дерево переписал ТЕСТ (`test_green_by_construction_census.py`
  инструментирует исходники НА МЕСТЕ, перепись ADR-543), и записи у него нет
  ПО ПОСТРОЕНИЮ;
* слепок байтов (ADR-774) — «сверено у 28 чтений»: он пинует байты ТОГО ЖЕ
  файла и сверил испорченные с испорченными;
* дерево доставки названо (ADR-796) — названо ВЕРНО: испорчено было именно оно.

Вопроса «компилируется ли то, что уезжает» не задавал НИКТО.

Литеральных дат и литеральных pid в файле нет: предмет — содержимое байтов, и
ни календарь, ни номера процессов к нему отношения не имеют. Сеть не трогается
ни одним тестом: все отказы этой семьи стоят ДО сети.

Запуск: python3 -m pytest spa_core/tests/test_delivery_syntax_gate.py -v
"""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PUSHER = ROOT / "push_to_github.py"
BATCH_CLI = ROOT / "push_to_github_batch.py"

#: Дословные байты аварии: `card_acceptance.py` из коммита `f4612d8e9`.
INCIDENT_BLOB = "b65010a27dca7ee59713c2e9defc976cf9513c8b"

#: Место, которое интерпретатор назвал в той копии. Проверяется дословно: отказ
#: без МЕСТА отправил бы читателя искать строку глазами в 10 тысячах строк.
INCIDENT_LINE = 10658


class Unmeasured(AssertionError):
    """НЕ ИЗМЕРЕНО с названной причиной — третий исход, а не «чисто»."""


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ptg():
    mod = _load("_syntax_ptg", "push_to_github.py")
    yield mod
    mod.reset_delivery_pin()


@pytest.fixture(scope="module")
def incident_bytes() -> bytes:
    """Дословная копия испорченного файла — из ИСТОРИИ репозитория.

    Предпосылка здесь — НАСТОЯЩАЯ история доставки, и выдумать её тест не может
    (`.claude/rules/deployment.md`, § «GIT-ОКРУЖЕНИЕ в тестах»: глубина клона —
    вход ХАРНЕССА, `fetch-depth: 0`). Блоба нет ⇒ ГРОМКИЙ отказ с названной
    причиной, а НЕ `pytest.skip`: скип сделал бы «не измерено» неотличимым от
    «прошло» — дословный урок цикла #465.
    """
    try:
        out = subprocess.run(["git", "cat-file", "blob", INCIDENT_BLOB],
                             cwd=ROOT, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Unmeasured(
            f"НЕ ИЗМЕРЕНО: git не ответил ({type(exc).__name__}: {exc}) — "
            f"положительный контроль мерить не на чем") from exc
    if out.returncode != 0:
        raise Unmeasured(
            f"НЕ ИЗМЕРЕНО: блоба {INCIDENT_BLOB[:12]} нет в объектной базе "
            f"{ROOT} (код {out.returncode}: "
            f"{out.stderr.decode('utf-8', 'replace').strip()}). Это предпосылка "
            f"ХАРНЕССА, а не предмет теста: джоба обязана объявить "
            f"`fetch-depth: 0`")
    return out.stdout


def _functions(source: str) -> dict:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise Unmeasured(f"НЕ ИЗМЕРЕНО: CLI не разобран ({exc})") from exc
    return {n.name: n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def calls_in(source: str, func_name: str) -> list:
    """Имена функций, ВЫЗЫВАЕМЫХ внутри `func_name`, в порядке появления."""
    funcs = _functions(source)
    if func_name not in funcs:
        raise Unmeasured(f"НЕ ИЗМЕРЕНО: функции `{func_name}` нет")
    return [c.func.id for c in ast.walk(funcs[func_name])
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]


# ═════════════════════════════════════════════════════════════════════════════
# A. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: ДОСЛОВНЫЕ БАЙТЫ АВАРИИ
#
# Проверка, никогда не видевшая настоящей поломки, — украшение
# (`.claude/rules/deployment.md`). Здесь поломка не изображена, а ВЗЯТА.
# ═════════════════════════════════════════════════════════════════════════════
def test_the_incident_bytes_are_refused_and_the_place_is_named(
        ptg, tmp_path, incident_bytes):
    """Дословный `f4612d8e9`: гейт отказывает и называет файл, строку, причину."""
    target = tmp_path / "card_acceptance.py"
    target.write_bytes(incident_bytes)
    assert ptg.git_blob_sha(incident_bytes) == INCIDENT_BLOB, (
        "взяты НЕ байты аварии — положительный контроль мерил бы не тот предмет")
    ptg.pin_delivery_bytes([str(target)])

    with pytest.raises(ptg.DeliveredBytesAreNotPython) as exc:
        ptg.enforce_delivery_compiles([str(target)])

    msg = str(exc.value)
    assert "card_acceptance.py" in msg, (
        "отказ обязан НАЗВАТЬ файл: без имени читатель не знает, кого искать")
    assert str(INCIDENT_LINE) in msg, (
        f"отказ не называет МЕСТО (строка {INCIDENT_LINE}) — читателю остаётся "
        f"искать её глазами в десяти тысячах строк")
    assert "unterminated string literal" in msg, (
        "отказ не называет ПРИЧИНУ, которую назвал интерпретатор")


def test_the_incident_bytes_are_refused_by_the_real_cli_with_its_own_code(
        tmp_path, incident_bytes):
    """Тот же замер НА НАСТОЯЩЕМ CLI: код возврата **15**, и сеть не тронута.

    Это не дубль предыдущего теста: тот мерит ГЕЙТ, этот — ПРОВОДКУ гейта в
    `main()` вместе с отображением исключения в код возврата. Утверждение
    приёмки карточки — про ПУШЕР («пушер ОТКАЗЫВАЕТ ... со своим кодом
    возврата»), а не про функцию, и измерить его можно только так.
    """
    target = tmp_path / "card_acceptance.py"
    target.write_bytes(incident_bytes)

    out = subprocess.run(
        [sys.executable, str(PUSHER), "--dry-run", "--files", str(target),
         "--message", "проба: дословные байты аварии f4612d8e9"],
        cwd=ROOT, capture_output=True, timeout=600)

    assert out.returncode == 15, (
        f"настоящий CLI вышел {out.returncode}, а не 15 — отказ либо не "
        f"случился, либо приехал под чужим именем. stderr: "
        f"{out.stderr.decode('utf-8', 'replace')[-2000:]}")
    text = (out.stdout + out.stderr).decode("utf-8", "replace")
    assert INCIDENT_BLOB[:12] in text, (
        "слепок не назвал блоб аварии — значит судились НЕ те байты")
    assert "не является Python" in text


def test_valid_python_is_not_refused_by_this_axis_on_the_real_cli(tmp_path):
    """Обратная сторона НА ТОМ ЖЕ CLI: исправный файл эту ось проходит.

    Без этого теста предыдущий был бы зелен и на пушере, который отказывает
    ВСЕГДА, — то есть мерил бы не тот предмет.

    Сцена намеренно та же (каталог вне рабочего дерева), и потому ниже по стеку
    отказывает СОСЕДНИЙ гейт — окно мутационного прибора, своим кодом 10
    («дерево файла не определяется», ADR-789). Это и есть предмет проверки:
    третья ось сказала «сверено» и НЕ подменила вердикт соседа. Равенство с 15
    было бы ложью в опасную сторону, равенство с 0 — требованием собрать
    полноценное рабочее дерево ради чужого вопроса.
    """
    target = tmp_path / "ok.py"
    target.write_text("x = 1\n", encoding="utf-8")

    out = subprocess.run(
        [sys.executable, str(PUSHER), "--dry-run", "--files", str(target),
         "--message", "проба: исправный файл"],
        cwd=ROOT, capture_output=True, timeout=600)

    text = (out.stdout + out.stderr).decode("utf-8", "replace")
    assert out.returncode != 15, (
        f"исправный Python отклонён третьей осью — ложный отказ: {text[-2000:]}")
    assert "разбор уезжающего Python: сверено 1" in text, (
        f"ось промолчала о том, что спросила и получила ответ: {text[-2000:]}")


# ═════════════════════════════════════════════════════════════════════════════
# B. ТРИ ИСХОДА РАЗЛИЧИМЫ (инв. #17)
# ═════════════════════════════════════════════════════════════════════════════
def test_unreadable_bytes_are_the_third_outcome_not_a_pass(ptg, tmp_path):
    """Байты не прочитаны ⇒ `unmeasured` с причиной, а не «компилируется».

    Отказывать здесь было бы неверно: про отсутствующий файл внятнее отказывает
    `resolve_files` («Файл не найден»), и два отказа на одно наблюдение спорили
    бы именами. А МОЛЧАТЬ нельзя — тогда «не измерено» стало бы неотличимо от
    «сверено», то есть вернулся бы fail-OPEN, который тише красного теста.
    """
    missing = tmp_path / "vanished.py"
    missing.write_text("x = 1\n", encoding="utf-8")
    ptg.pin_delivery_bytes([str(missing)])
    missing.unlink()

    verdicts = ptg.enforce_delivery_compiles([str(missing)])

    assert [v["state"] for v in verdicts] == ["unmeasured"], verdicts
    assert "не прочитаны" in verdicts[0]["reason"]
    assert "НЕ ИЗМЕРЕНО" in ptg.delivery_syntax_summary(), (
        "итог оси молчит о том, что ничего не измерил")
    assert "сверено" not in ptg.delivery_syntax_summary()


def test_the_three_outcomes_do_not_share_a_summary_line(ptg, tmp_path):
    """Итог различает ВСЕ три исхода, а не два из трёх.

    Мерится ДИФФЕРЕНЦИАЛЬНО: три сцены, отличающиеся РОВНО одним наблюдением,
    обязаны дать три РАЗНЫХ строки. «В строке есть слово» прошло бы и у меры,
    которая печатает одно и то же.
    """
    said = {}
    for label, text in (("compiles", "x = 1\n"), ("not_python", "def f(:\n")):
        ptg.reset_delivery_pin()
        p = tmp_path / f"{label}.py"
        p.write_text(text, encoding="utf-8")
        ptg.pin_delivery_bytes([str(p)])
        try:
            ptg.enforce_delivery_compiles([str(p)])
        except ptg.DeliveredBytesAreNotPython:
            pass
        said[label] = ptg.delivery_syntax_summary()

    ptg.reset_delivery_pin()
    gone = tmp_path / "gone.py"
    gone.write_text("x = 1\n", encoding="utf-8")
    ptg.pin_delivery_bytes([str(gone)])
    gone.unlink()
    ptg.enforce_delivery_compiles([str(gone)])
    said["unmeasured"] = ptg.delivery_syntax_summary()

    assert len(set(said.values())) == 3, (
        f"исходы слиплись в одной строке итога: {said}")


def test_the_gate_was_never_called_is_said_out_loud(ptg):
    """Гейт не зван ⇒ итог говорит это, а не «сверено 0».

    Библиотечный вызов `batch_push` минуя CLI гейта не проходит — как и все
    соседние гейты этой семьи. Цена односторонняя и обязана быть ВИДНА: «сверено
    0 файлов» читалось бы как «спросили и всё чисто».
    """
    assert "не зван" in ptg.delivery_syntax_summary()


def test_not_called_and_nothing_to_judge_are_two_different_lines(ptg, tmp_path):
    """«Гейта не звали» и «звали, а `*.py` в наборе не было» — РАЗНЫЕ исходы.

    ПОПРАВКА того же цикла #1001, найденная чтением СВОЕГО ЖЕ вывода: второй
    пуш цикла везло два `.md`, гейт был ЗВАН, судить ему было нечего — и вывод
    сказал «гейт не зван НИ РАЗУ». Два разных состояния под одной строкой есть
    ровно тот класс, против которого написан ADR-886: читатель увидел бы «не
    зван» у работающего гейта и пошёл бы искать несуществующую поломку
    проводки.

    Мерится ДИФФЕРЕНЦИАЛЬНО — две сцены, отличающиеся РОВНО тем, звали гейт или
    нет; «в строке есть слово» прошло бы и у меры, которая печатает одно и то же.
    """
    not_called = ptg.delivery_syntax_summary()

    only_md = tmp_path / "note.md"
    only_md.write_text("текст\n", encoding="utf-8")
    ptg.pin_delivery_bytes([str(only_md)])
    ptg.enforce_delivery_compiles([str(only_md)])
    nothing_to_judge = ptg.delivery_syntax_summary()

    assert not_called != nothing_to_judge, (
        f"оба состояния печатаются одной строкой: {not_called!r}")
    assert "не зван" in not_called and "нет ни одного" in nothing_to_judge


def test_the_reset_returns_the_axis_to_never_asked(ptg, tmp_path):
    """После `reset_delivery_pin()` третья ось снова говорит «не зван».

    НАСТОЯЩАЯ ДЫРА, найденная выжившим мутантом №16 спецификации ADR-886: сам
    гейт чистит свой перечень на входе, поэтому забытая чистка в сбросе не
    видна НИ ОДНОМУ прогону, который гейт зовёт. Видна она ровно там, где гейта
    не звали: сброшенный пин с вердиктами прошлой сцены выдал бы «сверено» за
    наблюдение, которого в этом пуше не было, — то есть третий исход инв. #17
    снова стал бы неотличим от первого.
    """
    p = tmp_path / "a.py"
    p.write_text("a = 1\n", encoding="utf-8")
    ptg.pin_delivery_bytes([str(p)])
    ptg.enforce_delivery_compiles([str(p)])
    assert "сверено 1" in ptg.delivery_syntax_summary()

    ptg.reset_delivery_pin()

    assert "не зван" in ptg.delivery_syntax_summary(), (
        f"после сброса ось показывает вердикты ПРОШЛОЙ сцены: "
        f"{ptg.delivery_syntax_summary()}")


def test_a_non_python_extension_is_not_counted_as_verified(ptg, tmp_path):
    """Не-`*.py` этой осью НЕ судится и в «сверено» НЕ попадает.

    Вопрос задаётся тому, кто ОБЪЯВИЛ себя Python. Сломанный JSON или Astro
    здесь не судится намеренно: у каждого языка свой разборщик, и выдумывать их
    значило бы завести меру, отвечающую «я не умею» под видом «чисто». Но и
    считать такой файл «сверенным» нельзя — это было бы ровно то же «чисто» из
    незнания.
    """
    broken_json = tmp_path / "state.json"
    broken_json.write_text("{ не json", encoding="utf-8")
    ptg.pin_delivery_bytes([str(broken_json)])

    verdicts = ptg.enforce_delivery_compiles([str(broken_json)])

    assert verdicts == [], verdicts
    said = ptg.delivery_syntax_summary()
    assert "сверено" not in said, f"файл без вопроса учтён как измеренный: {said}"
    assert "нет ни одного" in said, (
        f"итог не говорит, что судить было НЕЧЕГО: {said}")


def test_a_null_byte_source_is_refused_under_the_gate_own_name(ptg, tmp_path):
    """Нулевой байт в исходнике отклоняется ИМЕНЕМ ГЕЙТА, а не падением пушера.

    ЗАМЕР (python 3.13.11): такой исходник приходит `SyntaxError`-ом («source
    code string cannot contain null bytes»), а НЕ `ValueError`. Первая редакция
    этого теста утверждала обратное; ложную посылку нашёл выживший мутант №9
    спецификации ADR-886 — снятие `ValueError` из перечня не меняет здесь НИ
    ОДНОГО наблюдаемого исхода, то есть мутант ЭКВИВАЛЕНТЕН, а дыры покрытия
    нет. Тест остаётся, потому что мерит он не ветку, а ИСХОД: имя отказа и
    есть то, что читает следующая сессия.
    """
    p = tmp_path / "nul.py"
    p.write_bytes(b"x = 1\n\x00y = 2\n")
    ptg.pin_delivery_bytes([str(p)])

    with pytest.raises(ptg.DeliveredBytesAreNotPython) as exc:
        ptg.enforce_delivery_compiles([str(p)])
    assert "nul.py" in str(exc.value)


# ═════════════════════════════════════════════════════════════════════════════
# C. БАЙТЫ БЕРУТСЯ ДВЕРЬЮ, И ОТКАЗ ДВЕРИ СОХРАНЯЕТ СВОЁ ИМЯ
# ═════════════════════════════════════════════════════════════════════════════
def test_the_gate_judges_the_bytes_that_will_actually_leave(ptg, tmp_path):
    """Подмена после пина ⇒ отказывает ДВЕРЬ БАЙТОВ, своим именем и кодом.

    Своего `read_bytes` у гейта нет намеренно: читай он сам — и он судил бы
    ОДНО чтение, а уехало бы ДРУГОЕ, то есть вернулся бы предмет ADR-774 на
    новом месте. Проверяется это тем, что подмена даёт `DeliveryBytesDrifted`,
    а НЕ `DeliveredBytesAreNotPython`: подменить имя отказа значило бы потерять
    ответ ADR-774.
    """
    p = tmp_path / "a.py"
    p.write_text("a = 1\n", encoding="utf-8")
    ptg.pin_delivery_bytes([str(p)])
    p.write_text("def broken(:\n", encoding="utf-8")        # и сломан, и подменён

    with pytest.raises(ptg.DeliveryBytesDrifted) as exc:
        ptg.enforce_delivery_compiles([str(p)])
    assert not isinstance(exc.value, ptg.DeliveredBytesAreNotPython), (
        "отказ двери байтов приехал под именем третьей оси — ответ ADR-774 "
        "потерян")


def test_the_gate_has_no_raw_read_of_the_delivery_bytes():
    """У гейта нет СВОЕГО чтения диска (AST, не подстрока)."""
    funcs = _functions(PUSHER.read_text(encoding="utf-8"))
    name = "enforce_delivery_compiles"
    if name not in funcs:
        raise Unmeasured(f"НЕ ИЗМЕРЕНО: функции `{name}` в пушере нет")
    raw = [c for c in ast.walk(funcs[name])
           if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
           and c.func.attr == "read_bytes"]
    assert not raw, (
        f"гейт читает байты сам ({len(raw)} раз) — значит судит ОДНО чтение, "
        f"а уедет ДРУГОЕ")
    assert "read_delivery_bytes" in calls_in(
        PUSHER.read_text(encoding="utf-8"), name), (
        "гейт не зовёт дверь байтов — слепок до него не доходит")


# ═════════════════════════════════════════════════════════════════════════════
# D. ПРОВОДКА: ОБЕ ДВЕРИ, ПОРЯДОК, ОДНА РЕАЛИЗАЦИЯ
# ═════════════════════════════════════════════════════════════════════════════
def test_both_delivery_doors_ask_the_question_right_after_the_pin():
    """Гейт зовётся в `main()` ОБОИХ CLI, после пина и ДО всех прочих гейтов."""
    for label, path in (("push_to_github.py", PUSHER),
                        ("push_to_github_batch.py", BATCH_CLI)):
        calls = calls_in(path.read_text(encoding="utf-8"), "main")
        assert "enforce_delivery_compiles" in calls, (
            f"{label}: `main()` не ЗОВЁТ гейт разбора — дверь без него "
            f"доставит то, что первая отклоняет (урок номеров ADR: 26.08 "
            f"через вторую дверь уехал второй ADR-145)")
        assert "pin_delivery_bytes" in calls and \
            "enforce_delivery_toolchain" in calls, (
            f"{label}: перечень гейтов изменился — порядок мерить не от чего")
        assert calls.index("pin_delivery_bytes") < \
            calls.index("enforce_delivery_compiles"), (
            f"{label}: гейт разбора стоит ДО пина — он судил бы байты, которые "
            f"слепком ещё не закреплены")
        assert calls.index("enforce_delivery_compiles") < \
            calls.index("enforce_delivery_toolchain"), (
            f"{label}: гейт разбора стоит ПОСЛЕ гейтов о СМЫСЛЕ уезжающего, а "
            f"у неразбираемых байтов смысла нет вовсе")


def test_the_order_measure_goes_red_on_a_swap():
    """Отрицательный контроль порядка: мера видит перестановку."""
    source = ("def main():\n"
              "    pin_delivery_bytes(all_files)\n"
              "    enforce_delivery_toolchain(all_files)\n"
              "    enforce_delivery_compiles(all_files)\n")
    calls = calls_in(source, "main")
    assert calls.index("enforce_delivery_compiles") > \
        calls.index("enforce_delivery_toolchain"), (
        "мера порядка не различает перестановку — значит она ничего не мерит")


def test_the_batch_door_has_no_second_implementation():
    """У второй двери нет СВОЕЙ реализации — только ре-экспорт канона.

    Две копии означали бы, что одна дверь отказывает, а вторая молча везёт
    файл, который не разбирается интерпретатором. Авария 01.11 приехала через
    ПЕРВУЮ дверь — и ровно поэтому вторая не вправе её пропустить.
    """
    cli = _load("_syntax_cli_identity", "push_to_github_batch.py")
    try:
        for name in ("enforce_delivery_compiles", "delivery_syntax_summary",
                     "DeliveredBytesAreNotPython"):
            assert getattr(cli, name) is getattr(cli._root_push, name), (
                f"`{name}` у batch-CLI — НЕ объект канонической копии")
        assert cli.NOT_PYTHON_EXIT == cli._root_push.NOT_PYTHON_EXIT
        own = _functions(BATCH_CLI.read_text(encoding="utf-8"))
        for name in ("enforce_delivery_compiles", "delivery_syntax_summary"):
            assert name not in own, (
                f"batch-CLI определяет СВОЙ `{name}` — два вердикта на один "
                f"вопрос")
        assert "_SYNTAX_VERDICTS" not in BATCH_CLI.read_text(encoding="utf-8"), (
            "batch-CLI объявляет свой store — одна дверь считала бы в один "
            "список, а печатала бы другой")
    finally:
        cli._root_push.reset_delivery_pin()


def test_refusal_carries_its_own_exit_code(ptg):
    """Свой код возврата: общий `1` читался бы как «пушер сломался»."""
    taken = {ptg.NOT_PYTHON_EXIT, ptg.BYTES_DRIFT_EXIT, ptg.DELIVERY_TREE_EXIT,
             ptg.ADR_INTERLOCK_EXIT, ptg.OWNER_CHOICE_INTERLOCK_EXIT,
             ptg.CHANGE_EVIDENCE_EXIT, ptg.MUTATION_WINDOW_EXIT,
             ptg.PUBLICATION_GATE_UNMEASURED_EXIT,
             ptg.OWNER_CHOICE_UNMEASURED_EXIT}
    assert len(taken) == 9, (
        f"код третьей оси совпал с кодом соседнего интерлока — различить "
        f"отказы станет нечем: {sorted(taken)}")
    assert ptg.NOT_PYTHON_EXIT not in (0, 1, 2, 3, 4, 5, 6)


# ═════════════════════════════════════════════════════════════════════════════
# E. ОБХОД ОБЪЯВЛЕН И ПЕЧАТАЕТСЯ
# ═════════════════════════════════════════════════════════════════════════════
def test_the_declared_bypass_names_itself_out_loud(ptg, tmp_path, capsys):
    """`--allow-not-python` не отказывает, но МОЛЧА тоже не пропускает."""
    p = tmp_path / "broken.py"
    p.write_text("def f(:\n", encoding="utf-8")
    ptg.pin_delivery_bytes([str(p)])

    verdicts = ptg.enforce_delivery_compiles([str(p)], allow=True)

    assert [v["state"] for v in verdicts] == ["not_python"]
    out = capsys.readouterr().out
    assert "--allow-not-python" in out, (
        "обход сработал МОЛЧА — необъявленный обход хуже отсутствующего гейта")
    assert "НЕ РАЗБИРАЕТСЯ" in out
