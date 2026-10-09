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
        # `--rootdir` добавлен циклом #747: якорь ЗДЕСЬ уже был (`cwd=tmp_path` —
        # один из трёх измеренных #382), но линт `test_child_pytest_rootdir.py`
        # читает ARGV и `cwd` не видит, поэтому на `main` он КРАСНЫЙ (прогон
        # 36852036618, обе ноги). Утверждение теста не ослаблено и не сужено
        # (инв. #16) — добавлен ровно тот флаг, который требует сообщение линта.
        [sys.executable, "-m", "pytest", str(tmp_path), "-q", "-p", "no:randomly",
         "-p", "no:cacheprovider", "--rootdir", str(tmp_path),
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
        if not _resumes_after_failure(s.get("if"))
    ]
    assert not naked, (
        "шаг после первого набора без условия возобновления будет ПРОПУЩЕН при "
        "падении предыдущего, и его вердикт станет не красным, а отсутствующим "
        f"(ADR-474, замер: так неделями не исполнялись «scripts/ gate tests» и "
        f"«Pre-deploy checks»). Без условия: {naked}"
    )


#: Условия, при которых шаг исполняется ПОСЛЕ ПАДЕНИЯ предыдущего. Перечень
#: ЗАКРЫТ литералом: подстрочная сверка («есть слово cancelled») приняла бы любое
#: выражение с этим токеном, в том числе `cancelled()` без отрицания (ADR-333).
_RESUME_CONDITIONS: tuple[str, ...] = ("!cancelled()", "always()")

#: Шаг, которому `always()` РАЗРЕШЁН, — ровно один и назван ИМЕНЕМ, не подстрокой.
#: Разрешение куплено замером, а не доводом (ADR-679, заказ G109 п. 1): цена этого
#: шага 0…7 с, медиана 2 (36 наблюдений), запись в хранилище 0,7…5,3 МБ сжатой,
#: а доля уцелевшей записи на пути ОТМЕНЫ — 2 из 150 при 16 из 16 на пути отказа.
#: Отмена есть ГЛАВНЫЙ путь прогона (215 из 300), и `!cancelled()` не покрывает
#: его ПО ПОСТРОЕНИЮ. Добавление второго имени сюда — отдельное решение с
#: отдельным замером цены, а не правка списка.
_ALWAYS_ALLOWED_STEPS: tuple[str, ...] = ("Upload test records (junit + stream)",)


def _normalise_if(raw: object) -> str:
    """Условие без обёртки `${{ }}` и пробелов. Пустая строка — условия нет."""
    text = str(raw or "").strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2].strip()
    return "".join(text.split())


def _resumes_after_failure(raw: object) -> bool:
    return _normalise_if(raw) in _RESUME_CONDITIONS


def test_only_the_record_upload_may_carry_always_and_working_steps_may_not() -> None:
    """`always()` запрещён ПОШАГОВО, а не по токену на весь файл.

    **Что здесь изменилось и почему (цикл #817, ADR-679, инв. #16 — правка теста
    намеренная и обоснована здесь же).** Прежняя редакция запрещала `always()`
    где угодно в `test.yml` с доводом: такой шаг доигрывал бы 120-минутный прогон
    и `cancel-in-progress` перестал бы разгружать очередь (затор из 166 прогонов,
    замер 12.09). Довод ВЕРЕН для шагов, которые ДЕЛАЮТ РАБОТУ, и ПУСТ для шага
    выгрузки записи: его цена измерена и равна 0…7 с, медиана 2 с (36 наблюдений)
    против ноги тестов 194…229 мин. Доигрывать там нечего, а под прежним запретом
    запись теряли 148 отменённых прогонов из 150.

    Запрет поэтому не снят, а СУЖЕН до предмета, и проверка стала СИЛЬНЕЕ: раньше
    она вообще не отличала шаг работы от шага выгрузки, теперь называет оба.
    Контроль в обе стороны — ниже и в `test_always_on_a_working_step_is_caught`.
    """
    steps = _load_test_job_steps()
    offenders = []
    for step in steps:
        if _normalise_if(step.get("if")) != "always()":
            continue
        name = str(step.get("name") or step.get("uses") or "<без имени>").strip()
        does_work = "run" in step or name not in _ALWAYS_ALLOWED_STEPS
        if does_work:
            offenders.append(name)
    assert not offenders, (
        "`always()` исполняет шаг и при отмене джобы. Работающему шагу это "
        "возвращает затор очереди (замер 12.09, 166 прогонов): он доигрывал бы "
        "вытесненный прогон целиком. Разрешён он РОВНО на шаге выгрузки записи, "
        f"чья цена измерена секундами. Найдено на работающих шагах: {offenders}"
    )
    # Обратная сторона того же утверждения: разрешение не должно оказаться пустым.
    # Если шага выгрузки с `always()` в воркфлоу нет, значит запись снова теряется
    # на пути отмены — и тест обязан сказать это, а не промолчать (ADR-679).
    allowed = [str(s.get("name") or "").strip() for s in steps
               if _normalise_if(s.get("if")) == "always()"]
    assert allowed == list(_ALWAYS_ALLOWED_STEPS), (
        "шаг выгрузки записи обязан нести `always()`: под `!cancelled()` запись "
        "не покидает раннер на пути ОТМЕНЫ (измерено: 2 прогона из 150), а отмена "
        f"есть главный путь прогона. Найдено: {allowed}"
    )


def test_every_other_condition_resumes_after_failure_but_not_after_cancellation() -> None:
    """У всех прочих шагов условие остаётся `!cancelled()` — и это проверяется.

    Сужение запрета выше не должно превратиться в «условие может быть любым»:
    шаг без условия возобновления после падения ПРОПУСКАЕТСЯ, и его вердикт
    становится не красным, а отсутствующим (ADR-474).
    """
    steps = _load_test_job_steps()
    conditions = [(str(s.get("name") or s.get("uses") or "<без имени>").strip(),
                   _normalise_if(s.get("if")))
                  for s in steps if s.get("if") is not None]
    assert conditions, "НЕ ИЗМЕРЕНО: условий `if:` в джобе `test` не нашлось вовсе"
    wrong = [(n, c) for n, c in conditions if c not in _RESUME_CONDITIONS]
    assert not wrong, (
        f"условие, не выражающее «после падения исполнись»: {wrong}"
    )
    # Все, кроме разрешённого шага, несут именно `!cancelled()`.
    stray = [(n, c) for n, c in conditions
             if c == "always()" and n not in _ALWAYS_ALLOWED_STEPS]
    assert not stray, f"`always()` просочился на чужой шаг: {stray}"


def test_always_on_a_working_step_is_caught() -> None:
    """Положительный контроль СУЖЕНИЯ: `always()` на шаге с `run:` обязан краснеть.

    Без этого теста сужение запрета было бы неотличимо от его снятия.
    """
    scene = [
        {"name": "Run spa_core unit tests", "if": "${{ always() }}",
         "run": "python -m pytest spa_core/tests/"},
        {"name": "Upload test records (junit + stream)", "if": "${{ always() }}",
         "uses": "actions/upload-artifact@v4"},
    ]
    offenders = [str(s.get("name")) for s in scene
                 if _normalise_if(s.get("if")) == "always()"
                 and ("run" in s or str(s.get("name")) not in _ALWAYS_ALLOWED_STEPS)]
    assert offenders == ["Run spa_core unit tests"], (
        "правило обязано ловить `always()` на работающем шаге и пропускать его "
        f"на шаге выгрузки записи; найдено: {offenders}"
    )
    # И обратно: шаг выгрузки БЕЗ `always()` обязан быть находкой.
    without = [s for s in scene if s.get("name") in _ALWAYS_ALLOWED_STEPS
               and _normalise_if(s.get("if")) != "always()"]
    assert not without
    renamed = [{"name": "Upload coverage", "if": "${{ always() }}",
                "uses": "actions/upload-artifact@v4"}]
    assert [str(s.get("name")) for s in renamed
            if _normalise_if(s.get("if")) == "always()"
            and str(s.get("name")) not in _ALWAYS_ALLOWED_STEPS] == ["Upload coverage"], (
        "разрешение привязано к ИМЕНИ шага, а не к подстроке «Upload»")


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
