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

import ast
import re

import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DIRS = ("spa_core/alerts", "spa_core/monitoring", "spa_core/governance")

#: Перепись на 2026-08-29. Каждый — кандидат «подключить или вывести».
#: Найдено УЖЕСТОЧЕНИЕМ детектора 30.08, а не написано в этот день.
#:
#: Пока детектор искал имя во всём тексте, `golive_checker_hy` выглядел
#: подключённым из-за ОДНОЙ фразы в докстроке соседа: «Аналог
#: golive_checker_hy.py для Engine B». Настоящих вызовов нет ни одного.
#:
#: Это переякорение после починки сторожа, а не ослабление: детектор стал
#: строже, перепись выросла на пред-существовавшую сироту, которой он раньше
#: не видел. Карточка на подключение —
#: `agent-golive-checker-hy-sirota-naidena-uzhestocheniem`.
#: Правило «в KNOWN_UNWIRED не добавлять» остаётся в силе для НОВЫХ модулей.
#:
#: 2026-10-27 (цикл #958, ADR-835) — ВТОРОЕ переякорение, той же природы и по
#: тому же разрешению. Детектор перестал считать проводкой ПУТЬ ТЕСТ-ФАЙЛА,
#: написанный внутри чужого текста, и на этом вскрылась сирота, которой он не
#: видел НИ ОДНОГО дня: `live_registry_scene_census` родился 23.10 тем же
#: коммитом (`1f56210e0`), что и `scripts/ci_control_weights.json`, и его
#: единственным «вызывающим» была строка таблицы весов
#: `"spa_core/tests/test_live_registry_scene_census.py": 68.174`.
#: Карточка на подключение —
#: `inbox-live-registry-scene-census-sirota-vskryt.md`.
_FOUND_BY_STRICTER_DETECTOR = {
    "spa_core/monitoring/golive_checker_hy.py",
    "spa_core/monitoring/live_registry_scene_census.py",
}

KNOWN_UNWIRED = _FOUND_BY_STRICTER_DETECTOR | {
    "spa_core/alerts/adaptive_monitor.py",
    "spa_core/monitoring/arbitrum_gas_monitor.py",
    "spa_core/monitoring/data_freshness_monitor.py",
    "spa_core/monitoring/findings_bridge_c125.py",
    "spa_core/monitoring/golive_checker_lp.py",
    "spa_core/monitoring/optimism_gas_monitor.py",
    # `slo_proposal.py` УШЁл из переписи 26.10 (ADR-814): его зовёт
    # `slo_keepability._derived` — правило «какой срок физически возможен»
    # получило читателя, и второй копии правила в дереве нет. Храповик по
    # построению может только убывать, и это его убыль.
    "spa_core/monitoring/stalled_run_diagnosis.py",
    "spa_core/monitoring/unified_gas_monitor.py",
    "spa_core/governance/cpa_governance_watcher.py",
}


def has_entrypoint(text: str) -> bool:
    return "__main__" in text or "def main(" in text


def _code_only(text: str) -> str:
    """Текст .py БЕЗ прозы: докстроки и комментарии вырезаны.

    Детектор искал имя модуля во ВСЁМ тексте, и упоминание
    `slo_proposal.architect_floor` в ДОКСТРОКЕ чужого скрипта объявило сироту
    «подключённой»: сторож сам себя ослепил чужой прозой. Третий случай этого
    класса за сутки — проводка проверяется формой вызова, а не появлением имени
    в тексте.

    Не-Python оставляем как есть: обёртка `.sh`, plist и манифест ссылаются на
    модуль именно строкой, и там имя — это и есть вызов.

    Комментарии режутся грубо (`#` до конца строки), в том числе внутри строк.
    Ошибка идёт в сторону «меньше упоминаний» ⇒ БОЛЬШЕ сирот в переписи —
    fail-CLOSED, как и положено сторожу.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    drop: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            d = body[0]
            drop.update(range(d.lineno, (d.end_lineno or d.lineno) + 1))
    kept = ["" if (i + 1) in drop else re.sub(r"#.*$", "", line)
            for i, line in enumerate(text.splitlines())]
    return "\n".join(kept)


#: Путь ТЕСТ-ФАЙЛА, написанный внутри чужого текста.
#:
#: Форма закрытая и узкая: `test_<имя>.py` с необязательным каталогом впереди.
#: Ошибка идёт в сторону «меньше упоминаний» ⇒ БОЛЬШЕ сирот в переписи —
#: fail-CLOSED, тот же знак, что у `_code_only`.
_TEST_PATH = re.compile(r"[\w./-]*\btest_[A-Za-z0-9_]+\.py")


def _without_test_paths(text: str) -> str:
    """Текст без ПУТЕЙ ТЕСТ-ФАЙЛОВ: имя сторожа в них — не вызов.

    Четвёртый случай одного класса («доказательство слабее вызова»): докстринг
    (#255), комментарий (#227), текст сообщения (#278), груз пуша (#379) — и
    теперь ПУТЬ ТЕСТ-ФАЙЛА в чужой таблице. Файл `_tree_texts` отбрасывает по
    каталогу (`"/tests/" in rel`), то есть тест как ФАЙЛ вызывающим не
    считается; но ИМЯ тест-файла, написанное ВНУТРИ не-теста, проскакивало
    подстрокой, потому что стем сторожа — его часть
    (`spa_core/tests/test_adaptive_monitor.py` содержит `adaptive_monitor`).

    Замер 2026-10-27 на `origin/main` 599c8ed4f: таблица весов CI
    `scripts/ci_control_weights.json` (родилась 23.10, коммит `1f56210e0`,
    2030 путей тест-файлов) объявила «подключёнными» ПЯТЬ сторожей, и у всех
    пяти это было ЕДИНСТВЕННОЕ доказательство. Четверо из пяти числились в
    `KNOWN_UNWIRED`, поэтому `test_fixed_modules_leave_the_census` покраснел и
    СВОИМ ЖЕ текстом потребовал убрать их из списка — то есть сторож
    предписывал снять с учёта четыре настоящие сироты НАВСЕГДА (список может
    только убывать). Пятая (`live_registry_scene_census`) не числилась нигде и
    не была видна вовсе — fail-OPEN, тише красного теста.

    Запуск теста вызовом сторожа не является и по смыслу: `pytest
    spa_core/tests/test_adaptive_monitor.py` исполняет ТЕСТ, а вопрос
    храповика — включён ли сам сторож в проводку системы (урок #144).
    """
    return _TEST_PATH.sub("", text)


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
                body = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            out[rel] = _without_test_paths(
                _code_only(body) if f.suffix == ".py" else body)
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
        "В KNOWN_UNWIRED НЕ добавлять — подключить или вывести карточкой. "
        "Исключение ровно одно и оно названо: если сироту вскрыло УЖЕСТОЧЕНИЕ "
        "детектора, это переякорение — заводится отдельным множеством "
        "`_FOUND_BY_STRICTER_DETECTOR` с датой, причиной и карточкой.")


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


def test_prose_is_not_wiring():
    """Положительный контроль к починке 30.08: упоминание в докстроке — не вызов.

    Ровно так `slo_proposal` объявлялся «починенным», а `golive_checker_hy`
    прятался в переписи: у обоих единственное упоминание было прозой.
    """
    src = '"""Аналог zzz_orphan_module.py для Engine B."""\nx = 1  # и ещё zzz_orphan_module\n'
    assert "zzz_orphan_module" not in _code_only(src), (
        "проза снова читается как проводка — сторож слепнет от чужой докстроки")


def test_a_real_call_survives_the_prose_strip():
    """Обратный контроль: настоящий импорт вырезать нельзя."""
    src = '"""Докстрока про zzz_orphan_module."""\nfrom spa_core.x import zzz_orphan_module\n'
    assert "zzz_orphan_module" in _code_only(src)


def test_a_test_file_path_is_not_wiring():
    """Положительный контроль ADR-835: авария 23.10 воспроизводится ДОСЛОВНО.

    Строка взята из `scripts/ci_control_weights.json` без единой правки. До
    починки стем `adaptive_monitor` был в ней виден подстрокой, и сторож,
    которого не зовёт никто, числился подключённым.
    """
    row = '  "spa_core/tests/test_adaptive_monitor.py": 0.419,\n'
    assert "adaptive_monitor" in row, "строка аварии перестала нести стем"
    assert "adaptive_monitor" not in _without_test_paths(row), (
        "путь тест-файла снова читается как проводка — ровно та форма, "
        "которой таблица весов CI объявила пять сторожей подключёнными")


def test_a_real_call_on_the_same_line_survives_the_test_path_strip():
    """Обратный контроль: вырезается ПУТЬ ТЕСТА, а не строка с ним.

    Без этого плеча починка могла бы съесть настоящий вызов, стоящий рядом, —
    и сторож объявил бы сиротой живой модуль. Ошибаться он обязан в сторону
    находки, но не в сторону выдумки.
    """
    line = ('python3 -m spa_core.alerts.adaptive_monitor && '
            'pytest spa_core/tests/test_adaptive_monitor.py\n')
    kept = _without_test_paths(line)
    assert "spa_core.alerts.adaptive_monitor" in kept, (
        "вырезан настоящий вызов — полоса реза шире предмета")
    assert "tests/test_adaptive_monitor.py" not in kept


def test_the_weights_table_no_longer_wires_the_five():
    """Поведенческое плечо НА ЖИВОМ ДЕРЕВЕ: вердикт меряется, а не заявляется.

    Контроль детали (две проверки выше) зелен и на мёртвой проводке — урок
    #144. Здесь спрашивается НАСТОЯЩАЯ перепись: пятеро обязаны быть в ней, и
    `scripts/ci_control_weights.json` обязан оставаться их единственным
    упоминанием (иначе утверждение стухло бы молча, когда появится настоящий
    вызывающий, — и тогда модуль честно уйдёт из `KNOWN_UNWIRED`).
    """
    five = {
        "spa_core/alerts/adaptive_monitor.py",
        "spa_core/monitoring/data_freshness_monitor.py",
        "spa_core/monitoring/live_registry_scene_census.py",
        "spa_core/monitoring/unified_gas_monitor.py",
        "spa_core/governance/cpa_governance_watcher.py",
    }
    present = {m for m in five if (_ROOT / m).exists()}
    assert present == five, f"модули переписи пропали из дерева: {five - present}"
    census = _census()
    assert five <= census, (
        "пятеро снова числятся подключёнными: "
        f"{sorted(five - census)}")
    # Вернуться в ПЕРЕПИСЬ и СТОЯТЬ НА УЧЁТЕ — разные утверждения, и второе
    # мутация сняла бы молча: имя, выпавшее из `_FOUND_BY_STRICTER_DETECTOR`,
    # ушло бы в «новые сироты», а тот тест КРАСЕН по другой причине
    # (`step_time_drift`) — то есть сигнал был бы замаскирован чужим красным.
    # Замер мутациями ADR-835 нашёл ровно это: мутант 5/11 ВЫЖИЛ.
    assert five <= KNOWN_UNWIRED, (
        "сторож вернулся в перепись, но на учёте не стои́т: "
        f"{sorted(five - KNOWN_UNWIRED)}")
