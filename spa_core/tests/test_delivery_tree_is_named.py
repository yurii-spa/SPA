"""Дерево, из которого пушер читает байты, обязано быть НАЗВАНО (ADR-796).

**Авария, которую воспроизводит каждый тест** — замер цикла #918 на живом
пушере (`--dry-run`). Относительный путь разрешался от константы
`PROJECT_ROOT`, то есть от ПРОД-дерева, а не от дерева, которое сессия собрала
и протестировала, и у этого умолчания были ДВЕ разные судьбы:

| путь существует в прод-дереве? | что делал пушер | видно ли это |
|---|---|---|
| нет | `FileNotFoundError` → `FAIL … Файл не найден` | **громко** |
| **да** | читал БАЙТЫ ПРОД-ФАЙЛА и везёл их как твои | **никак** |

Из шестнадцати объявленных относительными путями файлов семь в прод-дереве
отсутствовали и честно покраснели, а восьмой — `docs/STATE.md` — там ЕСТЬ, и
слепок байтов записал про него blob ПРОД-копии `0fcb1332`, тогда как дерево
цикла несло `b29ddbf4` (именно он и уехал потом на origin). Прод-копия
`STATE.md` дрейфует от origin ⇒ доставка относительным путём увезла бы на
`main` локальный дрейф прод-дерева вместо работы цикла — МОЛЧА и с кодом
возврата 0. Спасло ровно то, что семь путей из шестнадцати не существовали.

Защита от подмены байтов (ADR-774) этого не ловит ПО ПОСТРОЕНИЮ: она пинует
байты того же неверного файла, и сверка их ПОДТВЕРЖДАЕТ.

Сеть НЕ ТРОГАЕТСЯ НИ ОДНИМ тестом: отказ двери наступает внутри пина, то есть
до любого обращения к GitHub, а сцены CLI останавливаются на нём же. Литеральных
дат и литеральных pid в файле нет вовсе — предмет здесь содержимое файлов, а не
календарь и не номера процессов.

Запуск: python3 -m pytest spa_core/tests/test_delivery_tree_is_named.py -v
"""
from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PUSHER = ROOT / "push_to_github.py"
BATCH_CLI = ROOT / "push_to_github_batch.py"

#: Путь, на котором авария и случилась. Берётся не ради красоты: именно этот
#: файл есть В ОБОИХ деревьях всегда, поэтому «тихая» ветка умолчания на нём и
#: срабатывает.
REL = "docs/STATE.md"


class Unmeasured(AssertionError):
    """НЕ ИЗМЕРЕНО с названной причиной — третий исход, а не «чисто»."""


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _tree(base: Path, name: str) -> Path:
    """Одноразовое РАБОЧЕЕ ДЕРЕВО, а не просто каталог (ADR-789).

    `git init -b main` объявлен ЯВНО: `init.defaultBranch` — свойство ХОСТА
    (Apple Git даёт `main`, git на `ubuntu-latest` — `master`), и фикстура,
    промолчавшая об имени, зелена здесь и красна в CI
    (`.claude/rules/deployment.md`, «GIT-ОКРУЖЕНИЕ в тестах»). Сцена, которая
    НЕ дерево, получила бы ответ ЧУЖОГО гейта — цена этого измерена ADR-789.
    """
    t = base / name
    t.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=t, check=True)
    return t


def _write(tree: Path, rel: str, text: str) -> Path:
    f = tree / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    return f


@pytest.fixture()
def ptg():
    mod = _load("_tree_ptg", "push_to_github.py")
    yield mod
    mod.reset_delivery_pin()
    mod.declare_prod_root_relative(False)


@pytest.fixture()
def scene(tmp_path):
    """Две разные сцены: ПРОД-дерево и дерево, из которого позвали пушер."""
    return _tree(tmp_path, "prod"), _tree(tmp_path, "mine")


@pytest.fixture()
def linked_scene(tmp_path):
    """Прод-дерево и СВЯЗАННЫЙ worktree ТОГО ЖЕ репозитория.

    Для вопросов про отображение пути внутрь репо сцена из двух НЕЗАВИСИМЫХ
    репозиториев ответила бы чужим гейтом: `repo_relative_path` fail-CLOSED
    отказывает чужому дереву, и отказ читался бы как вердикт этой двери (ровно
    класс ADR-789 — «сцена доставки обязана быть рабочим деревом»). Боевая
    сцена и есть такая: worktree цикла принадлежит прод-клону.
    """
    prod = _tree(tmp_path, "prod_linked")
    (prod / ".gitkeep").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", ".gitkeep"], cwd=prod, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "base"], cwd=prod, check=True)
    mine = tmp_path / "mine_linked"
    subprocess.run(["git", "worktree", "add", "-q", "--detach", str(mine)],
                   cwd=prod, check=True)
    return prod, mine


def _resolve(ptg, rel, prod, mine, **kw):
    """Зов двери с ЯВНО названными деревьями — все три оси входы, не окружение."""
    return ptg.resolve_delivery_path(rel, project_root=prod, runner_tree=mine,
                                     cwd=mine, **kw)


# ═════════════════════════════════════════════════════════════════════════════
# A. ЗАМЕР #918: один путь, два дерева, РАЗНЫЕ байты ⇒ ОТКАЗ с обоими blob-ами
# ═════════════════════════════════════════════════════════════════════════════
def test_diverging_bytes_under_one_relative_path_are_refused(ptg, scene):
    prod, mine = scene
    _write(prod, REL, "дрейф прод-дерева\n")
    _write(mine, REL, "работа цикла\n")

    with pytest.raises(ptg.AmbiguousDeliveryTree) as exc:
        _resolve(ptg, REL, prod, mine)

    text = str(exc.value)
    prod_blob = subprocess.run(["git", "hash-object", str(prod / REL)],
                               capture_output=True, text=True, check=True).stdout.strip()
    mine_blob = subprocess.run(["git", "hash-object", str(mine / REL)],
                               capture_output=True, text=True, check=True).stdout.strip()
    assert prod_blob != mine_blob, (
        "сцена не воспроизвела аварию: байты кандидатов совпали, и «тихая» ветка "
        "умолчания на них неотличима от верной — НЕ ИЗМЕРЕНО")
    assert prod_blob in text and mine_blob in text, (
        "отказ обязан напечатать ОБА blob-а: без них читатель не отличит «не тот "
        f"файл» от «файла нет». Напечатано: {text}")
    assert "ПРОД-дерево" in text, "в отказе не назван источник умолчания"


def test_the_refusal_names_the_real_cure(ptg, scene):
    """Отказ, не назвавший лекарства, учит снимать строгость (урок #918 п. 2)."""
    prod, mine = scene
    _write(prod, REL, "a\n")
    _write(mine, REL, "b\n")
    with pytest.raises(ptg.AmbiguousDeliveryTree) as exc:
        _resolve(ptg, REL, prod, mine)
    text = str(exc.value)
    assert "ABSOLUTE" in text or "АБСОЛЮТНЫЙ" in text, (
        "лекарство #1 — абсолютный путь из своего дерева — в отказе не названо")
    assert "--allow-prod-root-relative" in text, (
        "осознанный обход в отказе не назван: сторож без пути наверх учит себя "
        "обходить руками")


# ═════════════════════════════════════════════════════════════════════════════
# B. ОБРАТНАЯ СТОРОНА: объявленное согласие ВЕЗЁТ прод-дерево и говорит об этом
# ═════════════════════════════════════════════════════════════════════════════
def test_declared_consent_delivers_the_prod_tree_and_says_so(ptg, scene, capsys):
    prod, mine = scene
    _write(prod, REL, "дрейф прод-дерева\n")
    _write(mine, REL, "работа цикла\n")

    got = _resolve(ptg, REL, prod, mine, allow_prod_root=True)
    assert got == prod / REL, (
        "объявленный обход обязан везти ИМЕННО названное дерево, иначе флаг "
        "ничего не объявляет")
    out = capsys.readouterr().out
    assert "ОБХОД ОБЪЯВЛЕН" in out, (
        "обход, который не печатается, делает подмену невидимой — ровно предмет "
        "аварии")


def test_consent_is_read_from_the_module_declaration_too(ptg, scene):
    """CLI объявляет согласие на модуле: дверей доставки две, store обязан быть один."""
    prod, mine = scene
    _write(prod, REL, "a\n")
    _write(mine, REL, "b\n")
    with pytest.raises(ptg.AmbiguousDeliveryTree):
        _resolve(ptg, REL, prod, mine)
    ptg.declare_prod_root_relative(True)
    assert _resolve(ptg, REL, prod, mine) == prod / REL
    ptg.declare_prod_root_relative(False)
    with pytest.raises(ptg.AmbiguousDeliveryTree):
        _resolve(ptg, REL, prod, mine)


# ═════════════════════════════════════════════════════════════════════════════
# C. ФАЙЛ ТОЛЬКО В ПРОДЕ — та же авария без расхождения байтов
#
# Это НЕ «файл не найден»: в прод-дереве он есть, и до ADR-796 его байты
# уезжали молча. Прод-дерево держит файлы, которых на origin нет вовсе
# (замер #918: 116 файлов `data/` однажды уже уехали так на три недели назад).
# ═════════════════════════════════════════════════════════════════════════════
def test_a_path_that_exists_only_in_the_prod_tree_is_refused(ptg, scene):
    prod, mine = scene
    _write(prod, "data/prod_only.json", "{}\n")
    with pytest.raises(ptg.AmbiguousDeliveryTree) as exc:
        _resolve(ptg, "data/prod_only.json", prod, mine)
    text = str(exc.value)
    assert "ТОЛЬКО в прод-дереве" in text, (
        f"причина отказа не названа своими словами: {text}")
    assert "файла НЕТ" in text, (
        "отказ обязан сказать, что в дереве вызова файла нет — иначе читатель "
        "решит, что расходятся байты")


# ═════════════════════════════════════════════════════════════════════════════
# D. КОНТРОЛЬ «НЕ ИНВЕРТИРОВАНО»: единственный найденный файл читается, а не
#    подменяется отказом. Громкое «не найдено» прода больше не маскирует
#    ВЕРНЫЙ ответ своего дерева.
# ═════════════════════════════════════════════════════════════════════════════
def test_a_path_found_only_in_the_callers_tree_is_read_and_named(ptg, scene, capsys):
    prod, mine = scene
    f = _write(mine, "spa_core/new_module.py", "x = 1\n")
    got = _resolve(ptg, "spa_core/new_module.py", prod, mine)
    assert got == f, "файл есть РОВНО в одном дереве — читать нечего больше"
    assert "дерево НАЗВАНО" in capsys.readouterr().out, (
        "выбранное дерево обязано быть названо вслух: молчание здесь и есть то "
        "умолчание, против которого написан ADR-796")


def test_an_absolute_path_is_not_touched_by_a_single_bit(ptg, scene):
    """Абсолютный путь уже назвал своё дерево сам — правка его не касается."""
    prod, mine = scene
    f = _write(mine, REL, "работа цикла\n")
    _write(prod, REL, "дрейф\n")
    assert _resolve(ptg, str(f), prod, mine) == f
    assert ptg.resolve_delivery_path(str(f)) == f


def test_when_the_caller_stands_in_the_prod_root_nothing_changes(ptg, tmp_path):
    """Штатный autopush из launchd: одно дерево ⇒ вопроса нет, вердиктов нет."""
    prod = _tree(tmp_path, "prod_only_tree")
    f = _write(prod, REL, "один и тот же файл\n")
    got = ptg.resolve_delivery_path(REL, project_root=prod, runner_tree=prod, cwd=prod)
    assert got == f
    assert ptg._TREE_VERDICTS == [], (
        "дверь заговорила там, где деревьев одно: шум в штатном пути учит его "
        "игнорировать")


# ═════════════════════════════════════════════════════════════════════════════
# E. ТРЕТИЙ ИСХОД РАЗЛИЧИМ (инв. #17): «спросили и байты равны» ≠ «не спрашивали»
# ═════════════════════════════════════════════════════════════════════════════
def test_identical_bytes_in_both_trees_pass_and_are_said_out_loud(ptg, scene, capsys):
    prod, mine = scene
    _write(prod, REL, "одни и те же байты\n")
    _write(mine, REL, "одни и те же байты\n")
    got = _resolve(ptg, REL, prod, mine)
    assert got == prod / REL
    out = capsys.readouterr().out
    assert "байты СОВПАЛИ" in out, (
        "«измерено и равно» промолчало — и стало неотличимо от «не измеряли»")
    assert [v["verdict"] for v in ptg._TREE_VERDICTS] == ["agreed"]


def test_an_unreadable_candidate_is_not_mistaken_for_agreement(ptg, scene):
    """Нечитаемый кандидат — НЕ ИЗМЕРЕНО, и это отказ, а не «расхождения нет»."""
    prod, mine = scene
    p = _write(prod, REL, "одни и те же байты\n")
    _write(mine, REL, "одни и те же байты\n")
    os.chmod(p, 0o000)
    try:
        if os.access(p, os.R_OK):          # root/ACL — предпосылка НЕ ОБЕСПЕЧЕНА
            raise Unmeasured(
                "кандидат остался читаемым после chmod 000 — сцену «нечитаемый "
                "кандидат» поднять не удалось; НЕ ИЗМЕРЕНО, а не «прошло»")
        with pytest.raises(ptg.AmbiguousDeliveryTree) as exc:
            _resolve(ptg, REL, prod, mine)
    finally:
        os.chmod(p, 0o644)
    assert "НЕ ИЗМЕРЕНО" in str(exc.value), (
        "нечитаемый кандидат получил пустую строку или совпал с соседом — "
        "«не прочитали» превратилось в «расхождения нет»")


# ═════════════════════════════════════════════════════════════════════════════
# F. ГРОМКИЙ СЛУЧАЙ НЕ СТАЛ ТИШЕ: файла нет нигде ⇒ прежний отказ «не найден»
# ═════════════════════════════════════════════════════════════════════════════
def test_a_path_missing_everywhere_keeps_the_old_loud_refusal(ptg, scene, monkeypatch):
    prod, mine = scene
    monkeypatch.setattr(ptg, "PROJECT_ROOT", prod)
    monkeypatch.chdir(mine)
    with pytest.raises(RuntimeError) as exc:
        ptg.resolve_files(["docs/NO_SUCH_FILE.md"])
    assert "Файл не найден" in str(exc.value), (
        "отказ двери подменил внятный «файл не найден» своим — читателя увели "
        f"не туда: {exc.value}")


# ═════════════════════════════════════════════════════════════════════════════
# G. ОДНА ДВЕРЬ НА ТРЁХ ЧИТАТЕЛЕЙ ПУТИ
#
# Разойдись они — пин лёг бы на один файл, а уехал бы другой: это ровно предмет
# ADR-774, вернувшийся с другой стороны. Перечень читателей ЗАМКНУТ и меряется
# AST, а не подстрокой: подстрока «PROJECT_ROOT / local» переживает
# переименование переменной.
# ═════════════════════════════════════════════════════════════════════════════
PATH_READERS = ("_delivery_abs", "resolve_files", "push_file")


def _calls_the_door(source: str, func: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Name)
                        and inner.func.id == "resolve_delivery_path"):
                    return True
            return False
    raise Unmeasured(f"читателя пути `{func}` в пушере НЕТ — перечень разошёлся "
                     f"с кодом, и это НЕ ИЗМЕРЕНО, а не «чисто»")


def _default_root_joins(source: str) -> list:
    """Сложения с `PROJECT_ROOT`, оставшиеся МИМО двери (AST, не подстрока)."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
                and isinstance(node.left, ast.Name)
                and node.left.id == "PROJECT_ROOT"):
            out.append(node.lineno)
    return out


def test_every_path_reader_goes_through_the_one_door():
    source = PUSHER.read_text(encoding="utf-8")
    missing = [f for f in PATH_READERS if not _calls_the_door(source, f)]
    assert missing == [], (
        f"читатели пути мимо двери: {missing} — пин спросит один файл, уедет "
        f"другой, и сторож ADR-774 ПОДТВЕРДИТ подмену")


def test_no_reader_joins_the_prod_root_behind_the_doors_back():
    source = PUSHER.read_text(encoding="utf-8")
    stray = _default_root_joins(source)
    assert stray == [], (
        f"в пушере осталось сложение `PROJECT_ROOT / …` мимо двери (строки "
        f"{stray}): вторая копия правила — тот механизм, которым цикл #40 "
        f"разослал файлы в корень репо")


def test_the_pin_and_resolve_files_agree_on_the_very_same_file(
        ptg, linked_scene, monkeypatch):
    """Ключ слепка и путь читателя — ОДИН, и измерен там, где дверь ПРОПУСКАЕТ.

    Сцена выбрана так, что ответ двери и ответ умолчания РАЗНЫЕ: файл есть
    только в дереве вызова, и до ADR-796 оба читателя смотрели в прод-дерево,
    где его нет. Совпади они на абсолютном пути — проверка была бы зелена и на
    нормализации, согласованной сама с собой (дыра, найденная мутацией №19
    цикла #890).
    """
    prod, mine = linked_scene
    _write(mine, "spa_core/only_here.py", "x = 1\n")
    monkeypatch.setattr(ptg, "PROJECT_ROOT", prod)
    monkeypatch.chdir(mine)
    monkeypatch.setattr(ptg, "MODULE_FILE", str(mine / "push_to_github.py"))

    rel = "spa_core/only_here.py"
    pin = ptg.pin_delivery_bytes([rel])
    resolved = [str(ap) for _, ap in ptg.resolve_files([rel])]
    assert sorted(pin["digests"]) == sorted(resolved) == [str(mine / rel)], (
        f"пин и читатель разошлись либо выбрали прод-дерево: пин "
        f"{sorted(pin['digests'])}, читатель {resolved}")
    assert pin["unreadable"] == {}, (
        "файл существует в дереве вызова — «не прочитан» здесь означал бы, что "
        "пин смотрит не туда")


def test_both_readers_agree_under_the_declared_bypass_too(
        ptg, linked_scene, monkeypatch):
    """Обратная сторона: объявленный обход тоже ведёт ОБА читателя в ОДНО дерево."""
    prod, mine = linked_scene
    _write(prod, REL, "дрейф\n")
    _write(mine, REL, "работа цикла\n")
    monkeypatch.setattr(ptg, "PROJECT_ROOT", prod)
    monkeypatch.chdir(mine)
    monkeypatch.setattr(ptg, "MODULE_FILE", str(mine / "push_to_github.py"))
    ptg.declare_prod_root_relative(True)

    pin = ptg.pin_delivery_bytes([REL])
    resolved = [str(ap) for _, ap in ptg.resolve_files([REL])]
    assert sorted(pin["digests"]) == sorted(resolved) == [str(prod / REL)], (
        "под объявленным обходом читатели разошлись — обход развёл бы пин и "
        f"доставку: пин {sorted(pin['digests'])}, читатель {resolved}")


# ═════════════════════════════════════════════════════════════════════════════
# H. ВТОРОЙ ДВЕРИ НЕТ: батч-CLI зовёт ТУ ЖЕ функцию, а не свою копию
# ═════════════════════════════════════════════════════════════════════════════
def test_the_batch_cli_imports_the_same_door_object():
    batch = _load("_tree_batch", "push_to_github_batch.py")
    root = batch._root_push
    assert batch.resolve_delivery_path is root.resolve_delivery_path, (
        "у батч-CLI своя копия двери: одна дверь отказывала бы, а вторая молча "
        "везла бы байты прод-дерева — дословно урок двух копий "
        "`repo_relative_path` (цикл #40)")
    assert batch.AmbiguousDeliveryTree is root.AmbiguousDeliveryTree
    assert batch.DELIVERY_TREE_EXIT == root.DELIVERY_TREE_EXIT == 12


# ═════════════════════════════════════════════════════════════════════════════
# I. ИСХОД, А НЕ СТРУКТУРА: НАСТОЯЩИЙ CLI на одноразовой сцене, два прогона с
#    ПРОТИВОПОЛОЖНЫМИ ответами. Сеть не трогается: отказ наступает внутри пина.
# ═════════════════════════════════════════════════════════════════════════════
_DRIVER = '''
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("_cli_ptg", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
sys.modules["_cli_ptg"] = mod
spec.loader.exec_module(mod)
mod.PROJECT_ROOT = Path(sys.argv[2])
mod.MODULE_FILE = str(Path(sys.argv[3]) / "push_to_github.py")
sys.argv = ["push_to_github.py"] + sys.argv[4:]
mod.main()
'''


def _cli(tmp_path, cli: Path, prod: Path, mine: Path, *extra) -> tuple:
    driver = tmp_path / "driver.py"
    driver.write_text(_DRIVER, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(driver), str(cli), str(prod), str(mine),
         "--files", REL, "--message", "сцена двери", "--dry-run", *extra],
        capture_output=True, text=True, cwd=str(mine), timeout=300,
        env={**os.environ, "SPA_PUSH_ALLOW_PROD_ROOT_RELATIVE": "0"})
    return proc.returncode, proc.stdout + proc.stderr


@pytest.mark.parametrize("cli", [PUSHER, BATCH_CLI], ids=["push", "batch"])
def test_the_real_cli_refuses_with_its_own_exit_code(tmp_path, scene, cli):
    prod, mine = scene
    _write(prod, REL, "дрейф прод-дерева\n")
    _write(mine, REL, "работа цикла\n")

    rc_refused, out_refused = _cli(tmp_path, cli, prod, mine)
    rc_declared, out_declared = _cli(tmp_path, cli, prod, mine,
                                     "--allow-prod-root-relative")

    assert rc_refused == 12, (
        f"настоящий CLI не отказал своим кодом (вышел {rc_refused}) — именно так "
        f"#918 получил бы код 0 и чужие байты: {out_refused[-400:]}")
    assert "ОТКАЗ (дерево доставки не названо)" in out_refused
    assert rc_declared != 12, (
        "объявленное согласие НЕ проходит дверь — обход, который не работает, "
        f"равен его отсутствию: {out_declared[-400:]}")
    assert "ОБХОД ОБЪЯВЛЕН" in out_declared, (
        "вторая сцена прошла дверь МОЛЧА: различить «объявил» и «не спросили» "
        f"нечем: {out_declared[-400:]}")
    assert rc_refused != rc_declared, (
        "две сцены с ПРОТИВОПОЛОЖНЫМИ правильными ответами дали один код — "
        "дверь не меряет ничего")
