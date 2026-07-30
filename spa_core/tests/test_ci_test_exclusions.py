#!/usr/bin/env python3
"""Гейт против КЛАССА «тесты живого кода молча не выполняются» — этажом выше файлов.

Зачем этот файл существует
==========================
Циклы #37/#38/#39 нашли один и тот же приём внутри тестовых файлов: тест-файл
гасился ``pytest.mark.skip`` с шаблонной отпиской. Против него цикл #39 построил
``test_no_template_skip_reasons.py`` — но тот сканирует **тестовые файлы** и
**по построению не видит** второй способ выключить те же тесты: флаг
``--ignore`` в команде pytest внутри ``.github/workflows/*.yml``.

Цикл #42 нашёл ровно это (карточка ``agent-ci-ignores-golive-gate-tests``):

* ``test.yml`` исключал ``spa_core/tests/test_golive_checker.py`` — **43 теста
  гейта, который выдаёт публичное «29/29 READY»**, не выполнялись в CI ни разу;
* ``ci.yml`` дважды передавал ``--ignore=tests/test_golive_checker.py``, причём
  один из двух путей в репозитории **не существует** (мёртвый игнор: ничего не
  выключает, но читающий workflow уверен, что исключение осознанное);
* причина исключения не была записана НИГДЕ — флаг приехал вместе с самим
  файлом workflow в коммите-импорте ``b9cf63fb5`` (2026-07-17), т.е. и
  «временной мерой после падения» он не был.

Невидимое исключение хуже красного теста: оно не попадает ни в счётчик
падений, ни в глаза читателю, и создаёт впечатление покрытия там, где его нет
(инвариант #16 — молча ослаблять/выключать тесты запрещено).

Что проверяется (детерминированно, только чтение файлов репозитория, без сети)
=============================================================================
1. Дерево workflow'ов вообще сканируется и в нём найдена хотя бы одна команда
   pytest — сканер, ничего не нашедший, НЕ считается зелёным (fail-CLOSED).
2. Каждое исключение тестов (``--ignore``, ``--ignore-glob``, ``--deselect``,
   ``-k``/``-m`` с отрицанием) в команде pytest — только из явного реестра
   ``_ALLOWED_EXCLUSIONS``.
3. У каждой записи реестра есть **прослеживаемое** обоснование (ссылка на
   карточку / ADR / документ), а не отписка.
4. Каждый исключаемый путь **существует** (с учётом ``cd`` в шаге workflow) —
   мёртвый игнор краснеет сразу.
5. В реестре нет протухших записей: убрали игнор из workflow — уберите и запись.

Гейт НЕ запрещает исключения как таковые. Он запрещает **невидимые** и
**мёртвые**: обоснуй в реестре — и оно станет видимым в diff'е и в этом тесте.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import NamedTuple

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"

# ── Реестр разрешённых исключений ─────────────────────────────────────────────
# Ключ: (имя файла workflow, флаг, значение флага ДОСЛОВНО как в YAML).
# Значение: обоснование — обязано содержать прослеживаемую ссылку
# (``_TRACE_TOKENS``: карточка / ADR / файл документации), чтобы через полгода
# можно было понять, почему тесты не гоняются, не поднимая git-археологию.
#
# ПУСТОЙ реестр — нормальное состояние: цикл #46 снял оба игнора
# ``test_golive_checker`` (один был мёртвым, второй выключал 43 теста гейта
# готовности; возврат подтверждён РЕАЛЬНЫМ прогоном Actions на ubuntu-22.04,
# а не локальным — журнал 2026-W31, карточка agent-ci-ignores-golive-gate-tests).
_ALLOWED_EXCLUSIONS: dict[tuple[str, str, str], str] = {}

# Обоснование должно быть прослеживаемым: ссылка на карточку, ADR или документ.
_TRACE_TOKENS = ("agent-", "own-", "owner-decision-", "ADR", "docs/", "MP-")
_MIN_JUSTIFICATION_LEN = 30

# Флаги pytest, которые убирают тесты из прогона.
_PATH_FLAGS = ("--ignore", "--deselect")          # значение — путь (нужна проверка существования)
_GLOB_FLAGS = ("--ignore-glob",)                  # значение — glob (путь как таковой не проверяем)
_EXPR_FLAGS = ("-k", "-m")                        # значение — выражение; ловим только отрицание


class Exclusion(NamedTuple):
    """Одно исключение тестов, найденное в команде pytest внутри workflow."""

    workflow: str   # имя файла workflow
    flag: str       # "--ignore" / "--deselect" / "--ignore-glob" / "-k" / "-m"
    value: str      # значение флага дословно
    cwd: str        # рабочий каталог шага относительно корня репо ("" = корень)
    command: str    # сама команда (для сообщения об ошибке)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.workflow, self.flag, self.value)


# ── Разбор workflow → команды оболочки ────────────────────────────────────────
_RUN_RE = re.compile(r"^(\s*)(?:-\s+)?run:\s*(.*)$")
_CD_RE = re.compile(r"^\s*cd\s+([^\s;&|]+)\s*$")
# Вызов pytest: "pytest ...", "python -m pytest ...", "python3 -m pytest ..."
_PYTEST_RE = re.compile(r"(?:^|[\s;&|(])(?:python3?\s+-m\s+)?pytest(?:\s|$)")


def _run_blocks(text: str) -> list[list[str]]:
    """Вернуть тела всех ``run:``-шагов как списки логических команд.

    Поддерживает block-scalar (``run: |``) и однострочный ``run: cmd``.
    Продолжения строк (``\\`` в конце) склеиваются в одну логическую команду.
    """
    lines = text.splitlines()
    blocks: list[list[str]] = []
    i = 0
    while i < len(lines):
        m = _RUN_RE.match(lines[i])
        if not m:
            i += 1
            continue
        indent, rest = len(m.group(1)), m.group(2).strip()
        i += 1
        if rest and rest[0] not in "|>":
            blocks.append(_join_continuations([rest]))
            continue
        body: list[str] = []
        while i < len(lines):
            line = lines[i]
            if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                break
            body.append(line)
            i += 1
        blocks.append(_join_continuations(body))
    return blocks


def _join_continuations(body: list[str]) -> list[str]:
    """Склеить строки, оканчивающиеся на ``\\``, в одну логическую команду."""
    out: list[str] = []
    buf = ""
    for raw in body:
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.endswith("\\"):
            buf += line[:-1].strip() + " "
            continue
        out.append((buf + line.strip()).strip())
        buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


def _tokenize(command: str) -> list[str]:
    """Разбить команду по правилам оболочки: ``-k "not slow"`` — ОДИН аргумент.

    При незакрытой кавычке (в YAML такое бывает) деградируем до простого
    ``split()`` — потерять кавычки хуже, чем упасть на разборе.
    """
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _flag_values(command: str, flag: str) -> list[str]:
    """Значения ``flag`` в команде: и ``--flag=v``, и ``--flag v``."""
    values: list[str] = []
    tokens = _tokenize(command)
    for idx, tok in enumerate(tokens):
        if tok.startswith(flag + "="):
            values.append(_unquote(tok[len(flag) + 1:]))
        elif tok == flag and idx + 1 < len(tokens):
            values.append(_unquote(tokens[idx + 1]))
    return values


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _normalize_cwd(cwd: str, target: str) -> str:
    """Применить ``cd target`` к текущему относительному каталогу."""
    parts = [p for p in cwd.split("/") if p] if cwd else []
    for piece in target.strip("/").split("/"):
        if piece in ("", "."):
            continue
        if piece == "..":
            if parts:
                parts.pop()
        else:
            parts.append(piece)
    return "/".join(parts)


def collect_exclusions(files: dict[str, str]) -> list[Exclusion]:
    """Собрать исключения тестов из содержимого workflow-файлов.

    ``files``: {имя файла: текст}. Вынесено параметром, чтобы гейт можно было
    проверить положительными контролями на синтетическом YAML.
    """
    found: list[Exclusion] = []
    for name, text in sorted(files.items()):
        for block in _run_blocks(text):
            # Каждый шаг ``run:`` — новая оболочка из корня workspace, поэтому cwd
            # сбрасывается на каждом блоке: без этого ``cd spa_core`` из предыдущего
            # шага сделал бы мёртвый путь следующего шага «живым» — то есть гейт
            # промолчал бы ровно о той находке, ради которой создан.
            cwd = ""
            for command in block:
                if command.lstrip().startswith("#"):
                    continue  # закомментированный вызов ничего не выключает
                cd_match = _CD_RE.match(command)
                if cd_match:
                    cwd = _normalize_cwd(cwd, cd_match.group(1))
                    continue
                if not _PYTEST_RE.search(command):
                    continue
                for flag in _PATH_FLAGS + _GLOB_FLAGS:
                    for value in _flag_values(command, flag):
                        found.append(Exclusion(name, flag, value, cwd, command))
                for flag in _EXPR_FLAGS:
                    for value in _flag_values(command, flag):
                        if re.search(r"\bnot\b", value):
                            found.append(Exclusion(name, flag, value, cwd, command))
    return found


def _read_workflows() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(_WORKFLOWS_DIR.glob("*.yml")) + sorted(_WORKFLOWS_DIR.glob("*.yaml"))
    }


def _pytest_command_count(files: dict[str, str]) -> int:
    return sum(
        1
        for text in files.values()
        for block in _run_blocks(text)
        for command in block
        if _PYTEST_RE.search(command)
    )


def _excluded_path(exc: Exclusion) -> Path:
    """Путь, который исключает флаг, с учётом ``cd`` в шаге и node-id ``::``."""
    raw = exc.value.split("::")[0]
    prefix = f"{exc.cwd}/" if exc.cwd else ""
    return _REPO_ROOT / f"{prefix}{raw}"


_WORKFLOW_FILES = _read_workflows()
_EXCLUSIONS = collect_exclusions(_WORKFLOW_FILES)


# ── Гейт над РЕАЛЬНЫМ репозиторием ────────────────────────────────────────────
def test_workflow_tree_is_scannable() -> None:
    """Fail-CLOSED: сканер, ничего не нашедший, не считается зелёным."""
    assert _WORKFLOWS_DIR.is_dir(), f"нет каталога workflow'ов: {_WORKFLOWS_DIR}"
    assert _WORKFLOW_FILES, "в .github/workflows не найдено ни одного YAML — сканер слеп"
    assert _pytest_command_count(_WORKFLOW_FILES) > 0, (
        "ни в одном workflow не найдено команды pytest — либо CI перестал гонять тесты, "
        "либо сломался разбор run-блоков; молчаливого «всё в порядке» здесь не будет"
    )


def test_no_unregistered_test_exclusions() -> None:
    """Любое исключение тестов в CI — только из явного реестра."""
    unregistered = [e for e in _EXCLUSIONS if e.key not in _ALLOWED_EXCLUSIONS]
    assert not unregistered, (
        "в CI выключаются тесты, и это нигде не обосновано:\n"
        + "\n".join(
            f"  {e.workflow}: {e.flag} {e.value}  (cwd={e.cwd or '<корень>'})\n"
            f"      команда: {e.command}"
            for e in unregistered
        )
        + "\n\nЛибо снимите флаг, либо внесите запись в _ALLOWED_EXCLUSIONS "
          "с прослеживаемым обоснованием (карточка/ADR/док)."
    )


def test_every_registered_exclusion_has_traceable_justification() -> None:
    """Обоснование обязано быть содержательным и прослеживаемым."""
    bad: list[str] = []
    for key, reason in _ALLOWED_EXCLUSIONS.items():
        text = (reason or "").strip()
        if len(text) < _MIN_JUSTIFICATION_LEN:
            bad.append(f"{key}: обоснование короче {_MIN_JUSTIFICATION_LEN} символов")
        elif not any(token in text for token in _TRACE_TOKENS):
            bad.append(f"{key}: нет ссылки на карточку/ADR/док ({', '.join(_TRACE_TOKENS)})")
    assert not bad, "негодные обоснования в _ALLOWED_EXCLUSIONS:\n" + "\n".join(bad)


def test_excluded_paths_exist() -> None:
    """Мёртвый игнор (путь не существует) — сразу красный."""
    dead = [
        e
        for e in _EXCLUSIONS
        if e.flag in _PATH_FLAGS and not _excluded_path(e).exists()
    ]
    assert not dead, (
        "исключение указывает на несуществующий путь — оно ничего не выключает "
        "и вводит читателя workflow в заблуждение:\n"
        + "\n".join(
            f"  {e.workflow}: {e.flag}={e.value} (cwd={e.cwd or '<корень>'}) "
            f"→ нет {_excluded_path(e)}"
            for e in dead
        )
    )


def test_registry_has_no_stale_entries() -> None:
    """Убрали игнор из workflow — уберите и запись, иначе реестр протухает."""
    live = {e.key for e in _EXCLUSIONS}
    stale = [key for key in _ALLOWED_EXCLUSIONS if key not in live]
    assert not stale, (
        "в _ALLOWED_EXCLUSIONS есть записи, которых больше нет ни в одном workflow: "
        f"{stale}"
    )


# ── Положительные контроли разбора (без них гейт может быть зелёным «вслепую») ─
_SYNTHETIC_IGNORE = """
jobs:
  test:
    steps:
      - name: Run unit tests
        run: |
          python -m pytest spa_core/tests/ -q \\
            --ignore=spa_core/tests/test_golive_checker.py
"""

_SYNTHETIC_CD = """
jobs:
  test:
    steps:
      - name: Run unit tests
        run: |
          cd spa_core
          python -m pytest tests/ -q --ignore=tests/test_golive_checker.py
"""

_SYNTHETIC_INLINE = """
jobs:
  test:
    steps:
      - run: pytest tests/ --deselect tests/test_x.py::TestY -k "not slow"
"""

_SYNTHETIC_MYPY = """
jobs:
  lint:
    steps:
      - name: mypy
        run: |
          python -m mypy spa_core/ \\
            --ignore-missing-imports \\
            --no-error-summary
"""


def test_parser_finds_multiline_ignore() -> None:
    found = collect_exclusions({"synthetic.yml": _SYNTHETIC_IGNORE})
    assert [(e.flag, e.value, e.cwd) for e in found] == [
        ("--ignore", "spa_core/tests/test_golive_checker.py", "")
    ]


def test_parser_resolves_step_cwd() -> None:
    """``cd spa_core`` + ``--ignore=tests/x`` = ``spa_core/tests/x`` (иначе путь ищут не там)."""
    found = collect_exclusions({"synthetic.yml": _SYNTHETIC_CD})
    assert len(found) == 1
    assert found[0].cwd == "spa_core"
    assert _excluded_path(found[0]) == _REPO_ROOT / "spa_core/tests/test_golive_checker.py"


def test_parser_finds_inline_deselect_and_negative_k() -> None:
    found = collect_exclusions({"synthetic.yml": _SYNTHETIC_INLINE})
    assert {(e.flag, e.value) for e in found} == {
        ("--deselect", "tests/test_x.py::TestY"),
        ("-k", "not slow"),
    }


def test_parser_ignores_non_pytest_commands() -> None:
    """``--ignore-missing-imports`` у mypy — не исключение тестов (живой ci-lite.yml)."""
    assert collect_exclusions({"synthetic.yml": _SYNTHETIC_MYPY}) == []


def test_dead_ignore_is_detected() -> None:
    """Контроль правила «путь существует»: несуществующий файл ловится."""
    dead = collect_exclusions(
        {"synthetic.yml": _SYNTHETIC_IGNORE.replace(
            "test_golive_checker.py", "test_does_not_exist_ever.py")}
    )
    assert len(dead) == 1
    assert not _excluded_path(dead[0]).exists()


def test_unregistered_exclusion_would_be_caught() -> None:
    """Контроль правила «только из реестра»: синтетическое исключение не в реестре."""
    found = collect_exclusions({"synthetic.yml": _SYNTHETIC_CD})
    assert [e for e in found if e.key not in _ALLOWED_EXCLUSIONS] == found


def test_scanner_is_fail_closed_on_empty_input() -> None:
    """Пустой вход не должен читаться как «исключений нет, всё хорошо»."""
    assert _pytest_command_count({}) == 0
    assert _pytest_command_count({"empty.yml": "jobs:\n  test:\n    steps: []\n"}) == 0


def test_real_workflows_contain_expected_suites() -> None:
    """Живой контроль: разбор реально видит команды CI, а не пустоту."""
    commands = [
        command
        for text in _WORKFLOW_FILES.values()
        for block in _run_blocks(text)
        for command in block
        if _PYTEST_RE.search(command)
    ]
    assert any("spa_core/tests" in c or "cd spa_core" in c or "tests/" in c for c in commands), (
        "в workflow'ах не найдено ни одного прогона известных сюит — проверьте разбор"
    )


def test_golive_checker_tests_are_not_excluded_anywhere() -> None:
    """Точечный пин находки цикла #46: гейт go-live не исключается ни в одном workflow.

    Именно эти 43 теста были невидимо выключены в обеих сюитах, а гейт публикует
    «29/29 READY» наружу — регрессия здесь не должна проходить CI молча.
    """
    excluded = [e for e in _EXCLUSIONS if "test_golive_checker" in e.value]
    assert not excluded, (
        "тесты гейта готовности снова исключены из CI:\n"
        + "\n".join(f"  {e.workflow}: {e.flag}={e.value}" for e in excluded)
    )


def test_cwd_does_not_leak_between_run_steps() -> None:
    """Каждый шаг ``run:`` стартует из корня workspace, а не там, где кончился прошлый.

    Без сброса `cd` мёртвый путь второго шага `ci.yml` выглядел бы живым.
    """
    text = (
        "        run: |\n"
        "          cd spa_core\n"
        "          python -m pytest tests/ --ignore=tests/x.py\n"
        "        run: |\n"
        "          python -m pytest tests/ --ignore=tests/y.py\n"
    )
    found = collect_exclusions({"synthetic.yml": text})
    assert [(e.value, e.cwd) for e in found] == [("tests/x.py", "spa_core"), ("tests/y.py", "")]


def test_parser_ignores_positive_selectors() -> None:
    """Точечный прогон (`-k "head"` в живом `proof-gate.yml`) — законная форма, не находка."""
    text = '        run: python3 -m pytest spa_core/tests/test_dd_pack.py -k "head" -q\n'
    assert collect_exclusions({"synthetic.yml": text}) == []


def test_parser_does_not_match_yaml_paths_ignore_key() -> None:
    """``paths-ignore:`` — ключ триггера workflow, а не флаг pytest."""
    text = "on:\n  push:\n    paths-ignore:\n      - 'docs/**'\n      - '**.md'\n"
    assert collect_exclusions({"synthetic.yml": text}) == []


def test_parser_skips_commented_out_invocations() -> None:
    """Закомментированная команда ничего не выключает — находкой быть не должна."""
    text = (
        "        run: |\n"
        "          # python -m pytest tests/ --ignore=tests/x.py   # старый вариант\n"
        "          python -m pytest tests/ -q\n"
    )
    assert collect_exclusions({"synthetic.yml": text}) == []
