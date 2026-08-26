"""Дочерний `pytest` обязан быть заякорен — иначе он сканирует системный /tmp целиком.

Карточка `inbox-dochernii-pytest-visnet-esli-ego-test-fa` (находка цикла #315):
дочерний прогон, чей тест-файл лежал в `tmp_path` родителя, не доходил до
`--collect-only` за 300 с, а тот же файл из `tempfile.mkdtemp()` отвечал за 0.00 с.
Причина в карточке названа НЕ была — стояли две гипотезы (уборка нумерованных
каталогов, локи `TempPathFactory`).

Цикл #382 измерил причину, и **обе гипотезы неверны**. Разбор — в докстринге
`_child_pytest.py`; коротко: без ini-файла среди предков аргумента pytest берёт
rootdir как ОБЩЕГО ПРЕДКА cwd и аргумента (`/private`), `confcutdir` наследует
rootdir, и `Session.collect` строит `Dir`-узлы на всех предках вплоть до
`$TMPDIR` — а `Dir.collect` делает по ним `scandir`. На этой машине в `$TMPDIR`
лежало 9 780 560 записей.

Отсюда два вывода, и оба закреплены здесь:

* **`mkdtemp` — не починка, а везение.** Он возвращает НЕразрешённый
  `/var/folders/…`, у которого с cwd нет общего предка кроме `/`, поэтому pytest
  откатывается к каталогу самого аргумента. Один `.resolve()` — и пятиминутный
  простой возвращается молча (замер: `mkdtemp RESOLVED → TIMEOUT >25 с`).
* **Починка — якорь.** `--rootdir` (0.26 с), `--confcutdir` (0.13 с) или
  `cwd`=каталог файла (0.13 с). Договорённость набора — `--rootdir` через
  `_child_pytest.child_pytest_argv`, потому что её видно в argv и её можно
  проверить линтом, а не «помнить».

Инв. #16: ни один существующий assert здесь не ослаблен — файл только добавляет.
"""

from __future__ import annotations

import ast
import functools
import io
import os
import re
import tokenize
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from spa_core.tests import _child_pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_DIRS = ("spa_core/tests", "tests")

#: Здоровый дочерний прогон тривиального файла — доли секунды (замер #315 и #382).
#: Потолок узкий НАМЕРЕННО: если якорь снимут, тест обязан назваться быстро,
#: а не съесть job целиком (ровно тот класс, ради которого в test.yml держат
#: pytest-timeout).
CHILD_BUDGET_S = 30.0


# ---------------------------------------------------------------------------
# 1. Договорённость: как выглядит заякоренный вызов
# ---------------------------------------------------------------------------

def test_argv_pins_rootdir_to_the_files_own_directory(tmp_path):
    f = tmp_path / "test_child_probe.py"
    f.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    argv = _child_pytest.child_pytest_argv(f, "-q")
    assert argv[:3] == [sys.executable, "-m", "pytest"]
    assert "--rootdir" in argv, "якорь пропал из argv — вернулся класс #315"
    assert argv[argv.index("--rootdir") + 1] == str(tmp_path)
    assert argv[-1] == "-q", "дополнительные аргументы обязаны доезжать до дочернего прогона"


def test_argv_anchors_a_directory_argument_at_itself(tmp_path):
    """Каталог как аргумент — якорь на нём самом, а не на его родителе."""
    argv = _child_pytest.child_pytest_argv(tmp_path)
    assert argv[argv.index("--rootdir") + 1] == str(tmp_path)


# ---------------------------------------------------------------------------
# 2. Причина, измеренная самим pytest'ом (без запуска дочернего процесса)
# ---------------------------------------------------------------------------

def _rootdir_for(arg: Path, invocation_dir: Path, rootdir_cmd_arg=None) -> Path:
    from _pytest.config.findpaths import determine_setup

    return determine_setup(
        inifile=None,
        args=[str(arg)],
        rootdir_cmd_arg=str(rootdir_cmd_arg) if rootdir_cmd_arg else None,
        invocation_dir=invocation_dir,
        override_ini=None,
    )[0]


def test_anchor_pins_rootdir_even_for_a_path_under_the_system_temp(tmp_path):
    """Прямая проверка механизма: с якорем rootdir — ровно каталог файла.

    Без якоря rootdir считается общим предком cwd и аргумента, и для
    РАЗРЕШЁННОГО пути под системным /tmp это предок самого /tmp — именно тогда
    `Dir.collect` уходит в scandir по миллионам записей.
    """
    f = tmp_path / "test_child_probe.py"
    f.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    anchored = _rootdir_for(f, REPO_ROOT, rootdir_cmd_arg=tmp_path)
    assert anchored == tmp_path, (
        "явный --rootdir перестал определять rootdir дочернего прогона — "
        "договорённость набора держится ни на чём"
    )

    system_tmp = Path(tempfile.gettempdir()).resolve()
    assert not system_tmp.is_relative_to(anchored), (
        f"заякоренный rootdir {anchored} всё ещё накрывает системный временный каталог "
        f"{system_tmp}: collect обойдёт его целиком, и это те самые 300 с из карточки"
    )


def test_unanchored_rootdir_is_what_lets_collect_reach_the_system_temp(tmp_path):
    """Обратная сторона: НЕзаякоренный вызов для того же файла берёт rootdir выше /tmp.

    Тест не утверждает, что так будет на любой машине (общий предок зависит от
    того, где лежит cwd), поэтому он проверяет УТВЕРЖДЕНИЕ, а не окружение:
    если общий предок действительно накрывает системный /tmp, то и rootdir
    накрывает его — то есть механизм именно тот, что назван в карточке.
    """
    f = tmp_path / "test_child_probe.py"
    f.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    system_tmp = Path(tempfile.gettempdir()).resolve()
    plain = _rootdir_for(f, REPO_ROOT)

    # общий предок cwd и аргумента — то, из чего pytest и считает rootdir
    common = Path(os.path.commonpath([str(REPO_ROOT), str(f)]))

    if system_tmp.is_relative_to(common):
        assert system_tmp.is_relative_to(plain), (
            f"общий предок {common} накрывает {system_tmp}, а rootdir {plain} — нет: "
            "объяснение из карточки перестало соответствовать поведению pytest, "
            "и линт ниже сторожит уже не тот механизм"
        )
    else:
        pytest.skip(
            f"на этой машине cwd ({REPO_ROOT}) и системный /tmp ({system_tmp}) "
            "не имеют общего предка выше /tmp — опасная форма здесь не возникает"
        )


# ---------------------------------------------------------------------------
# 3. Настоящий дочерний прогон — положительный контроль на самом якоре
# ---------------------------------------------------------------------------

def test_anchored_child_run_answers_from_inside_the_parents_basetemp(tmp_path):
    """Файл лежит РОВНО там, где цикл #315 получил 300 с, — и прогон отвечает мгновенно.

    Это и есть положительный контроль: убери `--rootdir` из
    `child_pytest_argv` — и этот тест упрётся в свой таймаут, воспроизведя
    аварию байт-в-байт.
    """
    f = tmp_path / "test_child_probe.py"
    f.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    t0 = time.time()
    try:
        proc = _child_pytest.run_child_pytest(
            f, "-q", "-p", "no:cacheprovider", timeout=CHILD_BUDGET_S
        )
    except subprocess.TimeoutExpired:  # pragma: no cover - это и есть авария
        pytest.fail(
            f"дочерний pytest не ответил за {CHILD_BUDGET_S} с на тривиальном файле в "
            f"{tmp_path} — вернулся класс #315: якорь rootdir снят, и collect обходит "
            f"системный временный каталог"
        )
    took = time.time() - t0
    assert proc.returncode == 0, f"дочерний прогон упал:\n{proc.stdout}\n{proc.stderr}"
    assert "1 passed" in proc.stdout, proc.stdout
    assert took < CHILD_BUDGET_S, f"дочерний прогон занял {took:.1f} с"


# ---------------------------------------------------------------------------
# 4. Линт: одна договорённость, а не устная
# ---------------------------------------------------------------------------

#: Форма запуска дочернего прогона в argv. Ищется по ИСХОДНИКУ, а не по AST-узлу
#: вызова: половина настоящих мест собирает `cmd` в переменную и передаёт её в
#: `subprocess.run(cmd, ...)`, и AST-детектор их МОЛЧА пропускал (проверено:
#: первая редакция этого линта не увидела оба живых guard-файла).
_ARGV_SHAPE = re.compile(r"""["']-m["']\s*,\s*["']pytest["']""")
_SPAWNERS = re.compile(r"\bsubprocess\.(run|Popen|check_output|check_call|call)\b")
#: Якорь засчитывается только как КОД. Вторая редакция этого линта засчитывала
#: его из комментария: мутация «молча верни незаякоренный вызов» осталась ЗЕЛЁНОЙ,
#: потому что рядом лежал комментарий со словом `--rootdir` (класс «сторож,
#: описавший свою аварию, кормит свой же корпус»).
_HELPER_USE = re.compile(r"_child_pytest\s*\.\s*(run_child_pytest|child_pytest_argv)")


def _code_only(src: str) -> str:
    """Исходник без комментариев и докстрингов — прозе якорь не засчитывается."""
    try:
        tree = ast.parse(src)
    except SyntaxError:  # pragma: no cover - не наш предмет
        return src
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                doc_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    # комментарии снимаются ОДНИМ проходом токенайзера по всему файлу:
    # построчный вариант стоил 15 с на набор и превратил бы линт в налог.
    cuts: dict[int, int] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                line = tok.start[0]
                cuts[line] = min(cuts.get(line, tok.start[1]), tok.start[1])
    except (tokenize.TokenError, IndentationError):  # pragma: no cover
        pass
    out = []
    for i, line in enumerate(src.splitlines(), 1):
        if i in doc_lines:
            continue
        if i in cuts:
            line = line[: cuts[i]]
        out.append(line)
    return "\n".join(out)


def _spawns_child_pytest(src: str) -> bool:
    # Дешёвый предфильтр по СЫРОМУ тексту: снимать комментарии с тысячи файлов
    # ради пяти совпадений — 6.8 с на прогон, то есть налог на весь набор.
    # Предфильтр может только РАСШИРЯТЬ множество кандидатов (в коде оба признака
    # тоже присутствуют), поэтому находку он потерять не может.
    if not (_ARGV_SHAPE.search(src) and _SPAWNERS.search(src)):
        return False
    code = _code_only(src)
    return bool(_ARGV_SHAPE.search(code) and _SPAWNERS.search(code))


@functools.lru_cache(maxsize=1)
def _child_pytest_files() -> tuple[Path, ...]:
    found = []
    for rel in SCAN_DIRS:
        base = REPO_ROOT / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            src = path.read_text(encoding="utf-8", errors="replace")
            if _spawns_child_pytest(src):
                found.append(path)
    return tuple(found)


#: Файлы, чей дочерний тест-файл лежит ВНУТРИ репозитория. Такому прогону rootdir
#: даёт `pytest.ini` репозитория (он находится подъёмом от самого аргумента), и
#: опасная форма не возникает по построению. Список именной и с причиной —
#: молчаливое пополнение краснеет отдельным тестом ниже.
_ANCHORED_BY_THE_REPO_INI = {
    "spa_core/tests/test_backup_root_hermetic_and_responsive.py":
        "дочерний файл — git-tracked `_child_backup_pin_check.py` в spa_core/tests/: "
        "rootdir даёт pytest.ini репозитория, поднимаясь от самого аргумента",
    "tests/test_owner_gate_check.py":
        "блок `__main__` перезапускает САМ СЕБЯ (`__file__`) — аргумент всегда внутри "
        "репозитория, опасной формы нет",
}


def test_every_child_pytest_run_is_anchored():
    """Дочерний прогон с файлом ВНЕ репозитория обязан пинить rootdir.

    Иначе он платит теми самыми 300 с — молча, и выглядит это как «тест долго
    идёт», а не как «проверка не выполнилась».
    """
    offenders = []
    for path in _child_pytest_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in _ANCHORED_BY_THE_REPO_INI:
            continue
        code = _code_only(path.read_text(encoding="utf-8", errors="replace"))
        uses_helper = bool(_HELPER_USE.search(code))
        pins = any(flag in code for flag in _child_pytest.ROOTDIR_FLAGS)
        if not (uses_helper or pins):
            offenders.append(rel)
    assert not offenders, (
        "дочерний pytest запускается без якоря rootdir в: "
        + ", ".join(offenders)
        + ". Возьми spa_core/tests/_child_pytest.run_child_pytest (или передай "
        "--rootdir/--confcutdir явно): без якоря pytest считает rootdir общим предком "
        "cwd и аргумента и обходит scandir'ом весь системный временный каталог "
        "(замер #382: 9 780 560 записей, >300 с). tempfile.mkdtemp() тут НЕ спасает — "
        "он работает лишь потому, что возвращает неразрешённый /var/..., и один "
        ".resolve() возвращает аварию."
    )


def test_the_exception_list_names_files_that_still_exist_and_still_spawn():
    """Исключение без предмета — украшение; список ведётся только вниз."""
    spawning = {p.relative_to(REPO_ROOT).as_posix() for p in _child_pytest_files()}
    for rel, reason in _ANCHORED_BY_THE_REPO_INI.items():
        assert (REPO_ROOT / rel).is_file(), f"исключение {rel} указывает на несуществующий файл"
        assert reason.strip(), f"исключение {rel} без названной причины"
        assert rel in spawning, (
            f"{rel} больше не запускает дочерний pytest — исключение обязано уйти, "
            "иначе список перестаёт быть измеримым"
        )
