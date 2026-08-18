"""Признак «это прод-запуск» обязан ДОЙТИ до продовых писателей.

Карточка ``inbox-uvod-putei-ne-deistvuet-vne-pytest-obych``, замер 2026-08-18.

Почему этот сторож существует отдельно от ``test_sandboxed_state_path.py``.
Тот проверяет МЕХАНИЗМ (``live_paths.sandboxed_default`` уводит без признака и
не уводит с ним) — и остался бы полностью зелёным, если бы признак не был
раскатан ни на одного реального писателя. Правило доставки формулирует это
прямо: четыре вопроса — четыре разных сторожа, зелёный ответ на один никогда не
означает ответа на другой. Здесь задаётся пятый вопрос: **дойдёт ли признак до
живого прод-пути**.

Цена ошибки измерена, а не предположена. Увод стал умолчанием; продовых
писателей уводимых логов ровно три семейства:

* ``com.spa.daily_cycle`` → ``scripts/run_daily_paper_cycle.sh`` →
  ``cycle_runner.py:1021`` (``run_tier_b``) и ``cycle_gates.py:91``
  (``run_tier_a``) — признак приходит из ``EnvironmentVariables`` плиста;
* ``com.spa.analytics_tier_b`` → ``scripts/agent_analytics_tier_b.sh``;
* ``com.spa.analytics_tier_c`` → ``scripts/agent_analytics_tier_c.sh``.

У ДВУХ последних плисты не имеют ``EnvironmentVariables`` вовсе — признак им
может дать только общая обёртка ``scripts/agent_template.sh``. Убери из неё
одну строку, и 53 из 56 ring-buffer логов молча уедут в ``/tmp``: ни
``deployment_acceptance`` (стартуемость), ни ``agent_health`` (процесс жив), ни
``agent_code_freshness`` (код свежий) об этом не скажут — каждый честно
ответит на свой вопрос.

Время сюда не входит: свежести эти проверки не судят, литеральных дат нет.
"""
from __future__ import annotations

import plistlib
import re
from pathlib import Path

import pytest

from spa_core.utils import live_paths


REPO_ROOT = Path(__file__).resolve().parents[2]

AGENT_TEMPLATE = REPO_ROOT / "scripts" / "agent_template.sh"

#: Обёртки продовых писателей уводимых логов — измерены, не предположены.
ANALYTICS_WRAPPERS = (
    REPO_ROOT / "scripts" / "agent_analytics_tier_b.sh",
    REPO_ROOT / "scripts" / "agent_analytics_tier_c.sh",
)

DAILY_CYCLE_PLIST = REPO_ROOT / "scripts" / "com.spa.daily_cycle.plist"


def test_agent_template_exports_the_production_signal():
    """Общая обёртка флота обязана называть запуск продовым.

    ``:-`` обязателен: явно заданное значение (``SPA_ENV=ci`` в CI) должно
    оставаться сильнее, иначе обёртка сломала бы сетевые сторожа CI.
    """
    assert AGENT_TEMPLATE.is_file(), f"нет {AGENT_TEMPLATE}"
    text = AGENT_TEMPLATE.read_text()

    pattern = re.compile(
        r'^\s*export\s+SPA_ENV="\$\{SPA_ENV:-production\}"\s*$', re.MULTILINE
    )
    assert pattern.search(text), (
        "scripts/agent_template.sh больше не экспортирует SPA_ENV=production. "
        "Через неё идут обёртки com.spa.analytics_tier_b/c, и без признака их "
        "ring-buffer логи уходят в песочницу — прод молча перестаёт писать."
    )


@pytest.mark.parametrize(
    "wrapper", ANALYTICS_WRAPPERS, ids=lambda p: p.name
)
def test_analytics_agent_wrappers_go_through_the_template(wrapper: Path):
    """Признак доходит до tier_b/c ТОЛЬКО через общую обёртку.

    Если обёртка перестанет звать ``agent_template.sh`` (или заведёт свой
    ``exec`` мимо него), признак пропадёт — а механизм при этом останется
    зелёным. Поэтому проводка закреплена отдельно от механизма.
    """
    assert wrapper.is_file(), f"нет {wrapper}"
    text = wrapper.read_text()
    assert "agent_template.sh" in text, (
        f"{wrapper.name} больше не идёт через agent_template.sh — признак "
        f"SPA_ENV=production до этого агента не дойдёт, и его логи уедут в /tmp"
    )


def test_daily_cycle_plist_still_carries_the_production_signal():
    """Дневной цикл — второй продовый писатель, признак у него из плиста."""
    assert DAILY_CYCLE_PLIST.is_file(), f"нет {DAILY_CYCLE_PLIST}"
    with DAILY_CYCLE_PLIST.open("rb") as fh:
        plist = plistlib.load(fh)

    env = plist.get("EnvironmentVariables") or {}
    assert env.get("SPA_ENV") == "production", (
        "com.spa.daily_cycle потерял SPA_ENV=production: cycle_runner (run_tier_b) "
        "и cycle_gates (run_tier_a) перестанут писать аналитические логи в дерево"
    )


def test_the_signal_name_the_wrapper_sets_is_the_one_live_paths_reads():
    """Обёртка и читатель обязаны говорить об ОДНОЙ переменной.

    Родовой класс «два имени для одной вещи»: разойдись они — обёртка честно
    экспортирует, читатель честно не находит, оба теста зелёные, прод молчит.
    """
    assert live_paths.ENV_NAME_ENV == "SPA_ENV"
    assert live_paths.PRODUCTION_ENV_VALUE == "production"

    text = AGENT_TEMPLATE.read_text()
    assert f"export {live_paths.ENV_NAME_ENV}=" in text, (
        "имя переменной в agent_template.sh разошлось с live_paths.ENV_NAME_ENV"
    )


def test_analytics_never_uses_the_pytest_only_redirect():
    """Храповик: в аналитике не должно быть увода, действующего только под pytest.

    ``sandboxed_state_path`` уводит по признаку ``under_test()``. Для
    ``spa_core/analytics/`` это ровно тот дефект, который здесь чинится: семь
    модулей остались на нём после цикла #275 и продолжали пачкать дерево при
    обычном запуске инструмента. Правильная форма для аналитики —
    ``sandboxed_default(path, tree_default)``.

    Запрет ограничен каталогом аналитики намеренно: у ``export_data``,
    ``gap_monitor``, ``alert_dispatcher`` и родни семантика прежняя и меняется
    отдельной работой, со своим замером писателей.
    """
    offenders = sorted(
        p.relative_to(REPO_ROOT).as_posix()
        for p in (REPO_ROOT / "spa_core" / "analytics").rglob("*.py")
        if "sandboxed_state_path" in p.read_text()
    )
    assert offenders == [], (
        "в spa_core/analytics/ вернулся увод, действующий только под pytest: "
        f"{offenders}. Обычный запуск скрипта снова будет пачкать git-tracked data/. "
        "Использовать sandboxed_default(path, tree_default)."
    )
