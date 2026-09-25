# LLM_FORBIDDEN
"""Сторож на ФОРМУ отказа сторожа зависаний (ADR-474, цикл #694).

**Авария, которую воспроизводит этот файл.** `.github/workflows/test.yml` гонял
`spa_core/tests/` с `--timeout=180 --timeout-method=thread`. Шаг месяц докладывал
`failure`, и это читалось как «тесты падают». Замер прогона **36119204905**
(`f1f813226`, Python 3.11) говорит другое: лог кончается штампом
``+++++++ Timeout +++++++`` и стеком, **сводки pytest в нём нет ни одной**, прогресс
доехал до ``[ 10%]`` за 1732 с. Из 106 810 собранных тестов ≈96 000 не получили
никакого вердикта. То есть шаг не падал, а **обрывался**, и «не измерено» выдавалось
за «красное» — прямое нарушение инварианта #17.

Причина механическая: `thread` — не «свалить тест», а таймер, который печатает стеки
и зовёт ``os._exit(1)``, убивая СЕССИЮ. `signal` (SIGALRM) поднимает исключение
В ТЕСТЕ: виновник называется, сессия доходит до конца и печатает сводку. Именно это и
было объявлено намерением в самом воркфлоу («a per-test wedge backstop so a hung test
fails-fast + **NAMED**») — механизм противоречил своей же объявленной цели.

**Два разных вопроса — два разных теста, и ни один не заменяет другого:**

| Вопрос | Кто отвечает здесь |
|---|---|
| Правда ли `thread` убивает сессию, а `signal` — нет? | дифференциальный контроль на ЖИВОМ pytest |
| Не вернулся ли `thread` в воркфлоу и читает ли кто-то junit-запись? | сторожа над `.github/workflows/` |

Первый мерит поведение библиотеки (оно могло измениться с версией), второй — проводку.
Зелёный ответ на один не есть ответ на другой.

**Отсутствие `pytest-timeout` — ТРЕТИЙ ИСХОД, а не скип.** Скип здесь сделал бы
«не измерено» неотличимым от «прошло» — ровно тот дефект, против которого файл написан
(`.claude/rules/deployment.md`, «Класс шире, чем pid»).
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"

# Порог внутреннего прогона и длительность жжения. Сознательно крошечные: предмет
# замера — ФОРМА отказа, а не его порог, и платить за неё секундами незачем.
_INNER_TIMEOUT_S = 1
_BURN_S = 5

_SUMMARY_RE = re.compile(r"\d+ passed")
_TIMEOUT_STAMP = "Timeout"


def _tool_present(name: str) -> bool:
    """Есть ли модуль. ОТДЕЛЬНЫЙ вопрос от «успешен ли прогон» (инв. #17)."""
    return importlib.util.find_spec(name) is not None


def _make_case(tmp_path: Path) -> Path:
    """Дерево из трёх файлов; дорогой — ПЕРВЫЙ по алфавиту, как в настоящей аварии.

    Цена платится в `setUpClass`, а не в теле теста: именно так падал
    `test_constitution_right_to_fix.py:390` (`cls.doc = rsc.measure(...)`).
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "test_a_expensive.py").write_text(textwrap.dedent(f'''
        import time, unittest

        def _burn(seconds):
            """Жжёт в чистом Python: управление возвращается в интерпретатор постоянно,
            поэтому SIGALRM доставляется. Так же ведёт себя настоящая перепись —
            55 276 коротких ast.parse, а не один длинный вызов в C."""
            end = time.time() + seconds
            n = 0
            while time.time() < end:
                n += 1
            return n

        class ExpensiveSetUpClass(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                cls.n = _burn({_BURN_S})

            def test_uses_the_expensive_fixture(self):
                self.assertGreater(self.n, 0)
    ''').strip(), encoding="utf-8")
    (tmp_path / "test_b_cheap.py").write_text(
        "def test_cheap_one(): assert True\ndef test_cheap_two(): assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "test_c_cheap.py").write_text(
        "def test_cheap_three(): assert True\n", encoding="utf-8",
    )
    return tmp_path


def _run(tmp_path: Path, method: str) -> subprocess.CompletedProcess[str]:
    junit = tmp_path / f"junit-{method}.xml"
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "-q", "-p", "no:randomly",
         "-p", "no:cacheprovider",
         f"--timeout={_INNER_TIMEOUT_S}", f"--timeout-method={method}",
         f"--junitxml={junit}"],
        cwd=tmp_path, capture_output=True, text=True, timeout=300,
    )


@pytest.fixture(scope="module")
def _timeout_plugin_present() -> bool:
    if not _tool_present("pytest_timeout"):
        pytest.fail(
            "НЕ ИЗМЕРЕНО: pytest-timeout отсутствует, поэтому форму отказа сторожа "
            "зависаний проверить нечем. Скип здесь запрещён: он сделал бы «не измерено» "
            "неотличимым от «прошло» — ровно тем дефектом, против которого файл написан. "
            "CI ставит pytest-timeout в шаге Install test dependencies.",
        )
    return True


# ── дифференциальный контроль на ЖИВОМ pytest ─────────────────────────────────

def test_thread_method_kills_the_session_and_prints_no_summary(
    tmp_path: Path, _timeout_plugin_present: bool,
) -> None:
    """Воспроизведение аварии 25.09 дословно: обрыв без сводки.

    Это ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: он обязан остаться зелёным, пока `thread` ведёт себя
    так, как вёл в CI. Покраснеет он, если pytest-timeout изменит поведение — и тогда
    правку воркфлоу надо будет перемерить, а не доверять этому файлу.
    """
    result = _run(_make_case(tmp_path), "thread")
    output = result.stdout + result.stderr

    assert _TIMEOUT_STAMP in output, f"штампа таймаута нет вовсе:\n{output[-2000:]}"
    assert not _SUMMARY_RE.search(output), (
        "у `thread` сводки быть НЕ ДОЛЖНО — именно её отсутствие и есть авария "
        f"«≈96 000 тестов без вердикта»:\n{output[-2000:]}"
    )
    assert "test_cheap_three" not in output, (
        "дешёвые тесты после дорогого не должны были выполниться: сессия убита"
    )
    assert not (tmp_path / "junit-thread.xml").exists(), (
        "убитая сессия junit-запись не пишет — на этом и стоит вердикт «НЕ ИЗМЕРЕНО»"
    )


def test_signal_method_names_the_offender_and_finishes_the_session(
    tmp_path: Path, _timeout_plugin_present: bool,
) -> None:
    """Обратная сторона того же замера: виновник назван, остальные измерены."""
    result = _run(_make_case(tmp_path), "signal")
    output = result.stdout + result.stderr

    assert _SUMMARY_RE.search(output), (
        f"у `signal` сессия обязана дойти до сводки:\n{output[-2000:]}"
    )
    assert "test_uses_the_expensive_fixture" in output, (
        f"виновник обязан быть НАЗВАН по имени:\n{output[-3000:]}"
    )
    assert result.returncode != 0, "просроченный тест обязан остаться КРАСНЫМ"
    junit = tmp_path / "junit-signal.xml"
    assert junit.exists(), "дошедшая до конца сессия обязана оставить junit-запись"
    assert "test_cheap_three" in junit.read_text(encoding="utf-8"), (
        "тесты ПОСЛЕ просроченного обязаны получить вердикт — в этом весь смысл правки"
    )


def test_the_two_methods_differ_exactly_in_whether_a_verdict_survives(
    tmp_path: Path, _timeout_plugin_present: bool,
) -> None:
    """Контроль на сам контроль: разница между методами не выдумана, а измерена.

    Если оба метода однажды начнут вести себя одинаково, два теста выше могли бы
    оба остаться зелёными по случайности формулировок. Здесь сравниваются ИСХОДЫ.
    """
    thread_dir = _make_case(tmp_path / "thread"); signal_dir = _make_case(tmp_path / "signal")
    thread_has_record = (_run(thread_dir, "thread"), (thread_dir / "junit-thread.xml").exists())[1]
    signal_has_record = (_run(signal_dir, "signal"), (signal_dir / "junit-signal.xml").exists())[1]
    assert (thread_has_record, signal_has_record) == (False, True), (
        "предмет правки — именно это различие: thread не оставляет вердикта, signal оставляет"
    )


# ── сторожа над проводкой воркфлоу ────────────────────────────────────────────

def _workflow_texts() -> dict[str, str]:
    assert _WORKFLOWS.is_dir(), f"НЕ ИЗМЕРЕНО: нет каталога {_WORKFLOWS}"
    texts = {p.name: p.read_text(encoding="utf-8") for p in sorted(_WORKFLOWS.glob("*.yml"))}
    assert texts, f"НЕ ИЗМЕРЕНО: в {_WORKFLOWS} не нашлось ни одного *.yml"
    return texts


def _load_test_job_steps() -> list[dict]:
    """Шаги джобы `test` из `test.yml`. Разбор настоящий (`yaml.safe_load`), не самодельный.

    Импорт локальный и fail-CLOSED — по образцу `test_ci_covers_every_test_dir.py`:
    верхнеуровневый `import yaml` уронил бы СБОРКОЙ весь файл, то есть заодно и восемь
    тестов, которым pyyaml не нужен, а «не измерено» стало бы неотличимо от «сломано».
    """
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover — в CI pyyaml установлен всегда
        pytest.fail(
            "НЕ ИЗМЕРЕНО: для разбора test.yml нужен pyyaml (он есть в списке "
            f"зависимостей CI, шаг Install test dependencies): {exc}",
        )
    doc = yaml.safe_load((_WORKFLOWS / "test.yml").read_text(encoding="utf-8")) or {}
    steps = doc.get("jobs", {}).get("test", {}).get("steps")
    assert steps, "НЕ ИЗМЕРЕНО: в test.yml не разобрались шаги джобы `test`"
    return steps


def test_no_workflow_uses_the_session_killing_timeout_method() -> None:
    offenders = {
        name: [ln for ln in text.splitlines()
               if "--timeout-method=thread" in ln and not ln.lstrip().startswith("#")]
        for name, text in _workflow_texts().items()
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, (
        "`--timeout-method=thread` убивает сессию: вместо вердикта о наборе получается "
        "обрыв, и «не измерено» становится неотличимо от «красно» (инв. #17, ADR-474). "
        f"Нужен `signal`. Найдено: {offenders}"
    )


def test_every_pytest_step_records_its_own_run() -> None:
    """Без своей записи прогона третий исход неразличим по построению."""
    text = (_WORKFLOWS / "test.yml").read_text(encoding="utf-8")
    steps = [b for b in re.split(r"\n      - name: ", text)[1:] if "-m pytest" in b]
    assert steps, "НЕ ИЗМЕРЕНО: в test.yml не нашлось ни одного шага с pytest"
    missing = [s.splitlines()[0] for s in steps if "--junitxml" not in s]
    assert not missing, f"шаги pytest без --junitxml (вердикт о них недостижим): {missing}"


def test_every_recorded_run_has_a_reader() -> None:
    """Артефакт без читателя — та же слепота, что и его отсутствие."""
    text = (_WORKFLOWS / "test.yml").read_text(encoding="utf-8")
    written = set(re.findall(r"--junitxml=(\S+)", text))
    read = set(re.findall(r"ci_verdict\.py\s+(\S+)", text))
    assert written, "НЕ ИЗМЕРЕНО: junit-записей в test.yml нет вовсе"
    assert not (written - read), (
        f"junit-запись пишется, но никто её не читает — вердикта не будет: {written - read}"
    )
    assert not (read - written), (
        f"вердикт читает запись, которую никто не пишет ⇒ вечное «НЕ ИЗМЕРЕНО»: {read - written}"
    )


def test_every_step_after_the_first_suite_carries_the_resume_condition() -> None:
    """Найдено КОНТРОЛЕМ НА КОНТРОЛЬ (цикл #694): снятие `if:` не краснило ничего.

    Первая редакция сторожа ниже проверяла лишь ФОРМУ условия у тех шагов, где оно
    есть. Поэтому молчаливое удаление строки `if:` вернуло бы ровно ту слепоту, ради
    которой правка и делалась («шаг пропущен после падения предыдущего ⇒ вердикт не
    красный, а ОТСУТСТВУЮЩИЙ»), и ни один тест не краснел. Дифференциальный контроль
    это и показал: 8 passed при снятом условии.
    """
    steps = _load_test_job_steps()
    names = [s.get("name") or s.get("uses") or "<без имени>" for s in steps]
    first_suite = next(
        (i for i, s in enumerate(steps) if "-m pytest" in str(s.get("run", ""))), None,
    )
    assert first_suite is not None, "НЕ ИЗМЕРЕНО: шага с pytest в test.yml нет вовсе"

    naked = [
        names[i] for i, s in enumerate(steps[first_suite + 1:], start=first_suite + 1)
        if "cancelled()" not in str(s.get("if", ""))
    ]
    assert not naked, (
        "шаг после первого набора без условия возобновления будет ПРОПУЩЕН при "
        "падении предыдущего, и его вердикт станет не красным, а отсутствующим "
        f"(ADR-474, замер: так неделями не исполнялись «scripts/ gate tests» и "
        f"«Pre-deploy checks»). Без условия: {naked}"
    )


def test_steps_resume_after_failure_but_not_after_cancellation() -> None:
    """`!cancelled()`, а НЕ `always()` — и различие здесь не стилистическое.

    Шаги с `always()` исполняются и при ОТМЕНЕ джобы, поэтому вытесненный пуш
    доигрывал бы 120-минутный прогон, и `cancel-in-progress` перестал бы разгружать
    очередь — тот самый затор из 166 прогонов (замер 12.09, описан в шапке test.yml).
    `!cancelled()` даёт ровно нужное: «после ПАДЕНИЯ да, после ОТМЕНЫ нет».
    """
    text = (_WORKFLOWS / "test.yml").read_text(encoding="utf-8")
    conditions = re.findall(r"^\s+if: (.+)$", text, flags=re.M)
    assert conditions, "НЕ ИЗМЕРЕНО: условий `if:` в test.yml не нашлось вовсе"
    always = [c for c in conditions if "always()" in c]
    assert not always, (
        "`always()` исполняет шаг и при отмене джобы, отменяя смысл "
        f"`cancel-in-progress`; нужно `!cancelled()`. Найдено: {always}"
    )
    assert all("cancelled()" in c for c in conditions), (
        f"условие, не выражающее «после падения да, после отмены нет»: {conditions}"
    )


def test_the_heavy_step_has_an_outer_wedge_bound() -> None:
    """`signal` не прерывает блокировку в C-коде — внешняя граница обязана остаться."""
    text = (_WORKFLOWS / "test.yml").read_text(encoding="utf-8")
    block = text.split("- name: Run spa_core unit tests", 1)
    assert len(block) == 2, "НЕ ИЗМЕРЕНО: шаг `Run spa_core unit tests` не найден"
    head = block[1].split("run:", 1)[0]
    assert "timeout-minutes:" in head, (
        "у тяжёлого шага обязана быть внешняя граница зависания: SIGALRM не достаёт до "
        "блокировки в C-коде (замер #59, `_ssl__SSLSocket_read`), и без границы джоба "
        "висела бы до умолчания Actions в 360 мин"
    )
