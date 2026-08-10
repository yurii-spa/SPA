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

_TRACE_TOKENS = ("agent-", "own-", "owner-decision-", "inbox-", "ADR", "docs/", "MP-", "цикл #")
_MIN_JUSTIFICATION_LEN = 30


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
