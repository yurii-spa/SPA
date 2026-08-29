"""Сторож с точкой входа, которого никто не зовёт, — не сторож, а файл.

# LLM_FORBIDDEN

У `scripts/` такой храповик есть (`test_unwired_scripts_ratchet`), у модулей
`spa_core/` — не было. Разница дорогая: `spa_core/alerts/apy_spike_monitor.py`
написан, имеет ВЕРНЫЙ порог (`compound_v3` > 8 %), и 25.08 показание было
**9.2007 %** — он бы сработал. Его не звал никто, и всплеск нашёлся неделей
позже вручную, при разборе перекладок книги.

Замер 2026-08-29: из **72** модулей со своей точкой входа в `alerts/`,
`monitoring/` и `governance/` **11** не упомянуты нигде — ни в plist, ни в
обёртке, ни в другом модуле, ни в манифесте.

Список может ТОЛЬКО СОКРАЩАТЬСЯ: модуль либо подключают, либо выводят из
обращения карточкой (директива владельца «90 % должно РАБОТАТЬ»). Пополнять
базу, чтобы погасить падение, запрещено.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DIRS = ("spa_core/alerts", "spa_core/monitoring", "spa_core/governance")

#: Перепись на 2026-08-29. Каждый — кандидат «подключить или вывести».
KNOWN_UNWIRED = {
    "spa_core/alerts/adaptive_monitor.py",
    "spa_core/alerts/apy_spike_monitor.py",
    "spa_core/monitoring/arbitrum_gas_monitor.py",
    "spa_core/monitoring/data_freshness_monitor.py",
    "spa_core/monitoring/findings_bridge_c125.py",
    "spa_core/monitoring/golive_checker_lp.py",
    "spa_core/monitoring/optimism_gas_monitor.py",
    "spa_core/monitoring/slo_proposal.py",
    "spa_core/monitoring/stalled_run_diagnosis.py",
    "spa_core/monitoring/unified_gas_monitor.py",
    "spa_core/governance/cpa_governance_watcher.py",
}


def has_entrypoint(text: str) -> bool:
    return "__main__" in text or "def main(" in text


def _tree_texts() -> dict:
    """{путь: текст} по всему дереву, где мог бы стоять вызов — ОДИН проход.

    Первая редакция звала `grep` на каждый модуль: 72 запуска, 85 секунд.
    Медленный тест рано или поздно отключают — тот же класс, что мы здесь
    и ловим. Вторая редакция склеивала всё в одну строку и считала вхождения,
    но модуль упоминает СВОЁ имя в собственной докстроке и выглядел
    «вызываемым». Теперь тексты хранятся отдельно, и файл никогда не
    засчитывается сам себе.
    """
    out = {}
    for sub in ("spa_core", "scripts", "launchd", "architecture"):
        base = _ROOT / sub
        if not base.exists():
            continue
        for f in base.rglob("*"):
            if not f.is_file() or f.suffix not in (".py", ".sh", ".plist", ".json"):
                continue
            rel = str(f.relative_to(_ROOT))
            if "/tests/" in rel or "/archive/" in rel:
                continue
            try:
                out[rel] = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return out


def _census() -> set:
    """Модули с точкой входа, чьё ИМЯ не встречается НИ В ОДНОМ другом файле.

    Ищем имя модуля, как ищет человек: обёртка `agent_x.sh`, plist и манифест
    ссылаются по имени, а не по точечному пути. Редакция, искавшая только
    `spa_core.alerts.x`, объявила сиротами `morning_digest` и `portfolio_health`,
    которые вызываются обёрткой и plist'ом — ложная находка, пойманная сверкой
    ДО публикации.
    """
    texts = _tree_texts()
    found = set()
    for sub in _DIRS:
        d = _ROOT / sub
        if not d.exists():
            continue
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_"):
                continue
            if not has_entrypoint(f.read_text(encoding="utf-8", errors="replace")):
                continue
            rel = str(f.relative_to(_ROOT))
            if not any(f.stem in body for path, body in texts.items() if path != rel):
                found.add(rel)
    return found


def test_census_is_not_vacuous():
    """Без этого «сирот нет» значило бы «сканер ничего не нашёл»."""
    total = sum(1 for sub in _DIRS for f in (_ROOT / sub).glob("*.py")
                if not f.name.startswith("_")
                and has_entrypoint(f.read_text(encoding="utf-8", errors="replace")))
    assert total >= 50, f"модулей с точкой входа всего {total} — скан сузился"


def test_no_new_guard_module_is_left_unwired():
    new = sorted(_census() - KNOWN_UNWIRED)
    assert not new, (
        f"новый сторож с точкой входа, которого никто не зовёт: {new}. "
        "Написать проверку и не позвать её — то же, что не написать: "
        "apy_spike_monitor так пропустил всплеск 9.2 % при пороге 8 %. "
        "В KNOWN_UNWIRED НЕ добавлять — подключить или вывести карточкой.")


def test_fixed_modules_leave_the_census():
    fixed = sorted(KNOWN_UNWIRED - _census())
    assert not fixed, (
        f"эти модули больше не сироты: {fixed} — убери их из KNOWN_UNWIRED, "
        "иначе список перестанет что-либо значить.")


def test_the_spike_monitor_case_is_pinned():
    """Не «какой-нибудь» сирота: у этого верный порог и пропущенное срабатывание."""
    from spa_core.alerts.apy_spike_monitor import SPIKE_THRESHOLDS
    assert SPIKE_THRESHOLDS["compound_v3"] == 8.0
    assert 9.2007 > SPIKE_THRESHOLDS["compound_v3"], (
        "показание 25.08 перестало превышать порог — перепроверь разбор")


def test_detector_needs_an_entrypoint_not_just_a_file():
    """Библиотека без точки входа сиротой не считается — её зовут импортом."""
    assert has_entrypoint("if __name__ == '__main__':\n    main()\n")
    assert has_entrypoint("def main(argv=None):\n    return 0\n")
    assert not has_entrypoint("def helper():\n    return 1\n")
