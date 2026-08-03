"""Гейт mypy В ТОМ CI, КОТОРЫЙ РЕАЛЬНО СМОТРЯТ (цикл #107).

Карточка ``agent-task-krasnyi-ci-lite-nevidim-geit-mypy-zhivet``, вариант 1.

**Что чинится.** Статический гейт типов жил ровно в одном месте — шаге
``Type check`` файла ``.github/workflows/ci-lite.yml``. Замер цикла #95:
``SPA CI-Lite`` простоял красным ~8.5 часов, и ни один из четырёх автономных
циклов (#92–#95) этого не заметил — все они сверяют «CI на main» по
``SPA Tests`` / ``SPA CI``, а третий workflow в эту формулировку не попадает;
нашли красноту только ручным запросом Actions API. Вдобавок ``ci-lite``
запускается по расписанию раз в 6 часов, то есть между пушем, ломающим типы,
и первой краснотой проходили часы.

Этот файл переносит ТО ЖЕ САМОЕ измерение в pytest, который крутится в
``SPA Tests`` / ``SPA CI`` на КАЖДОМ push и PR. Гейт в ci-lite не снят — он
остаётся; проверка не заменена, а продублирована в видимое место.

**Почему не skip при отсутствии mypy (инв. #2, класс #37/#39).** Тест, который
при отсутствии инструмента становится зелёным (или skipped), утверждает
проверку, которой не делал. Поэтому: mypy нет ⇒ КРАСНЫЙ с названной причиной.
Зависимость гарантирована в обоих workflow (``ci.yml`` / ``test.yml`` ставят
``mypy==2.1.0``), и это тоже пиннится ниже — иначе «гарантия» держится на
памяти, а не на проверке.

Только stdlib. Сети нет. Кэш mypy пишется в ``tmp_path`` — набор не оставляет
следов в репозитории.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CI_LITE = WORKFLOWS / "ci-lite.yml"
GATE_PATH = REPO_ROOT / "scripts" / "mypy_gate.py"

# Оба workflow, которые циклы называют «CI на main» — гейт обязан быть виден
# именно здесь.
WATCHED_WORKFLOWS = ("ci.yml", "test.yml")


def _load_gate():
    """Импортировать scripts/mypy_gate.py по пути (scripts/ — не пакет)."""
    spec = importlib.util.spec_from_file_location("spa_mypy_gate", GATE_PATH)
    assert spec and spec.loader, f"не удалось загрузить {GATE_PATH}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gate():
    assert GATE_PATH.exists(), (
        f"{GATE_PATH} отсутствует — источник правды гейта типов удалён. "
        "Это КРАСНЫЙ: без него ci-lite.yml и этот тест разойдутся молча."
    )
    return _load_gate()


# ─── 1. Сам гейт ─────────────────────────────────────────────────────────────


def test_mypy_is_installed(gate):
    """Отсутствие mypy — КРАСНЫЙ, а не skip (инв. #2).

    Если этот тест упал в CI — значит из pip-набора workflow пропала mypy,
    и гейт типов перестал выполняться. Чинить надо зависимость, а не тест.
    """
    assert gate.mypy_available(), (
        f"mypy не установлен в {sys.executable}. Гейт типов НЕ ВЫПОЛНЕН.\n"
        "Молчаливого skip здесь нет: пропущенная проверка, объявленная "
        "пройденной, — это тот самый fail-OPEN (#37/#39), ради которого гейт "
        "и заводился. Установить: pip install mypy==2.1.0"
    )


def test_mypy_gate_passes(gate, tmp_path):
    """Ключевые money-path модули проходят mypy — то же измерение, что в ci-lite."""
    rc, out = gate.run(cache_dir=str(tmp_path / "mypy_cache"))
    assert rc == 0, f"гейт mypy НЕ пройден (rc={rc}):\n{out}"


def test_missing_mypy_is_red_not_green(gate, monkeypatch):
    """Положительный контроль: без mypy `run()` обязан вернуть НЕнулевой код.

    Мутационная проверка самого механизма fail-CLOSED — иначе «мы бы покраснели»
    остаётся обещанием. Подменяется ровно измерение наличия инструмента.
    """
    monkeypatch.setattr(gate, "mypy_available", lambda: False)
    rc, out = gate.run()
    assert rc != 0, "mypy отсутствует, а гейт вернул успех — это fail-OPEN"
    assert "НЕ УСТАНОВЛЕН" in out, f"причина отказа не названа: {out!r}"


# ─── 2. Гейт нельзя сузить молча ─────────────────────────────────────────────


def test_gate_module_list_is_not_empty(gate):
    """Пустой список = гейт, который всегда зелёный и ничего не проверяет."""
    assert len(gate.MODULES) >= 4, (
        f"список модулей гейта сузился до {len(gate.MODULES)}: {gate.MODULES}. "
        "Сужение проверки — только с обоснованием и записью в журнал (инв. #16)."
    )


def test_gate_modules_all_exist(gate):
    """Модуль из списка, которого нет на диске, mypy молча не проверит."""
    missing = [m for m in gate.MODULES if not (REPO_ROOT / m).exists()]
    assert not missing, (
        f"в списке гейта есть несуществующие файлы: {missing}. "
        "Гейт по несуществующему пути ничего не измеряет."
    )


def test_gate_covers_money_path_modules(gate):
    """Именно money-path модули и общие типы — то, ради чего гейт существует."""
    for required in ("risk/policy.py", "allocator/allocator.py",
                     "paper_trading/cycle_runner.py"):
        assert any(required in m for m in gate.MODULES), (
            f"{required} выпал из гейта типов: {gate.MODULES}"
        )


# ─── 3. Один источник правды: ci-lite не должен уехать своим списком ─────────


def test_ci_lite_delegates_to_the_shared_gate():
    """ci-lite.yml зовёт scripts/mypy_gate.py, а не свою inline-копию списка.

    Пока список жил inline в YAML, любая правка здесь или там расходилась
    молча — и «гейт в двух местах» означал два РАЗНЫХ гейта.
    """
    text = CI_LITE.read_text(encoding="utf-8")
    assert "scripts/mypy_gate.py" in text, (
        "ci-lite.yml больше не зовёт scripts/mypy_gate.py — источник правды "
        "гейта раздвоился."
    )
    assert not re.search(r"-m\s+mypy\b", text), (
        "в ci-lite.yml вернулся собственный вызов `python -m mypy` — это вторая "
        "копия списка модулей, которая разойдётся с scripts/mypy_gate.py."
    )


@pytest.mark.parametrize("wf", WATCHED_WORKFLOWS)
def test_watched_workflows_install_mypy(wf):
    """`SPA Tests` / `SPA CI` ставят mypy — иначе гейт в них КРАСНЫЙ, а не тихий.

    Без этого `test_mypy_is_installed` покраснел бы в CI на пустом месте; с ним
    зависимость — проверяемый факт, а не намерение.
    """
    path = WORKFLOWS / wf
    assert path.exists(), f"{wf} отсутствует"
    text = path.read_text(encoding="utf-8")
    install_lines = [ln for ln in text.splitlines() if "pip install" in ln]
    assert install_lines, f"в {wf} не найдено ни одной строки `pip install`"

    # ВАЖНО: смотреть только на КОМАНДУ, отрезав комментарий после `#`.
    # Первая версия этого теста читала строку целиком и была зелёной, когда
    # пакет из команды убрали, а слово «mypy» осталось в поясняющем комментарии
    # на той же строке (поймано мутацией M3, цикл #107). Проверка, которую
    # удовлетворяет комментарий, ничего не измеряет.
    installed: list[str] = []
    for ln in install_lines:
        command = ln.split("#", 1)[0]
        installed += re.findall(r"(?:^|\s)(mypy)(?:==[\w.]+)?(?=\s|$)", command)
    assert installed, (
        f"{wf} не ставит пакет mypy (слово в комментарии не считается) — гейт "
        f"типов в наблюдаемом CI не выполнится. Команды установки: "
        f"{[ln.split('#', 1)[0].strip() for ln in install_lines]}"
    )


# ─── 4. Падение шага не должно молча гасить остальные проверки ──────────────


def test_ci_lite_check_steps_are_independent():
    """Каждый шаг-проверка ci-lite помечен `if: ${{ !cancelled() }}`.

    Замер цикла #95: при красном `Type check` шаги `Import check` и
    `Registry check` уходили в `skipped` — одна ошибка типов гасила остаток
    гейта, и это выглядело как «проверки не нужны». Джоб при этом остаётся
    красным при падении ЛЮБОГО шага: проверок стало выполняться больше, а не
    меньше.
    """
    text = CI_LITE.read_text(encoding="utf-8")
    steps = re.findall(r"^      - name: (.+)$", text, flags=re.M)
    assert steps, "в ci-lite.yml не разобран ни один шаг — сканер сломан"

    # Checkout / setup-python — не проверки, а предусловия: их падение обязано
    # остановить джоб (без исходников и питона мерить нечего).
    prerequisites = {"Checkout", "Set up Python 3.11"}
    checks = [s for s in steps if s not in prerequisites]
    assert len(checks) >= 6, f"шагов-проверок неожиданно мало: {checks}"

    blocks = text.split("      - name: ")
    missing = []
    for block in blocks[1:]:
        name = block.splitlines()[0]
        if name in prerequisites:
            continue
        if "if: ${{ !cancelled() }}" not in block.split("\n        run:")[0]:
            missing.append(name)
    assert not missing, (
        "шаги ci-lite.yml без `if: ${{ !cancelled() }}` — их молча пропустит "
        f"падение предыдущего шага: {missing}"
    )
