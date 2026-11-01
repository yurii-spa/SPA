"""Четвёртая ось пина доставки: а эта строка реестра — ЗАГОЛОВОК? (ADR-889)

**Класс, который воспроизводит каждый тест этого файла.** ADR-838 поставил предел на
колонку «Заголовок» реестра решений (200 символов), ADR-840 убрал состояние (675
толстых строк → 0) и дал прибор, который берёт заголовок из `H1` файла решения
одним вызовом `python3 scripts/adr_number.py titles --write`. Сторож у класса ЕСТЬ —
`spa_core/tests/test_adr_index_titles.py`. Чего не было — ВОПРОСА В МОМЕНТ ДОСТАВКИ.

**Цена измерена на живой истории** (замер 2026-11-01, цикл #1004, зеркало `origin`,
39 коммитов `docs/decisions/INDEX.md` с 28.10): из **38** строк, добавленных в реестр
после ADR-840, **ЧЕТЫРЕ** были толстыми В МОМЕНТ ДОБАВЛЕНИЯ — `ADR-853` (205),
`ADR-854` (365), `ADR-886` (201), `ADR-887` (283). Каждая уехала на `main` МОЛЧА и
красила там `test_adr_index_titles` до прихода следующего цикла.

Положительный контроль идёт **ДОСЛОВНО по байтам** реестра из коммита `fa5bfcbd9`
(blob ``f404cfbd6dfe0134592f9165f26b1e779b21b876``, 200 052 байта) — того самого, где
толстыми стояли ОДНОВРЕМЕННО `ADR-886` и `ADR-887`, а не по выдуманному «похожему»
файлу (`.claude/rules/deployment.md`, § «проверка сторожа сторожей»).

Три существующих сторожа доставки отвечают на этой аварии ВЕРНО и мимо:

* слепок байтов (ADR-774) — «сверено»: он пинует байты ТОГО ЖЕ файла и сверил
  толстую строку с толстой же;
* гейт разбора (ADR-886) — молчит ВЕРНО: `INDEX.md` не объявлял себя Python;
* интерлок номеров ADR — спрашивает об УНИКАЛЬНОСТИ номера и о наличии строки в
  реестре, а о ДЛИНЕ ячейки не знает ничего.

Литеральных дат и литеральных pid в файле нет: предмет — содержимое байтов, и ни
календарь, ни номера процессов к нему отношения не имеют. Сеть не трогается ни одним
тестом: все отказы этой семьи стоят ДО сети.

Запуск: python3 -m pytest spa_core/tests/test_delivery_adr_title_gate.py -v
"""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Дословные байты аварии: `docs/decisions/INDEX.md` из коммита `fa5bfcbd9`.
INCIDENT_BLOB = "f404cfbd6dfe0134592f9165f26b1e779b21b876"

#: Номера, стоявшие в том реестре толстыми, и их измеренные длины. Проверяются
#: ДОСЛОВНО: отказ без номера и длины отправил бы читателя искать строку глазами
#: среди 738 строк реестра.
INCIDENT_FAT = {"886": 201, "887": 283}

#: Шапка объявленной формы. Нужна сценам, собираемым руками: `register_title_rows`
#: опознаёт строку ПО ФОРМЕ, и без шапки реестр всё равно разбирается, — но сцена
#: без шапки не была бы реестром, а предмет здесь именно реестр.
HEAD = ("# ADR INDEX\n\n"
        "| ADR | Заголовок | Статус | Файл |\n"
        "|---|---|---|---|\n")


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
    mod = _load("_title_gate_ptg", "push_to_github.py")
    yield mod
    mod.reset_delivery_pin()


@pytest.fixture(scope="module")
def incident_bytes() -> bytes:
    """Дословная копия толстого реестра — из ИСТОРИИ репозитория.

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


def _register(tmp_path: Path, text: str) -> Path:
    """Одноразовое дерево, несущее реестр по КАНОНИЧЕСКОМУ пути.

    Путь — часть предмета: гейт задаёт вопрос ТОЛЬКО `docs/decisions/INDEX.md`,
    и сцена, положившая те же байты в другое место, мерила бы другой вопрос.
    """
    p = tmp_path / "docs" / "decisions" / "INDEX.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


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
# Проверка, никогда не видевшая настоящей поломки, — украшение. Здесь поломка
# не изображена, а ВЗЯТА из истории доставки.
# ═════════════════════════════════════════════════════════════════════════════
def test_the_incident_register_is_refused_and_every_fat_row_is_named(
        ptg, tmp_path, incident_bytes):
    """Дословный `fa5bfcbd9`: отказ называет ОБА номера, их длины и предел."""
    assert ptg.git_blob_sha(incident_bytes) == INCIDENT_BLOB, (
        "взяты НЕ байты аварии — положительный контроль мерил бы не тот предмет")
    target = _register(tmp_path, incident_bytes.decode("utf-8"))
    ptg.pin_delivery_bytes([str(target)])

    with pytest.raises(ptg.DeliveredAdrTitleIsFat) as exc:
        ptg.enforce_delivery_adr_titles([str(target)])

    msg = str(exc.value)
    for key, chars in INCIDENT_FAT.items():
        assert f"ADR-{key}" in msg, (
            f"отказ не назвал ADR-{key} — читатель пошёл бы искать строку "
            f"глазами среди 738 строк реестра")
        assert str(chars) in msg, (
            f"отказ не назвал ДЛИНУ ячейки ADR-{key} ({chars}) — без числа "
            f"непонятно, насколько строка вне предела")
    assert "titles --write" in msg, (
        "отказ не назвал выход. Сторож, не назвавший команду починки, учит "
        "обходить себя, а не чинить предмет")


def test_the_incident_verdicts_name_both_rows_and_the_measured_limit(
        ptg, tmp_path, incident_bytes):
    """Вердикт — ЗАМЕР, а не слово: номера, длины, номера строк и предел."""
    target = _register(tmp_path, incident_bytes.decode("utf-8"))
    ptg.pin_delivery_bytes([str(target)])
    with pytest.raises(ptg.DeliveredAdrTitleIsFat):
        ptg.enforce_delivery_adr_titles([str(target)])

    verdicts = ptg._ADR_TITLE_VERDICTS
    assert len(verdicts) == 1 and verdicts[0]["state"] == "fat", verdicts
    assert verdicts[0]["limit"] == 200, (
        "предел вердикта разошёлся с объявленным — двигать его можно ТОЛЬКО "
        "вниз и ТОЛЬКО тем же коммитом, что литерал здесь (инв. #16)")
    measured = {f["key"]: f["chars"] for f in verdicts[0]["fat"]}
    assert measured == INCIDENT_FAT, (
        f"замер аварии разошёлся: {measured} против {INCIDENT_FAT} — либо "
        f"разбор колонки сменился, либо взят не тот блоб")
    assert all(f["row"] > 0 for f in verdicts[0]["fat"]), (
        "вердикт не несёт номера строки — отказ без МЕСТА неполон")


def test_the_live_register_passes_the_gate(ptg, tmp_path):
    """Обратная сторона: на ЖИВОМ реестре гейт молчит. Это и есть состояние.

    Без этой половины отказы были бы неотличимы от сторожа, который краснеет
    всегда, и единственным способом доставить реестр стал бы флаг обхода.
    """
    live = (ROOT / "docs" / "decisions" / "INDEX.md").read_text(encoding="utf-8")
    target = _register(tmp_path, live)
    ptg.pin_delivery_bytes([str(target)])
    verdicts = ptg.enforce_delivery_adr_titles([str(target)])
    assert len(verdicts) == 1, verdicts
    assert verdicts[0]["state"] == "within_limit", (
        f"живой реестр не проходит свой же гейт: {verdicts[0]} — позови "
        f"`python3 scripts/adr_number.py titles --write`")
    assert verdicts[0]["rows"] > 500, (
        f"в живом реестре измерено всего {verdicts[0]['rows']} строк — столько "
        f"не бывает, значит разбор формы сломан и «толстых нет» ничего не значит")


# ═════════════════════════════════════════════════════════════════════════════
# B. ТРИ ИСХОДА РАЗЛИЧИМЫ (инв. #17), и каждое звено порвано ОТДЕЛЬНО
# ═════════════════════════════════════════════════════════════════════════════
def test_a_row_exactly_at_the_limit_passes_and_one_over_it_does_not(
        ptg, tmp_path):
    """Граница ВКЛЮЧИТЕЛЬНА, и обе её стороны проверены на одной сцене.

    Односторонняя проверка пропустила бы предел, съехавший на символ, — и
    `ADR-886` (201 при пределе 200) именно таким и был.
    """
    at = _register(tmp_path / "at", HEAD + f"| ADR-920 | {'я' * 200} | "
                                           f"Accepted | [x](ADR-920-x.md) |\n")
    ptg.pin_delivery_bytes([str(at)])
    assert ptg.enforce_delivery_adr_titles([str(at)])[0]["state"] == "within_limit"
    ptg.reset_delivery_pin()

    over = _register(tmp_path / "over", HEAD + f"| ADR-921 | {'я' * 201} | "
                                              f"Accepted | [x](ADR-921-x.md) |\n")
    ptg.pin_delivery_bytes([str(over)])
    with pytest.raises(ptg.DeliveredAdrTitleIsFat):
        ptg.enforce_delivery_adr_titles([str(over)])


def test_an_escaped_pipe_is_not_allowed_to_under_report_the_length(
        ptg, tmp_path):
    """АВАРИЯ ADR-840 ДОСЛОВНО: наивный разбор отвечал КОРОЧЕ ячейки.

    `\\|` внутри ячейки markdown считает литеральной чёрточкой, а наивный
    `split("|")` — разделителем: у `ADR-831` он давал 163 символа против 2 089
    канонических, то есть строка «проходила» предел, не будучи в нём. Своей
    копии разбора у гейта нет намеренно — иначе он пускал бы через предел ровно
    те строки, из-за которых предел и понадобился.
    """
    tail = "хвост пересказа, " * 20
    row = (f"| ADR-922 | начало \\| {tail} | Accepted | [x](ADR-922-x.md) |")
    naive = [c.strip() for c in row.strip().strip("|").split("|")][1]
    assert len(naive) <= 200, (
        "сцена не воспроизводит аварию: наивный разбор уже не занижает длину")

    target = _register(tmp_path, HEAD + row + "\n")
    ptg.pin_delivery_bytes([str(target)])
    with pytest.raises(ptg.DeliveredAdrTitleIsFat) as exc:
        ptg.enforce_delivery_adr_titles([str(target)])
    assert "ADR-922" in str(exc.value), (
        "гейт пропустил строку, которую наивный разбор считает короткой — "
        "значит он разбирает колонку САМ, а не канонической дверью ADR-840")


def test_a_register_without_a_single_declared_row_is_unmeasured(ptg, tmp_path):
    """Ни одной строки в форме ⇒ НЕ ИЗМЕРЕНО с причиной, а не «толстых нет».

    Fail-CLOSED: неизвестно, какая ячейка является заголовком, поэтому «предел
    держится» было бы утверждением о замере, которого не было.
    """
    target = _register(tmp_path, "# ADR INDEX\n\nпроза без таблицы\n")
    ptg.pin_delivery_bytes([str(target)])
    verdicts = ptg.enforce_delivery_adr_titles([str(target)])
    assert verdicts[0]["state"] == "unmeasured", verdicts
    assert "НЕ ИЗМЕРЕНА" in verdicts[0]["reason"], verdicts[0]["reason"]


def test_bytes_that_are_not_utf8_are_unmeasured_not_clean(ptg, tmp_path):
    """Байты не декодируются ⇒ третий исход, а не «прошло»."""
    p = tmp_path / "docs" / "decisions" / "INDEX.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"| ADR-923 | \xff\xfe | Accepted | [x](x.md) |\n")
    ptg.pin_delivery_bytes([str(p)])
    verdicts = ptg.enforce_delivery_adr_titles([str(p)])
    assert verdicts[0]["state"] == "unmeasured", verdicts
    assert "UTF-8" in verdicts[0]["reason"], verdicts[0]["reason"]


def test_a_vanished_register_is_unmeasured_with_a_named_reason(ptg, tmp_path):
    """Байты не прочитаны ⇒ причина НАЗВАНА. Пустота совпала бы с «чисто»."""
    gone = tmp_path / "docs" / "decisions" / "INDEX.md"
    gone.parent.mkdir(parents=True, exist_ok=True)
    gone.write_text(HEAD, encoding="utf-8")
    ptg.pin_delivery_bytes([str(gone)])
    gone.unlink()
    verdicts = ptg.enforce_delivery_adr_titles([str(gone)])
    assert verdicts[0]["state"] == "unmeasured", verdicts
    assert "байты не прочитаны" in verdicts[0]["reason"], verdicts[0]["reason"]


def test_a_missing_parser_is_unmeasured_and_not_a_silent_pass(
        ptg, tmp_path, monkeypatch, incident_bytes):
    """Прибора разбора нет ⇒ НЕ ИЗМЕРЕНО, даже если реестр ТОЛСТЫЙ.

    Это самое опасное место класса: fail-OPEN здесь тише красного теста, потому
    что вердикт «чисто» выглядит как ответ. Сцена даёт гейту НАСТОЯЩУЮ аварию и
    отнимает прибор — вердикт обязан сказать «не измерено», а не промолчать.
    """
    target = _register(tmp_path, incident_bytes.decode("utf-8"))
    ptg.pin_delivery_bytes([str(target)])
    monkeypatch.setattr(ptg, "_register_parser",
                        lambda runner_file=None: (None, "прибор отнят сценой"))
    verdicts = ptg.enforce_delivery_adr_titles([str(target)])
    assert verdicts[0]["state"] == "unmeasured", verdicts
    assert verdicts[0]["reason"] == "прибор отнят сценой"


def test_the_parser_comes_from_the_tree_of_the_running_cli(ptg, tmp_path):
    """`runner_file` берёт прибор рядом с ЗАПУЩЕННЫМ CLI, а не с модулем.

    Тот же приём и тот же довод, что у `enforce_adr_numbers`: batch-CLI обязан
    мерить СВОЁ дерево. Сцена — пустое дерево: прибора в нём нет, и гейт обязан
    это НАЗВАТЬ, а не взять прибор соседа.
    """
    mod, why = ptg._register_parser(str(tmp_path / "push_to_github.py"))
    assert mod is None and why and "не ввезён" in why, (why, mod)
    mod2, why2 = ptg._register_parser(str(ROOT / "push_to_github.py"))
    assert mod2 is not None and why2 is None, why2
    assert mod2.TITLE_MAX_CHARS == 200


# ═════════════════════════════════════════════════════════════════════════════
# C. ВОПРОС ЗАДАЁТСЯ ТОЛЬКО РЕЕСТРУ, И «НЕ ЗВАН» ≠ «НЕЧЕГО СУДИТЬ»
# ═════════════════════════════════════════════════════════════════════════════
def test_a_foreign_markdown_is_not_asked_the_question(ptg, tmp_path):
    """Чужой markdown — «не спрашивали», а не «прошёл».

    Колонка «Заголовок» есть свойство ЭТОЙ таблицы; спросить его у любого
    markdown значило бы выдумать колонку там, где её нет, и число «сверено»
    росло бы от молчания соседей по набору.
    """
    other = tmp_path / "docs" / "journal" / "2026-W44.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text(HEAD + f"| ADR-924 | {'я' * 400} | Accepted | [x](x.md) |\n",
                     encoding="utf-8")
    ptg.pin_delivery_bytes([str(other)])
    verdicts = ptg.enforce_delivery_adr_titles([str(other)])
    assert verdicts == [], verdicts
    assert "реестра в наборе нет" in ptg.delivery_adr_title_summary()


def test_not_called_and_nothing_to_judge_are_different_lines(ptg, tmp_path):
    """Пустой перечень — ДВА состояния, и слить их значит соврать читателю.

    Поправка цикла #1001 к ADR-886 дословно: пуш из двух `.md` печатал «гейт не
    зван НИ РАЗУ», хотя гейт был зван и судить ему было нечего.
    """
    assert "не зван НИ РАЗУ" in ptg.delivery_adr_title_summary()
    other = tmp_path / "readme.md"
    other.write_text("текст\n", encoding="utf-8")
    ptg.pin_delivery_bytes([str(other)])
    ptg.enforce_delivery_adr_titles([str(other)])
    assert "реестра в наборе нет" in ptg.delivery_adr_title_summary()


def test_the_summary_distinguishes_all_three_outcomes(ptg, tmp_path,
                                                      incident_bytes):
    """Три итоговые строки РАЗНЫЕ — иначе «не измерено» неотличимо от «сверено»."""
    said = {}

    clean = _register(tmp_path / "clean", HEAD + "| ADR-925 | Короткий | "
                                                 "Accepted | [x](ADR-925-x.md) |\n")
    ptg.pin_delivery_bytes([str(clean)])
    ptg.enforce_delivery_adr_titles([str(clean)])
    said["within_limit"] = ptg.delivery_adr_title_summary()
    ptg.reset_delivery_pin()

    fat = _register(tmp_path / "fat", incident_bytes.decode("utf-8"))
    ptg.pin_delivery_bytes([str(fat)])
    with pytest.raises(ptg.DeliveredAdrTitleIsFat):
        ptg.enforce_delivery_adr_titles([str(fat)])
    said["fat"] = ptg.delivery_adr_title_summary()
    ptg.reset_delivery_pin()

    prose = _register(tmp_path / "prose", "проза без таблицы\n")
    ptg.pin_delivery_bytes([str(prose)])
    ptg.enforce_delivery_adr_titles([str(prose)])
    said["unmeasured"] = ptg.delivery_adr_title_summary()

    assert len(set(said.values())) == 3, (
        f"три исхода слиплись в одной строке итога: {said} — «не измерено» "
        f"стало неотличимо от «сверено», то есть вернулся fail-OPEN")

    # РАЗЛИЧИМОСТЬ ПО РОДУ, а не по числу — дыра, найденная мутацией №13 своего же
    # прибора: со снятой веткой «НЕ ИЗМЕРЕНО» итог проваливался в ветку «в пределе»
    # и выходил строкой «в пределе ? символов все 0 строк(и)». Три строки оставались
    # РАЗНЫМИ (у них разные числа), и проверка выше была ЗЕЛЕНА при живом fail-OPEN:
    # читатель видел «в пределе» там, где не измерено ничего.
    assert "НЕ ИЗМЕРЕНО" in said["unmeasured"], said["unmeasured"]
    assert "ТОЛСТЫХ" in said["fat"], said["fat"]
    assert "в пределе" in said["within_limit"], said["within_limit"]
    assert "НЕ ИЗМЕРЕНО" not in said["within_limit"], (
        f"итог «в пределе» говорит о неизмеренном: {said['within_limit']}")


# ═════════════════════════════════════════════════════════════════════════════
# D. ОСОЗНАННЫЙ ОБХОД ПЕЧАТАЕТСЯ, А НЕ МОЛЧИТ
# ═════════════════════════════════════════════════════════════════════════════
def test_the_conscious_bypass_names_the_finding_and_does_not_stop_delivery(
        ptg, tmp_path, capsys, incident_bytes):
    """`allow=True` не молчит: находка НАЗВАНА, доставка продолжается."""
    target = _register(tmp_path, incident_bytes.decode("utf-8"))
    ptg.pin_delivery_bytes([str(target)])
    verdicts = ptg.enforce_delivery_adr_titles([str(target)], allow=True)
    out = capsys.readouterr().out
    assert verdicts[0]["state"] == "fat"
    assert "--allow-fat-adr-title" in out, (
        "обход не напечатан — молчащий обход есть fail-OPEN, а не решение")
    for key in INCIDENT_FAT:
        assert f"ADR-{key}" in out, f"обход не назвал ADR-{key}"


# ═════════════════════════════════════════════════════════════════════════════
# E. ПРОВОДКА: ДВЕ ДВЕРИ, ОДНА РЕАЛИЗАЦИЯ, НАЗВАННЫЙ ПОРЯДОК
#
# Класс, измеренный ADR-ом про интерлок номеров: блок жил в ОДНОЙ двери, а
# вторая молча везла находку. Поэтому проверяется не «есть ли функция», а
# «зовут ли её ОБА CLI и в том же порядке».
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("rel", ["push_to_github.py", "push_to_github_batch.py"])
def test_both_delivery_doors_call_the_gate_after_the_pin(rel):
    """Гейт зван в `main()` обеих дверей, и ПОСЛЕ пина байтов.

    Порядок не вкусовой: гейт берёт байты дверью `read_delivery_bytes`, которая
    сверяет их со слепком. Позови его ДО пина — и он судил бы содержимое, про
    которое неизвестно, то ли это, что уедет (предмет ADR-774).
    """
    source = (ROOT / rel).read_text(encoding="utf-8")
    calls = calls_in(source, "main")
    for need in ("pin_delivery_bytes", "enforce_delivery_adr_titles"):
        assert need in calls, (
            f"{rel}: `main()` не зовёт `{need}` — гейт без вызывающего либо "
            f"вторая дверь доставки пропускает класс целиком")
    assert (calls.index("pin_delivery_bytes")
            < calls.index("enforce_delivery_adr_titles")), (
        f"{rel}: гейт колонки стоит ДО пина — он судил бы байты, про которые "
        f"неизвестно, те ли это, что уедут")


def test_the_batch_door_reuses_the_implementation_and_keeps_no_copy():
    """У batch-CLI нет СВОЕЙ копии гейта: имя только ре-экспортировано.

    Две копии означали бы, что одна дверь отказывает, а вторая молча везёт
    толстую строку — дословный класс интерлока номеров ADR-145.
    """
    source = (ROOT / "push_to_github_batch.py").read_text(encoding="utf-8")
    assert "enforce_delivery_adr_titles = _root_push.enforce_delivery_adr_titles" \
        in source, "batch-CLI не ре-экспортирует гейт из канонического модуля"
    assert "def enforce_delivery_adr_titles" not in source, (
        "у batch-CLI завелась СВОЯ копия гейта — две копии расходятся, и одна "
        "дверь начинает везти то, что вторая отклоняет")


def test_the_exit_code_does_not_collide_with_a_neighbouring_interlock():
    """Свой код отказа. Совпади он с соседом — читатель лечил бы не ту болезнь."""
    ptg = _load("_title_gate_codes", "push_to_github.py")
    codes = {
        "FAT_ADR_TITLE_EXIT": ptg.FAT_ADR_TITLE_EXIT,
        "NOT_PYTHON_EXIT": ptg.NOT_PYTHON_EXIT,
        "BYTES_DRIFT_EXIT": ptg.BYTES_DRIFT_EXIT,
        "DELIVERY_TREE_EXIT": ptg.DELIVERY_TREE_EXIT,
        "MUTATION_WINDOW_EXIT": ptg.MUTATION_WINDOW_EXIT,
        "ADR_INTERLOCK_EXIT": ptg.ADR_INTERLOCK_EXIT,
        "CHANGE_EVIDENCE_EXIT": ptg.CHANGE_EVIDENCE_EXIT,
        "PUBLICATION_GATE_EXIT": ptg.PUBLICATION_GATE_EXIT,
        "OWNER_CHOICE_INTERLOCK_EXIT": ptg.OWNER_CHOICE_INTERLOCK_EXIT,
    }
    assert len(set(codes.values())) == len(codes), (
        f"код отказа совпал с кодом соседнего интерлока: {codes}")
    assert ptg.FAT_ADR_TITLE_EXIT == 16, (
        "код отказа разошёлся с объявленным в ADR-889 (16) — он печатается в "
        "отказе и читается вызывающими")


def test_the_canonical_register_path_is_the_one_the_guard_uses():
    """Путь реестра у гейта и у сторожа колонки — ОДИН.

    Разойдись они — гейт охранял бы файл, которого сторож не знает, и обратно.
    """
    ptg = _load("_title_gate_path", "push_to_github.py")
    assert ptg.ADR_REGISTER_REL == "docs/decisions/INDEX.md"
    assert (ROOT / ptg.ADR_REGISTER_REL).is_file(), (
        f"канонического реестра по пути {ptg.ADR_REGISTER_REL} нет — гейт "
        f"охранял бы путь, которого в дереве не существует")
