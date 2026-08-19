# LLM_FORBIDDEN
"""spa_core/tests/test_prescribed_run_matches_ci.py — третий вопрос о тестах.

**Зачем (цикл #189, 2026-08-10, карточка `inbox-ci-spa-tests-krasnyi-minimum-8-kommitov`).**
Workflow `SPA Tests` был **красным на 8 коммитах подряд** (`70bb71d6` … `8729e440`), и
этого не увидела ни одна сессия. Не потому, что кто-то смотрел и промолчал: `CLAUDE.md`
предписывал прогон `python3 -m pytest spa_core/tests/ -v`, каталог `tests/` (13 045 тестов)
в него не входил, и сессия честно отчитывалась «мой набор зелёный» — отвечая на СВОЙ
вопрос, а не на нужный «репозиторий зелёный». Замер цикла #188: 93 629 зелёных
`spa_core/tests` при 6 падениях и 2 ошибках в `tests/`.

**Чем этот гейт отличается от двух соседних — три вопроса, три сторожа.**

| Вопрос | Кто отвечает |
|---|---|
| Что из тестов **выключили** флагом (`--ignore`/`--deselect`/`-k not …`)? | `test_ci_test_exclusions.py` (цикл #46) |
| Какой каталог с тестами CI **не включил** ни разу? | `test_ci_covers_every_test_dir.py` (цикл #74) |
| **Покрывает ли предписанная человеку/сессии команда то, что гейтит CI?** | этот файл |

Первые два смотрят на CI и молчат про `CLAUDE.md`; расхождение между «что гоняет CI» и
«что велено гонять перед пушем» по построению невидимо обоим. Именно в этот зазор и
провалились восемь коммитов.

**Fail-CLOSED (инвариант #2).** Ни одной команды pytest в `CLAUDE.md` ⇒ КРАСНЫЙ: «не нашёл»
здесь неотличимо от «парсер сломался», а молчаливое «всё покрыто» — это ровно тот класс
дефектов, ради которого файл написан. Пустой набор целей CI — тоже КРАСНЫЙ.

**Разбор команд НЕ дублируется:** токенизация и распознавание вызова pytest берутся из
`test_ci_test_exclusions`, сбор целей CI — из `test_ci_covers_every_test_dir`. Чинить
придётся в одном месте (урок цикла #47 о встроенной копии).
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLAUDE_MD = _REPO_ROOT / "CLAUDE.md"


def _load_sibling(name: str):
    """Загрузить соседний тест-модуль ПО ПУТИ (не через import).

    `ci.yml` запускает набор как ``cd spa_core && pytest tests/``, а `test.yml` — как
    ``pytest spa_core/tests/``: в этих двух случаях модуль оказывается в разных пакетах,
    и `import` был бы хрупок. Путь одинаков всегда.
    """
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_prescribed_gate_{name}", path)
    assert spec and spec.loader, f"не удалось загрузить соседний модуль {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_coverage = _load_sibling("test_ci_covers_every_test_dir")
_exclusions = _load_sibling("test_ci_test_exclusions")

_tokenize = _exclusions._tokenize
_unquote = _exclusions._unquote
_PYTEST_RE = _exclusions._PYTEST_RE
_VALUE_FLAGS = _coverage._VALUE_FLAGS


# ── Реестр осознанно НЕ предписанных каталогов ────────────────────────────────
# Ключ — путь относительно корня репо; значение — обоснование со ссылкой.
# Пусто по построению: сегодня предписанная команда покрывает ВСЕ пять каталогов,
# которые гейтит CI. Запись сюда — осознанное решение с прослеживаемой ссылкой,
# а не способ погасить красный (инвариант #16).
_ALLOWED_UNPRESCRIBED: dict[str, str] = {}

# ── Реестр осознанно НЕ предписанных переменных окружения (цикл #304) ─────────
# Тот же договор, что и выше: запись — осознанное решение с прослеживаемой ссылкой,
# а не способ погасить красный (инвариант #16). Пусто по построению.
_ALLOWED_MISSING_ENV: dict[str, str] = {}

_TRACE_TOKENS = ("agent-", "own-", "owner-decision-", "inbox-", "ADR", "docs/", "MP-", "цикл #")
_MIN_JUSTIFICATION_LEN = 30

_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def prescribed_targets(text: str) -> set[str]:
    """Позиционные цели всех вызовов pytest в тексте (``CLAUDE.md``).

    ``text`` — параметром, чтобы гейт проверялся положительными контролями на
    синтетическом документе, а не только на живом дереве.
    """
    targets: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue                       # строка-комментарий внутри блока ничего не гоняет
        if not _PYTEST_RE.search(stripped):
            continue
        skip_next = False
        seen_pytest = False
        for token in _tokenize(stripped):
            if skip_next:
                skip_next = False
                continue
            if not seen_pytest:
                if token.endswith("pytest"):
                    seen_pytest = True
                continue
            if token.startswith("-"):
                if "=" not in token and token in _VALUE_FLAGS:
                    skip_next = True
                continue
            raw = _unquote(token).split("::")[0]
            if not raw or raw.startswith("$"):
                continue
            targets.add(raw.rstrip("/"))
    return targets


def prescribed_env(text: str) -> dict[str, str]:
    """Переменные, которые НЕСЁТ предписанная команда: префикс ``VAR=value`` перед pytest.

    Берутся только присваивания ДО имени интерпретатора/``pytest`` — то есть ровно то, что
    оболочка положит в окружение процесса. ``mypy==2.1.0`` и прочие аргументы после вызова
    сюда не попадают: они не окружение.
    """
    env: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue                       # закомментированная строка ничего не гоняет
        if not _PYTEST_RE.search(stripped):
            continue
        for token in _tokenize(stripped):
            if token.endswith("pytest") or token.startswith("-"):
                break                      # начался сам вызов — префикс окружения кончился
            if _ENV_ASSIGN_RE.match(token):
                name, _, value = token.partition("=")
                env[name] = _unquote(value)
                continue
            break                          # `python3` и т.п. — префикс кончился
    return env


def missing_env(ci_env: dict[str, str], prescribed: dict[str, str]) -> dict[str, str]:
    """Переменные CI, которых предписанная команда не несёт ИЛИ несёт с другим значением."""
    return {
        name: value
        for name, value in ci_env.items()
        if prescribed.get(name) != value
    }


def ci_gating_dirs() -> set[str]:
    """Каталоги, которые реально запускает CI (цели-файлы и мусор отброшены)."""
    return {
        target.rstrip("/")
        for target in _coverage._TARGETS
        if (_REPO_ROOT / target).is_dir()
    }


def unprescribed(ci_dirs: set[str], prescribed: set[str]) -> set[str]:
    """Каталоги CI, которые предписанная команда не называет — ни сам, ни его предок."""
    missing: set[str] = set()
    for directory in ci_dirs:
        parts = directory.split("/")
        ancestors = {"/".join(parts[:i]) for i in range(1, len(parts) + 1)}
        if not (ancestors & prescribed):
            missing.add(directory)
    return missing


_CLAUDE_TEXT = _CLAUDE_MD.read_text(encoding="utf-8")
_PRESCRIBED = prescribed_targets(_CLAUDE_TEXT)
_CI_DIRS = ci_gating_dirs()
_PRESCRIBED_ENV = prescribed_env(_CLAUDE_TEXT)
_CI_ENV = _coverage._CI_PYTEST_ENV


# ── Проверки над живым деревом ────────────────────────────────────────────────

def test_claude_md_prescribes_at_least_one_pytest_command():
    """Fail-CLOSED: нет команды — значит парсер сломался ИЛИ команду убрали. Оба — красные."""
    assert _PRESCRIBED, (
        f"в {_CLAUDE_MD.name} не найдено ни одной позиционной цели pytest — "
        "«не нашёл» здесь неотличимо от «сканер сломался» (инвариант #2)"
    )


def test_ci_gating_dirs_are_not_empty():
    """Fail-CLOSED: пустой набор целей CI означал бы, что сравнивать не с чем."""
    assert _CI_DIRS, (
        "разбор workflow не дал ни одного каталога — сравнивать предписанную команду "
        "не с чем; молчаливое «всё покрыто» запрещено (инвариант #2)"
    )


def test_prescribed_run_covers_every_ci_gating_dir():
    """Главный вопрос: команда из CLAUDE.md покрывает всё, что гейтит CI."""
    missing = unprescribed(_CI_DIRS, _PRESCRIBED) - set(_ALLOWED_UNPRESCRIBED)
    assert not missing, (
        f"CI гейтит эти каталоги, а предписанный прогон их не называет: {sorted(missing)}. "
        f"Предписано: {sorted(_PRESCRIBED)}. Ровно так восемь коммитов подряд уезжали "
        "на красный main при отчёте «тесты зелёные» (цикл #189)."
    )


def test_allowed_unprescribed_entries_are_justified_and_live():
    """Реестр исключений не должен врать: обоснование со ссылкой, каталог существует и нужен."""
    for directory, reason in _ALLOWED_UNPRESCRIBED.items():
        assert len(reason) >= _MIN_JUSTIFICATION_LEN, f"{directory}: обоснование слишком короткое"
        assert any(token in reason for token in _TRACE_TOKENS), (
            f"{directory}: в обосновании нет прослеживаемой ссылки (карточка / ADR / docs/)"
        )
        assert directory in _CI_DIRS, (
            f"{directory}: запись протухла — CI этот каталог больше не гейтит, "
            "исключение обязано уйти вместе с причиной"
        )


# ── Положительные контроли: каждый воспроизводит реальную аварию ──────────────

_PRE_FIX_CLAUDE_MD = """
## Команды
```bash
# Все тесты:
python3 -m pytest spa_core/tests/ -v
```
"""


def test_positive_control_pre_fix_claude_md_is_red():
    """Контроль: ровно та команда, что стояла в CLAUDE.md до 2026-08-10, обязана краснеть.

    Проверка, никогда не видевшая настоящей поломки, — украшение
    (`.claude/rules/deployment.md`). Здесь поломка настоящая: этот текст жил в репозитории
    и стоил восьми коммитов красного main.
    """
    prescribed = prescribed_targets(_PRE_FIX_CLAUDE_MD)
    assert prescribed == {"spa_core/tests"}, prescribed
    missing = unprescribed(_CI_DIRS, prescribed)
    assert "tests" in missing, (
        "довод всего файла: старая команда НЕ покрывала tests/ — контроль обязан это ловить"
    )


def test_positive_control_commented_out_command_does_not_count():
    """Закомментированная строка ничего не гоняет — и не имеет права считаться покрытием."""
    text = "```bash\n# python3 -m pytest tests/ -q\n```"
    assert prescribed_targets(text) == set()


def test_positive_control_value_flag_argument_is_not_a_target():
    """`-k not slow` не должен «покрыть» каталог с именем `not`."""
    targets = prescribed_targets("python3 -m pytest tests/ -k slow -p no:randomly -q")
    assert targets == {"tests"}, targets


def test_positive_control_file_target_does_not_cover_its_directory():
    """Названный ФАЙЛ не покрывает каталог: `pytest tests/test_x.py` — это не `tests/`."""
    targets = prescribed_targets("python3 -m pytest tests/test_checkpoint_7day.py -q")
    assert targets == {"tests/test_checkpoint_7day.py"}
    assert "tests" in unprescribed({"tests"}, targets)


def test_positive_control_ancestor_target_covers_nested_dir():
    """Обратная сторона: названный предок покрывает вложенный каталог — иначе гейт кричал бы зря."""
    assert unprescribed({"spa_core/analytics/gross_of"}, {"spa_core"}) == set()


@pytest.mark.parametrize("directory", sorted(_CI_DIRS))
def test_every_ci_dir_is_named_by_the_prescribed_command(directory: str):
    """Поимённо — чтобы падение называло КОНКРЕТНЫЙ каталог, а не общий список."""
    if directory in _ALLOWED_UNPRESCRIBED:
        pytest.skip(f"осознанное исключение: {_ALLOWED_UNPRESCRIBED[directory]}")
    assert not unprescribed({directory}, _PRESCRIBED), (
        f"CI гейтит {directory}, предписанная команда его не называет"
    )


# ── ЧЕТВЁРТЫЙ вопрос: тот же ли ПРОГОН, а не только те же каталоги (цикл #304) ─
#
# «Те же каталоги» и «тот же прогон» — разные утверждения, и второе не проверял никто.
# Замер #304 на `spa_core/tests/test_cycle_nav_determinism.py` — том самом файле, который
# карточка `inbox-shest-testov-eto-15-steny-vsei-priemki-i` звала «15 % стены приёмки»:
#
#     SPA_ENV=ci   →   14.30 с,    20 763 потока   ← так гоняет CI
#     без SPA_ENV  →  125.30 с,   679 762 потока   ← так предписывал CLAUDE.md
#
# Оба прогона — 6 passed: набор тестов ОДИН, прогон РАЗНЫЙ. Разница не в тестах, а в
# рантайме: `cycle_runner` под `SPA_ENV=ci` осознанно пропускает advisory-слой Tier B, и без
# этой переменной каждый смоделированный цикл поднимает ~479 advisory-модулей. То есть
# «15 % стены приёмки» — не свойство файла и не цена property-теста, а цена РАСХОЖДЕНИЯ
# предписанной команды с CI. Диагнозы #289 (adapter_orchestrator) и #296 (signal_aggregator)
# называли механизм, но мерили условие, в котором CI не работает ни разу.
#
# Медленная приёмка — названная причина класса «осиротевшая работа»: сессия успевает умереть
# между «сделал» и «доставил». Поэтому вопрос стоит здесь, рядом с тремя своими братьями.

def test_ci_env_for_the_gating_suite_is_measured():
    """Fail-CLOSED: пустое окружение неотличимо от сломанного разбора workflow.

    Ровно та же логика, что у трёх соседних проверок этого файла: «не нашёл» здесь не значит
    «нечего требовать» — это значит, что разбор сломался ИЛИ CI перестал задавать окружение.
    Оба случая требуют человека, а не молчаливого зелёного (инвариант #2).
    """
    assert _CI_ENV, (
        "не удалось определить окружение, под которым CI гоняет гейтящий набор. "
        "Молчаливое «значит, требовать нечего» запрещено: так и жил зазор, "
        "стоивший 8× времени приёмки (цикл #304)."
    )


def test_prescribed_run_carries_the_ci_environment():
    """Главный вопрос: предписанная команда воспроизводит ПРОГОН CI, а не только его каталоги."""
    missing = missing_env(_CI_ENV, _PRESCRIBED_ENV)
    missing = {k: v for k, v in missing.items() if k not in _ALLOWED_MISSING_ENV}
    assert not missing, (
        "CI гоняет гейтящий набор под этими переменными, а предписанная в CLAUDE.md команда "
        f"их не несёт: {missing}. Предписано: {_PRESCRIBED_ENV or '{}'}. "
        "Это не косметика: без SPA_ENV=ci тот же набор идёт 125.30 с вместо 14.30 с "
        "(679 762 потока против 20 763) на одном только test_cycle_nav_determinism.py, "
        "потому что рантайм перестаёт пропускать advisory-слой Tier B (цикл #304)."
    )


@pytest.mark.parametrize("name", sorted(_CI_ENV))
def test_every_ci_env_var_is_carried_by_the_prescribed_command(name: str):
    """Поимённо — чтобы падение называло КОНКРЕТНУЮ переменную, а не общий словарь."""
    if name in _ALLOWED_MISSING_ENV:
        pytest.skip(f"осознанное исключение: {_ALLOWED_MISSING_ENV[name]}")
    assert _PRESCRIBED_ENV.get(name) == _CI_ENV[name], (
        f"CI задаёт {name}={_CI_ENV[name]!r}, предписанная команда несёт "
        f"{_PRESCRIBED_ENV.get(name)!r}"
    )


def test_allowed_missing_env_entries_are_justified_and_live():
    """Реестр исключений по окружению не должен врать — тот же договор, что и у каталогов."""
    for name, reason in _ALLOWED_MISSING_ENV.items():
        assert len(reason) >= _MIN_JUSTIFICATION_LEN, f"{name}: обоснование слишком короткое"
        assert any(token in reason for token in _TRACE_TOKENS), (
            f"{name}: в обосновании нет прослеживаемой ссылки (карточка / ADR / docs/)"
        )
        assert name in _CI_ENV, (
            f"{name}: запись протухла — CI эту переменную больше не задаёт, "
            "исключение обязано уйти вместе с причиной"
        )


# ── Положительные контроли к четвёртому вопросу ───────────────────────────────

def test_positive_control_pre_fix_claude_md_carries_no_env():
    """Контроль: команда, что стояла в CLAUDE.md до цикла #304, обязана краснеть.

    Это НЕ синтетика: ровно эта строка жила в репозитории и стоила 8× времени приёмки.
    """
    text = (
        "```bash\n"
        "# Все тесты — РОВНО ТО, ЧТО ГЕЙТИТ CI:\n"
        "python3 -m pytest spa_core/tests/ tests/ scripts/tests/"
        " spa_core/analytics/gross_of/ research/cards/ -q\n"
        "```"
    )
    assert prescribed_env(text) == {}, "старая команда не несла окружения вовсе"
    assert missing_env({"SPA_ENV": "ci"}, prescribed_env(text)) == {"SPA_ENV": "ci"}


def test_positive_control_wrong_env_value_is_not_a_match():
    """`SPA_ENV=dev` — это ДРУГОЙ прогон; совпадение по имени переменной не считается."""
    env = prescribed_env("SPA_ENV=dev python3 -m pytest tests/ -q")
    assert env == {"SPA_ENV": "dev"}
    assert missing_env({"SPA_ENV": "ci"}, env) == {"SPA_ENV": "ci"}


def test_positive_control_env_prefix_is_parsed_and_targets_survive():
    """Префикс окружения не должен ни потеряться сам, ни съесть позиционные цели."""
    line = "SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest spa_core/tests/ tests/ -q"
    assert prescribed_env(line) == {"SPA_ENV": "ci", "PYTHONHASHSEED": "0"}
    assert prescribed_targets(line) == {"spa_core/tests", "tests"}


def test_positive_control_commented_out_command_carries_no_env():
    """Закомментированная строка ничего не гоняет — и ничего не «несёт»."""
    assert prescribed_env("# SPA_ENV=ci python3 -m pytest tests/ -q") == {}


def test_positive_control_flag_argument_is_not_read_as_env():
    """`mypy==2.1.0` после вызова — аргумент, а не переменная окружения."""
    assert prescribed_env("python3 -m pytest tests/ -q -o cache_dir=/tmp/x") == {}


def test_reverse_control_matching_env_is_not_a_finding():
    """Обратный контроль: когда команда несёт ровно окружение CI — находок ноль."""
    env = prescribed_env("SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest tests/ -q")
    assert missing_env({"SPA_ENV": "ci", "PYTHONHASHSEED": "0"}, env) == {}


def test_positive_control_manual_only_workflow_does_not_set_the_bar():
    """`spa-run.yml` гоняет `spa_core/tests` БЕЗ окружения — но main не гейтит.

    Он `workflow_dispatch`-only (аварийный ручной прогон). Считать его — значит обнулить
    ответ одним шагом, которого на пути в main нет; не считать по причине «мешает» — значит
    подогнать. Признак взят проверяемый: гоняется ли workflow на push/pull_request.
    """
    manual = (
        "name: manual\non:\n  workflow_dispatch:\njobs:\n  j:\n    steps:\n"
        "      - run: python3 -m pytest spa_core/tests/ -q\n"
    )
    gating = (
        "name: gate\non:\n  push:\n    branches: [main]\njobs:\n  j:\n    steps:\n"
        "      - run: python3 -m pytest spa_core/tests/ -q\n        env:\n          SPA_ENV: ci\n"
    )
    dirs = {"spa_core/tests"}
    assert _coverage.ci_pytest_env({"manual.yml": manual}, dirs) == {}
    assert _coverage.ci_pytest_env({"gate.yml": gating}, dirs) == {"SPA_ENV": "ci"}
    both = _coverage.ci_pytest_env({"manual.yml": manual, "gate.yml": gating}, dirs)
    assert both == {"SPA_ENV": "ci"}, (
        "ручной workflow не имеет права обнулять требование гейтящего"
    )


def test_positive_control_install_step_comment_is_not_a_pytest_run():
    """Хвост-комментарий шага `pip install` не должен считаться прогоном каталога.

    Живой случай: `ci.yml` упоминает `scripts/tests/` СЛОВАМИ в комментарии строки установки
    зависимостей, а в списке пакетов стоит слово `pytest` — вместе это читалось как «шаг
    гоняет scripts/tests без окружения» и в одиночку обнуляло ответ.

    **`run: |` здесь обязателен, и это не украшение.** Первая редакция этого контроля писала
    шаг ПЛОСКИМ скаляром (`- run: pip install …  # …`) — и молча ничего не проверяла: в
    плоском скаляре `#` после пробела съедает сам YAML, до нашего разбора комментарий не
    доезжает вовсе, и контроль оставался зелёным под собственной мутацией. В `ci.yml` шаг
    записан блочным скаляром, где `#` — обычный текст; авария живёт именно там.
    """
    text = (
        "name: gate\non:\n  push:\n    branches: [main]\njobs:\n  j:\n    steps:\n"
        "      - run: |\n"
        "          pip install pytest pyyaml  # ратчет в scripts/tests/ зовёт его\n"
        "      - run: |\n"
        "          python3 -m pytest scripts/tests/ -q\n"
        "        env:\n          SPA_ENV: ci\n"
    )
    # Сначала — что комментарий ДОЕХАЛ до разбора (иначе контроль ничего не стережёт).
    steps = _coverage.pytest_steps(text)
    assert len(steps) == 2, steps
    assert "scripts/tests" not in steps[0][0], (
        "упоминание каталога в комментарии не имеет права быть целью"
    )
    assert _coverage.ci_pytest_env({"gate.yml": text}, {"scripts/tests"}) == {"SPA_ENV": "ci"}


def test_positive_control_file_target_step_does_not_set_the_bar():
    """`proof-gate.yml` зовёт ИМЕНОВАННЫЕ файлы — предписанная команда воспроизводит не его.

    Рядом обязан стоять НАСТОЯЩИЙ гейтящий шаг: без него утверждение выродится в `{} == {}`
    и пройдёт при любой ошибке отбора. Проверяем ровно то, что шаг по файлу не обнуляет
    требование, поставленное шагом по каталогу.
    """
    text = (
        "name: proof\non:\n  pull_request:\n    branches: [main]\njobs:\n  j:\n    steps:\n"
        "      - run: python3 -m pytest spa_core/tests/test_dd_pack.py -q\n"
        "      - run: python3 -m pytest spa_core/tests/ -q\n"
        "        env:\n          SPA_ENV: ci\n"
    )
    assert _coverage.ci_pytest_env({"proof.yml": text}, {"spa_core/tests"}) == {"SPA_ENV": "ci"}
