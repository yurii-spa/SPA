"""Версию pytest в CI выбирает ДЕРЕВО, а не календарь (ADR-841).

**Что измерено 2026-10-28 (цикл #961).** `SPA CI` на `main` не выдавал вердикта ЧЕТЫРЕ
прогона подряд, и причина была не в тестах:

| прогон | sha | pytest | что в логе |
|---|---|---|---|
| 40298635738 (26.10 09:19) | — | **9.1.1** | `54 failed, 120055 passed, 682 skipped, 2485 subtests passed in 21441.35s (5:57:21)` |
| 40588407688 (27.10 21:38) | `82483f3ec` | **9.2.0** | `runner has received a shutdown signal` · ни строки pytest |
| 40589002249 (27.10 21:42) | `06e3acd23` | **9.2.0** | то же |
| 40603175501 (27.10 23:35) | `9f3507856` | **9.2.0** | то же |
| 40615345405 (28.10 01:29) | `306dc94c3` | **9.2.0** | то же, шаг умер за **41 с** на СБОРЕ тестов |

`pip install pytest` без `==` берёт у PyPI то, что там лежит СЕГОДНЯ. 9.2.0 вышел между
26-м и 27-м, и с этого момента шаг тестов умирал на сборе: раннер получал shutdown (подпись
нехватки памяти), сводки не появлялось ВОВСЕ — то есть «не измерено», выданное под словом
`failure` (ровно ловушка из `CLAUDE.md`: «CI красный» ≠ «тесты падают»). Дерево при этом не
менялось: тот же код давал сводку на 9.1.1 и ничего на 9.2.0.

**Что проверяется ниже.** Каждое `pip install … pytest` в `.github/workflows/` несёт `==`.
Это НЕ про конкретный номер версии: номер — решение, и он живёт в самих воркфлоу и в ADR-841.
Проверяется, что номер вообще ЕСТЬ, потому что его отсутствие делает вердикт CI функцией даты.

**Чего не проверяется** (честная граница): годится ли закреплённая версия. Это свойство
раннера и набора, и отвечает на него только прогон. Пин — не гарантия зелени, а условие
того, чтобы вердикт зависел от дерева; `ci-lite.yml` держит свой номер (8.3.4) намеренно —
у него свой, узкий набор.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"

#: `pip install` (с любыми флагами) ставит pytest — и номер версии за ним не назван.
#: `(?!=)` ровно про это: `pytest==9.1.1` под шаблон не попадает, `pytest-asyncio` тоже
#: (после `pytest` идёт дефис, а не граница слова).
_UNPINNED = re.compile(r"pip install(?:\s+--\S+|\s+-\w)*\s+pytest(?![=\w-])")

#: `pip install` ставит pytest с НАЗВАННЫМ номером. Нужен для контроля в обе стороны:
#: сторож, который только краснеет, неотличим от сторожа, который краснеет всегда.
_PINNED = re.compile(r"pip install(?:\s+--\S+|\s+-\w)*\s+pytest==\d")


def _workflow_files() -> list[Path]:
    files = sorted(_WORKFLOWS.glob("*.yml"))
    assert files, (
        f"{_WORKFLOWS} не содержит ни одного воркфлоу. Это НЕ «нарушений нет»: каталог не "
        f"прочитан, и мера ничего не измерила (инв. #17)."
    )
    return files


def _install_lines(text: str) -> list[tuple[int, str]]:
    """Строки, ставящие пакеты через pip. Комментарий YAML отрезан — он не команда.

    Без отрезания комментария проза вроде «см. `pip install` выше» читалась бы как установка,
    и сторож краснел бы на тексте — та самая cry-wolf-ошибка, после которой сторожей снимают.
    """
    out = []
    for no, line in enumerate(text.split("\n"), start=1):
        if "pip install" not in line:
            continue
        out.append((no, line.split("#", 1)[0]))
    return out


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_every_workflow_names_the_pytest_version_it_installs(path: Path):
    """Ни одного `pip install pytest` без `==`: иначе вердикт CI — функция календаря."""
    unpinned = [
        no for no, line in _install_lines(path.read_text(encoding="utf-8"))
        if _UNPINNED.search(line)
    ]
    assert not unpinned, (
        f".github/workflows/{path.name}: строк(и) {unpinned} ставят pytest без номера версии.\n"
        f"`pip install pytest` берёт у PyPI то, что там СЕГОДНЯ. 27.10 этим способом приехал "
        f"9.2.0, и шаг тестов умирал на СБОРЕ за ~40 с с `runner has received a shutdown "
        f"signal` — сводки pytest не было ВОВСЕ, четыре прогона подряд (ADR-841).\n"
        f"Напиши `pytest==<номер>`. Снимать этот сторож нельзя: он про то, чтобы вердикт "
        f"зависел от дерева, а не от даты прогона."
    )


def test_the_pin_is_actually_present_somewhere_and_the_measure_sees_it():
    """Обратная сторона: мера ВИДИТ закреплённый пин, а не краснеет вслепую.

    Без этой половины проверка выше была бы неотличима от сторожа, который зелен всегда:
    например если шаблон перестал бы находить `pip install` вовсе.
    """
    pinned = [
        (p.name, no) for p in _workflow_files()
        for no, line in _install_lines(p.read_text(encoding="utf-8"))
        if _PINNED.search(line)
    ]
    assert pinned, (
        "ни в одном воркфлоу мера не нашла закреплённого pytest — значит она не находит "
        "`pip install` вовсе, и зелёный ответ выше ничего не означает."
    )


@pytest.mark.parametrize("line, unpinned_expected", [
    ("          pip install pytest pytest-asyncio pyyaml", True),
    ("        run: python3 -m pip install --quiet pytest", True),
    ("          pip install pytest --quiet", True),
    ("          pip install pytest==9.1.1 pytest-asyncio", False),
    ("        run: python3 -m pip install --quiet pytest==9.1.1", False),
    ("          pip install pytest-asyncio pytest-timeout", False),
    ("          pip install mypy==2.1.0", False),
])
def test_the_measure_answers_both_ways_on_named_forms(line, unpinned_expected):
    """Каждая форма, бытующая в воркфлоу, разобрана отдельно — и обе стороны названы.

    `pytest-asyncio` и `pytest-timeout` под шаблон попадать не должны: это ДРУГИЕ пакеты, и
    считать их нарушением значило бы учить всех снимать сторожа.
    """
    assert bool(_UNPINNED.search(line.split("#", 1)[0])) is unpinned_expected


def test_a_pip_install_inside_a_yaml_comment_is_not_a_command():
    """Проза с «pip install» в комментарии нарушением НЕ является (у нас такая есть)."""
    line = "          # ставится тем же `pip install pytest` выше, см. комментарий"
    assert not _UNPINNED.search(line.split("#", 1)[0])
    assert _UNPINNED.search("          pip install pytest"), (
        "сцена не воспроизводит предмет: та же команда ВНЕ комментария обязана быть находкой")
