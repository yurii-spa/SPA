# LLM_FORBIDDEN
"""spa_core/tests/test_ci_covers_every_test_dir.py — гейт КЛАССА «тесты есть, но их никто не гоняет».

**Зачем (цикл #74, 2026-08-01, карточка `agent-ci-never-runs-scripts-tests-dir`).**
Каталог `scripts/tests/` — 191 тест, среди них репетиция стоп-крана
(`test_kill_switch_drill.py`), страж инварианта #3 «LLM запрещён»
(`test_lint_llm_forbidden.py`), гейт деплоя агентов инварианта #12
(`test_check_agent_before_deploy.py`), преflight гейта go-live и сам ратчет
неиспользуемых импортов — **не запускался в CI ни разу**: оба workflow называли только
`tests/` и `spa_core/tests/`. Из-за этого ратчет стоял КРАСНЫМ (70 при потолке 36), а CI
на `main` был зелёным. Тем же измерением нашлись ещё два таких каталога:
`spa_core/analytics/gross_of/` (295 зелёных тестов) и `research/cards/` (7).

**Чем это отличается от гейта цикла #46** (`test_ci_test_exclusions.py`, соседний файл).
Тот ловит ЯВНОЕ выключение: `--ignore` / `--ignore-glob` / `--deselect` / отрицание в
`-k`/`-m` внутри команды pytest. Здесь выключения нет вовсе — каталог просто никогда не
называли, и по построению соседнего гейта это невидимо: нечего «исключать», если тебя не
включали. Поэтому нужен второй вопрос: **не «что выключили», а «что не включили»**.

Разбор workflow НЕ дублируется: парсер (`run:`-блоки, block-scalar, продолжения `\\`,
`cd` внутри шага, кавычки через `shlex`) переиспользуется из `test_ci_test_exclusions`
— чинить его придётся в одном месте. Цикл #47 закрыл ровно такой дефект (встроенная
копия арифметики этажом выше), повторять его здесь незачем.

**Fail-CLOSED (инвариант #2).** Сканер, не нашедший ни одной команды pytest, или обход,
не нашедший ни одного каталога с тестами, считается КРАСНЫМ: «ничего не нашёл» здесь
неотличимо от «сканер сломался», а молчаливое «всё покрыто» — это ровно класс
#29/#31/#35–#38/#40 (утверждение о проверке, которой не было).

**Как добавить каталог в исключения.** Только через `_ALLOWED_UNCOVERED` — с
обоснованием, в котором есть прослеживаемая ссылка (карточка / ADR / `docs/`).
Протухшая запись (каталог исчез или уже покрыт) тоже краснит: реестр не должен врать.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"


# ── Переиспользование парсера соседнего гейта (без sys.path-допущений) ────────
def _load_sibling(name: str):
    """Загрузить соседний тест-модуль ПО ПУТИ.

    Через `import` было бы хрупко: `ci.yml` запускает набор как
    ``cd spa_core && pytest tests/``, а `test.yml` — как ``pytest spa_core/tests/``;
    в этих двух случаях модуль оказывается в разных пакетах. Путь одинаков всегда.
    """
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_ci_gate_{name}", path)
    assert spec and spec.loader, f"не удалось загрузить соседний модуль {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_exclusions = _load_sibling("test_ci_test_exclusions")
_run_blocks = _exclusions._run_blocks
_join_continuations = _exclusions._join_continuations
_tokenize = _exclusions._tokenize
_normalize_cwd = _exclusions._normalize_cwd
_unquote = _exclusions._unquote
_CD_RE = _exclusions._CD_RE
_PYTEST_RE = _exclusions._PYTEST_RE
# «Это ЗАПУСК pytest, а не упоминание его в чужой команде» + отрезание
# хвоста-комментария — общее определение соседа (цикл #305, карточка
# `inbox-razbor-workflow-chitaet-shag-pip-install`). Копии здесь БОЛЬШЕ НЕТ:
# до #305 `strip_inline_comment` жил в этом файле и звался только разбором
# окружения, а общий разбор целей продолжал читать комментарий как каталоги.
pytest_run_segments = _exclusions.pytest_run_segments
is_pytest_run = _exclusions.is_pytest_run
strip_inline_comment = _exclusions.strip_inline_comment


# ── Реестр осознанно НЕ запускаемых каталогов ────────────────────────────────
# ключ — путь относительно корня репо; значение — обоснование со ссылкой.
# Каждая запись здесь измерена, а не предположена (цикл #74).
_ALLOWED_UNCOVERED: dict[str, str] = {
    "attic/scripts": (
        "attic/ — ретированный код-надгробие. Здесь лежат тесты недельного отчёта "
        "доказательной базы, уехавшего в архив вместе со своим предметом: решение "
        "владельца 2026-08-25 (вариант 1), ADR-140 — оживить ТОЛЬКО тридцатидневный "
        "отчёт. Держать их в наборе CI значило бы гонять проверки архивированного "
        "кода; удалять — терять возможность вернуть отчёт одной командой, которую "
        "называет attic/MANIFEST.md. Карточка "
        "owner-decision-tri-otcheta-o-dokazatelnoi-baze-treka-mo."
    ),
    "attic/alerts": (
        "attic/ — то же самое для ежедневного отчёта в Телеграм: архивирован тем же "
        "решением владельца (ADR-140), тесты уехали за предметом. Возврат — одной "
        "командой из attic/MANIFEST.md."
    ),
    "attic/modules/tests": (
        "attic/ — ретированный код-надгробие; модули там поднимают ImportError по "
        "построению, набор не собирается (те самые ошибки сборки, что упомянуты в "
        "docs/STATE.md для attic/ и scripts/archive/). Карточка "
        "agent-ci-never-runs-scripts-tests-dir."
    ),
    "scripts/archive": (
        "scripts/archive/ — архив; оба workflow и так держат его в paths-ignore, "
        "запускать архивные тесты нечего. Карточка agent-ci-never-runs-scripts-tests-dir."
    ),
    "scripts": (
        "Единственный test_*.py верхнего уровня scripts/ — scripts/test_coverage_report.py, "
        "и это НЕ тесты, а скрипт-отчёт о покрытии (MP-1519): pytest собирает по нему "
        "0 тестов (измерено). Каталог scripts/tests/ покрыт отдельно. Карточка "
        "agent-ci-never-runs-scripts-tests-dir."
    ),
}

# Каталоги, которые не обходим вообще (не часть репо-дерева исходников).
_SKIP_DIR_NAMES = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
                   "dist", "build", ".mypy_cache", ".claude"}

# Флаги pytest, съедающие СЛЕДУЮЩИЙ токен: иначе их значение (`short`, `no:randomly`,
# `not slow`) попало бы в позиционные аргументы и «покрыло» бы несуществующий каталог.
_VALUE_FLAGS = {"-k", "-m", "-p", "-n", "-c", "-o", "--tb", "--ignore", "--ignore-glob",
                "--deselect", "--timeout", "--timeout-method", "--maxfail", "--rootdir",
                "--junitxml", "--durations", "--import-mode", "-W", "--log-level"}

_TRACE_TOKENS = ("agent-", "own-", "owner-decision-", "ADR", "docs/", "MP-")
_MIN_JUSTIFICATION_LEN = 30

# Перенаправления оболочки (`2>&1`, `2>/dev/null`, `> out.txt`): `shlex` отдаёт их
# обычными словами, и до #305 они оседали в целях. Аргументом pytest они не являются
# никогда. Отдельный токен-цель (`> out.txt` через пробел) съедается вместе с оператором.
_REDIRECT_RE = re.compile(r"^\d*(?:>>|>|<)")


def discover_test_dirs(root: Path) -> set[str]:
    """Каталоги с файлами ``test_*.py``, путями относительно корня репо."""
    found: set[str] = set()
    for path in root.rglob("test_*.py"):
        # Скип-имена проверяются по ОТНОСИТЕЛЬНЫМ частям пути: абсолютные parts
        # включают компоненты ВНЕ репо, и checkout, живущий, например, под
        # `.claude/worktrees/<name>/`, скипал бы ВСЁ дерево → пустой обход →
        # ложный fail-CLOSED. Внутрирепозиторные копии (`.claude/worktrees/...`
        # внутри самого репо) по-прежнему скипаются.
        if any(part in _SKIP_DIR_NAMES for part in path.relative_to(root).parts):
            continue
        rel = path.parent.relative_to(root).as_posix()
        found.add(rel if rel != "." else "")
    return found


def block_pytest_targets(block: list[str]) -> set[str]:
    """Позиционные цели pytest в ОДНОМ ``run:``-блоке, с учётом ``cd`` внутри шага.

    Вынесено из :func:`collect_pytest_targets` циклом #304, чтобы разбор окружения
    (``ci_pytest_env``) спрашивал «какие каталоги гоняет ЭТОТ шаг» тем же кодом, а не
    второй копией цикла по токенам. Урок цикла #47 — встроенная копия расходится с
    оригиналом не «если», а «когда».
    """
    # Каждый ``run:`` — новая оболочка из корня workspace ⇒ cwd сбрасывается,
    # иначе `cd spa_core` предыдущего шага «покрыл» бы путь следующего.
    targets: set[str] = set()
    cwd = ""
    for command in block:
        if command.lstrip().startswith("#"):
            continue                          # закомментированный вызов ничего не гоняет
        cd_match = _CD_RE.match(command)
        if cd_match:
            cwd = _normalize_cwd(cwd, cd_match.group(1))
            continue
        # Цели берутся ТОЛЬКО из сегментов, которые действительно запускают pytest
        # (#305): шаг `pip install pytest …` вызовом не является, а хвост конвейера
        # `… | tee test_output.txt` — не аргумент pytest.
        for tokens in pytest_run_segments(command):
            skip_next = False
            seen_pytest = False
            for token in tokens:
                if skip_next:
                    skip_next = False
                    continue
                if not seen_pytest:
                    # пропускаем `python3 -m pytest` / `pytest`
                    if token.endswith("pytest"):
                        seen_pytest = True
                    continue
                if token.startswith("-"):
                    if "=" not in token and token in _VALUE_FLAGS:
                        skip_next = True
                    continue
                if _REDIRECT_RE.match(token):
                    # голый оператор (`>`/`2>`) уносит и СЛЕДУЮЩИЙ токен — это имя файла
                    if _REDIRECT_RE.fullmatch(token):
                        skip_next = True
                    continue
                raw = _unquote(token).split("::")[0]
                if not raw or raw.startswith("$"):
                    continue
                targets.add(_normalize_cwd(cwd, raw))
    return targets


def collect_pytest_targets(files: dict[str, str]) -> set[str]:
    """Позиционные цели всех вызовов pytest в workflow, с учётом ``cd`` в шаге.

    ``files``: {имя файла: текст} — параметром, чтобы гейт проверялся положительными
    контролями на синтетическом YAML, а не только на живом дереве.
    """
    targets: set[str] = set()
    for _name, text in sorted(files.items()):
        for block in _run_blocks(text):
            targets |= block_pytest_targets(block)
    return targets


def uncovered_test_dirs(test_dirs: set[str], targets: set[str]) -> set[str]:
    """Каталоги, которые не назван ни один вызов pytest — ни сам, ни его предок."""
    uncovered: set[str] = set()
    for directory in test_dirs:
        parts = directory.split("/") if directory else []
        ancestors = {"/".join(parts[:i]) for i in range(len(parts) + 1)}
        ancestors.discard("")
        ancestors.add(directory)
        if not (ancestors & targets):
            uncovered.add(directory)
    return uncovered


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
        if is_pytest_run(command) and not command.lstrip().startswith("#")
    )


# ── ОКРУЖЕНИЕ, под которым CI зовёт pytest (цикл #304) ───────────────────────
# «Те же каталоги» и «тот же прогон» — РАЗНЫЕ утверждения, и второе никем не
# проверялось. Замер #304 на `spa_core/tests/test_cycle_nav_determinism.py`
# (тот самый файл, который карточка звала «15 % стены приёмки»):
#
#   SPA_ENV=ci  →  14.30 с,     20 763 потока   ← так гоняет CI
#   без SPA_ENV → 125.30 с,  679 762 потока     ← так предписывал CLAUDE.md
#
# Разница не в тестах, а в рантайме: `cycle_runner` под `SPA_ENV=ci` осознанно
# пропускает advisory-слой Tier B (комментарий на месте пропуска), и без этой
# переменной каждый смоделированный цикл поднимает ~479 advisory-модулей. Оба
# прогона — 6 passed: набор один, прогон разный.
#
# Разбор YAML здесь настоящий (`yaml.safe_load`), а не второй самодельный
# индент-парсер: прецедент — `tests/test_ci_workflows.py`, и pyyaml стоит в
# списке зависимостей CI (`ci.yml`). Импорт fail-CLOSED: без pyyaml гейт
# КРАСНЕЕТ с внятным сообщением, а не пропускается молча — молчаливый скип
# здесь был бы ровно тем классом, ради которого файл написан.
def _triggers_on_main(doc: dict) -> bool:
    """Гоняется ли workflow на push/pull_request в main (то есть ГЕЙТИТ ли он main).

    Ключ ``on`` YAML 1.1 разбирает как булево ``True`` — спрашиваем оба написания, иначе
    ответ был бы «ни один workflow не гейтит main», то есть тихий fail-OPEN.
    """
    on = doc.get("on", doc.get(True))
    if isinstance(on, str):
        return on in ("push", "pull_request")
    if isinstance(on, list):
        return bool({"push", "pull_request"} & set(on))
    if isinstance(on, dict):
        return bool({"push", "pull_request"} & set(on))
    return False


def pytest_steps(text: str) -> list[tuple[set[str], dict[str, str]]]:
    """``(цели, env)`` каждого шага workflow, который зовёт pytest.

    ``env`` шага — job-level, перекрытый step-level (ровно как их складывает Actions).
    Хвосты-комментарии из команд убраны (см. :func:`strip_inline_comment`).
    """
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover — в CI pyyaml установлен всегда
        raise AssertionError(
            "для разбора окружения workflow нужен pyyaml (он есть в списке зависимостей "
            f"CI в ci.yml); молчаливый скип здесь запрещён, инвариант #2: {exc}"
        ) from exc

    doc = yaml.safe_load(text) or {}
    if not isinstance(doc, dict) or not _triggers_on_main(doc):
        return []
    found: list[tuple[set[str], dict[str, str]]] = []
    for job in (doc.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        job_env = {str(k): str(v) for k, v in (job.get("env") or {}).items()}
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            lines = [strip_inline_comment(ln) for ln in str(step.get("run") or "").splitlines()]
            targets = block_pytest_targets(_join_continuations(lines))
            if not targets:
                continue
            step_env = {str(k): str(v) for k, v in (step.get("env") or {}).items()}
            found.append((targets, {**job_env, **step_env}))
    return found


def ci_pytest_env(files: dict[str, str], gating_dirs: set[str]) -> dict[str, str]:
    """Окружение, под которым CI гоняет ГЕЙТЯЩИЙ набор — пересечение по имени И значению.

    **Почему только гейтящие шаги.** Первый замер #304 брал пересечение по ВСЕМ шагам с
    pytest и получил пусто: `proof-gate.yml`, `spa-run.yml` и шаг мета-проверки в `ci.yml`
    окружения не ставят вовсе, и один такой шаг обнулял бы ответ. Но предписанная команда
    повторяет не их, а ровно те шаги, что гоняют гейтящие каталоги, — вопрос ставится о них.

    **Почему пересечение, а не объединение.** Переменная, которую ставит один шаг из трёх,
    — особенность шага, а не свойство «прогона CI»; требовать её от предписанной команды
    значило бы красить гейт на ровном месте. Требуем ровно то, без чего локальный прогон
    заведомо не тот же самый.

    ``files``/``gating_dirs`` — параметрами, чтобы гейт проверялся положительными
    контролями на синтетическом YAML, а не только на живом дереве.
    """
    envs: list[dict[str, str]] = []
    for _name, text in sorted(files.items()):
        for targets, env in pytest_steps(text):
            # Каталог ЦЕЛИКОМ, а не файл внутри него: `proof-gate.yml` тоже гейтит main,
            # но зовёт четыре ИМЕНОВАННЫХ файла из `spa_core/tests/` под своим окружением,
            # и предписанная команда воспроизводит не его, а прогон каталогов.
            if targets & gating_dirs:
                envs.append(env)
    if not envs:
        return {}
    shared = dict(envs[0])
    for env in envs[1:]:
        shared = {k: v for k, v in shared.items() if env.get(k) == v}
    return shared


def gating_dirs(targets: set[str], root: Path) -> set[str]:
    """Из целей CI — только те, что существуют как каталоги (файлы и мусор отброшены)."""
    return {t.rstrip("/") for t in targets if (root / t).is_dir()}


_WORKFLOW_FILES = _read_workflows()
_TARGETS = collect_pytest_targets(_WORKFLOW_FILES)
_TEST_DIRS = discover_test_dirs(_REPO_ROOT)
_GATING_DIRS = gating_dirs(_TARGETS, _REPO_ROOT)
_CI_PYTEST_ENV = ci_pytest_env(_WORKFLOW_FILES, _GATING_DIRS)


# ── Проверки над живым деревом ────────────────────────────────────────────────
def test_workflow_tree_is_scannable() -> None:
    """Fail-CLOSED: сканер, не нашедший ни одной команды pytest, — сломан, а не «чист»."""
    assert _WORKFLOW_FILES, f"в {_WORKFLOWS_DIR} нет ни одного workflow — сканировать нечего"
    count = _pytest_command_count(_WORKFLOW_FILES)
    assert count > 0, (
        "ни одной команды pytest не найдено ни в одном workflow. Это НЕ значит «всё "
        "покрыто» — это значит, что разбор сломался (или CI перестал гонять тесты)."
    )
    assert _TARGETS, (
        f"найдено {count} команд pytest, но ни одной позиционной цели — разбор аргументов "
        "сломан; молчаливое «покрыто» здесь запрещено."
    )


def test_test_dir_discovery_is_not_empty() -> None:
    """Fail-CLOSED: обход, не нашедший тестов, — сломанный обход."""
    assert _TEST_DIRS, "не найдено ни одного каталога с test_*.py — обход дерева сломан"


def test_every_test_dir_is_run_by_ci() -> None:
    """Каждый каталог с тестами обязан запускаться CI — или стоять в реестре с обоснованием.

    КРАСНЫЙ здесь означает: тесты написаны, лежат в репозитории и НЕ выполняются.
    Чинить надо добавлением каталога в workflow, а не записью в реестр «чтобы позеленело»
    (инвариант #16).
    """
    uncovered = uncovered_test_dirs(_TEST_DIRS, _TARGETS)
    unregistered = sorted(uncovered - set(_ALLOWED_UNCOVERED))
    assert not unregistered, (
        "каталоги с тестами, которые CI не запускает НИ ОДНОЙ командой pytest:\n  "
        + "\n  ".join(unregistered)
        + "\nДобавь их в workflow. Реестр _ALLOWED_UNCOVERED — только для осознанных "
          "исключений с прослеживаемым обоснованием."
    )


def test_registry_entries_have_traceable_justification() -> None:
    """Каждая запись реестра — с обоснованием и ссылкой на карточку/ADR/doc."""
    for directory, why in sorted(_ALLOWED_UNCOVERED.items()):
        assert len(why) >= _MIN_JUSTIFICATION_LEN, (
            f"{directory}: обоснование слишком короткое — нужна причина, а не отписка"
        )
        assert any(token in why for token in _TRACE_TOKENS), (
            f"{directory}: в обосновании нет прослеживаемой ссылки "
            f"(одно из {_TRACE_TOKENS})"
        )


def test_registry_has_no_stale_entries() -> None:
    """Реестр не должен врать: запись про исчезнувший или уже покрытый каталог — красная."""
    uncovered = uncovered_test_dirs(_TEST_DIRS, _TARGETS)
    stale = sorted(set(_ALLOWED_UNCOVERED) - uncovered)
    assert not stale, (
        "протухшие записи _ALLOWED_UNCOVERED (каталог исчез или уже запускается в CI) — "
        f"удали их: {stale}"
    )


# ── Положительные контроли: гейт обязан краснеть там, где должен ──────────────
_SYNTHETIC_SIMPLE = """
jobs:
  t:
    steps:
      - name: run
        run: python -m pytest tests/ -q --tb=short -p no:randomly
"""

_SYNTHETIC_CD = """
jobs:
  t:
    steps:
      - name: run
        run: |
          cd spa_core
          python -m pytest tests/ -q
"""

_SYNTHETIC_VALUE_FLAGS = """
jobs:
  t:
    steps:
      - name: run
        run: |
          python -m pytest scripts/tests/ -k "not slow" --timeout 180 \\
            --timeout-method=thread -p no:randomly
"""

_SYNTHETIC_COMMENTED = """
jobs:
  t:
    steps:
      - name: run
        run: |
          # python -m pytest scripts/tests/ -q
          echo skip
"""

_SYNTHETIC_NO_PYTEST = """
jobs:
  t:
    steps:
      - name: run
        run: python3 scripts/pre_deploy_check.py
"""


def test_parser_finds_a_plain_target() -> None:
    assert collect_pytest_targets({"w.yml": _SYNTHETIC_SIMPLE}) == {"tests"}


def test_parser_resolves_step_cwd() -> None:
    """``cd spa_core`` + ``pytest tests/`` — это spa_core/tests, а не tests."""
    targets = collect_pytest_targets({"w.yml": _SYNTHETIC_CD})
    assert targets == {"spa_core/tests"}


def test_flag_values_are_not_mistaken_for_targets() -> None:
    """`-k "not slow"`, `--timeout 180`, `-p no:randomly` — значения флагов, не каталоги."""
    targets = collect_pytest_targets({"w.yml": _SYNTHETIC_VALUE_FLAGS})
    assert targets == {"scripts/tests"}, targets


def test_commented_out_pytest_covers_nothing() -> None:
    """Закомментированный вызов ничего не запускает — и покрытием считаться не может."""
    assert collect_pytest_targets({"w.yml": _SYNTHETIC_COMMENTED}) == set()


def test_scanner_is_fail_closed_on_input_without_pytest() -> None:
    files = {"w.yml": _SYNTHETIC_NO_PYTEST}
    assert _pytest_command_count(files) == 0
    assert collect_pytest_targets(files) == set()


def test_ancestor_target_covers_nested_dir() -> None:
    """`pytest tests/` покрывает и `tests/bee` — вложенность это НЕ находка."""
    assert uncovered_test_dirs({"tests", "tests/bee"}, {"tests"}) == set()


def test_uncovered_dir_is_detected() -> None:
    """Главный контроль: каталог, которого нет ни в одной команде, — находка."""
    assert uncovered_test_dirs({"tests", "scripts/tests"}, {"tests"}) == {"scripts/tests"}


def test_file_target_does_not_cover_its_directory() -> None:
    """`pytest tests/test_x.py` — это один файл, а не весь каталог."""
    assert uncovered_test_dirs({"tests"}, {"tests/test_x.py"}) == {"tests"}


# ── Контроли цикла #305: установка ≠ запуск, комментарий ≠ цель ───────────────
# Каждый — воспроизведение живой аварии, а не украшение. Все на БЛОЧНОМ скаляре
# (`run: |`): в плоском `#` съедает сам YAML, и такой контроль зелен под любой
# мутацией (ловушка, которую #304 поймал у себя).
# Строка взята из живого `ci.yml` дословно, включая хвост-комментарий со словами
# `scripts/tests/`.
_SYNTHETIC_PIP_INSTALL = """
jobs:
  t:
    steps:
      - name: deps
        run: |
          pip install pytest pytest-asyncio pyyaml numpy bcrypt mypy==2.1.0  # pyflakes = the unused-import ratchet in scripts/tests/ shells out to it
"""

_SYNTHETIC_PIP_INSTALL_VIA_M = """
jobs:
  t:
    steps:
      - name: deps
        run: |
          python3 -m pip install --quiet pytest
"""

_SYNTHETIC_PIPE_TAIL = """
jobs:
  t:
    steps:
      - name: run
        run: |
          python -m pytest spa_core/tests/ -x -q 2>&1 | tee test_output.txt
"""

_SYNTHETIC_IF_PREFIX = """
jobs:
  t:
    steps:
      - name: probe
        run: |
          if python3 -m pytest spa_core/tests/test_dd_pack.py --collect-only -q 2>/dev/null | grep -q "head_live"; then
            echo yes
          fi
"""

_SYNTHETIC_COMMENT_TAIL_ON_REAL_RUN = """
jobs:
  t:
    steps:
      - name: run
        run: |
          python -m pytest tests/ -q  # раньше гоняли и scripts/tests/, см. карточку
"""


def test_pip_install_is_not_a_pytest_run() -> None:
    """Шаг УСТАНОВКИ зависимостей не запускает ничего — целей у него нет.

    Живой дефект: `pip install pytest pyyaml numpy …` давал цели `pyyaml`, `numpy`,
    `bcrypt`, а из хвоста-комментария — `the`, `to` и настоящий каталог `scripts/tests`.
    """
    files = {"w.yml": _SYNTHETIC_PIP_INSTALL}
    assert collect_pytest_targets(files) == set()
    assert _pytest_command_count(files) == 0


def test_pip_install_via_dash_m_is_not_a_pytest_run() -> None:
    """`python3 -m pip install --quiet pytest` — тоже установка (живой proof-gate.yml).

    Утверждение о ЧИСЛЕ вызовов здесь обязательно: в этой команде `pytest` — последний
    токен, поэтому целей у неё нет и при полностью сломанном разборе. Проверка одних
    только целей была бы зелёной под КАЖДОЙ мутацией — ровно то украшение, которое
    цикл #304 нашёл у себя своей же мутацией. Мерим то, что действительно меняется.
    """
    files = {"w.yml": _SYNTHETIC_PIP_INSTALL_VIA_M}
    assert collect_pytest_targets(files) == set()
    assert _pytest_command_count(files) == 0


def test_pipe_tail_is_not_a_pytest_argument() -> None:
    """`… 2>&1 | tee test_output.txt` — хвост конвейера, а не цели pytest."""
    assert collect_pytest_targets({"w.yml": _SYNTHETIC_PIPE_TAIL}) == {"spa_core/tests"}


def test_shell_prefix_does_not_hide_a_real_run() -> None:
    """Обратный контроль: `if python3 -m pytest …` — НАСТОЯЩИЙ вызов, терять его нельзя.

    Без этого «позиционное» правило поехало бы в fail-OPEN: пропущенный вызов для
    соседнего гейта исключений означает пропущенное исключение тестов.
    """
    targets = collect_pytest_targets({"w.yml": _SYNTHETIC_IF_PREFIX})
    assert targets == {"spa_core/tests/test_dd_pack.py"}, targets


def test_comment_tail_on_a_real_run_is_not_a_target() -> None:
    """Слова в хвосте-комментарии настоящего вызова целями не становятся."""
    assert collect_pytest_targets({"w.yml": _SYNTHETIC_COMMENT_TAIL_ON_REAL_RUN}) == {"tests"}


def test_live_targets_are_real_paths_only() -> None:
    """Обе стороны замера #305 на ЖИВОМ дереве, а не на синтетике.

    До правки: 92 цели, из них реальных путей 10. Утверждение здесь — не «ровно 11»
    (это ратчет на пустом месте, workflow меняются), а КЛАСС: каждая цель обязана
    быть путём в репозитории. Мусорная цель безобидна лишь по знаку покрытия; она
    же выдаёт каталог за покрытый прозой и обнуляет любой вопрос «а под чем гоняем».
    """
    junk = sorted(t for t in _TARGETS if not (_REPO_ROOT / t).exists())
    assert not junk, (
        f"в целях CI есть то, чего нет в репозитории: {junk}. Разбор снова читает "
        "чужие слова как цели pytest."
    )


def test_gating_dirs_survived_the_tightening() -> None:
    """Обратный контроль ужатия: ни один реально гоняемый каталог не потерян.

    Если этот тест покраснеет — это НАХОДКА (CI перестал гонять каталог), а не повод
    откатить правку разбора.
    """
    assert _GATING_DIRS == {
        "tests", "spa_core/tests", "scripts/tests",
        "spa_core/analytics/gross_of", "research/cards",
    }, sorted(_GATING_DIRS)
